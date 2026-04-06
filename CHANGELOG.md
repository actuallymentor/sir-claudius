# Changelog

## [0.22.1] - 2026-04-06

### Changed
- loop modifier shows its source in statusline: `loop(string)`, `loop(./)`, or `loop(~/.agents)`

## [0.22.0] - 2026-04-06

### Added
- multi-block LOOP.md: `===` delimiters split prompts into sequential blocks with per-block wait conditions

## [0.21.0] - 2026-04-06

### Added
- loop prompt fallback chain: inline string > `./LOOP.md` > `~/.agents/LOOP.md`

## [0.20.2] - 2026-04-01

### Fixed
- clear terminal after Claude's TUI exits to prevent rendering artifacts from polluting script output

## [0.20.1] - 2026-04-01

### Fixed
- add missing `statusLine.type` field in settings.json patch, fixing validation error on fresh installs

## [0.20.0] - 2026-04-01

### Added
- `update` runs `claude update` on the host if Claude Code is installed

### Fixed
- remove hardcoded `--platform=linux/arm64` from Dockerfile causing exec format error on x86_64

## [0.19.0] - 2026-04-01

### Added
- `update` pulls `~/.agents` git repo if present

## [0.18.0] - 2026-03-30

### Changed
- rename `autopilot` modifier to `background`
- rename `CLAUDIUS_AUTOPILOT` env var to `CLAUDIUS_BACKGROUND`

### Breaking
- `claudius autopilot` is now `claudius background`

## [0.17.1] - 2026-03-28

### Fixed
- background resume hint now shown outside tmux so it survives window close

## [0.17.0] - 2026-03-28

### Added
- `loop` modifier — re-prompt Claude when idle from LOOP.md or inline string
- system notifications on plan detection (macOS osascript, Linux notify-send, terminal bell)
- case-insensitive LOOP.md file detection

### Changed
- `yolo` now auto-accepts plans with 30s review window (was 10s, previously required background)
- `background` only manages tmux sessions — no longer controls plan acceptance or loop
- `loop` replaces background's LOOP.md handling as a standalone modifier

### Breaking
- `claudius background` no longer auto-accepts plans — use `claudius yolo background`
- `claudius background` no longer handles LOOP.md — use `claudius background loop`

## [0.16.0] - 2026-03-27

### Added
- enable tmux mouse support by default in background sessions (82ddff5)
- increase tmux scrollback history to 10k lines in background sessions (4ea088c)

## [0.15.3] - 2026-03-26

### Fixed
- worktree creation failure now exits immediately instead of continuing with broken state
- credential sync daemon writes are now atomic (temp file + mv) to prevent truncated reads
- background update check no longer interleaves output with interactive prompts
- unquoted temp file path in update subcommand trap

### Changed
- document LOOP.md periodic re-prompting feature (background mode)
- fix README claiming worktree is incompatible with continue/resume (they work fine)
- clarify sandbox "no changes escape" — session metadata and caches persist on host

## [0.15.1] - 2026-03-24

### Fixed
- suppress "Terminated" shell message from credential sync daemon on exit (disown instead of wait)

## [0.15.0] - 2026-03-17

### Added
- live credential sync for long-running containers — tokens no longer go stale mid-session
- Linux: mount host credentials file directly (instant refresh, no daemon needed)
- macOS: background sync daemon re-extracts Keychain credentials every 5 minutes

## [0.14.0] - 2026-03-12

### Added
- `background` modifier — auto-accept plan approval prompts independently of yolo

### Changed
- `yolo` no longer auto-accepts plans — use `claudius yolo background` for full autonomy
- permission bypass triggers in auto-accept.py gated by `CLAUDIUS_YOLO` env var

## [0.13.3] - 2026-03-12

### Fixed
- plan approval sends Shift+Tab instead of Enter (Claude Code UI changed — Enter now rejects)
- user input during 10s accept delay no longer blocked — keystrokes cancel auto-accept and forward to child

## [0.13.2] - 2026-03-10

### Added
- statusline shows `owner/repo` from git remote alongside session modifiers

## [0.13.1] - 2026-03-10

### Fixed
- statusline not appearing for users without a pre-existing statusLine in settings.json

## [0.13.0] - 2026-03-09

### Changed
- statusline shows session modifiers (YOLO, WORKTREE, RESUME, etc.) instead of repo name
- `CLAUDIUS_MODIFIERS` env var exposed inside container for statusline consumption
- default sessions show "claudius" label; modifier sessions show uppercased tags joined with `·`

## [0.12.1] - 2026-03-09

### Changed
- statusline shows `owner/repo` from git remote instead of working directory name

## [0.12.0] - 2026-03-09

### Added
- portable statusline inside container — shows directory, git branch, and Claude usage %
- `CLAUDE_SESSION_KEY` and `CLAUDE_ORG_ID` env vars for usage tracking credentials
- auto-extract usage credentials from host's `~/.claude/fetch-claude-usage.swift`

### Changed
- settings.json is now always copied as a writable temp file (was only in yolo mode) to patch container paths

## [0.11.0] - 2026-02-27

