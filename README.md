<p align="center">
  <img src="docs/opsora-logo.png" alt="Opsora" width="200" />
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
  <a href="#installation"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License" /></a>
  <a href="#installation"><img src="https://img.shields.io/badge/pip-install-blue" alt="pip" /></a>
  <img src="https://img.shields.io/badge/providers-7-orange" alt="Providers" />
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey" alt="Platform" />
  <a href="https://github.com/opsora/opsora-cli/stargazers"><img src="https://img.shields.io/github/stars/opsora/opsora-cli?style=social" alt="Stars" /></a>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#features">Features</a> •
  <a href="#comparison">Comparison</a> •
  <a href="#providers">Providers</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#contributing">Contributing</a>
</p>

---

## ✨ Why Opsora?

Most AI coding tools lock you into a single provider. Opsora connects to **seven providers simultaneously** and auto-routes your prompts to the best model based on intent — code questions go to code-optimized models, quick questions go to fast models, and complex analysis goes to flagship models. All from a single terminal prompt.

```
┌──────────────────────────────────────────────────────────┐
│  OPSORA v2.0 — Codex/Cursor Edition                      │
│  ● nvidia  ● alibaba  ● openai  ● bedrock  ● tokenhub   │
│  Python 3.12 | Node v24 | Terraform 1.9                  │
└──────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### One-line Install

```bash
curl -fsSL https://raw.githubusercontent.com/opsora/opsora-cli/main/install.sh | bash
```

### Install with pip

```bash
pip install opsora-cli

# Run
opsora
```

### Docker

```bash
docker run -it --rm \
  -v ~/.opsora_env:/root/.opsora_env:ro \
  ghcr.io/opsora/opsora-cli:latest
```

### Claude Code + NVIDIA (Termux / Android)

Use Claude Code on your phone with NVIDIA full-power models via LiteLLM gateway:

```bash
git clone https://github.com/Cladius-Weinert/opsora-cli.git ~/opsora-cli
bash ~/opsora-cli/claude-code-termux/install-termux.sh
nano ~/.opsora/claude-code/secrets.env   # NVIDIA_API_KEY=nvapi-...
opsora-gateway && opsora-model power && opsora-claude
```

See [`claude-code-termux/README.md`](claude-code-termux/README.md) for model profiles (`power`, `coder`, `reasoning`, `nemotron`, etc.).

### From Source

```bash
git clone https://github.com/opsora/opsora-cli.git
cd opsora-cli
pip install -e .
opsora
```

## Features

### 🎨 Codex/Cursor-Style Terminal UI

A rich terminal interface with real-time provider status, streaming markdown responses, syntax-highlighted code blocks, and a persistent status bar — no browser required.

```
  ⚡ opsora [nvidia:llama-3.1-70b] ❯ explain this architecture
  ⠋ nvidia:meta/llama-3.1-70b-instruct thinking…

  ## Architecture Overview

  The project follows a **modular monolith** pattern with three layers:

  1. **Provider Layer** — abstracts all AI backends behind a unified interface
  2. **Routing Engine** — selects optimal model based on prompt intent
  3. **Tool Layer** — file I/O, shell execution, memory, and knowledge graphs
```

### 🤖 Intelligent Auto-Routing

Opsora analyzes your prompt and routes to the optimal provider and model automatically:

| Prompt Intent | Routed To | Why |
|---|---|---|
| `code`, `function`, `debug`, `fix` | Code-specialized model | Optimized for code generation |
| `what is`, `quick`, `simple` | Fast/cheap model | Low latency, low cost |
| `analyze`, `architecture`, `complex` | Flagship model | Deep reasoning capability |
| `aws`, `terraform`, `ec2` | AWS Bedrock | Cloud-native context |
| Everything else | Your preferred order | Configurable via `OPSORA_PROVIDER_ORDER` |

### 🛠️ Built-in Tools

| Tool | Description |
|---|---|
| `read_file` / `write_file` | Read and write local files with path safety |
| `run_command` | Execute shell commands with timeout protection |
| `memory_add` / `memory_search` | Persistent memory across sessions |
| `graphify_query` | Query local knowledge graphs for project context |
| `aws_command` | Read-only AWS CLI operations (safe by default) |
| `workspace_status` | Inspect workspace capabilities |

### ⚡ YOLO Mode

Enable YOLO mode to auto-execute safe operations without confirmation prompts. File reads, shell commands (with timeout), and read-only AWS operations run immediately.

### 🔄 Automatic Fallback

When your primary provider fails, Opsora cascades through your configured provider order:

```
Primary → Next in OPSORA_PROVIDER_ORDER → Local Ollama → Error
```

No dropped prompts. No manual retries.

### 📋 Slash Commands

```
/help              Show all commands
/status            Provider & tool status
/models            All available provider routes
/model <provider>  Switch active provider
/model <p> <m>     Switch to specific model
/clear             Clear screen
/new               Reset conversation
/agents            List agent files
/aws <args>        Quick AWS read-only command
/run <cmd>         Quick shell command
/read <file>       Quick file read
/graphify <q>      Quick knowledge graph query
/memory <q>        Quick memory search
/exit              Exit Opsora
```

## Comparison

How Opsora stacks up against popular AI coding assistants:

| Feature | Opsora CLI | GitHub Copilot | Cursor | Codex CLI |
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
| **Cost** | Free (BYOK) | $10-39/mo | $20/mo | BYOK |

## Providers

Opsora connects to seven AI providers via OpenAI-compatible APIs:

| Provider | Models | Protocol |
|---|---|---|
| **NVIDIA NIM** | Llama 3.1 70B, Mixtral, CodeLlama | OpenAI-compatible |
| **Alibaba DashScope** | Qwen-Plus, Qwen-Turbo, Qwen-Max | OpenAI-compatible |
| **OpenAI** | GPT-4o, GPT-4o-mini | OpenAI API |
| **AWS Bedrock** | Amazon Nova Pro, Nova Lite | AWS Converse API |
| **Tencent TokenHub** | Hunyuan Hy3, Kimi K3, GLM-5, DeepSeek | OpenAI-compatible |
| **Ollama (local)** | Any local model (Qwen, Llama, etc.) | OpenAI-compatible |
| **Model Studio** | Qwen variants (regional) | OpenAI-compatible |

### Configure Providers

Add your API keys to `~/.opsora_env`:

```bash
# Provider API Keys
NVIDIA_API_KEY=your-key-here
DASHSCOPE_API_KEY=your-key-here
OPENAI_API_KEY=your-key-here
TOKENHUB_API_KEY=your-key-here

