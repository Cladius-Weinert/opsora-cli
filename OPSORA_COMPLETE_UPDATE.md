# 🚀 OPSORA COMPLETE SYSTEM UPDATE — 2026-07-20

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    OPSORA-BRAIN (us-east-1)                  │
│                    r5.2xlarge | Linux | 98.94.100.100       │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ Opsora   │  │ Instance │  │ Windows  │  │ Gmail/API  │  │
│  │ CLI v2   │  │ Command  │  │ Agent    │  │ Clients    │  │
│  │ (Codex)  │  │ Center   │  │ (SSM)    │  │            │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Docker: 8 containers | 6 ports active               │   │
│  │  Guacamole:8888 | WebUI:3000 | Dashboard:8000        │   │
│  │  Qdrant:6333 | N8N:5678 | OpsoraProxy:8080           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Local AI: Ollama (7 models, 37GB)                    │   │
│  │  NVIDIA API: Llama-3.1-70B (✓ working)               │   │
│  │  Kimchi CLI: v0.1.72                                  │   │
│  │  47 Skills installed                                  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  AWS: 6 instances | 11 S3 buckets | Bedrock proxy    │   │
│  │  3 valid AWS profiles | 1 SSM online (Windows)       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

         │ SSM                    │ RDP/Guacamole
         ▼                        ▼
