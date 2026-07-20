# Opsora CLI v2 — Codex/Cursor Edition

Terminal-first AI coding assistant dengan tampilan seperti Codex/Cursor, terintegrasi penuh dengan semua resource workspace.

## Quick Start

```bash
# Jalankan interactive mode
opsora

# Direct prompt (non-interactive)
opsora "Jelaskan arsitektur project ini"

# Dengan alias
opsora2
```

## Features

### 🎨 Codex/Cursor-Style UI
- **Header** dengan status semua provider (● ready / ○ offline)
- **Welcome panel** dengan resource summary lengkap
- **Tool calling display** dengan parameter dan output preview
- **Streaming response** dengan Markdown rendering
- **Status bar** dengan model aktif, waktu, dan mode

### 🔌 All Providers Connected
| Provider | Model Default | Status |
|----------|--------------|--------|
| **NVIDIA** | meta/llama-3.1-70b-instruct | ✓ API Key |
| **Alibaba** | qwen-plus, qwen-turbo, qwen-max | ✓ API Key |
| **Model Studio** | qwen-plus, qwen-turbo, qwen-max | ✓ API Key |
| **OpenAI** | gpt-4o, gpt-4o-mini | ✓ API Key |
| **AWS Bedrock** | amazon.nova-pro-v1:0 | ✓ Credentials |
| **Ollama Local** | qwen3.5:4b, llama3.1:latest | Runtime check |

### 🤖 Auto Model Routing
Opsora otomatis memilih model berdasarkan intent prompt:
- **Code/Debug/Fix** → `alibaba:qwen-plus`
- **Quick questions** → `alibaba:qwen-turbo`
- **Complex analysis** → `alibaba:qwen-max`
- **AWS/Terraform** → `bedrock:amazon.nova-pro` (jika available)
- **Default** → First available provider dari `OPSORA_PROVIDER_ORDER`

### 🛠️ Full Tool Integration
| Tool | Type | Description |
|------|------|-------------|
| `memory_add` | Safe | Simpan fakta ke memory persistent |
| `memory_search` | Safe | Cari context di memory |
| `graphify_query` | Safe | Query knowledge graph (49MB graph) |
| `workspace_status` | Safe | Status workspace capabilities |
| `read_file` | Host | Baca file lokal (auto-approve di YOLO mode) |
| `write_file` | Host | Tulis file lokal |
| `run_command` | Host | Eksekusi shell command (YOLO mode) |
| `aws_command` | AWS | Read-only AWS CLI operations |

### ⚡ YOLO Mode
- Commands dieksekusi **tanpa konfirmasi** untuk operasi yang aman
- File reads langsung approved
- Shell commands langsung dijalankan (timeout 120s)
- AWS hanya read-only (get/describe/list/head/scan/query)

### 📋 Commands

```
/help           Show all commands
/status         Show provider & tool status
/models         Show all provider routes
/tools          Show available tools
/model <prov>   Switch provider
/model <p> <m>  Switch to specific model
/clear          Clear screen
/new            New conversation
/agents         List agent files
/aws <args>     Quick AWS read-only command
/run <cmd>      Quick shell command
/read <file>    Quick file read
/graphify <q>   Quick graph query
/memory <q>     Quick memory search
/exit           Exit Opsora
```

## Architecture

```
opsora-cli/
├── cmd/
│   ├── opsora_v2.py      ← Codex/Cursor Edition (NEW)
│   ├── root.py           ← Original v1
│   ├── root_optimized.py ← Optimized v1
│   └── discovery.py      ← Service discovery
├── opsora-v2             ← Launcher script
├── opsora-launcher       ← Legacy launcher
└── opsora_repl.py        ← REPL prototype
```

## Configuration

Environment variables di `~/.opsora_env`:
```bash
# Provider API Keys
NVIDIA_API_KEY=...
DASHSCOPE_API_KEY=...
OPENAI_API_KEY=...

# Provider priority order
OPSORA_PROVIDER_ORDER=nvidia,alibaba,bedrock,local
OPSORA_ALLOW_LOCAL_FALLBACK=true

# AWS
AWS_PROFILE=default
AWS_DEFAULT_REGION=us-east-1
```

## Resources Connected

- **Memory**: 10 entries di `/home/ubuntu/opsora_memory.db`
- **Graphify**: 49MB graph di `/home/ubuntu/opsora/graphify-out/`
- **Agents**: 20+ agent files di workspace
- **Claude**: Claude Code Agent setup di `/home/ubuntu/claude-code-agent/`
- **AWS**: Bedrock, EC2, S3 access via profile
- **Terraform**: Infrastructure as Code
- **Node.js**: v24.18.0 via NVM
- **OpenCode**: CLI tool di `/home/ubuntu/.opencode/bin/`

## Fallback Chain

Ketika primary provider gagal, Opsora otomatis fallback:
1. Primary selection (berdasarkan auto-routing)
2. Provider berikutnya di `OPSORA_PROVIDER_ORDER`
3. Local Ollama (jika `OPSORA_ALLOW_LOCAL_FALLBACK=true`)
4. Error jika semua gagal

## Direct Mode

```bash
# Single query
opsora "Apa itu Graphify?"

# Execute command
opsora "Jalankan df -h dan jelaskan hasilnya"

# Read file
opsora "Baca file /home/ubuntu/opsora-cli/cmd/root.py dan jelaskan strukturnya"
```

## Troubleshooting

### API Keys Invalid/Expired
Update keys di `~/.opsora_env`:
```bash
# Edit file
nano ~/.opsora_env

# Reload
source ~/.bashrc
```

### Ollama Not Running
```bash
# Start Ollama
ollama serve &

# Pull model
ollama pull qwen3.5:4b
```

### AWS Credentials
```bash
# Check credentials
aws sts get-caller_identity --profile default

# Configure
aws configure --profile default
```

---

**Built for**: Ubuntu workspace with multi-provider AI access
**Style**: Codex/Cursor terminal aesthetic
**Mode**: YOLO — execute without confirmation when safe
