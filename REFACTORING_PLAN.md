# Opsora CLI Refactoring Plan

## Executive Summary

The current `opsora_v2.py` (2,371 lines) is a **monolithic single-file architecture** that violates multiple SOLID principles. This plan outlines a phased approach to transform it into a **modular, testable, extensible architecture** with proper separation of concerns.

---

## Current Architecture Analysis

### File Structure (45 Python files in opsora_cmd/)

| File | Lines | Responsibility |
|------|-------|----------------|
| `opsora_v2.py` | 2,371 | Main agent loop, provider routing, tool execution, slash commands, session mgmt, TUI |
| `opsora_routing.py` | ~400 | Intent classification, model selection |
| `opsora_session.py` | ~300 | SQLite session persistence |
| `opsora_mcp.py` | ~350 | MCP stdio client v1 |
| `opsora_mcp_v2.py` | ~500 | MCP stdio/HTTP/SSE client v2 |
| `opsora_plugins.py` | ~150 | Plugin discovery/loading |
| `opsora_agent.py` | ~550 | Autonomous agent (plan→act→verify) |
| `opsora_compression.py` | ~100 | Context compression |
| `opsora_cost.py` | ~100 | Token/cost tracking |
| `opsora_tui.py` | ~400 | Terminal UI, prompts, rendering |
| `opsora_new_tools.py` | ~200 | Web search, DB query, HTTP |
| `opsora_nvidia.py` | ~250 | NVIDIA NIM services |
| `opsora_subagent.py` | ~300 | Sub-agent orchestration |
| `opsora_google.py` | ~200 | Google services |
| Others | ~1,500 | Themes, memory, tools, reflection, streaming, graph |

### Critical Issues Identified

1. **Monolithic `opsora_v2.py`** — 2,371 lines with 15+ responsibilities
2. **Global State** — 8 global provider clients, `_mcp_client`, `_plugin_manager`, `_cost_tracker`, `_current_todos`, `_project_context`
3. **Tight Coupling** — Direct imports between modules, hardcoded provider logic
4. **No Dependency Injection** — Cannot mock providers/tools for testing
5. **Duplicate MCP Clients** — `opsora_mcp.py` AND `opsora_mcp_v2.py` coexist
6. **Hardcoded Routing** — Keywords in `opsora_routing.py` not configurable
7. **No Plugin API Contract** — `opsora_plugins.py` uses abstract base but no versioning
8. **Startup Performance** — All providers initialized at import time

---

## Proposed Target Architecture

```
opsora-cli/
├── opsora/
│   ├── __init__.py                 # Public exports, version
│   ├── config.py                   # Pydantic settings (replaces env vars)
│   ├── container.py                # Dependency injection container
│   ├── events.py                   # Event system (hooks, signals)
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── agent_loop.py           # Main ReAct loop (from opsora_v2.py)
│   │   ├── command_handler.py      # Slash command dispatcher
│   │   ├── model_selector.py       # Provider/model routing logic
│   │   ├── session_manager.py      # Session CRUD + search
│   │   ├── mcp_manager.py          # MCP client lifecycle (v2 only)
│   │   ├── tool_executor.py        # Tool sandbox + approval
│   │   ├── compression.py          # Context compression
│   │   ├── cost_tracker.py         # Token/cost tracking
│   │   └── autonomous_agent.py     # Autonomous agent loop
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract Provider interface
│   │   ├── registry.py             # Provider registry + discovery
│   │   ├── nvidia.py               # NVIDIA NIM implementation
│   │   ├── alibaba.py              # Alibaba/DashScope implementation
│   │   ├── openai.py               # OpenAI implementation
│   │   ├── bedrock.py              # AWS Bedrock implementation
│   │   ├── tokenhub.py             # TokenHub implementation
│   │   └── local.py                # Local model (ollama, etc.)
│   │
│   ├── routing/
│   │   ├── __init__.py
│   │   ├── intent_classifier.py    # Pluggable intent classification
│   │   ├── router.py               # Model selection with policies
│   │   ├── rules/                  # Configurable routing rules (YAML)
│   │   │   ├── default.yaml
│   │   │   └── cost_aware.yaml
│   │   └── ab_testing.py           # A/B testing framework
│   │
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── client.py               # Unified MCP client (v2 only)
│   │   ├── stdio_transport.py
│   │   ├── http_transport.py
│   │   ├── sse_transport.py
│   │   ├── health.py               # Health checks + auto-reconnect
│   │   └── pool.py                 # Connection pooling
│   │
│   ├── session/
│   │   ├── __init__.py
│   │   ├── store.py                # SQLite store (from opsora_session.py)
│   │   ├── compression.py          # Session compression for large histories
│   │   ├── tagging.py              # Session tags/categories
│   │   ├── search.py               # Full-text search by content
│   │   └── export.py               # Export/import (JSON, markdown)
│   │
│   ├── plugins/
│   │   ├── __init__.py
│   │   ├── api.py                  # Plugin API v1 (versioned)
│   │   ├── manager.py              # Discovery, loading, hot-reload
│   │   ├── registry.py             # Plugin registry with metadata
│   │   └── sandbox.py              # Execution sandbox (timeout, permissions)
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── tui.py                  # Terminal UI (from opsora_tui.py)
│   │   ├── prompts.py              # Prompt rendering
│   │   ├── rendering.py            # Tool call, diff, markdown rendering
│   │   └── themes.py               # Theme management
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py             # Tool registry
│   │   ├── builtin/                # Built-in tools (file, shell, git, web)
│   │   │   ├── __init__.py
│   │   │   ├── file_ops.py
│   │   │   ├── shell_ops.py
│   │   │   ├── git_ops.py
│   │   │   ├── web_ops.py
│   │   │   └── research_ops.py
│   │   └── mcp_tools.py            # MCP tool adapter
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── store.py                # Persistent memory (vector + SQLite)
│   │   └── graph.py                # Knowledge graph
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logging.py              # Structured logging
│       ├── validation.py           # Path, command validation
│       └── retry.py                # Retry policies
│
├── opsora_cli/
│   ├── __main__.py                 # Entry point
│   └── main.py                     # CLI orchestration
│
├── config/
│   ├── settings.yaml               # Main configuration
│   ├── providers.yaml              # Provider configuration
│   ├── routing.yaml                # Routing rules
│   ├── themes.yaml                 # Theme definitions
│   └── mcp.yaml                    # MCP server configuration
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
└── pyproject.toml
```

