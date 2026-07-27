#!/data/data/com.termux/files/usr/bin/bash
# Audit all Opsora models against live NVIDIA Integrate API
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
SECRETS="${INSTALL_DIR}/secrets.env"
[[ -f "$SECRETS" ]] && source "$SECRETS"

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "❌ Set NVIDIA_API_KEY in $SECRETS"
  exit 1
fi

KEY="${LITELLM_MASTER_KEY:-sk-opsora-local}"
PORT="${OPSORA_PROXY_PORT:-4000}"

bash "${INSTALL_DIR}/start-gateway.sh" restart
sleep 2

MODELS=(opsora-mini opsora-fast opsora-balanced opsora-power opsora-coder opsora-nemotron)
FAILED=0

echo "=== Opsora Model Audit (via proxy → NVIDIA) ==="
echo ""

for MODEL in "${MODELS[@]}"; do
  echo -n "▶ $MODEL ... "
  START=$(date +%s%N)
  RESP=$(curl -sS -m 45 \
    "http://127.0.0.1:${PORT}/v1/messages" \
    -H "Authorization: Bearer $KEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$MODEL\",\"max_tokens\":16,\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"Reply exactly: OK\"}]}" 2>&1) || true
  END=$(date +%s%N)
  MS=$(( (END - START) / 1000000 ))

  if echo "$RESP" | grep -q '"text"'; then
    TEXT=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['content'][0]['text'][:40])" 2>/dev/null || echo "?")
    echo "✅ ${MS}ms — $TEXT"
  else
    echo "❌ ${MS}ms"
    echo "$RESP" | head -c 200
    echo ""
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "=== Stream test (opsora-fast) ==="
STREAM=$(curl -sSN -m 30 \
  "http://127.0.0.1:${PORT}/v1/messages" \
  -H "Authorization: Bearer $KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"opsora-fast","max_tokens":32,"stream":true,"messages":[{"role":"user","content":"Say hi"}]}' 2>&1 | head -c 400)
if echo "$STREAM" | grep -q "content_block_delta"; then
  echo "✅ Streaming OK"
else
  echo "❌ Streaming failed"
  echo "$STREAM"
  FAILED=$((FAILED + 1))
fi

echo ""
if [[ "$FAILED" -eq 0 ]]; then
  echo "✅ Semua model OK"
else
  echo "❌ $FAILED model gagal — cek gateway.log"
  exit 1
fi
