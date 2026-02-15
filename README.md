# Sir Claudius

Let Claude Code run wild — safely sandboxed in Docker so it can't touch your system. Pre-built images published daily to [Docker Hub](https://hub.docker.com/r/actuallymentor/sir-claudius).

## Setup

1. **Install the wrapper** somewhere on your `$PATH`:

**Option A: Using the install script (recommended)**
```sh
curl -fsSL https://raw.githubusercontent.com/actuallymentor/sir-claudius/main/install.sh | sh
```

**Option B: Manual installation**
```sh
curl -fsSL https://raw.githubusercontent.com/actuallymentor/sir-claudius/main/claudius \
  -o /usr/local/bin/claudius && chmod +x /usr/local/bin/claudius
```

2. **Authenticate** — claudius automatically reuses your host Claude CLI credentials (macOS Keychain or `~/.claude/.credentials.json`). If you haven't logged into Claude Code on the host, run:

```sh
claudius setup
```

This opens a browser, authenticates via OAuth, and saves a fallback token to `~/.claude-sandbox-token`.

## Usage

```sh
# Interactive session in the current directory
claudius

# Update claudius script and pull the latest image (or rebuild if pull fails)
claudius update

# Force rebuild the local image with --no-cache
claudius rebuild

# Skip all permission prompts (--dangerously-skip-permissions)
claudius yolo

# Fully isolated — no workspace, host files read-only
claudius sandbox

# Read-only workspace — explore code without modifying it
claudius mudbox

# Chain commands in any order
claudius yolo mudbox          # read-only workspace + skip permissions
claudius sandbox yolo         # no workspace + skip permissions
claudius mudbox continue      # read-only workspace + resume last session

# Combine with a prompt
claudius sandbox -p "explain the difference between TCP and UDP"
claudius mudbox -p "review this codebase for security issues"

# Combine yolo with other arguments
claudius yolo -p "refactor this codebase"

# Pass arguments through to claude
claudius -p "explain this codebase"

# One-shot with print mode
claudius -p "write tests for lib/utils.js" --output-format json
```

## Sandbox mode

`claudius sandbox` runs a fully isolated session — no project directory is mounted and all host files are read-only. Nothing inside the container can modify your filesystem.

This is useful for:
- General questions, research, or brainstorming
- Running untrusted prompts safely
- Letting Claude experiment without any risk to your files

```sh
# Start an isolated session
claudius sandbox

# Ask a one-shot question
claudius sandbox -p "write a Python quicksort implementation"
```

In sandbox mode:
- `/workspace` is an empty, container-local directory
- Host config files (`~/.claude.json`, settings, session history) are mounted **read-only**
- Named volumes (npm/uv caches) still work so MCP servers function normally
- No changes can escape the container

## Mudbox mode

`claudius mudbox` mounts your project directory as **read-only**. Claude can see and explore all your code but cannot modify any files on the host.

This is useful for:
- Code review and security audits
- Codebase exploration and analysis
- Generating patches or suggestions without risk

```sh
# Start a read-only session
claudius mudbox

# Code review with full autonomy
claudius mudbox yolo -p "review this codebase for security issues"
```

In mudbox mode:
- `/workspace` is mounted **read-only** from the current directory
- Claude can read all project files but cannot write to them
- Host config files and session data remain writable (like normal mode)
- Claude can create files in container-local directories outside `/workspace`

## Chaining commands

Chainable commands (`yolo`, `sandbox`, `mudbox`, `continue`, `resume`) can be combined in any order:

```sh
claudius yolo mudbox          # read-only workspace + skip permissions
claudius sandbox yolo         # no workspace + skip permissions
claudius mudbox continue      # read-only workspace + resume last session
claudius yolo resume          # skip permissions + pick a session to resume
```

If both `sandbox` and `mudbox` are specified, `mudbox` takes priority (you get a read-only workspace rather than no workspace).

## Authentication priority

Claudius resolves credentials in this order:

1. `CLAUDE_CODE_OAUTH_TOKEN` environment variable
2. Host Claude CLI credentials (macOS Keychain / `~/.claude/.credentials.json`)
3. Fallback token file (`~/.claude-sandbox-token`, created by `claudius setup`)
4. `ANTHROPIC_API_KEY` environment variable

## What gets mounted

| Host | Container | Mode | Purpose |
|---|---|---|---|
| Current directory | `/workspace` | read-write (read-only in mudbox, not mounted in sandbox) | Project files |
| `~/.claude.json` | `/home/node/.claude.json` | read-write copy (read-only in sandbox) | Onboarding state, workspace trust |
| `~/.claude/settings.json` | `/home/node/.claude/settings.json` | read-only | User settings |
| `~/.claude/settings.local.json` | `/home/node/.claude/settings.local.json` | read-only | Local settings overrides |
| `~/.claude/CLAUDE.md` | `/home/node/.claude/CLAUDE.md` | read-only | Global instructions |
| `~/.claude/skills/` | `/home/node/.claude/skills/` | read-only | Custom skills |
| `claudius-npm-cache` (volume) | `/home/node/.npm` | read-write | npm/npx package cache |
| `claudius-uv-cache` (volume) | `/home/node/.cache` | read-write | uv/pip package cache |

## MCP servers

MCP servers configured on the host are automatically available inside the container. The `settings.json` mount carries your MCP definitions, and named Docker volumes persist the package caches so servers don't re-download every run.

```sh
# Configure an MCP server on the host (one-time)
claude mcp add my-server -- npx -y @some/mcp-server

# First claudius run downloads the package and caches it
claudius

# Subsequent runs start the MCP server instantly from cache
claudius
```

To clear the MCP caches:

```sh
docker volume rm claudius-npm-cache claudius-uv-cache
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CLAUDE_MODEL` | `claude-opus-4-6` | Model to use |
| `CLAUDE_CODE_OAUTH_TOKEN` | | Override the saved OAuth token |
| `ANTHROPIC_API_KEY` | | Use an API key instead of OAuth |
| `CLAUDE_SANDBOX_IMAGE` | `actuallymentor/sir-claudius:latest` | Pin to a specific image |

## Version pinning

```sh
# Pin to a specific Claude Code version
export CLAUDE_SANDBOX_IMAGE="actuallymentor/sir-claudius:1.0.3"
claudius
```

## Building locally

```sh
# Build with latest Claude Code
docker build -t sir-claudius .

# Pin to a specific version
docker build --build-arg CLAUDE_CODE_VERSION=1.0.58 -t sir-claudius .

# Verify installed version
docker run --rm sir-claudius --version
```
