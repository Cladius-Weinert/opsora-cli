"""
Unified Posting Interface - Multi-platform posting with platform-specific formatting.

Provides a single interface for posting to Telegram, Discord, Twitter, and other platforms
with automatic formatting optimization per platform.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
from pathlib import Path

from .settings import get_settings, BrandSettings
from .telegram_poster import TelegramPoster, TelegramTarget, SendResult as TGSendResult
from .discord_poster import DiscordPoster, DiscordChannel, SendResult as DCSendResult, EmbedBuilder

log = logging.getLogger("marketing.posting")


class Platform(str, Enum):
    """Supported platforms."""
    TELEGRAM = "telegram"
    DISCORD = "discord"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    THREADS = "threads"
    MASTODON = "mastodon"


class PostFormat(str, Enum):
    """Post format types."""
    TEXT = "text"
    MARKDOWN = "markdown"
    HTML = "html"
    EMBED = "embed"
    THREAD = "thread"


@dataclass(slots=True)
class MediaAttachment:
    """Media attachment for posts."""
    path: str | Path | bytes
    type: Literal["photo", "video", "document", "audio", "sticker"] = "photo"
    caption: Optional[str] = None
    filename: Optional[str] = None
    alt_text: Optional[str] = None  # For accessibility

    def __post_init__(self):
        if isinstance(self.path, Path):
            self.path = str(self.path)


@dataclass(slots=True)
class PostTarget:
    """Target for a post."""
    platform: Platform
    identifier: str | int  # Channel ID, username, etc.
    name: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class PostContent:
    """Content to post, with platform-specific variants."""
    # Core content
    text: str = ""
    html: Optional[str] = None
    markdown: Optional[str] = None

    # Platform-specific overrides
    telegram_text: Optional[str] = None
    discord_embeds: Optional[list[dict]] = None
    twitter_text: Optional[str] = None
    twitter_thread: Optional[list[str]] = None

    # Media
    media: list[MediaAttachment] = field(default_factory=list)

    # Formatting
    format: PostFormat = PostFormat.MARKDOWN
    disable_web_page_preview: bool = False

    # Scheduling
    scheduled_at: Optional[datetime] = None

    # Tracking
    campaign_id: Optional[str] = None
    utm_params: dict = field(default_factory=dict)

    def get_text(self, platform: Platform) -> str:
        """Get platform-optimized text."""
        if platform == Platform.TELEGRAM and self.telegram_text:
            return self.telegram_text
        if platform == Platform.TWITTER and self.twitter_text:
            return self.twitter_text
        if platform == Platform.DISCORD and self.discord_embeds:
            # Discord uses embeds, but we can extract description
            for embed in self.discord_embeds:
                if embed.get("description"):
                    return embed["description"]
        return self.markdown or self.text

    def get_discord_embeds(self) -> Optional[list[dict]]:
        """Get Discord embeds."""
        if self.discord_embeds:
            return self.discord_embeds
        # Auto-generate from text
        if self.text:
            return [{
                "description": self.text[:4096],
                "color": 0x8b5cf6,
            }]
        return None

    def get_twitter_thread(self) -> Optional[list[str]]:
        """Get Twitter thread."""
        if self.twitter_thread:
            return self.twitter_thread
        # Auto-split long text
        if self.twitter_text:
            return [self.twitter_text]
        if self.text and len(self.text) > 280:
            # Simple split - could be smarter
            chunks = [self.text[i:i+280] for i in range(0, len(self.text), 280)]
            return chunks
        return None


@dataclass(slots=True)
class PostResult:
    """Result of a post operation."""
    platform: Platform
    target: PostTarget
    status: Literal["ok", "error", "skipped"]
    message_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[dict] = None


class PlatformPoster(ABC):
    """Abstract base class for platform posters."""

    @property
    @abstractmethod
    def platform(self) -> Platform:
        """Platform this poster handles."""
        pass

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""
        pass

    @abstractmethod
    async def post(self, target: PostTarget, content: PostContent) -> PostResult:
        """Post content to target."""
        pass

    @abstractmethod
    async def broadcast(self, targets: list[PostTarget], content: PostContent) -> list[PostResult]:
        """Broadcast to multiple targets."""
        pass

    @abstractmethod
    async def discover_targets(self) -> list[PostTarget]:
        """Discover available targets."""
        pass

    async def __aenter__(self) -> PlatformPoster:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()


class TelegramPlatformPoster(PlatformPoster):
    """Telegram platform poster."""

    def __init__(self, poster: Optional[TelegramPoster] = None):
        self._poster = poster
        self._owns_poster = poster is None

    @property
    def platform(self) -> Platform:
        return Platform.TELEGRAM

    async def connect(self) -> None:
        if self._poster is None:
            self._poster = TelegramPoster()
        await self._poster.connect()

    async def disconnect(self) -> None:
        if self._poster and self._owns_poster:
            await self._poster.disconnect()

    async def post(self, target: PostTarget, content: PostContent) -> PostResult:
        assert self._poster is not None

        text = content.get_text(Platform.TELEGRAM)

        # Build inline keyboard if needed
        buttons = None
        if content.utm_params:
            # Add CTA button with UTM link
            from urllib.parse import urlencode
            base_url = get_settings().brand.website
            utm = urlencode(content.utm_params)
            buttons = [[{
                "text": "🔗 Learn More",
                "url": f"{base_url}?{utm}",
            }]]

        try:
            tg_result = await self._poster.send(
                target=target.identifier,
                text=text,
                parse_mode="md",
                file=content.media[0].path if content.media else None,
                caption=content.media[0].caption if content.media else None,
                buttons=buttons,
                silent=content.metadata.get("silent", False),
            )

            return PostResult(
                platform=Platform.TELEGRAM,
                target=target,
                status=tg_result.status,
                message_id=str(tg_result.message_id) if tg_result.message_id else None,
                error=tg_result.error,
            )
        except Exception as e:
            log.error("Telegram post failed: %s", e)
            return PostResult(
                platform=Platform.TELEGRAM,
                target=target,
                status="error",
                error=str(e),
            )

    async def broadcast(self, targets: list[PostTarget], content: PostContent) -> list[PostResult]:
        assert self._poster is not None

        tg_targets = [t.identifier for t in targets]
        text = content.get_text(Platform.TELEGRAM)

        buttons = None
        if content.utm_params:
            from urllib.parse import urlencode
            base_url = get_settings().brand.website
            utm = urlencode(content.utm_params)
            buttons = [[{"text": "🔗 Learn More", "url": f"{base_url}?{utm}"}]]

        tg_results = await self._poster.broadcast(
            tg_targets,
            text,
            parse_mode="md",
            file=content.media[0].path if content.media else None,
            caption=content.media[0].caption if content.media else None,
            buttons=buttons,
        )

        return [
            PostResult(
                platform=Platform.TELEGRAM,
                target=targets[i],
                status=r.status,
                message_id=str(r.message_id) if r.message_id else None,
                error=r.error,
            )
            for i, r in enumerate(tg_results)
        ]

    async def discover_targets(self) -> list[PostTarget]:
        assert self._poster is not None
        chats = await self._poster.list_groups_and_channels()
        return [
            PostTarget(
                platform=Platform.TELEGRAM,
                identifier=c.id,
                name=c.title,
                metadata={"type": c.type, "username": c.username},
            )
            for c in chats
        ]


class DiscordPlatformPoster(PlatformPoster):
    """Discord platform poster."""

    def __init__(self, poster: Optional[DiscordPoster] = None):
        self._poster = poster
        self._owns_poster = poster is None

    @property
    def platform(self) -> Platform:
        return Platform.DISCORD

    async def connect(self) -> None:
        if self._poster is None:
            self._poster = DiscordPoster()
        await self._poster.connect()

    async def disconnect(self) -> None:
        if self._poster and self._owns_poster:
            await self._poster.disconnect()

    async def post(self, target: PostTarget, content: PostContent) -> PostResult:
        assert self._poster is not None

        embeds = content.get_discord_embeds()
        components = None

        # Add CTA button with UTM link
        if content.utm_params:
            from urllib.parse import urlencode
            base_url = get_settings().brand.website
            utm = urlencode(content.utm_params)
            components = [DiscordPoster.create_action_row(
                DiscordPoster.create_button(
                    "Learn More",
                    custom_id="",
                    style=5,  # Link button
                    url=f"{base_url}?{utm}",
                    emoji="🔗",
                )
            )]

        try:
            dc_result = await self._poster.send_message(
                channel_id=int(target.identifier),
                content=content.text if not embeds else None,
                embeds=embeds,
                components=components,
            )

            return PostResult(
                platform=Platform.DISCORD,
                target=target,
                status=dc_result.status,
                message_id=dc_result.message_id,
                error=dc_result.error,
            )
        except Exception as e:
            log.error("Discord post failed: %s", e)
            return PostResult(
                platform=Platform.DISCORD,
                target=target,
                status="error",
                error=str(e),
            )

    async def broadcast(self, targets: list[PostTarget], content: PostContent) -> list[PostResult]:
        assert self._poster is not None

        dc_targets = [int(t.identifier) for t in targets]
        embeds = content.get_discord_embeds()

        components = None
        if content.utm_params:
            from urllib.parse import urlencode
            base_url = get_settings().brand.website
            utm = urlencode(content.utm_params)
            components = [DiscordPoster.create_action_row(
                DiscordPoster.create_button(
                    "Learn More",
                    custom_id="",
                    style=5,
                    url=f"{base_url}?{utm}",
                    emoji="🔗",
                )
            )]

        dc_results = await self._poster.broadcast(
            dc_targets,
            content=content.text if not embeds else None,
            embeds=embeds,
            components=components,
        )

        return [
            PostResult(
                platform=Platform.DISCORD,
                target=targets[i],
                status=r.status,
                message_id=r.message_id,
                error=r.error,
            )
            for i, r in enumerate(dc_results)
        ]

    async def discover_targets(self) -> list[PostTarget]:
        assert self._poster is not None
        guilds = await self._poster.list_guilds()
        targets = []
        for guild in guilds:
            channels = await self._poster.list_channels(guild.id)
            for ch in channels:
                if ch.type == 0:  # Text channel
                    targets.append(PostTarget(
                        platform=Platform.DISCORD,
                        identifier=ch.id,
                        name=f"{guild.name} / #{ch.name}",
                        metadata={"guild_id": guild.id, "guild_name": guild.name, "topic": ch.topic},
                    ))
        return targets


class TwitterPlatformPoster(PlatformPoster):
    """Twitter/X platform poster via twitterapi.io."""

    def __init__(self):
        self._settings = get_settings().twitter

    @property
    def platform(self) -> Platform:
        return Platform.TWITTER

    async def connect(self) -> None:
        # No persistent connection needed for REST API
        pass

    async def disconnect(self) -> None:
        pass

    async def post(self, target: PostTarget, content: PostContent) -> PostResult:
        # Twitter posting requires twitterapi.io with login cookies for write
        # For now, return not implemented
        return PostResult(
            platform=Platform.TWITTER,
            target=target,
            status="skipped",
            error="Twitter posting not yet implemented (requires login cookies)",
        )

    async def broadcast(self, targets: list[PostTarget], content: PostContent) -> list[PostResult]:
        return [await self.post(t, content) for t in targets]

    async def discover_targets(self) -> list[PostTarget]:
        # Could fetch own account info
        return []


class UnifiedPoster:
    """
    Unified interface for posting to multiple platforms.

    Usage:
        poster = UnifiedPoster()
        await poster.connect()

        content = PostContent(
            text="Hello world!",
            media=[MediaAttachment("image.jpg")],
            utm_params={"utm_source": "telegram", "utm_medium": "social"}
        )

        # Post to specific targets
        results = await poster.post([
            PostTarget(Platform.TELEGRAM, -1001234567890),
            PostTarget(Platform.DISCORD, 1234567890),
        ], content)

        # Or broadcast to all configured targets
        results = await poster.broadcast_all(content)

        await poster.disconnect()
    """

    def __init__(
        self,
        telegram_poster: Optional[TelegramPlatformPoster] = None,
        discord_poster: Optional[DiscordPlatformPoster] = None,
        twitter_poster: Optional[TwitterPlatformPoster] = None,
    ):
        self._posters: dict[Platform, PlatformPoster] = {}

        if telegram_poster:
            self._posters[Platform.TELEGRAM] = telegram_poster
        if discord_poster:
            self._posters[Platform.DISCORD] = discord_poster
        if twitter_poster:
            self._posters[Platform.TWITTER] = twitter_poster

        self._connected = False

    def add_poster(self, poster: PlatformPoster) -> None:
        """Add a platform poster."""
        self._posters[poster.platform] = poster

    def get_poster(self, platform: Platform) -> Optional[PlatformPoster]:
        """Get poster for platform."""
        return self._posters.get(platform)

    async def connect(self) -> None:
        """Connect all posters."""
        for poster in self._posters.values():
            await poster.connect()
        self._connected = True
        log.info("Unified poster connected: %s", list(self._posters.keys()))

    async def disconnect(self) -> None:
        """Disconnect all posters."""
        for poster in self._posters.values():
            await poster.disconnect()
        self._connected = False
        log.info("Unified poster disconnected")

    async def post(
        self,
        targets: list[PostTarget],
        content: PostContent,
    ) -> list[PostResult]:
        """
        Post content to specific targets.

        Args:
            targets: List of PostTarget (platform + identifier)
            content: Content to post

        Returns:
            List of PostResult
        """
        if not self._connected:
            await self.connect()

        # Group targets by platform
        by_platform: dict[Platform, list[PostTarget]] = {}
        for t in targets:
            by_platform.setdefault(t.platform, []).append(t)

        # Post to each platform
        all_results = []
        for platform, platform_targets in by_platform.items():
            poster = self._posters.get(platform)
            if not poster:
                log.warning("No poster for platform: %s", platform)
                for t in platform_targets:
                    all_results.append(PostResult(
                        platform=platform,
                        target=t,
                        status="skipped",
                        error=f"No poster configured for {platform.value}",
                    ))
                continue

            results = await poster.broadcast(platform_targets, content)
            all_results.extend(results)

        return all_results

    async def broadcast_all(self, content: PostContent) -> list[PostResult]:
        """Broadcast to all discovered targets across all platforms."""
        if not self._connected:
            await self.connect()

        all_results = []
        for poster in self._posters.values():
            try:
                targets = await poster.discover_targets()
                if targets:
                    results = await poster.broadcast(targets, content)
                    all_results.extend(results)
            except Exception as e:
                log.error("Broadcast failed for %s: %s", poster.platform, e)

        return all_results

    async def discover_all(self) -> dict[Platform, list[PostTarget]]:
        """Discover targets on all platforms."""
        if not self._connected:
            await self.connect()

        result = {}
        for platform, poster in self._posters.items():
            try:
                result[platform] = await poster.discover_targets()
            except Exception as e:
                log.error("Discovery failed for %s: %s", platform, e)
                result[platform] = []
        return result

    async def __aenter__(self) -> UnifiedPoster:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()


# =========================================================================
# Content Formatting Helpers
# =========================================================================

def format_for_telegram(text: str, *, escape: bool = True) -> str:
    """Format text for Telegram MarkdownV2."""
    if not escape:
        return text
    # Escape special MarkdownV2 characters
    special = r"_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_for_discord(text: str) -> str:
    """Format text for Discord (standard markdown)."""
    # Discord uses standard markdown, no special escaping needed
    return text


def format_for_twitter(text: str, max_len: int = 280) -> str:
    """Format text for Twitter."""
    if len(text) <= max_len:
        return text
    # Truncate with ellipsis
    return text[:max_len - 3] + "..."


def create_utm_url(
    base_url: str,
    source: str,
    medium: str = "social",
    campaign: Optional[str] = None,
    content: Optional[str] = None,
    term: Optional[str] = None,
) -> str:
    """Create URL with UTM parameters."""
    from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

    parsed = urlparse(base_url)
    params = parse_qs(parsed.query)

    params["utm_source"] = [source]
    params["utm_medium"] = [medium]
    if campaign:
        params["utm_campaign"] = [campaign]
    if content:
        params["utm_content"] = [content]
    if term:
        params["utm_term"] = [term]

    new_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def create_post_content(
    text: str,
    *,
    brand: Optional[BrandSettings] = None,
    platform: Optional[Platform] = None,
    campaign_id: Optional[str] = None,
    utm_source: Optional[str] = None,
    media: Optional[list[MediaAttachment]] = None,
) -> PostContent:
    """Create PostContent with platform-specific formatting."""
    brand = brand or get_settings().brand

    # Generate platform variants
    telegram_text = format_for_telegram(text)
    discord_embeds = [{
        "description": format_for_discord(text),
        "color": int(brand.color.lstrip("#"), 16),
        "footer": {"text": brand.name},
    }]
    twitter_text = format_for_twitter(text)

    # UTM params
    utm_params = {}
    if utm_source:
        utm_params["utm_source"] = utm_source
        utm_params["utm_medium"] = "social"
        if campaign_id:
            utm_params["utm_campaign"] = campaign_id

    return PostContent(
        text=text,
        telegram_text=telegram_text,
        discord_embeds=discord_embeds,
        twitter_text=twitter_text,
        media=media or [],
        campaign_id=campaign_id,
        utm_params=utm_params,
    )


# Convenience function
async def create_unified_poster(
    telegram_session: Optional[str] = None,
    discord_token: Optional[str] = None,
    discord_gateway: bool = False,
) -> UnifiedPoster:
    """Create a UnifiedPoster with configured platform posters."""
    posters = {}

    if telegram_session or get_settings().telegram.session_path:
        tg = TelegramPlatformPoster()
        posters[Platform.TELEGRAM] = tg

    if discord_token or get_settings().discord.token:
        dc = DiscordPlatformPoster()
        posters[Platform.DISCORD] = dc

    if get_settings().twitter.api_key:
        tw = TwitterPlatformPoster()
        posters[Platform.TWITTER] = tw

    return UnifiedPoster(**posters)