# Gotchas

## OAuth Token Refresh Race Condition (fixed 2026-02-27)

**Problem**: The pre-flight auth check (`claude -p "..."`) can trigger an OAuth token refresh on the host, rotating both access and refresh tokens. If credentials were captured *before* the check, the container gets stale tokens → 401.

**Fix**: Two-phase auth in `claudius`:
1. **Detection** (before pre-flight): Check if credentials exist without reading secrets
2. **Capture** (after pre-flight): Read the actual credentials, which now include any refreshed tokens

Key detail: on macOS, `security find-generic-password -s "..." ` (without `-w`) checks existence without extracting the password, avoiding unnecessary keychain prompts.
