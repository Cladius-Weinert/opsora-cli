---
name: opsora-deploy-doctor
description: Diagnose and fix deployment issues across Fly.io, Vercel, Render, Docker, and VPS. Pre-deploy validation, deploy execution, post-deploy health checks, and automatic rollback on failure.
---

# Skill: Deploy Doctor

End-to-end deployment diagnosis and execution. Detects the target platform, validates readiness, executes deployment, verifies health, and rolls back on failure.

## When to use

- Before deploying ("is this ready to deploy?")
- When a deployment fails ("deploy broke, fix it")
- After deploying ("verify the deploy is working")
- Setting up deployment for a new project

## Platform detection

Detect the deployment target from project files:

| File | Platform | Deploy command |
|------|----------|---------------|
| `fly.toml` | Fly.io | `flyctl deploy` |
| `vercel.json` / `.vercel/` | Vercel | `vercel --prod` |
| `render.yaml` | Render | Git push (auto-deploy) |
| `Dockerfile` + `docker-compose.yml` | Docker/VPS | `docker compose up -d` |
| `.github/workflows/deploy*.yml` | GitHub Actions | Git push (CI/CD) |
| `nginx/` + systemd `.service` | Native VPS | `systemctl restart` |

## Pre-deploy checklist

Run ALL of these before deploying:

1. **Build test** — Does the project build without errors?
   - Next.js: `npm run build`
   - Python: `python -m py_compile <main_file>`
   - Docker: `docker build -t test .`

2. **Config validation**
   - Fly.io: validate fly.toml (region, memory, volume)
   - Vercel: validate vercel.json (routes, rewrites)
   - Docker: validate Dockerfile (non-root user, health check)

3. **Environment variables** — Are all required env vars set?
   - Check `.env.example` against deployed environment
   - Flag any missing critical vars

4. **Secret scan** — Run `opsora-secret-guard` first
   - Block deploy if secrets would be exposed

5. **Health endpoint** — Does the app have a `/health` endpoint?
   - If not, recommend adding one

## Deploy execution

### Fly.io
```bash
# Validate
flyctl validate

# Create volume if needed
flyctl volumes create <name> --region <region> --size 1

# Set secrets
flyctl secrets set KEY=value KEY2=value2

# Deploy
flyctl deploy

# Verify
curl -s https://<app>.fly.dev/health
```

### Vercel
```bash
# Preview first
vercel

# Production
vercel --prod

# Verify
curl -s https://<project>.vercel.app/api/health
```

### Docker/VPS
```bash
# Build
docker compose build

# Deploy
docker compose up -d --remove-orphans

# Verify
docker compose ps
curl -s http://localhost:<port>/health
```

## Post-deploy health check

After every deploy:
1. Wait 5-10 seconds for startup
2. Hit the health endpoint (retry 3x with 5s intervals)
3. Check response: HTTP 200 + expected body
4. If failed: read logs, diagnose, report

## Rollback on failure

If health check fails after deploy:
1. **Fly.io:** `flyctl releases` → `flyctl deploy --image <previous>`
2. **Docker:** `docker compose down` → `docker compose up -d` with previous image tag
3. **Vercel:** `vercel rollback` or redeploy previous deployment

## Tools used

| Tool | Purpose |
|------|---------|
| `glob_search` | Detect platform config files |
| `read_file` | Read fly.toml, Dockerfile, vercel.json |
| `run_command` | Execute build, deploy, health check commands |
| `web_fetch` | Hit health endpoint for verification |

## Output format

```
## Deploy Doctor Report

### Platform: Fly.io (detected from fly.toml)
### Region: Singapore (sin)
### Config: 256MB RAM, shared CPU, auto-scaling

### Pre-deploy checks
- ✅ Build: passed
- ✅ Config: valid
- ⚠️ Env vars: NVIDIA_API_KEY not set (will use fallback)
- ✅ Secrets: clean
- ✅ Health endpoint: /health exists

### Deploy
- ✅ flyctl deploy: success (v12, 45s)

### Post-deploy
- ✅ Health check: HTTP 200 (3.2s response time)
- ✅ Models: 7 active
- ✅ Providers: NVIDIA, DashScope connected

### Summary: Deploy successful 🎉
```