---

## Phase 1: Critical Fixes (Security, Bugs, Stability)

**Duration:** 1-2 weeks  
**Risk:** Low  
**Effort:** ~40 hours

### 1.1 Security Fixes (Immediate)

| Issue | Fix | Files |
|-------|-----|-------|
| Path traversal in `read_file`/`write_file` | Use `_validate_path` consistently, add symlink checks | `opsora_v2.py`, new `utils/validation.py` |
| Command injection in `run_command` | Use `shlex.split`, no shell=True for user input | `opsora_v2.py`, new `tools/builtin/shell_ops.py` |
| Auto-install allowlist bypass | Move to config, add signature verification | `opsora_v2.py` → `config/providers.yaml` |
| Credential exposure in logs | Redact sensitive fields in all logging | `utils/logging.py` |
| MCP server command injection | Validate/sanitize server commands | `mcp/stdio_transport.py` |

### 1.2 Bug Fixes

| Bug | Fix |
|-----|-----|
| Duplicate MCP clients (`mcp.py` + `mcp_v2.py`) | **Remove `opsora_mcp.py`**, standardize on v2 |
| Global state mutation during tests | Add DI container, reset between tests |
| Session ID collision (SHA256 of timestamp) | Use UUID4 + timestamp |
| Context compression loses tool call IDs | Preserve `tool_call_id` in compressed messages |
| Provider fallback doesn't respect model capabilities | Add capability matching in router |
| Cost tracker uses hardcoded prices | Move to `config/providers.yaml` with per-model pricing |

### 1.3 Stability Improvements

- Add structured logging with correlation IDs
- Implement request timeouts for all provider calls
- Add circuit breaker for failing providers
- Health check endpoint for MCP servers

---

## Phase 2: Modularization (Core Architecture)

**Duration:** 3-4 weeks  
**Risk:** Medium  
**Effort:** ~120 hours

### 2.1 Dependency Injection Container

```python
# opsora/container.py
from dependency_injector import containers, providers

class OpsoraContainer(containers.DeclarativeContainer):
    config = providers.Configuration()
    
    # Providers
    nvidia_provider = providers.Factory(NvidiaProvider, api_key=config.nvidia.api_key)
    alibaba_provider = providers.Factory(AlibabaProvider, api_key=config.alibaba.api_key)
    provider_registry = providers.Factory(ProviderRegistry, providers=[
        nvidia_provider, alibaba_provider, ...
    ])
    
    # Core services
    model_selector = providers.Factory(ModelSelector, registry=provider_registry)
    session_manager = providers.Factory(SessionManager, db_path=config.session.db_path)
    mcp_manager = providers.Factory(MCPManager, config_path=config.mcp.config_path)
    tool_executor = providers.Factory(ToolExecutor, approval_service=...)
    
    # Agent
    agent_loop = providers.Factory(AgentLoop, 
        model_selector=model_selector,
        tool_executor=tool_executor,
        session_manager=session_manager,
    )
```

