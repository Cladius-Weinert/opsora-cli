# 🧹 Opsora Workspace Cleanup Audit — 2026-07-20

## Summary
- **Total workspace size**: ~4.2GB (excluding snap, .qwen, .codex)
- **Largest projects**: ai-coding-workspace (608MB), claude-code-agent (602MB), opsora (532MB), god-mode-v4 (502MB)
- **Docker images**: 21.91GB (9 images, 8 active)
- **Build cache**: 1.434GB (538MB reclaimable)

## ✅ SAFE TO DELETE (Confirmed Garbage)

### Root-level junk files (20KB total)
| File | Size | Reason |
|------|------|--------|
| `/home/ubuntu/__pycache__/` | 20KB | Root-level Python cache, 3 .pyc files |
| `/home/ubuntu/agent_base.pyo` | 1.5KB | Compiled Python, superseded by .py |
| `/home/ubuntu/agent_base.pyxY` | 1.6KB | Typo/corrupted filename, not valid extension |
| `/home/ubuntu/accept:` | 0B | Empty file with colon in name |

### Empty directories (24KB total)
| Directory | Size | Reason |
|-----------|------|--------|
| `/home/ubuntu/snap/llama/` | 12KB | Empty, no content |
| `/home/ubuntu/snap/ollama/` | 12KB | Empty, no content |

### Python cache directories (regenerable)
| Directory | Size | Reason |
|-----------|------|--------|
| `/home/ubuntu/opsora/__pycache__/` | ~20KB | Auto-generated, regenerable |
| `/home/ubuntu/opsora_updates/__pycache__/` | ~20KB | Auto-generated, regenerable |
| `/home/ubuntu/opsora-agents/__pycache__/` | ~8KB | Single .pyc file |

### Docker cleanup (reclaimable)
| Item | Size | Reason |
|------|------|--------|
| Unused CUDA images (x2) | 700MB | Not actively used |
| python:3.9-slim | 185MB | Not referenced by active containers |
| Build cache | 538MB | Old build artifacts |
| Unused volumes | 1.117GB | Orphaned volumes |

**Total reclaimable from Docker**: ~2.54GB

## ⚠️ REVIEW BEFORE DELETE (Not automatically garbage)

| Item | Size | Notes |
|------|------|-------|
| `/home/ubuntu/graphify-out/` | 126MB | Cached analysis output, regenerable but takes time |
| `/home/ubuntu/opsora_updates/` | 76KB | Appears to be an update staging area, has actual code |
| `/home/ubuntu/super_agent_hub/` | 68KB | Agent hub with app.py and templates |
| `/home/ubuntu/constituent-dashboard/` | 56KB | Docker-based dashboard project |
| `/home/ubuntu/opsora-dprd-bot/` | 40KB | DPRD bot with docker, docs, infrastructure, src |
| `/home/ubuntu/snap/gemini-cli/` | 264MB | Gemini CLI session data and cached tools |
| `/home/ubuntu/snap/codex/` | 2.8MB | Codex session history and logs |
| `/home/ubuntu/.aider*` | ~90KB | Aider chat history, input history, tag caches |
| Expired AWS profiles (root1, root2, opsora_2) | N/A | Credentials need rotation, not deletion |

## 🔒 DO NOT DELETE (Important)

| Item | Size | Reason |
|------|------|--------|
| `/home/ubuntu/opsora/` | 532MB | Main Opsora project — agents, core, infra, SAM |
| `/home/ubuntu/opsora-cli/` | 212KB | CLI v2 + Command Center — primary tool |
| `/home/ubuntu/opsora-web/` | 84KB | Flask web server + UI |
| `/home/ubuntu/opsora-agents/` | 274MB | Agent harness, Ollama integration, bootstrap |
| `/home/ubuntu/claude-code-agent/` | 602MB | Claude client with web interface |
| `/home/ubuntu/ai-coding-workspace/` | 608MB | Coding workspace with projects |
| `/home/ubuntu/god-mode-v4/` | 502MB | Autonomous terminal agent |
| `/home/ubuntu/gpt-pilot/` | 453MB | GPT-Pilot clone |
| `/home/ubuntu/bedrock-agent/` | 474MB | Bedrock agent with web UI |
| `/home/ubuntu/aws/` | 269MB | AWS CLI v2 installation |
| `/home/ubuntu/tools/` | 75MB | Bedrock agent tools |
| `/home/ubuntu/amazon-q-env/` | 19MB | Amazon Q virtual environment |
| `/home/ubuntu/ngc/` | 121MB | NVIDIA NGC CLI |
| `/home/ubuntu/graphify-out/.graphify_*.json` | ~15MB | Graphify analysis cache (part of larger dir) |
| `/home/ubuntu/agent*.py` (4 files) | ~47KB | Main agent implementations |
| `/home/ubuntu/opsora_memory.py` | 5.7KB | SQLite memory module |
| `/home/ubuntu/opsora_tools.py` | 1.7KB | Safe tools module |
| `/home/ubuntu/.opsora_env` | ~1KB | API keys — CRITICAL |
| `/home/ubuntu/.bashrc` | ~5KB | Shell config with aliases |
| `/home/ubuntu/model-studio.env` | ~1KB | Model Studio credentials — CRITICAL |
| `/home/ubuntu/.aws/credentials` | ~1KB | AWS credentials — CRITICAL |
| `/home/ubuntu/.aws/config` | ~1KB | AWS profiles — CRITICAL |
| `/home/ubuntu/.aliyun/config.json` | ~1KB | Alibaba Cloud config — CRITICAL |
| `/home/ubuntu/.qwen/` | ~120KB | Qwen Code sessions and memory |
| `/home/ubuntu/.codex/` | ~50MB | Codex config and skills |
| `/home/ubuntu/.kimchi/` | ~1MB | Kimchi CLI config |
| `/home/ubuntu/.opencode/` | ~100KB | OpenCode config |
| `/home/ubuntu/.continue/` | ~10KB | Continue IDE config |
| Docker containers (4 running) | 90MB | constituent-dashboard, opsora-webui, etc. |

## Action Plan

### Phase 1: Safe cleanup (immediate, ~2.6GB reclaimed)
1. Delete root __pycache__ and junk files
2. Delete empty snap directories
3. Docker prune (unused images, cache, volumes)

### Phase 2: Optional cleanup (~126MB)
4. Archive graphify-out if not needed for active debugging
5. Review super_agent_hub, constituent-dashboard, opsora-dprd-bot

### Phase 3: Key rotation (security)
6. Rotate expired AWS profile keys (root1, root2, opsora_2)
7. Verify all API keys still valid
