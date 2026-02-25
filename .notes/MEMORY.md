# Memory

## Project: Sir Claudius

Docker-based sandbox for running Claude Code. Key files: `Dockerfile`, `claudius` (host launch script), `install.sh`.

## Key Decisions

- GitHub CLI auth: mounted `~/.config/gh` read-only into container (added 2026-02-24)
- Auto-accept plan mode prompts in YOLO mode via `auto-accept.py` PTY wrapper (added 2026-02-25)
- Auto-accept has 10s countdown shown in terminal title bar (OSC 0), TUI stays responsive during wait (added 2026-02-25)
