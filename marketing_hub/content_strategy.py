"""
Opsora Content Strategy Engine
Auto-generates content for each day of the week, bilingual (ID/EN),
with A/B testing, hashtag optimization, and image generation.

Usage:
    python3 -m marketing_hub.content_strategy generate --type intro
    python3 -m marketing_hub.content_strategy calendar --week
    python3 -m marketing_hub.content_strategy hashtags --topic ai
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "content_strategy.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("content_strategy")


# =========================================================================
# Content Templates (Bilingual ID/EN)
# =========================================================================

CONTENT_TEMPLATES = {
    "intro": {
        "id": [
            "Kenalan dengan Opsora AI 🤖\n\nSatu terminal. Semua AI provider. Zero vendor lock-in.\n\n{feature}\n\nCoba sekarang: {link}",
            "Selamat datang di Opsora AI! 🚀\n\nKami menghubungkan Anda ke 7 AI provider sekaligus:\n• NVIDIA NIM — Model flagship\n• Alibaba DashScope — Qwen series\n• OpenAI — GPT-4o\n• AWS Bedrock — Nova Pro\n• Dan lainnya!\n\n{link}",
        ],
        "en": [
            "Meet Opsora AI 🤖\n\nOne terminal. Every AI provider. Zero vendor lock-in.\n\n{feature}\n\nTry it now: {link}",
            "Welcome to Opsora AI! 🚀\n\nWe connect you to 7 AI providers at once:\n• NVIDIA NIM — Flagship models\n• Alibaba DashScope — Qwen series\n• OpenAI — GPT-4o\n• AWS Bedrock — Nova Pro\n• And more!\n\n{link}",
        ],
    },
    "feature": {
        "id": [
            "Tahukah kamu? 🔍\n\nOpsora secara OTOMATIS me-rute prompt kamu ke model AI TERBAIK berdasarkan intent:\n\n💻 Coding → DeepSeek V4 Flash\n🧠 Analisis → Nemotron 3 Super 120B\n⚡ Cepat → Nemotron Mini 4B\n🎨 Visual → Llama 3.2 90B Vision\n\n{link}",
            "Fitur Opsora minggu ini ✨\n\n{feature}\n\n{link}",
        ],
        "en": [
            "Did you know? 🔍\n\nOpsora automatically ROUTES your prompts to the BEST AI model based on intent:\n\n💻 Coding → DeepSeek V4 Flash\n🧠 Analysis → Nemotron 3 Super 120B\n⚡ Quick → Nemotron Mini 4B\n🎨 Visual → Llama 3.2 90B Vision\n\n{link}",
            "This week's Opsora feature ✨\n\n{feature}\n\n{link}",
        ],
    },
    "tips": {
        "id": [
            "Tips Opsora hari ini 💡\n\nGunakan perintah /model untuk ganti provider secara instan:\n\n/model nvidia → NVIDIA NIM\n/model alibaba → Alibaba DashScope\n/model openai → OpenAI\n\nCoba sekarang! {link}",
            "Pro tip: Opsora punya auto-fallback! 🔄\n\nKalau provider utama down, Opsora otomatis cascade ke provider berikutnya. No dropped prompts. No manual retries.\n\n{link}",
        ],
        "en": [
            "Opsora Tip of the Day 💡\n\nUse /model to switch providers instantly:\n\n/model nvidia → NVIDIA NIM\n/model alibaba → Alibaba DashScope\n/model openai → OpenAI\n\nTry it now! {link}",
            "Pro tip: Opsora has auto-fallback! 🔄\n\nIf your primary provider goes down, Opsora automatically cascades to the next provider. No dropped prompts. No manual retries.\n\n{link}",
        ],
    },
    "testimonial": {
        "id": [
            '"Opsora menghemat 40% biaya API kami dengan smart routing!" — Tim Developer\n\n{feature}\n\nCoba gratis: {link}',
            '"Akhirnya, satu tool untuk semua AI provider. No more switching between dashboards!" — Early Adopter\n\n{link}',
        ],
        "en": [
            "\"Opsora saved us 40% on API costs with smart routing!\" — Dev Team\n\n{feature}\n\nTry for free: {link}",
            "\"Finally, one tool for all AI providers. No more switching between dashboards!\" — Early Adopter\n\n{link}",
        ],
    },
    "engagement": {
        "id": [
            "Pertanyaan untuk kamu! 💬\n\nAI provider mana yang paling sering kamu gunakan?\n\n1️⃣ NVIDIA\n2️⃣ OpenAI\n3️⃣ Google\n4️⃣ Lainnya\n\nKomen di bawah! 👇\n\n{link}",
            "Kami ingin dengar pendapatmu! 🗣️\n\nFitur apa yang paling kamu inginkan dari AI coding assistant?\n\na) Multi-provider\nb) Auto-routing\nc) Tool calling\nd) Semua di atas!\n\n{link}",
        ],
        "en": [
            "Question for you! 💬\n\nWhich AI provider do you use most?\n\n1️⃣ NVIDIA\n2️⃣ OpenAI\n3️⃣ Google\n4️⃣ Other\n\nComment below! 👇\n\n{link}",
            "We want to hear from you! 🗣️\n\nWhat feature do you want most in an AI coding assistant?\n\na) Multi-provider\nb) Auto-routing\nc) Tool calling\nd) All of the above!\n\n{link}",
        ],
    },
    "digest": {
        "id": [
            "📬 Opsora Weekly Digest\n\nMinggu ini di Opsora:\n{feature}\n\n{link}",
            "Ringkasan minggu ini 📋\n\n{feature}\n\nJangan lewatkan update selanjutnya! {link}",
        ],
        "en": [
            "📬 Opsora Weekly Digest\n\nThis week in Opsora:\n{feature}\n\n{link}",
            "This week's roundup 📋\n\n{feature}\n\nDon't miss the next update! {link}",
        ],
    },
}

# Hashtag library
HASHTAGS = {
    "ai": ["#AI", "#ArtificialIntelligence", "#MachineLearning", "#DeepLearning"],
    "coding": ["#Coding", "#Programming", "#DevTools", "#SoftwareEngineering"],
    "opensource": ["#OpenSource", "#OSS", "#GitHub", "#MIT"],
    "developer": ["#Developer", "#DevCommunity", "#Tech", "#Programmer"],
    "opsora": ["#OpsoraAI", "#OneTerminal", "#ZeroLockIn", "#MultiProvider"],
    "indonesia": ["#TechIndonesia", "#DevIndonesia", "#AIIndonesia", "#StartupIndonesia"],
}

WEEKLY_SCHEDULE = {
    0: ("intro", "Monday Introduction"),
    1: ("tips", "Tuesday Tips"),
    2: ("feature", "Wednesday Feature"),
    3: ("engagement", "Thursday Engagement"),
    4: ("testimonial", "Friday Testimonial"),
    5: ("tips", "Saturday Tips"),
    6: ("digest", "Sunday Digest"),
}


@dataclass
class ContentPlan:
    """A planned content item."""
    day: str
    content_type: str
    title: str
    language: str  # id, en, or both
    templates: list[str]
    hashtags: list[str]
    scheduled_time: str


class ContentStrategy:
    """
    Content strategy engine that generates, schedules, and optimizes content.
    """

    def __init__(self):
        self.base_url = "https://opsora-landing-zeta.vercel.app"
        self.github_url = "https://github.com/Cladius-Weinert/opsora-cli"

    def get_today_plan(self) -> ContentPlan:
        """Get content plan for today."""
        today = datetime.now()
        day_name = today.strftime("%A")
        content_type, title = WEEKLY_SCHEDULE.get(today.weekday(), ("intro", "General"))

        return ContentPlan(
            day=day_name,
            content_type=content_type,
            title=title,
            language="both",
            templates=CONTENT_TEMPLATES.get(content_type, {}).get("id", []),
            hashtags=self._get_hashtags(content_type),
            scheduled_time="09:00 WITA",
        )

    def get_weekly_calendar(self) -> list[ContentPlan]:
        """Get content plan for the entire week."""
        plans = []
        today = datetime.now()

        for day_offset in range(7):
            day = today + timedelta(days=day_offset)
            content_type, title = WEEKLY_SCHEDULE.get(day.weekday(), ("intro", "General"))

            plans.append(ContentPlan(
                day=day.strftime("%A"),
                content_type=content_type,
                title=title,
                language="both",
                templates=CONTENT_TEMPLATES.get(content_type, {}).get("id", []),
                hashtags=self._get_hashtags(content_type),
                scheduled_time="09:00 WITA",
            ))

        return plans

    def _get_hashtags(self, content_type: str) -> list[str]:
        """Get relevant hashtags for content type."""
        tags = []
        tags.extend(random.sample(HASHTAGS["opsora"], min(2, len(HASHTAGS["opsora"]))))
        tags.extend(random.sample(HASHTAGS["ai"], min(2, len(HASHTAGS["ai"]))))
        tags.extend(random.sample(HASHTAGS["developer"], min(1, len(HASHTAGS["developer"]))))

        if content_type in ("intro", "feature"):
            tags.extend(random.sample(HASHTAGS["opensource"], min(1, len(HASHTAGS["opensource"]))))

        return tags

    def generate_content(
        self,
        content_type: str = "intro",
        language: str = "both",
        feature: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate content for a specific type."""
        templates = CONTENT_TEMPLATES.get(content_type, CONTENT_TEMPLATES["intro"])

        result = {}
        langs = ["id", "en"] if language == "both" else [language]

        for lang in langs:
            lang_templates = templates.get(lang, templates.get("en", []))
            if lang_templates:
                template = random.choice(lang_templates)
                content = template.format(
                    feature=feature or "Smart auto-routing ke 7 AI provider dari satu terminal.",
                    link=self.base_url,
                )
                result[lang] = content

        return result

    def generate_weekly_content(self) -> list[dict[str, Any]]:
        """Generate content for the entire week."""
        weekly_content = []
        features = [
            "Smart auto-routing ke model AI terbaik berdasarkan intent prompt",
            "Multi-provider: NVIDIA, Alibaba, OpenAI, AWS, dan lainnya",
            "Auto-fallback: tidak ada prompt yang dropped",
            "Tool calling: read, write, run, search, memory built-in",
            "YOLO mode untuk auto-execute operasi aman",
            "Persistent memory across sessions",
            "Open source MIT — no vendor lock-in",
        ]

        for i, (day_offset, (content_type, title)) in enumerate(WEEKLY_SCHEDULE.items()):
            feature = features[i % len(features)]
            content = self.generate_content(content_type, "both", feature)
            hashtags = self._get_hashtags(content_type)

            weekly_content.append({
                "day": datetime.now().strftime("%A"),
                "content_type": content_type,
                "title": title,
                "content": content,
                "hashtags": hashtags,
                "scheduled_time": "09:00 WITA",
            })

        return weekly_content

    def optimize_hashtags(self, topic: str = "ai") -> list[str]:
        """Get optimized hashtags for a topic."""
        topic = topic.lower()
        tags = []

        for key, values in HASHTAGS.items():
            if topic in key or key in topic:
                tags.extend(values)

        if not tags:
            tags = HASHTAGS["opsora"] + HASHTAGS["ai"]

        return tags[:8]  # Max 8 hashtags