# Provider priority order (comma-separated)
OPSORA_PROVIDER_ORDER=nvidia,alibaba,tokenhub,bedrock,openai,local

# Allow fallback to local Ollama
OPSORA_ALLOW_LOCAL_FALLBACK=true

# AWS Bedrock (uses AWS credentials, not API key)
AWS_PROFILE=default
AWS_DEFAULT_REGION=us-east-1

# Custom Ollama URL (optional)
OPSORA_OLLAMA_URL=http://127.0.0.1:11434/v1
```

> **Security:** Never commit your `.opsora_env` file. It is automatically excluded via `.gitignore`.

## Architecture

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
├── cmd/
│   └── opsora_v2.py          # Main CLI application
├── config/                    # Provider & cloud configs
├── scripts/                   # Utility scripts
├── .github/
│   └── ISSUE_TEMPLATE/        # Bug reports & feature requests
├── setup.py                   # Python packaging
├── install.sh                 # One-line installer
├── LICENSE                    # MIT License
├── CONTRIBUTING.md            # Contribution guidelines
└── README.md                  # This file
```

## Screenshots

> **Demo screenshots and GIFs coming soon.** Star the repo to get notified! 🌟

<!-- TODO: Add terminal screenshots/GIFs showing:
  - Interactive mode with auto-routing
  - Tool calling display
  - YOLO mode in action
  - Provider fallback cascade
-->

## Open-Core Model

Opsora CLI is **free and open source** under the MIT license. Use it as-is with your own API keys at no cost.

**Opsora Pro** (coming soon) will add:
- 🏢 Team workspaces & shared memory
- 📊 Usage analytics & cost tracking
- 🔒 SSO & audit logging
- 🌐 Hosted knowledge graph
- ⚡ Priority support

The open-source CLI will always remain fully functional. Pro features are additive.

## Requirements

- **Python** 3.10+
- **OS:** Linux, macOS, or Windows (WSL)
- **Optional:** Ollama for local models, AWS CLI for Bedrock

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup

```bash
git clone https://github.com/opsora/opsora-cli.git
cd opsora-cli
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest tests/
```

## Roadmap

- [ ] Streaming responses (partial implementation)
- [ ] MCP server integration
- [ ] Multi-session support
- [ ] Plugin system for custom tools
- [ ] VS Code extension
- [ ] Web dashboard
- [ ] Opsora Pro — team workspaces

## FAQ

<details>
<summary><strong>Do I need API keys for all providers?</strong></summary>
No. Configure at least one provider and Opsora will use it. More providers = better fallback coverage and model selection.
</details>

<details>
<summary><strong>Can I use Opsora completely offline?</strong></summary>
Yes, with Ollama installed locally. Set <code>OPSORA_PROVIDER_ORDER=local</code> in your <code>~/.opsora_env</code>.
</details>

<details>
<summary><strong>How does auto-routing work?</strong></summary>
Opsora analyzes keywords in your prompt (code, debug, analyze, aws, etc.) and routes to the provider/model best suited for that task type. You can override this anytime with <code>/model &lt;provider&gt;</code>.
</details>

<details>
<summary><strong>Is my code sent to third-party APIs?</strong></summary>
Yes — whichever provider handles your prompt receives the conversation. Use local Ollama for fully private execution.
</details>

<details>
<summary><strong>What is Graphify?</strong></summary>
Graphify is a local knowledge graph tool that indexes your project files into a queryable graph, enabling context-aware AI responses based on your codebase structure.
</details>

## License

[MIT](LICENSE) — free for personal and commercial use.

---

<p align="center">
  <strong>Built with ❤️ for developers who refuse to be locked in.</strong><br/>
  <sub>Star ⭐ this repo if Opsora helps your workflow!</sub>
</p>
