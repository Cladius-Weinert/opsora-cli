#!/data/data/com.termux/files/usr/bin/bash
# Stop LiteLLM gateway
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
PID_FILE="${INSTALL_DIR}/gateway.pid"

if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "✅ Gateway stopped (PID $PID)"
  fi
  rm -f "$PID_FILE"
else
  pkill -f "litellm --config" 2>/dev/null && echo "✅ Gateway stopped" || echo "Gateway tidak jalan"
fi
