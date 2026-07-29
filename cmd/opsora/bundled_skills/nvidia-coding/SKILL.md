---
name: nvidia-coding
description: Best practices for NVIDIA Integrate API coding agents on Termux and CLI
---

# NVIDIA Coding Agent Skill

## API setup
- Base URL: `https://integrate.api.nvidia.com/v1`
- Auth: `Authorization: Bearer $NVIDIA_API_KEY`
- Key format: `nvapi-...` from https://org.ngc.nvidia.com/setup/api-keys

## Verified models (account-dependent)
Prefer models confirmed working before flagship names from docs:
- `meta/llama-3.1-70b-instruct` — balanced daily driver
- `meta/llama-3.1-8b-instruct` — fast / background
- `deepseek-ai/deepseek-v4-pro` — coding & reasoning
- `nvidia/nemotron-3-super-120b-a12b` — flagship when available

## Agent workflow
1. Search memory before large refactors
2. Use tool calling in small steps (rate limit ~40 RPM on trial tier)
3. Cache repeated file reads and memory searches
4. Fall back to DashScope `qwen-plus` when NVIDIA returns 429

## Termux notes
- Install Termux from F-Droid, not Play Store
- Use LiteLLM gateway on `127.0.0.1:4000` for Claude Code compatibility
- Prefer `opsora-model balanced` on phones with limited RAM
