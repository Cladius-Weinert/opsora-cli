"""Configuration for Opsora Marketing Hub - Backwards Compatibility Layer

This module re-exports settings from the new Pydantic-based settings.py
for backwards compatibility with existing code.
"""
from .settings import (
    get_settings,
    reload_settings,
    TELEGRAM_SESSION,
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    DISCORD_TOKEN,
    DISCORD_API_BASE,
    TWITTER_API_KEY,
    TWITTER_API_BASE,
    TWITTER_LOGIN_COOKIES,
    BRAND_NAME,
    BRAND_HANDLE,
    BRAND_COLOR,
    BRAND_EMAIL,
    BRAND_WEBSITE,
    BRAND_LOGO_URL,
    TELEGRAM_CHANNELS,
    DISCORD_CHANNELS,
    GMAIL_ACCOUNTS,
)

__all__ = [
    "get_settings",
    "reload_settings",
    "TELEGRAM_SESSION",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "DISCORD_TOKEN",
    "DISCORD_API_BASE",
    "TWITTER_API_KEY",
    "TWITTER_API_BASE",
    "TWITTER_LOGIN_COOKIES",
    "BRAND_NAME",
    "BRAND_HANDLE",
    "BRAND_COLOR",
    "BRAND_EMAIL",
    "BRAND_WEBSITE",
    "BRAND_LOGO_URL",
    "TELEGRAM_CHANNELS",
    "DISCORD_CHANNELS",
    "GMAIL_ACCOUNTS",
]