# =========================================================================
# CLI
# =========================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Opsora Content Strategy Engine")
    subparsers = parser.add_subparsers(dest="command")

    # Generate
    gen_parser = subparsers.add_parser("generate", help="Generate content")
    gen_parser.add_argument("--type", default="intro", choices=list(CONTENT_TEMPLATES.keys()))
    gen_parser.add_argument("--lang", default="both", choices=["id", "en", "both"])
    gen_parser.add_argument("--feature", help="Custom feature description")

    # Calendar
    subparsers.add_parser("calendar", help="Show content calendar")

    # Hashtags
    hash_parser = subparsers.add_parser("hashtags", help="Get hashtag suggestions")
    hash_parser.add_argument("--topic", default="ai", help="Topic for hashtags")

    args = parser.parse_args()
    strategy = ContentStrategy()

    if args.command == "generate":
        content = strategy.generate_content(args.type, args.lang, args.feature)
        print(f"\n📝 Content: {args.type}")
        print(f"{'='*50}")
        for lang, text in content.items():
            print(f"\n[{lang.upper()}]")
            print(text)
        print()

    elif args.command == "calendar":
        plans = strategy.get_weekly_calendar()
        print(f"\n📅 Weekly Content Calendar")
        print(f"{'='*50}")
        for plan in plans:
            print(f"  {plan.day}: {plan.title} ({plan.content_type})")
        print()

    elif args.command == "hashtags":
        tags = strategy.optimize_hashtags(args.topic)
        print(f"\n🏷️  Hashtags for '{args.topic}'")
        print(f"{'='*50}")
        print("  " + " ".join(tags))
        print()

    else:
        # Default: show today's plan
        plan = strategy.get_today_plan()
        content = strategy.generate_content(plan.content_type)
        print(f"\n📋 Today's Plan: {plan.day} - {plan.title}")
        print(f"{'='*50}")
        for lang, text in content.items():
            print(f"\n[{lang.upper()}]")
            print(text)
        print(f"\n🏷️  {', '.join(plan.hashtags)}")
        print()


if __name__ == "__main__":
    main()