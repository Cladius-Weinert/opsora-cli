# Opsora Marketing Hub - Implementation Plan

## Current State Analysis (as of 2026-08-03)

### Existing Modules
| Module | Status | Key Features |
|--------|--------|--------------|
| `hub.py` | CLI entry point | Commands: discover, post, broadcast, schedule |
| `config.py` | Hardcoded secrets | Telegram, Discord, Twitter, Brand config |
| `content_engine.py` | Template-based | 6 post types, weekly schedule, basic generation |
| `telegram_poster.py` | Telethon-based | Send, broadcast, list chats/groups |
| `discord_poster.py` | REST API-based | Send message, embeds, broadcast, list guilds/channels |

### Known Integrations
- **Telegram**: Yakovlev @exaplolos (ID: 8010520796) - 25+ groups/channels
- **Discord**: Opsora#9330 (ID: 1520866975352487987) - NOT in any server
- **Twitter**: twitterapi.io proxy (read-only works, write needs proxy+login)

### Technical Debt
- ❌ No type hints
- ❌ No Pydantic config management
- ❌ No proper error handling/logging
- ❌ No unit/integration tests
- ❌ No timezone handling (Bali/WITA)
- ❌ No recurring posts support
- ❌ No media attachments support
- ❌ No inline keyboards (Telegram)
- ❌ No slash commands (Discord)
- ❌ No analytics/engagement tracking
- ❌ No A/B testing
- ❌ No Dockerfile

---

## Phase 1: Foundation (Week 1) - HIGH PRIORITY

### 1.1 Config Refactor with Pydantic Settings
**File**: `config.py` → `settings.py`
- Pydantic BaseSettings with environment variable support
- Separate config classes: TelegramSettings, DiscordSettings, TwitterSettings, BrandSettings, SchedulerSettings
- Validation for required fields
- Support for `.env` file loading
- Type-safe configuration access

### 1.2 Logging & Error Handling Standardization
**Files**: All modules
- Structured logging with `structlog` or standard `logging` + JSON formatter
- Custom exception hierarchy: `MarketingHubError`, `PostingError`, `SchedulingError`, `AuthError`
- Retry logic with exponential backoff for API calls
- Circuit breaker pattern for external services

### 1.3 Type Hints Across All Modules
**Files**: All `.py` files
- Full type annotations (params, returns, class attributes)
- Protocol/ABC for platform posters
- Generic types for responses

---

## Phase 2: Core Improvements (Week 1-2) - HIGH PRIORITY

### 2.1 Enhanced Content Engine with AI Models
**File**: `content_engine.py`
- Integration with NVIDIA Nemotron / Alibaba Qwen via existing Opsora routing
- Structured templates with Jinja2
- Content variants (A/B test ready)
- Hashtag optimization suggestions
- Content calendar data structure
- SEO/keyword integration

### 2.2 Scheduler Module (NEW)
**File**: `scheduler.py`
- APScheduler with persistent job store (SQLite/Redis)
- Timezone: Asia/Makassar (WITA/Bali)
- Recurring schedules: cron, interval, date
- Media attachment scheduling
- Job persistence across restarts
- Webhook callbacks for job events
- CLI: `schedule add/list/remove/run-now`

### 2.3 Unified Posting Interface
**File**: `posting.py` (NEW)
- Abstract base class `PlatformPoster`
- Concrete implementations: `TelegramPoster`, `DiscordPoster`, `TwitterPoster`
- Platform-specific formatting (MarkdownV2, Discord embeds, Twitter threads)
- Media handling: photos, videos, documents
- Rate limiting per platform
- Unified response format

---

## Phase 3: Platform-Specific Upgrades (Week 2) - HIGH PRIORITY

### 3.1 Telegram Bot Enhancement
**File**: `telegram_poster.py`
- Inline keyboards with callback handlers
- Command handlers: `/start`, `/help`, `/subscribe`, `/unsubscribe`, `/stats`
- Broadcast to multiple targets with progress tracking
- Media support: photos, videos, documents, albums
- Chat member tracking (joins/leaves)
- Poll/quiz support
- Webhook mode for production

