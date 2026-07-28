# Troubleshooting — Codex + Termux + NVIDIA

| Error / gejala | Penyebab | Perbaikan |
|----------------|----------|-----------|
| `cannot execute binary` / `No such file or directory` saat jalankan `codex` | Paket resmi `@openai/codex` (glibc) di Termux Bionic | `npm uninstall -g @openai/codex` lalu `npm i -g @mmmbuto/codex-cli-termux@latest` |
| `Error loading config.toml: 'wire_api = "chat"' is no longer supported` | Codex ≥0.122 menghapus Chat Completions wire | Set `wire_api = "responses"` atau hapus baris (default = responses) |
| `404` / `Not Found` ke `integrate.api.nvidia.com/.../responses` | NVIDIA NIM **hanya** Chat Completions | Jangan arahkan Codex ke NVIDIA langsung. Pakai OpenRouter (Path A) atau LiteLLM + `use_chat_completions_api: true` (Path B) |
| LiteLLM `/responses` → 500 / upstream 404 | Bridge belum aktif; request diteruskan ke `/responses` backend | Di `litellm_config.yaml` set `use_chat_completions_api: true` dan `model: openai/<id>` + `api_base: https://integrate.api.nvidia.com/v1` |
| `provider ... is reserved` / tidak bisa override `openai` | ID reserved: `openai`, `ollama`, `lmstudio` | Pakai id custom: `openrouter`, `litellm_proxy`, dll. di `[model_providers.*]` |
| `model_provider` di project `.codex/config.toml` diabaikan | Provider hanya di user-level | Pindahkan ke `~/.codex/config.toml` |
| `OPENROUTER_API_KEY` missing / 401 | Env belum di-load | `cp ~/.codex/.env.example ~/.codex/.env`, isi key, `source ~/.bashrc` |
| OpenRouter 402 / credit errors meski ada NVIDIA key | BYOK belum di-set / fallback credit habis | Aktifkan BYOK NVIDIA di https://openrouter.ai/settings/integrations ; opsi "Always use this key" |
| OpenRouter model not found | Salah slug | Pakai slug OR: `qwen/qwen3-coder`, `deepseek/deepseek-v4-flash`, `nvidia/nemotron-3-super-120b-a12b`, `meta-llama/llama-3.3-70b-instruct` |
| NVIDIA 401 / 403 | Key invalid atau trial habis | Buat ulang di https://build.nvidia.com/settings/api-keys (`nvapi-...`) |
| NVIDIA 404 model | Model ID salah untuk Integrate API | Gunakan ID penuh: `qwen/qwen3-coder-480b-a35b-instruct`, `deepseek-ai/deepseek-v4-flash`, `nvidia/nemotron-3-super-120b-a12b`, `meta/llama-3.3-70b-instruct` |
| Codex hang / stream idle timeout di HP | Jaringan lambat / model besar | Naikkan `stream_idle_timeout_ms` di provider; atau pakai profil `nvidia-deepseek-flash` / Groq |
| Permission / sandbox error di `/sdcard/...` | FUSE `/sdcard` tidak cocok untuk tool Codex | Kerjakan di `~/projects` (home Termux), bukan `/sdcard` |
| `termux-open-url: not found` saat login | Termux:API belum terpasang | `pkg install termux-api` + install app **Termux:API** dari F-Droid |
| `codex: command not found` setelah npm install | npm global bin tidak di PATH | Tambahkan `export PATH="$(npm bin -g):$HOME/.local/bin:$PATH"` ke `~/.bashrc` |
| Profile `--profile X` tidak mengubah model (Codex ≥0.134) | Profil pindah ke file terpisah | Buat `~/.codex/X.config.toml` (top-level keys); Termux fork ~0.130 masih mendukung `[profiles.X]` |
| LiteLLM health OK tapi Codex 401 | `LITELLM_API_KEY` ≠ `LITELLM_MASTER_KEY` | Samakan key di VPS `.env` dan `~/.codex/.env` |
| LiteLLM container exit / crash loop | Config YAML invalid / key kosong | `docker logs codex-litellm-proxy`; pastikan `litellm_config.yaml` mount + `NVIDIA_API_KEY` terisi |
| Connection refused ke VPS:4000 dari HP | Firewall / bind salah | Bind `0.0.0.0:4000`, buka port, atau taruh reverse proxy HTTPS; update `base_url` di `litellm_proxy` |
| SSL / cleartext blocked | HTTP dari HP ke VPS tanpa TLS | Pasang Caddy/nginx TLS; gunakan `https://.../v1` |
| `jq: not found` di smoke-test | jq belum terpasang | `pkg install jq` (Termux) / `apt install jq` (VPS) |
| Responses body kosong / tool loop aneh | Model tidak bagus untuk agentic coding | Ganti profil `nvidia-qwen-coder` atau Anthropic via OpenRouter/LiteLLM |
| `LD_LIBRARY_PATH` / `libc++_shared.so` errors | Binary native Termux fork | Reinstall `@mmmbuto/codex-cli-termux@latest`; jangan jalankan ELF dari lokasi yang memutus `RUNPATH=$ORIGIN` |
| Rate limit 429 | Kuota provider / OR | Tunggu, ganti profil, atau naikkan limit di dashboard provider |

## Cek cepat

```bash
# Path A
bash smoke-test.sh openrouter
codex --profile nvidia-qwen-coder "print hello"

# Path B
bash smoke-test.sh litellm
bash smoke-test.sh nvidia
codex --profile litellm-qwen-coder "print hello"
```

## Referensi endpoint

| Layanan | Endpoint yang dipakai Codex / smoke |
|---------|-------------------------------------|
| OpenRouter | `https://openrouter.ai/api/v1/responses` |
| LiteLLM proxy | `{LITELLM_BASE_URL}/responses` |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1/chat/completions` (**bukan** `/responses`) |
