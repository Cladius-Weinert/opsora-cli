"""
Telegram Poster - Enhanced with inline keyboards, command handlers, media support.

Uses Telethon for userbot-style posting and python-telegram-bot for webhook/bot mode.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from telethon import TelegramClient, events
from telethon.tl.types import (
    Message,
    MessageMediaPhoto,
    MessageMediaDocument,
    InputPeerChannel,
    InputPeerChat,
    InputPeerUser,
)
from telethon.errors import (
    FloodWaitError,
    ChatAdminRequiredError,
    ChannelPrivateError,
    UserNotParticipantError,
)

from .settings import get_settings, TelegramSettings

log = logging.getLogger("marketing.telegram")


@dataclass(slots=True)
class TelegramTarget:
    """Represents a Telegram chat/channel target."""
    id: int
    title: str
    type: str  # "channel", "group", "supergroup", "private"
    username: Optional[str] = None
    access_hash: Optional[int] = None

    @property
    def mention(self) -> str:
        if self.username:
            return f"@{self.username}"
        return str(self.id)


@dataclass(slots=True)
class SendResult:
    """Result of a send operation."""
    target: TelegramTarget
    status: Literal["ok", "error", "skipped"]
    message_id: Optional[int] = None
    error: Optional[str] = None


class TelegramPosterError(Exception):
    """Base exception for Telegram poster errors."""
    pass


class TelegramAuthError(TelegramPosterError):
    """Authentication/authorization error."""
    pass


class TelegramRateLimitError(TelegramPosterError):
    """Rate limit exceeded."""
    def __init__(self, wait_seconds: int):
        self.wait_seconds = wait_seconds
        super().__init__(f"Rate limited, wait {wait_seconds}s")


class TelegramPoster:
    """
    Enhanced Telegram poster with:
    - Userbot mode (Telethon) for broadcasting to groups/channels
    - Bot mode (python-telegram-bot) for webhooks and inline keyboards
    - Media support: photos, videos, documents, albums
    - Inline keyboard support
    - Command handlers
    - Broadcast with progress tracking
    """

    def __init__(
        self,
        settings: Optional[TelegramSettings] = None,
        use_bot_mode: bool = False,
    ):
        self.settings = settings or get_settings().telegram
        self.use_bot_mode = use_bot_mode and self.settings.bot_token is not None
        self._client: Optional[TelegramClient] = None
        self._bot_app: Any = None  # python-telegram-bot Application
        self._connected = False
        self._command_handlers: dict[str, callable] = {}
        self._callback_handlers: dict[str, callable] = {}

    # =========================================================================
    # Connection Management
    # =========================================================================

    async def connect(self) -> None:
        """Establish connection to Telegram."""
        if self._connected:
            return

        if self.use_bot_mode:
            await self._connect_bot()
        else:
            await self._connect_userbot()

        self._connected = True
        log.info("Telegram connected (mode: %s)", "bot" if self.use_bot_mode else "userbot")

    async def _connect_userbot(self) -> None:
        """Connect using Telethon userbot."""
        self._client = TelegramClient(
            self.settings.session_path,
            self.settings.api_id,
            self.settings.api_hash,
            device_model="Opsora Marketing Hub",
            system_version="Linux",
            app_version="1.0",
        )

        await self._client.connect()

        if not await self._client.is_user_authorized():
            raise TelegramAuthError(
                "Telegram userbot not authorized. Run telegram_auth.py first."
            )

        me = await self._client.get_me()
        log.info("Userbot authorized as: %s (@%s)", me.first_name, me.username)

    async def _connect_bot(self) -> None:
        """Connect using python-telegram-bot (for webhooks)."""
        try:
            from telegram import Bot
            from telegram.ext import Application, CommandHandler, CallbackQueryHandler
        except ImportError:
            raise TelegramPosterError(
                "python-telegram-bot not installed. Install with: pip install python-telegram-bot"
            )

        self._bot_app = Application.builder().token(self.settings.bot_token).build()
        bot = Bot(self.settings.bot_token)
        me = await bot.get_me()
        log.info("Bot authorized as: %s (@%s)", me.first_name, me.username)

        # Register default handlers
        self._bot_app.add_handler(CommandHandler("start", self._cmd_start))
        self._bot_app.add_handler(CommandHandler("help", self._cmd_help))
        self._bot_app.add_handler(CallbackQueryHandler(self._handle_callback))

        # Initialize but don't start polling (webhook mode)
        await self._bot_app.initialize()

    async def disconnect(self) -> None:
        """Close connections."""
        if self.use_bot_mode and self._bot_app:
            await self._bot_app.shutdown()
            self._bot_app = None
        elif self._client and self._connected:
            await self._client.disconnect()
            self._client = None
        self._connected = False
        log.info("Telegram disconnected")

    async def __aenter__(self) -> TelegramPoster:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    # =========================================================================
    # Message Sending
    # =========================================================================

    async def send(
        self,
        target: int | str | TelegramTarget,
        text: str,
        *,
        parse_mode: str = "md",
        file: Optional[str | Path | bytes] = None,
        caption: Optional[str] = None,
        buttons: Optional[list[list[dict]]] = None,
        silent: bool = False,
        schedule_date: Optional[float] = None,
    ) -> SendResult:
        """
        Send a message to a target.

        Args:
            target: Chat ID, username, or TelegramTarget
            text: Message text
            parse_mode: "md" (MarkdownV2), "html", or None
            file: Path to media file, URL, or bytes
            caption: Caption for media
            buttons: Inline keyboard buttons [[{"text": "...", "callback_data": "..."}, ...], ...]
            silent: Send silently (no notification)
            schedule_date: Unix timestamp to schedule message

        Returns:
            SendResult with status and message_id
        """
        await self.connect()

        # Resolve target
        tg_target = await self._resolve_target(target)
        if not tg_target:
            return SendResult(
                target=TelegramTarget(id=0, title="unknown", type="unknown"),
                status="error",
                error="Could not resolve target",
            )

        try:
            if self.use_bot_mode:
                return await self._send_bot(tg_target, text, parse_mode, file, caption, buttons, silent, schedule_date)
            else:
                return await self._send_userbot(tg_target, text, parse_mode, file, caption, buttons, silent, schedule_date)
        except FloodWaitError as e:
            log.warning("Flood wait: %ds", e.seconds)
            raise TelegramRateLimitError(e.seconds)
        except (ChatAdminRequiredError, ChannelPrivateError, UserNotParticipantError) as e:
            log.error("Permission error for %s: %s", tg_target, e)
            return SendResult(target=tg_target, status="error", error=f"Permission denied: {e}")

    async def _send_userbot(
        self,
        target: TelegramTarget,
        text: str,
        parse_mode: str,
        file: Optional[str | Path | bytes],
        caption: Optional[str],
        buttons: Optional[list[list[dict]]],
        silent: bool,
        schedule_date: Optional[float],
    ) -> SendResult:
        """Send via Telethon userbot."""
        assert self._client is not None

        # Build buttons markup
        markup = None
        if buttons:
            from telethon import Button
            markup = [
                [Button.inline(btn["text"], btn.get("callback_data", "")) for btn in row]
                for row in buttons
            ]

        # Prepare file
        file_obj = None
        if file:
            if isinstance(file, (str, Path)):
                file_obj = str(file)
            elif isinstance(file, bytes):
                file_obj = file

        # Build kwargs dynamically — caption only valid with file
        kwargs = {
            "entity": target.id,
            "message": text,
            "parse_mode": parse_mode if parse_mode else None,
            "silent": silent,
        }
        if file_obj:
            kwargs["file"] = file_obj
            if caption:
                kwargs["caption"] = caption
        if markup:
            kwargs["buttons"] = markup
        if schedule_date:
            kwargs["schedule"] = schedule_date

        msg = await self._client.send_message(**kwargs)

        return SendResult(
            target=target,
            status="ok",
            message_id=msg.id,
        )

    async def _send_bot(
        self,
        target: TelegramTarget,
        text: str,
        parse_mode: str,
        file: Optional[str | Path | bytes],
        caption: Optional[str],
        buttons: Optional[list[list[dict]]],
        silent: bool,
        schedule_date: Optional[float],
    ) -> SendResult:
        """Send via python-telegram-bot."""
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        from telegram.constants import ParseMode

        assert self._bot_app is not None
        bot = self._bot_app.bot

        # Build keyboard
        reply_markup = None
        if buttons:
            keyboard = [
                [InlineKeyboardButton(btn["text"], callback_data=btn.get("callback_data", "")) for btn in row]
                for row in buttons
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

        # Determine parse mode
        pm = None
        if parse_mode == "md":
            pm = ParseMode.MARKDOWN_V2
        elif parse_mode == "html":
            pm = ParseMode.HTML

        # Send
        if file:
            # Handle media
            if isinstance(file, (str, Path)):
                with open(file, "rb") as f:
                    msg = await bot.send_document(
                        chat_id=target.id,
                        document=f,
                        caption=caption or text,
                        parse_mode=pm,
                        reply_markup=reply_markup,
                        disable_notification=silent,
                    )
            else:
                # bytes - not directly supported, save to temp
                raise NotImplementedError("Bytes file sending not implemented for bot mode")
        else:
            msg = await bot.send_message(
                chat_id=target.id,
                text=text,
                parse_mode=pm,
                reply_markup=reply_markup,
                disable_notification=silent,
            )

        return SendResult(
            target=target,
            status="ok",
            message_id=msg.message_id,
        )

    async def send_media_group(
        self,
        target: int | str | TelegramTarget,
        media: list[dict],
        *,
        caption: Optional[str] = None,
        silent: bool = False,
    ) -> list[SendResult]:
        """
        Send a media group (album).

        Args:
            target: Target chat
            media: List of {"type": "photo"|"video"|"document", "media": path|bytes, "caption": "..."}
            caption: Overall caption (for first item)
            silent: Send silently

        Returns:
            List of SendResult
        """
        await self.connect()
        tg_target = await self._resolve_target(target)
        if not tg_target:
            return [SendResult(
                target=TelegramTarget(id=0, title="unknown", type="unknown"),
                status="error",
                error="Could not resolve target",
            )]

        if self.use_bot_mode:
            raise NotImplementedError("Media groups not yet implemented for bot mode")

        assert self._client is not None

        # Build telethon media
        from telethon import functions, types
        from telethon.utils import get_peer_id

        peer = await self._client.get_input_entity(tg_target.id)
        media_objects = []

        for i, item in enumerate(media):
            file_path = item["media"]
            if isinstance(file_path, (str, Path)):
                uploaded = await self._client.upload_file(file_path)
            else:
                uploaded = await self._client.upload_file(file_path)

            if item["type"] == "photo":
                media_objects.append(types.InputMediaUploadedPhoto(uploaded))
            elif item["type"] == "video":
                media_objects.append(types.InputMediaUploadedDocument(
                    file=uploaded,
                    mime_type="video/mp4",
                    attributes=[types.DocumentAttributeVideo(0, 0, 0, 0)],
                ))
            else:
                media_objects.append(types.InputMediaUploadedDocument(
                    file=uploaded,
                    mime_type="application/octet-stream",
                ))

        # Send as album
        result = await self._client(functions.messages.SendMultiMediaRequest(
            peer=peer,
            multi_media=media_objects,
            silent=silent,
        ))

        return [
            SendResult(target=tg_target, status="ok", message_id=msg.id)
            for msg in result.updates
            if hasattr(msg, "id")
        ]

    # =========================================================================
    # Broadcasting
    # =========================================================================

    async def broadcast(
        self,
        targets: list[int | str | TelegramTarget],
        text: str,
        *,
        parse_mode: str = "md",
        file: Optional[str | Path | bytes] = None,
        caption: Optional[str] = None,
        buttons: Optional[list[list[dict]]] = None,
        silent: bool = False,
        delay: float = 1.0,
        progress_callback: Optional[callable] = None,
    ) -> list[SendResult]:
        """
        Broadcast message to multiple targets with rate limiting.

        Args:
            targets: List of target IDs/usernames/TelegramTarget
            text: Message text
            parse_mode: Parse mode
            file: Media file
            caption: Media caption
            buttons: Inline keyboard
            silent: Silent send
            delay: Delay between sends (seconds)
            progress_callback: Called with (completed, total, current_result)

        Returns:
            List of SendResult
        """
        results = []
        total = len(targets)

        for i, target in enumerate(targets):
            result = await self.send(
                target, text,
                parse_mode=parse_mode,
                file=file,
                caption=caption,
                buttons=buttons,
                silent=silent,
            )
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, total, result)

            # Rate limiting delay
            if i < total - 1:
                await asyncio.sleep(delay)

        return results

    async def broadcast_to_configured(
        self,
        text: str,
        *,
        channels: bool = True,
        groups: bool = True,
        **kwargs,
    ) -> list[SendResult]:
        """Broadcast to configured target channels/groups."""
        targets = []
        if channels:
            targets.extend(self.settings.target_channels)
        if groups:
            targets.extend(self.settings.target_groups)
        return await self.broadcast(targets, text, **kwargs)

    # =========================================================================
    # Target Discovery
    # =========================================================================

    async def list_chats(self, limit: int = 50) -> list[TelegramTarget]:
        """List all chats (private, groups, channels)."""
        await self.connect()
        if self.use_bot_mode:
            raise NotImplementedError("Chat listing not available in bot mode")

        assert self._client is not None
        dialogs = await self._client.get_dialogs(limit=limit)

        return [
            TelegramTarget(
                id=d.id,
                title=d.title or d.name or str(d.id),
                type="channel" if d.is_channel else "group" if d.is_group else "private",
                username=getattr(d.entity, "username", None),
                access_hash=getattr(d.entity, "access_hash", None),
            )
            for d in dialogs
        ]

    async def list_groups_and_channels(self, limit: int = 100) -> list[TelegramTarget]:
        """List only groups and channels (broadcast targets)."""
        chats = await self.list_chats(limit)
        return [c for c in chats if c.type in ("group", "channel", "supergroup")]

    async def get_chat_info(self, target: int | str) -> Optional[TelegramTarget]:
        """Get detailed info for a chat."""
        await self.connect()
        if self.use_bot_mode:
            raise NotImplementedError("Not available in bot mode")

        assert self._client is not None
        try:
            entity = await self._client.get_entity(target)
            return TelegramTarget(
                id=entity.id,
                title=getattr(entity, "title", None) or getattr(entity, "first_name", "") or str(entity.id),
                type="channel" if getattr(entity, "broadcast", False) else "group" if getattr(entity, "megagroup", False) else "private",
                username=getattr(entity, "username", None),
                access_hash=getattr(entity, "access_hash", None),
            )
        except Exception as e:
            log.error("Failed to get chat info for %s: %s", target, e)
            return None

    async def join_channel(self, channel: str) -> SendResult:
        """
        Join a channel or group by username or invite link.

        Args:
            channel: Channel username (e.g., "@opsora_ai"), invite link, or chat ID

        Returns:
            SendResult with status
        """
        await self.connect()
        if self.use_bot_mode:
            return SendResult(
                target=TelegramTarget(id=0, title=channel, type="unknown"),
                status="error",
                error="Join channel not available in bot mode"
            )

        assert self._client is not None
        try:
            from telethon.tl.functions.channels import JoinChannelRequest
            from telethon.tl.functions.messages import ImportChatInviteRequest

            # Handle invite links (t.me/joinchat/... or t.me/+...)
            if "t.me/joinchat/" in channel or "t.me/+" in channel:
                # Extract hash from invite link
                invite_hash = channel.split("/")[-1].replace("+", "")
                result = await self._client(ImportChatInviteRequest(invite_hash))
                chat = result.chats[0] if result.chats else result.updates[0].chats[0] if result.updates else None
            else:
                # Join by username or ID
                result = await self._client(JoinChannelRequest(channel))
                chat = result.chats[0] if result.chats else None

            if chat:
                tg_target = TelegramTarget(
                    id=chat.id,
                    title=getattr(chat, "title", None) or getattr(chat, "first_name", "") or str(chat.id),
                    type="channel" if getattr(chat, "broadcast", False) else "group" if getattr(chat, "megagroup", False) else "private",
                    username=getattr(chat, "username", None),
                    access_hash=getattr(chat, "access_hash", None),
                )
                log.info("Joined channel: %s (%s)", tg_target.title, tg_target.mention)
                return SendResult(target=tg_target, status="ok", message_id=0)
            else:
                return SendResult(
                    target=TelegramTarget(id=0, title=channel, type="unknown"),
                    status="error",
                    error="No chat returned from join request"
                )

        except Exception as e:
            log.error("Failed to join channel %s: %s", channel, e)
            return SendResult(
                target=TelegramTarget(id=0, title=channel, type="unknown"),
                status="error",
                error=str(e)
            )

    # =========================================================================
    # Command & Callback Handlers (Bot Mode)
    # =========================================================================

    def register_command(self, command: str, handler: callable) -> None:
        """Register a command handler (bot mode)."""
        self._command_handlers[command] = handler
        if self._bot_app:
            from telegram.ext import CommandHandler
            self._bot_app.add_handler(CommandHandler(command, handler))

    def register_callback(self, pattern: str, handler: callable) -> None:
        """Register a callback query handler (bot mode)."""
        self._callback_handlers[pattern] = handler

    async def _cmd_start(self, update, context) -> None:
        """Default /start handler."""
        await update.message.reply_text(
            f"🤖 Welcome to {get_settings().brand.name}!\n\n"
            f"Use /help to see available commands."
        )

    async def _cmd_help(self, update, context) -> None:
        """Default /help handler."""
        commands = [
            ("start", "Start the bot"),
            ("help", "Show this help"),
            ("subscribe", "Subscribe to broadcasts"),
            ("unsubscribe", "Unsubscribe from broadcasts"),
            ("stats", "Show channel stats"),
        ]
        text = "📋 Available Commands:\n\n"
        text += "\n".join(f"/{cmd} - {desc}" for cmd, desc in commands)
        await update.message.reply_text(text)

    async def _handle_callback(self, update, context) -> None:
        """Handle inline keyboard callbacks."""
        query = update.callback_query
        data = query.data

        # Check registered handlers
        for pattern, handler in self._callback_handlers.items():
            if data.startswith(pattern):
                await handler(query, context, data)
                return

        # Default: acknowledge
        await query.answer("Callback received")

    # =========================================================================
    # Webhook Support (Bot Mode)
    # =========================================================================

    async def start_webhook(
        self,
        url: str,
        port: int = 8443,
        path: str = "/webhook/telegram",
        ssl_cert: Optional[str] = None,
        ssl_key: Optional[str] = None,
    ) -> None:
        """Start webhook server for receiving updates (bot mode)."""
        if not self.use_bot_mode:
            raise TelegramPosterError("Webhook only available in bot mode")

        assert self._bot_app is not None
        await self._bot_app.bot.set_webhook(
            url=f"{url}{path}",
            certificate=open(ssl_cert, "rb") if ssl_cert else None,
        )

        # Start aiohttp webhook server
        from telegram.ext import Application
        await self._bot_app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=path.lstrip("/"),
            webhook_url=f"{url}{path}",
        )

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    async def _resolve_target(self, target: int | str | TelegramTarget) -> Optional[TelegramTarget]:
        """Resolve target to TelegramTarget."""
        if isinstance(target, TelegramTarget):
            return target
        if isinstance(target, int):
            return await self.get_chat_info(target)
        if isinstance(target, str):
            # Could be username or numeric string
            try:
                return await self.get_chat_info(int(target))
            except ValueError:
                return await self.get_chat_info(target)
        return None


# Convenience function for backwards compatibility
async def create_poster(
    session: Optional[str] = None,
    api_id: Optional[int] = None,
    api_hash: Optional[str] = None,
    use_bot: bool = False,
) -> TelegramPoster:
    """Create a TelegramPoster with optional overrides."""
    settings = get_settings().telegram
    if session:
        settings.session_path = session
    if api_id:
        settings.api_id = api_id
    if api_hash:
        settings.api_hash = api_hash
    return TelegramPoster(settings=settings, use_bot_mode=use_bot)