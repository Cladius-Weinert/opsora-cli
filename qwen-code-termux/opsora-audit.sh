#!/usr/bin/env bash
# Opsora Audit — secret status, repo health, context export untuk Qwen Code
# Usage: opsora-audit [secrets|repos|context|health|export|reveal|all|help]
set -euo pipefail

VERSION="1.0.0"
INSTALL_DIR="${OPSORA_QWEN_DIR:-$HOME/.opsora/qwen-code}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$INSTALL_DIR/models.json" ]] || INSTALL_DIR="$SCRIPT_DIR"
SECRETS_FILE="${INSTALL_DIR}/secrets.env"
PRIVATE_DIR="${HOME}/.opsora/private"
SNAPSHOT_FILE="${PRIVATE_DIR}/credentials.snapshot"
EXPORT_FILE="${INSTALL_DIR}/context-bundle.md"
MEMORY_FILE="${SCRIPT_DIR}/OPSORA_MEMORY_KONTEKS.md"

# shellcheck disable=SC2034
CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERR]${NC} $*" >&2; }

load_secrets() {
  [[ -f "$SECRETS_FILE" ]] && set -a && source "$SECRETS_FILE" && set +a
  [[ -f "$HOME/.qwen/.env" ]] && set -a && source "$HOME/.qwen/.env" && set +a
}