### 2.2 Module Extraction Priority

| Priority | Module | Source | Lines |
|----------|--------|--------|-------|
| 1 | `core/agent_loop.py` | `opsora_v2.py:run_agent_turn` | ~300 |
| 2 | `core/command_handler.py` | `opsora_v2.py:handle_command` | ~400 |
| 3 | `core/model_selector.py` | `opsora_v2.py:auto_select_model` + `opsora_routing.py` | ~200 |
| 4 | `core/session_manager.py` | `opsora_session.py` | ~300 |
| 5 | `core/mcp_manager.py` | `opsora_mcp_v2.py` | ~500 |
| 6 | `core/tool_executor.py` | `opsora_v2.py:execute_tool` | ~400 |
| 7 | `providers/` | `opsora_v2.py` provider getters | ~200 |
| 8 | `tools/builtin/` | `opsora_v2.py` tool implementations | ~500 |

### 2.3 Breaking Changes

- Remove global `_mcp_client`, `_plugin_manager`, `_cost_tracker`, `_current_todos`
- Replace `Selection` dataclass with typed `ModelSelection(provider: Provider, model: ModelConfig)`
- Replace env var config with Pydantic `Settings` loaded from `config/settings.yaml`

---

## Phase 3: Plugin System & Extensibility

**Duration:** 2-3 weeks  
**Risk:** Medium  
**Effort:** ~80 hours

### 3.1 Versioned Plugin API

```python
# opsora/plugins/api.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class PluginV1(Protocol):
    """Plugin API v1 — stable contract."""
    name: str
    version: str  # Semantic version
    description: str
    min_opsora_version: str
    max_opsora_version: str | None = None
    
    def schema(self) -> ToolSchema: ...
    async def execute(self, args: dict, context: PluginContext) -> ToolResult: ...
    def cleanup(self) -> None: ...

class PluginContext:
    """Injected context for plugin execution."""
    session_id: str
    workspace_root: Path
    approval_mode: ApprovalMode
    config: dict
```

### 3.2 Plugin Features

| Feature | Implementation |
|---------|----------------|
| **Discovery** | Entry points + `~/.opsora/plugins/` directory |
| **Hot Reload** | File watcher with debounce |
| **Sandbox** | Subprocess isolation, timeout, resource limits |
| **Permissions** | Declare required permissions in manifest |
| **Dependencies** | `requirements.txt` per plugin, auto-install in venv |
| **Marketplace** | Remote plugin index (future) |

### 3.3 Plugin Manifest (`plugin.yaml`)

```yaml
name: my-plugin
version: 1.0.0
description: "Custom tool for XYZ"
author: "User"
min_opsora_version: "3.2.0"
permissions:
  - filesystem:read
  - network:https://api.example.com
entry_point: my_plugin:MyPlugin
dependencies:
  - requests>=2.31
```

---

## Phase 4: Performance & Observability

**Duration:** 2-3 weeks  
**Risk:** Low  
**Effort:** ~60 hours

### 4.1 Performance Optimizations

| Optimization | Impact | Implementation |
|--------------|--------|----------------|
| **Lazy provider init** | -40% startup time | Initialize on first use via DI container |
| **Model metadata cache** | -200ms per request | Cache `models.list()` for 1 hour |
| **Streaming responses** | Perceived latency | Use `stream=True` in OpenAI client |
| **Connection pooling** | -50ms per MCP call | HTTP/stdio connection reuse |
| **Parallel tool calls** | -30% multi-tool latency | `asyncio.gather` for independent tools |
| **Context compression async** | Non-blocking | Background compression task |

### 4.2 Observability

```python
# opsora/events.py
from dataclasses import dataclass
from enum import Enum
from typing import Callable
import time

class EventType(Enum):
    PROVIDER_REQUEST = "provider.request"
    PROVIDER_RESPONSE = "provider.response"
    TOOL_CALL_START = "tool.call.start"
    TOOL_CALL_END = "tool.call.end"
    AGENT_TURN_START = "agent.turn.start"
    AGENT_TURN_END = "agent.turn.end"
    SESSION_SAVE = "session.save"
    ERROR = "error"

@dataclass
class Event:
    type: EventType
    timestamp: float
    correlation_id: str
    data: dict

class EventBus:
    def __init__(self):
        self._subscribers: dict[EventType, list[Callable]] = {}
    
    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]):
        self._subscribers.setdefault(event_type, []).append(handler)
    
    def emit(self, event: Event):
        for handler in self._subscribers.get(event.type, []):
            try:
                handler(event)
            except Exception:
                pass  # Don't let observers crash the main loop
```

