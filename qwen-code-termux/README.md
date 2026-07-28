# Qwen Code CLI — Full Power Setup Termux (Android)

Paket ini menginstal **Qwen Code CLI** di HP Android (Termux) dengan konfigurasi **full power**:

- **Context besar** — hingga 1M token (DashScope Qwen3.x)
- **Reasoning** — `enable_thinking` pada Qwen3.7 Max/Plus dan model NVIDIA Nemotron
- **Caching** — `enableCacheControl` + `enableCacheSharing` untuk hemat token/RPM
- **Embedding** — NVIDIA `nv-embedqa-e5-v5` (1024 dim) untuk RAG/indexing
- **RPM balancing** — retry backoff, fallback chain, tier concurrency, sub-agent routing
- **Multi-provider** — DashScope intl + NVIDIA Integrate + Coding Plan (opsional)

> **Penting:** Paket resmi `@qwen-code/qwen-code` gagal di Termux. Wajib pakai fork: `@mmmbuto/qwen-code-termux`.

> **Konteks lengkap Opsora:** Baca [`OPSORA_MEMORY_KONTEKS.md`](./OPSORA_MEMORY_KONTEKS.md) — memory file audit 2 hari terakhir (repos, credentials, MCP, skills, arsitektur, GitHub activity).

## Model Profiles (terverifikasi 2026-07-28)

| Profile | Model | Provider | Context | Fitur |
|---------|-------|----------|---------|-------|
| `power` | `qwen3-coder-plus` | DashScope intl | **1M** | Default coding agent |
| `reasoning` | `qwen3.7-max` | DashScope intl | **1M** | Thinking + reasoning |
| `balanced` | `qwen3.7-plus` | DashScope intl | **1M** | Balanced + thinking |
| `coder-next` | `qwen3-coder-next` | DashScope intl | **1M** | Latest coder |
| `fast` | `qwen3-coder-flash` | DashScope intl | **1M** | Sub-agent / background |
| `nvidia-coder` | `deepseek-v4-flash` | NVIDIA | 128K | Fast coding + reasoning |
| `nvidia-reasoning` | `nemotron-super-49b-v1.5` | NVIDIA | 128K | Reasoning output |
| `nvidia-power` | `nemotron-3-super-120b` | NVIDIA | 128K | Flagship MoE |
| `nvidia-fast` | `llama-3.1-8b-instruct` | NVIDIA | 128K | RPM overflow |
| `coding-plan` | `qwen3-coder-plus` | Coding Plan | **1M** | Butuh key terpisah |

### Embedding

| Profile | Model | Dims | Provider |
|---------|-------|------|----------|
| `nvidia` (default) | `nvidia/nv-embedqa-e5-v5` | 1024 | NVIDIA Integrate |
| `dashscope` | `text-embedding-v3` | 1024 | DashScope intl |

## Install Cepat (Termux)

```bash
# 1) Clone repo
pkg install git -y
git clone https://github.com/Cladius-Weinert/opsora-cli.git ~/opsora-cli
cd ~/opsora-cli/qwen-code-termux

# 2) Install
bash install-termux.sh

# 3) Isi API keys
nano ~/.opsora/qwen-code/secrets.env
# export NVIDIA_API_KEY=nvapi-...
# export DASHSCOPE_API_KEY=sk-...

# 4) Sync & test
opsora-qwen-sync
opsora-qwen-test

# 5) Jalankan
opsora-qwen-model power
opsora-qwen
```

