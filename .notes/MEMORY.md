# Memory

## Project: Sir Claudius

Docker-based sandbox for running Claude Code. Key files: `Dockerfile`, `claudius` (host launch script), `install.sh`.

## Key Decisions

- GitHub CLI auth: mounted `~/.config/gh` read-only into container (added 2026-02-24)
- Auto-accept plan mode prompts in YOLO mode via `auto-accept.py` PTY wrapper (added 2026-02-25)
- Auto-accept uses active select-based wait during 30s delay — user keystrokes cancel auto-accept (fixed 2026-03-12, delay increased 2026-03-28)
- Modifiers refactored (v0.17.0): yolo = permissions + plan auto-accept (30s delay) + host notifications; background = tmux only; loop = periodic re-prompting (replaces old autopilot's LOOP.md handling) (refactored 2026-03-28, renamed autopilot→background 2026-03-30)
- Plan approval UI changed in Claude Code ~v2.1.x — Enter now rejects; Shift+Tab (`\x1b[Z`) bound to "yes-accept-edits" accepts (fixed 2026-03-12)
- Claude Code TUI uses `\x1b[\d*C` (cursor-forward) as visual spaces; must replace with real space before stripping ANSI (fixed 2026-02-25)
- OAuth auth bug: pre-flight check can rotate refresh tokens, invalidating credentials captured before the check. Fix: two-phase auth — detect first, capture after pre-flight (fixed 2026-02-27)
- node_modules isolation choice persisted in `$CLAUDIUS_DIR/nm_preferences` (tab-separated hash→Y|N). Returning users get 5s timeout defaulting to previous choice (added 2026-02-27)

## Worktree Mode (added 2026-02-27, resumable 2026-02-27)

`claudius worktree` creates an isolated git worktree per session. Key design: temp files fix up `.git` and `gitdir` paths so git works inside Docker. On exit, merge-or-keep prompt lets user defer merge. Metadata in `~/.claudius/worktrees/<id>.json` links sessions to worktrees. `session_modifiers` uses `worktree:<ID>` token for reverse lookup. `resume`/`continue` auto-detect worktree sessions. `worktree list` and `worktree clean` manage lifecycle. See `GOTCHAS.md` for Docker path details.

## Statusline (added 2026-03-09, modifiers 2026-03-09)

Portable `statusline.sh` ships with the container image at `/usr/local/bin/statusline.sh`. The `claudius` script always creates a writable settings.json copy and rewrites the `statusLine.command` path to point to the container script. Usage tracking credentials (`CLAUDE_SESSION_KEY`, `CLAUDE_ORG_ID`) are extracted from `~/.claude/fetch-claude-usage.swift` or accepted as explicit env vars. First segment shows session modifiers (YOLO·WORKTREE·RESUME) via `CLAUDIUS_MODIFIERS` env var; defaults to "claudius" for plain sessions.

## Loop Modifier — Periodic Re-prompting (added 2026-03-26, refactored 2026-03-28)

`loop` is a standalone chainable modifier. Prompt source fallback: inline string → `./LOOP.md` (case-insensitive) → `~/.agents/LOOP.md` (global default). First line parsed for global interval (cron syntax, human-readable, defaults to 30 min). Inline prompt always uses 30-min interval. `entrypoint.sh` gates `auto-accept.py` on `CLAUDIUS_YOLO=1 || CLAUDIUS_LOOP=1`. Multi-block support (v0.22.0): `===` delimiters (3+ `=`) split LOOP.md into sequential blocks with per-block wait conditions. Three wait types: `===` (interval — timed wait using global interval), `===idle===` (120s silence), `===NNs/m/h===` (exact timed wait). Initial block and last-block wrap-around both use "interval" wait. `parse_interval_line()` accepts single-letter units (`5s`, `10m`, `2h`, `1d`) in addition to full words. Statusline shows live countdown via `/tmp/claudius-loop-deadline` (wall-clock epoch written by `auto-accept.py`, read by `statusline.sh`). Boot message: "🔄 Looping {source} every HH:MM:SS".

## Host Notifications (added 2026-03-28)

When yolo detects a plan trigger, `auto-accept.py` writes to `/tmp/claudius-notify` (a host-mounted FIFO). The host-side `claudius` script runs a background watcher that reads from the FIFO and sends OS notifications (osascript on macOS, notify-send on Linux, terminal bell as universal fallback). Non-blocking writes with `O_WRONLY|O_NONBLOCK` — fails silently if no reader.

## Background tmux Wrapping (added 2026-03-26, refactored 2026-03-28, renamed from autopilot 2026-03-30)

`claudius background` re-executes inside a persistent tmux session using a dedicated server socket (`tmux -L claudius`). One session per directory (keyed by `pwd -P`, encoded to escape `.` and `:`). As of v0.17.0, background ONLY manages tmux — it no longer controls plan acceptance or loop. Use `claudius yolo background loop` for the old full-autonomy behavior.

## Gotchas

See `GOTCHAS.md` for accumulated pitfalls
