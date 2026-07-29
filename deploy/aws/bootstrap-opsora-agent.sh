#!/usr/bin/env bash
# Bootstrap Opsora Agent Stack on AWS EC2 (opsora-brain, model-vps, termux-vm)
# Run ON the EC2 instance as ubuntu user:
#   curl -fsSL https://raw.githubusercontent.com/Cladius-Weinert/opsora-cli/cursor/agent-stack-context-cache-c133/deploy/aws/bootstrap-opsora-agent.sh | bash
set -euo pipefail

OPSORA_CLI_REPO="${OPSORA_CLI_REPO:-https://github.com/Cladius-Weinert/opsora-cli.git}"
OPSORA_CLI_BRANCH="${OPSORA_CLI_BRANCH:-cursor/agent-stack-context-cache-c133}"
INSTALL_ROOT="${OPSORA_INSTALL_ROOT:-$HOME}"
CLI_DIR="$INSTALL_ROOT/opsora-cli"
OPSORA_DIR="$INSTALL_ROOT/.opsora"

echo "╔══════════════════════════════════════════════╗"
echo "║  OPSORA AWS AGENT STACK BOOTSTRAP            ║"
echo "╚══════════════════════════════════════════════╝"

sudo apt-get update -y
sudo apt-get install -y git python3 python3-pip python3-venv curl jq

# Clone or update opsora-cli
if [[ -d "$CLI_DIR/.git" ]]; then
  git -C "$CLI_DIR" fetch origin "$OPSORA_CLI_BRANCH"
  git -C "$CLI_DIR" checkout "$OPSORA_CLI_BRANCH"
  git -C "$CLI_DIR" pull --ff-only origin "$OPSORA_CLI_BRANCH" || true
else
  git clone --branch "$OPSORA_CLI_BRANCH" --depth 1 "$OPSORA_CLI_REPO" "$CLI_DIR"
fi

# Install opsora package (memory, cache, context, skills)
python3 -m pip install --user --upgrade pip
python3 -m pip install --user -e "$CLI_DIR"
python3 -m pip install --user 'litellm[proxy]' httpx rich prompt-toolkit openai boto3 requests

mkdir -p "$OPSORA_DIR/skills" "$OPSORA_DIR/claude-code" "$OPSORA_DIR/nvidia-custom"

# Environment file
ENV_FILE="$OPSORA_DIR/opsora_env"
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<EOF
# Opsora AWS agent stack — fill in secrets
export OPSORA_WORKSPACE_ROOT="$INSTALL_ROOT"
export OPSORA_DIR="$OPSORA_DIR"
export OPSORA_MAX_CONTEXT_TOKENS=24000
export OPSORA_KEEP_RECENT_MESSAGES=8
export OPSORA_PROVIDER_ORDER=nvidia,alibaba,bedrock,local
# export NVIDIA_API_KEY=nvapi-...
# export DASHSCOPE_API_KEY=sk-...
EOF
fi

# NVIDIA custom catalog build (if key present)
if [[ -n "${NVIDIA_API_KEY:-}" ]]; then
  bash "$CLI_DIR/deploy/ngc/build-custom-catalog.sh"
  cp -f "$OPSORA_DIR/nvidia-custom/opsora-nvidia-profiles.json" "$OPSORA_DIR/" 2>/dev/null || true
fi

# Claude Code Termux configs (also works on Linux brain)
cp -f "$CLI_DIR/claude-code-termux/litellm-config.yaml" "$OPSORA_DIR/claude-code/"
cp -f "$CLI_DIR/claude-code-termux/models.json" "$OPSORA_DIR/claude-code/"
bash "$CLI_DIR/claude-code-termux/setup-agent-stack.sh" || true

# Systemd service for LiteLLM gateway (optional)
if [[ "${OPSORA_INSTALL_GATEWAY_SERVICE:-1}" == "1" ]]; then
  sudo tee /etc/systemd/system/opsora-gateway.service >/dev/null <<UNIT
[Unit]
Description=Opsora LiteLLM Gateway
After=network.target

[Service]
Type=simple
User=$USER
EnvironmentFile=-$OPSORA_DIR/claude-code/secrets.env
EnvironmentFile=-$ENV_FILE
ExecStart=$(python3 -m site --user-base 2>/dev/null | xargs -I{} echo {}/bin/litellm) --config $OPSORA_DIR/claude-code/litellm-config.yaml --port 4000 --host 127.0.0.1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
  sudo systemctl daemon-reload
  echo "ℹ️  Enable gateway: sudo systemctl enable --now opsora-gateway"
fi

# Shell helpers
BIN_DIR="$INSTALL_ROOT/.local/bin"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/opsora-brain-status" <<'SCRIPT'
#!/usr/bin/env bash
source "$HOME/.opsora/opsora_env" 2>/dev/null || true
echo "=== Opsora Brain Status ==="
opsora --help 2>/dev/null | head -1 || echo "opsora CLI: not in PATH"
python3 -c "from opsora.memory import memory_stats; from opsora.cache import cache_stats; print('Memory:', memory_stats()); print('Cache:', cache_stats())" 2>/dev/null
curl -sf http://127.0.0.1:4000/health/liveliness >/dev/null && echo "Gateway: UP" || echo "Gateway: DOWN"
SCRIPT
chmod +x "$BIN_DIR/opsora-brain-status"

grep -q 'opsora_env' "$HOME/.bashrc" 2>/dev/null || echo "source $ENV_FILE 2>/dev/null" >> "$HOME/.bashrc"

echo ""
echo "✅ Bootstrap complete on $(hostname)"
echo "   CLI: $CLI_DIR"
echo "   Env: $ENV_FILE (add NVIDIA_API_KEY)"
echo "   Status: opsora-brain-status"
echo "   Gateway config: $OPSORA_DIR/claude-code/litellm-config.yaml"
