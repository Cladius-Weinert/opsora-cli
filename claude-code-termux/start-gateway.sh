#!/data/data/com.termux/files/usr/bin/bash
# Start lightweight NVIDIA proxy (no LiteLLM — works on Termux)
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
SECRETS="${INSTALL_DIR}/secrets.env"
PID_FILE="${INSTALL_DIR}/gateway.pid"
LOG_FILE="${INSTALL_DIR}/gateway.log"
PROXY="${INSTALL_DIR}/nvidia-proxy.py"

[[ -f "$SECRETS" ]] && source "$SECRETS"

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "❌ NVIDIA_API_KEY belum di-set di $SECRETS"
  exit 1
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "✅ Proxy sudah jalan (PID $(cat "$PID_FILE"))"
  exit 0
fi

export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-opsora-local}"
export OPSORA_PROXY_PORT="${OPSORA_PROXY_PORT:-4000}"

echo "▶ Starting NVIDIA proxy on port ${OPSORA_PROXY_PORT}..."
nohup python3 "$PROXY" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
sleep 2

if curl -sf "http://127.0.0.1:${OPSORA_PROXY_PORT}/health" >/dev/null; then
  echo "✅ Proxy ready — http://127.0.0.1:${OPSORA_PROXY_PORT}"
else
  echo "⚠️  Cek log: tail -f $LOG_FILE"
fi
