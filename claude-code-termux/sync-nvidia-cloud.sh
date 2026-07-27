#!/usr/bin/env bash
# Sync NVIDIA Cloud catalog → Opsora Claude Code config
# Jalankan setelah dapat/update NVIDIA API key dari NGC Console
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
SECRETS="${INSTALL_DIR}/secrets.env"

[[ -f "$SECRETS" ]] && source "$SECRETS"

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "❌ Set NVIDIA_API_KEY di $SECRETS"
  echo "   https://org.ngc.nvidia.com/setup/api-keys"
  exit 1
fi

mkdir -p "$INSTALL_DIR"

echo "=== NVIDIA Cloud Sync ==="
echo ""

# 1) List Integrate models
echo "▶ Integrate API models..."
INTEGRATE_COUNT=$(curl -sf "https://integrate.api.nvidia.com/v1/models" \
  -H "Authorization: Bearer $NVIDIA_API_KEY" \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin)['data']))")
echo "   ✅ $INTEGRATE_COUNT models available"

# 2) Key scope audit (if opsora repo available)
OPSORA_ROOT="${OPSORA_ROOT:-$HOME/opsora}"
if [[ -f "$OPSORA_ROOT/scripts/nvcf-key-scope-audit.mjs" ]]; then
  echo "▶ Key scope audit..."
  export NGC_CLI_API_KEY="$NVIDIA_API_KEY"
  node "$OPSORA_ROOT/scripts/nvcf-key-scope-audit.mjs" --key inference 2>&1 | grep -E '^(✅|❌)' || true
fi

# 3) NVCF catalog export
if [[ -f "$OPSORA_ROOT/scripts/ngc-nvcf-client.mjs" ]]; then
  echo "▶ NVCF functions..."
  node "$OPSORA_ROOT/scripts/ngc-nvcf-client.mjs" catalog-export 2>&1 | tail -1
  cp "$OPSORA_ROOT/.opsora/nvcf-active-catalog.json" "$INSTALL_DIR/nvcf-catalog.json" 2>/dev/null || true
fi

# 4) Copy latest configs
cp -f "$ROOT/litellm-config.yaml" "$INSTALL_DIR/"
cp -f "$ROOT/nvidia-cloud-catalog.json" "$INSTALL_DIR/"
cp -f "$ROOT/models.json" "$INSTALL_DIR/" 2>/dev/null || cp -f "$ROOT/nvidia-cloud-catalog.json" "$INSTALL_DIR/models.json"

echo ""
echo "✅ Sync selesai → $INSTALL_DIR"
echo "   Restart gateway: opsora-gateway (stop lalu start)"
