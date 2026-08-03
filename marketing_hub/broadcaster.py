"""
Multi-Platform Broadcaster — Unified interface to post across ALL platforms.

Integrates:
- Telegram (via Telethon userbot)
- Discord (via discord_rest_mcp.py / REST API)
- Twitter/X (via twitterapi.io proxy)
- Gmail (via opsora_google_mcp.py)
- Landing Page updates (via Vercel API)
- GitHub (via gh CLI)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional

from .settings import get_settings
from .posting import (
    Platform, PostContent, PostTarget, PostResult,
    UnifiedPoster, TelegramPlatformPoster, DiscordPlatformPoster,
    TwitterPlatformPoster, create_post_content,
)
from .analytics import AnalyticsTracker, EventType

log = logging.getLogger("marketing.broadcaster")


class BroadcastStatus(str, Enum):
    """Status of a broadcast operation."""
    PENDING = "pending"
    SENDING = "sending"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(slots=True)
class BroadcastResult:
    """Result of a multi-platform broadcast."""
    id: str = ""
    status: BroadcastStatus = BroadcastStatus.PENDING
    platform_results: dict[str, list[PostResult]] = field(default_factory=dict)
    total_targets: int = 0
    successful: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    content_preview: str = ""

    @property
    def summary(self) -> str:
        """Get a human-readable summary."""
        lines = [
            f"📡 Broadcast {self.id}",
            f"   Status: {self.status.value}",
            f"   Targets: {self.successful}/{self.total_targets} successful",
        ]
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            lines.append(f"   Duration: {int(delta.total_seconds())}s")
        for platform, results in self.platform_results.items():
            ok = sum(1 for r in results if r.status == "ok")
            lines.append(f"   {platform}: {ok}/{len(results)}")
        if self.errors:
            lines.append(f"   Errors: {len(self.errors)}")
            for err in self.errors[:3]:
                lines.append(f"     ❌ {err}")
        return "\n".join(lines)


class Broadcaster:
    """
    Multi-platform broadcaster that posts content to all available services.

    Features:
    - Post to Telegram, Discord, Twitter, Gmail, Landing Page, GitHub
    - Automatic platform detection and formatting
    - Engagement tracking via AnalyticsTracker
    - Retry logic with exponential backoff
    - Rate limiting per platform
    - Broadcast to multiple targets per platform
    """

    def __init__(
        self,
        unified_poster: Optional[UnifiedPoster] = None,
        analytics: Optional[AnalyticsTracker] = None,
    ):
        self._poster = unified_poster or UnifiedPoster()
        self._analytics = analytics or AnalyticsTracker()
        self._connected = False

    async def connect(self) -> None:
        """Connect to all platform posters."""
        if not self._connected:
            await self._poster.connect()
            self._connected = True
            log.info("Broadcaster connected")

    async def disconnect(self) -> None:
        """Disconnect all platform posters."""
        if self._connected:
            await self._poster.disconnect()
            self._connected = False
            log.info("Broadcaster disconnected")

    async def __aenter__(self) -> Broadcaster:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    # =========================================================================
    # Core Broadcast Methods
    # =========================================================================

    async def broadcast(
        self,
        content: PostContent,
        platforms: Optional[list[Platform]] = None,
        telegram_targets: Optional[list[int | str]] = None,
        discord_channels: Optional[list[int]] = None,
        send_email: bool = False,
        email_recipients: Optional[list[str]] = None,
        update_landing_page: bool = False,
        create_github_release: bool = False,
        campaign_id: Optional[str] = None,
    ) -> BroadcastResult:
        """
        Broadcast content to multiple platforms.

        Args:
            content: Content to broadcast
            platforms: Specific platforms to target (default: all configured)
            telegram_targets: Override Telegram targets
            discord_channels: Override Discord channels
            send_email: Send as email via Gmail
            email_recipients: Email recipients (uses brand email if empty)
            update_landing_page: Update Vercel landing page
            create_github_release: Create GitHub release
            campaign_id: Campaign ID for tracking

        Returns:
            BroadcastResult with per-platform results
        """
        result = BroadcastResult(
            id=f"bcast_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            started_at=datetime.now(),
            content_preview=content.text[:100],
        )

        await self.connect()

        # Determine platforms
        if platforms is None:
            platforms = [Platform.TELEGRAM, Platform.DISCORD]

        tasks = []

        for platform in platforms:
            if platform == Platform.TELEGRAM:
                tasks.append(self._broadcast_telegram(content, telegram_targets, result))
            elif platform == Platform.DISCORD:
                tasks.append(self._broadcast_discord(content, discord_channels, result))
            elif platform == Platform.TWITTER:
                tasks.append(self._broadcast_twitter(content, result))

        if send_email:
            tasks.append(self._send_email(content, email_recipients, result))

        if update_landing_page:
            tasks.append(self._update_landing_page(content, result))

        if create_github_release:
            tasks.append(self._create_github_release(content, result))

        # Run all tasks concurrently
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Calculate totals
        for platform_results in result.platform_results.values():
            for pr in platform_results:
                result.total_targets += 1
                if pr.status == "ok":
                    result.successful += 1
                else:
                    result.failed += 1
                    if pr.error:
                        result.errors.append(f"[{pr.platform.value}] {pr.error}")

        result.status = (
            BroadcastStatus.COMPLETED if result.failed == 0
            else BroadcastStatus.PARTIAL if result.successful > 0
            else BroadcastStatus.FAILED
        )
        result.completed_at = datetime.now()

        # Track in analytics
        self._analytics.track_post_sent(
            platform="broadcaster",
            post_id=result.id,
            content_preview=content.text[:200],
            campaign_id=campaign_id or "",
            metadata={
                "platforms": [p.value for p in (platforms or [])],
                "successful": result.successful,
                "failed": result.failed,
            },
        )

        log.info(
            "Broadcast %s: %d/%d successful",
            result.id, result.successful, result.total_targets,
        )
        return result

    async def _broadcast_telegram(
        self,
        content: PostContent,
        targets: Optional[list[int | str]],
        result: BroadcastResult,
    ) -> None:
        """Broadcast to Telegram."""
        poster = self._poster.get_poster(Platform.TELEGRAM)
        if not poster:
            result.errors.append("Telegram poster not configured")
            return

        try:
            if targets:
                tg_targets = [PostTarget(Platform.TELEGRAM, t) for t in targets]
            else:
                settings = get_settings().telegram
                tg_targets = [
                    PostTarget(Platform.TELEGRAM, ch)
                    for ch in settings.target_channels + settings.target_groups
                ]

            if not tg_targets:
                log.warning("No Telegram targets configured")
                return

            tg_results = await poster.broadcast(tg_targets, content)
            result.platform_results["telegram"] = tg_results

            for r in tg_results:
                if r.status == "ok":
                    self._analytics.track_post_sent(
                        platform="telegram",
                        post_id=r.message_id or "",
                        content_preview=content.text[:200],
                        channel_id=str(r.target.identifier),
                        channel_name=r.target.name or "",
                    )

        except Exception as e:
            log.error("Telegram broadcast failed: %s", e)
            result.errors.append(f"Telegram: {e}")

    async def _broadcast_discord(
        self,
        content: PostContent,
        channels: Optional[list[int]],
        result: BroadcastResult,
    ) -> None:
        """Broadcast to Discord."""
        poster = self._poster.get_poster(Platform.DISCORD)
        if not poster:
            result.errors.append("Discord poster not configured")
            return

        try:
            if channels:
                dc_targets = [PostTarget(Platform.DISCORD, ch) for ch in channels]
            else:
                settings = get_settings().discord
                dc_targets = [
                    PostTarget(Platform.DISCORD, ch)
                    for ch in settings.target_channels
                ]

            if not dc_targets:
                log.warning("No Discord targets configured")
                return

            dc_results = await poster.broadcast(dc_targets, content)
            result.platform_results["discord"] = dc_results

            for r in dc_results:
                if r.status == "ok":
                    self._analytics.track_post_sent(
                        platform="discord",
                        post_id=r.message_id or "",
                        content_preview=content.text[:200],
                        channel_id=str(r.target.identifier),
                        channel_name=r.target.name or "",
                    )

        except Exception as e:
            log.error("Discord broadcast failed: %s", e)
            result.errors.append(f"Discord: {e}")

    async def _broadcast_twitter(
        self,
        content: PostContent,
        result: BroadcastResult,
    ) -> None:
        """Post to Twitter/X via twitterapi.io."""
        poster = self._poster.get_poster(Platform.TWITTER)
        if not poster:
            result.errors.append("Twitter poster not configured")
            return

        try:
            settings = get_settings().twitter
            if not settings.login_cookies:
                log.warning("Twitter write requires login cookies — skipping")
                return

            target = PostTarget(Platform.TWITTER, "me")
            tw_result = await poster.post(target, content)
            result.platform_results["twitter"] = [tw_result]

            if tw_result.status == "ok":
                self._analytics.track_post_sent(
                    platform="twitter",
                    post_id=tw_result.message_id or "",
                    content_preview=content.text[:200],
                )

        except Exception as e:
            log.error("Twitter post failed: %s", e)
            result.errors.append(f"Twitter: {e}")

    async def _send_email(
        self,
        content: PostContent,
        recipients: Optional[list[str]],
        result: BroadcastResult,
    ) -> None:
        """Send content as email via Gmail MCP."""
        try:
            sys.path.insert(0, str(Path("/root/opsora-cli/opsora_cmd").resolve()))
            email_to = recipients or [get_settings().brand.email]
            subject = f"[Opsora AI] {content.text[:50]}..."

            email_body = f"""
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <div style="background: linear-gradient(135deg, #8b5cf6, #6d28d9); padding: 20px; text-align: center;">
        <h1 style="color: white; margin: 0;">{get_settings().brand.name}</h1>
    </div>
    <div style="padding: 20px; line-height: 1.6;">
        {content.text}
    </div>
    <div style="padding: 20px; text-align: center; color: #666; font-size: 12px;">
        <p>© {datetime.now().year} {get_settings().brand.name}. All rights reserved.</p>
        <p><a href="{get_settings().brand.website}">{get_settings().brand.website}</a></p>
    </div>
