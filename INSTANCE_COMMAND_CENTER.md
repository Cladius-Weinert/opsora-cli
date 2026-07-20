# 🏠 Opsora Unified Instance Command Center — Plan

## Current State: 6 Instances Across 2 Regions

| # | Instance | Type | Platform | State | Region | SSM | Data |
|---|----------|------|----------|-------|--------|-----|------|
| 1 | **opsora-brain** | r5.2xlarge | Linux | ✅ Running | us-east-1 | ✗ | 600MB+ projects, agents, DBs, Docker |
| 2 | **rdp-windows-prod** | m5zn.2xlarge | Windows | ✅ Running | us-west-2 | ✅ Online | TeamViewer, Terraform, Docker, Python 3.14, Datadog |
| 3 | pw-agent-vps | m7i-flex.large | Linux | Stopped | us-east-1 | ✗ | Unknown |
| 4 | cloudpc-ec2-win | m5.xlarge | Windows | Stopped | us-east-1 | ✗ | Unknown |
| 5 | my-termux-vm | t3.micro | Linux | Stopped | us-east-1 | ✗ | Unknown |
| 6 | opsora-model-vps | m7i-flex.large | Linux | Stopped | us-east-1 | ✗ | Unknown |

## Credential Inventory

### AWS Profiles (6 total)
| Profile | Account | User | Status |
|---------|---------|------|--------|
| **default** | 134748917746 | jalankecil351 | ✅ Valid |
| **cladius** | 134748917746 | vps-operator | ✅ Valid |
| **kimchi-bedrock** | 134748917746 | kimchi-bedrock-user | ✅ Valid (Bedrock only) |
| root1 | 134748917746 | - | ❌ Expired |
| root2 | 134748917746 | - | ❌ Expired |
| opsora_2 | 134748917746 | - | ❌ Expired |

### AI Provider Keys
| Provider | Key | Status |
|----------|-----|--------|
| NVIDIA | nvapi-8fOcr... | ✅ Configured |
| Alibaba/DashScope | sk-ws-H.YIHYYH... + 2 alt keys | ✅ 3 keys configured |
| OpenAI | $DASHSCOPE_API_KEY (alias) | ✅ Configured |
| Kimchi/CAST AI | castai_v1_cb999... | ✅ Configured |
| Datadog | 97c5d199e4cfd... | ✅ Configured |
| RAM (Alibaba) | LTAI5tDgTVdo... | ✅ Configured |

### Aliyun
| Profile | Access Key | Region | Status |
|---------|-----------|--------|--------|
| default | LTAI5tDgTVdousEGHQxA1PMG | ap-southeast-1 | ✅ Configured |

## Architecture: 1 Kepala

```
                    ┌─────────────────────────────────┐
                    │    OPSORA-BRAIN (r5.2xlarge)    │
                    │    ← CENTRAL COMMAND CENTER →   │
                    │    us-east-1 | Linux             │
                    │                                  │
                    │  • Instance Command Center v2    │
                    │  • Opsora CLI v2 (Codex style)   │
                    │  • All 6 AWS profiles            │
                    │  • All AI provider keys          │
                    │  • Memory + Graphify             │
                    │  • Docker (9 containers)         │
                    │  • 15 projects (2.8GB+)          │
                    └──────┬─────────┬─────────┬───────┘
                           │         │         │
              ┌────────────┤    SSM  │   SSH   │
              │            │         │         │
     ┌────────▼───────┐  ┌▼──────────┐  ┌──────▼────────┐
     │ rdp-windows-   │  │ pw-agent  │  │ cloudpc-ec2   │
     │ prod           │  │ vps       │  │ win           │
     │ us-west-2      │  │ us-east-1 │  │ us-east-1     │
     │ SSM ✅ Online  │  │ Stopped   │  │ Stopped       │
     │ Terraform,     │  │ Unknown   │  │ Unknown       │
     │ Docker, Python │  │           │  │               │
     └────────────────┘  └───────────┘  └───────────────┘
```

## How It Works

### 1. Centralized Discovery
Command Center otomatis discover semua instance dari:
- Semua AWS profiles (default, cladius)
- Semua regions (us-east-1, us-west-2)
- SSM agent status check

### 2. Remote Data Access
- **Windows instances** → SSM + PowerShell scripts
- **Linux instances** → SSM + Shell scripts (atau SSH)
- Pre-built data categories: disk, services, network, processes, docker, files, apps, users

