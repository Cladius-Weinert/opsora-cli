<p align="center">
  <img src="https://raw.githubusercontent.com/opsora/opsora-cli/main/docs/opsora-logo.png" alt="Opsora" width="200" />
</p>

<h1 align="center">Opsora CLI</h1>

<p align="center">
  <strong>One terminal. Every AI provider. Zero vendor lock-in.</strong>
</p>

<p align="center">
  A multi-provider AI coding assistant with a Codex/Cursor-style terminal UI —<br/>
  auto-routing, tool calling, memory, and knowledge graphs built in.
</p>

<p align="center">
  <a href="#instalasi"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License" /></a>
  <a href="#instalasi"><img src="https://img.shields.io/badge/pip-install-blue" alt="pip" /></a>
  <img src="https://img.shields.io/badge/providers-7-orange" alt="Providers" />
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey" alt="Platform" />
  <a href="https://github.com/opsora/opsora-cli/stargazers"><img src="https://img.shields.io/github/stars/opsora/opsora-cli?style=social" alt="Stars" /></a>
</p>

<p align="center">
  <a href="#instalasi">Instalasi</a> •
  <a href="#fitur">Fitur</a> •
  <a href="#perbandingan">Perbandingan</a> •
  <a href="#provider">Provider</a> •
  <a href="#arsitektur">Arsitektur</a> •
  <a href="#kontribusi">Kontribusi</a> •
  <a href="#dokumentasi">Dokumentasi</a>
</p>

---

## 🇮🇩 Mengapa Opsora?

Sebagian besar alat AI coding mengunci Anda ke satu provider. Opsora terhubung ke **tujuh provider sekaligus** dan secara otomatis me-rute prompt Anda ke model terbaik berdasarkan intent — pertanyaan kode ke model khusus kode, pertanyaan cepat ke model cepat, dan analisis kompleks ke model flagship. Semua dari satu terminal prompt.

✅ **Open source & MIT licensed** — no vendor lock-in, fully auditable.
✅ **Terminal-native UI** — rich TUI dengan streaming responses, syntax highlighting, dan status bar — no browser needed.
✅ **Built-in tooling** — `read_file`, `write_file`, `run_command`, `memory_search`, `graphify_query`, dan lainnya — semua aman dan permission-aware.
✅ **Automatic fallback** — jika provider utama gagal, Opsora cascade ke provider berikutnya di urutan terkonfigurasi.
✅ **Local-first** — gunakan Ollama untuk eksekusi offline, private sepenuhnya.

```
┌──────────────────────────────────────────────────────────┐
│  OPSORA v3.1 — Codex/Claude Code Edition                 │
│  ● nvidia  ● alibaba  ● openai  ● bedrock  ● tokenhub   │
│  Python 3.12 | Node v24 | Terraform 1.9                  │
└──────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start | Instalasi Cepat

### One-line Install

```bash
curl -fsSL https://raw.githubusercontent.com/opsora/opsora-cli/main/install.sh | bash
```

### Install dengan pip

```bash
pip install opsora-cli

# Jalankan
opsora
```

### Docker

```bash
docker run -it --rm \
  -v ~/.opsora_env:/root/.opsora_env:ro \
  ghcr.io/opsora/opsora-cli:latest
```

### Claude Code + NVIDIA (Termux / Android)

Gunakan Claude Code di HP dengan model full-power NVIDIA via LiteLLM gateway:

```bash
git clone https://github.com/Cladius-Weinert/opsora-cli.git ~/opsora-cli
bash ~/opsora-cli/claude-code-termux/install-termux.sh
nano ~/.opsora/claude-code/secrets.env   # NVIDIA_API_KEY=nvapi-...
opsora-gateway && opsora-model power && opsora-claude
```

Lihat [`claude-code-termux/README.md`](claude-code-termux/README.md) untuk model profiles (`power`, `coder`, `reasoning`, `nemotron`, dll).

### Dari Source

```bash
git clone https://github.com/opsora/opsora-cli.git
cd opsora-cli
pip install -e .
opsora
```

## ✨ Fitur | Features

### 🧠 Problem Solving System | Sistem Pemecahan Masalah

Opsora menyertakan sistem pemecahan masalah 5 langkah yang repeatable:

1. **THINK** — Analisis masalah, constraints, dan konteks (mis. file, error, environment).
2. **PLAN** — Daftar langkah konkret, executable (mis. `glob_search`, `read_file`, `grep_search`).
3. **ACT** — Eksekusi langkah pertama menggunakan tools nyata; kembalikan output mentah.
4. **VERIFY** — Validasi kebenaran, keamanan, dan konsistensi hasil.
5. **REPORT** — Ringkas progress dalam 1–3 kalimat dan nyatakan *next step*.

Sistem ini digunakan otomatis untuk semua task kompleks dan terekspos via `opsora_cmd/problem_solver.py`.

### 🎨 Codex/Cursor-Style Terminal UI

Rich terminal interface dengan real-time provider status, streaming markdown responses, syntax-highlighted code blocks, dan persistent status bar — tanpa browser.

```
  ⚡ opsora [nvidia:llama-3.1-70b] ❯ jelaskan arsitektur ini
  ⠋ nvidia:meta/llama-3.1-70b-instruct thinking…

  ## Architecture Overview

  Project ini mengikuti pola **modular monolith** dengan tiga layer:

  1. **Provider Layer** — mengabstraksi semua AI backend behind unified interface
  2. **Routing Engine** — memilih model optimal berdasarkan prompt intent
  3. **Tool Layer** — file I/O, shell execution, memory, dan knowledge graphs
