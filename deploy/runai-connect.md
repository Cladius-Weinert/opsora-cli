# Connect AWS GPU → Run:ai SaaS (opsora.nv.run.ai)

Tenant sudah aktif: **https://opsora.nv.run.ai**

## Prerequisites

- NVIDIA Personal Key (`NVIDIA_API_KEY`)
- AWS GPU instance running (`opsora-model` / `opsora-model-vps`)
- `kubectl` + Helm on GPU node or EKS cluster

## Steps

1. Login Run:ai UI: https://opsora.nv.run.ai (SSO NGC)
2. Create cluster → copy install command (Helm)
3. On AWS GPU instance:

```bash
# Example — follow exact command from Run:ai UI
helm repo add runai https://runai.jfrog.io/artifactory/api/helm/runai-charts --username ... --password ...
helm install runai-cluster runai/runai-cluster -n runai --create-namespace
```

4. Verify in UI: **Clusters** → node GPU visible
5. Submit workload (fine-tune / inference):

```bash
runai submit train -p opsora -i nvcr.io/nvidia/nemo-microservices/customizer-api -g 1 \
  --command -- python train.py
```

## Fleet mapping

| Node | IP | Role |
|------|-----|------|
| aop-vps | 54.81.31.132 | Orchestrator |
| opsora-model | 18.208.28.108 | AI worker |
| opsora-brain | 98.94.100.100 | Command center |

Connect **opsora-model** or **opsora-model-vps** to Run:ai for GPU workloads.
