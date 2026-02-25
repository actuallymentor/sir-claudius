# Memory

## Project: Sir Claudius

Docker-based sandbox for running Claude Code. Key files: `Dockerfile`, `claudius` (host launch script), `install.sh`.

## Key Decisions

- GitHub CLI auth: mounted `~/.config/gh` read-only into container (added 2026-02-24)
- Auto-accept plan mode prompts in YOLO mode via `auto-accept.py` PTY wrapper (added 2026-02-25)
- Auto-accept uses simple 10s sleep before sending Enter — countdown title bar removed as unnecessary (simplified 2026-02-25)
- Claude Code TUI uses `\x1b[\d*C` (cursor-forward) as visual spaces; must replace with real space before stripping ANSI (fixed 2026-02-25)
