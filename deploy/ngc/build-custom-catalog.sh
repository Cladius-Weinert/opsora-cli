#!/usr/bin/env bash
# Build custom NVIDIA catalog + NVCF profile map for Opsora agent stack
set -euo pipefail

INSTALL_DIR="${OPSORA_DIR:-$HOME/.opsora}"
OUT_DIR="${INSTALL_DIR}/nvidia-custom"
mkdir -p "$OUT_DIR"

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "❌ Set NVIDIA_API_KEY"
  exit 1
fi

echo "=== Opsora NVIDIA Custom Build ==="

# 1) Integrate catalog
curl -sf "https://integrate.api.nvidia.com/v1/models" \
  -H "Authorization: Bearer $NVIDIA_API_KEY" \
  -o "$OUT_DIR/integrate-models.json"

INTEGRATE_COUNT=$(python3 -c "import json; print(len(json.load(open('$OUT_DIR/integrate-models.json'))['data']))")
echo "✅ Integrate models: $INTEGRATE_COUNT"

# 2) NVCF functions
curl -sf "https://api.nvcf.nvidia.com/v2/nvcf/functions" \
  -H "Authorization: Bearer $NVIDIA_API_KEY" \
  -o "$OUT_DIR/nvcf-functions.json"

OUT_DIR="$OUT_DIR" python3 <<'PY'
import json, pathlib, os
out = pathlib.Path(os.environ["OUT_DIR"])
funcs = json.load(open(out / "nvcf-functions.json"))
if not isinstance(funcs, list):
    funcs = funcs.get("functions", funcs.get("data", []))
active = [f for f in funcs if isinstance(f, dict) and f.get("status") == "ACTIVE"]
coding = []
for f in active:
    name = str(f.get("name", ""))
    if any(k in name.lower() for k in ("llama", "deepseek", "gemma", "nemotron", "qwen", "coder")):
        coding.append({
            "name": name,
            "id": f.get("id"),
            "status": f.get("status"),
            "api_base": "https://api.nvcf.nvidia.com/v2/nvcf",
        })
profile = {
    "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    "integrate_count": len(json.load(open(out / "integrate-models.json"))["data"]),
    "nvcf_active_count": len(active),
    "recommended_profiles": {
        "balanced": {"backend": "integrate", "model": "meta/llama-3.1-70b-instruct"},
        "fast": {"backend": "integrate", "model": "meta/llama-3.1-8b-instruct"},
        "coder": {"backend": "integrate", "model": "deepseek-ai/deepseek-v4-pro"},
        "flagship": {"backend": "integrate", "model": "nvidia/nemotron-3-super-120b-a12b"},
        "nvcf_gemma": {"backend": "nvcf", "model": "ai-gemma-2-2b-it"},
        "nvcf_llama8": {"backend": "nvcf", "model": "ai-llama-3_1-8b-instruct"},
    },
    "nvcf_coding_functions": coding[:30],
}
json.dump(profile, open(out / "opsora-nvidia-profiles.json", "w"), indent=2)
print(f"✅ NVCF active: {len(active)} | coding-related: {len(coding)}")
PY

echo "✅ Profiles: $OUT_DIR/opsora-nvidia-profiles.json"

# 3) Verify key models
verify_model() {
  local model="$1"
  local code
  code=$(curl -s -m 25 -o /tmp/opsora_nv_verify.json -w "%{http_code}" \
    "https://integrate.api.nvidia.com/v1/chat/completions" \
    -H "Authorization: Bearer $NVIDIA_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"OK\"}],\"max_tokens\":3}")
  echo "  $model → HTTP $code"
}

echo "▶ Model verification"
for m in meta/llama-3.1-70b-instruct meta/llama-3.1-8b-instruct deepseek-ai/deepseek-v4-pro nvidia/nemotron-3-super-120b-a12b; do
  verify_model "$m"
done

echo ""
echo "✅ Custom NVIDIA catalog → $OUT_DIR"
