#!/data/data/com.termux/files/usr/bin/bash
# Ganti model Qwen Code berdasarkan profile
# Usage: switch-model.sh power|reasoning|fast|nvidia-coder|...
set -euo pipefail

PROFILE="${1:-}"
INSTALL_DIR="${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$INSTALL_DIR/models.json" ]] || INSTALL_DIR="$SCRIPT_DIR"
MODELS_JSON="${INSTALL_DIR}/models.json"
RPM_JSON="${INSTALL_DIR}/rpm-config.json"
SETTINGS="${HOME}/.qwen/settings.json"

usage() {
  echo "Usage: switch-model.sh <profile>"
  echo ""
  echo "Profiles:"
  python3 -c "
import json
d = json.load(open('${MODELS_JSON}'))
for k, v in d['profiles'].items():
    r = ' [reasoning]' if v.get('reasoning') else ''
    c = ' [cache]' if v.get('caching') else ''
    print(f\"  {k:18} → {v['qwen_model']:45} ({v['label']}){r}{c}\")
" 2>/dev/null || cat "$MODELS_JSON"
}

if [[ -z "$PROFILE" ]]; then
  usage
  exit 1
fi

read -r QWEN_MODEL BASE_URL FAST_MODEL RPM_TIER <<<"$(python3 <<PY
import json, sys
d = json.load(open("${MODELS_JSON}"))
p = d["profiles"].get("${PROFILE}")
if not p:
    sys.exit(1)
bg = d["profiles"][d["recommended"]["background"]]
print(p["qwen_model"], p["baseUrl"], bg["qwen_model"], p.get("rpm_tier", "balanced"))
PY
)" || {
  echo "❌ Profile tidak dikenal: $PROFILE"
  usage
  exit 1
}

python3 <<PY
import json, os

settings_path = os.path.expanduser("${SETTINGS}")
rpm_path = "${RPM_JSON}"
template_path = "${INSTALL_DIR}/settings.json"

with open(settings_path if os.path.isfile(settings_path) else template_path) as f:
    settings = json.load(f)

rpm = {}
if os.path.isfile(rpm_path):
    with open(rpm_path) as f:
        rpm = json.load(f)

tier = rpm.get("tiers", {}).get("${RPM_TIER}", {})
fallbacks = rpm.get("fallbacks", {}).get("modelFallbacks", "")

settings.setdefault("model", {})
settings["model"]["name"] = "${QWEN_MODEL}"
settings["model"]["baseUrl"] = "${BASE_URL}"
settings["fastModel"] = "openai:${FAST_MODEL}"
if fallbacks:
    settings["modelFallbacks"] = fallbacks

# Apply RPM tier to matching provider model entry
for model_entry in settings.get("modelProviders", {}).get("openai", {}).get("models", []):
    if model_entry.get("id") == "${QWEN_MODEL}" and model_entry.get("baseUrl") == "${BASE_URL}":
        gc = model_entry.setdefault("generationConfig", {})
        if tier.get("maxRetries"):
            gc["maxRetries"] = tier["maxRetries"]
        if tier.get("retryInitialDelayMs"):
            gc["retryInitialDelayMs"] = tier["retryInitialDelayMs"]
        if tier.get("retryMaxDelayMs"):
            gc["retryMaxDelayMs"] = tier["retryMaxDelayMs"]
        if tier.get("timeoutMs"):
            gc["timeout"] = tier["timeoutMs"]

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print(f"✅ Model → ${QWEN_MODEL}")
print(f"   Profile: ${PROFILE} | RPM tier: ${RPM_TIER}")
print(f"   Fast model: ${FAST_MODEL}")
PY

echo "   Jalankan: opsora-qwen  atau  qw"
