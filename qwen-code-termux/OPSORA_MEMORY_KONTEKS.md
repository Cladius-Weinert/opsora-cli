# OPSORA — Memory & Konteks Lengkap untuk Qwen Code

> **Dibuat:** 2026-07-28  
> **Audit:** Multi-agent (GitHub activity + Cursor/MCP + Architecture)  
> **Periode kerja:** 26–28 Juli 2026 (2 hari terakhir)  
> **Tujuan:** Memberi Qwen Code konteks luas agar bisa menyesuaikan diri dengan seluruh ekosistem Opsora tanpa mengulang onboarding.

**PENTING KEAMANAN:** File ini hanya berisi **nama** variabel/env dan **path** konfigurasi. **JANGAN** commit API key, token, atau password asli. Ambil nilai secret dari `~/.opsora/qwen-code/secrets.env`, `secrets/` (gitignored), atau Cursor Cloud Agent injected secrets.

---

## 1. Identitas Produk & Aturan Keras

### Apa itu Opsora?

Opsora adalah **AI B2B SaaS / productized automation** untuk SMB lokal (klinik gigi, villa/hotel, salon, rental, travel) — dimulai di **Denpasar/Bali**, Indonesia.

**MVP:** AI receptionist + lead capture + CRM follow-up + booking automation + dashboard + human handoff.

**Positioning:** Membantu bisnis merespons lead lebih cepat, menangkap data otomatis, follow-up konsisten, mengurangi kehilangan pelanggan karena respon lambat.

### Aturan keras (WAJIB di semua repo)

| Aturan | Detail |
|--------|--------|
| **Tidak auto-send** | Jangan kirim WhatsApp/email outbound tanpa persetujuan admin manusia |
| **Secret server-side** | `OPSORA_LEAD_API_TOKEN` dan semua API key hanya di server/env — jangan expose ke client |
| **Jangan commit secret** | `.env`, `.env.local`, `secrets/*`, `*.pem`, `*.key` — gitignored |
| **Jangan rusak `/api/lead`** | Endpoint intake lead di landing adalah jalur produksi kritis |
| **Human review** | Outreach, rotasi secret produksi, 2FA/CAPTCHA, aksi destruktif infra |
| **Bahasa AI** | Draft reply dalam Bahasa Indonesia; tidak klaim medis, tidak harga pasti, tidak konfirmasi booking final |

### Dokumen otak utama (baca pertama)

| File | Path | Isi |
|------|------|-----|
| **CODEX_OPSORA_BRAIN** | `/agent/repos/opsora/CODEX_OPSORA_BRAIN.md` | Charter operator, MVP, infra, strategi bisnis, tool-selection |
| **AGENTS.md** | `/agent/repos/opsora-landing/AGENTS.md` | Aturan repo landing, flow lead, validasi |
| **SECRETS.md** | `/agent/repos/opsora/docs/SECRETS.md` | Registry secret terpadu, lookup order |
| **INDEX.md** | `/agent/repos/opsora/docs/INDEX.md` | Peta operator: script/doc + label safety |
| **File ini** | `opsora-cli/qwen-code-termux/OPSORA_MEMORY_KONTEKS.md` | Konteks gabungan 2 hari kerja |

---

## 2. Enam Repositori & Perannya

GitHub org: **`Cladius-Weinert`**

| Repo | Path lokal | Branch default | Peran |
|------|-----------|----------------|-------|
| **opsora** | `/agent/repos/opsora` | `main` | Monorepo otak + `operatoros` (self-hosted CRM), infra, orchestrator, docs, Android app |
| **opsora-landing** | `/agent/repos/opsora-landing` | `main` | Landing page publik + `POST /api/lead` (Vercel) |
| **opsora-dashboard** | `/agent/repos/opsora-dashboard` | `main` | CRM SaaS produksi (Next.js 16 + Supabase + Qwen + WATI) |
| **opsora-cli** | `/agent/repos/opsora-cli` | `main` | CLI multi-provider + setup Qwen/Claude/Codex Termux |
| **opsora-agent** | `/agent/repos/opsora-agent` | `main` | Spec OperatorOS V5 (reconciliation doc, belum ada kode) |
| **memori-agent-dashboard** | `/agent/repos/memori-agent-dashboard` | `master` | Agent IDE + backend (FastAPI + LangGraph), deploy `useopsora.com` |

