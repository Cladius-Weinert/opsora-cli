"""
Opsora CLI Marketing Commands
Adds /market slash commands to Opsora CLI.

Usage:
    /market post --text "Hello" --platform all
    /market schedule
    /market analytics
    /market broadcast --text "Hello" --targets "id1,id2"
    /market campaign --type intro
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from marketing_hub.content_strategy import ContentStrategy
from marketing_hub.analytics import Analytics
from marketing_hub.broadcaster import Broadcaster
from marketing_hub.autonomous_engine import AutonomousEngine


class MarketingCommands:
    """
    Marketing slash commands for Opsora CLI.
    Integrates with the main CLI's command handler.
    """

    def __init__(self):
        self.strategy = ContentStrategy()
        self.analytics = Analytics()
        self.broadcaster = Broadcaster()
        self.engine = AutonomousEngine()

    def handle_command(self, args: list[str]) -> str:
        """Handle /market command."""
        if not args:
            return self._show_help()

        subcommand = args[0].lower()

        handlers = {
            "post": self._cmd_post,
            "schedule": self._cmd_schedule,
            "analytics": self._cmd_analytics,
            "broadcast": self._cmd_broadcast,
            "campaign": self._cmd_campaign,
            "hashtags": self._cmd_hashtags,
            "status": self._cmd_status,
            "help": self._show_help,
        }

        handler = handlers.get(subcommand)
        if not handler:
            return f"Unknown command: {subcommand}\n{self._show_help()}"

        return handler(args[1:])

    def _show_help(self) -> str:
        return """📢 Opsora Marketing Commands

  /market post --text <content> [--platform all|telegram|discord|twitter|email|github]
  /market schedule                    Show weekly content calendar
  /market analytics [--days 7]        Show engagement analytics
  /market broadcast --text <content> [--targets id1,id2]
  /market campaign --type <type>      Generate campaign content
  /market hashtags --topic <topic>    Get hashtag suggestions
  /market status                      Show marketing system status
  /market help                        Show this help
"""

    def _cmd_post(self, args: list[str]) -> str:
        text = self._get_arg(args, "--text")
        if not text:
            return "Usage: /market post --text <content> [--platform all]"

        platform = self._get_arg(args, "--platform", "all")

        if platform == "all":
            results = asyncio.run(self.broadcaster.post_to_all(text))
        elif platform == "telegram":
            result = asyncio.run(self.broadcaster.post_to_telegram(text))
            results = {platform: result}
        elif platform == "discord":
            result = asyncio.run(self.broadcaster.post_to_discord(text))
            results = {platform: result}
        else:
            return f"Unknown platform: {platform}"

        lines = ["📢 Broadcast Results:"]
        for p, r in results.items():
            icon = "✅" if r.status == "ok" else "⚠️" if r.status == "skipped" else "❌"
            lines.append(f"  {icon} {p}: {r.status}")
            if r.message:
                lines.append(f"     {r.message}")
        return "\n".join(lines)

    def _cmd_schedule(self, args: list[str]) -> str:
        plans = self.strategy.get_weekly_calendar()
        lines = ["📅 Weekly Content Calendar:", ""]
        for plan in plans:
            lines.append(f"  {plan.day}: {plan.title} ({plan.content_type})")
        return "\n".join(lines)

    def _cmd_analytics(self, args: list[str]) -> str:
        days = int(self._get_arg(args, "--days", "7"))
        report = self.analytics.get_report(days)
        return report.get("summary", "No analytics data yet.")

    def _cmd_broadcast(self, args: list[str]) -> str:
        text = self._get_arg(args, "--text")
        if not text:
            return "Usage: /market broadcast --text <content> [--targets id1,id2]"

        targets_str = self._get_arg(args, "--targets")
        if targets_str:
            targets = [t.strip() for t in targets_str.split(",")]
            result = asyncio.run(self.broadcaster.post_to_telegram(text, targets=targets))
        else:
            result = asyncio.run(self.broadcaster.post_to_telegram(text))

        icon = "✅" if result.status == "ok" else "❌"
        return f"{icon} Telegram broadcast: {result.status}\n{result.message or result.error or ''}"

    def _cmd_campaign(self, args: list[str]) -> str:
        content_type = self._get_arg(args, "--type", "intro")
        content = self.strategy.generate_content(content_type, "both")
        lines = [f"📝 Campaign Content ({content_type}):", ""]
        for lang, text in content.items():
            lines.append(f"[{lang.upper()}]")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    def _cmd_hashtags(self, args: list[str]) -> str:
        topic = self._get_arg(args, "--topic", "ai")
        tags = self.strategy.optimize_hashtags(topic)
        return f"🏷️  Hashtags for '{topic}':\n  {' '.join(tags)}"

    def _cmd_status(self, args: list[str]) -> str:
        import os
        lines = ["📡 Marketing System Status:", ""]
        lines.append(f"  Telegram: {'✅' if os.path.exists('/root/.telegram-mcp/opsora.session') else '⚠️'} Session")
        lines.append(f"  Google: {'✅' if os.path.exists('/root/.google_auth/tokens') else '⚠️'} OAuth")
        lines.append(f"  GitHub: {'✅' if os.system('which gh >/dev/null 2>&1') == 0 else '❌'} CLI")
        lines.append(f"  Twitter: {'✅' if os.environ.get('TWITTER_API_KEY') else '⚠️'} API Key")
        lines.append(f"  NVIDIA: {'✅' if os.environ.get('NVIDIA_API_KEY') else '❌'} API Key")
        lines.append(f"  DashScope: {'✅' if os.environ.get('DASHSCOPE_API_KEY') else '❌'} API Key")
        return "\n".join(lines)

    @staticmethod
    def _get_arg(args: list[str], name: str, default: Optional[str] = None) -> Optional[str]:
        for i, arg in enumerate(args):
            if arg == name and i + 1 < len(args):
                return args[i + 1]
        return default


# =========================================================================
# Direct CLI usage (for testing)
# =========================================================================

if __name__ == "__main__":
    cmd = MarketingCommands()
    result = cmd.handle_command(sys.argv[1:] if len(sys.argv) > 1 else [])
    print(result)