---
name: opsora-context-memory
description: Use Opsora memory, cache, and skills for above-average agent context
---

# Opsora Context & Memory Skill

## When to use memory
- Save stable project facts: stack, conventions, deployment targets
- Save user preferences: language, default branch, provider choice
- Do NOT save secrets, tokens, or credentials

## Commands
- `/memory <query>` — quick search
- `/skills` — list loaded skills
- `/cache` — cache hit statistics

## Tool usage
- Call `memory_search` before multi-file edits
- Call `skill_match` when the task matches a known workflow
- Reuse cached `graphify_query` results within the same session

## Context strategy
- Keep recent turns verbatim
- Compress older turns into a short summary
- Inject matched skills into the system prompt for specialized tasks
