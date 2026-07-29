#!/usr/bin/env bash
# Master deploy: NVIDIA NGC custom + AWS bootstrap package
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== Opsora Cloud Deploy ==="
echo ""

# Phase 1: NVIDIA (API-based, works from anywhere with NVIDIA_API_KEY)
if [[ -n "${NVIDIA_API_KEY:-}" ]]; then
  echo "▶ Phase 1: NVIDIA NGC / Integrate custom catalog"
  bash deploy/ngc/build-custom-catalog.sh
else
  echo "⚠️  Skip NVIDIA build — NVIDIA_API_KEY not set"
fi

echo ""
echo "▶ Phase 2: AWS bootstrap package ready"
echo "   Run ON opsora-brain (98.94.100.100) or any EC2 Ubuntu:"
echo ""
echo "   export NVIDIA_API_KEY=nvapi-..."
echo "   curl -fsSL https://raw.githubusercontent.com/Cladius-Weinert/opsora-cli/${OPSORA_CLI_BRANCH:-cursor/agent-stack-context-cache-c133}/deploy/aws/bootstrap-opsora-agent.sh | bash"
echo ""
echo "▶ Phase 3: Local agent stack (this machine)"
if [[ -f claude-code-termux/setup-agent-stack.sh ]]; then
  bash claude-code-termux/setup-agent-stack.sh || true
fi

echo ""
echo "✅ Deploy package complete"
echo "   NVIDIA profiles: \${OPSORA_DIR:-~/.opsora}/nvidia-custom/opsora-nvidia-profiles.json"