┌────────────────────┐    ┌────────────────────┐
│ rdp-windows-prod   │    │ 4 Stopped Instances │
│ us-west-2          │    │ us-east-1           │
│ m5zn.2xlarge       │    │ • pw-agent-vps      │
│ Playwright ✓       │    │ • cloudpc-ec2-win   │
│ Node.js v24 ✓      │    │ • my-termux-vm      │
│ Chrome ✓           │    │ • opsora-model-vps  │
│ SSM Online ✓       │    │                     │
└────────────────────┘    └────────────────────┘
```

---

## 🤖 AI Providers

### Working (✓)

| Provider | Model | Endpoint | Status |
|----------|-------|----------|--------|
| **NVIDIA** | llama-3.1-70b-instruct | integrate.api.nvidia.com | ✅ Verified |
| **Ollama Local** | 7 models (37GB total) | localhost:11434 | ✅ Running |

### Ollama Models Available

| Model | Size | Type |
|-------|------|------|
| qwen2.5-coder:32b | 18.5 GB | Code generation |
| llama3.1:latest | 4.6 GB | General purpose |
| llama3.1:8b | 4.6 GB | General purpose |
| llama3:latest | 4.3 GB | General purpose |
| qwen3.5:4b | 3.2 GB | Fast responses |
| phi3:latest | 2.0 GB | Lightweight |
| nomic-embed-text:latest | 0.3 GB | Embeddings |

### Expired/Invalid (✗)

| Provider | Reason |
|----------|--------|
| Alibaba DashScope (3 keys) | 401 Invalid API key |
| OpenAI | Using wrong key (DashScope key) |
| Model Studio Beijing | 401 Invalid |
| Model Studio Singapore | 403 Access denied |

### Keys in Qwen Settings (untested)

| Key | Provider | Base URL |
|-----|----------|----------|
| DEEPSEEK_API_KEY | DeepSeek | api.deepseek.com |
| XAI_API_KEY | Groq | api.groq.com |
| OPENROUTER_API_KEY | OpenRouter | openrouter.ai |
| ZAI_API_KEY | ZhipuAI | open.bigmodel.cn |
| MINIMAX_API_KEY | MiniMax | api.minimax.chat |
| DASHSCOPE_API_KEY (new) | DashScope Intl | dashscope-intl.aliyuncs.com |

---

## ☁️ AWS Infrastructure

### EC2 Instances (6 total)

| Instance | Type | Region | State | IP | Role |
|----------|------|--------|-------|----|------|
| **opsora-brain** | r5.2xlarge | us-east-1 | 🟢 Running | 98.94.100.100 | Central AI hub (THIS machine) |
| **rdp-windows-prod** | m5zn.2xlarge | us-west-2 | 🟢 Running | 35.166.137.207 | Windows workhorse + SSM |
| pw-agent-vps | m7i-flex.large | us-east-1 | 🔴 Stopped | 54.81.31.132 | Agent VPS |
| cloudpc-ec2-win | m5.xlarge | us-east-1 | 🔴 Stopped | 34.224.16.68 | Cloud PC |
| opsora-model-vps | m7i-flex.large | us-east-1 | 🔴 Stopped | — | Model serving |
| my-termux-vm | t3.micro | us-east-1 | 🔴 Stopped | — | Termux VM |

### S3 Buckets (11)

| Bucket | Purpose |
|--------|---------|
| opsora-production-artifacts-134748917746 | Production artifacts |
| opsora-enterprise-knowledge-base-1784255405 | Knowledge base |
| opsora-agent-screenshots | Agent screenshot exchange (NEW) |
| opsora-backups-134748917746 | Backups |
| config-bucket-134748917746 | Config |
| sagemaker-us-east-1-134748917746 | SageMaker |
| sagemaker-studio-cyczp0dhvel | SageMaker Studio |
| dprd-live-1784309026 | DPRD bot |
| pw-agent-evidence-134748917746-us-east-1 | Agent evidence |
| aws-sam-cli-managed-default | SAM deployments |

### AWS Profiles

| Profile | User | Status |
|---------|------|--------|
| default | jalankecil351 | ✅ Valid |
| cladius | vps-operator | ✅ Valid |
| kimchi-bedrock | kimchi-bedrock-user | ✅ Valid (Bedrock only) |
| root1 | — | ❌ Expired |
| root2 | — | ❌ Expired |
| opsora_2 | — | ❌ Expired |

---

## 🐳 Docker Infrastructure

### Running Containers

| Container | Status | Port | Purpose |
|-----------|--------|------|---------|
| guacamole | ✅ Running | 8888 | Browser-based RDP to Windows |
| guacd | ✅ Running | 4822 | RDP protocol daemon |
| opsora-postgres | ✅ Running | — | Opsora database |
| opsora-qdrant | ✅ Running | 6333 | Vector DB for embeddings |
| opsora-n8n | ✅ Running | 5678 | Workflow automation |
| opsora-webui | ✅ Running | 3000 | Open WebUI (AI chat) |
| opsora-ollama | ✅ Running | 11434 | Ollama AI server |
| constituent-dashboard | ✅ Running | 8000 | Constituency dashboard |

### Access URLs

| Service | URL |
|---------|-----|
| Guacamole RDP | http://localhost:8888/guacamole |
| Open WebUI | http://localhost:3000 |
| N8N Workflows | http://localhost:5678 |
| Dashboard | http://localhost:8000 |
| Qdrant | http://localhost:6333 |
| Opsora Proxy | http://localhost:8080 |

---

## 🛠️ Tools & CLI Built Today

### Opsora CLI v2 (Codex/Cursor Edition)
```bash
opsora              # Launch interactive Codex-style CLI
opsora2             # Same (alias)
```
- 8 tools: memory, graphify, file ops, shell, AWS
- Auto model routing (code→qwen-plus, quick→qwen-turbo)
- YOLO mode enabled

### Instance Command Center
```bash
instances           # Show all instances with data
instances-list      # Quick instance list
win-agent "<task>"  # Autonomous browser agent on Windows
```

### Windows Agent (OpenClaw-style)
```bash
win-agent "Check Gmail for unread emails"
win-agent "Go to outlook.com and summarize latest emails"
```
- Uses SSM → PowerShell → Playwright (headless browser)
- NVIDIA Llama-3.1-70B as brain
- Supports: open_url, navigate, click, type, fill, get_page_text

### Gmail Access Scripts
```bash
python3 ~/opsora-cli/cmd/opsora_windows_agent_v2.py "Open Gmail..."
python3 ~/opsora-cli/cmd/opsora_windows_agent_v3.py  # Diagnostic
```

---

## 🔌 MCP & Skills

### MCP Servers Configured
| Server | Command | Purpose |
|--------|---------|---------|
| graphify | `graphify --mcp` | Knowledge graph queries |

### Codex Skills (47 installed)

**AI/LLM:** token-optimizer, speech, transcribe, multi-agent-orchestration, openai-docs
**Design:** figma (7 skills), figma-code-connect, figma-generate-design
**Deployment:** cloudflare-deploy, render-deploy, netlify-deploy, vercel-deploy, hatch-pet
**Development:** cli-creator, playwright, playwright-interactive, screenshot, jupyter-notebook, aspnet-core, winui-app, migrate-to-codex, yeet
**Security:** security-best-practices, security-ownership-map, security-threat-model
**Collaboration:** linear, sentry, chatgpt-apps
**Notion:** knowledge-capture, meeting-intelligence, research-documentation, spec-to-implementation
**Operations:** opsora-operations, gh-address-comments, gh-fix-ci, define-goal

### AI Coding Tools Installed
| Tool | Version | Status |
|------|---------|--------|
| Qwen Code | Latest | ✅ Active (this session) |
| Kimchi CLI | 0.1.72 | ✅ Installed |
| Codex (OpenAI) | Latest | ✅ Configured |
| Gemini CLI | Latest | ✅ Installed (snap) |
| OpenCode | Latest | ✅ Installed |
| Continue IDE | Latest | ✅ Configured |
| Aider | Latest | ✅ Installed |

---

## 📊 System Services

| Service | Status | Purpose |
|---------|--------|---------|
| opsora-proxy | ✅ Running | Bedrock Mantle Proxy |
| docker | ✅ Running | Container runtime |
| containerd | ✅ Running | Container management |
| libvirtd | ✅ Running | VM management |
| cron | ✅ Running | Scheduled tasks |
| chrony | ✅ Running | NTP time sync |

---

## 🧹 Cleanup Done

| Action | Space Reclaimed |
|--------|----------------|
| __pycache__ removed | 20KB |
| agent_base.pyo/pyxY deleted | 3KB |
| accept: empty file deleted | 0B |
| snap/llama + snap/ollama removed | 24KB |
| Project __pycache__ cleaned | 48KB |
| Docker images pruned | 700MB |
| Docker build cache pruned | 538MB |
| **Total** | **~1.24GB** |

.gitignore updated to prevent __pycache__, *.pyc, *.pyo from reappearing.

---

## 🔑 Credentials Summary

| Type | Keys | Status |
|------|------|--------|
| NVIDIA API | 1 key | ✅ Working |
| Ollama | No key needed | ✅ Local |
| AWS IAM | 6 profiles (3 valid) | ✅ Partial |
| Alibaba/DashScope | 6 keys | ❌ All expired |
| OpenAI | 1 key (wrong) | ❌ Expired |
| DeepSeek | 1 key | ⏳ Untested |
| Groq/xAI | 1 key | ⏳ Untested |
| OpenRouter | 1 key | ⏳ Untested |
| ZhipuAI | 1 key | ⏳ Untested |
| MiniMax | 1 key | ⏳ Untested |
| Datadog | 1 key | ✅ Configured |
| Kimchi/CAST AI | 1 key | ✅ Configured |
| Aliyun RAM | 1 key pair | ✅ Configured |
| GitHub | Token | ✅ gh 2.96.0 |

---

## ⚡ Quick Start Commands

```bash
# Interactive AI assistant (Codex-style)
opsora

