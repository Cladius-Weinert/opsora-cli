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
NODE_MARKER="${INSTALL_DIR}/.node-version"

echo -e "${BOLD}${CYAN}Opsora Claude Code — Termux installer${NC}"

# ── Packages ────────────────────────────────────────────────────
info "Installing Termux packages..."
pkg update -y >/dev/null

BASE_PKGS="python git curl jq"
if command -v node >/dev/null 2>&1; then
  ok "Node sudah terpasang ($(node -v)) — skip nodejs-lts"
  pkg install -y $BASE_PKGS
else
  info "Node belum ada — install nodejs-lts..."
  pkg install -y $BASE_PKGS nodejs-lts 2>/dev/null || pkg install -y $BASE_PKGS nodejs
fi

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

CURRENT_NODE_VER="$(node -v 2>/dev/null || echo "none")"
PREV_NODE_VER="$(cat "$NODE_MARKER" 2>/dev/null || echo "")"
FORCE_NPM_REINSTALL=false
if [[ -n "$PREV_NODE_VER" && "$PREV_NODE_VER" != "$CURRENT_NODE_VER" ]]; then
  FORCE_NPM_REINSTALL=true
  warn "Node berubah ($PREV_NODE_VER → $CURRENT_NODE_VER) — reinstall Claude Code"
fi
echo "$CURRENT_NODE_VER" >"$NODE_MARKER"

info "Installing Claude Code @${CLAUDE_VERSION}..."
if $FORCE_NPM_REINSTALL; then
  npm install -g "@anthropic-ai/claude-code@${CLAUDE_VERSION}"
else
  npm install -g "@anthropic-ai/claude-code@${CLAUDE_VERSION}" 2>/dev/null || true
fi
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

# ── Restart proxy after update ──────────────────────────────────
bash "$INSTALL_DIR/stop-gateway.sh" 2>/dev/null || true

# ── Shell wrappers ──────────────────────────────────────────────
cat >"$BIN_DIR/opsora-gateway" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
exec "$HOME/.opsora/claude-code/start-gateway.sh" "$@"
WRAP

cat >"$BIN_DIR/opsora-model" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
exec "$HOME/.opsora/claude-code/switch-model.sh" "$@"
WRAP

cp -f "$SRC/opsora-claude.sh" "$BIN_DIR/opsora-claude"
chmod +x "$BIN_DIR/opsora-gateway" "$BIN_DIR/opsora-model" "$BIN_DIR/opsora-claude"

grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >>"$HOME/.bashrc"
export PATH="$HOME/.local/bin:$PATH"

# ── Verify ──────────────────────────────────────────────────────
echo ""
info "Verifying gateway..."
if [[ -f "$INSTALL_DIR/secrets.env" ]] && grep -q 'nvapi-' "$INSTALL_DIR/secrets.env"; then
  if bash "$INSTALL_DIR/test-gateway.sh" opsora-balanced 2>&1 | tee /tmp/opsora-gateway-test.log | grep -q '"text"\|event:'; then
    ok "Gateway + NVIDIA model OK (opsora-balanced)"
  else
    warn "Gateway test gagal:"
    tail -15 /tmp/opsora-gateway-test.log 2>/dev/null || true
    warn "Cek log: tail -20 $INSTALL_DIR/gateway.log"
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
