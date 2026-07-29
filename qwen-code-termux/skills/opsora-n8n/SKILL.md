---
name: opsora-n8n
description: Safe n8n workflow management — document, backup, create, and modify workflows without exposing credentials or breaking production lead flow.
---

# Skill: n8n Workflow Architect

Manage n8n automation workflows safely. The n8n instance runs as Docker container `opsora-n8n` on the VPS and handles the critical lead flow pipeline.

## When to use

- Creating new n8n workflows
- Modifying existing lead flow workflows
- Debugging workflow failures
- Documenting workflow logic
- Backing up workflow configurations

## Architecture

```
[Landing page POST /api/lead]
    ↓ HTTP + X-Opsora-Token header
[n8n webhook trigger]
    ↓
[AI processing (Ollama qwen2.5:3b)]
    ↓
[CRM logger 127.0.0.1:3010]
    ↓
[Lead saved to NDJSON]
    ↓
[Dashboard notification]
```

## Hard rules

1. **Never expose n8n credentials** — API tokens, webhook URLs, and auth headers stay server-side
2. **Never modify the production lead webhook** without testing on a copy first
3. **Always backup** before modifying — `n8n export:workflow` to JSON
4. **No destructive changes** — don't delete nodes, rename active webhooks, or change auth during production hours
5. **Test with mock data** — use the demo leads in `opsora/demo/sample-leads.json`

## Workflow operations

### List workflows
```bash
# Via n8n API (container must be running)
curl -s http://127.0.0.1:5678/api/v1/workflows \
  -H "X-N8N-API-KEY: $N8N_API_KEY" | jq '.data[].name'
```

### Export (backup) workflow
```bash
# Export single workflow to JSON
curl -s http://127.0.0.1:5678/api/v1/workflows/<id> \
  -H "X-N8N-API-KEY: $N8N_API_KEY" > backup-<name>.json
```

### Import workflow from backup
```bash
curl -X POST http://127.0.0.1:5678/api/v1/workflows \
  -H "X-N8N-API-KEY: $N8N_API_KEY" \
  -H "Content-Type: application/json" \
  -d @backup-<name>.json
```

### Test webhook locally
```bash
# Send test lead to the webhook
curl -X POST http://127.0.0.1:5678/webhook/<path> \
  -H "X-Opsora-Token: $OPSORA_LEAD_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","phone":"08123456789","source":"test"}'
```

## Workflow documentation template

For each workflow, maintain:

```markdown
## Workflow: <name>
- **Trigger:** <webhook/schedule/manual>
- **Input:** <expected payload format>
- **Steps:**
  1. <node> — <what it does>
  2. <node> — <what it does>
- **Output:** <where data goes>
- **Error handling:** <what happens on failure>
- **Last tested:** <date>
- **Backup:** `backups/<name>.json`
```

## Troubleshooting

| Problem | Check | Fix |
|---------|-------|-----|
| Webhook not triggering | Container running? `docker ps \| grep n8n` | `docker restart opsora-n8n` |
| Lead not saving | CRM logger at 3010? | `curl http://127.0.0.1:3010/health` |
| AI draft empty | Ollama running? | `curl http://127.0.0.1:11434/api/tags` |
| Auth failing | Token match? | Compare `OPSORA_LEAD_API_TOKEN` in n8n vs landing |

## Tools used

| Tool | Purpose |
|------|---------|
| `run_command` | Docker commands, n8n API calls, curl tests |
| `read_file` | Read workflow JSON backups, demo data |
| `write_file` | Save workflow backups, documentation |
