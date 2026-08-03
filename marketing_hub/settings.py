"""
Opsora Marketing Hub - Configuration with Pydantic Settings

Environment-based configuration with validation, type safety, and .env support.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelegramSettings(BaseSettings):
    """Telegram Bot API configuration."""
    model_config = SettingsConfigDict(
        env_prefix="TG_",
        case_sensitive=False,
        extra="ignore",
    )

    # Required — must come from env (TG_API_ID, TG_API_HASH, TG_PHONE); never hardcode secrets
    api_id: Optional[int] = Field(default=None, description="Telegram API ID from my.telegram.org (env TG_API_ID)")
    api_hash: Optional[str] = Field(default=None, description="Telegram API Hash (env TG_API_HASH)")
    session_path: str = Field(default="/root/.telegram-mcp/opsora", description="Telethon session file path")
    phone: Optional[str] = Field(default=None, description="Phone number for authentication (env TG_PHONE)")

    # Optional - Target chats for broadcasting
    target_channels: list[int] = Field(default_factory=list, description="List of channel/chat IDs to broadcast to")
    target_groups: list[int] = Field(default_factory=list, description="List of group IDs to broadcast to")

    # Bot token (if using Bot API instead of userbot)
    bot_token: Optional[str] = Field(default=None, description="Bot token from @BotFather")

    # Webhook settings (for production)
    webhook_url: Optional[str] = Field(default=None, description="Webhook URL for receiving updates")
    webhook_port: int = Field(default=8443, description="Webhook server port")
    webhook_path: str = Field(default="/webhook/telegram", description="Webhook path")


class DiscordSettings(BaseSettings):
    """Discord Bot configuration."""
    model_config = SettingsConfigDict(
        env_prefix="DISCORD_",
        case_sensitive=False,
        extra="ignore",
    )

    # Required — must come from env (DISCORD_TOKEN); never hardcode secrets
    token: Optional[str] = Field(
        default=None,
        description="Discord bot token (env DISCORD_TOKEN)"
    )
    application_id: Optional[int] = Field(default=None, description="Discord application ID for slash commands")
    public_key: Optional[str] = Field(default=None, description="Discord public key for interaction verification")

    # Optional - Target channels for broadcasting
    target_channels: list[int] = Field(default_factory=list, description="List of channel IDs to broadcast to")
    target_guilds: list[int] = Field(default_factory=list, description="List of guild/server IDs")

    # API settings
    api_base: str = Field(default="https://discord.com/api/v10", description="Discord API base URL")
    api_version: int = Field(default=10, description="Discord API version")

    # Gateway settings (for slash commands/events)
    use_gateway: bool = Field(default=False, description="Use Discord gateway for real-time events")
    intents: int = Field(default=3276799, description="Gateway intents bitmask (default: all non-privileged)")

    # Webhook settings
    webhook_url: Optional[str] = Field(default=None, description="Webhook URL for receiving interactions")
    webhook_port: int = Field(default=8444, description="Webhook server port")
    webhook_path: str = Field(default="/webhook/discord", description="Webhook path")


class TwitterSettings(BaseSettings):
    """Twitter/X API configuration via twitterapi.io proxy."""
    model_config = SettingsConfigDict(
        env_prefix="TWITTER_",
        case_sensitive=False,
        extra="ignore",
    )

    api_key: Optional[str] = Field(
        default=None,
        description="twitterapi.io API key (env TWITTER_API_KEY)"
    )
    api_base: str = Field(default="https://api.twitterapi.io", description="Twitter API base URL")

    # For write operations (requires login cookies)
    login_cookies: Optional[str] = Field(default=None, description="Twitter login cookies for write access")
    username: Optional[str] = Field(default=None, description="Twitter username")
    password: Optional[str] = Field(default=None, description="Twitter password (for cookie generation)")

    # Rate limiting
    rate_limit_requests: int = Field(default=300, description="Requests per 15-minute window")
    rate_limit_window: int = Field(default=900, description="Rate limit window in seconds")


class BrandSettings(BaseSettings):
    """Brand identity and messaging configuration."""
    model_config = SettingsConfigDict(
        env_prefix="BRAND_",
        case_sensitive=False,
        extra="ignore",
    )

    name: str = Field(default="Opsora AI", description="Brand name")
    handle: str = Field(default="@opsabora", description="Social media handle")
    color: str = Field(default="#8b5cf6", description="Brand hex color")
    email: str = Field(default="hello@opsora.dev", description="Contact email")
    website: str = Field(default="https://opsora.dev", description="Website URL")
    logo_url: str = Field(default="https://opsora.dev/logo.png", description="Logo image URL")
    tagline: str = Field(default="Your AI-powered business assistant", description="Brand tagline")
    description: str = Field(
        default="AI-powered business automation for UMKM: chatbot, CRM, social media, lead gen, and more.",
        description="Brand description"
    )

    # UTM defaults
    utm_source: str = Field(default="social", description="Default UTM source")
    utm_medium: str = Field(default="organic", description="Default UTM medium")
    utm_campaign: str = Field(default="brand_awareness", description="Default UTM campaign")


class SchedulerSettings(BaseSettings):
    """Scheduler configuration."""
    model_config = SettingsConfigDict(
        env_prefix="SCHED_",
        case_sensitive=False,
        extra="ignore",
    )

    # Timezone - Bali/WITA (Asia/Makassar)
    timezone: str = Field(default="Asia/Makassar", description="IANA timezone for scheduling")

    # Job store
    job_store_url: str = Field(default="sqlite:///jobs.sqlite", description="APScheduler job store URL")
    job_store_type: Literal["memory", "sqlalchemy", "redis"] = Field(
        default="sqlalchemy", description="Job store type"
    )

    # Redis settings (if using redis job store)
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")

    # Scheduler behavior
    max_instances: int = Field(default=3, description="Max concurrent instances of same job")
    coalesce: bool = Field(default=True, description="Coalesce missed executions")
    misfire_grace_time: int = Field(default=300, description="Misfire grace time in seconds")

    # Default schedule
    default_post_time: str = Field(default="09:00", description="Default post time (HH:MM in timezone)")
    default_post_days: list[str] = Field(
        default_factory=lambda: ["monday", "wednesday", "friday"],
        description="Default posting days"
    )


class AnalyticsSettings(BaseSettings):
    """Analytics and tracking configuration."""
    model_config = SettingsConfigDict(
        env_prefix="ANALYTICS_",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    db_url: str = Field(default="sqlite:///analytics.sqlite", description="Analytics database URL")

    # Google Analytics / Measurement Protocol
    ga_measurement_id: Optional[str] = Field(default=None, description="GA4 Measurement ID (G-XXXXXXXXXX)")
    ga_api_secret: Optional[str] = Field(default=None, description="GA4 API Secret")

    # UTM tracking
    track_utm: bool = Field(default=True, description="Automatically append UTM parameters")
    utm_source_override: Optional[str] = Field(default=None, description="Override UTM source per platform")

    # Retention
    raw_data_retention_days: int = Field(default=90, description="Raw event retention")
    aggregated_retention_days: int = Field(default=365, description="Aggregated metrics retention")

    # Export
    export_formats: list[str] = Field(
        default_factory=lambda: ["csv", "json", "parquet"],
        description="Supported export formats"
    )


class AIModelSettings(BaseSettings):
    """AI model configuration for content generation."""
    model_config = SettingsConfigDict(
        env_prefix="AI_",
        case_sensitive=False,
        extra="ignore",
    )

    # Provider preferences (uses existing Opsora routing)
    preferred_provider: Literal["alibaba", "nvidia", "auto"] = Field(
        default="auto", description="Preferred AI provider"
    )
    preferred_model: Optional[str] = Field(
        default=None, description="Specific model override (e.g., qwen3-coder-flash)"
    )

    # Content generation settings
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Generation temperature")
    max_tokens: int = Field(default=2048, ge=100, le=8192, description="Max tokens per generation")
    top_p: float = Field(default=0.9, ge=0.0, le=1.0, description="Nucleus sampling top-p")

    # Image generation
    image_model: str = Field(
        default="nvidia/nemotron-3-ultra-550b-a55b",
        description="Model for image generation (via NVIDIA)"
    )
    image_size: Literal["512x512", "768x768", "1024x1024", "1792x1024", "1024x1792"] = Field(
        default="1024x1024", description="Generated image size"
    )
    image_style: Optional[str] = Field(default=None, description="Style preset for images")


class WebhookSettings(BaseSettings):
    """Webhook server configuration."""
    model_config = SettingsConfigDict(
        env_prefix="WEBHOOK_",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = Field(default="0.0.0.0", description="Webhook server host")
    port: int = Field(default=8080, description="Webhook server port")
    ssl_cert: Optional[str] = Field(default=None, description="SSL certificate path")
    ssl_key: Optional[str] = Field(default=None, description="SSL key path")

    # Security
    secret_token: Optional[str] = Field(default=None, description="Shared secret for signature verification")
    allowed_ips: list[str] = Field(default_factory=list, description="Allowed IP ranges (CIDR)")

    # Rate limiting
    rate_limit: int = Field(default=100, description="Requests per minute per IP")
    rate_limit_burst: int = Field(default=20, description="Burst allowance")


class Settings(BaseSettings):
    """Main settings aggregator."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_nested_delimiter="__",
    )

    # Sub-settings (loaded from nested env vars like TG__API_ID)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    discord: DiscordSettings = Field(default_factory=DiscordSettings)
    twitter: TwitterSettings = Field(default_factory=TwitterSettings)
    brand: BrandSettings = Field(default_factory=BrandSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    analytics: AnalyticsSettings = Field(default_factory=AnalyticsSettings)
    ai: AIModelSettings = Field(default_factory=AIModelSettings)
    webhook: WebhookSettings = Field(default_factory=WebhookSettings)

    # Global settings
    environment: Literal["development", "staging", "production"] = Field(
        default="development", description="Runtime environment"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", description="Logging level"
    )
    log_format: Literal["json", "console"] = Field(
        default="console", description="Log output format"
    )

    # Data directories
    data_dir: Path = Field(default=Path("/root/.opsora/marketing"), description="Data directory")
    cache_dir: Path = Field(default=Path("/root/.opsora/marketing/cache"), description="Cache directory")

    @field_validator("data_dir", "cache_dir", mode="before")
    @classmethod
    def expand_path(cls, v: str | Path) -> Path:
        return Path(v).expanduser().resolve()

    def model_post_init(self, __context) -> None:
        """Create directories after initialization."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get global settings instance (singleton)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Force reload settings from environment."""
    global _settings
    _settings = Settings()
    return _settings


# Backwards compatibility - export individual config values
# These mirror the old config.py for gradual migration
TELEGRAM_SESSION = get_settings().telegram.session_path
TELEGRAM_API_ID = get_settings().telegram.api_id
TELEGRAM_API_HASH = get_settings().telegram.api_hash

DISCORD_TOKEN = get_settings().discord.token
DISCORD_API_BASE = get_settings().discord.api_base

TWITTER_API_KEY = get_settings().twitter.api_key
TWITTER_API_BASE = get_settings().twitter.api_base
TWITTER_LOGIN_COOKIES = get_settings().twitter.login_cookies or ""

BRAND_NAME = get_settings().brand.name
BRAND_HANDLE = get_settings().brand.handle
BRAND_COLOR = get_settings().brand.color
BRAND_EMAIL = get_settings().brand.email
BRAND_WEBSITE = get_settings().brand.website
BRAND_LOGO_URL = get_settings().brand.logo_url

TELEGRAM_CHANNELS = get_settings().telegram.target_channels
DISCORD_CHANNELS = get_settings().discord.target_channels

GMAIL_ACCOUNTS = [
    "cladiusweinert05@gmail.com",
    "jalankecil351@gmail.com",
]