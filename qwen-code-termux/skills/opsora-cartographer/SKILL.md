---
name: opsora-cartographer
description: Map any project structure before coding — entry points, routes, dependencies, scripts, and architecture patterns. Run at the start of every new repo or unfamiliar codebase.
---

# Skill: Repo Cartographer

Map the entire project before writing a single line of code. This skill produces a structured understanding of what the project is, how it works, and where to make changes.

## When to use

- First time working in a repository
- Before implementing a feature in an unfamiliar codebase
- When asked "what does this project do?" or "how is this structured?"
- Before debugging — understand the landscape first

## Execution steps

1. **Project identity** — Read the README, package.json/pyproject.toml/go.mod/Cargo.toml to identify:
   - Language, framework, runtime
   - Project name, version, description
   - Entry point (main file, bin, start script)

2. **Directory structure** — Use `glob_search` with `**/*` limited to depth 3 to map the tree:
   ```
   src/ or app/ or lib/ — main source
   tests/ or __tests__/ or test/ — test files
   scripts/ or bin/ — automation
   config/ or .env.example — configuration
   docs/ — documentation
   ```

3. **Route/endpoint discovery** — Use `grep_search` for:
   - `router\.` or `app\.(get|post|put|delete)` (Express/Fastify)
   - `@(app|router)\.(get|post)` (Flask/FastAPI decorators)
   - `def do_GET\|def do_POST` (stdlib HTTP)
   - `page\.tsx\|route\.ts\|route\.tsx` (Next.js app router)

4. **Dependencies** — Count and categorize:
   - Runtime deps (package.json dependencies, requirements.txt)
   - Dev deps (test runners, linters, build tools)
   - External services (env vars referencing APIs, databases, queues)

5. **Scripts and automation** — List all runnable scripts:
   - npm scripts, Makefile targets, bash scripts
   - CI/CD workflows (.github/workflows/)
   - Deploy scripts, migration scripts

6. **Git state** — Current branch, uncommitted changes, recent commits

## Output format

```
## Project: <name> v<version>
- **Stack:** <language> + <framework> + <runtime>
- **Entry:** <main file>
- **Routes:** <N> endpoints across <M> files
- **Tests:** <framework> — <N> test files
- **Scripts:** <N> automation scripts
- **External services:** <list>
- **Git:** branch <name>, <N> uncommitted changes

### Key files
| File | Purpose |
|------|---------|
| ... | ... |

### Architecture
<2-3 sentence description of how data flows through the system>
```

## Tools used

| Tool | Purpose |
|------|---------|
| `glob_search` | Map directory structure, find config files |
| `grep_search` | Find route definitions, entry points, patterns |
| `read_file` | Read README, package.json, key source files |

## Performance

- Small repos (<100 files): <10 seconds
- Medium repos (100-500 files): 10-30 seconds
- Large repos (500+ files): 30-60 seconds

## Examples

**New repo onboarding:**
```
User: "I need to work on the opsora-agent-api repo"
→ Run cartographer → produces structured map
→ Now you know: stdlib Python server, 7 model aliases, port 8080, SQLite usage tracking
```

**Before debugging:**
```
User: "the deploy is failing, help me fix it"
→ Run cartographer first → find deploy scripts, CI workflows, Docker config
→ Then investigate the specific failure
```
