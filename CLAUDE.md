# AGENTS.md

Sir Claudius: a Docker-based sandbox for running Claude Code. Three files matter:

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the container image (runs as non-root `node` user with sudo, installs Claude Code via native installer) |
| `claudius` | Bash script users run on their host to launch the container |
| `install.sh` | One-line installer that downloads `claudius` and pulls the Docker image |

Supporting files:
- `CONTAINER_AGENTS.md` — gets COPY'd into the container as `AGENTS.md` (for the LLM inside the container, not for you)
- `.dockerignore` — allowlist; any file COPY'd in the Dockerfile must be listed here with `!`

## Verification rules

**After editing `Dockerfile`**: rebuild, verify the image builds successfully, and confirm Claude Code responds to a prompt without errors.

```sh
docker build -t claudius-test .
docker run --rm claudius-test -p "respond with ok"
```

**After editing `claudius`**: verify the script parses and the flags work. If you add, remove, or rename a subcommand, env var, or flag — update the `--help` output to match.

```sh
bash -n claudius && echo "syntax ok"
bash claudius --version
bash claudius --help
```

**After editing `.dockerignore`**: ensure every file referenced by `COPY` in the Dockerfile is allowlisted.
