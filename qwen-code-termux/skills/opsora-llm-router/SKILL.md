---
name: opsora-llm-router
description: Optimize LLM costs and performance — route tasks to the cheapest viable model, manage free tiers, balance RPM across providers, and configure fallback chains.
---

# Skill: LLM Cost Optimizer

Route every task to the cheapest model that can handle it well. This skill manages the multi-provider routing matrix across 7 providers and 10+ model profiles.

## When to use

- Choosing which model to use for a task
- Debugging why a model is slow or returning 503/429
- Optimizing API costs across providers
- Setting up model profiles or fallback chains
- Understanding RPM limits and how to work within them

## Provider landscape

| Provider | Best models | Free tier | RPM limit | Latency |
|----------|------------|-----------|-----------|---------|
| **DashScope intl** | qwen3-coder-plus, qwen3.7-max | No (pay-per-use) | ~60 RPM | Low |
| **NVIDIA** | deepseek-v4-flash, nemotron-super-49b | Limited | ~40 RPM | Medium |
| **TokenHub** | hy3, kimi-k3 | 1M tokens each! | ~30 RPM | Low |
| **Alibaba Coding Plan** | qwen3-coder-plus | Weekly quota | ~30 RPM | Low |
| **OpenRouter** | free-tier variants | Free (limited) | Varies | Medium |
| **Ollama** | qwen2.5:3b (local) | Unlimited | Unlimited | Very low |
| **AWS Bedrock** | nova-pro | AWS credits | High | Medium |

## Routing matrix

### By task complexity

| Task | Tier | Recommended model | Fallback |
|------|------|-------------------|----------|
| Simple questions, status checks | **fast** | qwen3-coder-flash | deepseek-v4-flash, llama-3.1-8b |
| Code generation, API routes | **balanced** | qwen3-coder-plus | hy3 (TokenHub), qwen-plus |
| Architecture, debugging, review | **deep** | qwen3.7-max | kimi-k3, nemotron-super-49b |
| Browser automation, GUI | **gui** | computerUse | N/A |

### By cost optimization

| Priority | Use | Why |
|----------|-----|-----|
| 1 | TokenHub free tier (hy3, kimi-k3) | 1M free tokens each, excellent quality |
| 2 | Ollama local (qwen2.5:3b) | Free, unlimited, no latency |
| 3 | DashScope (qwen3-coder-plus) | Best quality/cost for coding, 1M context |
| 4 | NVIDIA (deepseek-v4-flash) | Fast, good for overflow |
| 5 | OpenRouter free variants | Last resort, quality varies |

## RPM management

### Tier concurrency limits

| Tier | Max parallel | Timeout | Use case |
|------|-------------|---------|----------|
| fast | 8 | 60s | Sub-agents, background tasks |
| balanced | 4 | 180s | Default coding |
| deep | 2 | 300s | Reasoning, architecture |

### Fallback chain (when primary fails)

```
503 (Service Unavailable):
  → Switch to fast model immediately
  → Retry original after 30s

429 (Rate Limited):
  → Exponential backoff: 2s, 4s, 8s, 16s, 32s
  → After 3 retries: switch to fallback provider
  → Provider order: dashscope → nvidia → tokenhub → openrouter → local

Connection error:
  → Immediate switch to next provider
  → Log error for monitoring
```

## Model profile switchinging

```bash
# Switch to power profile (qwen3-coder-plus)
opsora-qwen-model power

# Switch to fast profile (sub-agents)
opsora-qwen-model fast

# Switch to NVIDIA coding
opsora-qwen-model nvidia-coder

# Test all profiles
opsora-qwen-test
```

## Cost estimation

| Model | Input ($/1M tokens) | Output ($/1M tokens) | Best for |
|-------|--------------------|--------------------|----------|
| qwen3-coder-flash | $0.10 | $0.20 | Background, sub-agents |
| qwen3-coder-plus | $0.30 | $0.60 | Primary coding |
| qwen3.7-max | $0.50 | $1.20 | Reasoning |
| deepseek-v4-flash | $0.25 | $0.55 | NVIDIA coding |
| nemotron-super-49b | $0.40 | $0.90 | NVIDIA reasoning |
| hy3 (TokenHub) | FREE | FREE | First 1M tokens |

## Tools used

| Tool | Purpose |
|------|---------|
| `read_file` | Read models.json, rpm-config.json, settings.json |
| `run_command` | Test model connectivity, check RPM status |
| `grep_search` | Find model references in codebase |
