#!/data/data/com.termux/files/usr/bin/bash
# Codex CLI (Termux fork) + OpenRouter/NVIDIA bootstrap
# Usage: bash termux-install.sh
# English comments; user messages bilingual where helpful.
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

echo -e "${BOLD}${CYAN}"
echo '  ╔══════════════════════════════════════════════════╗'
echo '  ║  Codex CLI Termux + NVIDIA / OpenRouter          ║'
echo '  ║  Path A: OpenRouter BYOK  |  Path B: LiteLLM     ║'
echo '  ╚══════════════════════════════════════════════════╝'
echo -e "${NC}"

# ── Detect Termux ───────────────────────────────────────────────
if [[ ! -d /data/data/com.termux/files/usr ]]; then
  warn "Not running inside Termux — continuing anyway (dev/CI)."
fi

# Prefer Termux prefix when present
export PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
export HOME="${HOME:-$PREFIX/../home}"
# Normalize HOME for Termux
if [[ -d /data/data/com.termux/files/home ]]; then
  HOME="/data/data/com.termux/files/home"
  export HOME
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
PROJECTS_DIR="${PROJECTS_DIR:-$HOME/projects}"
BIN_DIR="$HOME/.local/bin"
SETUP_DIR="${CODEX_SETUP_DIR:-$HOME/.local/share/codex-termux-nvidia-setup}"
REPO_RAW="${CODEX_SETUP_REPO:-https://raw.githubusercontent.com/Cladius-Weinert/opsora-cli/main/codex-termux-nvidia-setup}"

# When installed via `curl ... | bash`, companion files are not beside the script.
ensure_setup_files() {
  local cfg="$SRC_DIR/dot-codex/config.toml"
  if [[ -f "$cfg" ]]; then
  return 0
  fi
  info "Mengunduh file konfigurasi dari GitHub..."
  mkdir -p "$SETUP_DIR/dot-codex"
  local files=(
    "dot-codex/config.toml"
    "dot-codex/env.example"
    "smoke-test.sh"
    "TROUBLESHOOTING.md"
    "README.md"
  )
  local f url
  for f in "${files[@]}"; do
    url="$REPO_RAW/$f"
    if curl -fsSL "$url" -o "$SETUP_DIR/$f"; then
      ok "  $f"
    else
      warn "  gagal unduh $f"
    fi
  done
  SRC_DIR="$SETUP_DIR"
}
ensure_setup_files

# ── Packages ────────────────────────────────────────────────────
info "Updating packages..."
if command -v pkg >/dev/null 2>&1; then
  pkg update -y
  pkg upgrade -y
  pkg install -y git curl wget jq openssh which nano \
    clang make pkg-config openssl libffi zlib \
    tur-repo 2>/dev/null || true
  # Node LTS required for npm global Codex Termux package
  if ! command -v node >/dev/null 2>&1; then
    pkg install -y nodejs-lts || pkg install -y nodejs
  fi
  # Optional: termux-api for termux-open-url (login / browser helpers)
  pkg install -y termux-api 2>/dev/null || warn "termux-api optional (install Termux:API app for URL open)"
else
  warn "pkg not found — install nodejs, git, curl, jq manually"
fi

NODE_VER="$(node -v 2>/dev/null || true)"
[[ -n "$NODE_VER" ]] || die "Node.js missing. Install nodejs-lts then re-run."
ok "Node $NODE_VER / npm $(npm -v 2>/dev/null || echo '?')"

# ── Directories (NEVER use /sdcard for projects) ────────────────
info "Creating dirs: $CODEX_HOME and $PROJECTS_DIR"
mkdir -p "$CODEX_HOME" "$PROJECTS_DIR" "$BIN_DIR" "$HOME/.local/share"

# Soft-link convenience (optional)
if [[ ! -e "$HOME/Projects" ]]; then
  ln -sfn "$PROJECTS_DIR" "$HOME/Projects" 2>/dev/null || true
fi

# ── Uninstall official Codex if present (breaks on Bionic) ──────
if npm list -g @openai/codex >/dev/null 2>&1; then
  warn "Removing official @openai/codex (fails on Termux Bionic)..."
  npm uninstall -g @openai/codex || true
fi

# ── Install Termux Codex fork ───────────────────────────────────
info "Installing @mmmbuto/codex-cli-termux@latest ..."
npm install -g @mmmbuto/codex-cli-termux@latest

if ! command -v codex >/dev/null 2>&1; then
  # Ensure npm global bin is on PATH
  NPM_BIN="$(npm bin -g 2>/dev/null || npm prefix -g)/bin"
  export PATH="$NPM_BIN:$BIN_DIR:$PATH"
  if ! command -v codex >/dev/null 2>&1; then
    die "codex binary not on PATH. Add to ~/.bashrc: export PATH=\"$NPM_BIN:\$HOME/.local/bin:\$PATH\""
  fi
fi
ok "codex $(codex --version 2>/dev/null || echo 'installed')"

# ── Install config.toml (user-level ONLY) ───────────────────────
CFG_SRC="$SRC_DIR/dot-codex/config.toml"
ENV_SRC="$SRC_DIR/dot-codex/env.example"

if [[ -f "$CFG_SRC" ]]; then
  if [[ -f "$CODEX_HOME/config.toml" ]]; then
    BACKUP="$CODEX_HOME/config.toml.bak.$(date +%Y%m%d%H%M%S)"
    cp -f "$CODEX_HOME/config.toml" "$BACKUP"
    warn "Existing config backed up → $BACKUP"
  fi
  cp -f "$CFG_SRC" "$CODEX_HOME/config.toml"
  ok "Wrote $CODEX_HOME/config.toml"