**Metrics to Track:**
- Provider latency (p50, p95, p99)
- Tool call success/failure rates
- Token usage per model
- Session duration & message count
- MCP server health status

### 4.3 Structured Logging

```json
{
  "timestamp": "2026-08-03T10:15:30.123Z",
  "level": "INFO",
  "correlation_id": "abc-123",
  "event": "provider.request",
  "provider": "nvidia",
  "model": "nemotron-3-ultra",
  "tokens_estimated": 1500,
  "duration_ms": 1200
}
```

---

## Phase 5: Advanced Features

**Duration:** 3-4 weeks  
**Risk:** Medium  
**Effort:** ~100 hours

### 5.1 Configurable Routing Rules

**File:** `config/routing.yaml`

```yaml
version: 1
rules:
  - intent: "code"
    priority: 100
    conditions:
      - "contains: write, create, generate, function, class, bug, fix, refactor"
    providers:
      - name: "alibaba"
        models: ["qwen3-coder-flash", "qwen-plus"]
        weight: 1.0
      - name: "nvidia"
        models: ["meta/llama-3.1-70b-instruct"]
        weight: 0.8
    fallback: "quick"

  - intent: "analysis"
    priority: 90
    conditions:
      - "contains: analyze, architecture, design, strategy, compare"
    providers:
      - name: "alibaba"
        models: ["qwen3.7-max", "qwen-max"]
        weight: 1.0
      - name: "tokenhub"
        models: ["kimi-k3"]
        weight: 0.9

policies:
  cost_aware:
    max_cost_per_request: 0.10
    prefer_free_tier: true
  latency_aware:
    max_latency_ms: 3000
    fallback_on_timeout: true
  ab_test:
    enabled: true
    traffic_split:
      alibaba: 0.6
      nvidia: 0.4
```

### 5.2 Session Enhancements

| Feature | Description |
|---------|-------------|
| **Compression** | Compress sessions > 50k tokens using LLM summarization |
| **Tagging** | Add tags: `#bugfix`, `#feature`, `#research` |
| **Search** | Full-text search across message content + tool outputs |
| **Export** | Export to JSON, Markdown, HTML with rendering |
| **Branching** | Fork session at any point (already partially implemented) |

### 5.3 MCP Enhancements

| Feature | Description |
|---------|-------------|
| **Connection Pool** | Reuse stdio processes, HTTP connections |
| **Health Checks** | Periodic `/health` ping, auto-reconnect |
| **Tool Timeout** | Per-tool timeout config (default 30s) |
| **Retry Logic** | Exponential backoff for transient failures |
| **Resource Support** | Read MCP resources (files, APIs) |
| **Prompt Support** | Use MCP prompt templates |

### 5.4 A/B Testing for Model Selection

```python
# opsora/routing/ab_testing.py
class ABTestRouter:
    def __init__(self, config: ABTestConfig):
        self.config = config
        self.assignments: dict[str, str] = {}  # session_id -> variant
    
    def select(self, session_id: str, candidates: list[ModelOption]) -> ModelOption:
        variant = self.assignments.get(session_id) or self._assign(session_id)
        return self._filter_by_variant(candidates, variant)
    
    def record_outcome(self, session_id: str, success: bool, latency_ms: float):
        # Send to analytics backend
        pass
```

---

## Migration Strategy

### Backward Compatibility

1. **Config Migration Script** — `opsora migrate-config` converts env vars → `config/settings.yaml`
2. **Session Migration** — Read old SQLite format, write new format
3. **Plugin Compatibility** — Support v0 plugins with deprecation warnings
4. **MCP Config** — Keep `~/.opsora/mcp.json` format, add v2 features

### Rollout Plan

| Week | Milestone |
|------|-----------|
| 1-2 | Phase 1 complete, all tests pass |
| 3-4 | Phase 2 core modules extracted, DI container working |
| 5-6 | Phase 2 complete, old `opsora_v2.py` deprecated |
| 7-8 | Phase 3 plugin system v1 released |
| 9-10 | Phase 4 observability dashboard |
| 11-12 | Phase 5 advanced features, config-driven routing |
| 13 | Integration testing, documentation, release v4.0 |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **Breaking changes in Phase 2** | High | High | Feature flags, parallel run old/new, comprehensive integration tests |
| **DI container complexity** | Medium | Medium | Start simple, use `dependency-injector` library, document patterns |
| **Plugin sandbox escape** | Low | Critical | Subprocess isolation, seccomp profiles, capability dropping |
| **Routing rule conflicts** | Medium | Medium | Priority-based resolution, validation at load time |
| **MCP v2 migration** | Medium | High | Keep v1 compat layer, gradual migration per server |
| **Performance regression** | Low | Medium | Benchmark suite in CI, alert on >10% regression |
| **Config migration failures** | Medium | Medium | Dry-run mode, backup old config, rollback script |