# See all instances
instances

# Autonomous browser agent on Windows
win-agent "Check my Gmail inbox"

# Remote desktop to Windows (browser-based)
# Open http://YOUR_IP:8888/guacamole → guacadmin/guacadmin

# Open WebUI (AI chat with all models)
# Open http://YOUR_IP:3000

# N8N workflow automation
# Open http://YOUR_IP:5678

# Direct AWS commands
aws ec2 describe-instances --profile default
aws s3 ls --profile default

# Git operations
gh pr list
gh repo list Cladius-Weinert
```

---

## 🚧 Action Items (What Needs You)

1. **Rotate expired API keys**: Alibaba DashScope (6 keys), OpenAI
2. **Test additional providers**: DeepSeek, Groq, OpenRouter, ZhipuAI, MiniMax
3. **Rotate expired AWS profiles**: root1, root2, opsora_2
4. **Login Gmail manually** via Guacamole RDP (one-time, then cookies persist)
5. **Start stopped instances** if needed: `instances` → `start pw-agent-vps`

---

**Total resources connected: 6 EC2 instances | 11 S3 buckets | 8 Docker containers | 7 Ollama models | 47 skills | 6+ AI providers | 6 ports active | 10+ tools**

**Workspace: /home/ubuntu (~5.6GB clean)**
**Last updated: 2026-07-20 08:15 UTC**
