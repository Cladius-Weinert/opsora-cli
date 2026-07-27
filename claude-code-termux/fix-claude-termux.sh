#!/data/data/com.termux/files/usr/bin/bash
# Quick repair for existing Termux installs
set -euo pipefail

REPO_DIR="${OPSORA_REPO_DIR:-$HOME/opsora-cli}"
INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
BIN_DIR="$HOME/.local/bin"
SRC="${REPO_DIR}/claude-code-termux"

mkdir -p "$BIN_DIR" "$INSTALL_DIR"

# Update scripts + proxy from repo when available
if [[ -d "$SRC" ]]; then
  cp -f "$SRC/nvidia-proxy.py" "$SRC/settings.json" "$SRC/models.json" "$SRC/"*.sh "$INSTALL_DIR/" 2>/dev/null || true
  chmod +x "$INSTALL_DIR/"*.sh 2>/dev/null || true
fi

resolve_claude_cli() {
  local c npm_prefix="${NPM_CONFIG_PREFIX:-$HOME/.npm-global}"
  for c in \
    "$npm_prefix/lib/node_modules/@anthropic-ai/claude-code/cli.js" \
    "$(npm root -g 2>/dev/null)/@anthropic-ai/claude-code/cli.js"; do
    [[ -f "$c" ]] && echo "$c" && return 0
  done
  return 1
}

CLAUDE_CLI="$(resolve_claude_cli)" || {
  echo "📦 Claude Code tidak ditemukan — install @2.1.112..."
  export NPM_CONFIG_PREFIX="${NPM_CONFIG_PREFIX:-$HOME/.npm-global}"
  export PATH="$NPM_CONFIG_PREFIX/bin:$PATH"
  npm install -g @anthropic-ai/claude-code@2.1.112 || {
    echo "❌ npm install gagal"
    exit 1
  }
  CLAUDE_CLI="$(resolve_claude_cli)" || { echo "❌ cli.js tidak ditemukan"; exit 1; }
}

if head -1 "$CLAUDE_CLI" | grep -q '/usr/bin/env node'; then
  sed -i '1s|#!/usr/bin/env node|#!'"$PREFIX"'/bin/node|' "$CLAUDE_CLI"
fi

[[ -f "$INSTALL_DIR/apply-settings.sh" ]] && bash "$INSTALL_DIR/apply-settings.sh" \
  || [[ -f "$SRC/apply-settings.sh" ]] && bash "$SRC/apply-settings.sh"

if [[ -f "$SRC/opsora-claude.sh" ]]; then
  cp -f "$SRC/opsora-claude.sh" "$BIN_DIR/opsora-claude"
else
  echo "❌ opsora-claude.sh tidak ditemukan di repo — pull opsora-cli terbaru"
  exit 1
fi
chmod +x "$BIN_DIR/opsora-claude"

bash "$INSTALL_DIR/stop-gateway.sh" 2>/dev/null || true
bash "$INSTALL_DIR/start-gateway.sh" restart 2>/dev/null || true

echo "✅ Fix selesai. Jalankan: opsora-claude"