---

## Testing Strategy

### Test Pyramid

```
         E2E Tests (5%)
        /              \
   Integration Tests (15%)
  /                      \
Unit Tests (80%) - Fast, isolated, mocked
```

### Key Test Files to Create

| Test | Purpose |
|------|---------|
| `tests/unit/core/test_agent_loop.py` | Agent loop with mocked providers/tools |
| `tests/unit/routing/test_router.py` | Routing rules, A/B testing |
| `tests/unit/providers/test_registry.py` | Provider discovery, fallback |
| `tests/unit/plugins/test_manager.py` | Plugin load/unload, sandbox |
| `tests/integration/test_mcp_lifecycle.py` | MCP connect/disconnect/reconnect |
| `tests/integration/test_session_crud.py` | Session save/load/search |
| `tests/e2e/test_cli.py` | Full CLI workflows |

### CI Pipeline Additions

```yaml
# .github/workflows/test.yml
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - pytest tests/unit --cov=opsora --cov-fail-under=80
  
  integration:
    runs-on: ubuntu-latest
    services:
      postgres: ...
      redis: ...
    steps:
      - pytest tests/integration
  
  e2e:
    runs-on: ubuntu-latest
    steps:
      - pytest tests/e2e --headed
  
  security:
    runs-on: ubuntu-latest
    steps:
      - bandit -r opsora/
      - safety check
      - pip-audit
```

---

## Effort Summary

| Phase | Duration | Effort | Risk | Dependencies |
|-------|----------|--------|------|--------------|
| 1: Critical Fixes | 1-2 weeks | 40h | Low | None |
| 2: Modularization | 3-4 weeks | 120h | Medium | Phase 1 |
| 3: Plugin System | 2-3 weeks | 80h | Medium | Phase 2 |
| 4: Performance/Obs | 2-3 weeks | 60h | Low | Phase 2 |
| 5: Advanced Features | 3-4 weeks | 100h | Medium | Phases 2-4 |
| **Total** | **11-16 weeks** | **~400h** | **Medium** | — |

---

## Success Criteria

| Metric | Target |
|--------|--------|
| **Startup time** | < 500ms (currently ~2-3s) |
| **Test coverage** | > 80% unit, > 60% integration |
| **Provider latency (p95)** | < 3s |
| **MCP reconnect time** | < 5s |
| **Plugin load time** | < 100ms per plugin |
| **Config validation** | < 50ms |
| **Memory usage (idle)** | < 100MB |
| **Session save/load** | < 100ms for 10k messages |

---

## Appendix: File Mapping (Old → New)

| Old File | New Location(s) |
|----------|-----------------|
| `opsora_v2.py` | `core/agent_loop.py`, `core/command_handler.py`, `core/model_selector.py`, `core/tool_executor.py`, `providers/`, `tools/builtin/` |
| `opsora_routing.py` | `routing/intent_classifier.py`, `routing/router.py`, `config/routing.yaml` |
| `opsora_session.py` | `session/store.py`, `session/search.py`, `session/export.py` |
| `opsora_mcp.py` | **REMOVE** (use v2) |
| `opsora_mcp_v2.py` | `mcp/client.py`, `mcp/stdio_transport.py`, `mcp/http_transport.py`, `mcp/health.py` |
| `opsora_plugins.py` | `plugins/api.py`, `plugins/manager.py`, `plugins/registry.py`, `plugins/sandbox.py` |
| `opsora_agent.py` | `core/autonomous_agent.py` |
| `opsora_compression.py` | `core/compression.py`, `session/compression.py` |
| `opsora_cost.py` | `core/cost_tracker.py` |
| `opsora_tui.py` | `ui/tui.py`, `ui/prompts.py`, `ui/rendering.py` |
| `opsora_new_tools.py` | `tools/builtin/web_ops.py`, `tools/builtin/research_ops.py` |
| `opsora_nvidia.py` | `providers/nvidia.py` (NIM services) |
| `opsora_google.py` | `providers/google.py` |
| `opsora_themes.py` | `ui/themes.py`, `config/themes.yaml` |
| `opsora_memory.py` | `memory/store.py` |
| `opsora_graph_v2.py` | `memory/graph.py` |

---

*Document version: 1.0*  
*Created: 2026-08-03*  
*Author: Opsora Architecture Review*