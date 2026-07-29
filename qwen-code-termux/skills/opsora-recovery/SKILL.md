---
name: opsora-recovery
description: System recovery after outages — service health checks, Docker/tmux status, tunnel verification, generate recovery report. Run after reboot, deploy failure, or any system issue.
---

# Skill: Recovery Engineer

Diagnose and recover from system outages. Produces a structured health report covering all services, infrastructure, and connectivity — then applies fixes in priority order.

## When to use

- After a VPS reboot or power outage
- When "something is broken" and you need to find what
- After a failed deployment
- Periodic health audit (weekly recommended)
- When the tunnel/dashboard/API is unreachable

## Recovery priority order

Fix in this order — each depends on the previous:

1. **Disk space** — if full, nothing else works
2. **Docker** — containers won't start without Docker daemon
3. **Core services** — API, n8n, Ollama, CRM logger
4. **Web services** — Next.js apps, nginx
5. **Tunnels** — Cloudflare Quick Tunnel (temporary!)
6. **External** — Vercel, Render, DNS

## Execution steps

### 1. Disk space check
```bash
df -h /
# If >90%: clean Docker images, logs, tmp files
docker system prune -f
journalctl --vacuum-size=100M
rm -rf /tmp/opsora-* 2>/dev/null
```

### 2. Docker daemon
```bash
systemctl is-active docker
# If inactive:
systemctl start docker
# Check containers:
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
# Restart unhealthy:
docker restart <container-name>
```

### 3. Core services
```bash
# Check each service
curl -s http://127.0.0.1:8789/health    # OperatorOS API
curl -s http://127.0.0.1:5678            # n8n
curl -s http://127.0.0.1:11434/api/tags  # Ollama
curl -s http://127.0.0.1:3010/health     # CRM logger
curl -s http://127.0.0.1:8790            # Public gateway

# systemd services
systemctl is-active opsora-production
systemctl is-active operatoros-api
systemctl is-active operatoros-web
```

### 4. tmux sessions
```bash
tmux list-sessions 2>/dev/null
# Expected sessions: orchestrator, opsora, tunnel
# Recreate if missing:
tmux new-session -d -s orchestrator "node scripts/opsora-orchestrator.mjs serve"
```

### 5. Tunnel check
```bash
# Cloudflare Quick Tunnel (temporary!)
ps aux | grep cloudflared
# If not running:
cloudflared tunnel --url http://localhost:8790 &
# Note the URL — it changes on every restart!
```

### 6. External services
```bash
# Landing page
curl -s -o /dev/null -w "%{http_code}" https://opsora-landing-zeta.vercel.app

# Agent IDE
curl -s -o /dev/null -w "%{http_code}" https://useopsora.com

# API (if deployed)
curl -s -o /dev/null -w "%{http_code}" https://opsora-agent-api.fly.dev/health
```

## Output format

```
## 🔧 Recovery Report — <timestamp>

### System
- Disk: 45% used (12GB/27GB) ✅
- Memory: 2.1GB/4GB (52%) ✅
- Load: 0.85 ✅
- Uptime: 3 days

### Docker
- opsora-n8n: running (healthy) ✅
- opsora-api: running (healthy) ✅
- opsora-web: running (unhealthy) ⚠️
  → Restarting... ✅ Fixed

### Services
| Service | Port | Status |
|---------|------|--------|
| OperatorOS API | 8789 | ✅ healthy |
| n8n | 5678 | ✅ healthy |
| Ollama | 11434 | ✅ running (2 models) |
| CRM logger | 3010 | ✅ healthy |
| Gateway | 8790 | ✅ healthy |

### tmux
- orchestrator: running ✅
- opsora: NOT FOUND ❌ → Recreated ✅
- tunnel: running ✅

### Tunnel
- URL: https://<random>.trycloudflare.com
- ⚠️ Quick Tunnel — URL changes on restart!

### Actions taken
1. Restarted opsora-web container (was unhealthy)
2. Recreated opsora tmux session

### Remaining issues
- ⚠️ Quick Tunnel URL changed — update webhook config
- ⚠️ No permanent domain configured yet
```

## Tools used

| Tool | Purpose |
|------|---------|
| `run_command` | All system checks, Docker commands, curl health checks |
| `read_file` | Read service configs, systemd unit files |
| `web_fetch` | Check external URL availability |