### Path produksi (VPS asli vs workspace agent)

Di VPS Ubuntu (`aop-vps`, AWS EC2): `/home/ubuntu/opsora/`  
Di workspace Cursor Cloud Agent: `/agent/repos/`

Keduanya valid — sesuaikan path saat menjalankan script.

---

## 3. Arsitektur & Alur Data

### Lead pipeline (customer-facing)

```
[opsora-landing]  Vercel — https://opsora-landing-zeta.vercel.app
   POST /api/lead  (server-side, token OPSORA_LEAD_API_TOKEN)
        │  HTTP + header X-Opsora-Token
        ▼
Secure webhook / gateway (n8n / dashboard webhook)
        │
        ├── Path self-hosted → n8n → Ollama → operatoros API (opsora repo)
        └── Path cloud       → POST /api/webhook → opsora-dashboard → Supabase
        │
        ▼
[opsora-dashboard]  Admin review lead + AI draft (Qwen)
   Admin approve → WATI (WhatsApp) / Resend (email)   ← TIDAK PERNAH auto-send
   Vercel cron /api/cron/daily → Supabase Edge functions
```

### Dua implementasi CRM (domain sama, stack beda)

| | **opsora/operatoros** | **opsora-dashboard** |
|---|---|---|
| Stack | Fastify 5 + SQLite + Next.js | Next.js 16 + Supabase Postgres |
| Deploy | Docker Compose di VPS | Vercel |
| Auth | scrypt session + API keys | Supabase Auth + RLS |
| Payment | Midtrans (IDR) | Midtrans + Stripe (via MCP) |
| AI | Ollama → Bedrock → template | Qwen max/turbo (DashScope) |

### Agent / operations plane

```
Operator (Qwen Code / Cursor / opsora-cli)
        │
        ▼
memori-agent-dashboard  (FastAPI + LangGraph + SSH pool + IDE)
        │  manages AWS/GCP/DO/Vultr instances
        ▼
opsora/infra/orchestrator/  (model routing, subagent pool, capability matrix)
        │
        ▼
VPS fleet (aop-vps) — n8n, Ollama, gateway, operatoros
```

### Shared Supabase

- **Project:** `opsora-prod` / ref `mwbgkkthwwlcndccnbnf` (Singapore)
- **opsora-dashboard:** tabel CRM publik (`leads`, `conversations`, `ai_drafts`, `businesses`)
- **memori-agent-dashboard:** schema `agent` (users, instances, agent_jobs, audit_log, dll.)

---

## 4. Aktivitas GitHub 2 Hari Terakhir (26–28 Jul 2026)

### Ringkasan velocity

| Repo | Commits | Status |
|------|--------:|--------|
| opsora | ~85 | Sangat aktif — Android app, control plane, NVIDIA, MCP |
| memori-agent-dashboard | ~30 | Agent IDE, Supabase, production deploy |
| opsora-cli | 20 | Qwen/Claude/Codex Termux, NVIDIA gateway |
| opsora-landing | 2 | Secret-guard hook, build fix |
| opsora-agent | 2 | Docs reconciliation |
| opsora-dashboard | 0 | Idle (sudah stabil v1.3.2) |

### Pekerjaan utama per repo

#### opsora (~85 commits)
- **Android app** `apps/opsora-android/` — v1.3.0 → **v1.8.0**, pipeline Chat-Plan-Execute, MCP catalog, sub-agents, login 90 hari
- **OperatorOS control plane** `operatoros/` — unified control plane, RLS/audit schema
- **NVIDIA NIM/NVCF** — NVCF client, key separation, NGC CLI, NIM sebagai default LLM
- **WhatsApp Desk** — manual handoff approve-and-send
- **Landing refresh** — konten Indonesia-wide
- **MCP/Cursor stack** — `.cursor/mcp.json`, skills (alibaba, elastic, nvidia, qwen-dashscope, dll.)
- **Elastic Cloud** — serverless `opsora-search`, observability

