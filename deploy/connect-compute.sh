#!/usr/bin/env bash
# Connect available Opsora compute backends (NVIDIA hosted + local gateway + fleet registry)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OPSORA_DIR="${OPSORA_DIR:-$HOME/.opsora}"
REGISTRY="$OPSORA_DIR/compute-registry.json"
ORG_ID="${NGC_ORG_ID:-1006275399815502}"
GATEWAY_PORT="${OPSORA_GATEWAY_PORT:-4000}"
GATEWAY_HOST="${OPSORA_GATEWAY_HOST:-127.0.0.1}"

mkdir -p "$OPSORA_DIR/claude-code" "$OPSORA_DIR/nvidia-custom"

echo "╔══════════════════════════════════════════════╗"
echo "║  OPSORA CONNECT COMPUTE                      ║"
echo "╚══════════════════════════════════════════════╝"

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "❌ Set NVIDIA_API_KEY (Opsora Personal Key dari org.ngc.nvidia.com)"
  exit 1
fi

export NGC_ORG_ID="$ORG_ID"
export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-opsora-local}"

# 1) NVIDIA catalog + profiles
if [[ -f "$SCRIPT_DIR/ngc/build-custom-catalog.sh" ]]; then
  echo "▶ Building NVIDIA catalog..."
  bash "$SCRIPT_DIR/ngc/build-custom-catalog.sh"
fi

cp -f "$CLI_DIR/claude-code-termux/litellm-config.yaml" "$OPSORA_DIR/claude-code/"
cp -f "$CLI_DIR/claude-code-termux/models.json" "$OPSORA_DIR/claude-code/" 2>/dev/null || true

# 2) secrets.env (never overwrite existing keys)
SECRETS="$OPSORA_DIR/claude-code/secrets.env"
if [[ ! -f "$SECRETS" ]]; then
  cp "$CLI_DIR/claude-code-termux/secrets.env.example" "$SECRETS"
fi

# 3) Probe compute targets
python3 <<PYEOF
import json, os, urllib.request, ssl, socket, time
from datetime import datetime, timezone

KEY = os.environ["NVIDIA_API_KEY"]
ORG = os.environ.get("NGC_ORG_ID", "1006275399815502")
ctx = ssl.create_default_context()

def http_ok(url, key=KEY):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            return True, r.status, ""
    except Exception as e:
        return False, getattr(e, 'code', -1), str(e)[:120]

def port_open(host, port, timeout=3):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False

registry = {
    "updated": datetime.now(timezone.utc).isoformat(),
    "org_id": ORG,
    "connected": [],
    "reachable": [],
    "blocked": [],
}

# NVIDIA hosted compute (serverless)
for name, url in [
    ("nvidia-integrate", "https://integrate.api.nvidia.com/v1/models"),
    ("nvidia-nvcf", "https://api.nvcf.nvidia.com/v2/nvcf/functions"),
    ("ngc-subscriptions", f"https://api.ngc.nvidia.com/v2/org/{ORG}/subscriptions"),
]:
    ok, code, err = http_ok(url)
    entry = {"id": name, "type": "nvidia-hosted", "url": url, "status": "connected" if ok else "blocked", "http": code}
    if not ok: entry["error"] = err
    (registry["connected"] if ok else registry["blocked"]).append(entry)

# Run:ai tenant
registry["reachable"].append({
    "id": "runai-saas",
    "type": "orchestrator",
    "url": "https://opsora.nv.run.ai",
    "status": "tenant-active",
    "note": "Login SSO required; connect AWS GPU cluster from UI",
})

# AWS fleet (SSH probe only)
fleet = [
    {"id": "aop-vps", "host": "54.81.31.132", "role": "orchestrator", "ports": [22, 8787]},
    {"id": "opsora-model", "host": "18.208.28.108", "role": "ai-worker", "ports": [22, 8788]},
    {"id": "opsora-brain", "host": "98.94.100.100", "role": "command-center", "ports": [22, 4000, 11434]},
    {"id": "cloudpc-win", "host": "32.198.252.187", "role": "rdp-gui", "ports": [22, 3389]},
]
for node in fleet:
    ssh = port_open(node["host"], 22)
    services = {str(p): port_open(node["host"], p) for p in node["ports"] if p != 22}
    entry = {**node, "ssh_open": ssh, "services": services, "status": "reachable" if ssh else "unreachable"}
    (registry["reachable"] if ssh else registry["blocked"]).append(entry)

