#!/usr/bin/env python3
"""
PTY wrapper that auto-accepts prompts and re-prompts Claude Code.

Used by the "yolo" modifier to auto-accept plan approval and permission prompts.
Used by the "loop" modifier to periodically re-prompt Claude when idle.

All I/O passes through transparently. The user can still type normally.
During the accept delay, keystrokes cancel auto-accept and forward to the child.
"""

import glob
import os
import sys
import pty
import re
import fcntl
import logging
import select
import signal
import termios
import time
import tty
import errno

# ─── Debug logging ───────────────────────────────────────────────────
# Writes to /tmp/auto-accept.log so we can diagnose without breaking the TUI.
# Set AUTO_ACCEPT_DEBUG=1 to enable.
DEBUG = os.environ.get("AUTO_ACCEPT_DEBUG", "0") == "1"
if DEBUG:
    logging.basicConfig(
        filename="/tmp/auto-accept.log",
        level=logging.DEBUG,
        format="%(asctime)s %(message)s",
    )
else:
    logging.basicConfig(level=logging.CRITICAL)

log = logging.getLogger("auto-accept")


# ─── Trigger patterns ────────────────────────────────────────────────
# Each pattern is matched against ANSI-stripped terminal output.
# On match, we wait briefly for the TUI to redraw, then send the
# appropriate keystroke to accept.

# Plan approval triggers — active when CLAUDIUS_YOLO=1.
# Shift+Tab is bound to "yes-accept-edits" in the plan component.
# (Enter rejects the plan in the current Claude Code UI.)
PLAN_TRIGGERS = [
    "needs your approval",
]

# Permission bypass triggers — also active when CLAUDIUS_YOLO=1.
# These accept via Enter (the desired option is already highlighted).
YOLO_TRIGGERS = [
    "Yes, and bypass permissions",
    "Yes, clear context",
]

YOLO_MODE = os.environ.get("CLAUDIUS_YOLO", "0") == "1"
LOOP_MODE = os.environ.get("CLAUDIUS_LOOP", "0") == "1"

# Triggers only fire in yolo mode. Loop-only mode does no auto-accepting.
ALL_TRIGGERS = (PLAN_TRIGGERS + YOLO_TRIGGERS) if YOLO_MODE else []

# Compiled regex to strip ANSI escape sequences before matching.
# Covers CSI sequences (with optional ? prefix), OSC sequences, and
# other common terminal escapes like \x1b= / \x1b> (keypad mode).
ANSI_RE = re.compile(
    r"\x1b\[[\?]?[0-9;]*[a-zA-Z]"   # CSI: \e[...X  or \e[?...X
    r"|\x1b\][^\x07]*\x07"           # OSC: \e]...\a
    r"|\x1b[()][0-9A-Za-z]"          # charset: \e(B, \e)0, etc.
    r"|\x1b[=>]"                     # keypad mode: \e= / \e>
)

# Cursor-forward sequences (\e[C, \e[1C, \e[nC) are used as visual
# spaces in Claude Code's TUI. Replace these with a real space BEFORE
# stripping other ANSI codes so word boundaries are preserved.
CURSOR_FWD_RE = re.compile(r"\x1b\[\d*C")

# Seconds to wait after detecting a trigger before sending Enter.
# Gives the TUI time to finish its redraw cycle.
REDRAW_DELAY = 0.5

# Seconds to wait before auto-accepting. Gives the user time to review
# the plan and intervene if needed. A system notification is sent at
# trigger time so the user has the full window to react.
ACCEPT_DELAY = 30

# Minimum seconds between consecutive auto-accepts (debounce).
# Prevents double-firing when the same prompt text appears in the redraw.
DEBOUNCE_INTERVAL = 3.0

# ─── Notification ───────────────────────────────────────────────────
# Writes to a host-mounted FIFO so the claudius host script can send
# OS-level notifications (osascript on macOS, notify-send on Linux).

NOTIFY_FIFO = "/tmp/claudius-notify"


