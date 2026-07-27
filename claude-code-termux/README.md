# Claude Code + NVIDIA — Setup Termux (Android)

Paket ini menghubungkan **Claude Code** di HP Anda ke model **NVIDIA Integrate** (dan provider lain) lewat gateway **LiteLLM**. Claude Code mengirim request format Anthropic; LiteLLM menerjemahkannya ke NVIDIA/OpenAI-compatible API.

## Model yang tersedia

| Profile | Claude Code name | Backend | Kegunaan |
|---------|------------------|---------|----------|
| `power` | `opsora-power` | Llama 3.3 70B (NVIDIA) | **Full power** — arsitektur, coding berat |
| `balanced` | `opsora-balanced` | Llama 3.1 70B | Sehari-hari |
| `coder` | `opsora-coder` | DeepSeek V4 Flash | Refactor & debug |
| `reasoning` | `opsora-reasoning` | DeepSeek R1 | Analisis kompleks |
| `nemotron` | `opsora-nemotron` | Nemotron 340B | Flagship NVIDIA |
| `fast` | `opsora-fast` | Ministral 14B | Background / ringan |
| `qwen-plus` | `opsora-qwen-plus` | Qwen Plus (Alibaba) | Butuh `DASHSCOPE_API_KEY` |
| `qwen-max` | `opsora-qwen-max` | Qwen Max (Alibaba) | Full power Alibaba |
| `local` | `opsora-local` | Ollama di HP | Offline (butuh `ollama serve`) |

## Install cepat (Termux)

```bash
# 1) Clone repo
pkg install git -y
git clone https://github.com/Cladius-Weinert/opsora-cli.git ~/opsora-cli
cd ~/opsora-cli/claude-code-termux

# 2) Install
bash install-termux.sh

# 3) Isi NVIDIA API key
nano ~/.opsora/claude-code/secrets.env
# export NVIDIA_API_KEY=nvapi-...

# 4) Start gateway + Claude Code
opsora-gateway
opsora-model power
opsora-claude
```

Atau one-liner (setelah clone):

```bash
bash ~/opsora-cli/claude-code-termux/install-termux.sh
```

## NVIDIA API Key

1. Buka https://org.ngc.nvidia.com/setup/api-keys
2. Buat **Personal Key** (format `nvapi-...`)
3. Paste ke `~/.opsora/claude-code/secrets.env`

## Perintah shell

| Command | Fungsi |
|---------|--------|
| `opsora-gateway` | Start LiteLLM proxy (port 4000) |
| `opsora-gateway` stop via `stop-gateway.sh` | Stop proxy |
| `opsora-model power` | Ganti model utama |
| `opsora-claude` | Start gateway + jalankan `claude` |

## Ganti model di sesi Claude Code

```bash
opsora-model coder    # DeepSeek untuk coding
opsora-model power    # Llama 3.3 70B full power
```

Atau di dalam Claude Code: `/model` → pilih dari daftar (butuh `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, sudah di-set).

## Arsitektur

```
Termux HP
  └── Claude Code (claude)
        │  Anthropic Messages API
        ▼
  LiteLLM gateway :4000
        │  OpenAI-compatible
        ▼
  NVIDIA Integrate API
  https://integrate.api.nvidia.com/v1
        ├── meta/llama-3.3-70b-instruct
        ├── deepseek-ai/deepseek-v4-flash
        ├── mistralai/ministral-14b-instruct-2512
        └── ...
```

## File penting

| Path | Isi |
|------|-----|
| `~/.claude/settings.json` | Config Claude Code (base URL, model) |
| `~/.opsora/claude-code/secrets.env` | API keys (JANGAN di-share) |
| `~/.opsora/claude-code/litellm-config.yaml` | Mapping model |
| `~/.opsora/claude-code/models.json` | Katalog profile |

## Troubleshooting

**Gateway tidak start**
```bash
tail -f ~/.opsora/claude-code/gateway.log
```

**Model tidak ditemukan di NVIDIA**
- Cek model ID di https://build.nvidia.com
- Edit `litellm-config.yaml` jika model ID berubah

**Claude Code masih pakai Anthropic langsung**
- Pastikan `ANTHROPIC_API_KEY=""` di settings.json
- Pastikan `ANTHROPIC_BASE_URL=http://127.0.0.1:4000`
- Jalankan `/status` di Claude Code

**HP lemot / RAM kecil**
- Pakai `opsora-model fast` atau `opsora-model local` (Ollama 7B)
- Hindari `nemotron` dan `power` di device RAM < 6GB (model jalan di cloud NVIDIA, bukan lokal — tapi session Claude Code tetap berat)

## Opsional: Alibaba Qwen

Tambahkan di `secrets.env`:
```bash
export DASHSCOPE_API_KEY=sk-...
```
Lalu: `opsora-model qwen-plus`

## Opsional: Ollama lokal

```bash
pkg install ollama  # atau install manual
ollama pull qwen2.5-coder:7b
ollama serve &
opsora-model local
```
