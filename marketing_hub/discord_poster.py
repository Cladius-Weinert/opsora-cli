"""
Discord Poster - Enhanced with slash commands, rich embeds, server management, webhooks.

Uses discord.py for gateway connection and REST API for simple posting.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import discord
from discord import app_commands
from discord.ext import commands

from .settings import get_settings, DiscordSettings

log = logging.getLogger("marketing.discord")


@dataclass(slots=True)
class DiscordChannel:
    """Represents a Discord channel."""
    id: int
    name: str
    type: int  # 0=text, 1=DM, 2=voice, 4=category, 5=announcement, 11=thread, etc.
    guild_id: Optional[int] = None
    guild_name: Optional[str] = None
    topic: Optional[str] = None
    nsfw: bool = False
    parent_id: Optional[int] = None


@dataclass(slots=True)
class DiscordGuild:
    """Represents a Discord guild/server."""
    id: int
    name: str
    icon: Optional[str] = None
    owner_id: Optional[int] = None
    member_count: int = 0
    features: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SendResult:
    """Result of a send operation."""
    channel_id: int
    status: Literal["ok", "error"]
    message_id: Optional[str] = None
    error: Optional[str] = None


class DiscordPosterError(Exception):
    """Base exception for Discord poster errors."""
    pass


class DiscordAuthError(DiscordPosterError):
    """Authentication error."""
    pass


class DiscordRateLimitError(DiscordPosterError):
    """Rate limit exceeded."""
    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after}s")


class DiscordPoster:
    """
    Enhanced Discord poster with:
    - REST API mode (no gateway) for simple posting
    - Gateway mode (discord.py) for slash commands, events, real-time
    - Rich embeds with components (buttons, selects)
    - Slash command registration and handling
    - Server/guild management
    - Thread support for announcements
    - Webhook support
    - Auto-mod integration
    """

    def __init__(
        self,
        settings: Optional[DiscordSettings] = None,
        use_gateway: bool = False,
    ):
        self.settings = settings or get_settings().discord
        self.use_gateway = use_gateway or self.settings.use_gateway
        self._bot: Optional[commands.Bot] = None
        self._tree: Optional[app_commands.CommandTree] = None
        self._http_session: Any = None  # aiohttp session for REST
        self._ready = asyncio.Event()
        self._command_handlers: dict[str, callable] = {}
        self._component_handlers: dict[str, callable] = {}

    # =========================================================================
    # Connection Management
    # =========================================================================

    async def connect(self) -> None:
        """Establish connection to Discord."""
        if self.use_gateway:
            await self._connect_gateway()
        else:
            await self._connect_rest()
        log.info("Discord connected (mode: %s)", "gateway" if self.use_gateway else "REST")

    async def _connect_gateway(self) -> None:
        """Connect using discord.py gateway."""
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True
        intents.guild_reactions = True
        intents.dm_messages = True

        self._bot = commands.Bot(
            command_prefix="!",
            intents=intents,
            application_id=self.settings.application_id,
        )
        self._tree = self._bot.tree

        # Event handlers
        @self._bot.event
        async def on_ready():
            log.info("Gateway ready: %s (ID: %s)", self._bot.user, self._bot.user.id)
            self._ready.set()

        @self._bot.event
        async def on_interaction(interaction: discord.Interaction):
            await self._handle_interaction(interaction)

        # Start bot
        asyncio.create_task(self._bot.start(self.settings.token))
        await self._ready.wait()

        # Sync commands
        await self._sync_commands()

    async def _connect_rest(self) -> None:
        """Initialize REST-only mode."""
        import aiohttp
        self._http_session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bot {self.settings.token}",
                "Content-Type": "application/json",
                "User-Agent": "OpsoraBot/2.0",
            },
            base_url=self.settings.api_base,
        )
        # Verify token
        await self.get_bot_info()

    async def disconnect(self) -> None:
        """Close connections."""
        if self._bot:
            await self._bot.close()
            self._bot = None
            self._tree = None
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
        self._ready.clear()
        log.info("Discord disconnected")

    async def __aenter__(self) -> DiscordPoster:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    # =========================================================================
    # REST API Methods (work in both modes)
    # =========================================================================

    async def _api(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        """Make REST API call."""
        if self._http_session:
            # Use aiohttp
            async with self._http_session.request(method, path, json=data) as resp:
                if resp.status == 429:
                    retry = float(resp.headers.get("Retry-After", 1))
                    raise DiscordRateLimitError(retry)
                if resp.status >= 400:
                    text = await resp.text()
                    raise DiscordPosterError(f"Discord API {resp.status}: {text}")
                return await resp.json()
        else:
            # Fallback to urllib (sync, for backwards compat)
            import asyncio
            return await asyncio.to_thread(self._api_sync, method, path, data)

    def _api_sync(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        """Sync API call using urllib."""
        url = f"{self.settings.api_base}{path}"
        body = json.dumps(data).encode() if data else None
        req = Request(url, data=body, headers={
            "Authorization": f"Bot {self.settings.token}",
            "Content-Type": "application/json",
            "User-Agent": "OpsoraBot/2.0",
        }, method=method)
        try:
            with urlopen(req) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            err = e.read().decode()
            if e.code == 429:
                import json as json_lib
                retry = json_lib.loads(err).get("retry_after", 1)
                raise DiscordRateLimitError(retry)
            raise DiscordPosterError(f"Discord API {e.code}: {err}")

    # =========================================================================
    # Bot Info & Discovery
    # =========================================================================

    async def get_bot_info(self) -> dict:
        """Get bot user info."""
        return await self._api("GET", "/users/@me")

    async def list_guilds(self) -> list[DiscordGuild]:
        """List guilds the bot is in."""
        data = await self._api("GET", "/users/@me/guilds")
        return [
            DiscordGuild(
                id=g["id"],
                name=g["name"],
                icon=g.get("icon"),
                owner_id=g.get("owner_id"),
                member_count=g.get("approximate_member_count", 0),
                features=g.get("features", []),
            )
            for g in data
        ]

    async def list_channels(self, guild_id: int) -> list[DiscordChannel]:
        """List channels in a guild."""
        data = await self._api("GET", f"/guilds/{guild_id}/channels")
        return [
            DiscordChannel(
                id=c["id"],
                name=c["name"],
                type=c["type"],
                guild_id=guild_id,
                topic=c.get("topic"),
                nsfw=c.get("nsfw", False),
                parent_id=c.get("parent_id"),
            )
            for c in data
        ]

    async def get_channel(self, channel_id: int) -> DiscordChannel:
        """Get channel info."""
        data = await self._api("GET", f"/channels/{channel_id}")
        return DiscordChannel(
            id=data["id"],
            name=data["name"],
            type=data["type"],
            guild_id=data.get("guild_id"),
            topic=data.get("topic"),
            nsfw=data.get("nsfw", False),
            parent_id=data.get("parent_id"),
        )

    async def get_guild(self, guild_id: int) -> DiscordGuild:
        """Get guild info."""
        data = await self._api("GET", f"/guilds/{guild_id}")
        return DiscordGuild(
            id=data["id"],
            name=data["name"],
            icon=data.get("icon"),
            owner_id=data.get("owner_id"),
            member_count=data.get("approximate_member_count", 0),
            features=data.get("features", []),
        )

    # =========================================================================
    # Message Sending
    # =========================================================================

    async def send_message(
        self,
        channel_id: int,
        content: Optional[str] = None,
        *,
        embeds: Optional[list[dict | discord.Embed]] = None,
        components: Optional[list[dict]] = None,
        files: Optional[list[dict]] = None,
        thread_id: Optional[int] = None,
        flags: int = 0,
    ) -> SendResult:
        """
        Send a message to a channel.

        Args:
            channel_id: Target channel ID
            content: Message text (max 2000 chars)
            embeds: List of embed dicts or discord.Embed objects
            components: Message components (buttons, selects)
            files: List of {"filename": "...", "content": bytes} for multipart
            thread_id: Thread ID to send in
            flags: Message flags (e.g., 1<<6 for SUPPRESS_EMBEDS)

        Returns:
            SendResult
        """
        # Convert embeds to dict
        embed_dicts = []
        if embeds:
            for e in embeds:
                if isinstance(e, discord.Embed):
                    embed_dicts.append(e.to_dict())
                else:
                    embed_dicts.append(e)

        # Convert components to Discord format
        component_dicts = []
        if components:
            for row in components:
                if isinstance(row, dict) and "type" in row:
                    component_dicts.append(row)
                elif isinstance(row, list):
                    component_dicts.append({"type": 1, "components": row})

        payload = {
            "content": content,
            "embeds": embed_dicts,
            "components": component_dicts,
            "flags": flags,
        }
        if thread_id:
            payload["thread_id"] = thread_id

        # Handle files (multipart)
        if files:
            # Need multipart form data
            return await self._send_multipart(channel_id, payload, files)

        try:
            data = await self._api("POST", f"/channels/{channel_id}/messages", payload)
            return SendResult(
                channel_id=channel_id,
                status="ok",
                message_id=data.get("id"),
            )
        except DiscordRateLimitError:
            raise
        except Exception as e:
            return SendResult(channel_id=channel_id, status="error", error=str(e))

    async def _send_multipart(self, channel_id: int, payload: dict, files: list[dict]) -> SendResult:
        """Send message with file attachments using multipart."""
        import aiohttp
        if not self._http_session:
            raise DiscordPosterError("File upload requires aiohttp session (gateway mode)")

        form = aiohttp.FormData()
        form.add_field("payload_json", json.dumps(payload))
        for i, f in enumerate(files):
            form.add_field(f"files[{i}]", f["content"], filename=f["filename"])

        async with self._http_session.post(f"/channels/{channel_id}/messages", data=form) as resp:
            if resp.status == 429:
                retry = float(resp.headers.get("Retry-After", 1))
                raise DiscordRateLimitError(retry)
            if resp.status >= 400:
                text = await resp.text()
                raise DiscordPosterError(f"Discord API {resp.status}: {text}")
            data = await resp.json()
            return SendResult(channel_id=channel_id, status="ok", message_id=data.get("id"))

    async def send_embed(
        self,
        channel_id: int,
        title: str,
        description: str,
        *,
        color: int = 0x8b5cf6,  # Brand purple
        fields: Optional[list[dict]] = None,
        thumbnail: Optional[str] = None,
        image: Optional[str] = None,
        url: Optional[str] = None,
        footer: Optional[str] = None,
        footer_icon: Optional[str] = None,
        author: Optional[dict] = None,
        timestamp: Optional[datetime] = None,
        components: Optional[list[dict]] = None,
    ) -> SendResult:
        """Send a rich embed message."""
        embed = {
            "title": title,
            "description": description,
            "color": color,
        }
        if fields:
            embed["fields"] = fields
        if thumbnail:
            embed["thumbnail"] = {"url": thumbnail}
        if image:
            embed["image"] = {"url": image}
        if url:
            embed["url"] = url
        if footer:
            embed["footer"] = {"text": footer}
            if footer_icon:
                embed["footer"]["icon_url"] = footer_icon
        if author:
            embed["author"] = author
        if timestamp:
            embed["timestamp"] = timestamp.isoformat()

        return await self.send_message(channel_id, embeds=[embed], components=components)

    async def send_announcement(
        self,
        channel_id: int,
        title: str,
        description: str,
        *,
        color: int = 0x8b5cf6,
        fields: Optional[list[dict]] = None,
        image: Optional[str] = None,
        components: Optional[list[dict]] = None,
    ) -> SendResult:
        """Send an announcement embed (for announcement channels)."""
        return await self.send_embed(
            channel_id,
            title=f"📢 {title}",
            description=description,
            color=color,
            fields=fields,
            image=image,
            components=components,
        )

    # =========================================================================
    # Broadcasting
    # =========================================================================

    async def broadcast(
        self,
        channel_ids: list[int],
        content: Optional[str] = None,
        *,
        embeds: Optional[list[dict]] = None,
        components: Optional[list[dict]] = None,
        delay: float = 1.0,
        progress_callback: Optional[callable] = None,
    ) -> list[SendResult]:
        """Broadcast to multiple channels."""
        results = []
        for i, cid in enumerate(channel_ids):
            result = await self.send_message(cid, content, embeds=embeds, components=components)
            results.append(result)
            if progress_callback:
                progress_callback(i + 1, len(channel_ids), result)
            if i < len(channel_ids) - 1:
                await asyncio.sleep(delay)
        return results

    async def broadcast_to_configured(
        self,
        content: Optional[str] = None,
        *,
        embeds: Optional[list[dict]] = None,
        **kwargs,
    ) -> list[SendResult]:
        """Broadcast to configured target channels."""
        return await self.broadcast(self.settings.target_channels, content, embeds=embeds, **kwargs)

    # =========================================================================
    # Thread Management (for announcements)
    # =========================================================================

    async def create_thread(
        self,
        channel_id: int,
        name: str,
        *,
        message_id: Optional[int] = None,
        auto_archive_duration: int = 1440,  # 24 hours
        type: int = 11,  # PUBLIC_THREAD
    ) -> dict:
        """Create a thread in a channel."""
        if message_id:
            path = f"/channels/{channel_id}/messages/{message_id}/threads"
        else:
            path = f"/channels/{channel_id}/threads"

        data = await self._api("POST", path, {
            "name": name,
            "auto_archive_duration": auto_archive_duration,
            "type": type,
        })
        return data

    async def send_to_thread(
        self,
        thread_id: int,
        content: Optional[str] = None,
        *,
        embeds: Optional[list[dict]] = None,
    ) -> SendResult:
        """Send message to a thread."""
        return await self.send_message(thread_id, content, embeds=embeds)

    # =========================================================================
    # Slash Commands (Gateway Mode)
    # =========================================================================

    def register_slash_command(
        self,
        name: str,
        description: str,
        handler: callable,
        guild_ids: Optional[list[int]] = None,
        options: Optional[list[dict]] = None,
    ) -> None:
        """Register a slash command (gateway mode)."""
        if not self.use_gateway:
            raise DiscordPosterError("Slash commands require gateway mode")

        self._command_handlers[name] = handler

        @self._tree.command(name=name, description=description, guild_ids=guild_ids)
        async def _wrapper(interaction: discord.Interaction, **kwargs):
            await handler(interaction, **kwargs)

    def register_component_handler(self, custom_id: str, handler: callable) -> None:
        """Register a component (button/select) handler."""
        self._component_handlers[custom_id] = handler

    async def _sync_commands(self) -> None:
        """Sync slash commands with Discord."""
        if self._tree:
            try:
                await self._tree.sync()
                log.info("Slash commands synced")
            except Exception as e:
                log.error("Failed to sync commands: %s", e)

    async def _handle_interaction(self, interaction: discord.Interaction) -> None:
        """Handle incoming interactions."""
        if interaction.type == discord.InteractionType.application_command:
            # Slash command - handled by tree
            pass
        elif interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get("custom_id", "")
            for pattern, handler in self._component_handlers.items():
                if custom_id.startswith(pattern):
                    await handler(interaction)
                    return

    # =========================================================================
    # Webhook Support
    # =========================================================================

    async def create_webhook(
        self,
        channel_id: int,
        name: str,
        avatar: Optional[bytes] = None,
    ) -> dict:
        """Create a webhook in a channel."""
        data = {"name": name}
        if avatar:
            import base64
            data["avatar"] = base64.b64encode(avatar).decode()
        return await self._api("POST", f"/channels/{channel_id}/webhooks", data)

    async def list_webhooks(self, channel_id: int) -> list[dict]:
        """List webhooks in a channel."""
        return await self._api("GET", f"/channels/{channel_id}/webhooks")

    async def execute_webhook(
        self,
        webhook_id: int,
        webhook_token: str,
        content: Optional[str] = None,
        *,
        embeds: Optional[list[dict]] = None,
        username: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> dict:
        """Execute a webhook."""
        import aiohttp
        url = f"https://discord.com/api/webhooks/{webhook_id}/{webhook_token}"
        payload = {}
        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = embeds
        if username:
            payload["username"] = username
        if avatar_url:
            payload["avatar_url"] = avatar_url

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise DiscordPosterError(f"Webhook {resp.status}: {text}")
                return await resp.json() if resp.content_type == "application/json" else {}

    # =========================================================================
    # Message History & Management
    # =========================================================================

    async def get_messages(self, channel_id: int, limit: int = 50, before: Optional[str] = None) -> list[dict]:
        """Get message history."""
        params = f"?limit={limit}"
        if before:
            params += f"&before={before}"
        return await self._api("GET", f"/channels/{channel_id}/messages{params}")

    async def delete_message(self, channel_id: int, message_id: str) -> bool:
        """Delete a message."""
        try:
            await self._api("DELETE", f"/channels/{channel_id}/messages/{message_id}")
            return True
        except Exception:
            return False

    async def edit_message(
        self,
        channel_id: int,
        message_id: str,
        content: Optional[str] = None,
        embeds: Optional[list[dict]] = None,
    ) -> dict:
        """Edit a message."""
        payload = {}
        if content is not None:
            payload["content"] = content
        if embeds is not None:
            payload["embeds"] = embeds
        return await self._api("PATCH", f"/channels/{channel_id}/messages/{message_id}", payload)

    async def add_reaction(self, channel_id: int, message_id: str, emoji: str) -> bool:
        """Add a reaction to a message."""
        try:
            await self._api("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me")
            return True
        except Exception:
            return False

    # =========================================================================
    # Guild Management
    # =========================================================================

    async def leave_guild(self, guild_id: int) -> bool:
        """Leave a guild."""
        try:
            await self._api("DELETE", f"/users/@me/guilds/{guild_id}")
            return True
        except Exception:
            return False

    async def get_guild_member(self, guild_id: int, user_id: int) -> Optional[dict]:
        """Get a guild member."""
        try:
            return await self._api("GET", f"/guilds/{guild_id}/members/{user_id}")
        except Exception:
            return None

    async def get_guild_roles(self, guild_id: int) -> list[dict]:
        """Get guild roles."""
        return await self._api("GET", f"/guilds/{guild_id}/roles")

    # =========================================================================
    # Utility
    # =========================================================================

    @staticmethod
    def create_button(
        label: str,
        custom_id: str,
        style: int = 1,  # 1=primary, 2=secondary, 3=success, 4=danger, 5=link
        emoji: Optional[str] = None,
        disabled: bool = False,
        url: Optional[str] = None,
    ) -> dict:
        """Create a button component."""
        btn: dict = {
            "type": 2,
            "label": label,
            "style": style,
            "disabled": disabled,
        }
        if custom_id:
            btn["custom_id"] = custom_id
        if emoji:
            btn["emoji"] = {"name": emoji}
        if url:
            btn["style"] = 5
            btn["url"] = url
        return btn

    @staticmethod
    def create_select(
        custom_id: str,
        options: list[dict],
        placeholder: str = "Select...",
        min_values: int = 1,
        max_values: int = 1,
        disabled: bool = False,
    ) -> dict:
        """Create a select menu component."""
        return {
            "type": 3,
            "custom_id": custom_id,
            "options": options,
            "placeholder": placeholder,
            "min_values": min_values,
            "max_values": max_values,
            "disabled": disabled,
        }

    @staticmethod
    def create_action_row(*components: dict) -> dict:
        """Create an action row component."""
        return {"type": 1, "components": list(components)}


# =========================================================================
# Embed Builder Helpers
# =========================================================================

class EmbedBuilder:
    """Fluent embed builder."""

    def __init__(self):
        self._embed: dict = {}

    def title(self, title: str) -> EmbedBuilder:
        self._embed["title"] = title
        return self

    def description(self, desc: str) -> EmbedBuilder:
        self._embed["description"] = desc
        return self

    def color(self, color: int) -> EmbedBuilder:
        self._embed["color"] = color
        return self

    def field(self, name: str, value: str, inline: bool = True) -> EmbedBuilder:
        self._embed.setdefault("fields", []).append({
            "name": name,
            "value": value,
            "inline": inline,
        })
        return self

    def thumbnail(self, url: str) -> EmbedBuilder:
        self._embed["thumbnail"] = {"url": url}
        return self

    def image(self, url: str) -> EmbedBuilder:
        self._embed["image"] = {"url": url}
        return self

    def url(self, url: str) -> EmbedBuilder:
        self._embed["url"] = url
        return self

    def footer(self, text: str, icon: Optional[str] = None) -> EmbedBuilder:
        self._embed["footer"] = {"text": text}
        if icon:
            self._embed["footer"]["icon_url"] = icon
        return self

    def author(self, name: str, url: Optional[str] = None, icon: Optional[str] = None) -> EmbedBuilder:
        self._embed["author"] = {"name": name}
        if url:
            self._embed["author"]["url"] = url
        if icon:
            self._embed["author"]["icon_url"] = icon
        return self

    def timestamp(self, dt: Optional[datetime] = None) -> EmbedBuilder:
        self._embed["timestamp"] = (dt or datetime.utcnow()).isoformat()
        return self

    def build(self) -> dict:
        return self._embed.copy()


# Convenience function
async def create_poster(
    token: Optional[str] = None,
    use_gateway: bool = False,
    application_id: Optional[int] = None,
) -> DiscordPoster:
    """Create a DiscordPoster with optional overrides."""
    settings = get_settings().discord
    if token:
        settings.token = token
    if use_gateway:
        settings.use_gateway = True
    if application_id:
        settings.application_id = application_id
    return DiscordPoster(settings=settings, use_gateway=use_gateway)