# Mask: first 4 + last 4 chars, never full value on stdout
mask_value() {
  local v="$1"
  local len=${#v}
  if [[ -z "$v" ]]; then
    echo "MISSING"
  elif [[ "$len" -le 12 ]]; then
    echo "SET (len=${len}, masked)"
  else
    echo "${v:0:4}...${v: -4} (len=${len})"
  fi
}

secret_status() {
  local name="$1"
  local val="${!name:-}"
  local file_hint="$2"
  if [[ -n "$val" ]]; then
    printf "  %-40s ✅ %s\n" "$name" "$(mask_value "$val")"
  else
    printf "  %-40s ❌ MISSING  → %s\n" "$name" "$file_hint"
  fi
}

cmd_secrets() {
  load_secrets
  echo -e "${BOLD}=== Opsora Secret Audit (masked — nilai penuh TIDAK ditampilkan) ===${NC}"
  echo "Secrets file: ${SECRETS_FILE}"
  echo ""

  echo "── AI Providers (Qwen / NVIDIA) ──"
  secret_status DASHSCOPE_API_KEY "nano $SECRETS_FILE"
  secret_status NVIDIA_API_KEY "https://org.ngc.nvidia.com/setup/api-keys"
  secret_status BAILIAN_CODING_PLAN_API_KEY "opsional — Coding Plan console"
  secret_status AI_API_KEY "opsora-dashboard .env"
  secret_status LLM_API_KEY "memori-agent-dashboard deploy/.env"

  echo ""
  echo "── Lead Flow & Auth ──"
  secret_status OPSORA_LEAD_API_TOKEN "opsora-landing + dashboard .env"
  secret_status OPSORA_WEBHOOK_URL "opsora-landing .env"
  secret_status OPSORA_ADMIN_PASSWORD "opsora/infra/.env"
  secret_status OPSORA_PAY_SECRET "opsora/infra/.env"
  secret_status JWT_SECRET "memori-agent-dashboard"
  secret_status CRON_SECRET "opsora-dashboard Vercel"

  echo ""
  echo "── Supabase ──"
  secret_status NEXT_PUBLIC_SUPABASE_URL "Supabase dashboard → API"
  secret_status NEXT_PUBLIC_SUPABASE_ANON_KEY "Supabase dashboard → API"
  secret_status SUPABASE_SERVICE_ROLE_KEY "server-side only"
  secret_status SUPABASE_URL "memori-agent"
  secret_status SUPABASE_ANON_KEY "memori-agent"

  echo ""
  echo "── Messaging & Payment ──"
  secret_status RESEND_API_KEY "opsora-dashboard / secrets/resend_api_key"
  secret_status WATI_API_TOKEN "opsora-dashboard"
  secret_status MIDTRANS_SERVER_KEY "opsora/operatoros"
  secret_status MIDTRANS_CLIENT_KEY "opsora/operatoros"

  echo ""
  echo "── Infra / Cloud ──"
  secret_status VULTR_API_KEY "opsora/secrets/vultr_api_key"
  secret_status AWS_ACCESS_KEY_ID "AWS IAM"
  secret_status AWS_SECRET_ACCESS_KEY "AWS IAM"
  secret_status TF_API_TOKEN "Terraform Cloud"
  secret_status VAULT_ADDR "opsora/secrets/vault_addr"
  secret_status VERCEL_TOKEN "CircleCI / Vercel"

  echo ""
  echo "── Qwen tuning ──"
  secret_status OPSORA_QWEN_DEFAULT_PROFILE "default: power"
  secret_status OPSORA_QWEN_FAST_PROFILE "default: fast"
  secret_status QWEN_PROJECTS_DIR "default: \$HOME/projects"

  echo ""
  local missing
  missing=$(cmd_secrets_count_missing)
  if [[ "$missing" -eq 0 ]]; then
    ok "Semua secret wajib terisi."
  else
    warn "$missing secret penting masih kosong. Edit: nano $SECRETS_FILE"
    echo "  Snapshot lokal (opsional): opsora-audit reveal --yes-i-understand"
  fi
}

cmd_secrets_count_missing() {
  load_secrets
  local count=0
  for v in DASHSCOPE_API_KEY NVIDIA_API_KEY; do
    [[ -z "${!v:-}" ]] && count=$((count + 1))
  done
  echo "$count"
}

find_repo() {
  local name="$1"
  local candidates=(
    "${QWEN_PROJECTS_DIR:-$HOME/projects}/$name"
    "$HOME/$name"
    "$HOME/opsora/$name"
    "/agent/repos/$name"
  )
  for p in "${candidates[@]}"; do
    [[ -d "$p/.git" ]] && echo "$p" && return 0
  done
  return 1
}

cmd_repos() {
  echo -e "${BOLD}=== Opsora Repositories ===${NC}"
  local repos=(opsora opsora-landing opsora-dashboard opsora-cli opsora-agent memori-agent-dashboard)
  for r in "${repos[@]}"; do
    local path
    if path=$(find_repo "$r" 2>/dev/null); then
      local branch commits
      branch=$(git -C "$path" branch --show-current 2>/dev/null || echo "?")
      commits=$(git -C "$path" log --since="2 days ago" --oneline 2>/dev/null | wc -l | tr -d ' ')
      printf "  ✅ %-28s %-20s branch=%-25s commits(2d)=%s\n" "$r" "$path" "$branch" "$commits"
    else
      printf "  ❌ %-28s NOT CLONED → git clone https://github.com/Cladius-Weinert/%s.git\n" "$r" "$r"
    fi
  done
  echo ""
  info "Clone semua: opsora-audit clone"
}

cmd_clone() {
  local base="${QWEN_PROJECTS_DIR:-$HOME/projects}"
  mkdir -p "$base"
  local repos=(opsora opsora-landing opsora-dashboard opsora-cli opsora-agent memori-agent-dashboard)
  for r in "${repos[@]}"; do
    local dest="$base/$r"
    if [[ -d "$dest/.git" ]]; then
      ok "$r sudah ada di $dest"
    else
      info "Cloning $r..."
      git clone --depth 1 "https://github.com/Cladius-Weinert/${r}.git" "$dest" || warn "Gagal clone $r"
    fi
  done
}

cmd_context() {
  echo -e "${BOLD}=== Opsora Context Paths (untuk Qwen Code) ===${NC}"
  cat <<CTX

  Memory file     : ${MEMORY_FILE}
  Context export  : ${EXPORT_FILE}
  Qwen settings   : ${HOME}/.qwen/settings.json
  Qwen agents     : ${HOME}/.qwen/agents/
  Secrets env     : ${SECRETS_FILE}
  Projects dir    : ${QWEN_PROJECTS_DIR:-$HOME/projects}

  Dokumen otak:
    - CODEX_OPSORA_BRAIN.md  (di repo opsora)
    - AGENTS.md              (di repo opsora-landing)
    - docs/SECRETS.md        (di repo opsora)

  Perintah cepat:
    opsora-audit all          # audit lengkap
    opsora-audit export       # bundle konteks untuk Qwen
    opsora-qwen-sync          # test provider API
    opsora-qwen-test          # smoke test model
    opsora-qwen-model power   # switch model

  Skill Qwen: baca ~/.qwen/agents/opsora-audit.md
CTX
  if [[ -f "$MEMORY_FILE" ]]; then
  echo ""
  ok "Memory file tersedia ($(wc -l < "$MEMORY_FILE" | tr -d ' ') baris)"
  else
  warn "Memory file belum ada — pull opsora-cli terbaru"
  fi
}

cmd_health() {
  load_secrets
  echo -e "${BOLD}=== API Health Check ===${NC}"

  if [[ -n "${NVIDIA_API_KEY:-}" ]]; then
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}" \
      "https://integrate.api.nvidia.com/v1/models" \
      -H "Authorization: Bearer $NVIDIA_API_KEY" --max-time 15)
    [[ "$code" == "200" ]] && ok "NVIDIA Integrate — HTTP $code" || warn "NVIDIA Integrate — HTTP $code"
  else
    warn "NVIDIA — skip (key missing)"
  fi

  if [[ -n "${DASHSCOPE_API_KEY:-}" ]]; then
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}" \
      "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models" \
      -H "Authorization: Bearer $DASHSCOPE_API_KEY" --max-time 15)
    [[ "$code" == "200" ]] && ok "DashScope intl — HTTP $code" || warn "DashScope intl — HTTP $code"
  else
    warn "DashScope — skip (key missing)"
  fi

  local urls=(
    "Landing|https://opsora-landing-zeta.vercel.app"
    "Agent IDE|https://useopsora.com"
  )
  for entry in "${urls[@]}"; do
    local name="${entry%%|*}" url="${entry##*|}"
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}" -L "$url" --max-time 15)
    [[ "$code" =~ ^[23] ]] && ok "$name — HTTP $code" || warn "$name — HTTP $code"
  done
}

