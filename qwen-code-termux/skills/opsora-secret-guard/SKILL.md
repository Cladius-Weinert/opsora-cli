---
name: opsora-secret-guard
description: Scan code and staged changes for credential leaks — API keys, tokens, passwords, private keys. Run before every commit and when reviewing PRs. Blocks dangerous commits.
---

# Skill: Secret Guardian

Prevent credential leaks by scanning code for secret patterns before they reach git history. This skill enforces the hard rule: **never commit secrets**.

## When to use

- Before committing changes (pre-commit gate)
- When reviewing a PR for security issues
- When editing .env files, config files, or deployment scripts
- When someone pastes an API key in chat — detect and warn

## Secret patterns detected

### API keys and tokens
| Pattern | Example | Provider |
|---------|---------|----------|
| `sk-[a-zA-Z0-9]{20,}` | `sk-proj-abc123...` | OpenAI |
| `nvapi-[a-zA-Z0-9]{20,}` | `nvapi-Zbs5GV...` | NVIDIA |
| `pk_(live\|test)_[a-zA-Z0-9]{20,}` | `pk_live_abc123...` | Stripe |
| `ghp_[a-zA-Z0-9]{36}` | `ghp_abc123...` | GitHub PAT |
| `xox[baprs]-[a-zA-Z0-9-]{10,}` | `xoxb-abc123...` | Slack |
| `AKIA[0-9A-Z]{16}` | `AKIAIOSFODNN7EXAMPLE` | AWS Access Key |
| `flyt_[a-zA-Z0-9]{20,}` | `flyt_abc123...` | Fly.io |
| `opsk-[a-f0-9]{48}` | `opsk-d068e28a...` | Opsora |

### Sensitive files
- `.env`, `.env.local`, `.env.production`
- `*.pem`, `*.key`, `*.p12`, `*.pfx`
- `credentials`, `secrets.json`, `service-account.json`
- `id_rsa`, `id_ed25519`, `*.ssh`

### Embedded secrets in code
- Hardcoded `password = "..."` or `api_key = "..."`
- Bearer tokens in source code
- Connection strings with embedded credentials

## Execution steps

1. **Scan staged files** — `run_command("git diff --cached --name-only")` to get staged files
2. **Filter binary/safe files** — Skip images, compiled assets, lockfiles
3. **Pattern match** — `grep_search` each pattern against staged content
4. **Report findings** — For each match:
   - File path and line number
   - Pattern type (not the actual secret value!)
   - Severity (critical/high/medium)
5. **Block if critical** — If any critical secrets found, recommend:
   - Move to `.env` and add to `.gitignore`
   - Use environment variables in code
   - Use `secrets/` directory (gitignored)

## Hard rules

- **NEVER print actual secret values** in output — show masked version only (`sk-ab...xy12`)
- **NEVER suggest committing .env files** — always .gitignore them
- **Block, don't warn** — if critical secrets are staged, the commit should be prevented
- **Check diffs, not just files** — secrets in deleted lines are still in git history

## Tools used

| Tool | Purpose |
|------|---------|
| `run_command` | Get staged file list via git diff |
| `grep_search` | Pattern match against file contents |
| `read_file` | Read specific files for manual inspection |

## Output format

```
## Secret Scan Results

### 🚨 CRITICAL (blocks commit)
- `src/config.py:42` — OpenAI API key pattern detected
  → Move to environment variable: `os.getenv("OPENAI_API_KEY")`

### ⚠️ WARNING
- `deploy/docker-compose.yml:15` — Possible hardcoded password
  → Use Docker secrets or env_file instead

### ✅ Clean files: 23/25
```

## Integration with git

To use as a pre-commit hook:
```bash
# In .git/hooks/pre-commit
opsora-secret-guard --staged
exit $?
```

## Remediation patterns

| Problem | Fix |
|---------|-----|
| API key in source | `os.getenv("KEY_NAME")` + add to .env |
| Password in config | Use secrets manager or env var |
| .env committed | `git rm --cached .env` + add to .gitignore |
| Key in git history | `git filter-branch` or BFG Repo Cleaner + rotate key |
