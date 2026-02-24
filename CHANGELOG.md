# Changelog

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
