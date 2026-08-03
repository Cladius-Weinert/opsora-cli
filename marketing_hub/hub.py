#!/usr/bin/env python3
"""
Opsora Social Media Marketing Hub
Broadcast marketing content to Telegram, Discord, and more.

Usage:
  python -m marketing_hub.hub post --type intro
  python -m marketing_hub.hub broadcast --text "Hello world"
  python -m marketing_hub.hub discover
  python -m marketing_hub.hub schedule
"""
import asyncio
import argparse
import json
import sys
import logging

from .telegram_poster import TelegramPoster
from .discord_poster import DiscordPoster
from .content_engine import generate_post, get_todays_post

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
log = logging.getLogger("hub")


async def cmd_discover(args):
    """Discover available channels and groups"""
    print("=== Telegram Groups & Channels ===")
    tg = TelegramPoster()
    try:
        chats = await tg.list_groups_and_channels(limit=30)
        for c in chats:
            print(f"  {c.title} (ID: {c.id})")
        if not chats:
            print("  No groups/channels found. Join some first!")
    except Exception as e:
        print(f"  Error: {e}")
    finally:
        await tg.disconnect()

    print("\n=== Discord Servers & Channels ===")
    dc = DiscordPoster()
    try:
        info = await dc.get_bot_info()
        print(f"  Bot: {info['username']}#{info['discriminator']}")
        guilds = await dc.list_guilds()
        if guilds:
            for g in guilds:
                print(f"  Server: {g['name']} (ID: {g['id']})")
                channels = await dc.list_channels(g['id'])
                for ch in channels:
                    if ch['type'] == 0:
                        print(f"    #{ch['name']} (ID: {ch['id']})")
        else:
            print("  Bot not in any server yet. Add it to a server first!")
    except Exception as e:
        print(f"  Error: {e}")


async def cmd_post(args):
    """Generate and display a post"""
    if args.text:
        content = args.text
    elif args.type:
        content = generate_post(args.type)
    else:
        content = get_todays_post()

    print(content)
    return content


async def cmd_broadcast(args):
    """Broadcast to configured targets"""
    if args.text:
        content = args.text
    elif args.type:
        content = generate_post(args.type)
    else:
        content = get_todays_post()

    print(f"Content:\n{content}\n")

    results = {"telegram": [], "discord": []}

    # Telegram
    if args.telegram_targets:
        tg = TelegramPoster()
        try:
            targets = [t.strip() for t in args.telegram_targets.split(",")]
            results["telegram"] = await tg.broadcast(targets, content)
            for r in results["telegram"]:
                status = "✅" if r["status"] == "ok" else "❌"
                print(f"  Telegram {status} {r['target']}")
        except Exception as e:
            print(f"  Telegram error: {e}")
        finally:
            await tg.disconnect()

    # Discord
    if args.discord_channels:
        dc = DiscordPoster()
        try:
            channels = [c.strip() for c in args.discord_channels.split(",")]
            results["discord"] = dc.broadcast(channels, content)
            for r in results["discord"]:
                status = "✅" if r["status"] == "ok" else "❌"
                print(f"  Discord {status} channel {r['channel']}")
        except Exception as e:
            print(f"  Discord error: {e}")

    return results


async def cmd_schedule(args):
    """Show today's scheduled content"""
    from datetime import datetime
    day = datetime.now().strftime("%A")
    content = get_todays_post()
    print(f"📅 {day}'s Post:\n")
    print(content)


async def cmd_join(args):
    """Join a Telegram channel or group"""
    print(f"Joining {args.channel}...")
    tg = TelegramPoster()
    try:
        result = await tg.join_channel(args.channel)
        if result.status == "ok":
            print(f"✅ Joined: {result.target.title} ({result.target.mention})")
            print(f"   ID: {result.target.id}, Type: {result.target.type}")
        else:
            print(f"❌ Failed: {result.error}")
    except Exception as e:
        print(f"  Error: {e}")
    finally:
        await tg.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Opsora Social Media Marketing Hub")
    sub = parser.add_subparsers(dest="command")

    p_disc = sub.add_parser("discover", help="Discover channels")
    p_post = sub.add_parser("post", help="Generate a post")
    p_post.add_argument("--type", choices=["intro", "feature", "tips", "testimonial", "digest", "engagement", "random"])
    p_post.add_argument("--text", help="Custom text instead of generated")

    p_bcast = sub.add_parser("broadcast", help="Broadcast to channels")
    p_bcast.add_argument("--type", choices=["intro", "feature", "tips", "testimonial", "digest", "engagement", "random"])
    p_bcast.add_argument("--text", help="Custom text")
    p_bcast.add_argument("--telegram-targets", help="Comma-separated Telegram chat IDs")
    p_bcast.add_argument("--discord-channels", help="Comma-separated Discord channel IDs")

    p_sched = sub.add_parser("schedule", help="Show today's scheduled content")

    p_join = sub.add_parser("join", help="Join a Telegram channel/group")
    p_join.add_argument("channel", help="Channel username (e.g., @opsora_ai) or invite link")

    args = parser.parse_args()

    if args.command == "discover":
        asyncio.run(cmd_discover(args))
    elif args.command == "post":
        asyncio.run(cmd_post(args))
    elif args.command == "broadcast":
        asyncio.run(cmd_broadcast(args))
    elif args.command == "schedule":
        asyncio.run(cmd_schedule(args))
    elif args.command == "join":
        asyncio.run(cmd_join(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