Atau one-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/Cladius-Weinert/opsora-cli/main/qwen-code-termux/install-termux.sh | bash
```

## Perintah Shell

| Command | Fungsi |
|---------|--------|
| `opsora-qwen` | Jalankan Qwen Code |
| `opsora-qwen-model power` | Ganti model profile |
| `opsora-qwen-sync` | Audit & sync providers |
| `opsora-qwen-test` | Smoke test semua model |
| `opsora-qwen-embed "text"` | Generate embedding |
| `qw` | Shortcut: cd projects + qwen |
| `qw-power` | Power model + start |
| `qw-fast` | Fast model + start |
| `qw-reason` | Reasoning model + start |
| `qw-nvidia` | NVIDIA coder + start |

## API Keys

| Key | Env Variable | Dapatkan di |
|-----|-------------|-------------|
| NVIDIA | `NVIDIA_API_KEY` | https://org.ngc.nvidia.com/setup/api-keys |
| DashScope intl | `DASHSCOPE_API_KEY` | https://bailian.console.alibabacloud.com/ |
| Coding Plan | `BAILIAN_CODING_PLAN_API_KEY` | Console → Coding Plan (key **terpisah**) |

## RPM Balancing

Qwen Code tidak punya client-side RPM cap. Strategi di `rpm-config.json`:

| Tier | maxParallel | Retries | Timeout | Untuk |
|------|-------------|---------|---------|-------|
| `fast` | 8 | 3 | 60s | Sub-agent, explore |
| `balanced` | 4 | 5 | 180s | Coding sehari-hari |
| `deep` | 2 | 5 | 300s | Reasoning, arsitektur |

**Provider limits (estimasi):**
- NVIDIA Integrate: ~40 RPM → fallback ke `fast` saat 503
- DashScope intl: ~60 RPM → gunakan `enableCacheControl`
- Coding Plan: ~30 RPM → weekly quota

**Fallback chain:** `qwen3-coder-flash` → `deepseek-v4-flash` → `llama-3.1-8b`

## Sub-Agent

Tiga sub-agent tersedia di `~/.qwen/agents/`:

| Agent | Model | Kegunaan |
|-------|-------|----------|
| `explore-fast` | `qwen3-coder-flash` | Eksplorasi codebase cepat |
| `reasoning-deep` | `qwen3.7-max` | Analisis arsitektur kompleks |
| `nvidia-coder` | `deepseek-v4-flash` | Coding via NVIDIA |

Konfigurasi global:
```json
{
  "fastModel": "openai:qwen3-coder-flash",
  "model": { "maxSubagentDepth": 3 },
  "agents": { "builtin": { "exploreModel": "fast" } }
}
```

## Caching

- **DashScope:** `enableCacheControl: true` di generationConfig → kirim cache-control headers
- **UI:** `ui.enableCacheSharing: true` → prefix cache untuk suggestion
- **Context:** `autoCompactThreshold: 0.85` → auto-compress saat context penuh

## Arsitektur

```
Termux HP
  └── Qwen Code CLI (qwen)
        │  OpenAI-compatible Chat Completions
        ├── DashScope intl ── qwen3-coder-plus (1M context, caching)
        ├── DashScope intl ── qwen3.7-max (reasoning + thinking)
        ├── NVIDIA Integrate ── deepseek-v4-flash (coding)
        ├── NVIDIA Integrate ── nemotron-super-49b (reasoning)
        └── Coding Plan (opsional) ── qwen3-coder-plus

  Sub-agents (fastModel)
        └── qwen3-coder-flash / llama-3.1-8b

  Embedding (terpisah)
        └── nvidia/nv-embedqa-e5-v5 (1024 dim)
```

## File Penting

| Path | Isi |
|------|-----|
| `~/.qwen/settings.json` | Config Qwen Code (modelProviders, caching, RPM) |
| `~/.qwen/.env` | API keys (symlink ke secrets.env) |
| `~/.qwen/agents/` | Sub-agent definitions |
| `~/.opsora/qwen-code/secrets.env` | API keys utama |
| `~/.opsora/qwen-code/models.json` | Katalog profile |
| `~/.opsora/qwen-code/rpm-config.json` | RPM/concurrency tuning |
| `~/.opsora/qwen-code/embedding-config.json` | Embedding config |

## Di Dalam Qwen Code

```
/auth          # Ganti auth method
/model         # Pilih model dari daftar
/doctor        # Cek environment & auth
/compress      # Ringkas chat history
/effort high   # Set reasoning effort
/help          # Semua perintah
```

## Troubleshooting

**Install gagal di Termux**
- Pastikan Termux dari F-Droid (bukan Google Play)
- Node.js >= 20: `pkg install nodejs-lts`
- Pakai fork: `npm install -g @mmmbuto/qwen-code-termux@latest`

**Model 503 (NVIDIA)**
- Worker queue penuh — tunggu 30s lalu retry
- Switch ke profile `fast` atau `nvidia-fast`
- Fallback otomatis via `modelFallbacks`

**Coding Plan 401**
- Key Coding Plan **berbeda** dari DASHSCOPE_API_KEY
- Set `BAILIAN_CODING_PLAN_API_KEY=sk-sp-...`

**Reasoning output kosong**
- Model NVIDIA Nemotron Super 49B output di `reasoning_content`, bukan `content`
- Qwen3.7 Max butuh `enable_thinking: true` di extra_body (sudah di-set)

**HP lemot**
- Pakai `qw-fast` untuk sesi ringan
- Turunkan `maxSubagentDepth` ke 2
- Hindari `nvidia-power` saat NVIDIA sedang 503

## Perbandingan dengan Paket Lain

| Paket | CLI | Gateway | Provider |
|-------|-----|---------|----------|
| `qwen-code-termux` | Qwen Code | Tidak perlu | Langsung ke API |
| `claude-code-termux` | Claude Code | LiteLLM :4000 | NVIDIA via proxy |
| `codex-termux-nvidia-setup` | Codex CLI | OpenRouter/LiteLLM | Multi-cloud |

Qwen Code berbicara Chat Completions secara native — tidak butuh LiteLLM gateway seperti Claude/Codex.
