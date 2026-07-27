#!/data/data/com.termux/files/usr/bin/bash
# Opsora Claude Code launcher — resolves cli.js at runtime (not install time)
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
[[ -f "$INSTALL_DIR/secrets.env" ]] && source "$INSTALL_DIR/secrets.env"

export ANTHROPIC_BASE_URL="http://127.0.0.1:4000"
export ANTHROPIC_AUTH_TOKEN="${LITELLM_MASTER_KEY:-sk-opsora-local}"
unset ANTHROPIC_API_KEY
export ANTHROPIC_MODEL="${OPSORA_DEFAULT_MODEL:-opsora-balanced}"
export ANTHROPIC_SMALL_FAST_MODEL="${OPSORA_FAST_MODEL:-opsora-fast}"
export ANTHROPIC_DEFAULT_SONNET_MODEL="opsora-balanced"
export ANTHROPIC_DEFAULT_OPUS_MODEL="opsora-power"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="opsora-fast"
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY="1"
export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS="1"

resolve_claude_cli() {
  local c npm_prefix="${NPM_CONFIG_PREFIX:-$HOME/.npm-global}"
  for c in \
    "$npm_prefix/lib/node_modules/@anthropic-ai/claude-code/cli.js" \
    "$(npm root -g 2>/dev/null)/@anthropic-ai/claude-code/cli.js"; do
    [[ -f "$c" ]] && echo "$c" && return 0
  done
  return 1
}

NODE="${TERMUX_NODE:-$PREFIX/bin/node}"
CLAUDE_CLI="$(resolve_claude_cli)" || {
  echo "❌ Claude Code tidak ditemukan. Jalankan:"
  echo "   npm install -g @anthropic-ai/claude-code@2.1.112"
  exit 1
}

if head -1 "$CLAUDE_CLI" | grep -q '/usr/bin/env node'; then
  sed -i '1s|#!/usr/bin/env node|#!'"$PREFIX"'/bin/node|' "$CLAUDE_CLI"
fi

"$INSTALL_DIR/start-gateway.sh" 2>/dev/null || true
exec "$NODE" "$CLAUDE_CLI" "$@"
