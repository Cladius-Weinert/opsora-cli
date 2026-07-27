#!/data/data/com.termux/files/usr/bin/bash
# Ganti model Claude Code (via settings.json)
# Usage: switch-model.sh power|balanced|coder|fast|reasoning|nemotron|qwen-plus|qwen-max|local
set -euo pipefail

PROFILE="${1:-}"
INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
MODELS_JSON="${INSTALL_DIR}/models.json"
SETTINGS="${HOME}/.claude/settings.json"

usage() {
  echo "Usage: switch-model.sh <profile>"
  echo ""
  echo "Profiles:"
  python3 -c "
import json, sys
d=json.load(open('${MODELS_JSON}'))
for k,v in d['profiles'].items():
    print(f\"  {k:12} → {v['claude_model']:20} ({v['label']})\")
" 2>/dev/null || cat "$MODELS_JSON"
}

if [[ -z "$PROFILE" ]]; then
  usage
  exit 1
fi

CLAUDE_MODEL=$(python3 -c "
import json, sys
d=json.load(open('${MODELS_JSON}'))
p=d['profiles'].get('${PROFILE}')
if not p: sys.exit(1)
print(p['claude_model'])
" 2>/dev/null) || {
  echo "❌ Profile tidak dikenal: $PROFILE"
  usage
  exit 1
}

FAST_MODEL=$(python3 -c "
import json
d=json.load(open('${MODELS_JSON}'))
print(d['profiles'][d['recommended']['background']]['claude_model'])
")

mkdir -p "${HOME}/.claude"

python3 <<PY
import json, os
settings_path = os.path.expanduser("${SETTINGS}")
template_path = "${INSTALL_DIR}/settings.json"

if os.path.isfile(settings_path):
    with open(settings_path) as f:
        settings = json.load(f)
else:
    with open(template_path) as f:
        settings = json.load(f)

settings.setdefault("env", {})
settings["env"]["ANTHROPIC_MODEL"] = "${CLAUDE_MODEL}"
settings["env"]["ANTHROPIC_SMALL_FAST_MODEL"] = "${FAST_MODEL}"
settings["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] = "${CLAUDE_MODEL}"

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
print("✅ Model → ${CLAUDE_MODEL} (profile: ${PROFILE})")
PY

echo "   Restart Claude Code session atau jalankan: claude"
