---
name: termux-mobile-agent
description: Mobile terminal agent patterns for Android Termux coding workflows
---

# Termux Mobile Agent Skill

## Environment
- Use `pkg update && pkg upgrade` before installing agents
- Keep secrets in `~/.opsora/claude-code/secrets.env` (never commit)
- Use `tmux` for persistent sessions on unstable mobile networks

## Recommended stack
1. `opsora-gateway` — LiteLLM proxy
2. `opsora-claude` or `opsora` CLI — agent interface
3. `opsora-model balanced` — default model profile

## Performance
- Avoid huge model profiles on low-RAM devices
- Enable Opsora context cache to reduce duplicate API calls
- Compress long sessions automatically with `/new` between tasks

## Security
- Rotate API keys if pasted into chat or shared screens
- Block reads of `.ssh`, `.aws`, and `.env` paths
