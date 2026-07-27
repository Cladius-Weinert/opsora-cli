#!/data/data/com.termux/files/usr/bin/bash
# Opsora — Claude Code + NVIDIA models untuk Termux (Android)
# Install: curl -fsSL .../install-termux.sh | bash
set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }

echo -e "${BOLD}${CYAN}"
echo '  ╔══════════════════════════════════════════════╗'
echo '  ║  OPSORA — Claude Code + NVIDIA (Termux)      ║'
echo '  ║  Full-power models via LiteLLM gateway       ║'
echo '  ╚══════════════════════════════════════════════╝'
echo -e "${NC}"

# ── Termux packages ─────────────────────────────────────────────
info "Updating Termux packages..."
pkg update -y
pkg install -y python git curl wget jq openssh

# Node.js untuk Claude Code (LTS jika tersedia)
if ! command -v node >/dev/null 2>&1; then
  pkg install -y nodejs-lts || pkg install -y nodejs
fi
ok "Node $(node -v 2>/dev/null || echo '?') / Python $(python3 -V)"

# ── Install dirs ────────────────────────────────────────────────
INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
REPO_DIR="${OPSORA_REPO_DIR:-$HOME/opsora-cli}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$INSTALL_DIR"
mkdir -p "$HOME/.claude"
mkdir -p "$HOME/.local/bin"

# ── Clone opsora-cli jika belum ada ─────────────────────────────
if [[ ! -d "$REPO_DIR/.git" ]]; then
  info "Cloning opsora-cli..."
  git clone --depth 1 https://github.com/Cladius-Weinert/opsora-cli.git "$REPO_DIR" 2>/dev/null \
    || git clone --depth 1 https://github.com/opsora/opsora-cli.git "$REPO_DIR"
fi

# Copy config files
info "Installing configs ke $INSTALL_DIR..."
cp -f "$REPO_DIR/claude-code-termux/litellm-config.yaml" "$INSTALL_DIR/"
cp -f "$REPO_DIR/claude-code-termux/models.json" "$INSTALL_DIR/"
cp -f "$REPO_DIR/claude-code-termux/settings.json" "$INSTALL_DIR/"
cp -f "$REPO_DIR/claude-code-termux/"*.sh "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/"*.sh

if [[ ! -f "$INSTALL_DIR/secrets.env" ]]; then
  cp "$REPO_DIR/claude-code-termux/secrets.env.example" "$INSTALL_DIR/secrets.env"
  warn "Edit API key: nano $INSTALL_DIR/secrets.env"
fi

# ── Python: LiteLLM gateway ─────────────────────────────────────
info "Installing LiteLLM..."
pip install --upgrade pip
pip install 'litellm[proxy]' httpx

# ── Claude Code CLI ─────────────────────────────────────────────
if ! command -v claude >/dev/null 2>&1; then
  info "Installing Claude Code..."
  npm install -g @anthropic-ai/claude-code 2>/dev/null \
    || curl -fsSL https://claude.ai/install.sh | bash 2>/dev/null \
    || warn "Install Claude Code manual: npm i -g @anthropic-ai/claude-code"
fi

# ── Claude settings.json ────────────────────────────────────────
if [[ ! -f "$HOME/.claude/settings.json" ]]; then
  cp "$INSTALL_DIR/settings.json" "$HOME/.claude/settings.json"
  ok "Created ~/.claude/settings.json"
else
  warn "~/.claude/settings.json sudah ada — merge manual atau backup dulu"
fi

# ── Shell helpers ───────────────────────────────────────────────
BIN_DIR="$HOME/.local/bin"
cat >"$BIN_DIR/opsora-gateway" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
exec "$HOME/.opsora/claude-code/start-gateway.sh" "$@"
WRAP
cat >"$BIN_DIR/opsora-model" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
exec "$HOME/.opsora/claude-code/switch-model.sh" "$@"
WRAP
cat >"$BIN_DIR/opsora-claude" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
[[ -f "$INSTALL_DIR/secrets.env" ]] && source "$INSTALL_DIR/secrets.env"
"$INSTALL_DIR/start-gateway.sh" 2>/dev/null || true
exec claude "$@"
WRAP
chmod +x "$BIN_DIR/opsora-gateway" "$BIN_DIR/opsora-model" "$BIN_DIR/opsora-claude"

# PATH
if ! grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >>"$HOME/.bashrc"
fi
export PATH="$HOME/.local/bin:$PATH"

# ── Done ──────────────────────────────────────────────────────
echo ""
ok "Install selesai!"
echo ""
echo "Langkah berikutnya:"
echo "  1. Isi NVIDIA API key:"
echo "     nano $INSTALL_DIR/secrets.env"
echo ""
echo "  2. Start gateway:"
echo "     opsora-gateway"
echo ""
echo "  3. Pilih model (opsional):"
echo "     opsora-model balanced   # Llama 3.1 70B — verified"
echo "     opsora-model coder      # DeepSeek V4 Pro — coding"
echo "     opsora-model nano       # Nemotron Nano — ringan di HP"
echo ""
echo "  4. Setup agent stack (memory, cache, skills):"
echo "     bash $REPO_DIR/claude-code-termux/setup-agent-stack.sh"
echo ""
echo "  5. Jalankan Claude Code:"
echo "     opsora-claude"
echo "     # atau: claude"
echo ""
echo "Model tersedia: balanced, fast, power, coder, reasoning, nemotron, nano, qwen-plus, local"
echo "Detail: cat $INSTALL_DIR/models.json | jq '.profiles | keys'"