### Added
- resumable worktree sessions — choose "keep" on exit, then `claudius resume <id>` to re-enter
- `claudius worktree list` — show active (unmerged) worktrees with age and session info
- `claudius worktree clean` — merge/cleanup worktrees by ID, `--merged`, `--stale`, or `--all`
- worktree metadata persisted to `~/.claudius/worktrees/<id>.json` for session tracking
- stale worktree warning (30+ days) on every invocation, throttled to once per day
- history listing shows worktree branch indicator for worktree sessions
- history inspect shows worktree status (active/merged) and branch name

### Changed
- `resume` and `continue` now auto-detect worktree sessions and re-enter the worktree
- post-exit merge prompt replaces unconditional auto-merge: `[m]erge` or `[k]eep`
- session_modifiers format extended with `worktree:<ID>` token for reverse lookup
- resume hint strips internal worktree token, showing clean `claudius resume <id>` command

## [0.10.1] - 2026-02-27

### Fixed
- mark `/workspace` as git safe directory in entrypoint to fix "dubious ownership" errors on bind mounts

## [0.10.0] - 2026-02-27

### Added
- `worktree` command — isolated git worktree per session for parallel-safe operation
- auto-merge on exit: fast-forward or merge commit, with conflict handling and push offer
- `CLAUDIUS_WORKTREE`, `CLAUDIUS_WORKTREE_BRANCH`, `CLAUDIUS_WORKTREE_ORIGINAL_BRANCH` env vars inside container
- system prompt tells Claude about the worktree branch and merge-back behavior

## [0.9.0] - 2026-02-27

### Added
- persist node_modules isolation choice per workspace — remembered across runs
- returning users get a 5-second timeout that defaults to their previous choice
- first-time users still get an indefinite prompt (default: isolate)

## [0.8.2] - 2026-02-27

### Fixed
- auth token race condition: pre-flight check could rotate OAuth tokens before credentials were captured, causing 401 in the container. Credentials are now captured after the pre-flight check.

### Changed
- simplify pre-flight auth check prompt (saves tokens)

## [0.8.1] - 2026-02-25

### Fixed
- ANSI stripping now replaces cursor-forward sequences with spaces, fixing silent pattern match failures

### Changed
- simplify auto-accept delay from I/O-forwarding countdown loop to plain 10s sleep
- match actual TUI menu text ("Yes, and bypass permissions", "Yes, clear context") instead of prompt header

### Removed
- terminal title bar countdown (OSC 0) — not visible in practice

## [0.8.0] - 2026-02-25

### Added
- 10-second countdown before auto-accepting plan prompts, shown in terminal title bar
- TUI stays responsive during countdown (I/O forwarding continues)

## [0.7.0] - 2026-02-25

### Added
- auto-accept plan mode approval prompts in YOLO mode via `auto-accept.py` PTY wrapper

## [0.6.5] - 2025-02-25

### Fixed
- bust prompt cache on pre-flight auth check with dynamic timestamp (d3ace94)

## [0.6.4] - 2026-02-24

## [0.6.3] - 2026-02-24

### Added
- pass host `gh` CLI auth into container via `GH_TOKEN` env var, with `~/.config/gh` config mount as fallback

## [0.6.2] - 2026-02-24

### Fixed
- correct login command in auth failure message (`claude "/login"` not `claude login`)

## [0.6.1] - 2026-02-22

### Added
- pre-flight auth check before launching container — warns if host credentials are expired or invalid

## [0.6.0] - 2026-02-20

### Added
- mount host `~/.agents` directory read-only into container

### Changed
- rename `CLAUDIUS_MODE` env var to `AGENT_AUTONOMY_MODE`
- extract `/home/node` into `CONTAINER_HOME` variable

## [0.5.0] - 2026-02-18

### Added
- re-add node_modules isolation with interactive prompt
- auto-detect Node.js projects via package.json, node_modules, .nvmrc, package-lock.json, yarn.lock, pnpm-lock.yaml
- `CLAUDIUS_NPM_ISOLATE` env var to force isolation on (1) or off (0)
- entrypoint chown for Docker volume UID mismatch on isolated node_modules

## [0.4.7] - 2026-02-18

### Changed
- switch Docker base image from Alpine to Debian slim (node:24-slim)
- add symlinks for fd and bat (Debian ships fd-find and batcat)
- install GitHub CLI via apt repository instead of Alpine package

## [0.4.2] - 2026-02-18

### Fixed
- `claudius update` now always pulls the docker image, even when the script version is already current

### Changed
- `claudius update` only shows the "Status: Image is up to date" line when no image update is available; shows full pull output when downloading a new image

## [0.4.1] - 2026-02-18

### Fixed
- history search now searches full session transcripts, not just the first prompt

### Removed
- history search highlight (ANSI codes not reliably rendered across environments)

## [0.4.0] - 2026-02-18

### Added
- search history sessions by description with `claudius history "search text"` (case-insensitive)
- `claudius history inspect <id>` to view full session details: metadata, tool usage stats, and conversation log

### Changed
- history session descriptions now use full terminal width instead of a fixed 60-character truncation
- history resume command column is now fixed-width so all rows align regardless of modifiers (yolo, sandbox, etc.)
- ~~history search results now highlight matching text in bold yellow~~ (removed in 0.4.1)
