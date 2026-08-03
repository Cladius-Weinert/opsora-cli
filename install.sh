#!/usr/bin/env bash
# Opsora CLI Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/opsora/opsora-cli/main/install.sh | bash
#
# This script installs Opsora CLI and its dependencies.
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

echo -e "${BOLD}${CYAN}"
echo '  ╔═══════════════════════════════════════╗'
echo '  ║     OPSORA CLI — Installer v2.0       ║'
echo '  ║   Multi-Provider AI Coding Assistant  ║'
echo '  ╚═══════════════════════════════════════╝'
echo -e "${NC}"

# ── Pre-flight checks ──────────────────────────────────────────

# Check OS
OS="$(uname -s)"
case "$OS" in
    Linux|Darwin)  info "Detected OS: $OS" ;;
    *)             fail "Unsupported OS: $OS. Use Linux or macOS." ;;
esac

# Check Python 3.10+
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
        ok "Python $PY_VERSION found"
    else
        fail "Python 3.10+ required (found $PY_VERSION). Install from https://python.org"
    fi
else
    fail "Python 3 not found. Install from https://python.org"
fi

# Check pip
if python3 -m pip --version &>/dev/null; then
    ok "pip is available"
else
    fail "pip not found. Install: https://pip.pypa.io/en/stable/installation/"
fi

# ── Installation ───────────────────────────────────────────────

INSTALL_DIR="${OPSORA_INSTALL_DIR:-$HOME/.opsora}"
BIN_DIR="${OPSORA_BIN_DIR:-$HOME/.local/bin}"

info "Install directory: $INSTALL_DIR"
info "Binary directory: $BIN_DIR"

# Create directories
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

# Clone or update repository
if [ -d "$INSTALL_DIR/repo" ]; then
    info "Updating existing installation..."
    cd "$INSTALL_DIR/repo"
    git pull --ff-only origin main 2>/dev/null || warn "Git pull failed, using existing files"
else
    info "Cloning Opsora CLI..."
    git clone --depth 1 https://github.com/opsora/opsora-cli.git "$INSTALL_DIR/repo"
fi

# Install Python package
info "Installing Python dependencies..."
cd "$INSTALL_DIR/repo"
python3 -m pip install --quiet --upgrade . 2>/dev/null || {
    warn "pip install failed, installing without editable mode..."
    python3 -m pip install --quiet --upgrade --user . 2>/dev/null || {
        # Fallback: install dependencies manually and symlink
        python3 -m pip install --quiet --user openai rich prompt-toolkit boto3 requests
    }
}

# Create launcher script
cat > "$BIN_DIR/opsora" << 'LAUNCHER'
#!/usr/bin/env bash
# Opsora CLI Launcher
set -euo pipefail

# Source environment if present
if [ -f "$HOME/.opsora_env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$HOME/.opsora_env"
    set +a
fi

# Try installed package first, then local repo
if python3 -c "import opsora_v2" 2>/dev/null; then
    exec python3 -c "from opsora_v2 import main; main()" "$@"
elif [ -f "$HOME/.opsora/repo/opsora_cmd/opsora_v2.py" ]; then
    exec python3 "$HOME/.opsora/repo/opsora_cmd/opsora_v2.py" "$@"
else
    echo "Error: Opsora CLI not found. Reinstall with:"
    echo "  curl -fsSL https://raw.githubusercontent.com/opsora/opsora-cli/main/install.sh | bash"
    exit 1
fi
LAUNCHER
chmod +x "$BIN_DIR/opsora"

# Create opsora2 alias
ln -sf "$BIN_DIR/opsora" "$BIN_DIR/opsora2"

# ── Environment config ────────────────────────────────────────

ENV_FILE="$HOME/.opsora_env"
if [ ! -f "$ENV_FILE" ]; then
    info "Creating environment config at $ENV_FILE"
    cat > "$ENV_FILE" << 'ENVCONFIG'
# Opsora CLI — Provider Configuration
# Add your API keys below. At least one provider is required.
# Docs: https://github.com/opsora/opsora-cli#configure-providers

# NVIDIA NIM (https://build.nvidia.com)
# NVIDIA_API_KEY=your-key-here

# Alibaba DashScope (https://dashscope.aliyun.com)
# DASHSCOPE_API_KEY=your-key-here

# OpenAI (https://platform.openai.com)
# OPENAI_API_KEY=your-key-here

# Tencent TokenHub
# TOKENHUB_API_KEY=your-key-here

# AWS Bedrock (uses AWS credentials, not API key)
# AWS_PROFILE=default
# AWS_DEFAULT_REGION=us-east-1

# Provider priority (comma-separated)
OPSORA_PROVIDER_ORDER=nvidia,alibaba,tokenhub,bedrock,openai,local

# Allow fallback to local Ollama
OPSORA_ALLOW_LOCAL_FALLBACK=true
ENVCONFIG
    ok "Created $ENV_FILE — add your API keys to get started"
else
    info "Existing config found at $ENV_FILE (skipping)"
fi

# ── PATH setup ─────────────────────────────────────────────────

# Ensure bin directory is in PATH
SHELL_RC=""
case "${SHELL:-/bin/bash}" in
    */zsh)  SHELL_RC="$HOME/.zshrc" ;;
    */bash) SHELL_RC="$HOME/.bashrc" ;;
    */fish) SHELL_RC="$HOME/.config/fish/config.fish" ;;
esac

PATH_LINE="export PATH=\"$BIN_DIR:\$PATH\""
if [ -n "$SHELL_RC" ] && [ -f "$SHELL_RC" ]; then
    if ! grep -qF "$BIN_DIR" "$SHELL_RC" 2>/dev/null; then
        echo "" >> "$SHELL_RC"
        echo "# Opsora CLI" >> "$SHELL_RC"
        echo "$PATH_LINE" >> "$SHELL_RC"
        info "Added $BIN_DIR to PATH in $SHELL_RC"
    fi
fi

# ── Done ───────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}✓ Opsora CLI installed successfully!${NC}"
echo ""
echo -e "  ${CYAN}Next steps:${NC}"
echo -e "    1. Add API keys to ${BOLD}~/.opsora_env${NC}"
echo -e "    2. Reload your shell:  ${BOLD}source $SHELL_RC${NC}"
echo -e "    3. Run:                ${BOLD}opsora${NC}"
echo ""
echo -e "  ${CYAN}Docs:${NC} https://github.com/opsora/opsora-cli"
echo ""
