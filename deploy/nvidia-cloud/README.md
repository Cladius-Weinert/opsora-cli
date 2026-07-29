# Opsora — NVIDIA Cloud Stack (tanpa AWS)

Kalau AWS fleet macet (SSH blocked, key invalid), pakai stack ini.

## Apa yang jalan

| Platform | URL | Perlu |
|----------|-----|-------|
| **NVIDIA Integrate API** | `integrate.api.nvidia.com` | `NVIDIA_API_KEY` ✅ |
| **Run:ai SaaS** | https://opsora.nv.run.ai | Login SSO NVIDIA |
| **LiteLLM Gateway (lokal)** | `http://127.0.0.1:4000/v1` | `bash deploy/nvidia-cloud-only.sh` |
| **LiteLLM Gateway (Render)** | `https://opsora-gateway.onrender.com/v1` | Deploy blueprint (lihat bawah) |

## 1. Jalankan dari Cloud Agent / laptop (instant)

```bash
export NVIDIA_API_KEY=nvapi-...
export NGC_ORG_ID=1006275399815502
bash deploy/nvidia-cloud-only.sh
```

Test:
```bash
curl http://127.0.0.1:4000/v1/models \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"

curl http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"opsora-fast","messages":[{"role":"user","content":"halo"}],"max_tokens":32}'
```

## 2. Deploy ke Render (console lain — gratis tier)

1. Buka https://dashboard.render.com/
2. **New** → **Blueprint**
3. Connect repo `Cladius-Weinert/opsora-cli`
4. Branch: `cursor/nvidia-cloud-stack-c133`
5. Render baca `render.yaml` otomatis
6. Isi secret `NVIDIA_API_KEY` saat deploy
7. URL publik: `https://opsora-gateway.onrender.com`

Atau one-click (setelah login Render):
https://dashboard.render.com/select-repo?type=blueprint

### Pakai dari Termux / Claude Code

```bash
export OPENAI_API_BASE=https://opsora-gateway.onrender.com/v1
export OPENAI_API_KEY=<LITELLM_MASTER_KEY dari Render dashboard>
```

Model: `opsora-fast`, `opsora-balanced`, `opsora-nemotron`, dll.

## 3. Run:ai (GPU cluster)

Tenant sudah ada: **opsora.nv.run.ai**

1. Login https://opsora.nv.run.ai dengan akun NVIDIA Opsora org
2. **Clusters** → Connect cluster (AWS/GCP/on-prem GPU)
3. Fine-tune NeMo: butuh GPU self-hosted + AI Enterprise

Detail: `deploy/runai-connect.md`

## Model profiles (verified)

| Alias | Backend |
|-------|---------|
| opsora-fast | llama-3.1-8b-instruct |
| opsora-balanced | llama-3.1-70b-instruct |
| opsora-power | deepseek-v4-pro |
| opsora-nemotron | nemotron-3-super-120b |

## Kenapa tidak AWS?

- Cloud Agent IP berubah → Security Group whitelist tidak praktis
- AWS keys yang dikirim invalid (`InvalidClientTokenId`)
- Instance `pw-agent-vps` / `opsora-model` sering **Stopped**

Stack NVIDIA + Render menggantikan **command center** tanpa perlu SSH ke EC2.
