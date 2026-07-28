#!/data/data/com.termux/files/usr/bin/bash
# Selesaikan setup Codex setelah ~/.codex/.env sudah diisi.
# Usage: bash finish-setup.sh
set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()   { echo -e "${RED}[ERR]${NC} $*"; exit 1; }

export PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
export HOME="${HOME:-/data/data/com.termux/files/home}"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
SETUP_DIR="${CODEX_SETUP_DIR:-$HOME/.local/share/codex-termux-nvidia-setup}"
REPO_RAW="${CODEX_SETUP_REPO:-https://raw.githubusercontent.com/Cladius-Weinert/opsora-cli/main/codex-termux-nvidia-setup}"
BIN_DIR="$HOME/.local/bin"

echo -e "${BOLD}${CYAN}Codex Termux — finish setup${NC}"

mkdir -p "$CODEX_HOME" "$HOME/projects" "$BIN_DIR" "$SETUP_DIR/dot-codex"

# ── .env wajib ──────────────────────────────────────────────────
if [[ ! -f "$CODEX_HOME/.env" ]]; then
  die "File $CODEX_HOME/.env belum ada. Buat dulu:\n  nano ~/.codex/.env\nIsi OPENROUTER_API_KEY= dan NVIDIA_API_KEY="
fi
ok "Found $CODEX_HOME/.env"

set -a
# shellcheck disable=SC1090
source "$CODEX_HOME/.env"
set +a

[[ -n "${OPENROUTER_API_KEY:-}" ]] || die "OPENROUTER_API_KEY kosong di ~/.codex/.env"
[[ -n "${NVIDIA_API_KEY:-}" ]] || warn "NVIDIA_API_KEY kosong — BYOK NVIDIA di OpenRouter mungkin belum bisa"

# ── Codex Termux fork ───────────────────────────────────────────
if ! command -v codex >/dev/null 2>&1; then
  info "Installing @mmmbuto/codex-cli-termux ..."
  npm install -g @mmmbuto/codex-cli-termux@latest
fi
export PATH="$(npm bin -g 2>/dev/null || echo "$PREFIX/bin"):$BIN_DIR:$PATH"
command -v codex >/dev/null 2>&1 || die "codex tidak ada di PATH"
ok "codex $(codex --version 2>/dev/null || echo ok)"

# ── config.toml ─────────────────────────────────────────────────
if [[ ! -f "$CODEX_HOME/config.toml" ]]; then
  info "Downloading config.toml ..."
  curl -fsSL "$REPO_RAW/dot-codex/config.toml" -o "$CODEX_HOME/config.toml"
fi
ok "config.toml ready"

# ── smoke-test ──────────────────────────────────────────────────
if [[ ! -f "$BIN_DIR/codex-smoke-test" ]]; then
  curl -fsSL "$REPO_RAW/smoke-test.sh" -o "$BIN_DIR/codex-smoke-test"
  chmod +x "$BIN_DIR/codex-smoke-test"
fi

info "Testing OpenRouter /responses ..."
if bash "$BIN_DIR/codex-smoke-test" openrouter; then
  ok "OpenRouter OK"
else
  warn "OpenRouter test gagal — cek key di openrouter.ai/keys"
fi

if [[ -n "${NVIDIA_API_KEY:-}" ]]; then
  info "Testing NVIDIA /chat/completions ..."
  bash "$BIN_DIR/codex-smoke-test" nvidia || warn "NVIDIA test gagal — cek key di build.nvidia.com"
fi

# ── bashrc minimal ──────────────────────────────────────────────
if ! grep -qF "codex-termux-nvidia" "$HOME/.bashrc" 2>/dev/null; then
  cat >>"$HOME/.bashrc" <<'EOF'

# >>> codex-termux-nvidia >>>
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export PATH="$(npm bin -g 2>/dev/null || echo $PREFIX/bin):$HOME/.local/bin:$PATH"
if [[ -f "$HOME/.codex/.env" ]]; then set -a; source "$HOME/.codex/.env"; set +a; fi
alias cdx-qwen='codex --profile nvidia-qwen-coder'
alias cdx-flash='codex --profile nvidia-deepseek-flash'
# <<< codex-termux-nvidia <<<
EOF
fi

echo
echo -e "${BOLD}${GREEN}Setup selesai!${NC}"
echo
echo "1. BYOK NVIDIA (wajib sekali, di browser HP):"
echo "   https://openrouter.ai/settings/integrations"
echo "   → NVIDIA → paste NVIDIA_API_KEY dari ~/.codex/.env"
echo
if command -v termux-open-url >/dev/null 2>&1; then
  read -r -p "Buka halaman BYOK sekarang? [y/N] " ans || ans=n
  if [[ "${ans,,}" == "y" ]]; then
    termux-open-url "https://openrouter.ai/settings/integrations"
  fi
fi
echo
echo "2. Jalankan Codex:"
echo "   source ~/.bashrc"
echo "   cd ~/projects"
echo "   codex --profile nvidia-qwen-coder"
echo
echo -e "${YELLOW}Jangan paste API key di chat — simpan hanya di ~/.codex/.env${NC}"
