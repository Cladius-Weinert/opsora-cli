#!/data/data/com.termux/files/usr/bin/bash
# Opsora — Qwen Code CLI full-power setup untuk Termux (Android)
# Install: bash install-termux.sh
set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }

echo -e "${BOLD}${CYAN}"
echo '  ╔══════════════════════════════════════════════════╗'
echo '  ║  OPSORA — Qwen Code CLI Full Power (Termux)      ║'
echo '  ║  NVIDIA + DashScope + Reasoning + Embedding      ║'
echo '  ╚══════════════════════════════════════════════════╝'
echo -e "${NC}"

# ── Termux packages ─────────────────────────────────────────────
info "Updating Termux packages..."
pkg update -y
pkg upgrade -y
pkg install -y nodejs-lts git curl wget jq nano openssh python
pkg install -y termux-api 2>/dev/null || warn "termux-api tidak terpasang (TTS opsional)"

ok "Node $(node -v 2>/dev/null || echo '?') / Python $(python3 -V 2>/dev/null || echo '?')"

# ── Install dirs ────────────────────────────────────────────────
INSTALL_DIR="${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}"
REPO_DIR="${OPSORA_REPO_DIR:-$HOME/opsora-cli}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$INSTALL_DIR"
mkdir -p "$HOME/.qwen/agents"
mkdir -p "$HOME/.local/bin"
mkdir -p "${QWEN_PROJECTS_DIR:-$HOME/projects}"

# ── Clone opsora-cli jika belum ada ─────────────────────────────
if [[ ! -d "$REPO_DIR/.git" ]]; then
  info "Cloning opsora-cli..."
  git clone --depth 1 https://github.com/Cladius-Weinert/opsora-cli.git "$REPO_DIR" 2>/dev/null \
    || git clone --depth 1 https://github.com/opsora/opsora-cli.git "$REPO_DIR"
fi

# ── Copy config files ───────────────────────────────────────────
info "Installing configs ke $INSTALL_DIR..."
QWEN_SRC="$REPO_DIR/qwen-code-termux"
[[ -d "$QWEN_SRC" ]] || QWEN_SRC="$SRC_DIR"

cp -f "$QWEN_SRC/settings.json" "$INSTALL_DIR/"
cp -f "$QWEN_SRC/models.json" "$INSTALL_DIR/"
cp -f "$QWEN_SRC/rpm-config.json" "$INSTALL_DIR/"
cp -f "$QWEN_SRC/embedding-config.json" "$INSTALL_DIR/"
cp -f "$QWEN_SRC/"*.sh "$INSTALL_DIR/" 2>/dev/null || true
chmod +x "$INSTALL_DIR/"*.sh 2>/dev/null || true
[[ -f "$QWEN_SRC/opsora-audit.sh" ]] && chmod +x "$INSTALL_DIR/opsora-audit.sh"

if [[ -d "$QWEN_SRC/agents" ]]; then
  cp -f "$QWEN_SRC/agents/"*.md "$HOME/.qwen/agents/" 2>/dev/null || true
fi

if [[ ! -f "$INSTALL_DIR/secrets.env" ]]; then
  cp "$QWEN_SRC/secrets.env.example" "$INSTALL_DIR/secrets.env"
  warn "Edit API keys: nano $INSTALL_DIR/secrets.env"
fi

# ── Qwen Code CLI (Termux fork) ─────────────────────────────────
if ! command -v qwen >/dev/null 2>&1; then
  info "Installing @mmmbuto/qwen-code-termux..."
  npm install -g @mmmbuto/qwen-code-termux@latest
fi
ok "Qwen Code $(qwen --version 2>/dev/null || echo 'installed')"

# ── Qwen settings.json ──────────────────────────────────────────
if [[ ! -f "$HOME/.qwen/settings.json" ]]; then
  cp "$INSTALL_DIR/settings.json" "$HOME/.qwen/settings.json"
  ok "Created ~/.qwen/settings.json"
else
  warn "~/.qwen/settings.json sudah ada — backup dulu jika ingin replace:"
  warn "  cp ~/.qwen/settings.json ~/.qwen/settings.json.bak"
  warn "  cp $INSTALL_DIR/settings.json ~/.qwen/settings.json"
fi

