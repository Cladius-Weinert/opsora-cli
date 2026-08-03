"""
Opsora Autonomous Marketing Engine
Self-running engine that generates content, schedules posts, broadcasts across ALL platforms,
tracks engagement, and adjusts strategy automatically.

Usage:
    python3 -m marketing_hub.autonomous_engine run          # Run once
    python3 -m marketing_hub.autonomous_engine daemon       # Run as daemon (loop)
    python3 -m marketing_hub.autonomous_engine status       # Show status
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from marketing_hub.settings import get_settings
from marketing_hub.content_engine import ContentEngine
from marketing_hub.telegram_poster import TelegramPoster
from marketing_hub.discord_poster import DiscordPoster
from marketing_hub.posting import UnifiedPoster as PostingManager

# Setup logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "autonomous_engine.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("autonomous_engine")

DB_PATH = Path(__file__).parent / "marketing.db"


@dataclass
class Campaign:
    """Represents a marketing campaign."""
    id: str
    name: str
    platform: str  # telegram, discord, twitter, email, all
    content_type: str  # intro, feature, tips, testimonial, engagement, digest
    status: str  # draft, scheduled, running, completed, failed
    created_at: str
    scheduled_at: Optional[str] = None
    completed_at: Optional[str] = None
    results: dict = field(default_factory=dict)


class AutonomousEngine:
    """
    Self-running marketing engine that:
    1. Generates content using AI models
    2. Schedules posts across all platforms
    3. Broadcasts to Telegram groups, Discord servers, email lists
    4. Tracks engagement and adjusts strategy
    """

    def __init__(self):
        self.settings = get_settings()
        self.content_engine = ContentEngine()
        self.telegram = TelegramPoster()
        self.discord = DiscordPoster()
        self.posting = PostingManager()
        self._running = False
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for campaign tracking."""
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT,
                platform TEXT,
                content_type TEXT,
                status TEXT,
                created_at TEXT,
                scheduled_at TEXT,
                completed_at TEXT,
                results TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT,
                platform TEXT,
                content TEXT,
                media_path TEXT,
                status TEXT,
                posted_at TEXT,
                engagement TEXT,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                platform TEXT,
                metric TEXT,
                value REAL,
                metadata TEXT
            )
        """)
        conn.commit()
        conn.close()

    # =========================================================================
    # Content Generation
    # =========================================================================

    async def generate_daily_content(self) -> dict[str, Any]:
        """Generate content for today based on weekly schedule."""
        day_names = {
            0: "intro",      # Monday
            1: "tips",       # Tuesday
            2: "feature",    # Wednesday
            3: "engagement", # Thursday
            4: "testimonial",# Friday
            5: "tips",       # Saturday
            6: "digest",     # Sunday
        }
        today = datetime.now()
        content_type = day_names[today.weekday()]

        log.info(f"Generating {content_type} content for {today.strftime('%A')}")

        # Generate content using AI
        content = await self.content_engine.generate(
            content_type=content_type,
            platform="all",
            tone="professional",
        )

        return {
            "type": content_type,
            "day": today.strftime("%A"),
            "date": today.isoformat(),
            "content": content,
        }

    # =========================================================================
    # Campaign Management
    # =========================================================================

    def create_campaign(
        self,
        name: str,
        platform: str = "all",
        content_type: str = "intro",
        schedule: Optional[str] = None,
    ) -> Campaign:
        """Create a new marketing campaign."""
        campaign = Campaign(
            id=f"camp_{int(time.time())}",
            name=name,
            platform=platform,
            content_type=content_type,
            status="draft",
            created_at=datetime.now().isoformat(),
            scheduled_at=schedule,
        )

        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT INTO campaigns (id, name, platform, content_type, status, created_at, scheduled_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign.id, campaign.name, campaign.platform, campaign.content_type, campaign.status, campaign.created_at, campaign.scheduled_at),
        )
        conn.commit()
        conn.close()

        log.info(f"Created campaign: {campaign.name} ({campaign.id})")
        return campaign

    def list_campaigns(self, status: Optional[str] = None) -> list[Campaign]:
        """List all campaigns, optionally filtered by status."""
        conn = sqlite3.connect(str(DB_PATH))
        if status:
            rows = conn.execute("SELECT * FROM campaigns WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall()
        conn.close()

        campaigns = []
        for row in rows:
            campaigns.append(Campaign(
                id=row[0], name=row[1], platform=row[2],
                content_type=row[3], status=row[4], created_at=row[5],
                scheduled_at=row[6], completed_at=row[7],
                results=json.loads(row[8]) if row[8] else {},
            ))
        return campaigns

    # =========================================================================
    # Broadcasting
    # =========================================================================

    async def broadcast_to_all(self, content: dict[str, Any]) -> dict[str, Any]:
        """Broadcast content to ALL available platforms."""
        results = {
            "telegram": {"status": "skipped", "error": None},
            "discord": {"status": "skipped", "error": None},
            "email": {"status": "skipped", "error": None},
        }

        text = content.get("content", {}).get("text", "")
        media = content.get("content", {}).get("media")

        # 1. Telegram - broadcast to all groups
        try:
            tg_results = await self.telegram.broadcast_to_configured(
                text=text,
                parse_mode="md",
                file=media,
            )
            success_count = sum(1 for r in tg_results if r.status == "ok")
            results["telegram"] = {
                "status": "ok",
                "sent": success_count,
                "total": len(tg_results),
                "targets": [str(r.target.id) for r in tg_results if r.status == "ok"],
            }
            log.info(f"Telegram: {success_count}/{len(tg_results)} sent")
        except Exception as e:
            results["telegram"] = {"status": "error", "error": str(e)}
            log.error(f"Telegram broadcast failed: {e}")

        # 2. Discord - post to channels
        try:
            dc_result = await self.discord.post(text=text)
            results["discord"] = {"status": "ok" if dc_result else "error"}
            log.info(f"Discord: {'ok' if dc_result else 'failed'}")
        except Exception as e:
            results["discord"] = {"status": "error", "error": str(e)}
            log.error(f"Discord post failed: {e}")

        # 3. Email via Gmail MCP
        try:
            email_result = await self._send_email_newsletter(text)
            results["email"] = email_result
        except Exception as e:
            results["email"] = {"status": "error", "error": str(e)}
            log.error(f"Email failed: {e}")

        return results

    async def _send_email_newsletter(self, content: str) -> dict:
        """Send email newsletter via Gmail MCP."""
        # Try opsora-google MCP
        try:
            from opsora_cmd.opsora_google_mcp import send_email
            for account in self.settings.gmail.accounts:
                result = send_email(
                    to=[account],
                    subject=f"Opsora AI Update - {datetime.now().strftime('%B %d, %Y')}",
                    body=content,
                )
                if result:
                    return {"status": "ok", "account": account}
        except ImportError:
            pass

        # Fallback: use google_auth_manager.py
        try:
            import subprocess
            result = subprocess.run(
                ["python3", "/root/google_auth_manager.py", "send", "--to", "cladiusweinert05@gmail.com", "--subject", "Opsora AI Update", "--body", content],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return {"status": "ok", "method": "google_auth_manager"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

        return {"status": "skipped", "reason": "No email method available"}

    # =========================================================================
    # Analytics
    # =========================================================================

    def record_analytics(self, platform: str, metric: str, value: float, metadata: Optional[dict] = None):
        """Record an analytics metric."""
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT INTO analytics (date, platform, metric, value, metadata) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().date().isoformat(), platform, metric, value, json.dumps(metadata or {})),
        )
        conn.commit()
        conn.close()

    def get_analytics_summary(self, days: int = 7) -> dict:
        """Get analytics summary for the last N days."""
        conn = sqlite3.connect(str(DB_PATH))
        cutoff = (datetime.now() - timedelta(days=days)).date().isoformat()

        rows = conn.execute(
            "SELECT platform, metric, SUM(value) FROM analytics WHERE date >= ? GROUP BY platform, metric",
            (cutoff,),
        ).fetchall()
        conn.close()

        summary = {}
        for platform, metric, value in rows:
            if platform not in summary:
                summary[platform] = {}
            summary[platform][metric] = value

        return summary

    # =========================================================================
    # Main Loop
    # =========================================================================

    async def run_once(self) -> dict[str, Any]:
        """Run the engine once: generate content → broadcast → record."""
        log.info("=" * 60)
        log.info("AUTONOMOUS ENGINE RUN STARTED")
        log.info("=" * 60)

        # 1. Generate content
        content = await self.generate_daily_content()
        log.info(f"Content generated: {content['type']}")

        # 2. Create campaign
        campaign = self.create_campaign(
            name=f"Daily {content['type']} - {content['day']}",
            platform="all",
            content_type=content['type'],
        )

        # 3. Broadcast
        broadcast_results = await self.broadcast_to_all(content)
        log.info(f"Broadcast results: {json.dumps(broadcast_results, indent=2)}")

        # 4. Update campaign status
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "UPDATE campaigns SET status = ?, completed_at = ?, results = ? WHERE id = ?",
            ("completed", datetime.now().isoformat(), json.dumps(broadcast_results), campaign.id),
        )
        conn.commit()
        conn.close()

        # 5. Record analytics
        for platform, result in broadcast_results.items():
            if result["status"] == "ok":
                sent_count = result.get("sent", 1)
                self.record_analytics(platform, "posts_sent", sent_count)
                self.record_analytics(platform, "campaigns_completed", 1)

        log.info("=" * 60)
        log.info("AUTONOMOUS ENGINE RUN COMPLETED")
        log.info("=" * 60)

        return {
            "campaign_id": campaign.id,
            "content_type": content['type'],
            "broadcast_results": broadcast_results,
        }

    async def run_daemon(self, interval_hours: int = 24):
        """Run the engine as a daemon, looping every N hours."""
        self._running = True
        log.info(f"Autonomous Engine daemon started (interval: {interval_hours}h)")

        while self._running:
            try:
                result = await self.run_once()
                log.info(f"Run completed: {result['campaign_id']}")
            except Exception as e:
                log.error(f"Run failed: {e}", exc_info=True)

            # Sleep until next run
            log.info(f"Sleeping for {interval_hours} hours...")
            await asyncio.sleep(interval_hours * 3600)

    def stop(self):
        """Stop the daemon."""
        self._running = False
        log.info("Autonomous Engine stopped")


# =========================================================================
# CLI Entry Point
# =========================================================================

async def main():
    engine = AutonomousEngine()

    if len(sys.argv) < 2:
        print("Usage: python3 -m marketing_hub.autonomous_engine [run|daemon|status]")
        return

    command = sys.argv[1]

    if command == "run":
        result = await engine.run_once()
        print(json.dumps(result, indent=2))

    elif command == "daemon":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        await engine.run_daemon(interval)

    elif command == "status":
        campaigns = engine.list_campaigns()
        print(f"\n📊 Autonomous Engine Status")
        print(f"{'='*50}")
        print(f"Total campaigns: {len(campaigns)}")
        for c in campaigns[:10]:
            print(f"  [{c.status}] {c.name} ({c.platform}) - {c.created_at[:10]}")
        print()

        summary = engine.get_analytics_summary(7)
        if summary:
            print(f"📈 Analytics (7 days):")
            for platform, metrics in summary.items():
                print(f"  {platform}: {metrics}")

    elif command == "campaigns":
        campaigns = engine.list_campaigns()
        for c in campaigns:
            print(f"{c.id}: [{c.status}] {c.name} ({c.platform})")

    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    asyncio.run(main())