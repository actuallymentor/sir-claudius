#!/bin/sh
set -e

# -----------------------------------------------------------
# install.sh — Install or update claudius
# -----------------------------------------------------------

INSTALL_PATH="${INSTALL_PATH:-$HOME/.local/bin/claudius}"
REPO_URL="https://raw.githubusercontent.com/actuallymentor/sir-claudius/main/claudius"
IMAGE="${CLAUDE_SANDBOX_IMAGE:-actuallymentor/sir-claudius:latest}"

echo "Installing claudius to $INSTALL_PATH..."

# Check if docker is available
if ! command -v docker > /dev/null 2>&1; then
    echo "Error: docker is not installed or not in PATH" >&2
    echo "Please install Docker first: https://docs.docker.com/get-docker/" >&2
    exit 1
fi

# Download the latest claudius script
echo "Downloading latest claudius script from GitHub..."
TEMP_FILE=$(mktemp)

# Clean up temp file on exit or interrupt
cleanup() {
    rm -f "$TEMP_FILE"
}
trap cleanup EXIT INT TERM

if ! curl -fsSL --connect-timeout 10 --max-time 30 "$REPO_URL" -o "$TEMP_FILE"; then
    echo "Error: Failed to download claudius script from $REPO_URL" >&2
    exit 1
fi

# Ensure the target directory exists (after download succeeds, before install)
mkdir -p "$(dirname "$INSTALL_PATH")"

# Try to install to the target path — try directly first, fall back to sudo
# Note: [ -w ] can lie on macOS (admin group + SIP), so we just try and catch failure
if mv "$TEMP_FILE" "$INSTALL_PATH" 2>/dev/null && chmod +x "$INSTALL_PATH" 2>/dev/null; then
    true
elif command -v sudo > /dev/null 2>&1; then
    echo "Installing to $INSTALL_PATH requires elevated permissions..."
    if ! sudo mv "$TEMP_FILE" "$INSTALL_PATH" || ! sudo chmod +x "$INSTALL_PATH"; then
        echo "Error: Failed to install to $INSTALL_PATH" >&2
        exit 1
    fi
else
    echo "Error: Cannot write to $(dirname "$INSTALL_PATH") and sudo is not available" >&2
    exit 1
fi

echo "✓ Installed claudius to $INSTALL_PATH"

# Pull the latest Docker image
echo ""
echo "Pulling latest Docker image ($IMAGE)..."
if docker pull "$IMAGE"; then
    echo "✓ Docker image updated"
else
    echo "Warning: Failed to pull image (you may need to rebuild locally)" >&2
fi

echo ""
echo "Installation complete!"

# Check if the install directory is on PATH
INSTALL_DIR="$(dirname "$INSTALL_PATH")"
case ":$PATH:" in
    *":$INSTALL_DIR:"*) ;;
    *)
        echo "Note: $INSTALL_DIR is not on your PATH."
        echo "Add it with:"
        echo "  export PATH=\"$INSTALL_DIR:\$PATH\""
        echo ""
        echo "To make it permanent, add that line to your shell profile (~/.bashrc, ~/.zshrc, etc.)"
        echo ""
        ;;
esac

echo "Run: claudius setup   (to authenticate)"
echo "  or: claudius        (to start)"
