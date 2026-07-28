#!/data/data/com.termux/files/usr/bin/bash
# Generate embeddings untuk RAG/indexing (di luar Qwen Code CLI)
# Usage: embed.sh "text to embed" [profile]
set -euo pipefail

INSTALL_DIR="${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}"
SECRETS="${INSTALL_DIR}/secrets.env"
EMBED_JSON="${INSTALL_DIR}/embedding-config.json"
PROFILE="${2:-nvidia}"

[[ -f "$SECRETS" ]] && set -a && source "$SECRETS" && set +a

TEXT="${1:-}"
if [[ -z "$TEXT" ]]; then
  echo "Usage: embed.sh \"text to embed\" [profile]"
  echo "Profiles: nvidia (default), dashscope"
  exit 1
fi

python3 <<PY
import json, os, sys, urllib.request

embed_cfg = json.load(open("${EMBED_JSON}"))
profile = embed_cfg["profiles"].get("${PROFILE}")
if not profile:
    print(f"Unknown profile: ${PROFILE}", file=sys.stderr)
    sys.exit(1)

api_key = os.environ.get(profile["envKey"], "")
if not api_key:
    print(f"Set {profile['envKey']} in secrets.env", file=sys.stderr)
    sys.exit(1)

body = {"model": profile["model"], "input": ["""${TEXT}"""]}
body.update(profile.get("request_body", {}))

req = urllib.request.Request(
    profile["endpoint"],
    data=json.dumps(body).encode(),
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(req, timeout=30) as resp:
    result = json.loads(resp.read())

embedding = result["data"][0]["embedding"]
print(json.dumps({
    "model": profile["model"],
    "dimensions": len(embedding),
    "embedding": embedding[:8],
    "truncated": True,
    "full_dims": len(embedding),
}))
PY
