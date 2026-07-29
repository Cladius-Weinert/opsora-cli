#!/usr/bin/env bash
# Setup Opsora agent stack: memory, cache, context, skills on Termux or Linux
set -euo pipefail

INSTALL_DIR="${OPSORA_CLAUDE_DIR:-$HOME/.opsora/claude-code}"
REPO_DIR="${OPSORA_REPO_DIR:-$HOME/opsora-cli}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$INSTALL_DIR"
mkdir -p "$HOME/.opsora/skills"
mkdir -p "$HOME/.opsora/sessions"

echo "=== Opsora Agent Stack Setup ==="

# Copy verified NVIDIA configs
cp -f "$SRC_DIR/litellm-config.yaml" "$INSTALL_DIR/"
cp -f "$SRC_DIR/models.json" "$INSTALL_DIR/"
cp -f "$SRC_DIR/nvidia-cloud-catalog.json" "$INSTALL_DIR/" 2>/dev/null || true

# Install Python stack for memory/cache/skills
if command -v pip3 >/dev/null 2>&1; then
  pip3 install --upgrade pip
  pip3 install 'litellm[proxy]' httpx rich prompt-toolkit openai boto3 requests
fi

# Install opsora-cli package (memory + cache + skills)
if [[ -d "$REPO_DIR" ]]; then
  pip3 install -e "$REPO_DIR"
else
  echo "Clone opsora-cli first:"
  echo "  git clone https://github.com/Cladius-Weinert/opsora-cli.git $REPO_DIR"
  exit 1
fi

# Environment defaults
ENV_FILE="$INSTALL_DIR/agent-stack.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'EOF'
# Opsora agent stack — memory, cache, context, skills
export OPSORA_WORKSPACE_ROOT="$HOME"
export OPSORA_DIR="$HOME/.opsora"
export OPSORA_MAX_CONTEXT_TOKENS=24000
export OPSORA_KEEP_RECENT_MESSAGES=8
export OPSORA_SKILLS_DIRS="$HOME/.opsora/skills"
EOF
fi

# Seed bundled skills into user skills dir
BUNDLED="$REPO_DIR/cmd/opsora/bundled_skills"
if [[ -d "$BUNDLED" ]]; then
  cp -rn "$BUNDLED"/* "$HOME/.opsora/skills/" 2>/dev/null || true
fi

# Claude Code project memory file
CLAUDE_MD="$HOME/.opsora/CLAUDE.md"
if [[ ! -f "$CLAUDE_MD" ]]; then
  cat > "$CLAUDE_MD" <<'EOF'
# Opsora Agent Context

- Use NVIDIA Integrate API via LiteLLM gateway on port 4000
- Default model: opsora-balanced (Llama 3.1 70B)
- Coding model: opsora-coder (DeepSeek V4 Pro)
- Search memory before large refactors
- Load skills for NVIDIA, Termux, and project-specific workflows
- Prefer small tool steps to avoid NVIDIA rate limits (~40 RPM trial)
EOF
fi

echo ""
echo "✅ Agent stack ready"
echo "   Config : $INSTALL_DIR"
echo "   Memory : $HOME/.opsora/memory.db"
echo "   Cache  : $HOME/.opsora/cache.db"
echo "   Skills : $HOME/.opsora/skills"
echo ""
echo "Next:"
echo "  source $INSTALL_DIR/secrets.env"
echo "  source $ENV_FILE"
echo "  opsora-gateway"
echo "  opsora-model balanced && opsora-claude"