# Local gateway
registry["connected"].append({
    "id": "opsora-gateway",
    "type": "local-litellm",
    "url": f"http://{os.environ.get('OPSORA_GATEWAY_HOST','127.0.0.1')}:{os.environ.get('OPSORA_GATEWAY_PORT','4000')}",
    "status": "pending-start",
})

out = os.environ.get("OPSORA_DIR", os.path.expanduser("~/.opsora")) + "/compute-registry.json"
with open(out, "w") as f:
    json.dump(registry, f, indent=2)
print(f"✅ Compute registry → {out}")
print(f"   connected: {len(registry['connected'])} | reachable: {len(registry['reachable'])} | blocked: {len(registry['blocked'])}")
PYEOF

# 4) Start LiteLLM gateway (local compute router)
if [[ "${OPSORA_START_GATEWAY:-1}" == "1" ]]; then
  export OPSORA_GATEWAY_PORT="$GATEWAY_PORT"
  export OPSORA_GATEWAY_HOST="$GATEWAY_HOST"
  LITELLM_BIN="$(python3 -m site --user-base)/bin/litellm"
  CONFIG="$OPSORA_DIR/claude-code/litellm-config.yaml"

  if curl -sf "http://$GATEWAY_HOST:$GATEWAY_PORT/health/liveliness" >/dev/null 2>&1; then
    echo "✅ Gateway already running on :$GATEWAY_PORT"
  else
    echo "▶ Starting LiteLLM gateway on $GATEWAY_HOST:$GATEWAY_PORT ..."
    SESSION_NAME="opsora-gateway"
    tmux -f /exec-daemon/tmux.portal.conf has-session -t "=$SESSION_NAME" 2>/dev/null && \
      tmux -f /exec-daemon/tmux.portal.conf kill-session -t "=$SESSION_NAME" 2>/dev/null || true
    tmux -f /exec-daemon/tmux.portal.conf new-session -d -s "$SESSION_NAME" -c "$CLI_DIR" -- "${SHELL:-bash}" -lc \
      "source '$SECRETS' 2>/dev/null; export NVIDIA_API_KEY='$NVIDIA_API_KEY' LITELLM_MASTER_KEY='$LITELLM_MASTER_KEY'; exec '$LITELLM_BIN' --config '$CONFIG' --port '$GATEWAY_PORT' --host '$GATEWAY_HOST'"
    sleep 4
    if curl -sf "http://$GATEWAY_HOST:$GATEWAY_PORT/health/liveliness" >/dev/null 2>&1; then
      echo "✅ Gateway UP → http://$GATEWAY_HOST:$GATEWAY_PORT"
    else
      echo "⚠️  Gateway starting... check: tmux attach -t $SESSION_NAME"
    fi
  fi
fi

# 5) Smoke test
if curl -sf "http://$GATEWAY_HOST:$GATEWAY_PORT/health/liveliness" >/dev/null 2>&1; then
  echo "▶ Smoke test opsora-fast..."
  curl -sf "http://$GATEWAY_HOST:$GATEWAY_PORT/v1/chat/completions" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d '{"model":"opsora-fast","messages":[{"role":"user","content":"ping"}],"max_tokens":8}' \
    | python3 -c "import sys,json; r=json.load(sys.stdin); print('✅', r['choices'][0]['message']['content'][:80])" \
    || echo "⚠️  Smoke test failed — check NVIDIA_API_KEY"
fi

echo ""
echo "Done. Registry: $REGISTRY"
echo "Use: curl http://$GATEWAY_HOST:$GATEWAY_PORT/v1/models -H 'Authorization: Bearer $LITELLM_MASTER_KEY'"