def send_notification(message):
    """Write a notification line to the host-mounted FIFO (non-blocking)."""
    try:
        fd = os.open(NOTIFY_FIFO, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, (message + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass  # no reader, FIFO missing, or not mounted — silently skip


# ─── LOOP — periodic re-prompting ──────────────────────────────────
# When the "loop" modifier is active, auto-accept will periodically
# type a prompt into the Claude terminal when Claude goes idle.
# The prompt comes from either CLAUDIUS_LOOP_PROMPT env var or a
# LOOP.md file in /workspace (case-insensitive).

LOOP_FILE = "/workspace/LOOP.md"
LOOP_IDLE_THRESHOLD = 120    # seconds of output silence → Claude is idle
LOOP_DEFAULT_INTERVAL = 1800 # 30 minutes
LOOP_DEADLINE_FILE = "/tmp/claudius-loop-deadline"


def strip_ansi(text):
    """Remove ANSI escape codes from text for clean pattern matching."""
    text = CURSOR_FWD_RE.sub(" ", text)   # cursor-forward → space
    return ANSI_RE.sub("", text)


def matched_trigger(text):
    """Return the first matching trigger pattern, or None."""
    clean = strip_ansi(text)
    for pattern in ALL_TRIGGERS:
        if pattern in clean:
            return pattern
    return None


def is_plan_trigger(pattern):
    """True if the matched pattern requires Shift+Tab instead of Enter."""
    return pattern in PLAN_TRIGGERS


def copy_terminal_size(from_fd, to_fd):
    """Copy the terminal window size from one fd to another."""
    try:
        size = fcntl.ioctl(from_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(to_fd, termios.TIOCSWINSZ, size)
    except OSError:
        pass


def drain_child_output(master_fd, stdout_fd):
    """Drain pending child output, forwarding to the real terminal."""
    try:
        while True:
            r, _, _ = select.select([master_fd], [], [], 0.05)
            if not r:
                break
            chunk = os.read(master_fd, 4096)
            if not chunk:
                break
            os.write(stdout_fd, chunk)
    except OSError:
        pass


def parse_interval_line(line):
    """
    Parse a single line for a time interval.

    Supports:
      - Cron syntax:      */5 * * * *  →  300 (seconds)
      - Human-readable:   every 10 minutes  →  600
                          4 hours, then do X  →  14400
                          30 seconds  →  30

    Returns seconds (int) or None if no interval found.
    """
    line = line.strip()
    if not line:
        return None

    # ── Cron syntax (5 whitespace-separated fields) ──
    fields = line.split()
    if len(fields) >= 5:
        minute, hour = fields[0], fields[1]
        # All remaining fields must look like cron tokens
        cron_token = re.compile(r'^[\d\*/,-]+$')
        if all(cron_token.match(f) for f in fields[:5]):
            # */N in minute field → every N minutes
            m = re.match(r'^\*/(\d+)$', minute)
            if m:
                return int(m.group(1)) * 60
            # Fixed minute + */N in hour field → every N hours
            if re.match(r'^\d+$', minute):
                m = re.match(r'^\*/(\d+)$', hour)
                if m:
                    return int(m.group(1)) * 3600
            # Other valid cron → default interval (caller decides)
            return None

    # ── Human-readable: look for a number followed by a time unit ──
    m = re.search(
        r'(\d+)\s*'
        r'(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)',
        line, re.IGNORECASE,
    )
    if m:
        value = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith('s'):
            return value
        elif unit.startswith('m'):
            return value * 60
        elif unit.startswith('h'):
            return value * 3600
        elif unit.startswith('d'):
            return value * 86400

    return None


# Regex matching block delimiters: ===, ===idle===, ===60s===, ======31m===, etc.
# 3+ leading equals, optional spec (idle | NNs/m/h), 3+ trailing equals when spec present.
BLOCK_DELIMITER_RE = re.compile(r'^={3,}(?:(idle|\d+[smh])={3,})?$', re.IGNORECASE)


def parse_delimiter(line):
    """
    Parse a === block delimiter line.

    Returns (wait_type, wait_seconds) or None if the line is not a delimiter.
    wait_type: "idle" — wait until Claude is idle (120s silence)
               "timed" — wait a fixed number of seconds
               "interval" — wait using the global loop interval
    wait_seconds: None for idle/interval, int seconds for timed
    """
    m = BLOCK_DELIMITER_RE.match(line.strip())
    if not m:
        return None
    spec = m.group(1)
    if spec is not None and spec.lower() == "idle":
        return ("idle", None)
    if spec is None:
        # Bare === means "wait the global interval", not "wait for 120s idle"
        return ("interval", None)
    value = int(spec[:-1])
    unit = spec[-1].lower()
    seconds = value * {"s": 1, "m": 60, "h": 3600}[unit]
    return ("timed", seconds)


def parse_loop_blocks(text):
    """
    Split text by === delimiters into a list of loop blocks.

    Each block is (prompt, wait_type, wait_seconds) where wait_type/wait_seconds
    describe the wait condition AFTER sending this block, before the next one.

    Wait types:
      "interval" — bare === or last block: wait the global loop interval
      "idle"     — ===idle===: wait for 120s of Claude silence
      "timed"    — ===10s===: wait exactly N seconds

    The last block (no trailing delimiter) gets ("interval", None) — wraps
    around using the global interval.
    """
    lines = text.split("\n")
    blocks = []
    current_lines = []

    for line in lines:
        delim = parse_delimiter(line)
        if delim is not None:
            # Finalize the accumulated block with this delimiter's wait spec
            prompt = "\n".join(current_lines).strip()
            if prompt:
                blocks.append((prompt, delim[0], delim[1]))
            current_lines = []
        else:
            current_lines.append(line)

    # Last block — wrap-around uses the global interval (same as bare ===)
    prompt = "\n".join(current_lines).strip()
    if prompt:
        blocks.append((prompt, "interval", None))

    return blocks


def find_loop_file():
    """
    Find LOOP.md using fallback order:
      1. /workspace/LOOP.md (case-insensitive)
      2. ~/.agents/LOOP.md (host-mounted, read-only)
    """
    # Check /workspace first (case-insensitive)
    if os.path.isfile(LOOP_FILE):
        return LOOP_FILE
    for f in glob.glob("/workspace/[Ll][Oo][Oo][Pp].[Mm][Dd]"):
        return f

    # Fall back to ~/.agents/LOOP.md (mounted from host)
    global_loop = os.path.expanduser("~/.agents/LOOP.md")
    if os.path.isfile(global_loop):
        return global_loop

    return None


def parse_loop_file(path):
    """
    Read LOOP.md and extract (global_interval, blocks).

    blocks is a list of (prompt, wait_type, wait_seconds) tuples. The global
    interval applies to idle waits that don't specify their own duration.

    Returns None if the file doesn't exist, is empty, or has no usable blocks.
    """
    if path is None:
        return None

    try:
        with open(path, "r") as f:
            content = f.read()
    except (OSError, IOError):
        return None

    if not content.strip():
        return None

    lines = content.split("\n")
    first_line = lines[0]
    interval = parse_interval_line(first_line)

    if interval is not None:
        # First line was an interval spec — content is the rest
        remaining = "\n".join(lines[1:]).strip()
    else:
        # First line is not an interval — entire file is content
        remaining = content.strip()
        interval = LOOP_DEFAULT_INTERVAL

    if not remaining:
        return None

    blocks = parse_loop_blocks(remaining)
    if not blocks:
        return None

    return (interval, blocks)


def format_interval(seconds):
    """Format seconds into a human-readable interval string."""
    if seconds < 60:
        n = seconds
        return f"{n} second{'s' if n != 1 else ''}"
    elif seconds < 3600:
        n = seconds // 60
        return f"{n} minute{'s' if n != 1 else ''}"
    elif seconds < 86400:
        n = seconds // 3600
        return f"{n} hour{'s' if n != 1 else ''}"
    else:
        n = seconds // 86400
        return f"{n} day{'s' if n != 1 else ''}"


def format_hms(seconds):
    """Format seconds as HH:MM:SS."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def write_loop_deadline(wait_type, wait_seconds, loop_interval):
    """Write the next-fire wall-clock deadline for the statusline countdown."""
    try:
        if wait_type == "idle":
            # Can't predict when idle will trigger — signal it
            content = "idle\n"
        else:
            delay = wait_seconds if wait_type == "timed" else loop_interval
            deadline = time.time() + delay
            content = f"{deadline:.2f}\n"
        with open(LOOP_DEADLINE_FILE, "w") as f:
            f.write(content)
    except OSError:
        pass


def clear_loop_deadline():
    """Remove the deadline file on exit."""
    try:
        os.unlink(LOOP_DEADLINE_FILE)
    except OSError:
        pass


def wait_for_accept_delay(master_fd, stdin_fd, stdout_fd, delay):
    """
    Wait `delay` seconds while keeping I/O flowing.
    Returns True if delay elapsed (proceed with auto-accept).
    Returns False if the user typed something (cancel auto-accept).
    """
    deadline = time.monotonic() + delay
    fds = [master_fd] + ([stdin_fd] if stdin_fd is not None else [])

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True

        try:
            readable, _, _ = select.select(fds, [], [], min(remaining, 0.1))
        except InterruptedError:
            continue  # SIGWINCH etc — retry, don't cancel
        except (select.error, ValueError):
            return False

        for fd in readable:
            if fd == master_fd:
                try:
                    chunk = os.read(master_fd, 4096)
                    if chunk:
                        os.write(stdout_fd, chunk)
                except OSError:
                    pass
            elif fd == stdin_fd:
                try:
                    data = os.read(stdin_fd, 1024)
                except OSError:
                    data = b""
                if data:
                    log.debug("User input during accept delay — cancelling auto-accept")
                    try:
                        os.write(master_fd, data)
                    except OSError:
                        pass
                    return False


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <command> [args...]", file=sys.stderr)
        sys.exit(1)

    log.debug("auto-accept.py starting, argv=%s", sys.argv)

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    stdin_is_tty = os.isatty(stdin_fd)
    log.debug("stdin_is_tty=%s", stdin_is_tty)

    # ── Loop detection (before fork, while terminal is still cooked) ──
    loop_config = None
    loop_interval = None
    loop_blocks = None

    if LOOP_MODE:
        # Inline prompt from env var takes priority over LOOP.md file
        env_prompt = os.environ.get("CLAUDIUS_LOOP_PROMPT", "").strip()
        if env_prompt:
            env_interval = os.environ.get("CLAUDIUS_LOOP_INTERVAL", "")
            loop_interval = int(env_interval) if env_interval else LOOP_DEFAULT_INTERVAL
            loop_blocks = [(env_prompt, "idle", None)]
            loop_config = (loop_interval, loop_blocks)
            print(
                f"\r🔄 Looping inline prompt every "
                f"{format_hms(loop_interval)}\r\n",
                end="", flush=True,
            )
        else:
            _loop_path = find_loop_file()
            loop_config = parse_loop_file(_loop_path)
            if loop_config:
                loop_interval, loop_blocks = loop_config
                _source = "~/.agents/LOOP.md" if "/.agents/" in (_loop_path or "") else "./LOOP.md"
                _block_info = f" ({len(loop_blocks)} blocks)" if len(loop_blocks) > 1 else ""
                print(
                    f"\r🔄 Looping {_source}{_block_info} every "
                    f"{format_hms(loop_interval)}\r\n",
                    end="", flush=True,
                )

        if loop_config:
            log.debug("LOOP: interval=%ds, blocks=%d", loop_interval, len(loop_blocks))

    # Save original terminal settings so we can restore on exit
    old_termios = None
    if stdin_is_tty:
        old_termios = termios.tcgetattr(stdin_fd)

    # Fork a child process in a new PTY
    child_pid, master_fd = pty.fork()

    if child_pid == 0:
        # ── Child process: exec the target command ──
        os.execvp(sys.argv[1], sys.argv[1:])
        # execvp only returns on error
        sys.exit(127)

    # ── Parent process: multiplex I/O and watch for triggers ──

    # Sync the child PTY's window size with the real terminal
    if stdin_is_tty:
        copy_terminal_size(stdout_fd, master_fd)

    # Forward SIGWINCH (terminal resize) to the child, and update PTY size
    def handle_winch(signum, frame):
        copy_terminal_size(stdout_fd, master_fd)
        try:
            os.kill(child_pid, signal.SIGWINCH)
        except OSError:
            pass

    signal.signal(signal.SIGWINCH, handle_winch)

    # Put the real terminal into raw mode so individual keystrokes
    # pass through to the child without line-buffering or signal handling.
    if stdin_is_tty:
        tty.setraw(stdin_fd)

    last_accept_time = 0.0

    # Buffer for accumulating output chunks for pattern matching.
    # We keep a sliding window so patterns split across read() calls
    # are still detected.
    output_buffer = ""
    BUFFER_MAX = 4096

    # LOOP.md idle tracking — timestamps for detecting when Claude goes quiet
    last_child_output_time = time.monotonic()
    last_user_input_time = 0.0
    # Start prompt timer at now so the initial timed wait counts from startup,
    # not from epoch 0 (which would fire immediately).
    last_loop_prompt_time = time.monotonic()

    # Multi-block loop state — tracks position and current wait condition
    loop_block_index = 0
    # Use the global interval for the initial block so it fires after
    # loop_interval seconds instead of waiting for the 120s idle threshold.
    loop_wait_type = "interval" if loop_blocks else "idle"
    loop_wait_seconds = None

    # Write the initial deadline so the statusline can start counting down
    if LOOP_MODE and loop_blocks:
        write_loop_deadline(loop_wait_type, loop_wait_seconds, loop_interval)

    # Build the list of fds to select on
    read_fds = [master_fd]
    if stdin_is_tty:
        read_fds.append(stdin_fd)

    try:
        while True:
            try:
                readable, _, _ = select.select(read_fds, [], [], 0.1)
            except (select.error, ValueError, InterruptedError):
                break

            for fd in readable:

                # ── User input → child ──
                if fd == stdin_fd:
                    try:
                        data = os.read(stdin_fd, 1024)
                    except OSError:
                        data = b""
                    if not data:
                        continue
                    last_user_input_time = time.monotonic()
                    try:
                        os.write(master_fd, data)
                    except OSError:
                        pass

                # ── Child output → user + pattern matching ──
                elif fd == master_fd:
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        data = b""
                    if not data:
                        # Child closed its PTY — we're done
                        raise StopIteration

                    last_child_output_time = time.monotonic()

                    # Pass through to the real terminal immediately
                    try:
                        os.write(stdout_fd, data)
                    except OSError:
                        pass

                    # Accumulate for pattern matching
                    try:
                        text = data.decode("utf-8", errors="replace")
                    except Exception:
                        text = ""

                    output_buffer += text
                    if len(output_buffer) > BUFFER_MAX:
                        output_buffer = output_buffer[-BUFFER_MAX:]

                    # Log the stripped buffer periodically for debugging
                    if DEBUG:
                        clean = strip_ansi(output_buffer)
                        # Only log the last 200 chars to keep it readable
                        log.debug("buffer tail (stripped): %r", clean[-200:])

                    # Check triggers
                    now = time.monotonic()
                    trigger = matched_trigger(output_buffer)
                    if trigger and (now - last_accept_time) > DEBOUNCE_INTERVAL:
                        last_accept_time = now
                        log.debug("TRIGGER MATCHED (%s) — waiting %.1fs redraw + %ds accept delay", trigger, REDRAW_DELAY, ACCEPT_DELAY)

                        # Send host notification for plan triggers
                        if is_plan_trigger(trigger):
                            send_notification("Claudius has a plan")

                        # Wait for the TUI to finish redrawing
                        time.sleep(REDRAW_DELAY)
                        drain_child_output(master_fd, stdout_fd)

                        # Active wait — keeps I/O flowing so the user can intervene
                        should_accept = wait_for_accept_delay(
                            master_fd,
                            stdin_fd if stdin_is_tty else None,
                            stdout_fd,
                            ACCEPT_DELAY,
                        )

                        if should_accept:
                            if is_plan_trigger(trigger):
                                # Plan approval UI: Shift+Tab is bound to "yes-accept-edits"
                                # which directly accepts the plan. Enter would reject it.
                                log.debug("SENDING SHIFT+TAB (plan approval)")
                                keystroke = b"\x1b[Z"
                            else:
                                # Simple select prompts: Enter picks the highlighted option
                                log.debug("SENDING ENTER")
                                keystroke = b"\r"

                            try:
                                os.write(master_fd, keystroke)
                            except OSError:
                                pass
                        else:
                            log.debug("Auto-accept cancelled — user took manual control")

                        # Clear the buffer so we don't re-trigger on residual text
                        output_buffer = ""

            # ── Loop: step through blocks and re-prompt Claude ──
            if LOOP_MODE and loop_blocks:
                now = time.monotonic()
                idle = now - last_child_output_time
                since_prompt = now - last_loop_prompt_time
                since_input = now - last_user_input_time

                # Determine if the current wait condition is satisfied
                should_send = False
                if loop_wait_type == "timed":
                    # Fixed delay — just wait the specified seconds
                    should_send = since_prompt >= loop_wait_seconds
                elif loop_wait_type == "interval":
                    # Bare === separator — wait the global interval (timed, not idle)
                    should_send = since_prompt >= loop_interval
                else:
                    # Explicit ===idle=== — Claude must be idle + minimum interval elapsed
                    min_interval = loop_wait_seconds if loop_wait_seconds is not None else loop_interval
                    should_send = (
                        idle >= LOOP_IDLE_THRESHOLD
                        and since_prompt >= min_interval
                        and since_input >= LOOP_IDLE_THRESHOLD
                    )

                if should_send:
                    prompt, next_wait_type, next_wait_seconds = loop_blocks[loop_block_index]
                    log.debug(
                        "LOOP: sending block %d/%d (idle=%.0fs, wait=%s/%s)",
                        loop_block_index + 1, len(loop_blocks),
                        idle, loop_wait_type,
                        f"{loop_wait_seconds}s" if loop_wait_seconds else "global",
                    )
                    try:
                        os.write(master_fd, prompt.encode("utf-8") + b"\r")
                    except OSError:
                        pass
                    last_loop_prompt_time = now
                    output_buffer = ""

                    # Advance to next block and set its wait condition
                    loop_wait_type = next_wait_type
                    loop_wait_seconds = next_wait_seconds
                    loop_block_index = (loop_block_index + 1) % len(loop_blocks)

                    # Update the deadline for the statusline countdown
                    write_loop_deadline(loop_wait_type, loop_wait_seconds, loop_interval)

    except StopIteration:
        pass
    except KeyboardInterrupt:
        # Forward Ctrl+C to child
        try:
            os.kill(child_pid, signal.SIGINT)
        except OSError:
            pass
    finally:
        # Restore the real terminal to its original mode.
        # Without this, the terminal stays in raw mode (no echo, no line editing).
        if old_termios is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_termios)
        clear_loop_deadline()

    # Wait for the child and propagate its exit code
    while True:
        try:
            _, status = os.waitpid(child_pid, 0)
            if os.WIFEXITED(status):
                sys.exit(os.WEXITSTATUS(status))
            elif os.WIFSIGNALED(status):
                sys.exit(128 + os.WTERMSIG(status))
            else:
                sys.exit(1)
        except ChildProcessError:
            sys.exit(0)
        except OSError as e:
            if e.errno == errno.EINTR:
                continue
            sys.exit(1)


if __name__ == "__main__":
    main()