#### memori-agent-dashboard (~30 commits)
- **Opsora Agent IDE** (PR #2 merged) — Cursor-style layout, git, diff viewer
- **Supabase** (PR #4 merged) — REST ke `opsora-prod`, schema `agent`
- **Production deploy** (PR #3 merged) — Docker, VPS workflow, `useopsora.com`
- **NVIDIA orchestrator** — multi-agent, model routing, tool loop SSE
- **Mobile bootstrap + JWT** — auth 90 hari
- **Elastic APM** observability

#### opsora-cli (20 commits)
- **Qwen Code Termux** — full-power setup, `models.json`, `settings.json`, sub-agents
- **Claude Code Termux** (PR #1 merged) — NVIDIA + multi-provider
- **Codex Termux** — LiteLLM gateway, NVIDIA/OpenRouter
- **NVIDIA cloud stack** — Render gateway tanpa AWS fleet

#### opsora-landing (2 commits)
- Secret-guard Cursor hook (`.cursor/hooks/detect-secrets.sh`)
- Build-blocking JSX fix

### Pull Request penting (belum semua merged)

| PR | Repo | Status | Topik |
|----|------|--------|-------|
| #13 | opsora | DRAFT | Android app v1.8.0 |
| #11, #15 | opsora | DRAFT | NVIDIA NIM/NVCF backend |
| #9 | opsora | **OPEN** | docs/free-tier-stack |
| #5 | memori-agent-dashboard | DRAFT | IDE API URL Docker fix |
| #2 | opsora-landing | DRAFT | Secret-guard hook |
| #1 | opsora-cli | MERGED | Claude Code Termux NVIDIA |

### Branch aktif (prefix `cursor/`)

Contoh: `cursor/opsora-android-app`, `cursor/nvidia-infra-setup`, `cursor/unified-operatoros-foundation`, `cursor/qwen-code-termux-setup`

---

## 5. Infrastruktur & URL Produksi

| Komponen | URL / Host | Catatan |
|----------|-----------|---------|
| Landing | https://opsora-landing-zeta.vercel.app | Vercel |
| Agent IDE | https://useopsora.com | memori-agent-dashboard |
| VPS utama | AWS EC2 `aop-vps` (ip-172-31-30-102) | SSH alias dari Termux |
| Ollama | `127.0.0.1:11434` | Model default `qwen2.5:3b` |
| n8n | Docker `opsora-n8n` | Workflow lead |
| Public gateway | `127.0.0.1:8790` | Bridge webhook |
| CRM logger | `127.0.0.1:3010` | NDJSON logger |
| operatoros API | `0.0.0.0:8789` | Fastify self-hosted |
| LiteLLM parliament | `207.148.74.150:4001` | Proxy LLM OperatorOS V5 |
| Orchestrator | port `8787` | Task router |
| Render API | `memori-agent-api.onrender.com` | Agent backend |

**Keterbatasan saat ini:** Quick Tunnel Cloudflare sementara — belum custom domain permanen untuk webhook.

---

## 6. Credential & Environment Variables

> **Hanya nama variabel.** Nilai ada di: `~/.opsora/qwen-code/secrets.env`, `secrets/<slug>`, `infra/.env`, Cursor Cloud Agent secrets, Vercel/Render env dashboard.

### 6.1 AI Providers (Qwen / NVIDIA / DashScope)

| Variabel | Layanan | Dipakai di |
|----------|---------|-----------|
| `DASHSCOPE_API_KEY` | Alibaba DashScope intl — Qwen3 coder/reasoning | qwen-code-termux, opsora-dashboard AI |
| `NVIDIA_API_KEY` | NVIDIA Integrate — DeepSeek/Nemotron/Llama + embedding | qwen-code-termux, memori-agent, opsora-cli |
| `BAILIAN_CODING_PLAN_API_KEY` | Alibaba Coding Plan (key terpisah) | qwen-code-termux profile `coding-plan` |
| `AI_API_KEY` / `QWEN_API_KEY` | Dashboard AI (alias DashScope) | opsora-dashboard |
| `AI_BASE_URL`, `AI_MODEL`, `AI_FALLBACK_MODEL` | Qwen max/turbo routing | opsora-dashboard `src/lib/ai.ts` |
| `AI_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Local Ollama routing | opsora/operatoros |
| `BEDROCK_OPENAI_BASE_URL`, `BEDROCK_OPENAI_API_KEY`, `BEDROCK_MODEL` | AWS Bedrock (opsional) | opsora infra |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` | Agent API default NVIDIA Llama 3.1 70B | memori-agent-dashboard |
| `OPSORA_QWEN_DEFAULT_PROFILE`, `OPSORA_QWEN_FAST_PROFILE` | Profile selector Qwen | qwen-code-termux |
| `QWEN_CODE_UNATTENDED_RETRY`, `QWEN_CODE_API_TIMEOUT_MS`, `QWEN_CODE_MAX_OUTPUT_TOKENS` | Headless tuning | qwen-code-termux |
| `QWEN_PROJECTS_DIR` | Direktori kerja (hindari /sdcard) | qwen-code-termux |
| `OPSORA_PROVIDER_ORDER`, `OPSORA_ALLOW_LOCAL_FALLBACK`, `OPSORA_OLLAMA_URL` | Multi-provider CLI routing | opsora-cli |

### 6.2 Lead Flow & Auth

| Variabel | Fungsi | Repo |
|----------|--------|------|
| `OPSORA_LEAD_API_TOKEN` | Token webhook lead (server-side only) | landing, dashboard |
| `OPSORA_WEBHOOK_URL` | URL webhook upstream dari landing | opsora-landing |
| `OPSORA_ADMIN_PASSWORD` | Login admin operatoros | opsora/infra |
| `OPSORA_PAY_SECRET` | Token signed URL billing | opsora/operatoros |
| `OPSORA_PUBLIC_API_URL`, `OPSORA_PUBLIC_WEB_URL`, `OPSORA_HTTP_PORT` | URL publik self-hosted | opsora/infra |
| `CRON_SECRET` | Auth Vercel cron routes | opsora-dashboard |
| `ADMIN_EMAIL` / `ADMIN_NOTIFY_EMAIL` | Notifikasi admin | opsora-dashboard |
| `JWT_SECRET`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT agent API | memori-agent-dashboard |
| `DATABASE_URL`, `DB_SCHEMA`, `REDIS_URL` | DB agent backend | memori-agent-dashboard |

### 6.3 Supabase

| Variabel | Fungsi |
|----------|--------|
| `NEXT_PUBLIC_SUPABASE_URL` | URL publik Supabase |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Anon key (client) |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role (server only) |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_PROJECT_REF` | Agent backend REST |
| `SUPABASE_DB_PASSWORD` | Opsional direct Postgres |

### 6.4 Messaging & Payment

| Variabel | Fungsi |
|----------|--------|
| `RESEND_API_KEY`, `RESEND_FROM` | Email via Resend |
| `WATI_API_URL`, `WATI_API_TOKEN` | WhatsApp via WATI |
| `MIDTRANS_SERVER_KEY`, `MIDTRANS_CLIENT_KEY`, `MIDTRANS_IS_PRODUCTION`, `MIDTRANS_NOTIFICATION_URL` | Pembayaran IDR |

### 6.5 Infra / Cloud / IaC

| Variabel | Fungsi |
|----------|--------|
| `VULTR_API_KEY`, `VULTR_REGION`, `VULTR_PLAN` | Vultr VPS |
| `HCP_CLIENT_ID`, `HCP_CLIENT_SECRET` | HashiCorp Cloud |
| `TF_API_TOKEN`, `TFC_TOKEN`, `TFE_ADDRESS` | Terraform Cloud |
| `VAULT_ADDR`, `HCP_VAULT_TOKEN` | Vault secrets |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | AWS (MCP + infra) |
| `ALIBABA_CLOUD_ACCESS_KEY_ID`, `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | Alibaba Cloud MCP |
| `TENCENTCLOUD_SECRET_ID`, `TENCENTCLOUD_SECRET_KEY`, `TENCENTCLOUD_REGION` | Tencent MCP |
| `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT` | GCP MCP |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` | Gmail MCP |
| `BROWSERLESS_WS` | Browser automation |

### 6.6 CI / Deploy Tokens

| Variabel | Platform |
|----------|----------|
| `OPSORA_TOKEN`, `VERCEL_TOKEN` | CircleCI → Vercel deploy |
| `NEXT_PUBLIC_API_URL` | Build-time API URL (memori web) |

### Prioritas lookup secret (opsora monorepo)

```
1. process.env (Cursor Cloud Agent injected)
2. secrets/<file_slug>  (gitignored)
3. infra/.env
4. .opsora/vault-cache.json
```

Helper: `scripts/lib/opsora-secrets.mjs`  
Diagnosa: `bash scripts/opsora-flow secrets check`

---

## 7. Qwen Code — Setup & Konfigurasi

### Fork wajib (Termux)

Paket resmi `@qwen-code/qwen-code` **gagal di Termux**.  
Wajib: **`@mmmbuto/qwen-code-termux`**

### File konfigurasi (sumber kebenaran)

| File | Path repo | Path runtime |
|------|-----------|--------------|
| settings.json | `qwen-code-termux/settings.json` | `~/.qwen/settings.json` |
| models.json | `qwen-code-termux/models.json` | `~/.opsora/qwen-code/models.json` |
| rpm-config.json | `qwen-code-termux/rpm-config.json` | `~/.opsora/qwen-code/rpm-config.json` |
| embedding-config.json | `qwen-code-termux/embedding-config.json` | `~/.opsora/qwen-code/embedding-config.json` |
| secrets.env | `qwen-code-termux/secrets.env.example` | `~/.opsora/qwen-code/secrets.env` |
| Sub-agents | `qwen-code-termux/agents/*.md` | `~/.qwen/agents/` |

### Model profiles (terverifikasi 2026-07-28)

| Profile | Model | Provider | Context | Use case |
|---------|-------|----------|---------|----------|
| `power` | qwen3-coder-plus | DashScope intl | 1M | **Default coding** |
| `reasoning` | qwen3.7-max | DashScope intl | 1M | Deep reasoning + thinking |
| `balanced` | qwen3.7-plus | DashScope intl | 1M | Balanced |
| `coder-next` | qwen3-coder-next | DashScope intl | 1M | Latest coder |
| `fast` | qwen3-coder-flash | DashScope intl | 1M | **Sub-agent / background** |
| `nvidia-coder` | deepseek-v4-flash | NVIDIA | 128K | Fast coding |
| `nvidia-reasoning` | nemotron-super-49b | NVIDIA | 128K | Reasoning |
| `nvidia-power` | nemotron-3-super-120b | NVIDIA | 128K | Flagship MoE |
| `nvidia-fast` | llama-3.1-8b-instruct | NVIDIA | 128K | RPM overflow |
| `coding-plan` | qwen3-coder-plus | Coding Plan | 1M | Key terpisah |

**Recommended routing:**
- Default: `power`
- Background/sub-agent: `fast`
- Fallback chain: `fast` → `nvidia-fast` → `balanced`

**Settings penting:**
- `reasoningEffort: high`
- `maxSubagentDepth: 3`
- `autoCompactThreshold: 0.85`
- `enableCacheSharing: true`
- Embedding default: `nvidia/nv-embedqa-e5-v5` (1024 dim)

### Sub-agents Qwen (definisi di repo)

| Agent | File | Model | Fungsi |
|-------|------|-------|--------|
| explore-fast | `agents/explore-fast.md` | fast | Eksplorasi codebase cepat |
| reasoning-deep | `agents/reasoning-deep.md` | reasoning | Analisis arsitektur mendalam |
| nvidia-coder | `agents/nvidia-coder.md` | nvidia-coder | Coding via NVIDIA |

### Perintah shell (setelah install)

```bash
opsora-qwen-sync          # sync config dari repo
opsora-qwen-test          # test semua model profiles
opsora-qwen-model power   # switch ke profile power
opsora-qwen               # jalankan Qwen Code CLI
qw                        # alias singkat
```

### RPM / concurrency tiers

| Tier | Parallel | Use case |
|------|----------|----------|
| fast | 8 | Sub-agent, background |
| balanced | 4 | Default work |
| deep | 2 | Reasoning, arsitektur |

Fallback: 503 → fast model; 429 → exponential backoff.

---

## 8. Cursor — MCP Servers, Skills, Plugins

### MCP servers terdaftar di workspace Cursor Cloud Agent

```
alibaba, Aurora-dsql, Awsiac, Aws-mcp, Awspricing, Aws-serverless-mcp,
Azure, Firebase, Mongodb, Phantom-mcp, Railway
```

Plus (dari metadata project): Render, Cloudflare-bindings, Cloudflare-observability, Linear, Notion, Figma, Supabase, Stripe, Higgsfield, Vercel, Port, Awsknowledge, Harness, Context7, Asana, Composio, Resend, Datadog, Elastic-docs, Grafana-cloud, Sourcegraph, Huggingface-skills, cursor-cloud, TENCENT, nvidia-search, Phantom-connect-sdk

### Status MCP menurut opsora orchestrator config

| Server | Status | Fungsi |
|--------|--------|--------|
| Render | ready | Deploy web/worker, Postgres, cron |
| Cloudflare-bindings/observability | ready | Workers, D1, KV, R2, tunnel |
| Linear | ready | Issue tracking |
| Notion | ready | CRM sync, docs |
| Figma | ready | Design-to-code |
| Firebase | ready | Firestore, auth, hosting |
| Higgsfield | ready | Generate media marketing |
| Phantom-mcp | ready | Crypto wallet ops |
| Supabase | needsAuth | Postgres, auth, storage |
| Stripe | needsAuth | Payments |
| Vercel | error | Deploy Next.js (perlu re-auth) |
| Port | error | Service catalog |
| AWS | error | EC2, Bedrock, S3 |

> Verifikasi status live sebelum pakai — status di atas dari audit JSON internal.

### MCP di opsora repo (`.cursor/mcp.json`)

Server: Alibaba, AWS, Confluent, Elastic, gcloud, GitHub, Gmail, Notion, Render, Stripe, Supabase, Tencent, Vertex, Terraform, Linear, Vercel

Env vars MCP (nama saja): lihat §6.5

### Cursor skills relevan (marketplace global)

Tidak ada skill Opsora-authored di repo. Skills tersedia via plugin cache:

| Area | Skill paths (di `~/.cursor/plugins/cache/cursor-public/`) |
|------|----------------------------------------------------------|
| Next.js/Vercel | `649/.../skills/nextjs/`, `vercel-cli`, `deployments-cicd`, `shadcn` |
| Render | `1295/.../skills/render-*` (20+ skills) |
| Supabase | `652/.../skills/supabase/`, `supabase-postgres-best-practices` |
| Stripe | `408/.../skills/stripe-*` |
| Git/PR | `677/.../skills/new-branch-and-pr/`, `fix-ci`, `loop-on-ci` |
| HuggingFace/NVIDIA | `735/.../skills/huggingface-*` |
| Qwen/DashScope | `opsora/.cursor/skills/qwen-dashscope/SKILL.md` (repo-specific) |

### Orchestrator config (opsora monorepo)

Path: `/agent/repos/opsora/infra/orchestrator/config/`

| File | Fungsi |
|------|--------|
| `model-routing.json` | Task type → model tier (fast/balanced/deep/gui) + subagent types |
| `capability-matrix.json` | Intent → console → model → runtime + humanRequired gates |
| `console-registry.json` | Registry semua console/API + auth env var + MCP mapping |
| `subagent-pool.json` | Worker pool (orchestrator :8787, workers :8788, RDP :3389) |
| `aop-vps-fleet.json` | VPS fleet definition |

### Cursor agents (opsora repo)

- `.cursor/agents/final-director.md`
- `.cursor/agents/whatsapp-desk.md`

### Cursor hooks

- **Cloud Agent** (auto): secret scanner di pre-commit — blok commit jika secret terdeteksi
- **opsora-landing**: `.cursor/hooks/detect-secrets.sh` — blok API key di prompt/shell

---

## 9. Setup CLI Sibling (Claude & Codex)

### Claude Code Termux
Path: `opsora-cli/claude-code-termux/`  
LiteLLM gateway :4000, NVIDIA cloud catalog, `settings.json`, `models.json`

### Codex Termux
Path: `opsora-cli/codex-termux-nvidia-setup/`  
LiteLLM/OpenRouter, `litellm_config.yaml`, `dot-codex/config.toml`

Env vars: `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `LITELLM_API_KEY`, `LITELLM_BASE_URL`, `LITELLM_MASTER_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `TOGETHER_API_KEY`

---

## 10. OperatorOS V5 (Target Arsitektur)

Dokumen: `/agent/repos/opsora-agent/docs/operatoros-v5-cli-agent-reconciliation.md`

Keputusan kunci:
- **Satu brain:** `agent-v4.js` (port 9000) — satu substrate reasoning/execution
- **CLI = thin frontend** (Ink, Node 22 ESM) — bukan brain kedua
- **LLM routing:** semua via LiteLLM parliament proxy `:4001`
- **Data:** Postgres (schemas: nodes, memory, workflows, audit) + Redis session
- **Workflow:** DAG runs/steps dengan retry/replay
- **Tool router:** bash_exec, ssh_exec, docker_exec, pm2_exec, secret_get/put, workflow_trigger
- **Approval policy:** setiap mutating tool call wajib audit + human gate

---

## 11. Validasi & Workflow Development

### Sebelum commit (semua repo)

```bash
npm run build                    # Next.js repos
git diff --check                 # whitespace errors
bash -n scripts/*.sh             # shell syntax
npm run check:secrets            # opsora-landing
bash scripts/opsora-flow secrets check  # opsora monorepo
```

### Branch naming (Cursor Cloud Agent)

```
cursor/<descriptive-name>-31b1
```

### Deploy

| App | Platform | Script |
|-----|----------|--------|
| Landing | Vercel | `opsora-landing/scripts/deploy-vercel-safe.sh` |
| Dashboard | Vercel | CircleCI pipeline |
| Agent IDE | Render/VPS | `memori-agent-dashboard/deploy/deploy-production.sh` |
| operatoros | Docker VPS | `opsora/infra/docker-compose.yml` |

---

## 12. Keamanan — Temuan Audit

| Temuan | Status | Rekomendasi |
|--------|--------|-------------|
| `memori-agent-dashboard/deploy/.env` pernah di git history | Dihapus + gitignored | Rotasi credential jika pernah berisi nilai asli; pertimbangkan history scrub |
| Secret-guard hook di landing | ✅ Ditambahkan | Pertahankan |
| MCP secrets dipindah ke gitignored local stores | ✅ Done di opsora | Jangan commit `.cursor/mcp.json` dengan nilai asli |
| Human approval untuk outbound | ✅ Enforced di product + agent safety | Jangan bypass |

---

## 13. Checklist Onboarding Qwen Code (Quick Start)

1. **Baca** `CODEX_OPSORA_BRAIN.md` → file ini → `AGENTS.md` (landing)
2. **Install** fork `@mmmbuto/qwen-code-termux` via `install-termux.sh`
3. **Copy config:**
   ```bash
   cp settings.json ~/.qwen/settings.json
   mkdir -p ~/.opsora/qwen-code
   cp models.json rpm-config.json embedding-config.json ~/.opsora/qwen-code/
   cp secrets.env.example ~/.opsora/qwen-code/secrets.env
   # isi DASHSCOPE_API_KEY dan NVIDIA_API_KEY
   ```
4. **Sync sub-agents:** `cp agents/*.md ~/.qwen/agents/`
5. **Test:** `opsora-qwen-test`
6. **Jalankan:** `opsora-qwen-model power && opsora-qwen`
7. **Clone repos** ke `~/projects/` atau `$QWEN_PROJECTS_DIR`
8. **Jangan** print/commit secret; gunakan `opsora-flow secrets check`

---

## 14. Glosarium

| Istilah | Arti |
|---------|------|
| HP | Android phone / Termux / Chrome (remote control only) |
| Termius | Mobile SSH client untuk VPS |
| aop-vps | SSH alias ke AWS EC2 Ubuntu VPS utama |
| OperatorOS | Platform agent/infra management (evolusi ke V5) |
| Parliament proxy | LiteLLM multi-model router di :4001 |
| WATI | WhatsApp Business API provider |
| DashScope intl | Alibaba Cloud AI API (region internasional) |
| NVCF | NVIDIA Cloud Functions (hosted NIM models) |
| RLS | Row Level Security (Supabase) |

---

## 15. Changelog Memory File

| Tanggal | Perubahan |
|---------|-----------|
| 2026-07-28 | Initial audit multi-agent: GitHub 2 hari, Cursor/MCP, arsitektur 6 repo, Qwen config |

---

*File ini adalah living document. Update setelah sprint besar atau perubahan arsitektur signifikan.*
