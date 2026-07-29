#!/data/data/com.termux/files/usr/bin/bash
# Apply Opsora gateway settings — overwrites ~/.claude/settings.json
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
SETTINGS="$HOME/.claude/settings.json"
TEMPLATE="${INSTALL_DIR}/settings.json"
MASTER_KEY="${LITELLM_MASTER_KEY:-sk-opsora-local}"

mkdir -p "$HOME/.claude"

python3 <<PY
import json, os, shutil

template = "${TEMPLATE}"
settings_path = os.path.expanduser("${SETTINGS}")
master_key = "${MASTER_KEY}"

with open(template) as f:
    settings = json.load(f)

settings.setdefault("env", {})
settings["env"]["ANTHROPIC_AUTH_TOKEN"] = master_key
settings["model"] = settings["env"].get("ANTHROPIC_MODEL", "opsora-balanced")

if os.path.isfile(settings_path):
    shutil.copy2(settings_path, settings_path + ".bak")

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print("✅ Settings →", settings_path)
PY

# Clear claude.ai OAuth so gateway credential wins
for f in \
  "$HOME/.claude/.credentials.json" \
  "$HOME/.claude/credentials.json" \
  "$HOME/.config/claude-code/auth.json"; do
  [[ -f "$f" ]] && rm -f "$f" && echo "🗑️  Removed OAuth: $f"
done

rm -f "$HOME/.claude/cache/gateway-models.json" 2>/dev/null || true
echo "✅ Gateway settings applied. Jalankan: opsora-claude"
