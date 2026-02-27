# Gotchas

## OAuth Token Refresh Race Condition (fixed 2026-02-27)

**Problem**: The pre-flight auth check (`claude -p "..."`) can trigger an OAuth token refresh on the host, rotating both access and refresh tokens. If credentials were captured *before* the check, the container gets stale tokens → 401.

**Fix**: Two-phase auth in `claudius`:
1. **Detection** (before pre-flight): Check if credentials exist without reading secrets
2. **Capture** (after pre-flight): Read the actual credentials, which now include any refreshed tokens

Key detail: on macOS, `security find-generic-password -s "..." ` (without `-w`) checks existence without extracting the password, avoiding unnecessary keychain prompts.

## Git Worktree Paths Inside Docker (2026-02-27)

**Problem**: A git worktree's `.git` file contains `gitdir: /absolute/host/path/.git/worktrees/<name>`. Inside the container, this host path doesn't exist, so git commands fail.

**Fix**: Mount the original repo's `.git` dir at `/git-root/.git` and create two temp files:
1. `/workspace/.git` → `gitdir: /git-root/.git/worktrees/<id>` (container-relative path)
2. `/git-root/.git/worktrees/<id>/gitdir` → `/workspace` (tells git where the worktree checkout lives)

This preserves git's internal path resolution. The `commondir` file in the worktree already uses `../..` (relative), so it resolves to `/git-root/.git/` correctly.
