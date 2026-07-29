# Claude Code + NVIDIA — Setup Termux (Android)

Paket ini menghubungkan **Claude Code** di HP Anda ke model **NVIDIA Integrate** lewat proxy Python ringan (`nvidia-proxy.py`). Claude Code mengirim request format Anthropic; proxy menerjemahkannya ke NVIDIA OpenAI-compatible API.

**Tidak perlu LiteLLM** — cocok untuk Termux dengan storage terbatas.

## Model yang tersedia

| Profile | Claude Code name | Backend | Kegunaan |
|---------|------------------|---------|----------|
| `power` | `opsora-power` | Llama 3.3 70B (NVIDIA) | **Full power** — arsitektur, coding berat |
| `balanced` | `opsora-balanced` | Llama 3.1 70B | Sehari-hari |
| `coder` | `opsora-coder` | Llama 3.1 70B | Refactor & debug |
| `reasoning` | `opsora-reasoning` | DeepSeek R1 | Analisis kompleks |
| `nemotron` | `opsora-nemotron` | Nemotron Ultra | Flagship NVIDIA |
| `fast` | `opsora-fast` | Llama 3.1 8B | Background / ringan |
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
opsora-model balanced
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
| `opsora-gateway` | Start NVIDIA proxy (port 4000) |
| `opsora-gateway` stop via `stop-gateway.sh` | Stop proxy |
| `opsora-model power` | Ganti model utama |
| `opsora-claude` | Start gateway + jalankan Claude Code (resolves cli.js at runtime) |

## Ganti model di sesi Claude Code

```bash
opsora-model coder    # Coding profile
opsora-model power    # Llama 3.3 70B full power
```

Atau di dalam Claude Code: `/model` → pilih dari daftar (butuh `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, sudah di-set).

## Arsitektur

```
Termux HP
  └── Claude Code (node + cli.js)
        │  Anthropic Messages API
        ▼
  nvidia-proxy.py :4000
        │  OpenAI-compatible
        ▼
  NVIDIA Integrate API
  https://integrate.api.nvidia.com/v1
        ├── meta/llama-3.3-70b-instruct
        ├── meta/llama-3.1-70b-instruct
        ├── meta/llama-3.1-8b-instruct
        └── ...
```

## File penting

| Path | Isi |
|------|-----|
| `~/.claude/settings.json` | Config Claude Code (base URL, model) |
| `~/.opsora/claude-code/secrets.env` | API keys (JANGAN di-share) |
| `~/.opsora/claude-code/nvidia-proxy.py` | Proxy Anthropic → NVIDIA |
| `~/.opsora/claude-code/models.json` | Katalog profile |

## Troubleshooting

### Gateway test gagal / "Proxy sudah jalan" setelah install

Proxy lama tidak di-restart setelah update `nvidia-proxy.py`. Perbaikan:

```bash
cd ~/opsora-cli && git pull
bash ~/opsora-cli/claude-code-termux/fix-claude-termux.sh
bash ~/.opsora/claude-code/stop-gateway.sh
bash ~/.opsora/claude-code/start-gateway.sh restart
bash ~/.opsora/claude-code/test-gateway.sh opsora-balanced
```

### `Cannot find module cli.js` setelah `/logout`

Wrapper lama membekukan path `cli.js` saat install. Update wrapper:

```bash
bash ~/opsora-cli/claude-code-termux/fix-claude-termux.sh
opsora-claude
```

### `bad interpreter: /usr/bin/env` atau `No such file or directory`

Termux tidak punya `/usr/bin/env`. Claude Code npm memakai shebang itu di `cli.js`.

**Perbaikan cepat (copy-paste):**

```bash
bash ~/opsora-cli/claude-code-termux/fix-claude-termux.sh
```

Atau manual:

```bash
# Perbaiki shebang (pakai single quotes — hindari bash ! expansion)
sed -i '1s|#!/usr/bin/env node|#!/data/data/com.termux/files/usr/bin/node|' \
  ~/.npm-global/lib/node_modules/@anthropic-ai/claude-code/cli.js

# Wrapper yang memanggil node langsung
cat > ~/.local/bin/opsora-claude << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
source "$HOME/.opsora/claude-code/secrets.env"
bash "$HOME/.opsora/claude-code/start-gateway.sh" 2>/dev/null || true
exec "$PREFIX/bin/node" "$HOME/.npm-global/lib/node_modules/@anthropic-ai/claude-code/cli.js" "$@"
EOF
chmod +x ~/.local/bin/opsora-claude
```

### Claude Code native crash / `Bad system call`

Gunakan versi JS **2.1.112** (bukan native binary terbaru):

```bash
npm install -g @anthropic-ai/claude-code@2.1.112
bash ~/opsora-cli/claude-code-termux/fix-claude-termux.sh
```

### Gateway tidak start

```bash
tail -f ~/.opsora/claude-code/gateway.log
curl http://127.0.0.1:4000/health
```

### Model tidak ditemukan di NVIDIA

- Cek model ID di https://build.nvidia.com
- Edit `MODEL_MAP` di `nvidia-proxy.py` jika model ID berubah

### Claude Code masih pakai Anthropic langsung

- Pastikan `ANTHROPIC_API_KEY=""` di settings.json
- Pastikan `ANTHROPIC_BASE_URL=http://127.0.0.1:4000`
- Jalankan `/status` di Claude Code

### HP lemot / storage penuh

- Hindari LiteLLM (butuh banyak disk)
- Pakai `opsora-model fast` (Llama 3.1 8B di cloud NVIDIA)
- Model berat jalan di cloud NVIDIA, bukan di HP — tapi session Claude Code tetap memakai RAM lokal

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
