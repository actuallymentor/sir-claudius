FROM node:24-slim

ARG CLAUDE_CODE_VERSION=""

# System dependencies for Claude Code and MCP servers
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git curl openssh-client jq \
        python3 python3-pip python3-venv \
        bat \
        build-essential \
        bzip2 \
        ca-certificates \
        dnsutils \
        entr \
        fd-find \
        file \
        gnupg \
        htop \
        iputils-ping \
        iproute2 \
        less \
        lsof \
        netcat-openbsd \
        patch \
        procps \
        psmisc \
        ripgrep \
        rsync \
        shellcheck \
        sqlite3 \
        sudo \
        strace \
        tree \
        unzip \
        wget \
        xz-utils \
        zip \
        zstd \
    && ln -s /usr/bin/batcat /usr/local/bin/bat \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

# Let the node user install global npm packages without sudo.
# The base node image sets the prefix to /usr/local (root-owned), which
# blocks `npm install -g` for MCP servers. Point it at a user-writable path.
RUN mkdir -p /home/node/.npm-global \
    && chown node:node /home/node/.npm-global
ENV NPM_CONFIG_PREFIX=/home/node/.npm-global
ENV PATH="/home/node/.npm-global/bin:$PATH"

# uv (Python package runner for MCP servers)
RUN pip3 install --break-system-packages uv

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Binary tools from GitHub releases (arch-aware)
RUN ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in \
        amd64) YQ_ARCH="amd64"; SCC_ARCH="x86_64" ;; \
        arm64) YQ_ARCH="arm64"; SCC_ARCH="arm64" ;; \
        *) echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac \
    # yq — YAML/JSON/XML processor
    && curl -fsSL "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${YQ_ARCH}" \
        -o /usr/local/bin/yq && chmod +x /usr/local/bin/yq \
    # scc — fast code line counter
    && curl -fsSL "https://github.com/boyter/scc/releases/latest/download/scc_Linux_${SCC_ARCH}.tar.gz" \
        | tar xz -C /usr/local/bin scc

# Prepare workspace and config directories (including session paths for bind mounts)
RUN mkdir -p /workspace /home/node/.claude/projects /home/node/.claude/plans /home/node/.claude/todos \
    && chown -R node:node /workspace /home/node/.claude

# Grant node user passwordless sudo for runtime package installs
RUN echo "node ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/node \
    && chmod 440 /etc/sudoers.d/node

# Switch to non-root user — container is the security boundary
USER node
ENV DISABLE_AUTOUPDATER=1
ENV PATH="/home/node/.local/bin:$PATH"

# Git commit identity — baked in so every commit uses the right author
ENV GIT_AUTHOR_NAME="Sir Claudius"
ENV GIT_AUTHOR_EMAIL="actuallymentor/sir-claudius@github.com"
ENV GIT_COMMITTER_NAME="Sir Claudius"
ENV GIT_COMMITTER_EMAIL="actuallymentor/sir-claudius@github.com"

# Install Claude Code via native installer (installs to /home/node/.local/bin)
RUN if [ -n "$CLAUDE_CODE_VERSION" ]; then \
        curl -fsSL https://claude.ai/install.sh | bash -s -- "$CLAUDE_CODE_VERSION"; \
    else \
        curl -fsSL https://claude.ai/install.sh | bash; \
    fi

# Verify Claude Code installed correctly
RUN claude --version

COPY --chown=node:node CONTAINER_AGENTS.md /home/node/AGENTS.md
COPY --chown=node:node entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude"]
