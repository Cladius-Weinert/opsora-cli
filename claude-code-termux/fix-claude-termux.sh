#!/data/data/com.termux/files/usr/bin/bash
# Perbaiki opsora-claude + shebang Claude Code di Termux (tanpa reinstall penuh)
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
BIN_DIR="$HOME/.local/bin"
NODE="${TERMUX_NODE:-$PREFIX/bin/node}"
NPM_PREFIX="${NPM_CONFIG_PREFIX:-$HOME/.npm-global}"

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

fix_shebang() {
  local cli="$1"
  if [[ -f "$cli" ]] && head -1 "$cli" | grep -qE '^#!/usr/bin/env node'; then
    # Single-quoted sed pattern — avoids bash history expansion on '!'
    sed -i '1s|#!/usr/bin/env node|#!'"$PREFIX"'/bin/node|' "$cli"
    echo "✅ Shebang diperbaiki: $cli"
  fi
}

mkdir -p "$BIN_DIR"

CLAUDE_CLI="$(resolve_claude_cli)" || {
  echo "❌ cli.js Claude Code tidak ditemukan."
  echo "   Install: npm install -g @anthropic-ai/claude-code@2.1.112"
  exit 1
}

fix_shebang "$CLAUDE_CLI"

cat >"$BIN_DIR/opsora-claude" <<WRAP
#!/data/data/com.termux/files/usr/bin/bash
INSTALL_DIR="\${OPSORA_CLAUDE_DIR:-\$HOME/.opsora/claude-code}"
[[ -f "\$INSTALL_DIR/secrets.env" ]] && source "\$INSTALL_DIR/secrets.env"
"\$INSTALL_DIR/start-gateway.sh" 2>/dev/null || true
exec "${NODE}" "${CLAUDE_CLI}" "\$@"
WRAP
chmod +x "$BIN_DIR/opsora-claude"

echo "✅ opsora-claude siap"
echo "   Node:  $NODE"
echo "   CLI:   $CLAUDE_CLI"
echo ""
echo "Jalankan: opsora-gateway && opsora-claude"