```

### 🤖 Intelligent Auto-Routing | Auto-Routing Cerdas

Opsora menganalisis prompt Anda dan me-rute ke provider/model optimal otomatis:

| Prompt Intent | Di-rute Ke | Alasan |
|---|---|---|
| `code`, `function`, `debug`, `fix` | Model khusus kode | Dioptimalkan untuk code generation |
| `what is`, `quick`, `simple` | Model cepat/murah | Low latency, low cost |
| `analyze`, `architecture`, `complex` | Model flagship | Kemampuan deep reasoning |
| `aws`, `terraform`, `ec2` | AWS Bedrock | Cloud-native context |
| Lainnya | Urutan preferensi Anda | Konfigurasi via `OPSORA_PROVIDER_ORDER` |

### 🛠️ Built-in Tools | Tools Bawaan

| Tool | Deskripsi |
|---|---|
| `read_file` / `write_file` | Baca/tulis file lokal dengan path safety |
| `run_command` | Eksekusi shell command dengan timeout protection |
| `memory_add` / `memory_search` | Persistent memory across sessions |
| `graphify_query` | Query local knowledge graphs untuk project context |
| `aws_command` | Read-only AWS CLI operations (safe by default) |
| `workspace_status` | Inspect workspace capabilities |

### ⚡ YOLO Mode

Enable YOLO mode untuk auto-execute operasi aman tanpa konfirmasi prompt. File reads, shell commands (dengan timeout), dan read-only AWS operations jalan langsung.

### 🔄 Automatic Fallback

Ketika provider utama gagal, Opsora cascade melalui urutan provider terkonfigurasi:

```
Primary → Next in OPSORA_PROVIDER_ORDER → Local Ollama → Error
```

No dropped prompts. No manual retries.

### 📋 Slash Commands

```
/help              Tampilkan semua command
/status            Provider & tool status
/models            Semua provider routes yang tersedia
/model <provider>  Ganti active provider
/model <p> <m>     Ganti ke model spesifik
/clear             Clear screen
/new               Reset percakapan
/agents            List agent files
/aws <args>        Quick AWS read-only command
/run <cmd>         Quick shell command
/read <file>       Quick file read
/graphify <q>      Quick knowledge graph query
/memory <q>        Quick memory search
/exit              Keluar dari Opsora
```

## 📊 Perbandingan | Comparison

Bagaimana Opsora berbanding dengan AI coding assistant populer:

| Fitur | Opsora CLI | GitHub Copilot | Cursor | Codex CLI |
|---|:---:|:---:|:---:|:---:|
| **Multi-provider** | ✅ 7 providers | ❌ OpenAI only | ⚠️ 2-3 | ❌ OpenAI only |
| **Auto model routing** | ✅ Intent-based | ❌ | ❌ | ❌ |
| **Terminal-native UI** | ✅ Rich TUI | Plugin only | VS Code fork | ✅ Basic |
| **Tool calling** | ✅ 8 built-in tools | Limited | ✅ | ✅ |
| **Persistent memory** | ✅ Built-in | ❌ | ❌ | ❌ |
| **Knowledge graph** | ✅ Graphify | ❌ | ❌ | ❌ |
| **Automatic fallback** | ✅ Provider cascade | ❌ | ❌ | ❌ |
| **Local/offline support** | ✅ Ollama | ❌ | ❌ | ❌ |
| **Self-hosted** | ✅ | ❌ | ❌ | ⚠️ |
| **Open source** | ✅ MIT | ❌ | ❌ | ✅ MIT |
| **Vendor lock-in** | None | High | High | High |
| **Biaya** | Free (BYOK) | $10-39/mo | $20/mo | BYOK |

## 🔌 Provider | Providers

Opsora terhubung ke tujuh AI provider via OpenAI-compatible APIs:

| Provider | Models | Protocol |
|---|---|---|
| **NVIDIA NIM** | Llama 3.1 70B, Mixtral, CodeLlama | OpenAI-compatible |
| **Alibaba DashScope** | Qwen-Plus, Qwen-Turbo, Qwen-Max | OpenAI-compatible |
| **OpenAI** | GPT-4o, GPT-4o-mini | OpenAI API |
| **AWS Bedrock** | Amazon Nova Pro, Nova Lite | AWS Converse API |
| **Tencent TokenHub** | Hunyuan Hy3, Kimi K3, GLM-5, DeepSeek | OpenAI-compatible |
| **Ollama (local)** | Any local model (Qwen, Llama, dll.) | OpenAI-compatible |
| **Model Studio** | Qwen variants (regional) | OpenAI-compatible |

### Konfigurasi Provider

Tambahkan API keys ke `~/.opsora_env`:

```bash
# Provider API Keys
NVIDIA_API_KEY=your-key-here
DASHSCOPE_API_KEY=your-key-here
OPENAI_API_KEY=your-key-here
TOKENHUB_API_KEY=your-key-here