cmd_export() {
  load_secrets
  mkdir -p "$INSTALL_DIR"
  local mem_path="$MEMORY_FILE"
  [[ -f "$mem_path" ]] || mem_path="(belum di-clone — pull opsora-cli)"

  cat >"$EXPORT_FILE" <<EOF
# Opsora Context Bundle
> Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ") by opsora-audit v${VERSION}
> Untuk di-load Qwen Code di awal sesi. TIDAK berisi nilai secret.

## Status Secret (masked)

| Variable | Status |
|----------|--------|
| DASHSCOPE_API_KEY | $(mask_value "${DASHSCOPE_API_KEY:-}") |
| NVIDIA_API_KEY | $(mask_value "${NVIDIA_API_KEY:-}") |
| OPSORA_LEAD_API_TOKEN | $(mask_value "${OPSORA_LEAD_API_TOKEN:-}") |
| BAILIAN_CODING_PLAN_API_KEY | $(mask_value "${BAILIAN_CODING_PLAN_API_KEY:-}") |

## Repos

EOF

  local repos=(opsora opsora-landing opsora-dashboard opsora-cli memori-agent-dashboard)
  for r in "${repos[@]}"; do
    local path
    if path=$(find_repo "$r" 2>/dev/null); then
      echo "- **$r**: \`$path\` (branch: $(git -C "$path" branch --show-current 2>/dev/null))" >>"$EXPORT_FILE"
    else
      echo "- **$r**: NOT CLONED" >>"$EXPORT_FILE"
    fi
  done

  cat >>"$EXPORT_FILE" <<EOF

## Aturan Keras

1. Jangan auto-send WhatsApp/email — human approval wajib
2. Jangan expose/commit secret — server-side only
3. Jangan rusak POST /api/lead di landing
4. Default model Qwen: profile \`power\` (qwen3-coder-plus)

## Memory Lengkap

Lokasi: \`${mem_path}\`

\`\`\`
# Load di Qwen: @${EXPORT_FILE}
# atau: cat ${EXPORT_FILE}
\`\`\`

## Perintah Skill

\`\`\`bash
opsora-audit all       # audit penuh
opsora-qwen-sync       # sync provider
opsora-qwen-model power && opsora-qwen
\`\`\`
EOF

  chmod 600 "$EXPORT_FILE"
  ok "Context bundle → $EXPORT_FILE"
  echo "  Load di Qwen Code: @$EXPORT_FILE"
}

cmd_reveal() {
  if [[ "${1:-}" != "--yes-i-understand" ]]; then
    err "PERINGATAN: perintah ini menulis NILAI PENUH secret ke file lokal."
    err "File: $SNAPSHOT_FILE (chmod 600, jangan commit/share)"
    err ""
    err "Jalankan: opsora-audit reveal --yes-i-understand"
    return 1
  fi

  load_secrets
  mkdir -p "$PRIVATE_DIR"
  chmod 700 "$PRIVATE_DIR"

  {
    echo "# Opsora Credentials Snapshot"
    echo "# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "# JANGAN commit, JANGAN share, JANGAN paste ke chat AI"
    echo "# Hapus setelah dipakai: rm $SNAPSHOT_FILE"
    echo ""
    local vars=(
      DASHSCOPE_API_KEY NVIDIA_API_KEY BAILIAN_CODING_PLAN_API_KEY
      OPSORA_LEAD_API_TOKEN OPSORA_WEBHOOK_URL OPSORA_ADMIN_PASSWORD OPSORA_PAY_SECRET
      NEXT_PUBLIC_SUPABASE_URL NEXT_PUBLIC_SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY
      SUPABASE_URL SUPABASE_ANON_KEY JWT_SECRET CRON_SECRET
      RESEND_API_KEY WATI_API_TOKEN WATI_API_URL
      MIDTRANS_SERVER_KEY MIDTRANS_CLIENT_KEY
      AI_API_KEY LLM_API_KEY LLM_BASE_URL LLM_MODEL
      VULTR_API_KEY AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY TF_API_TOKEN VAULT_ADDR VERCEL_TOKEN
    )
    for v in "${vars[@]}"; do
      local val="${!v:-}"
      if [[ -n "$val" ]]; then
        echo "export ${v}='${val//\'/\'\\\'\'}'"
      else
        echo "# export ${v}=  # MISSING"
      fi
    done
  } >"$SNAPSHOT_FILE"

  chmod 600 "$SNAPSHOT_FILE"
  ok "Snapshot ditulis ke: $SNAPSHOT_FILE"
  echo "  Baca lokal:  cat $SNAPSHOT_FILE"
  echo "  Hapus:       rm $SNAPSHOT_FILE"
  echo "  JANGAN paste isi file ke chat AI atau commit ke git."
}

cmd_all() {
  cmd_secrets
  echo ""
  cmd_repos
  echo ""
  cmd_health
  echo ""
  cmd_export
  echo ""
  cmd_context
}

cmd_help() {
  cat <<HELP
Opsora Audit v${VERSION} — skill helper untuk Qwen Code

Usage:
  opsora-audit <command>

Commands:
  secrets   Cek status secret (masked, aman untuk terminal)
  repos     Status 6 repo Opsora (clone/branch/commits)
  clone     Clone semua repo ke \$QWEN_PROJECTS_DIR
  context   Tampilkan path konteks & perintah cepat
  health    Health check API (NVIDIA, DashScope, produksi)
  export    Buat context-bundle.md untuk load di Qwen Code
  reveal    Tulis nilai penuh ke ~/.opsora/private/ (LOKAL SAJA)
  all       Jalankan secrets + repos + health + export + context
  help      Tampilkan bantuan ini

Contoh workflow Qwen Code:
  opsora-audit all
  opsora-audit export && opsora-qwen
  # Di Qwen: @$EXPORT_FILE

Skill agent: ~/.qwen/agents/opsora-audit.md
HELP
}

main() {
  local cmd="${1:-all}"
  shift || true
  case "$cmd" in
    secrets)  cmd_secrets ;;
    repos)    cmd_repos ;;
    clone)    cmd_clone ;;
    context)  cmd_context ;;
    health)   cmd_health ;;
    export)   cmd_export ;;
    reveal)   cmd_reveal "$@" ;;
    all)      cmd_all ;;
    help|-h|--help) cmd_help ;;
    *) err "Unknown command: $cmd"; cmd_help; exit 1 ;;
  esac
}

main "$@"