# ── Link secrets to ~/.qwen/.env ────────────────────────────────
if [[ ! -f "$HOME/.qwen/.env" ]] && [[ -f "$INSTALL_DIR/secrets.env" ]]; then
  ln -sf "$INSTALL_DIR/secrets.env" "$HOME/.qwen/.env"
  ok "Linked ~/.qwen/.env → secrets.env"
fi

# ── Shell helpers ───────────────────────────────────────────────
BIN_DIR="$HOME/.local/bin"

cat >"$BIN_DIR/opsora-qwen" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
INSTALL_DIR="${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}"
[[ -f "$INSTALL_DIR/secrets.env" ]] && set -a && source "$INSTALL_DIR/secrets.env" && set +a
[[ -f "$HOME/.qwen/.env" ]] && set -a && source "$HOME/.qwen/.env" && set +a
cd "${QWEN_PROJECTS_DIR:-$HOME/projects}"
exec qwen "$@"
WRAP

cat >"$BIN_DIR/opsora-qwen-model" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
exec "${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}/switch-model.sh" "$@"
WRAP

cat >"$BIN_DIR/opsora-qwen-sync" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
exec "${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}/sync-providers.sh" "$@"
WRAP

cat >"$BIN_DIR/opsora-qwen-test" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
exec "${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}/test-models.sh" "$@"
WRAP

cat >"$BIN_DIR/opsora-qwen-embed" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
exec "${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}/embed.sh" "$@"
WRAP

cat >"$BIN_DIR/opsora-audit" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
exec "${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}/opsora-audit.sh" "$@"
WRAP

chmod +x "$BIN_DIR/opsora-qwen" "$BIN_DIR/opsora-qwen-model" \
  "$BIN_DIR/opsora-qwen-sync" "$BIN_DIR/opsora-qwen-test" "$BIN_DIR/opsora-qwen-embed" \
  "$BIN_DIR/opsora-audit"

# ── PATH + aliases ──────────────────────────────────────────────
MARKER="# >>> opsora-qwen-termux >>>"
if ! grep -q "$MARKER" "$HOME/.bashrc" 2>/dev/null; then
  cat >>"$HOME/.bashrc" <<'BASHRC'

# >>> opsora-qwen-termux >>>
export OPSORA_QWEN_DIR="${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}"
export QWEN_PROJECTS_DIR="${QWEN_PROJECTS_DIR:-$HOME/projects}"
export PATH="$HOME/.local/bin:$(npm bin -g 2>/dev/null || echo $PREFIX/bin):$PATH"
[[ -f "$HOME/.qwen/.env" ]] && set -a && source "$HOME/.qwen/.env" && set +a
alias qw='cd "$QWEN_PROJECTS_DIR" && opsora-qwen'
alias qw-power='opsora-qwen-model power && qw'
alias qw-fast='opsora-qwen-model fast && qw'
alias qw-reason='opsora-qwen-model reasoning && qw'
alias qw-nvidia='opsora-qwen-model nvidia-coder && qw'
alias qw-audit='opsora-audit all'
# <<< opsora-qwen-termux <<<
BASHRC
  ok "Added aliases ke ~/.bashrc"
fi

export PATH="$HOME/.local/bin:$PATH"

# ── Done ──────────────────────────────────────────────────────
echo ""
ok "Install selesai!"
echo ""
echo "Langkah berikutnya:"
echo "  1. Isi API keys:"
echo "     nano $INSTALL_DIR/secrets.env"
echo ""
echo "  2. Sync & audit providers:"
echo "     opsora-qwen-sync"
echo ""
echo "  3. Test semua model:"
echo "     opsora-qwen-test"
echo ""
echo "  4. Pilih model:"
echo "     opsora-qwen-model power       # Qwen3 Coder Plus (default)"
echo "     opsora-qwen-model reasoning   # Qwen3.7 Max + thinking"
echo "     opsora-qwen-model nvidia-coder # DeepSeek V4 Flash"
echo ""
echo "  5. Audit & konteks Opsora:"
echo "     opsora-audit all"
echo "     opsora-audit export   # load di Qwen: @context-bundle.md"
echo ""
echo "  6. Jalankan Qwen Code:"
echo "     opsora-qwen"
echo "     # atau: qw-power / qw-audit"
echo ""
echo "Profiles: power, reasoning, balanced, coder-next, fast,"
echo "          nvidia-coder, nvidia-reasoning, nvidia-power, nvidia-fast, coding-plan"
