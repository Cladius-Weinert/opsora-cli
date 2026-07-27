#!/data/data/com.termux/files/usr/bin/bash
# Full Opsora Claude Code setup for Termux — run once, then: opsora-claude
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }

REPO_URL="${OPSORA_REPO_URL:-https://github.com/Cladius-Weinert/opsora-cli.git}"
REPO_DIR="${OPSORA_REPO_DIR:-$HOME/opsora-cli}"
INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
BIN_DIR="$HOME/.local/bin"
NPM_PREFIX="${NPM_CONFIG_PREFIX:-$HOME/.npm-global}"
NODE="${TERMUX_NODE:-$PREFIX/bin/node}"
CLAUDE_VERSION="${CLAUDE_CODE_VERSION:-2.1.112}"

echo -e "${BOLD}${CYAN}Opsora Claude Code — Termux installer${NC}"

# ── Packages ────────────────────────────────────────────────────
info "Installing Termux packages..."
pkg update -y >/dev/null
pkg install -y python git curl jq nodejs-lts 2>/dev/null || pkg install -y python git curl jq nodejs

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$NPM_PREFIX/bin" "$HOME/.claude"

# ── Repo ────────────────────────────────────────────────────────
if [[ ! -d "$REPO_DIR/.git" ]]; then
  info "Cloning opsora-cli..."
  git clone --depth 1 "$REPO_URL" "$REPO_DIR"
else
  info "Updating opsora-cli..."
  git -C "$REPO_DIR" pull --ff-only 2>/dev/null || true
fi

SRC="$REPO_DIR/claude-code-termux"
cp -f "$SRC/nvidia-proxy.py" "$SRC/settings.json" "$SRC/models.json" "$SRC/"*.sh "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/"*.sh

if [[ ! -f "$INSTALL_DIR/secrets.env" ]]; then
  cp "$SRC/secrets.env.example" "$INSTALL_DIR/secrets.env"
fi
if [[ -n "${NVIDIA_API_KEY:-}" ]]; then
  if grep -q '^export NVIDIA_API_KEY=' "$INSTALL_DIR/secrets.env"; then
    sed -i "s|^export NVIDIA_API_KEY=.*|export NVIDIA_API_KEY=${NVIDIA_API_KEY}|" "$INSTALL_DIR/secrets.env"
  else
    echo "export NVIDIA_API_KEY=${NVIDIA_API_KEY}" >>"$INSTALL_DIR/secrets.env"
  fi
  ok "NVIDIA_API_KEY disimpan ke secrets.env"
elif ! grep -q 'nvapi-' "$INSTALL_DIR/secrets.env" 2>/dev/null; then
  warn "Edit API key: nano $INSTALL_DIR/secrets.env"
fi

# ── npm global ────────────────────────────────────────────────────
grep -q 'npm-global' "$HOME/.bashrc" 2>/dev/null || {
  echo 'export NPM_CONFIG_PREFIX="$HOME/.npm-global"' >>"$HOME/.bashrc"
  echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >>"$HOME/.bashrc"
}
export NPM_CONFIG_PREFIX="$NPM_PREFIX"
export PATH="$NPM_PREFIX/bin:$PATH"

resolve_claude_cli() {
  local c
  for c in \
    "$NPM_PREFIX/lib/node_modules/@anthropic-ai/claude-code/cli.js" \
    "$(npm root -g 2>/dev/null)/@anthropic-ai/claude-code/cli.js"; do
    [[ -f "$c" ]] && echo "$c" && return 0
  done
  return 1
}

info "Installing Claude Code @${CLAUDE_VERSION}..."
npm install -g "@anthropic-ai/claude-code@${CLAUDE_VERSION}" 2>/dev/null || true
CLAUDE_CLI="$(resolve_claude_cli)" || {
  echo "❌ Claude Code gagal install. Coba: npm install -g @anthropic-ai/claude-code@${CLAUDE_VERSION}"
  exit 1
}

# Fix shebang (single quotes — avoid bash ! expansion)
if head -1 "$CLAUDE_CLI" | grep -q '/usr/bin/env node'; then
  sed -i '1s|#!/usr/bin/env node|#!'"$PREFIX"'/bin/node|' "$CLAUDE_CLI"
  ok "Shebang cli.js diperbaiki"
fi

# ── Apply gateway settings (force overwrite) ────────────────────
bash "$INSTALL_DIR/apply-settings.sh"

# ── Shell wrappers ──────────────────────────────────────────────
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

# Force NVIDIA gateway — override claude.ai OAuth
export ANTHROPIC_BASE_URL="http://127.0.0.1:4000"
export ANTHROPIC_AUTH_TOKEN="\${LITELLM_MASTER_KEY:-sk-opsora-local}"
unset ANTHROPIC_API_KEY
export ANTHROPIC_MODEL="\${OPSORA_DEFAULT_MODEL:-opsora-balanced}"
export ANTHROPIC_SMALL_FAST_MODEL="\${OPSORA_FAST_MODEL:-opsora-fast}"
export ANTHROPIC_DEFAULT_SONNET_MODEL="opsora-balanced"
export ANTHROPIC_DEFAULT_OPUS_MODEL="opsora-power"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="opsora-fast"
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY="1"
export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS="1"

"\$INSTALL_DIR/start-gateway.sh" 2>/dev/null || true
exec "${NODE}" "${CLAUDE_CLI}" "\$@"
WRAP

chmod +x "$BIN_DIR/opsora-gateway" "$BIN_DIR/opsora-model" "$BIN_DIR/opsora-claude"

grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >>"$HOME/.bashrc"
export PATH="$HOME/.local/bin:$PATH"

# ── Verify ──────────────────────────────────────────────────────
echo ""
info "Verifying gateway..."
if [[ -f "$INSTALL_DIR/secrets.env" ]] && grep -q 'nvapi-' "$INSTALL_DIR/secrets.env"; then
  bash "$INSTALL_DIR/start-gateway.sh"
  sleep 2
  if bash "$INSTALL_DIR/test-gateway.sh" opsora-fast 2>/dev/null | grep -q '"text"'; then
    ok "Gateway + NVIDIA model OK"
  else
    warn "Gateway test gagal — cek: tail ~/.opsora/claude-code/gateway.log"
  fi
else
  warn "NVIDIA_API_KEY belum diisi di $INSTALL_DIR/secrets.env"
fi

echo ""
ok "Install selesai!"
echo ""
echo "  1. Isi API key (jika belum):  nano $INSTALL_DIR/secrets.env"
echo "  2. Jalankan Claude Code:      opsora-claude"
echo "  3. Di dalam Claude, cek:      /status"
echo "     → harus ada 'Anthropic base URL: http://127.0.0.1:4000'"
echo "     → Auth token: ANTHROPIC_AUTH_TOKEN"
echo "  4. Pilih model:               /model → opsora-balanced"
echo ""
echo "Kalau masih 'API Usage Billing', ketik /logout lalu opsora-claude lagi."