# Provider priority order (comma-separated)
OPSORA_PROVIDER_ORDER=nvidia,alibaba,tokenhub,bedrock,openai,local

# Allow fallback ke local Ollama
OPSORA_ALLOW_LOCAL_FALLBACK=true

# AWS Bedrock (menggunakan AWS credentials, bukan API key)
AWS_PROFILE=default
AWS_DEFAULT_REGION=us-east-1

# Custom Ollama URL (optional)
OPSORA_OLLAMA_URL=http://127.0.0.1:11434/v1
```

> **Security:** Jangan pernah commit file `.opsora_env`. File ini otomatis dikecualikan via `.gitignore`.

## 🏗️ Arsitektur | Architecture

```
                    ┌─────────────────────────┐
                    │      Opsora CLI          │
                    │   (Terminal UI / REPL)    │
                    └──────────┬──────────────┘
                               │
                    ┌──────────▼──────────────┐
                    │    Auto-Routing Engine    │
                    │  (Intent Classification)  │
                    └──────────┬──────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────▼───────┐ ┌─────▼──────┐ ┌───────▼───────┐
     │  NVIDIA NIM    │ │  Alibaba   │ │  TokenHub     │
     │  Llama 3.1 70B │ │  Qwen Plus │ │  Hunyuan/Kimi │
     └────────────────┘ └────────────┘ └───────────────┘
              │                │                │
     ┌────────▼───────┐ ┌─────▼──────┐ ┌───────▼───────┐
     │  OpenAI        │ │  Bedrock   │ │  Ollama       │
     │  GPT-4o        │ │  Nova Pro  │ │  Local Models │
     └────────────────┘ └────────────┘ └───────────────┘

                    ┌─────────────────────────┐
                    │       Tool Layer         │
                    ├─────────────────────────┤
                    │  • File I/O             │
                    │  • Shell Execution       │
                    │  • Memory (persistent)   │
                    │  • Graphify (knowledge)  │
                    │  • AWS CLI (read-only)   │
                    │  • Workspace Status      │
                    └─────────────────────────┘

                    ┌─────────────────────────┐
                    │    Fallback Cascade      │
                    │  Primary → Next → ... →  │
                    │  Ollama → Error          │
                    └─────────────────────────┘
