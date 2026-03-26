#!/usr/bin/env python3
"""
PTY wrapper that auto-accepts prompts in Claude Code.

Used by the "autopilot" modifier to auto-accept plan approval prompts.
When CLAUDIUS_YOLO=1 is also set, permission bypass prompts are accepted too.

All I/O passes through transparently. The user can still type normally.
During the accept delay, keystrokes cancel auto-accept and forward to the child.
"""

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

# Plan approval triggers — always active in autopilot mode.
# Shift+Tab is bound to "yes-accept-edits" in the plan component.
# (Enter rejects the plan in the current Claude Code UI.)
PLAN_TRIGGERS = [
    "needs your approval",
]

# Permission bypass triggers — only active when CLAUDIUS_YOLO=1.
# These accept via Enter (the desired option is already highlighted).
YOLO_TRIGGERS = [
    "Yes, and bypass permissions",
    "Yes, clear context",
]

YOLO_MODE = os.environ.get("CLAUDIUS_YOLO", "0") == "1"
ALL_TRIGGERS = PLAN_TRIGGERS + (YOLO_TRIGGERS if YOLO_MODE else [])

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
# the plan and intervene if needed.
ACCEPT_DELAY = 10

# Minimum seconds between consecutive auto-accepts (debounce).
# Prevents double-firing when the same prompt text appears in the redraw.
DEBOUNCE_INTERVAL = 3.0

# ─── LOOP.md — periodic re-prompting ────────────────────────────────
# When /workspace/LOOP.md exists, auto-accept will periodically type
# its contents into the Claude terminal when Claude goes idle.

LOOP_FILE = "/workspace/LOOP.md"
LOOP_IDLE_THRESHOLD = 120    # seconds of output silence → Claude is idle
LOOP_DEFAULT_INTERVAL = 1800 # 30 minutes


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
        r'(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)',
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


def parse_loop_file(path):
    """
    Read LOOP.md and extract (interval_seconds, prompt_text).

    Returns None if the file doesn't exist, is empty, or has no usable prompt.
    """
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
        # First line was an interval spec — prompt is the rest
        prompt = "\n".join(lines[1:]).strip()
    else:
        # First line is not an interval — entire file is the prompt
        prompt = content.strip()
        interval = LOOP_DEFAULT_INTERVAL

    if not prompt:
        return None

    return (interval, prompt)


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

    # ── LOOP.md detection (before fork, while terminal is still cooked) ──
    loop_config = parse_loop_file(LOOP_FILE)
    loop_interval = None
    loop_prompt = None
    if loop_config:
        loop_interval, loop_prompt = loop_config
        print(
            f"\r🔄 LOOP.md detected — will re-prompt every "
            f"{format_interval(loop_interval)}\r\n",
            end="", flush=True,
        )
        log.debug("LOOP: interval=%ds, prompt=%r", loop_interval, loop_prompt[:80])

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
    last_loop_prompt_time = 0.0

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

            # ── LOOP.md: re-prompt Claude when idle ──
            if loop_config:
                now = time.monotonic()
                idle = now - last_child_output_time
                since_prompt = now - last_loop_prompt_time
                since_input = now - last_user_input_time

                if (idle >= LOOP_IDLE_THRESHOLD and
                        since_prompt >= loop_interval and
                        since_input >= LOOP_IDLE_THRESHOLD):
                    log.debug(
                        "LOOP: Claude idle %.0fs, re-prompting (interval=%ds)",
                        idle, loop_interval,
                    )
                    try:
                        os.write(master_fd, loop_prompt.encode("utf-8") + b"\r")
                    except OSError:
                        pass
                    last_loop_prompt_time = now
                    output_buffer = ""

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