### 3.2 Discord Bot Enhancement
**File**: `discord_poster.py`
- Slash commands: `/post`, `/schedule`, `/analytics`, `/config`
- Rich embeds with components (buttons, selects)
- Server/guild management (join/leave tracking)
- Thread support for announcements
- Webhook support for external integrations
- Auto-mod integration
- Presence/activity updates

---

## Phase 4: Analytics & Intelligence (Week 2-3) - MEDIUM PRIORITY

### 4.1 Analytics Module (NEW)
**File**: `analytics.py`
- Engagement tracking: views, clicks, reactions, forwards, replies
- Conversion metrics: link clicks → signups → purchases
- A/B testing framework for content variants
- Cohort analysis
- Real-time dashboard data structure
- Export to CSV/JSON/Parquet
- Integration with Google Analytics/UTM

### 4.2 Hashtag Research (NEW)
**File**: `hashtag_research.py`
- Trending hashtags via Twitter/Instagram APIs
- Hashtag performance tracking
- Related hashtag suggestions
- Optimal hashtag count per platform
- Competitor hashtag analysis

### 4.3 Image Generation (NEW)
**File**: `image_generation.py`
- NVIDIA Nemotron 3 Ultra / Stable Diffusion via API
- Brand-consistent templates
- Auto-resize for platform specs
- Text overlay with brand fonts
- Batch generation for content calendar

### 4.4 Competitor Monitor (NEW)
**File**: `competitor_monitor.py`
- Track competitor posts (Telegram, Discord, Twitter)
- Content strategy analysis
- Posting frequency/timing patterns
- Engagement benchmarking
- Alert on viral competitor content

### 4.5 Auto-Reply & Sentiment (NEW)
**File**: `auto_reply.py`
- Sentiment analysis (positive/negative/neutral)
- Auto-reply rules engine
- FAQ matching with embeddings
- Escalation to human
- Response time tracking

### 4.6 Lead Capture (NEW)
**File**: `lead_capture.py`
- Capture from: Telegram buttons, Discord modals, Twitter DMs
- Lead scoring
- CRM integration (webhook to n8n/Zapier/HubSpot)
- UTM parameter tracking
- Duplicate detection

---

## Phase 5: CLI & MCP Integration (Week 3) - HIGH PRIORITY

### 5.1 Opsora CLI Slash Commands
**Integration**: `opsora_cmd/opsora_new_tools.py` or new module
- `/market post [type] [--platforms] [--schedule]`
- `/market schedule [add|list|remove] [--cron] [--timezone]`
- `/market broadcast [--text] [--platforms] [--targets]`
- `/market analytics [--platform] [--days] [--export]`
- `/market discover [--platform]`
- `/market config [show|set]`

### 5.2 MCP Server Exposure
**File**: `marketing_mcp.py` (NEW)
- Tools: `generate_post`, `schedule_post`, `broadcast_post`, `get_analytics`, `discover_channels`
- Resources: `marketing://calendar`, `marketing://templates`, `marketing://analytics`
- Prompts: `create_campaign`, `optimize_hashtags`, `analyze_competitor`

### 5.3 Webhook Endpoints
**File**: `webhooks.py` (NEW)
- FastAPI/Starlette server
- Endpoints:
  - `POST /webhook/telegram` - Telegram updates
  - `POST /webhook/discord` - Discord interactions
  - `POST /webhook/twitter` - Twitter account activity
  - `POST /webhook/analytics` - Custom events
- Signature verification
- Rate limiting
- Async processing with background tasks

---

## Phase 6: Quality & Deployment (Week 3-4) - MEDIUM PRIORITY

### 6.1 Testing
**Directory**: `tests/`
- Unit tests: config, content_engine, scheduler, posters
- Integration tests: Telegram/Telethon mock, Discord REST mock
- Property-based tests for content generation
- Load tests for broadcast

### 6.2 Dockerization
**Files**: `Dockerfile`, `docker-compose.yml`, `.dockerignore`
- Multi-stage build
- Non-root user
- Health checks
- Environment-based config
- Compose with Redis (scheduler), PostgreSQL (analytics)