```

### Project Structure

```
opsora-cli/
├── opsora_cmd/
│   ├── opsora_v2.py          # Main CLI application
│   ├── opsora_routing.py     # Intent router & model selection
│   ├── opsora_mcp.py         # MCP client integration
│   ├── opsora_agent.py       # Autonomous agent loop
│   ├── opsora_session.py     # Session persistence (SQLite)
│   ├── opsora_memory.py      # Persistent memory (SQLite)
│   ├── opsora_tools.py       # Workspace tools & graphify
│   ├── opsora_tui.py         # Terminal UI components
│   ├── opsora_plugins.py     # Plugin system
│   ├── opsora_graph_v2.py    # Knowledge graph (FTS5 + edges)
│   ├── opsora_cost.py        # Cost tracking
│   ├── opsora_themes.py      # Theme system
│   ├── opsora_compression.py # Context compression
│   ├── opsora_new_tools.py   # Extended toolset
│   ├── opsora_reflect_v2.py  # Self-reflection
│   ├── opsora_subagent.py    # Sub-agent orchestration
│   ├── opsora_streaming.py   # Streaming responses
│   ├── openai_lite.py        # Lightweight OpenAI client
│   ├── problem_solver.py     # 5-step problem solving
│   └── *.py                  # Provider-specific modules
├── config/                    # Provider & cloud configs
├── scripts/                   # Utility scripts
├── marketing_hub/             # Social media automation
├── .github/
│   └── ISSUE_TEMPLATE/        # Bug reports & feature requests
├── setup.py                   # Python packaging
├── install.sh                 # One-line installer
├── LICENSE                    # MIT License
├── CONTRIBUTING.md            # Contribution guidelines
├── ARCHITECTURE.md            # System architecture docs
├── DEPLOYMENT.md              # Deployment guides
├── PROVIDERS.md               # Provider configurations
├── MCP_SERVERS.md             # MCP server documentation
├── EXTENSIONS.md              # Extensions documentation
├── TROUBLESHOOTING.md         # Common issues & solutions
└── README.md                  # This file
```

## 📸 Screenshots

> **Demo screenshots dan GIFs coming soon.** Star repo untuk notifikasi! 🌟

<!-- TODO: Add terminal screenshots/GIFs showing:
  - Interactive mode dengan auto-routing
  - Tool calling display
  - YOLO mode in action
  - Provider fallback cascade
-->

## 🎯 Open-Core Model

Opsora CLI **gratis dan open source** di bawah lisensi MIT. Gunakan se-adanya dengan API keys sendiri tanpa biaya.

**Opsora Pro** (coming soon) akan menambah:
- 🏢 Team workspaces & shared memory
- 📊 Usage analytics & cost tracking
- 🔒 SSO & audit logging
- 🌐 Hosted knowledge graph
- ⚡ Priority support

Open-source CLI akan selalu tetap fully functional. Pro features bersifat additive.

## 📋 Requirements

- **Python** 3.10+
- **OS:** Linux, macOS, atau Windows (WSL)
- **Optional:** Ollama untuk local models, AWS CLI untuk Bedrock

## 🤝 Kontribusi | Contributing

Kami welcome contributions! Lihat [CONTRIBUTING.md](CONTRIBUTING.md) untuk guidelines.

### Development Setup

```bash
git clone https://github.com/opsora/opsora-cli.git
cd opsora-cli
pip install -e ".[dev]"
```

### Menjalankan Tests

```bash
pytest tests/
```

## 🗺️ Roadmap

- [ ] Streaming responses (partial implementation)
- [ ] MCP server integration
- [ ] Multi-session support
- [ ] Plugin system untuk custom tools
- [ ] VS Code extension
- [ ] Web dashboard
- [ ] Opsora Pro — team workspaces

## ❓ FAQ

<details>
<summary><strong>Apakah saya butuh API keys untuk semua provider?</strong></summary>
Tidak. Konfigurasi minimal satu provider dan Opsora akan menggunakannya. Lebih banyak provider = coverage fallback lebih baik dan model selection lebih optimal.
</details>

<details>
<summary><strong>Bisakah saya gunakan Opsora sepenuhnya offline?</strong></summary>
Ya, dengan Ollama terinstall lokal. Set <code>OPSORA_PROVIDER_ORDER=local</code> di <code>~/.opsora_env</code> Anda.
</details>

<details>
<summary><strong>Bagaimana auto-routing bekerja?</strong></summary>
Opsora menganalisis keyword di prompt Anda (code, debug, analyze, aws, dll.) dan me-rute ke provider/model yang paling cocok untuk task type tersebut. Anda bisa override kapan saja dengan <code>/model <provider></code>.
</details>

<details>
<summary><strong>Apakah kode saya dikirim ke third-party APIs?</strong></summary>
Ya — provider manapun yang handle prompt Anda menerima percakapan. Gunakan local Ollama untuk eksekusi fully private.
</details>

<details>
<summary><strong>Apa itu Graphify?</strong></summary>
Graphify adalah tool knowledge graph lokal yang mengindeks file project Anda ke graph yang bisa di-query, memungkinkan AI responses yang context-aware berdasarkan struktur codebase Anda.
</details>

## 📄 License

[MIT](LICENSE) — gratis untuk penggunaan personal dan komersial.

---

<p align="center">
  <strong>Dibangun dengan ❤️ untuk developer yang menolak vendor lock-in.</strong><br/>
  <sub>Star ⭐ repo ini jika Opsora membantu workflow Anda!</sub>
</p>

---

## 📚 Dokumentasi Lengkap | Full Documentation

| Dokumentasi | Deskripsi |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture, data flow, component diagrams |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deployment guides untuk Fly.io, Render, Vercel, Docker |
| [PROVIDERS.md](PROVIDERS.md) | Semua provider configurations, model lists, routing rules |
| [MCP_SERVERS.md](MCP_SERVERS.md) | Semua 12 MCP servers, setup, usage, troubleshooting |
| [EXTENSIONS.md](EXTENSIONS.md) | Semua 7 extensions, agents, skills, commands |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common issues dan solutions |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guidelines, code style, PR process |

## 🔗 Links

- **GitHub:** https://github.com/opsora/opsora-cli
- **Documentation:** https://docs.opsora.dev
- **Discord:** https://discord.gg/opsora
- **Twitter:** https://twitter.com/opsora_ai