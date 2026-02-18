# Changelog

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