### 6.3 Documentation
**Files**: `README.md`, `docs/`
- Architecture overview
- Configuration guide
- CLI reference
- MCP tool reference
- Deployment guide
- Contributing guide

---

## Priority Matrix

| Task | Impact | Effort | Priority |
|------|--------|--------|----------|
| Pydantic Config | High | Low | 🔴 P0 |
| Type Hints + Logging | High | Low | 🔴 P0 |
| Scheduler with WITA | High | Medium | 🔴 P0 |
| Unified Posting Interface | High | Medium | 🔴 P0 |
| Telegram Inline Keyboards | High | Medium | 🔴 P0 |
| Discord Slash Commands | High | Medium | 🔴 P0 |
| AI Content Generation | High | Medium | 🔴 P0 |
| Analytics Core | Medium | High | 🟡 P1 |
| Hashtag Research | Medium | Medium | 🟡 P1 |
| Image Generation | Medium | High | 🟡 P1 |
| Competitor Monitor | Low | High | 🟢 P2 |
| Auto-Reply/Sentiment | Medium | High | 🟡 P1 |
| Lead Capture | Medium | High | 🟡 P1 |
| CLI Slash Commands | High | Low | 🔴 P0 |
| MCP Server | High | Medium | 🔴 P0 |
| Webhooks | Medium | Medium | 🟡 P1 |
| Tests | High | High | 🟡 P1 |
| Docker | Medium | Medium | 🟡 P1 |

---

## Implementation Order (Recommended)

### Sprint 1 (Days 1-3): Foundation
1. ✅ `settings.py` - Pydantic config
2. ✅ Type hints + logging across all existing files
3. ✅ `posting.py` - Unified interface + base classes
4. ✅ `scheduler.py` - APScheduler with WITA timezone

### Sprint 2 (Days 4-6): Platform Upgrades
5. ✅ `telegram_poster.py` - Inline keyboards, commands, media
6. ✅ `discord_poster.py` - Slash commands, embeds, webhooks
7. ✅ `content_engine.py` - AI integration, Jinja2, variants

### Sprint 3 (Days 7-9): Intelligence
8. ✅ `analytics.py` - Core tracking + A/B testing
9. ✅ `hashtag_research.py` - Trending + optimization
10. ✅ `image_generation.py` - NVIDIA vision models

### Sprint 4 (Days 10-12): Integration
11. ✅ CLI slash commands integration
12. ✅ MCP server exposure
13. ✅ Webhook endpoints

### Sprint 5 (Days 13-14): Quality
14. ✅ Unit/integration tests
15. ✅ Docker + compose
16. ✅ Documentation

---

## Dependencies to Add

```toml
# pyproject.toml additions
[project.optional-dependencies]
marketing = [
    "pydantic-settings>=2.0",
    "apscheduler>=3.10",
    "jinja2>=3.1",
    "structlog>=24.0",
    "httpx>=0.27",
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "python-telegram-bot>=21.0",  # For webhook mode
    "discord.py>=2.3",  # For slash commands + gateway
    "redis>=5.0",  # Job store
    "sqlalchemy>=2.0",  # Persistent job store
    "pandas>=2.2",  # Analytics
    "matplotlib>=3.8",  # Charts
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
    "httpx-mock>=0.10",
    "freezegun>=1.5",
]
```

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Config validation coverage | 100% |
| Type hint coverage | >95% |
| Test coverage | >80% |
| Broadcast success rate | >99% |
| Scheduler uptime | 99.9% |
| CLI command response time | <2s |
| MCP tool latency | <500ms |
| Webhook processing latency | <100ms |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Telegram API changes | Version pinning, integration tests |
| Discord gateway complexity | Start with REST + webhooks, add gateway later |
| Twitter write restrictions | Focus on read + twitterapi.io proxy |
| Rate limiting | Built-in retry + circuit breaker |
| Session expiration | Auto-reconnect + health checks |
| Timezone bugs | Comprehensive TZ tests with `freezegun` |