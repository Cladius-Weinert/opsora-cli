#!/data/data/com.termux/files/usr/bin/bash
# Test gateway + NVIDIA model connectivity
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
SECRETS="${INSTALL_DIR}/secrets.env"
PORT="${OPSORA_PROXY_PORT:-4000}"

[[ -f "$SECRETS" ]] && source "$SECRETS"

"$INSTALL_DIR/start-gateway.sh"

MODEL="${1:-opsora-fast}"
KEY="${LITELLM_MASTER_KEY:-sk-opsora-local}"

echo "▶ Testing model: $MODEL (non-stream)"
curl -sf "http://127.0.0.1:${PORT}/v1/messages" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d "{
    \"model\": \"$MODEL\",
    \"max_tokens\": 64,
    \"messages\": [{\"role\": \"user\", \"content\": \"Reply with exactly: OK\"}]
  }" | head -c 500

echo ""
echo "▶ Testing model: $MODEL (stream)"
curl -sfN "http://127.0.0.1:${PORT}/v1/messages" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d "{
    \"model\": \"$MODEL\",
    \"max_tokens\": 64,
    \"stream\": true,
    \"messages\": [{\"role\": \"user\", \"content\": \"Say hi\"}]
  }" | head -c 800

echo ""
echo "✅ Test selesai"