else
  warn "Missing $CFG_SRC — create config.toml manually (see README)"
fi

if [[ -f "$ENV_SRC" ]]; then
  if [[ ! -f "$CODEX_HOME/.env" ]]; then
    cp -f "$ENV_SRC" "$CODEX_HOME/.env"
    warn "Edit API keys: nano $CODEX_HOME/.env"
  else
    ok "$CODEX_HOME/.env already exists — not overwriting"
  fi
  # Keep example for reference
  cp -f "$ENV_SRC" "$CODEX_HOME/.env.example"
fi

# ── Shell env loader ────────────────────────────────────────────
BASHRC="$HOME/.bashrc"
MARKER="# >>> codex-termux-nvidia >>>"
if ! grep -qF "$MARKER" "$BASHRC" 2>/dev/null; then
  info "Appending PATH + .env loader to ~/.bashrc"
  cat >>"$BASHRC" <<'EOF'

# >>> codex-termux-nvidia >>>
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export PATH="$(npm bin -g 2>/dev/null || echo $PREFIX/bin):$HOME/.local/bin:$PATH"
# Load API keys for Codex / smoke tests (never commit .env)
if [[ -f "$HOME/.codex/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$HOME/.codex/.env"
  set +a
fi
# Prefer ~/projects for all coding work (avoid /sdcard FUSE quirks)
export CODEX_PROJECTS_DIR="${CODEX_PROJECTS_DIR:-$HOME/projects}"
alias cdx='cd "$CODEX_PROJECTS_DIR" && codex'
alias cdx-qwen='codex --profile nvidia-qwen-coder'
alias cdx-flash='codex --profile nvidia-deepseek-flash'
alias cdx-nemo='codex --profile nvidia-nemotron'
alias cdx-llama='codex --profile nvidia-llama70'
alias cdx-litellm='codex --profile litellm-qwen-coder'
# <<< codex-termux-nvidia <<<
EOF
  ok "Updated ~/.bashrc — run: source ~/.bashrc"
else
  ok "~/.bashrc already has codex-termux-nvidia block"
fi

# ── PATH for current session ────────────────────────────────────
export PATH="$(npm bin -g 2>/dev/null || true):$BIN_DIR:$PATH"
if [[ -f "$CODEX_HOME/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CODEX_HOME/.env"
  set +a
fi

# ── Helper: switch LiteLLM base URL ─────────────────────────────
cat >"$BIN_DIR/codex-use-litellm" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/bash
# Usage: codex-use-litellm https://vps.example.com:4000/v1
# Writes LITELLM_BASE_URL to ~/.codex/.env AND patches config.toml base_url
set -euo pipefail
BASE="${1:-}"
[[ -n "$BASE" ]] || { echo "Usage: codex-use-litellm https://HOST:4000/v1"; exit 1; }
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
ENVF="$CODEX_HOME/.env"
CFGF="$CODEX_HOME/config.toml"
touch "$ENVF"
if grep -q '^LITELLM_BASE_URL=' "$ENVF" 2>/dev/null; then
  sed -i "s|^LITELLM_BASE_URL=.*|LITELLM_BASE_URL=$BASE|" "$ENVF"
else
  echo "LITELLM_BASE_URL=$BASE" >>"$ENVF"
fi
if [[ -f "$CFGF" ]]; then
  # Patch only the litellm_proxy provider base_url (Codex reads TOML, not env for base_url)
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$CFGF" "$BASE" <<'PY'
import re, sys
path, base = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
pat = re.compile(
    r"(?ms)(\[model_providers\.litellm_proxy\][^\[]*?)(base_url\s*=\s*\")([^\"]*)(\")"
)
new, n = pat.subn(r"\1\2" + base + r"\4", text, count=1)
if n != 1:
    sys.exit(1)
open(path, "w", encoding="utf-8").write(new)
print("patched config.toml litellm_proxy.base_url")
PY
  else
    sed -i "s|^base_url = \".*\"  *# litellm-proxy-base|base_url = \"$BASE\"  # litellm-proxy-base|" "$CFGF"
  fi
fi
echo "[OK] LITELLM_BASE_URL=$BASE"
echo "     Run: source ~/.codex/.env && codex --profile litellm-qwen-coder"
WRAP
chmod +x "$BIN_DIR/codex-use-litellm"

# ── Smoke test copy ─────────────────────────────────────────────
if [[ -f "$SRC_DIR/smoke-test.sh" ]]; then
  cp -f "$SRC_DIR/smoke-test.sh" "$BIN_DIR/codex-smoke-test"
  chmod +x "$BIN_DIR/codex-smoke-test" "$SRC_DIR/smoke-test.sh"
fi

# ── Final checklist ─────────────────────────────────────────────
echo
ok "Bootstrap selesai / Bootstrap complete"
echo
echo -e "${BOLD}Langkah berikutnya / Next steps:${NC}"
echo "  1. nano ~/.codex/.env   # set OPENROUTER_API_KEY (Path A)"
echo "  2. OpenRouter BYOK: tambahkan NVIDIA key di"
echo "     https://openrouter.ai/settings/integrations"
echo "  3. source ~/.bashrc"
echo "  4. bash $SRC_DIR/smoke-test.sh openrouter"
echo "  5. cd ~/projects && codex --profile nvidia-qwen-coder"
echo
echo "  Path B (VPS): deploy litellm-docker-compose.yml,"
echo "  lalu: codex-use-litellm https://YOUR_VPS:4000/v1"
echo
echo -e "${YELLOW}Jangan simpan proyek di /sdcard — gunakan ~/projects${NC}"
