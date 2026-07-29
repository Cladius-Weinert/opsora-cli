#!/data/data/com.termux/files/usr/bin/bash
# Test gateway + NVIDIA model connectivity
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
SECRETS="${INSTALL_DIR}/secrets.env"
PORT="${OPSORA_PROXY_PORT:-4000}"

[[ -f "$SECRETS" ]] && source "$SECRETS"

bash "${INSTALL_DIR}/start-gateway.sh" restart

MODEL="${1:-opsora-fast}"
KEY="${LITELLM_MASTER_KEY:-sk-opsora-local}"
FAILED=0

test_request() {
  local label="$1"
  local stream="$2"
  local tmp
  tmp="$(mktemp)"

  echo "▶ Testing model: $MODEL ($label)"
  local http_code
  http_code=$(curl -sS -o "$tmp" -w "%{http_code}" \
    "http://127.0.0.1:${PORT}/v1/messages" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $KEY" \
    -H "anthropic-version: 2023-06-01" \
    -d "{
      \"model\": \"$MODEL\",
      \"max_tokens\": 64,
      \"stream\": $stream,
      \"messages\": [{\"role\": \"user\", \"content\": \"Reply with exactly: OK\"}]
    }" 2>"$tmp.err") || true

  if [[ "$http_code" == "200" ]]; then
    head -c 500 "$tmp"
    echo ""
    if [[ "$stream" == "true" ]]; then
      grep -q "event:" "$tmp" || {
        echo "❌ Stream response missing SSE events"
        FAILED=1
      }
    else
      grep -q '"text"' "$tmp" || {
        echo "❌ JSON response missing text content"
        FAILED=1
      }
    fi
  else
    echo "❌ HTTP $http_code"
    [[ -s "$tmp" ]] && cat "$tmp"
    [[ -s "$tmp.err" ]] && cat "$tmp.err" >&2
    FAILED=1
  fi

  rm -f "$tmp" "$tmp.err"
}

test_request "non-stream" "false"
test_request "stream" "true"

if [[ "$FAILED" -eq 0 ]]; then
  echo "✅ Test selesai"
else
  echo "❌ Gateway test gagal — cek: tail -20 ${INSTALL_DIR}/gateway.log"
  exit 1
fi