### 3. Unified Command Interface
```bash
# Jalankan command center
python3 ~/opsora-cli/cmd/instance_command_center.py

# Commands:
list              # Show semua instance
local             # Catalog data di opsora-brain
data rdp-windows  # Browser data di Windows instance
start opsora-model-vps  # Start stopped instance
stop pw-agent-vps       # Stop instance
ssh rdp-windows         # SSH ke instance
run rdp-windows "Get-Process"  # Run command via SSM
```

## Phase 1: Sekarang ✅

- [x] Semua credentials teridentifikasi dan terverifikasi
- [x] Instance Command Center v2 built dan tested
- [x] SSM access ke rdp-windows-prod (us-west-2) berhasil
- [x] Local data catalog di opsora-brain berfungsi
- [x] Auto-discovery dari multi-profile + multi-region

## Phase 2: Setup SSM di Semua Instance

**Target**: Install SSM agent di opsora-brain dan stopped instances

```bash
# Install SSM agent di opsora-brain (Linux)
sudo snap install amazon-ssm-agent --classic
sudo systemctl enable amazon-ssm-agent
sudo systemctl start amazon-ssm-agent

# Start instances yang stopped
aws ec2 start-instances --profile default --region us-east-1 \
  --instance-ids i-0bb950a0931925396  # pw-agent-vps
aws ec2 start-instances --profile default --region us-east-1 \
  --instance-ids i-0003ea3b38cd081ed  # cloudpc-ec2-win
aws ec2 start-instances --profile default --region us-east-1 \
  --instance-ids i-07e7a1a744e0f79a3  # my-termux-vm
aws ec2 start-instances --profile default --region us-east-1 \
  --instance-ids i-066d391b203fc87ae  # opsora-model-vps

# Setelah running, install SSM agent
# Linux: sudo snap install amazon-ssm-agent --classic
# Windows: SSM Agent pre-installed di Amazon AMI
```

## Phase 3: Sync Mechanism

### Option A: Git-based Sync
```bash
# Buat repo private untuk sync code antar instance
# opsora-brain sebagai origin, instance lain sebagai remotes
```

### Option B: S3 Sync
```bash
# Bucket untuk shared artifacts
aws s3 sync /home/ubuntu/ s3://opsora-production-artifacts/shared/
```

### Option C: SSM Document Distribution
```bash
# Push scripts/configs ke semua instance via SSM
aws ssm create-document --name "opsora-setup" --document-type "Command"
```

## Phase 4: Expired Key Rotation

```bash
# Rotate keys untuk expired profiles
# root1, root2, opsora_2 — perlu IAM user baru + credentials
```

## Data Yang Terkumpul

### opsora-brain (THIS machine)
- **15 projects**: ai-coding-workspace (608MB), claude-code-agent (602MB), opsora (532MB), god-mode-v4 (502MB), gpt-pilot (453MB), bedrock-agent (450MB), dll
- **4 agent files**: agent.py, agent_base.py, agent_manager.py, agent_sagemaker.py
- **1 database**: opsora_memory.db (20KB)
- **9 Docker containers** (2 running: constituent-dashboard, opsora-webui)
- **All AI provider keys** dan AWS credentials

### rdp-windows-prod (us-west-2, Windows, SSM Online)
- **C:\terraform-aws** — Terraform configs
- **C:\tools** — Scripts, bootstrap, modules, accounts
- **C:\Python314** — Python 3.14 installation
- **C:\TeamViewer** — Remote access
- **C:\Docker** — Docker installation
- **C:\Datadog** — Monitoring agent
- **C:\WSL** — Windows Subsystem for Linux
- **C:\WorkBuddyAI** — AI assistant tool
- **Chrome profiles** — Browser data
- **AnyDesk** — Remote access alternative
- **OBS Studio** — Screen recording
- **Services**: Datadog, Docker, TeamViewer, dll

## Commands Reference

```bash
# Quick instance check
python3 ~/opsora-cli/cmd/instance_command_center.py list

# Access Windows instance data
python3 ~/opsora-cli/cmd/instance_command_center.py data rdp-windows

# Catalog local data
python3 ~/opsora-cli/cmd/instance_command_center.py local

# Start all stopped instances
python3 ~/opsora-cli/cmd/instance_command_center.py all-start

# Run command on Windows via SSM
python3 ~/opsora-cli/cmd/instance_command_center.py run rdp-windows "Get-Service"

# Opsora CLI v2 (Codex-style)
opsora
```

---

**Status**: Phase 1 Complete ✅
**Next**: Phase 2 — Install SSM agent di semua instance
**Central Command**: `/home/ubuntu/opsora-cli/cmd/instance_command_center.py`
