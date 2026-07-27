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
echo '  ║  Lightweight proxy — no LiteLLM required     ║'
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
BIN_DIR="$HOME/.local/bin"
NPM_PREFIX="${NPM_CONFIG_PREFIX:-$HOME/.npm-global}"
NODE="${TERMUX_NODE:-$PREFIX/bin/node}"
CLAUDE_VERSION="${CLAUDE_CODE_VERSION:-2.1.112}"

mkdir -p "$INSTALL_DIR"
mkdir -p "$HOME/.claude"
mkdir -p "$BIN_DIR"
mkdir -p "$NPM_PREFIX/bin"

# ── Clone opsora-cli jika belum ada ─────────────────────────────
if [[ ! -d "$REPO_DIR/.git" ]]; then
  info "Cloning opsora-cli..."
  git clone --depth 1 https://github.com/Cladius-Weinert/opsora-cli.git "$REPO_DIR" 2>/dev/null \
    || git clone --depth 1 https://github.com/opsora/opsora-cli.git "$REPO_DIR"
fi

# Copy config files
info "Installing configs ke $INSTALL_DIR..."
cp -f "$REPO_DIR/claude-code-termux/nvidia-proxy.py" "$INSTALL_DIR/"
cp -f "$REPO_DIR/claude-code-termux/models.json" "$INSTALL_DIR/"
cp -f "$REPO_DIR/claude-code-termux/settings.json" "$INSTALL_DIR/"
cp -f "$REPO_DIR/claude-code-termux/"*.sh "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/"*.sh

if [[ ! -f "$INSTALL_DIR/secrets.env" ]]; then
  cp "$REPO_DIR/claude-code-termux/secrets.env.example" "$INSTALL_DIR/secrets.env"
  warn "Edit API key: nano $INSTALL_DIR/secrets.env"
fi

resolve_claude_cli() {
  local candidates=(
    "$NPM_PREFIX/lib/node_modules/@anthropic-ai/claude-code/cli.js"
    "$(npm root -g 2>/dev/null)/@anthropic-ai/claude-code/cli.js"
  )
  local c
  for c in "${candidates[@]}"; do
    if [[ -f "$c" ]]; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

fix_claude_shebang() {
  local cli="$1"
  if [[ -f "$cli" ]] && head -1 "$cli" | grep -qE '^#!/usr/bin/env node'; then
    sed -i '1s|#!/usr/bin/env node|#!'"$PREFIX"'/bin/node|' "$cli"
    ok "Shebang diperbaiki di cli.js"
  fi
}

# ── npm global prefix (Termux tidak punya /usr/bin/env) ─────────
if ! grep -q 'npm-global' "$HOME/.bashrc" 2>/dev/null; then
  {
    echo 'export NPM_CONFIG_PREFIX="$HOME/.npm-global"'
    echo 'export PATH="$HOME/.npm-global/bin:$PATH"'
  } >>"$HOME/.bashrc"
fi
export NPM_CONFIG_PREFIX="$NPM_PREFIX"
export PATH="$NPM_PREFIX/bin:$PATH"

# ── Claude Code CLI (pin 2.1.112 — versi JS; native binary rusak di Android)
info "Installing Claude Code @${CLAUDE_VERSION}..."
if ! resolve_claude_cli >/dev/null 2>&1; then
  npm install -g "@anthropic-ai/claude-code@${CLAUDE_VERSION}" \
    || warn "Install manual: npm install -g @anthropic-ai/claude-code@${CLAUDE_VERSION}"
fi

CLAUDE_CLI="$(resolve_claude_cli)" || {
  warn "Claude Code belum terpasang — jalankan fix-claude-termux.sh setelah npm install"
  CLAUDE_CLI="$NPM_PREFIX/lib/node_modules/@anthropic-ai/claude-code/cli.js"
}
fix_claude_shebang "$CLAUDE_CLI"

# ── Claude settings.json ────────────────────────────────────────
if [[ ! -f "$HOME/.claude/settings.json" ]]; then
  cp "$INSTALL_DIR/settings.json" "$HOME/.claude/settings.json"
  ok "Created ~/.claude/settings.json"
else
  warn "~/.claude/settings.json sudah ada — merge manual atau backup dulu"
fi

# ── Shell helpers ───────────────────────────────────────────────
cat >"$BIN_DIR/opsora-gateway" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
exec "$HOME/.opsora/claude-code/start-gateway.sh" "$@"
WRAP
cat >"$BIN_DIR/opsora-model" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
exec "$HOME/.opsora/claude-code/switch-model.sh" "$@"
WRAP
cat >"$BIN_DIR/opsora-claude" <<WRAP
#!/data/data/com.termux/files/usr/bin/bash
INSTALL_DIR="\${OPSORA_CLAUDE_DIR:-\$HOME/.opsora/claude-code}"
[[ -f "\$INSTALL_DIR/secrets.env" ]] && source "\$INSTALL_DIR/secrets.env"
"\$INSTALL_DIR/start-gateway.sh" 2>/dev/null || true
exec "${NODE}" "${CLAUDE_CLI}" "\$@"
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
echo "     opsora-model power      # Llama 3.3 70B — full power"
echo "     opsora-model balanced   # Llama 3.1 70B — sehari-hari"
echo "     opsora-model fast       # Llama 3.1 8B — ringan"
echo ""
echo "  4. Jalankan Claude Code:"
echo "     opsora-claude"
echo ""
echo "Sudah install tapi wrapper error? Jalankan:"
echo "  bash $REPO_DIR/claude-code-termux/fix-claude-termux.sh"
echo ""
echo "Model tersedia: power, balanced, coder, reasoning, nemotron, fast, qwen-plus, qwen-max, local"
echo "Detail: cat $INSTALL_DIR/models.json | jq '.profiles | keys'"