</body>
</html>
"""

            email_file = get_settings().data_dir / f"email_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            email_file.write_text(email_body)

            for recipient in email_to:
                try:
                    proc = subprocess.run(
                        [
                            "node", "/root/opsora-cli/opsora_cmd/opsora-gmail.js",
                            "send", "--to", recipient,
                            "--subject", subject, "--body", str(email_file),
                        ],
                        capture_output=True, text=True, timeout=30,
                    )
                    status = "ok" if proc.returncode == 0 else "error"
                    result.platform_results.setdefault("email", []).append(PostResult(
                        platform=Platform.TELEGRAM,
                        target=PostTarget(Platform.TELEGRAM, recipient),
                        status=status,
                    ))
                    if status == "ok":
                        self._analytics.track_post_sent(
                            platform="email", post_id=recipient,
                            content_preview=content.text[:200],
                        )
                except Exception as e:
                    result.errors.append(f"Email to {recipient}: {e}")

            email_file.unlink(missing_ok=True)

        except Exception as e:
            log.error("Email send failed: %s", e)
            result.errors.append(f"Email: {e}")

    async def _update_landing_page(
        self,
        content: PostContent,
        result: BroadcastResult,
    ) -> None:
        """Update the Vercel landing page."""
        try:
            vercel_token = os.environ.get("VERCEL_TOKEN", "")
            if not vercel_token:
                log.warning("VERCEL_TOKEN not set — skipping landing page update")
                return

            import urllib.request
            hook_url = "https://api.vercel.com/v1/integrations/deploy"
            req = urllib.request.Request(
                f"{hook_url}/prj_xxx?vercel_token={vercel_token}",
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                result.platform_results.setdefault("landing_page", []).append(PostResult(
                    platform=Platform.TELEGRAM,
                    target=PostTarget(Platform.TELEGRAM, "vercel"),
                    status="ok",
                    message_id=data.get("id", ""),
                ))
                log.info("Landing page redeploy triggered: %s", data.get("id"))

        except Exception as e:
            log.error("Landing page update failed: %s", e)
            result.errors.append(f"Landing page: {e}")

    async def _create_github_release(
        self,
        content: PostContent,
        result: BroadcastResult,
    ) -> None:
        """Create a GitHub release with the content."""
        try:
            tag = f"v{datetime.now().strftime('%Y%m%d.%H%M%S')}"
            title = content.text[:80].split("\n")[0]

            proc = subprocess.run(
                ["gh", "release", "create", tag, "--title", title,
                 "--notes", content.text[:500], "--repo", "opsora/opsora-cli"],
                capture_output=True, text=True, timeout=30,
            )

            if proc.returncode == 0:
                result.platform_results.setdefault("github", []).append(PostResult(
                    platform=Platform.TELEGRAM,
                    target=PostTarget(Platform.TELEGRAM, "github"),
                    status="ok",
                    url=proc.stdout.strip(),
                ))
                log.info("GitHub release created: %s", tag)
            else:
                result.errors.append(f"GitHub release failed: {proc.stderr[:200]}")

        except Exception as e:
            log.error("GitHub release failed: %s", e)
            result.errors.append(f"GitHub: {e}")

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    async def post_to_all(
        self,
        text: str,
        campaign_id: Optional[str] = None,
        platforms: Optional[list[Platform]] = None,
    ) -> BroadcastResult:
        """Post text to all configured platforms."""
        content = create_post_content(
            text=text, campaign_id=campaign_id, utm_source="broadcaster",
        )
        return await self.broadcast(content=content, platforms=platforms, campaign_id=campaign_id)

    async def broadcast_telegram_groups(
        self, text: str, group_ids: Optional[list[int]] = None,
    ) -> BroadcastResult:
        """Broadcast text to Telegram groups only."""
        content = create_post_content(text=text, utm_source="telegram_broadcast")
        return await self.broadcast(content=content, platforms=[Platform.TELEGRAM], telegram_targets=group_ids)

    async def send_newsletter(
        self, subject: str, body: str, recipients: Optional[list[str]] = None,
    ) -> BroadcastResult:
        """Send an email newsletter."""
        content = create_post_content(text=f"{subject}\n\n{body}", utm_source="newsletter")
        return await self.broadcast(content=content, platforms=[], send_email=True, email_recipients=recipients)

    async def announce_update(self, version: str, changes: list[str]) -> BroadcastResult:
        """Announce a new version/update across all platforms."""
        text = (
            f"🚀 **{get_settings().brand.name} v{version}**\n\n"
            + "\n".join(f"• {change}" for change in changes)
            + f"\n\n🔗 {get_settings().brand.website}"
        )
        content = create_post_content(text=text, utm_source="update_announcement")
        return await self.broadcast(
            content=content, platforms=[Platform.TELEGRAM, Platform.DISCORD],
            create_github_release=True,
        )

    async def discover_all_targets(self) -> dict[str, list[dict]]:
        """Discover available targets on all platforms."""
        await self.connect()
        targets: dict[str, list[dict]] = {}

        try:
            tg_poster = self._poster.get_poster(Platform.TELEGRAM)
            if tg_poster:
                tg_targets = await tg_poster.discover_targets()
                targets["telegram"] = [
                    {"id": t.identifier, "name": t.name, "type": t.metadata.get("type", "")}
                    for t in tg_targets
                ]
        except Exception as e:
            log.warning("Telegram discovery failed: %s", e)

        try:
            dc_poster = self._poster.get_poster(Platform.DISCORD)
            if dc_poster:
                dc_targets = await dc_poster.discover_targets()
                targets["discord"] = [
                    {"id": t.identifier, "name": t.name} for t in dc_targets
                ]
        except Exception as e:
            log.warning("Discord discovery failed: %s", e)

        return targets