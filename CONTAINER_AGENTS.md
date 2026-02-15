# Agent Tools Reference

This container is purpose-built for LLM coding agents. Below is a categorised reference of every tool available, plus guidance on installing project-specific tools on demand.

You are running as the `node` user (non-root) with **passwordless sudo** available. Use `sudo` for any operation that requires root privileges (installing system packages, writing to system directories, etc.).

---

## Code Search & Navigation

| Command | Description |
|---|---|
| `rg` (ripgrep) | Fastest recursive code search. Respects `.gitignore`. Use `rg -t js 'pattern'` to filter by type. |
| `fd` | Fast file finder. Respects `.gitignore`. Use `fd 'pattern'` or `fd -e jsx` to find by extension. |
| `tree` | Print directory structure. Use `tree -L 2` to limit depth, `tree -I node_modules` to exclude. |
| `bat` | File viewer with syntax highlighting and line numbers. Use `bat src/index.js -r 10:20` for ranges. |
| `scc` | Fast code line counter with complexity analysis. Run `scc` in a repo root for a full summary. |
| `grep` | Standard pattern search. Prefer `rg` for speed, but `grep` is available for scripts that expect it. |
| `find` | Standard file finder. Prefer `fd` for speed and `.gitignore` support. |

## Version Control

| Command | Description |
|---|---|
| `git` | Full Git CLI. |
| `gh` | GitHub CLI — PRs, issues, releases, API calls. Authenticate via `GH_TOKEN` env var. |
| `patch` | Apply unified diff / patch files. |
| `diff` | Compare files and directories. |

## Languages & Runtimes

| Command | Description |
|---|---|
| `node` / `npm` / `npx` | Node.js 24 LTS with full npm ecosystem. |
| `python3` / `pip3` | Python 3 with pip. Use `uv` for fast installs. |
| `uv` | Extremely fast Python package installer and runner. Use `uvx` to run CLI tools without install. |
| `gcc` / `g++` / `make` | C/C++ toolchain via `build-essential`. Required by many npm/pip native modules. |

## Data Processing

| Command | Description |
|---|---|
| `jq` | JSON processor. Pipe JSON into `jq '.key'` for extraction/transformation. |
| `yq` | YAML/JSON/XML/TOML processor. Same syntax as `jq` but for YAML. Use `yq '.key' file.yaml`. |
| `sqlite3` | Query and modify SQLite databases. Use `sqlite3 db.sqlite '.tables'` to inspect. |
| `sed` / `awk` / `perl` | Text stream processing. |

## Shell & Script Quality

| Command | Description |
|---|---|
| `shellcheck` | Static analysis for shell scripts. Run `shellcheck script.sh` to catch bugs. |
| `bash` | Bash 5 shell. |

## Archives & Compression

| Command | Description |
|---|---|
| `tar` | Archive tool. Supports `.tar`, `.tar.gz`, `.tar.xz`, `.tar.bz2`, `.tar.zst`. |
| `gzip` / `gunzip` | Standard gzip compression. |
| `bzip2` / `bunzip2` | Bzip2 compression. |
| `xz` / `unxz` | XZ compression (common in GitHub releases). |
| `zstd` / `unzstd` | Zstandard — fast compression, used in build caches. |
| `zip` / `unzip` | ZIP archives. |

## Network & Connectivity

| Command | Description |
|---|---|
| `curl` | HTTP client. Supports all methods, headers, auth, file uploads. |
| `wget` | Simple file downloader. Use `wget -q URL` for quiet downloads. |
| `ping` | Basic connectivity test. |
| `dig` / `nslookup` | DNS resolution debugging. |
| `nc` (netcat) | Check if ports are open: `nc -zv host 8080`. Raw TCP/UDP connections. |
| `ip` / `ss` | Network interfaces (`ip addr`) and socket stats (`ss -tlnp`). |

## Process & System Debugging

| Command | Description |
|---|---|
| `ps` | List running processes. Use `ps aux` for full listing. |
| `htop` | Interactive process monitor with CPU/memory stats. |
| `top` / `free` / `vmstat` | System resource monitoring (via `procps`). |
| `strace` | Trace system calls. Use `strace -f -e trace=network command` to debug. |
| `lsof` | List open files. Use `lsof -i :3000` to find what's using a port. |
| `killall` / `fuser` | Kill processes by name or find processes using a file/port (via `psmisc`). |

## File & Crypto Utilities

| Command | Description |
|---|---|
| `file` | Identify file types. Use `file unknown_binary` to check before processing. |
| `rsync` | Efficient file copy/sync. Use `rsync -av src/ dest/` for mirroring. |
| `openssl` | TLS/SSL toolkit, certificate inspection, hashing. |
| `gpg` | GPG signature verification for downloads. |
| `ssh` / `scp` | Remote access and secure file transfer. |
| `less` | Pager for browsing large output or git diffs. |

## File Watching

| Command | Description |
|---|---|
| `entr` | Re-run commands when files change. Use `find . -name '*.js' \| entr npm test`. |

---

## Install on Demand

You have **passwordless sudo** access. Additional dependencies not included in the base image can be installed at runtime with `sudo apt-get update && sudo apt-get install -y --no-install-recommends <package>`. For binaries not in APT, use `curl` to download from GitHub releases or official sources, then `sudo mv` them into `/usr/local/bin/`. Clean up with `sudo rm -rf /var/lib/apt/lists/*` after APT installs to keep the layer small.

---

## MCP Servers

MCP (Model Context Protocol) servers extend agent capabilities with external tools and data sources. They run as sidecar processes that the agent communicates with over stdio or HTTP.

### Installing MCP servers

Most MCP servers are published as npm or Python packages:

```bash
# npm-based MCP server
npm install -g @modelcontextprotocol/server-filesystem

# npm-based MCP server installed with sudo (if global install requires root)
sudo npm install -g @modelcontextprotocol/server-filesystem

# Python-based MCP server (using uv for speed)
uv pip install mcp-server-sqlite

# Python-based MCP server installed with sudo
sudo uv pip install mcp-server-sqlite
```

### Configuring MCP servers

Use the `claude mcp` CLI to add servers:

```bash
# Add a stdio-based server
claude mcp add --transport stdio --scope user my-server -- npx -y @modelcontextprotocol/server-filesystem /workspace

# Add a remote HTTP server
claude mcp add --transport http --scope user my-api https://example.com/mcp

# List configured servers
claude mcp list
```

For project-shared config, create `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "./data.db"]
    }
  }
}
```

### Tips

- Use `npx -y` or `uvx` to run MCP servers without a global install step
- MCP servers launched via stdio are ephemeral — they start and stop with the agent session
- Check the [MCP server registry](https://github.com/modelcontextprotocol/servers) for community-maintained servers
