# Codex CLI + NVIDIA — Setup Termux (Android)

Paket ini menjalankan **OpenAI Codex CLI** di HP Android (Termux) memakai model **NVIDIA** (build.nvidia.com / integrate.api.nvidia.com) plus provider cloud lain — **tanpa error Responses API**.

> **Penting:** Paket resmi `@openai/codex` gagal di Termux Bionic. Wajib pakai fork Termux: `@mmmbuto/codex-cli-termux`.

## Dua jalur arsitektur

| Jalur | Kapan dipakai | Alur |
|-------|---------------|------|
| **A (disarankan untuk HP)** | Setup ringan, tanpa VPS | Termux Codex → **OpenRouter** `/v1/responses` + **BYOK NVIDIA** |
| **B (power / multi-cloud)** | Butuh kontrol penuh | Termux Codex → **LiteLLM** di VPS → NVIDIA NIM + Groq + Together + DeepSeek + Gemini + Anthropic |

## Mengapa harus ada gateway?

Codex **hanya** berbicara **Responses API** (`wire_api = "responses"`). NVIDIA NIM hanya punya **Chat Completions**. Jadi:

- Path A: OpenRouter sudah expose `/v1/responses` (menerjemahkan ke provider BYOK).
- Path B: LiteLLM proxy dengan `use_chat_completions_api: true` menerjemahkan `/responses` → `/chat/completions`.

## Model (profil Codex)

| Profil | Model | Catatan |
|--------|-------|---------|
| `nvidia-qwen-coder` | `qwen/qwen3-coder` (OR) / `qwen/qwen3-coder-480b-a35b-instruct` (NIM) | Coding agent utama |
| `nvidia-deepseek-flash` | `deepseek/deepseek-v4-flash` | Cepat, coding/refactor |
| `nvidia-nemotron` | `nvidia/nemotron-3-super-120b-a12b` | Flagship NVIDIA |
| `nvidia-llama70` | `meta-llama/llama-3.3-70b-instruct` | General power |
| `groq-fast` / `together` / `deepseek` / `gemini` / `anthropic` | sesuai cloud | Path A via OpenRouter; Path B via LiteLLM |

## Install cepat (Path A — HP)

```bash
# Di Termux:
pkg update && pkg upgrade -y
curl -fsSL https://raw.githubusercontent.com/Cladius-Weinert/opsora-cli/main/codex-termux-nvidia-setup/termux-install.sh | bash
# atau dari clone lokal:
bash ~/opsora-cli/codex-termux-nvidia-setup/termux-install.sh

# Isi kunci API
cp ~/.codex/.env.example ~/.codex/.env
nano ~/.codex/.env   # OPENROUTER_API_KEY + (opsional) NVIDIA_API_KEY untuk BYOK

# Aktifkan BYOK NVIDIA di dashboard OpenRouter:
# https://openrouter.ai/settings/integrations

# Uji
bash ~/opsora-cli/codex-termux-nvidia-setup/smoke-test.sh openrouter

# Jalankan Codex
cd ~/projects
codex --profile nvidia-qwen-coder
```

## Path B — VPS LiteLLM

```bash
# Di VPS
cd codex-termux-nvidia-setup
cp litellm.env.example .env   # isi NVIDIA_API_KEY, GROQ_API_KEY, dll + LITELLM_MASTER_KEY
docker compose -f litellm-docker-compose.yml up -d

# Di Termux: set LITELLM_BASE_URL ke https://vps-anda:4000/v1
# lalu: codex --profile litellm-qwen-coder
```

## File dalam paket

| File | Fungsi |
|------|--------|
| `termux-install.sh` | Bootstrap Termux lengkap |
| `dot-codex/config.toml` | → salin ke `~/.codex/config.toml` |
| `dot-codex/env.example` | Template API keys → `~/.codex/.env` |
| `litellm_config.yaml` | Proxy multi-cloud (Path B) |
| `litellm-docker-compose.yml` | Docker Compose VPS |
| `smoke-test.sh` | Uji curl OpenRouter / LiteLLM / NVIDIA |
| `TROUBLESHOOTING.md` | Tabel error → perbaikan |

## Batasan kritis

- Provider **hanya** di `~/.codex/config.toml` (bukan project `.codex/`).
- Jangan pakai ID reserved: `openai`, `ollama`, `lmstudio`.
- Proyek kerja di `~/projects` — **bukan** `/sdcard`.
- `wire_api` harus `"responses"` (default sejak Codex modern).
