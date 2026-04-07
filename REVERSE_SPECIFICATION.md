# Claudius — Reverse Specification

> A containerised sandbox for running AI coding agents in isolated Docker environments.
>
> This specification captures the complete behaviour of Claudius v0.24.0 — sufficient to reimplement it in any language, for any LLM agent backend. Where behaviour is tied to a specific agent CLI (Claude Code), those coupling points are called out explicitly.

---

## Table of Contents

1. [Overview & Architecture](#1-overview--architecture)
2. [Installation](#2-installation)
3. [CLI Interface](#3-cli-interface)
4. [Execution Modes (Modifiers)](#4-execution-modes-modifiers)
5. [Standalone Commands](#5-standalone-commands)
6. [Container Image](#6-container-image)
7. [Credential Management](#7-credential-management)
8. [Workspace Mounting](#8-workspace-mounting)
9. [Node.js Module Isolation](#9-nodejs-module-isolation)
10. [Session Management](#10-session-management)
11. [Background Execution (tmux)](#11-background-execution-tmux)
12. [Worktree Isolation](#12-worktree-isolation)
13. [Loop / Recurring Prompts](#13-loop--recurring-prompts)
14. [PTY Wrapper & Auto-Accept](#14-pty-wrapper--auto-accept)
15. [Status Line](#15-status-line)
16. [Notifications](#16-notifications)
17. [System Prompt Injection](#17-system-prompt-injection)
18. [Configuration Mounting](#18-configuration-mounting)
19. [Cleanup & Resource Lifecycle](#19-cleanup--resource-lifecycle)
20. [Environment Variables Reference](#20-environment-variables-reference)

---

## 1. Overview & Architecture

Claudius is a **host-side orchestrator** that launches a Docker container pre-loaded with an AI coding agent. The architecture has three layers:

```
┌─────────────────────────────────────────────┐
│  Host (user's machine)                      │
│  ┌───────────────────────────────────────┐  │
│  │  claudius (bash script)               │  │
│  │  - Parses CLI flags & modifiers       │  │
│  │  - Resolves credentials               │  │
│  │  - Constructs docker run invocation   │  │
│  │  - Manages tmux for background mode   │  │
│  │  - Handles worktree merge on exit     │  │
│  └───────────────────────────────────────┘  │
│              │                               │
│              ▼                               │
│  ┌───────────────────────────────────────┐  │
│  │  Docker Container                     │  │
│  │  ┌─────────────────────────────────┐  │  │
│  │  │  entrypoint.sh                  │  │  │
│  │  │  - Marks /workspace git-safe    │  │  │
│  │  │  - Fixes node_modules ownership │  │  │
│  │  │  - Wraps through PTY wrapper    │  │  │
│  │  │    when yolo/loop active        │  │  │
│  │  └─────────────────────────────────┘  │  │
│  │  ┌─────────────────────────────────┐  │  │
│  │  │  auto-accept.py (PTY wrapper)   │  │  │
│  │  │  - Transparent I/O passthrough  │  │  │
│  │  │  - Pattern-matches agent output │  │  │
│  │  │  - Auto-accepts plans (yolo)    │  │  │
│  │  │  - Re-prompts on idle (loop)    │  │  │
│  │  └─────────────────────────────────┘  │  │
│  │  ┌─────────────────────────────────┐  │  │
│  │  │  AI Agent CLI (e.g. claude)     │  │  │
│  │  │  - The actual coding agent      │  │  │
│  │  └─────────────────────────────────┘  │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

### Key Design Principles

1. **Container as security boundary** — the agent has full root-equivalent access inside the container (passwordless sudo) but can only reach the host through explicit bind mounts. This is the primary safety mechanism.
2. **Modifiers are composable** — execution modes (yolo, background, loop, worktree, mudbox, sandbox) can be combined freely, subject to compatibility rules.
3. **Transparent I/O** — the PTY wrapper is invisible to both the user and the agent. All keystrokes and output pass through unchanged; the wrapper only acts on pattern matches.
4. **Credential isolation** — host credentials are copied to writable temp files (never mounted directly) so the container UID can refresh tokens. A sync daemon propagates host-side refreshes.

---

## 2. Installation

### Installer Script

A standalone shell script that:

1. **Requires**: Docker installed and on PATH.
2. **Downloads** the main launcher script from a canonical URL to a temp file.
3. **Installs** to `$INSTALL_PATH` (default: `$HOME/.local/bin/claudius`). Tries direct write, falls back to `sudo`.
4. **Pulls** the pre-built Docker image (warns on failure, doesn't abort — user can rebuild locally).
5. **Checks PATH** — if the install directory isn't on `$PATH`, prints the `export` command the user needs.

### Update Command

The `update` subcommand performs four operations:

1. Downloads the latest launcher script from GitHub (with `cachebust` query param).
2. Compares version strings and replaces the installed script if newer.
3. Pulls the latest Docker image.
4. If `~/.agents` is a git repo, runs `git pull` to update agent preferences.

---

## 3. CLI Interface

### Invocation

```
claudius [command...] [options] [-- agent_args...]
```

Arguments before `--` are parsed by claudius. Arguments after `--`, or flags starting with `-`, are passed through to the agent CLI.

### Argument Parsing

Chainable modifiers are parsed in a loop. Each recognised keyword sets an internal flag and shifts the argument. The loop exits on:
- `--` (explicit separator)
- Any `-*` flag (pass-through to agent)
- Unknown bare word (error with help hint)

Some modifiers accept an optional trailing argument:
- `loop "prompt text"` — the next non-flag, non-modifier word becomes the loop prompt.
- `resume [session_id_or_path]` — the next word becomes the target session.

### Compatibility Rules

| Combination | Result |
|---|---|
| `worktree` + `sandbox` | **Error**: worktree needs a git repo |
| `worktree` + `mudbox` | **Error**: worktree needs write access |
| All other combinations | Valid and composable |

---

## 4. Execution Modes (Modifiers)

### 4.1 Regular (default)

- Workspace mounted read-write at `/workspace`.
- Agent runs with normal interactive permission prompts.
- Autonomy mode: `regular`.

### 4.2 YOLO

- Passes `--dangerously-skip-permissions` (or equivalent) to the agent CLI.
- Enables PTY wrapper for auto-accepting plan approval and permission bypass prompts.
- Injects `skipDangerousModePermissionPrompt: true` into agent settings.
- System prompt instructs the agent to act with maximum autonomy.
- Autonomy mode: `yolo`.

### 4.3 Mudbox

- Workspace mounted **read-only** (`:ro` Docker flag).
- Agent can read all files but cannot modify anything on the host.
- System prompt tells the agent it's in read-only mode.
- Autonomy mode: `mudbox`.

### 4.4 Sandbox

- **No workspace mounted** — `/workspace` is an empty container-local directory.
- Host config/session mounts are all read-only.
- System prompt tells the agent there is no project mounted.
- Autonomy mode: `sandbox`.

### 4.5 Background

- Wraps the entire execution in a persistent **tmux** session.
- The user can close the terminal and the session continues.
- Reattaching: `claudius resume "/path/to/dir"` or `claudius sessions` → manual attach.
- Does **not** enable auto-acceptance by itself (requires `yolo` modifier).
- Autonomy mode: inherits from other modifiers.

### 4.6 Loop

- Activates periodic re-prompting of the agent when idle.
- See [Section 13](#13-loop--recurring-prompts) for full specification.

### 4.7 Worktree

- Creates an isolated git worktree for parallel-safe sessions.
- See [Section 12](#12-worktree-isolation) for full specification.

### 4.8 Continue

- Resumes the most recent agent session.
- Passes `--continue` to the agent CLI.
- Auto-detects if the previous session was a worktree session and re-enters the worktree.

### 4.9 Resume

- Resumes a specific session by ID, or opens the agent's session picker.
- If the argument is an **absolute path**, treats it as a background tmux session and attaches.
- Auto-detects worktree sessions from the session modifiers file.
- Validates that the session ID exists in history before passing to the agent.

---

## 5. Standalone Commands

These exit immediately after execution and cannot be combined with modifiers.

### 5.1 `setup`

Runs the agent's token setup flow, extracts the resulting API token from output using a regex pattern (e.g. `sk-ant-[A-Za-z0-9_-]*`), and saves it to `$HOME/.claude-sandbox-token` with `600` permissions. Strips ANSI escape codes before extraction.

### 5.2 `update`

See [Section 2](#2-installation).

### 5.3 `rebuild`

Runs `docker build --no-cache` using the Dockerfile co-located with the launcher script.

### 5.4 `history`

Lists previous agent sessions from `~/.claude/history.jsonl`.

**Arguments**:
- `[number]` — limit to N sessions (default: 15).
- `all` — show all sessions.
- `"search text"` — filter by prompt or transcript content (case-insensitive).
- `inspect <session_id>` — show full conversation log with tool usage statistics.

**Display**: Session ID, project path, branch, model, agent version, active modifiers, duration, message counts, top 8 tools used, and the `claudius resume` command.

### 5.5 `sessions`

Lists active background tmux sessions. Shows path, start time, runtime, attached/detached status, and attach commands.

### 5.6 `worktree list`

Lists active (unmerged) worktrees with ID, branch, age, session ID, and staleness indicator.

### 5.7 `worktree clean`

Merge and clean up worktrees. Sub-arguments:
- `<id>` — clean a specific worktree.
- `--merged` — remove metadata for already-merged worktrees.
- `--stale` — review worktrees older than 30 days.
- `--all` — merge and clean all active worktrees.

---

## 6. Container Image

### Base Image

Node.js 24 LTS (slim variant).

### System Packages

A comprehensive development toolkit:

| Category | Packages |
|---|---|
| Core | git, curl, openssh-client, jq, bash, sudo |
| Languages | python3, python3-pip, build-essential (gcc, g++, make) |
| Search/Nav | ripgrep, fd-find, tree, bat |
| Network | wget, dnsutils, iputils-ping, iproute2, netcat-openbsd |
| Data | sqlite3, yq (YAML processor) |
| Archives | bzip2, xz-utils, zip, unzip, zstd |
| Debug | htop, procps, psmisc, strace, lsof |
| Misc | shellcheck, rsync, patch, file, less, entr, gnupg, scc (code counter) |

### Debian Symlinks

- `batcat` → `bat`
- `fdfind` → `fd`

### User Configuration

- Non-root user `node` (UID 1000) with passwordless sudo.
- `NPM_CONFIG_PREFIX` set to `$HOME/.npm-global` (user-writable).
- Python package manager `uv` installed via pip.
- GitHub CLI (`gh`) installed from official APT repo.

### Agent Installation

The agent CLI is installed via its official installer script. An optional build arg (`CLAUDE_CODE_VERSION`) pins the version.

### Git Identity

Baked into the image via environment variables:
- Author/Committer name: configurable (e.g. "Sir Claudius")
- Author/Committer email: configurable

### Files Copied into Image

| Source | Destination | Purpose |
|---|---|---|
| `CONTAINER_AGENTS.md` | `~/AGENTS.md` | Tool reference doc for the agent |
| `auto-accept.py` | `/usr/local/bin/auto-accept.py` | PTY wrapper |
| `statusline.sh` | `/usr/local/bin/statusline.sh` | Status line script |
| `entrypoint.sh` | `/usr/local/bin/entrypoint.sh` | Container entrypoint |

### Entry Point

```dockerfile
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude"]
```

The entrypoint:
1. Marks `/workspace` as a git safe directory (handles UID mismatch).
2. Fixes `node_modules` ownership if npm isolation is active.
3. Routes through the PTY wrapper (`auto-accept.py`) if yolo or loop mode is active; otherwise execs the agent directly.

---

## 7. Credential Management

### Authentication Sources (priority order)

1. **`CLAUDE_CODE_OAUTH_TOKEN` env var** — static OAuth token, skips all other detection.
2. **macOS Keychain** — `security find-generic-password -s "Claude Code-credentials"`.
3. **Linux credentials file** — `~/.claude/.credentials.json`.
4. **Setup token file** — `$HOME/.claude-sandbox-token` (from `setup` command).
5. **`ANTHROPIC_API_KEY` env var** — raw API key fallback.

If none found, abort with instructions.

### Two-Phase Resolution

**Phase 1 — Detection** (before pre-flight check):
- Check which credential source exists, without reading the secret.

**Pre-flight Auth Check** (between phases):
- If host agent CLI is available, run `agent -p "respond with ok"` to verify credentials work.
- This can trigger an OAuth token refresh on the host.
- On 401/auth errors: abort with re-login instructions.
- On other errors: warn but continue.

**Phase 2 — Capture** (after pre-flight check):
- Read the (potentially refreshed) credentials into a writable temp file.
- Set temp file permissions to `666` (container needs write access for token refresh).
- Bind-mount the temp file into the container.

### Credential Sync Daemon

A background process on the host that runs every **300 seconds** (5 minutes):

1. Reads the credential source (Keychain or file).
2. Computes SHA-256 hash.
3. If the hash differs from the last-seen hash, writes new content to the temp file **in-place** (preserving the inode — `mv` would break the Docker bind mount).
4. Disowned from the shell (no "Terminated" messages on cleanup).
5. Killed during cleanup.

### Container Credential Mount

```
-v "$CREDS_TMPFILE:/home/node/.claude/.credentials.json"
```

Or, if using a static token:

```
-e "CLAUDE_CODE_OAUTH_TOKEN=$TOKEN"
```

---

## 8. Workspace Mounting

| Mode | Mount |
|---|---|
| Regular | `-v "$(pwd):/workspace"` (read-write) |
| Mudbox | `-v "$(pwd):/workspace:ro"` (read-only) |
| Sandbox | No workspace mount |
| Worktree | See [Section 12](#12-worktree-isolation) |

### Safety Check

Before mounting, warn the user if the current directory resolves to `/` or `$HOME`. Requires interactive confirmation. Skipped in worktree mode (mount target is always in the claudius cache directory).

### Interactive/TTY Detection

If stdin is a TTY (`[ -t 0 ]`), Docker is run with `-it` (interactive + pseudo-TTY). Non-TTY runs omit these flags (enables piped/scripted usage).

---

## 9. Node.js Module Isolation

### Problem

When a macOS host bind-mounts a project into a Linux container, `npm install` writes platform-specific native binaries. The host's `node_modules` becomes corrupted for one platform or the other.

### Solution

A Docker **named volume** overlays `node_modules`:

```
-v "claudius-nm-${hash}:/workspace/node_modules"
```

The volume name includes a 12-character SHA-256 hash of the workspace path for stability across runs.

### Auto-Detection

When `CLAUDIUS_NPM_ISOLATE` is not explicitly set:

1. Scan for Node.js signals: `package.json`, `node_modules`, `.nvmrc`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`.
2. If detected and TTY:
   - Look up previous choice from preference file (`$CLAUDIUS_DIR/nm_preferences`, keyed by workspace hash).
   - Prompt with 5-second timeout for returning users (using their previous answer as default).
   - Prompt with no timeout for first-time users.
   - Persist the choice.
3. If detected and non-TTY: default to isolating (no prompt).

### Ghost Cleanup

Docker creates an empty `node_modules` directory as a mount point even if one didn't exist. On exit, remove it if:
- It didn't exist before the run, AND
- It's empty (rmdir succeeds).

---

## 10. Session Management

### History File

Agent session history lives at `~/.claude/history.jsonl` — one JSON entry per line, tab-separated fields including `sessionId`, `timestamp`, project path, and model.

### Session Modifiers File

Claudius maintains its own metadata at `$CLAUDIUS_DIR/session_modifiers`:

```
SESSION_ID\tMODIFIER_STRING
```

Appended after each session. Stores which modifiers were active, including `worktree:{ID}` tokens for worktree sessions.

### Session State Mounts

| Host Path | Container Path | Purpose |
|---|---|---|
| `~/.claude/projects/` | `/home/node/.claude/projects/` | Conversation transcripts |
| `~/.claude/plans/` | `/home/node/.claude/plans/` | Saved plans |
| `~/.claude/todos/` | `/home/node/.claude/todos/` | Task tracking |
| `~/.claude/history.jsonl` | `/home/node/.claude/history.jsonl` | Session history |

All are mounted read-write in normal mode, read-only in sandbox mode.

### Resume Hint

After a session ends, if new history was written:
1. Extract the session ID from the last line of history.
2. Display a resume command: `claudius [modifiers] resume SESSION_ID`.
3. If in a background tmux session, also write the hint to a file for the outer host process to display after tmux exits.

---

## 11. Background Execution (tmux)

### Architecture

When `background` is active:
1. The launcher detects it's not inside tmux (`CLAUDIUS_IN_TMUX` not set).
2. Creates a tmux session (using the `claudius` socket namespace: `-L claudius`).
3. **Re-executes the entire launcher script** inside tmux with `CLAUDIUS_IN_TMUX=1`.
4. The inner execution proceeds normally (credential resolution, Docker launch, etc.).

### Session Naming

The tmux session name is derived from the resolved working directory:
- Dots → `__DOT__`
- Colons → `__CLN__`
- If longer than 200 characters: hash the path (SHA-256, 16 chars) + basename.

### Environment Forwarding

The following variables are explicitly forwarded into the tmux command string (tmux servers inherit the original env, not the caller's):

- `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_MODEL`
- `CLAUDE_SANDBOX_IMAGE`, `CLAUDE_SESSION_KEY`, `CLAUDE_ORG_ID`
- `CLAUDIUS_DIR`, `CLAUDIUS_NPM_ISOLATE`, `GH_TOKEN`

### Session Reuse

If a tmux session already exists for the directory:
- If the pane is dead (process exited): kill the old session, start fresh.
- If the pane is alive: attach to the existing session.

### tmux Settings

- Mouse: enabled
- Scrollback: 10,000 lines

---

## 12. Worktree Isolation

### Purpose

Run multiple parallel agent sessions on the same repo without conflicts. Each session works on an isolated git worktree with its own branch.

### Branch Naming

```
worktree/claudius-{YYYYMMDD-HHMMSS-XXXX}
```

Where `XXXX` is 2 random hex bytes (for uniqueness within the same second).

### Worktree Setup

1. Verify the current directory is a git repo and not already a worktree.
2. Record the current branch as `ORIGINAL_BRANCH`.
3. Generate the worktree ID and branch name.
4. Run `git worktree add` to create the worktree in `$CLAUDIUS_DIR/worktrees/{ID}/`.
5. Create metadata JSON at `$CLAUDIUS_DIR/worktrees/{ID}.json`.

### Docker Mounts for Worktree

Four mounts to make the worktree appear as a normal repo inside the container:

```
-v "$WORKTREE_DIR:/workspace"
-v "$GIT_DIR:/git-root/.git"
-v "$DOTGIT_TMPFILE:/workspace/.git"         # contains: "gitdir: /git-root/.git/worktrees/{ID}"
-v "$GITDIR_TMPFILE:/git-root/.git/worktrees/{ID}/gitdir"  # contains: "/workspace"
```

### Metadata

```json
{
  "worktreeId": "claudius-20260407-123456-a1b2",
  "branch": "worktree/claudius-20260407-123456-a1b2",
  "originalBranch": "main",
  "workspacePath": "/home/user/.claudius/worktrees/claudius-.../",
  "gitDir": "/path/to/repo/.git",
  "createdAt": "2026-04-07T12:34:56Z",
  "sessionId": null,
  "status": "active"
}
```

- `sessionId` is backfilled after the container exits.
- `status` transitions: `active` → `merged`.

### Post-Session Merge

On container exit:

1. Count commits ahead of the original branch.
2. **No commits** → clean up silently (remove worktree, delete branch, remove metadata).
3. **Has commits**:
   - **Interactive**: Offer `[m]erge` or `[k]eep` (15-second timeout, default merge).
   - **Non-interactive**: auto-merge.
4. **Merge strategy**: Try fast-forward first; fall back to merge commit.
5. **Merge conflict**: Abort the merge, keep the worktree, offer to push the branch to remote. Print manual merge/discard instructions.

### Resume Auto-Detection

When resuming a session:
1. Look up the session ID in the modifiers file.
2. If a `worktree:{ID}` token is found, load the worktree metadata.
3. Validate: status is `active`, directory exists, branch exists.
4. Re-enter the worktree (set all worktree flags and mounts).

### Stale Worktree Warning

Once per day (checked via file mtime), scan worktree metadata for entries older than 30 days. If found, warn the user and suggest `worktree clean --stale`.

---

## 13. Loop / Recurring Prompts

### Prompt Sources (priority order)

1. **Inline string**: `claudius loop "check for errors"` → 30-minute default interval.
2. **Project LOOP.md**: `./LOOP.md` (case-insensitive search).
3. **Global LOOP.md**: `~/.agents/LOOP.md`.

### LOOP.md Format

```markdown
[optional interval line]
first prompt block
===
second prompt block
===idle===
third prompt block (sent after Claude goes idle)
===60s===
fourth prompt block (sent after 60 seconds)
```

**First line** (optional): Sets the global interval.
- Cron: `*/5 * * * *` → every 5 minutes.
- Human-readable: `10 minutes`, `4 hours`, `30 seconds`.
- Default if omitted: **30 minutes** (1800 seconds).

**Block delimiters** (3+ `=` signs):

| Delimiter | Wait Behaviour |
|---|---|
| `===` | Wait the global interval (timed) |
| `===idle===` | Wait for agent idle (120s output silence) AND minimum interval |
| `===60s===` | Wait exactly 60 seconds |
| `===10m===` | Wait exactly 10 minutes |
| `===2h===` | Wait exactly 2 hours |

The last block (no trailing delimiter) wraps around using the global interval.

### Idle Detection

The agent is considered idle when:
- No output for ≥ 120 seconds, AND
- No user input for ≥ 120 seconds, AND
- Minimum interval since last prompt has elapsed.

### Prompt Injection

The PTY wrapper types the prompt text followed by a carriage return (`\r`) into the agent's stdin — simulating the user typing and pressing Enter.

### Multi-Block Cycling

Blocks are sent sequentially (index wraps around). Each block has its own wait condition that determines when the _next_ block fires.

### Deadline File

The PTY wrapper writes `/tmp/claudius-loop-deadline` with either:
- `idle\n` — for idle waits.
- `{epoch_timestamp}\n` — wall-clock deadline for timed waits.

Read by the status line for countdown display.

### Terminal Title Countdown

Updated every second with the remaining time until next prompt:
- Timed: `⏱ HH:MM:SS`
- Idle: `⏱ idle`

Written via OSC escape: `\033]0;{title}\007`

---

## 14. PTY Wrapper & Auto-Accept

### Architecture

A Python script that forks the agent process inside a pseudo-terminal (PTY). The parent multiplexes:
- User stdin → agent PTY master (keystrokes forwarded)
- Agent PTY master → user stdout (output forwarded)
- Pattern matching on agent output (ANSI-stripped)

### ANSI Stripping

Before pattern matching, output is cleaned:
1. Cursor-forward sequences (`\e[NC`) replaced with spaces (preserves word boundaries).
2. All other ANSI escapes stripped (CSI, OSC, charset, keypad mode).

### Trigger Patterns (YOLO mode only)

**Plan triggers** (response: Shift+Tab / `\x1b[Z`):
- `"needs your approval"`

**Permission triggers** (response: Enter / `\r`):
- `"Yes, and bypass permissions"`
- `"Yes, clear context"`

### Accept Delay

1. Pattern detected → send OS notification.
2. Wait 0.5 seconds for TUI redraw.
3. Wait **30 seconds** while keeping I/O flowing.
4. During the 30-second window, any user keystroke **cancels** auto-accept and forwards the keystroke to the agent.
5. If no user input: send the appropriate keystroke.

### Debounce

Minimum 3 seconds between consecutive auto-accepts (prevents double-firing from TUI redraws).

### Output Buffer

A 4096-character sliding window accumulates agent output for pattern matching. Cleared after each trigger match to prevent re-triggering on residual text.

### Terminal Restoration

On exit, the original terminal settings (saved via `tcgetattr`) are restored. Without this, the terminal would remain in raw mode.

### Signal Handling

- **SIGWINCH** (terminal resize): Forwarded to the agent, PTY size updated.
- **SIGINT** (Ctrl+C): Forwarded to the agent.

---

## 15. Status Line

A shell script invoked by the agent CLI as an external command. Outputs a single formatted line.

### Components (left to right, separated by `│`)

1. **Modifiers**: Active session modifiers joined with `·` (e.g. `yolo·background·loop 01:23:45`). Falls back to `claudius` when no modifiers active. Magenta colour.

2. **Repo**: `owner/repo` parsed from `git remote get-url origin`. Blue colour.

3. **Branch**: Current git branch with `⎇` prefix. Green colour.

4. **Usage**: API usage percentage from the provider's usage API.
   - Requires session key and org ID environment variables.
   - Shows percentage + 10-block progress bar (`▓░`) + reset time.
   - 10-level colour gradient: dark green (≤10%) → deep red (>90%).
   - Graceful degradation: shows `Usage: ~` if credentials missing.
   - 5-second timeout on API call.

### Loop Countdown in Modifiers

If a loop deadline file exists:
- Idle wait: shows `loop idle`.
- Timed wait: shows `loop HH:MM:SS` (remaining time).
- No deadline file: shows static interval.

---

## 16. Notifications

### Architecture

A named pipe (FIFO) mounted from host to container:

```
Host:      $NOTIFY_FIFO (mktemp -u + mkfifo)
Container: /tmp/claudius-notify
```

### Producer (inside container)

The PTY wrapper writes one-line messages to the FIFO using non-blocking I/O. Silently skips if no reader or FIFO not mounted.

### Consumer (on host)

A background watcher reads from the FIFO and dispatches:

1. **Terminal bell** (`\a`) — always.
2. **macOS**: `osascript -e 'display notification "..." with title "Claudius"'`.
3. **Linux**: `notify-send "Claudius" "..."`.

Only active when YOLO mode is enabled (the only mode that auto-accepts and thus needs to notify the user).

---

## 17. System Prompt Injection

The launcher constructs a system prompt appended to the agent's invocation. The base prompt:

> You are running inside a [Sandbox Name] Docker container — an isolated sandbox built for coding agents. You have passwordless sudo for any operation that needs root. Your workspace is /workspace (bind-mounted from the host). For a full reference of installed CLI tools and capabilities, read ~/AGENTS.md.

Mode-specific additions:

| Mode | Addition |
|---|---|
| Sandbox | "No workspace mounted. /workspace is empty and container-local. All host files are read-only." |
| Mudbox | "Workspace at /workspace is mounted READ-ONLY. You can read but not modify files." |
| YOLO | "Act with maximum autonomy. Do not ask for confirmation. Prefer doing over asking." |
| Worktree | "Isolated git worktree branched from '{original}' on branch '{branch}'. Commit freely." |

---

## 18. Configuration Mounting

### Agent Config Files

| Host Path | Container Path | Mode |
|---|---|---|
| `~/.claude.json` | `/home/node/.claude.json` | Writable (temp copy) |
| `~/.claude/settings.json` | `/home/node/.claude/settings.json` | Writable (temp copy, patched) |
| `~/.claude/settings.local.json` | `/home/node/.claude/settings.local.json` | Read-only |
| `~/.claude/CLAUDE.md` | `/home/node/.claude/CLAUDE.md` | Read-only |
| `~/.claude/skills/` | `/home/node/.claude/skills/` | Read-only |
| `~/.agents/` | `/home/node/.agents/` | Read-only |

### Workspace Trust Pre-seeding

The `~/.claude.json` copy is patched to include:

```json
{
  "projects": {
    "/workspace": {
      "allowedTools": [],
      "hasTrustDialogAccepted": true
    }
  }
}
```

This skips the first-run trust dialog.

### Settings Patches

The `settings.json` copy is patched to:
1. Set `statusLine.type` = `"command"` and `statusLine.command` = `"bash /usr/local/bin/statusline.sh"`.
2. In YOLO mode: set `skipDangerousModePermissionPrompt` = `true`.

### GitHub CLI Auth

1. Try `gh auth token` on the host → pass as `GH_TOKEN` env var.
2. Fall back to mounting `~/.config/gh:ro`.

### Usage Tracking

If `CLAUDE_SESSION_KEY` and `CLAUDE_ORG_ID` are available (via env vars or parsed from `~/.claude/fetch-claude-usage.swift`), pass them as env vars for the status line.

### Persistent Cache Volumes

Named Docker volumes that survive `--rm`:

| Volume Name | Container Path | Purpose |
|---|---|---|
| `claudius-npm-cache` | `/home/node/.npm` | npm download cache |
| `claudius-npm-global` | `/home/node/.npm-global` | Global npm packages |
| `claudius-uv-cache` | `/home/node/.cache` | Python/uv cache |

### Security

```
--security-opt seccomp=unconfined
```

Loosens seccomp so MCP servers and child processes work without blocked-syscall errors.

---

## 19. Cleanup & Resource Lifecycle

A trap on `EXIT` handles all cleanup:

| Resource | Cleanup Action |
|---|---|
| Credential sync daemon | `kill $PID` |
| Notification watcher | `kill $PID` |
| Notification FIFO | `rm -f` |
| Claude JSON temp file | `rm -f` |
| Settings temp file | `rm -f` |
| Credentials temp file | `rm -f` |
| Update notice temp file | `rm -f` |
| Worktree gitdir temp files | `rm -f` |
| Ghost node_modules directory | `rmdir` (only if it didn't pre-exist and is empty) |

### TUI Artifacts

After the Docker container exits and if stdout is a TTY, clear the terminal to remove agent TUI rendering artifacts.

### Exit Code

The launcher propagates the Docker container's exit code.

---

## 20. Environment Variables Reference

### Input (read by the launcher)

| Variable | Default | Purpose |
|---|---|---|
| `CLAUDE_SANDBOX_IMAGE` | `actuallymentor/sir-claudius:latest` | Docker image to use |
| `CLAUDE_MODEL` | `claude-opus-4-6` | Model identifier |
| `CLAUDE_CODE_OAUTH_TOKEN` | — | OAuth token (skips credential lookup) |
| `ANTHROPIC_API_KEY` | — | API key fallback |
| `CLAUDIUS_NPM_ISOLATE` | auto-detect | `1` = always isolate, `0` = never |
| `CLAUDE_SESSION_KEY` | — | Usage tracking session key |
| `CLAUDE_ORG_ID` | — | Usage tracking organisation ID |
| `CLAUDIUS_DIR` | `~/.claudius` | Cache/metadata directory |
| `GH_TOKEN` | — | GitHub CLI auth token |
| `AUTO_ACCEPT_DEBUG` | `0` | `1` = enable debug logging in PTY wrapper |

### Output (set by the launcher, passed to the container)

| Variable | Values | Purpose |
|---|---|---|
| `AGENT_AUTONOMY_MODE` | `yolo`, `mudbox`, `sandbox`, `regular` | Tells scripts/agents the current mode |
| `CLAUDIUS_YOLO` | `1` | Gates auto-acceptance in PTY wrapper |
| `CLAUDIUS_BACKGROUND` | `1` | Indicates background tmux session |
| `CLAUDIUS_LOOP` | `1` | Gates periodic re-prompting |
| `CLAUDIUS_LOOP_INTERVAL` | seconds (int) | Loop interval for status line |
| `CLAUDIUS_LOOP_PROMPT` | string | Inline loop prompt |
| `CLAUDIUS_NM_ISOLATED` | `1` | Triggers node_modules ownership fix |
| `CLAUDIUS_WORKTREE` | `1` | Indicates worktree mode |
| `CLAUDIUS_WORKTREE_BRANCH` | branch name | Active worktree branch |
| `CLAUDIUS_WORKTREE_ORIGINAL_BRANCH` | branch name | Merge target |
| `CLAUDIUS_MODIFIERS` | space-separated | Human-readable modifier string |
| `CLAUDE_MODEL` | model ID | Passed through to agent |

### Internal (not user-facing)

| Variable | Purpose |
|---|---|
| `CLAUDIUS_IN_TMUX` | Re-execution gate for background mode |
| `CLAUDIUS_TMUX_SESSION` | tmux session name (for resume hint persistence) |

---

## Appendix A: Agent-Agnostic Adaptation Guide

To reimplement Claudius for a different LLM agent, replace these coupling points:

| Coupling Point | Current (Claude Code) | What to Change |
|---|---|---|
| Agent CLI binary | `claude` | Replace with your agent's CLI command |
| Permission skip flag | `--dangerously-skip-permissions` | Your agent's equivalent flag |
| Resume/continue flags | `--continue`, `--resume` | Your agent's session management flags |
| Model flag | `--model $MODEL` | Your agent's model selection flag |
| System prompt flag | `--append-system-prompt` | Your agent's system prompt injection |
| Credential format | `.credentials.json`, Keychain key | Your agent's credential storage |
| Auto-accept patterns | `"needs your approval"`, etc. | Your agent's approval/permission prompt text |
| Auto-accept keystrokes | Shift+Tab (`\x1b[Z`), Enter (`\r`) | Your agent's acceptance keys |
| Session history file | `~/.claude/history.jsonl` | Your agent's history format/location |
| Config files | `.claude.json`, `settings.json` | Your agent's config structure |
| Trust pre-seeding | `hasTrustDialogAccepted` | Your agent's workspace trust mechanism |
| Settings patches | `statusLine`, `skipDangerousModePermissionPrompt` | Your agent's settings schema |
| Token pattern | `sk-ant-[A-Za-z0-9_-]*` | Your agent's token format |
| Usage API | `claude.ai/api/organizations/{id}/usage` | Your provider's usage API |

Everything else — Docker orchestration, worktree management, tmux wrapping, credential sync, node_modules isolation, LOOP.md parsing — is agent-agnostic and can be reused as-is.

## Appendix B: Glossary

| Term | Meaning |
|---|---|
| **Modifier** | A composable execution mode keyword (yolo, background, loop, etc.) |
| **PTY wrapper** | The `auto-accept.py` script that interposes between the user and the agent |
| **Credential sync daemon** | Background process that refreshes bind-mounted credentials from host |
| **Ghost directory** | Empty directory Docker creates as a mount point for named volumes |
| **FIFO** | Named pipe used for cross-container notification delivery |
| **Session modifiers file** | Claudius's own metadata linking session IDs to the modifiers used |
