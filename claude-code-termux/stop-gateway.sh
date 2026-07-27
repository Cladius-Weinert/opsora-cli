#!/data/data/com.termux/files/usr/bin/bash
# Stop NVIDIA proxy (and legacy LiteLLM if present)
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
PID_FILE="${INSTALL_DIR}/gateway.pid"
STOPPED=false

stop_pid() {
  local pid="$1"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
    echo "✅ Gateway stopped (PID $pid)"
    STOPPED=true
  fi
}

if [[ -f "$PID_FILE" ]]; then
  stop_pid "$(cat "$PID_FILE")"
  rm -f "$PID_FILE"
fi

if pkill -f "${INSTALL_DIR}/nvidia-proxy.py" 2>/dev/null; then
  echo "✅ Stopped nvidia-proxy.py"
  STOPPED=true
fi

if pkill -f "nvidia-proxy.py" 2>/dev/null; then
  echo "✅ Stopped stale nvidia-proxy.py"
  STOPPED=true
fi

if pkill -f "litellm --config" 2>/dev/null; then
  echo "✅ Stopped litellm"
  STOPPED=true
fi

if [[ "$STOPPED" == false ]]; then
  echo "Gateway tidak jalan"
fi
