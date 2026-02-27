# Memory

## Project: Sir Claudius

Docker-based sandbox for running Claude Code. Key files: `Dockerfile`, `claudius` (host launch script), `install.sh`.

## Key Decisions

- GitHub CLI auth: mounted `~/.config/gh` read-only into container (added 2026-02-24)
- Auto-accept plan mode prompts in YOLO mode via `auto-accept.py` PTY wrapper (added 2026-02-25)
- Auto-accept uses simple 10s sleep before sending Enter — countdown title bar removed as unnecessary (simplified 2026-02-25)
- Claude Code TUI uses `\x1b[\d*C` (cursor-forward) as visual spaces; must replace with real space before stripping ANSI (fixed 2026-02-25)
- OAuth auth bug: pre-flight check can rotate refresh tokens, invalidating credentials captured before the check. Fix: two-phase auth — detect first, capture after pre-flight (fixed 2026-02-27)
- node_modules isolation choice persisted in `$CLAUDIUS_DIR/nm_preferences` (tab-separated hash→Y|N). Returning users get 5s timeout defaulting to previous choice (added 2026-02-27)

## Worktree Mode (added 2026-02-27)

`claudius worktree` creates an isolated git worktree per session. Key design: temp files fix up `.git` and `gitdir` paths so git works inside Docker. On exit, auto-merges (ff-only then regular) or preserves branch on conflict. See `GOTCHAS.md` for Docker path details.

## Gotchas

See `GOTCHAS.md` for accumulated pitfalls
