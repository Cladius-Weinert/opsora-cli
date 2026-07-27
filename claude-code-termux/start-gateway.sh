#!/data/data/com.termux/files/usr/bin/bash
# Start LiteLLM gateway for Claude Code (NVIDIA + multi-provider)
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
CONFIG="${INSTALL_DIR}/litellm-config.yaml"
SECRETS="${INSTALL_DIR}/secrets.env"
PORT="${LITELLM_PORT:-4000}"
PID_FILE="${INSTALL_DIR}/gateway.pid"
LOG_FILE="${INSTALL_DIR}/gateway.log"

if [[ ! -f "$CONFIG" ]]; then
  echo "❌ Config tidak ditemukan: $CONFIG"
  echo "   Jalankan dulu: bash install-termux.sh"
  exit 1
fi

if [[ -f "$SECRETS" ]]; then
  # shellcheck disable=SC1090
  source "$SECRETS"
fi

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "❌ NVIDIA_API_KEY belum di-set di $SECRETS"
  exit 1
fi

export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-opsora-local}"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "✅ Gateway sudah jalan (PID $(cat "$PID_FILE")) — http://127.0.0.1:${PORT}"
  exit 0
fi

mkdir -p "$INSTALL_DIR"

echo "▶ Starting LiteLLM gateway on port ${PORT}..."
nohup litellm --config "$CONFIG" --port "$PORT" --host 127.0.0.1 \
  >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
sleep 3

if curl -sf "http://127.0.0.1:${PORT}/health/liveliness" >/dev/null 2>&1; then
  echo "✅ Gateway ready — http://127.0.0.1:${PORT}"
  echo "   Log: $LOG_FILE"
else
  echo "⚠️  Gateway mungkin masih starting. Cek: tail -f $LOG_FILE"
fi
