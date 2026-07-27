#!/data/data/com.termux/files/usr/bin/bash
# Start lightweight NVIDIA proxy (no LiteLLM — works on Termux)
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
SECRETS="${INSTALL_DIR}/secrets.env"
PID_FILE="${INSTALL_DIR}/gateway.pid"
LOG_FILE="${INSTALL_DIR}/gateway.log"
PROXY="${INSTALL_DIR}/nvidia-proxy.py"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ -f "$SECRETS" ]] && source "$SECRETS"

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "❌ NVIDIA_API_KEY belum di-set di $SECRETS"
  exit 1
fi

if [[ "${1:-}" == "restart" || "${OPSORA_FORCE_RESTART:-}" == "1" ]]; then
  bash "${SCRIPT_DIR}/stop-gateway.sh" 2>/dev/null || true
fi

proxy_running() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o args= 2>/dev/null | grep -q "nvidia-proxy.py"
}

if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE")
  if proxy_running "$PID"; then
    echo "✅ Proxy sudah jalan (PID $PID)"
    exit 0
  fi
  echo "⚠️  Stale PID $PID — restarting proxy"
  kill "$PID" 2>/dev/null || true
  rm -f "$PID_FILE"
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
  echo "⚠️  Proxy health check gagal — cek log:"
  tail -5 "$LOG_FILE" 2>/dev/null || true
fi
