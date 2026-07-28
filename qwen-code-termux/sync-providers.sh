#!/data/data/com.termux/files/usr/bin/bash
# Sync & audit semua provider — NVIDIA + DashScope + Coding Plan
set -euo pipefail

INSTALL_DIR="${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$INSTALL_DIR/rpm-config.json" ]] || INSTALL_DIR="$SCRIPT_DIR"
SECRETS="${INSTALL_DIR}/secrets.env"
MODELS_JSON="${INSTALL_DIR}/models.json"

[[ -f "$SECRETS" ]] && set -a && source "$SECRETS" && set +a

echo "=== Opsora Qwen Code — Provider Sync & Audit ==="
echo ""

# ── NVIDIA Integrate ────────────────────────────────────────────
if [[ -n "${NVIDIA_API_KEY:-}" ]]; then
  echo "▶ NVIDIA Integrate API..."
  COUNT=$(curl -sf "https://integrate.api.nvidia.com/v1/models" \
    -H "Authorization: Bearer $NVIDIA_API_KEY" \
    | python3 -c "import sys,json; print(len(json.load(sys.stdin)['data']))" 2>/dev/null || echo "?")
  echo "   ✅ $COUNT models listed"

  # Test key profiles
  for m in "deepseek-ai/deepseek-v4-flash" "nvidia/llama-3.3-nemotron-super-49b-v1.5" "meta/llama-3.1-8b-instruct"; do
    code=$(curl -sS -o /dev/null -w "%{http_code}" \
      "https://integrate.api.nvidia.com/v1/chat/completions" \
      -H "Authorization: Bearer $NVIDIA_API_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"OK\"}],\"max_tokens\":2}" \
      --max-time 60)
    status="✅" ; [[ "$code" != "200" ]] && status="⚠️ HTTP $code"
    echo "   $status $m"
  done

  # Embedding
  ecode=$(curl -sS -o /dev/null -w "%{http_code}" \
    "https://integrate.api.nvidia.com/v1/embeddings" \
    -H "Authorization: Bearer $NVIDIA_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"model":"nvidia/nv-embedqa-e5-v5","input":["test"],"input_type":"query"}' \
    --max-time 30)
  echo "   $([ "$ecode" = "200" ] && echo "✅" || echo "⚠️") embedding nvidia/nv-embedqa-e5-v5 (HTTP $ecode)"
else
  echo "❌ NVIDIA_API_KEY tidak diset di $SECRETS"
fi

echo ""

# ── DashScope International ─────────────────────────────────────
if [[ -n "${DASHSCOPE_API_KEY:-}" ]]; then
  echo "▶ DashScope International..."
  COUNT=$(curl -sf "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models" \
    -H "Authorization: Bearer $DASHSCOPE_API_KEY" \
    | python3 -c "import sys,json; print(len(json.load(sys.stdin)['data']))" 2>/dev/null || echo "?")
  echo "   ✅ $COUNT models listed"

  for m in "qwen3-coder-plus" "qwen3.7-max" "qwen3-coder-flash"; do
    code=$(curl -sS -o /dev/null -w "%{http_code}" \
      "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions" \
      -H "Authorization: Bearer $DASHSCOPE_API_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"OK\"}],\"max_tokens\":2}" \
      --max-time 60)
    status="✅" ; [[ "$code" != "200" ]] && status="⚠️ HTTP $code"
    echo "   $status $m"
  done
else
  echo "❌ DASHSCOPE_API_KEY tidak diset di $SECRETS"
fi

echo ""

# ── Coding Plan (opsional) ──────────────────────────────────────
if [[ -n "${BAILIAN_CODING_PLAN_API_KEY:-}" ]]; then
  echo "▶ Alibaba Coding Plan (intl)..."
  code=$(curl -sS -o /dev/null -w "%{http_code}" \
    "https://coding-intl.dashscope.aliyuncs.com/v1/chat/completions" \
    -H "Authorization: Bearer $BAILIAN_CODING_PLAN_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"model":"qwen3-coder-plus","messages":[{"role":"user","content":"OK"}],"max_tokens":2}' \
    --max-time 60)
  echo "   $([ "$code" = "200" ] && echo "✅" || echo "⚠️ HTTP $code") qwen3-coder-plus"
else
  echo "ℹ️  BAILIAN_CODING_PLAN_API_KEY tidak diset (opsional)"
fi

echo ""
echo "=== RPM Recommendations ==="
python3 -c "
import json
rpm = json.load(open('${INSTALL_DIR}/rpm-config.json'))
for tier, cfg in rpm['tiers'].items():
    print(f\"  {tier:10} maxParallel={cfg['maxParallel']} retries={cfg['maxRetries']} timeout={cfg['timeoutMs']}ms\")
print()
for prov, cfg in rpm['provider_limits'].items():
    print(f\"  {prov:20} ~{cfg['estimated_rpm']} RPM → fallback: {cfg['fallback_profile']}\")
" 2>/dev/null || true

echo ""
echo "✅ Sync selesai. Jalankan: opsora-qwen-test"
