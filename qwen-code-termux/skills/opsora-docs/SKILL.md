---
name: opsora-docs
description: Automatic documentation generation and maintenance — architecture docs, API references, changelogs, runbooks, README updates. Keeps docs in sync with code changes.
---

# Skill: Documentation Keeper

Every meaningful code change deserves updated documentation. This skill auto-generates and maintains documentation across all Opsora repos.

## When to use

- After implementing a new feature
- After changing API endpoints or configurations
- After fixing a bug (update runbooks)
- Before a PR — ensure docs are current
- When someone asks "how does X work?" and no docs exist

## Documentation types

### 1. Architecture docs
Auto-generate from code structure:
```markdown
# Architecture: <component>

## Overview
<2-3 sentences from README or CODEX_OPSORA_BRAIN>

## Components
| Component | File | Purpose |
|-----------|------|---------|
<extracted from directory structure + key files>

## Data Flow
<extracted from route handlers + service calls>

## External Dependencies
<extracted from package.json + env vars>
```

### 2. API reference
Auto-generate from route definitions:
```markdown
# API Reference: <service>

## Endpoints

### GET /health
- **Auth:** None
- **Response:** `{status, service, models, total_requests}`

### POST /v1/chat/completions
- **Auth:** Bearer token
- **Body:** `{model, messages, stream?}`
- **Response:** OpenAI-compatible chat completion
```

### 3. Changelogs
Generated from git commits since last tag:
```markdown
# Changelog

## Unreleased
### Added
- <new features from commit messages>
### Fixed
- <bug fixes from commit messages>
### Changed
- <modifications from commit messages>
```

### 4. Runbooks
Generated from recovery patterns:
```markdown
# Runbook: <scenario>

## Symptoms
<what the user sees>

## Diagnosis
<commands to run to identify the issue>

## Fix
<step-by-step resolution>

## Verification
<how to confirm the fix worked>

## Prevention
<how to avoid this in the future>
```

### 5. README updates
When code changes make README inaccurate:
- Update installation instructions
- Update feature lists
- Update configuration examples
- Update deployment instructions

## Documentation locations per repo

| Repo | Key doc files |
|------|--------------|
| opsora | `docs/*.md`, `CODEX_OPSORA_BRAIN.md`, `README.md` |
| opsora-landing | `AGENTS.md`, `README.md` |
| opsora-dashboard | `README.md` |
| opsora-cli | `README.md`, `README-v2.md` |
| opsora-agent-api | `README.md`, `docs.html` |
| memori-agent-dashboard | `README.md` |

## Conventions

- **Language:** Technical docs in English, business/outreach docs in Bahasa Indonesia
- **Format:** GitHub-flavored Markdown
- **Frontmatter:** None (keep it simple)
- **Diagrams:** Mermaid syntax when needed
- **Secrets:** Variable names only, NEVER actual values
- **Links:** Relative paths within repo

## Auto-update triggers

| Code change | Doc to update |
|-------------|---------------|
| New API route | API reference |
| New env var | `.env.example` + docs |
| New model/profile | models.json docs |
| New script | docs/INDEX.md |
| Deploy config change | DEPLOY.md |
| Schema change | Architecture docs |
| New dependency | README install section |

## Tools used

| Tool | Purpose |
|------|---------|
| `glob_search` | Find existing docs, source files |
| `grep_search` | Extract route definitions, env vars, config |
| `read_file` | Read source files, existing docs |
| `edit_file` | Update existing documentation |
| `write_file` | Create new documentation |
| `run_command` | `git log` for changelog generation |
