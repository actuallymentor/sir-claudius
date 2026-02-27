# Changelog

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
