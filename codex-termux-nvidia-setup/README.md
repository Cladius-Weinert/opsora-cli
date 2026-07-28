# Codex CLI + NVIDIA — Setup Termux (Android)

Paket ini menjalankan **OpenAI Codex CLI** di HP Android (Termux) memakai model **NVIDIA** (build.nvidia.com / integrate.api.nvidia.com) plus provider cloud lain — **tanpa error Responses API**.

> **Penting:** Paket resmi `@openai/codex` gagal di Termux Bionic. Wajib pakai fork Termux: `@mmmbuto/codex-cli-termux`.

## Tiga jalur arsitektur (diuji Jul 2026)

| Jalur | Kapan dipakai | Alur | Status uji |
|-------|---------------|------|------------|
| **C (disarankan)** | HP tanpa VPS, punya NVIDIA key | Termux Codex → **NVIDIA NIM langsung** `/v1/responses` | ✅ Codex 0.145 |
| **A** | Multi-cloud tanpa VPS | Termux Codex → **OpenRouter** `/v1/responses` + BYOK NVIDIA | ✅ (butuh OR key) |
| **B** | Multi-cloud penuh | Termux Codex → **LiteLLM** VPS → NVIDIA + Groq + Gemini + Anthropic | ⚠️ butuh LiteLLM ≥1.94 |

## Mengapa ada gateway?

Codex **hanya** berbicara **Responses API** (`wire_api = "responses"`). Sejak Jul 2026, NVIDIA NIM **juga** expose `/v1/responses` — sehingga **Path C (langsung)** kini berfungsi tanpa proxy.

Untuk provider yang masih Chat Completions saja (Groq, Together, dll.):
- Path A: OpenRouter menerjemahkan ke provider BYOK.
- Path B: LiteLLM proxy dengan `use_chat_completions_api: true`.

## Model NVIDIA aktif (Jul 2026)

| Profil | Model NVIDIA NIM | Catatan |
|--------|------------------|---------|
| `nvidia-deepseek-flash` | `deepseek-ai/deepseek-v4-flash` | **Default** — coding agent cepat |
| `nvidia-nemotron` | `nvidia/nemotron-3-super-120b-a12b` | Flagship NVIDIA |
| `nvidia-llama70` | `meta/llama-3.3-70b-instruct` | General purpose |

> ⚠️ `qwen/qwen3-coder-480b-a35b-instruct` **EOL sejak 2026-06-11** — jangan dipakai lagi.

## Prasyarat Termux

1. **Termux** dari F-Droid (bukan Play Store)
2. **Termux:API** (opsional, untuk `termux-open-url` saat login)
3. **Node.js LTS**: `pkg install nodejs-lts`
4. **Proyek di `~/projects`** — jangan `/sdcard` (FUSE noexec)
5. **NVIDIA API key**: https://build.nvidia.com/settings/api-keys (`nvapi-...`)

## Install cepat (Path C — NVIDIA langsung)

```bash
# Di Termux:
pkg update && pkg upgrade -y
pkg install git curl jq nodejs-lts

# Clone atau download paket setup
git clone https://github.com/Cladius-Weinert/opsora-cli.git ~/opsora-cli
bash ~/opsora-cli/codex-termux-nvidia-setup/termux-install.sh

# Isi API key NVIDIA
nano ~/.codex/.env
# NVIDIA_API_KEY=nvapi-xxxxxxxx

source ~/.bashrc

# Uji koneksi NVIDIA
bash ~/opsora-cli/codex-termux-nvidia-setup/smoke-test.sh nvidia

# Jalankan Codex (default: deepseek-v4-flash)
cd ~/projects
codex --profile nvidia-deepseek-flash
# atau alias: cdx-deepseek
```

## Path A — OpenRouter BYOK

```bash
# Tambahkan di ~/.codex/.env:
# OPENROUTER_API_KEY=sk-or-v1-...
# NVIDIA_API_KEY=nvapi-...  (untuk BYOK)

# Aktifkan BYOK NVIDIA di dashboard:
# https://openrouter.ai/settings/integrations

bash smoke-test.sh openrouter
codex --profile or-deepseek-flash
```

## Path B — VPS LiteLLM

```bash
# Di VPS
cd codex-termux-nvidia-setup
cp litellm.env.example .env   # isi NVIDIA_API_KEY, LITELLM_MASTER_KEY, dll
docker compose -f litellm-docker-compose.yml up -d

# Di Termux:
codex-use-litellm https://vps-anda:4000/v1
codex --profile litellm-deepseek-flash
```

> **Catatan LiteLLM:** Codex 0.145 mengirim `client_metadata` yang ditolak NVIDIA via bridge. Gunakan image `ghcr.io/berriai/litellm:main-latest` (bukan versi lama). Jika error `Unsupported parameter(s): client_metadata`, upgrade LiteLLM atau pakai Path C.

## Profil Codex ≥0.134

Sejak Codex 0.134, profil disimpan di file terpisah:

```
~/.codex/nvidia-deepseek-flash.config.toml
~/.codex/nvidia-nemotron.config.toml
~/.codex/nvidia-llama70.config.toml
```

Script install menyalin file ini otomatis. Aktifkan dengan:

```bash
codex --profile nvidia-deepseek-flash
```

## File dalam paket

| File | Fungsi |
|------|--------|
| `termux-install.sh` | Bootstrap Termux lengkap |
| `dot-codex/config.toml` | → salin ke `~/.codex/config.toml` |
| `dot-codex/*.config.toml` | Profil per-model (Codex ≥0.134) |
| `dot-codex/env.example` | Template API keys → `~/.codex/.env` |
| `litellm_config.yaml` | Proxy multi-cloud (Path B) |
| `litellm-docker-compose.yml` | Docker Compose VPS |
| `smoke-test.sh` | Uji curl OpenRouter / LiteLLM / NVIDIA |
| `TROUBLESHOOTING.md` | Tabel error → perbaikan |

## Hasil uji coba (Jul 2026)

| Test | Hasil |
|------|-------|
| NVIDIA `/chat/completions` deepseek-v4-flash | ✅ HTTP 200 |
| NVIDIA `/responses` direct dari Codex 0.145 | ✅ Reply OK |
| NVIDIA nemotron-3-super via Codex | ✅ Reply OK |
| Codex tool use (buat file) via NVIDIA direct | ✅ File terbuat |
| LiteLLM `/responses` smoke (curl) | ✅ HTTP 200 |
| Codex → LiteLLM → NVIDIA | ⚠️ `client_metadata` error (butuh LiteLLM main-latest) |
| Model qwen3-coder EOL | ❌ HTTP 410 Gone |

## Batasan kritis

- Provider **hanya** di `~/.codex/config.toml` (bukan project `.codex/`).
- Jangan pakai ID reserved: `openai`, `ollama`, `lmstudio`.
- Proyek kerja di `~/projects` — **bukan** `/sdcard`.
- `wire_api` harus `"responses"` (default sejak Codex modern).
- Fork Termux `@mmmbuto/codex-cli-termux` track upstream ~0.145.

## Referensi

- [OpenAI Codex CLI](https://github.com/openai/codex)
- [DioNanos/codex-termux](https://github.com/DioNanos/codex-termux) — fork Termux
- [NVIDIA NIM Models](https://build.nvidia.com/models)
- [Codex Custom Providers](https://developers.openai.com/codex/config-advanced)
