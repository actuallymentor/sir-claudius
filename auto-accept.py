#!/usr/bin/env python3
"""
PTY wrapper that auto-accepts plan mode prompts in Claude Code.

When AGENT_AUTONOMY_MODE=yolo, Claude Code should run with maximum autonomy.
Plan mode approval prompts still block waiting for user input — this wrapper
monitors terminal output, detects those prompts, and sends Enter to accept
the default (pre-selected) option.

All I/O passes through transparently. The user can still type normally.
"""

import os
import sys
import pty
import re
import fcntl
import select
import signal
import struct
import termios
import time
import tty
import errno


# ─── Trigger patterns ────────────────────────────────────────────────
# Each pattern is matched against ANSI-stripped terminal output.
# On match, we wait briefly for the TUI to redraw, then send Enter.

TRIGGER_PATTERNS = [
    "Claude Code needs your approval for the plan",
    "needs your approval",
    "Would you like to proceed",
]

# Compiled regex to strip ANSI escape sequences before matching.
# Covers CSI sequences (with optional ? prefix), OSC sequences, and
# other common terminal escapes like \x1b= / \x1b> (keypad mode).
ANSI_RE = re.compile(
    r"\x1b\[[\?]?[0-9;]*[a-zA-Z]"   # CSI: \e[...X  or \e[?...X
    r"|\x1b\][^\x07]*\x07"           # OSC: \e]...\a
    r"|\x1b[()][0-9A-Za-z]"          # charset: \e(B, \e)0, etc.
    r"|\x1b[=>]"                     # keypad mode: \e= / \e>
)

# Seconds to wait after detecting a trigger before starting the countdown.
# Gives the TUI time to finish its redraw cycle.
REDRAW_DELAY = 0.5

# Seconds to count down before auto-accepting. Gives the user time to review
# the plan. The countdown is shown in the terminal title bar (OSC 0).
COUNTDOWN_SECONDS = 10

# Minimum seconds between consecutive auto-accepts (debounce).
# Prevents double-firing when the same prompt text appears in the redraw.
DEBOUNCE_INTERVAL = 3.0


def strip_ansi(text):
    """Remove ANSI escape codes from text for clean pattern matching."""
    return ANSI_RE.sub("", text)


def matches_trigger(text):
    """Check if any trigger pattern appears in the stripped text."""
    clean = strip_ansi(text)
    return any(pattern in clean for pattern in TRIGGER_PATTERNS)


def copy_terminal_size(from_fd, to_fd):
    """Copy the terminal window size from one fd to another."""
    try:
        size = fcntl.ioctl(from_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(to_fd, termios.TIOCSWINSZ, size)
    except OSError:
        pass


def set_terminal_title(fd, title):
    """Set the terminal title via OSC 0. Non-destructive to TUI content."""
    try:
        os.write(fd, f"\x1b]0;{title}\x07".encode())
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


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <command> [args...]", file=sys.stderr)
        sys.exit(1)

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    stdin_is_tty = os.isatty(stdin_fd)

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

                    # Check triggers
                    now = time.monotonic()
                    if matches_trigger(output_buffer) and (now - last_accept_time) > DEBOUNCE_INTERVAL:
                        last_accept_time = now

                        # Wait for the TUI to finish redrawing
                        time.sleep(REDRAW_DELAY)

                        # Drain any output that arrived during the delay
                        drain_child_output(master_fd, stdout_fd)

                        # Countdown with visual feedback in the terminal title bar.
                        # The main I/O loop keeps running so the TUI stays responsive.
                        for remaining in range(COUNTDOWN_SECONDS, 0, -1):
                            set_terminal_title(stdout_fd, f"\u23f3 Auto-accepting plan in {remaining}s...")

                            # Forward I/O for 1 second (non-blocking)
                            deadline = time.monotonic() + 1.0
                            while time.monotonic() < deadline:
                                timeout = max(0, deadline - time.monotonic())
                                try:
                                    r, _, _ = select.select(read_fds, [], [], timeout)
                                except (select.error, ValueError, InterruptedError):
                                    r = []
                                for ready_fd in r:
                                    if ready_fd == stdin_fd:
                                        try:
                                            chunk = os.read(stdin_fd, 1024)
                                            if chunk:
                                                os.write(master_fd, chunk)
                                        except OSError:
                                            pass
                                    elif ready_fd == master_fd:
                                        try:
                                            chunk = os.read(master_fd, 4096)
                                            if chunk:
                                                os.write(stdout_fd, chunk)
                                        except OSError:
                                            pass

                        # Clear the countdown title
                        set_terminal_title(stdout_fd, "")

                        # Send Enter to accept the default selection
                        try:
                            os.write(master_fd, b"\r")
                        except OSError:
                            pass

                        # Clear the buffer so we don't re-trigger on residual text
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
