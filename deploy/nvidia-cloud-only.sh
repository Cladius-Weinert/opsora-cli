#!/usr/bin/env bash
# Opsora compute via NVIDIA Console only — skips blocked AWS fleet
set -euo pipefail

export OPSORA_SKIP_FLEET="${OPSORA_SKIP_FLEET:-1}"
export OPSORA_START_GATEWAY="${OPSORA_START_GATEWAY:-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔══════════════════════════════════════════════╗"
echo "║  OPSORA NVIDIA CLOUD (no AWS)                ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "Backends:"
echo "  • NVIDIA Integrate API (102+ models)"
echo "  • NVIDIA NVCF functions"
echo "  • Run:ai SaaS → https://opsora.nv.run.ai"
echo "  • LiteLLM gateway (local or Render)"
echo ""
echo "AWS fleet: SKIPPED (use Render blueprint or Run:ai instead)"
echo ""

bash "$SCRIPT_DIR/connect-compute.sh"
