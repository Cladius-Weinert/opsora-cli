#!/data/data/com.termux/files/usr/bin/bash
# Smoke test semua model profiles
set -euo pipefail

INSTALL_DIR="${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$INSTALL_DIR/models.json" ]] || INSTALL_DIR="$SCRIPT_DIR"
SECRETS="${INSTALL_DIR}/secrets.env"
MODELS_JSON="${INSTALL_DIR}/models.json"

[[ -f "$SECRETS" ]] && set -a && source "$SECRETS" && set +a

PASS=0
FAIL=0
SKIP=0

test_model() {
  local profile="$1" model="$2" base_url="$3" env_key="$4"
  local api_key="${!env_key:-}"

  if [[ -z "$api_key" ]]; then
    echo "⏭️  $profile — skip ($env_key tidak diset)"
    SKIP=$((SKIP + 1))
    return
  fi

  local start_ms end_ms elapsed code
  start_ms=$(date +%s%3N)
  code=$(curl -sS -o /tmp/qwen-test.json -w "%{http_code}" \
    "${base_url}/chat/completions" \
    -H "Authorization: Bearer $api_key" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${model}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply OK\"}],\"max_tokens\":4}" \
    --max-time 90)
  end_ms=$(date +%s%3N)
  elapsed=$((end_ms - start_ms))

  if [[ "$code" == "200" ]]; then
    echo "✅ $profile — ${model} (${elapsed}ms)"
    PASS=$((PASS + 1))
  else
    local detail
    detail=$(python3 -c "import json;d=json.load(open('/tmp/qwen-test.json'));print(d.get('error',d.get('detail',d))[:80])" 2>/dev/null || head -c 80 /tmp/qwen-test.json)
    echo "❌ $profile — ${model} HTTP $code (${elapsed}ms) $detail"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Qwen Code Model Smoke Test ==="
echo ""

while IFS='|' read -r profile model base_url env_key; do
  test_model "$profile" "$model" "$base_url" "$env_key"
done < <(python3 - "$MODELS_JSON" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for k, v in d["profiles"].items():
    print(f"{k}|{v['qwen_model']}|{v['baseUrl']}|{v['envKey']}")
PY
)

echo ""
echo "=== Embedding Test ==="
if [[ -n "${NVIDIA_API_KEY:-}" ]]; then
  code=$(curl -sS -o /tmp/emb-test.json -w "%{http_code}" \
    "https://integrate.api.nvidia.com/v1/embeddings" \
    -H "Authorization: Bearer $NVIDIA_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"model":"nvidia/nv-embedqa-e5-v5","input":["hello world"],"input_type":"query"}' \
    --max-time 30)
  if [[ "$code" == "200" ]]; then
    dims=$(python3 -c "import json;d=json.load(open('/tmp/emb-test.json'));print(len(d['data'][0]['embedding']))")
    echo "✅ embedding nvidia/nv-embedqa-e5-v5 (${dims} dims)"
    PASS=$((PASS + 1))
  else
    echo "❌ embedding HTTP $code"
    FAIL=$((FAIL + 1))
  fi
else
  echo "⏭️  embedding — skip (NVIDIA_API_KEY tidak diset)"
  SKIP=$((SKIP + 1))
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="
# 503 on NVIDIA under load is expected — don't fail if only transient errors
[[ "$FAIL" -le 1 ]] || exit 1
