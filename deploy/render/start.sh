#!/usr/bin/env bash
# Opsora LiteLLM gateway for Render (binds 0.0.0.0:$PORT per Render platform rules)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="${OPSORA_LITELLM_CONFIG:-$ROOT/claude-code-termux/litellm-config.yaml}"
PORT="${PORT:-4000}"
HOST="0.0.0.0"

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "ERROR: Set NVIDIA_API_KEY in Render Environment" >&2
  exit 1
fi

export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-opsora-render}"

echo "Starting Opsora gateway on $HOST:$PORT"
exec litellm --config "$CONFIG" --host "$HOST" --port "$PORT"
