#!/usr/bin/env bash
# smoke-test.sh — curl probes for OpenRouter /responses, LiteLLM /responses, NVIDIA /chat/completions
# Usage:
#   ./smoke-test.sh              # run all available (keys present)
#   ./smoke-test.sh openrouter
#   ./smoke-test.sh litellm
#   ./smoke-test.sh nvidia
#   ./smoke-test.sh all
set -euo pipefail

# Load ~/.codex/.env if present
if [[ -f "${CODEX_HOME:-$HOME/.codex}/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${CODEX_HOME:-$HOME/.codex}/.env"
  set +a
fi
# Also load local .env (VPS)
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }
skip() { echo -e "${YELLOW}[SKIP]${NC} $*"; }

TARGET="${1:-all}"
FAILS=0

OR_MODEL="${SMOKE_MODEL_OPENROUTER:-qwen/qwen3-coder}"
LL_MODEL="${SMOKE_MODEL_LITELLM:-nvidia-qwen3-coder}"
NV_MODEL="${SMOKE_MODEL_NVIDIA:-deepseek-ai/deepseek-v4-flash}"

# Prefer LITELLM_BASE_URL from env; strip trailing slash
LITELLM_URL="${LITELLM_BASE_URL:-http://127.0.0.1:4000/v1}"
LITELLM_URL="${LITELLM_URL%/}"
LITELLM_KEY="${LITELLM_API_KEY:-${LITELLM_MASTER_KEY:-}}"

json_has() {
  # $1=json $2=substring
  echo "$1" | grep -q "$2"
}

# ── OpenRouter /v1/responses ────────────────────────────────────
test_openrouter() {
  info "OpenRouter POST /api/v1/responses model=$OR_MODEL"
  if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
    skip "OPENROUTER_API_KEY not set"
    return 0
  fi
  local body resp code
  body="$(jq -nc \
    --arg m "$OR_MODEL" \
    '{model:$m, input:"Reply with exactly: OK_OPENROUTER", max_output_tokens:32}')"
  resp="$(curl -sS -w '\n%{http_code}' \
    https://openrouter.ai/api/v1/responses \
    -H "Authorization: Bearer ${OPENROUTER_API_KEY}" \
    -H "Content-Type: application/json" \
    -H "HTTP-Referer: https://github.com/mmmbuto/codex-cli-termux" \
    -H "X-Title: Codex-Termux-Smoke" \
    -d "$body" || true)"
  code="$(echo "$resp" | tail -n1)"
  body="$(echo "$resp" | sed '$d')"
  echo "$body" | head -c 800
  echo
  if [[ "$code" == "200" ]] && (json_has "$body" '"output"' || json_has "$body" 'OK_OPENROUTER' || json_has "$body" '"content"'); then
    pass "OpenRouter /responses HTTP $code"
  else
    fail "OpenRouter /responses HTTP $code"
    FAILS=$((FAILS + 1))
  fi
}

# ── LiteLLM /v1/responses (bridge → chat completions) ───────────
test_litellm() {
  info "LiteLLM POST ${LITELLM_URL}/responses model=$LL_MODEL"
  if [[ -z "$LITELLM_KEY" ]]; then
    skip "LITELLM_API_KEY / LITELLM_MASTER_KEY not set"
    return 0
  fi
  local body resp code
  body="$(jq -nc \
    --arg m "$LL_MODEL" \
    '{model:$m, input:"Reply with exactly: OK_LITELLM", max_output_tokens:32}')"
  resp="$(curl -sS -w '\n%{http_code}' \
    "${LITELLM_URL}/responses" \
    -H "Authorization: Bearer ${LITELLM_KEY}" \
    -H "Content-Type: application/json" \
    -d "$body" || true)"
  code="$(echo "$resp" | tail -n1)"
  body="$(echo "$resp" | sed '$d')"
  echo "$body" | head -c 800
  echo
  if [[ "$code" == "200" ]] && (json_has "$body" '"output"' || json_has "$body" 'OK_LITELLM' || json_has "$body" '"content"' || json_has "$body" '"choices"'); then
    pass "LiteLLM /responses HTTP $code"
  else
    fail "LiteLLM /responses HTTP $code (is proxy up? use_chat_completions_api set?)"
    FAILS=$((FAILS + 1))
  fi
}

# ── NVIDIA NIM /v1/chat/completions (raw — proves chat-only API) ─
test_nvidia() {
  info "NVIDIA POST /v1/chat/completions model=$NV_MODEL"
  if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
    skip "NVIDIA_API_KEY not set"
    return 0
  fi
  local body resp code
  body="$(jq -nc \
    --arg m "$NV_MODEL" \
    '{model:$m, messages:[{role:"user",content:"Reply with exactly: OK_NVIDIA"}], max_tokens:32, temperature:0.2}')"
  resp="$(curl -sS -w '\n%{http_code}' \
    https://integrate.api.nvidia.com/v1/chat/completions \
    -H "Authorization: Bearer ${NVIDIA_API_KEY}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d "$body" || true)"
  code="$(echo "$resp" | tail -n1)"
  body="$(echo "$resp" | sed '$d')"
  echo "$body" | head -c 800
  echo
  if [[ "$code" == "200" ]] && json_has "$body" '"choices"'; then
    pass "NVIDIA /chat/completions HTTP $code"
  else
    fail "NVIDIA /chat/completions HTTP $code"
    FAILS=$((FAILS + 1))
  fi

  # Negative probe: /responses on NVIDIA should fail (documents why LiteLLM bridge is required)
  info "NVIDIA negative probe: /v1/responses (expect non-200)"
  resp="$(curl -sS -w '\n%{http_code}' \
    https://integrate.api.nvidia.com/v1/responses \
    -H "Authorization: Bearer ${NVIDIA_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$(jq -nc --arg m "$NV_MODEL" '{model:$m, input:"hi"}')" || true)"
  code="$(echo "$resp" | tail -n1)"
  if [[ "$code" != "200" ]]; then
    pass "NVIDIA /responses correctly unavailable (HTTP $code) — use OpenRouter or LiteLLM bridge"
  else
    warn_msg="NVIDIA unexpectedly accepted /responses — re-check docs"
    echo -e "${YELLOW}[WARN]${NC} $warn_msg"
  fi
}

need_jq() {
  if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required. Termux: pkg install jq"
    exit 1
  fi
}

need_jq

case "$TARGET" in
  openrouter) test_openrouter ;;
  litellm)    test_litellm ;;
  nvidia)     test_nvidia ;;
  all|"")
    test_openrouter
    echo
    test_litellm
    echo
    test_nvidia
    ;;
  *)
    echo "Usage: $0 [openrouter|litellm|nvidia|all]"
    exit 2
    ;;
esac

echo
if [[ "$FAILS" -gt 0 ]]; then
  fail "$FAILS test(s) failed — see TROUBLESHOOTING.md"
  exit 1
fi
pass "Smoke tests finished (failures=$FAILS)"
