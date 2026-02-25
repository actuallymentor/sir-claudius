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
import select
import signal
import time
import errno


# ─── Trigger patterns ────────────────────────────────────────────────
# Each pattern is matched against ANSI-stripped terminal output.
# On match, we wait briefly for the TUI to redraw, then send Enter.

TRIGGER_PATTERNS = [
    "Claude Code needs your approval for the plan",
    "needs your approval",
    "Would you like to proceed",
]

# Compiled regex to strip ANSI escape sequences before matching
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b\[[\?]?[0-9;]*[a-zA-Z]")

# Seconds to wait after detecting a trigger before sending Enter.
# Gives the TUI time to finish its redraw cycle.
REDRAW_DELAY = 0.5

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


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <command> [args...]", file=sys.stderr)
        sys.exit(1)

    # Fork a child process in a new PTY
    child_pid, master_fd = pty.fork()

    if child_pid == 0:
        # ── Child process: exec the target command ──
        os.execvp(sys.argv[1], sys.argv[1:])
        # execvp only returns on error
        sys.exit(127)

    # ── Parent process: multiplex I/O and watch for triggers ──

    last_accept_time = 0.0

    # Forward SIGWINCH (terminal resize) to the child
    def handle_winch(signum, frame):
        try:
            os.kill(child_pid, signal.SIGWINCH)
        except OSError:
            pass

    signal.signal(signal.SIGWINCH, handle_winch)

    # Buffer for accumulating output chunks for pattern matching.
    # We keep a sliding window so patterns split across read() calls
    # are still detected.
    output_buffer = ""
    BUFFER_MAX = 4096

    try:
        while True:
            try:
                readable, _, _ = select.select([sys.stdin, master_fd], [], [], 0.1)
            except (select.error, ValueError):
                break

            for fd in readable:

                # ── User input → child ──
                if fd is sys.stdin:
                    try:
                        data = os.read(sys.stdin.fileno(), 1024)
                    except OSError:
                        data = b""
                    if not data:
                        continue
                    try:
                        os.write(master_fd, data)
                    except OSError:
                        pass

                # ── Child output → user + pattern matching ──
                elif fd is master_fd:
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        data = b""
                    if not data:
                        # Child closed its PTY — we're done
                        raise StopIteration

                    # Pass through to the real terminal immediately
                    try:
                        os.write(sys.stdout.fileno(), data)
                        sys.stdout.flush()
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
                        try:
                            while True:
                                r, _, _ = select.select([master_fd], [], [], 0.05)
                                if not r:
                                    break
                                chunk = os.read(master_fd, 4096)
                                if not chunk:
                                    break
                                os.write(sys.stdout.fileno(), chunk)
                        except OSError:
                            pass

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
