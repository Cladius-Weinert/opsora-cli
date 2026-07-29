# Opsora Cloud Deploy — NVIDIA NGC + AWS

Deploy custom agent stack (memory, cache, context, skills) ke NVIDIA Console dan AWS EC2.

## Prerequisites

| Secret | Untuk | Status di Cloud Agent |
|--------|-------|----------------------|
| `NVIDIA_API_KEY` | Integrate API + NVCF | ✅ Tersedia |
| `DASHSCOPE_API_KEY` | Fallback Alibaba | ✅ Tersedia |
| `AWS_SECRET_ACCESS_KEY` | EC2 API / boto3 | ❌ **Belum di-inject** |
| `AWS_EC2_PEM` atau SSH key | SSH ke opsora-brain | ❌ Tidak ada di agent |

> Cloud Agent IP (`13.59.103.110`) saat ini **diblok** oleh security group EC2 Anda (SSH connection reset).

---

## 1. NVIDIA NGC / Console (bisa dari mana saja)

```bash
export NVIDIA_API_KEY=nvapi-...
bash deploy/ngc/build-custom-catalog.sh
```

Output:
- `~/.opsora/nvidia-custom/integrate-models.json` — 102 model
- `~/.opsora/nvidia-custom/nvcf-functions.json` — 183 functions
- `~/.opsora/nvidia-custom/opsora-nvidia-profiles.json` — profile custom Opsora

### Profile yang diverifikasi

| Profile | Backend | Model |
|---------|---------|-------|
| balanced | Integrate | `meta/llama-3.1-70b-instruct` |
| fast | Integrate | `meta/llama-3.1-8b-instruct` |
| coder | Integrate | `deepseek-ai/deepseek-v4-pro` |
| flagship | Integrate | `nvidia/nemotron-3-super-120b-a12b` |
| nvcf_gemma | NVCF | `ai-gemma-2-2b-it` |

NVCF active functions untuk coding: **55** (dari 148 total active).

---

## 2. AWS EC2 — Bootstrap di opsora-brain

Jalankan **dari dalam** `opsora-brain` (98.94.100.100) atau instance Ubuntu lain:

```bash
export NVIDIA_API_KEY=nvapi-...
export DASHSCOPE_API_KEY=sk-...   # opsional

curl -fsSL https://raw.githubusercontent.com/Cladius-Weinert/opsora-cli/cursor/agent-stack-context-cache-c133/deploy/aws/bootstrap-opsora-agent.sh | bash
```

Ini akan:
1. Clone `opsora-cli` branch agent-stack
2. Install `opsora` package (memory, cache, skills)
3. Build NVIDIA custom catalog
4. Setup LiteLLM gateway + systemd service
5. Buat `opsora-brain-status` helper

Setelah bootstrap:
```bash
nano ~/.opsora/opsora_env          # isi API keys
source ~/.opsora/opsora_env
sudo systemctl enable --now opsora-gateway
opsora-brain-status
opsora
```

---

## 3. Connect compute (NVIDIA + gateway)

Jalankan dari mana saja dengan Opsora Personal Key:

```bash
export NVIDIA_API_KEY=nvapi-...
export NGC_ORG_ID=1006275399815502
bash deploy/connect-compute.sh
```

Ini akan:
1. Build NVIDIA catalog (102 model + NVCF)
2. Generate `~/.opsora/compute-registry.json`
3. Start LiteLLM gateway di `:4000` (12 model profiles)
4. Smoke test `opsora-fast`

Gateway endpoint: `http://127.0.0.1:4000/v1` (auth: `LITELLM_MASTER_KEY`)

Run:ai SaaS tenant: https://opsora.nv.run.ai — lihat `deploy/runai-connect.md`

## 4. Deploy semua (master script)

```bash
bash deploy/deploy-all.sh
```

---

## 5. NVIDIA Cloud only (tanpa AWS) — **pakai ini kalau fleet macet**

```bash
export NVIDIA_API_KEY=nvapi-...
bash deploy/nvidia-cloud-only.sh
```

Deploy publik ke **Render** (console lain, gratis):
1. https://dashboard.render.com → **New** → **Blueprint**
2. Repo `Cladius-Weinert/opsora-cli` branch `cursor/nvidia-cloud-stack-c133`
3. Set `NVIDIA_API_KEY` → dapat URL `https://opsora-gateway.onrender.com/v1`

Detail: [`deploy/nvidia-cloud/README.md`](nvidia-cloud/README.md)

---

## 6. Agar Cloud Agent bisa deploy AWS langsung

Tambahkan secrets di Cursor Cloud Agent environment:

1. `AWS_SECRET_ACCESS_KEY` — wajib untuk EC2 API
2. (Opsional) Upload `Cladius-Weinert-AWS-EC2-Key.pem` ke `opsora/secrets/aws_ec2_key`
3. Buka security group EC2 port 22 untuk IP Cloud Agent, atau gunakan SSM

Setelah itu agent bisa:
- Start stopped instances (`my-termux-vm`, `opsora-model-vps`)
- Run SSM commands
- Deploy otomatis tanpa SSH manual

---

## Architecture

```
NVIDIA Console (NGC)
  ├── Integrate API (102 models) ← opsora-nvidia-profiles.json
  └── NVCF (148 active)        ← LiteLLM routing

AWS opsora-brain (EC2)
  ├── opsora CLI (memory/cache/skills)
  ├── LiteLLM gateway :4000
  └── Ollama :11434 (fallback lokal)

Termux HP
  └── SSH / sync dari opsora-brain
```
