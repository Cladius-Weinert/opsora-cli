"""
Opsora Marketing Analytics Tracker
Track engagement, conversions, and generate reports.

Usage:
    python3 -m marketing_hub.analytics report --days 7
    python3 -m marketing_hub.analytics track --platform telegram --metric views --value 150
    python3 -m marketing_hub.analytics dashboard
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "analytics.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("analytics")

DB_PATH = Path(__file__).parent / "marketing.db"


class Analytics:
    """
    Track and report marketing analytics.
    Stores data in SQLite and generates reports.
    """

    def __init__(self):
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                platform TEXT,
                metric TEXT,
                value REAL,
                metadata TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT,
                platform TEXT,
                content_type TEXT,
                status TEXT,
                created_at TEXT,
                completed_at TEXT,
                results TEXT
            )
        """)
        conn.commit()
        conn.close()

    def track(self, platform: str, metric: str, value: float, metadata: Optional[dict] = None):
        """Track a metric."""
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT INTO analytics (date, platform, metric, value, metadata) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().date().isoformat(), platform, metric, value, json.dumps(metadata or {})),
        )
        conn.commit()
        conn.close()
        log.info(f"Tracked: {platform}/{metric} = {value}")

    def get_report(self, days: int = 7) -> dict[str, Any]:
        """Generate a report for the last N days."""
        conn = sqlite3.connect(str(DB_PATH))
        cutoff = (datetime.now() - timedelta(days=days)).date().isoformat()

        rows = conn.execute(
            "SELECT platform, metric, SUM(value), COUNT(*) FROM analytics WHERE date >= ? GROUP BY platform, metric ORDER BY platform, metric",
            (cutoff,),
        ).fetchall()

        daily = conn.execute(
            "SELECT date, platform, metric, SUM(value) FROM analytics WHERE date >= ? GROUP BY date, platform, metric ORDER BY date",
            (cutoff,),
        ).fetchall()

        campaigns = conn.execute(
            "SELECT status, COUNT(*) FROM campaigns WHERE created_at >= ? GROUP BY status",
            (cutoff,),
        ).fetchall()

        conn.close()

        platforms = defaultdict(dict)
        for platform, metric, total, count in rows:
            platforms[platform][metric] = {"total": total, "count": count, "avg": total / count if count else 0}

        daily_data = defaultdict(lambda: defaultdict(dict))
        for date, platform, metric, total in daily:
            daily_data[date][platform][metric] = total

        campaign_stats = {status: count for status, count in campaigns}

        return {
            "period_days": days,
            "generated_at": datetime.now().isoformat(),
            "platforms": dict(platforms),
            "daily": {k: dict(v) for k, v in daily_data.items()},
            "campaigns": campaign_stats,
            "summary": self._generate_summary(platforms, campaign_stats),
        }

    def _generate_summary(self, platforms: dict, campaign_stats: dict) -> str:
        total_posts = sum(m.get("posts_sent", {}).get("total", 0) for m in platforms.values())
        total_campaigns = campaign_stats.get("completed", 0)
        active_platforms = len(platforms)

        lines = [
            f"📊 Marketing Analytics Summary",
            f"{'='*40}",
            f"Active platforms: {active_platforms}",
            f"Total posts: {int(total_posts)}",
            f"Campaigns completed: {total_campaigns}",
        ]

        for platform, metrics in platforms.items():
            lines.append(f"\n  {platform}:")
            for metric, data in metrics.items():
                lines.append(f"    {metric}: {int(data['total'])} (avg {data['avg']:.1f}/day)")

        return "\n".join(lines)

    def export_json(self, days: int = 7) -> str:
        report = self.get_report(days)
        return json.dumps(report, indent=2, default=str)


# =========================================================================
# CLI
# =========================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Opsora Marketing Analytics")
    subparsers = parser.add_subparsers(dest="command")

    track_parser = subparsers.add_parser("track", help="Track a metric")
    track_parser.add_argument("--platform", required=True)
    track_parser.add_argument("--metric", required=True)
    track_parser.add_argument("--value", type=float, required=True)
    track_parser.add_argument("--metadata", help="JSON metadata")

    report_parser = subparsers.add_parser("report", help="Generate report")
    report_parser.add_argument("--days", type=int, default=7)
    report_parser.add_argument("--format", choices=["text", "json"], default="text")

    subparsers.add_parser("dashboard", help="Show live dashboard")

    args = parser.parse_args()
    analytics = Analytics()

    if args.command == "track":
        metadata = json.loads(args.metadata) if args.metadata else None
        analytics.track(args.platform, args.metric, args.value, metadata)
        print(f"✅ Tracked: {args.platform}/{args.metric} = {args.value}")

    elif args.command == "report":
        report = analytics.get_report(args.days)
        if args.format == "json":
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"\n{report['summary']}")
            print(f"\n📈 Daily Breakdown:")
            for date, platforms in sorted(report.get("daily", {}).items()):
                print(f"\n  {date}:")
                for platform, metrics in platforms.items():
                    for metric, value in metrics.items():
                        print(f"    {platform}/{metric}: {int(value)}")

    elif args.command == "dashboard":
        report = analytics.get_report(7)
        print(f"\n📊 Live Dashboard")
        print(f"{'='*50}")
        print(report["summary"])
        print(f"\n💾 Data: {DB_PATH}")

    else:
        report = analytics.get_report(1)
        print(report["summary"])


if __name__ == "__main__":
    main()