"""
Content Engine - AI-powered content generation with templates and variants.

Features:
- Jinja2 template engine for structured content
- AI model integration (NVIDIA Nemotron, Alibaba Qwen via Opsora routing)
- Content variants for A/B testing
- Hashtag optimization
- Content calendar
- SEO/keyword integration
- Multi-platform formatting
"""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional
from string import Template

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .settings import get_settings, BrandSettings, AIModelSettings
from .posting import Platform, PostContent, MediaAttachment, create_post_content

log = logging.getLogger("marketing.content")


# =========================================================================
# Data Classes
# =========================================================================

@dataclass(slots=True)
class ContentTemplate:
    """Content template with metadata."""
    name: str
    description: str
    category: str  # "promo", "educational", "engagement", "news", "testimonial"
    platforms: list[Platform] = field(default_factory=lambda: [Platform.TELEGRAM, Platform.DISCORD])
    template_text: str = ""
    template_file: Optional[str] = None
    variables: list[str] = field(default_factory=list)
    required_vars: list[str] = field(default_factory=list)
    default_vars: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def render(self, variables: dict) -> str:
        """Render template with variables."""
        # Merge defaults
        vars_merged = {**self.default_vars, **variables}

        # Check required
        missing = [v for v in self.required_vars if v not in vars_merged]
        if missing:
            raise ValueError(f"Missing required variables: {missing}")

        # Use Jinja2 if template has {{ }} syntax
        if "{{" in self.template_text:
            env = Environment(autoescape=select_autoescape())
            template = env.from_string(self.template_text)
            return template.render(**vars_merged)

        # Fallback to string.Template
        template = Template(self.template_text)
        return template.safe_substitute(vars_merged)


@dataclass(slots=True)
class ContentVariant:
    """Content variant for A/B testing."""
    id: str
    template_name: str
    variables: dict
    weight: float = 1.0  # Selection weight
    platform_overrides: dict[Platform, dict] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class GeneratedContent:
    """Generated content with variants."""
    base_content: PostContent
    variants: list[ContentVariant] = field(default_factory=list)
    selected_variant: Optional[ContentVariant] = None
    metadata: dict = field(default_factory=dict)

    def get_content(self, platform: Platform) -> PostContent:
        """Get platform-specific content, applying variant if selected."""
        content = self.base_content

        if self.selected_variant:
            # Apply variant overrides
            override = self.selected_variant.platform_overrides.get(platform, {})
            for key, value in override.items():
                if hasattr(content, key):
                    setattr(content, key, value)

        return content


# =========================================================================
# Template Library
# =========================================================================

DEFAULT_TEMPLATES: dict[str, ContentTemplate] = {
    "intro": ContentTemplate(
        name="intro",
        description="Brand introduction post",
        category="promo",
        platforms=[Platform.TELEGRAM, Platform.DISCORD, Platform.TWITTER],
        template_text="""🚀 Introducing {{ brand_name }}

{{ tagline }}

✅ {{ feature_1 }}
✅ {{ feature_2 }}
✅ {{ feature_3 }}
✅ {{ feature_4 }}
✅ {{ feature_5 }}

Stop juggling 10 different tools. {{ brand_name }} does it all.

🔗 {{ website }}
{{ handle }}

{{ hashtags }}""",
        variables=["brand_name", "tagline", "feature_1", "feature_2", "feature_3", "feature_4", "feature_5", "website", "handle", "hashtags"],
        required_vars=["brand_name", "website", "handle"],
        default_vars={
            "feature_1": "AI Chatbot for customer service",
            "feature_2": "Automated lead generation",
            "feature_3": "Smart CRM & pipeline management",
            "feature_4": "Social media management",
            "feature_5": "Website & landing page builder",
        },
        tags=["launch", "introduction", "brand"],
    ),

    "feature_highlight": ContentTemplate(
        name="feature_highlight",
        description="Highlight a specific feature",
        category="promo",
        platforms=[Platform.TELEGRAM, Platform.DISCORD, Platform.TWITTER],
        template_text="""⚡ {{ brand_name }} Feature Spotlight: {{ feature_name }}

{{ description }}

Why businesses choose {{ brand_name }}:
• No coding required
• Setup in under 5 minutes
• Affordable pricing for UMKM
• Full Bahasa Indonesia support

👉 {{ cta }}: {{ website }}

{{ hashtags }}""",
        variables=["brand_name", "feature_name", "description", "cta", "website", "hashtags"],
        required_vars=["brand_name", "feature_name", "description", "website"],
        default_vars={"cta": "Try it free"},
        tags=["feature", "product"],
    ),

    "tips": ContentTemplate(
        name="tips",
        description="Educational tips post",
        category="educational",
        platforms=[Platform.TELEGRAM, Platform.DISCORD, Platform.TWITTER],
        template_text="""💡 {{ title }}

{{ points }}

Semua ini bisa kamu lakukan dengan {{ brand_name }}. Mulai dari GRATIS!

🔗 {{ website }}

{{ hashtags }}""",
        variables=["title", "points", "brand_name", "website", "hashtags"],
        required_vars=["title", "points", "brand_name", "website"],
        default_vars={
            "title": "5 Cara AI Bisa Tingkatkan Penjualan",
            "points": "1. Chatbot 24/7 — jangan biarkan customer pergi tanpa jawaban\n2. Lead scoring otomatis — fokus ke prospect yang paling potensial\n3. Email follow-up otomatis — nurture leads tanpa effort\n4. Social media scheduler — konsisten posting tanpa repot\n5. Analytics dashboard — tahu apa yang works, cut yang tidak",
        },
        tags=["tips", "education", "umkm"],
    ),

    "testimonial": ContentTemplate(
        name="testimonial",
        description="Social proof/testimonial post",
        category="testimonial",
        platforms=[Platform.TELEGRAM, Platform.DISCORD, Platform.TWITTER],
        template_text="""📊 Results speak louder than promises.

With {{ brand_name }}, businesses are seeing:
• {{ stat_1 }}
• {{ stat_2 }}
• {{ stat_3 }}
• {{ stat_4 }}

Ready to see results? Start free at {{ website }}

{{ hashtags }}""",
        variables=["brand_name", "stat_1", "stat_2", "stat_3", "stat_4", "website", "hashtags"],
        required_vars=["brand_name", "website"],
        default_vars={
            "stat_1": "3x faster response time to customers",
            "stat_2": "40% more qualified leads",
            "stat_3": "60% reduction in manual admin work",
            "stat_4": "24/7 customer engagement without hiring extra staff",
        },
        tags=["results", "social-proof", "testimonial"],
    ),

    "engagement": ContentTemplate(
        name="engagement",
        description="Engagement question post",
        category="engagement",
        platforms=[Platform.TELEGRAM, Platform.DISCORD, Platform.TWITTER],
        template_text="""🤔 {{ question }}

Drop jawaban kamu di komentar! 👇

{{ brand_name }} hadir untuk bantu kamu automate dan scale bisnis dengan AI.

🔗 {{ website }}

{{ hashtags }}""",
        variables=["question", "brand_name", "website", "hashtags"],
        required_vars=["question", "brand_name", "website"],
        default_vars={
            "question": "Apa tantangan terbesar kamu dalam mengelola bisnis online?",
        },
        tags=["engagement", "discussion", "community"],
    ),

    "weekly_digest": ContentTemplate(
        name="weekly_digest",
        description="Weekly update post",
        category="news",
        platforms=[Platform.TELEGRAM, Platform.DISCORD],
        template_text="""📅 Week {{ week }} Update from {{ brand_name }}

This week we shipped:
{{ shipped }}

What's coming next:
{{ coming }}

Stay tuned! Follow {{ handle }} for updates.

🔗 {{ website }}

{{ hashtags }}""",
        variables=["week", "brand_name", "shipped", "coming", "handle", "website", "hashtags"],
        required_vars=["brand_name", "website", "handle"],
        default_vars={
            "shipped": "🔧 New features and improvements\n📈 Growing community\n💬 Amazing feedback from users",
            "coming": "• Advanced AI agent workflows\n• Multi-channel inbox integration\n• Better analytics dashboard",
        },
        tags=["weekly", "update", "news"],
    ),

    "case_study": ContentTemplate(
        name="case_study",
        description="Customer case study",
        category="testimonial",
        platforms=[Platform.TELEGRAM, Platform.DISCORD],
        template_text="""📈 Case Study: {{ customer_name }}

{{ customer_type }} from {{ location }} was struggling with:
• {{ problem_1 }}
• {{ problem_2 }}

After implementing {{ brand_name }}:
✅ {{ result_1 }}
✅ {{ result_2 }}
✅ {{ result_3 }}

"{{ quote }}" — {{ customer_name }}

Want similar results? 👉 {{ website }}

{{ hashtags }}""",
        variables=["customer_name", "customer_type", "location", "problem_1", "problem_2", "brand_name", "result_1", "result_2", "result_3", "quote", "website", "hashtags"],
        required_vars=["customer_name", "brand_name", "website"],
        tags=["case-study", "customer-success"],
    ),

    "announcement": ContentTemplate(
        name="announcement",
        description="Product announcement",
        category="news",
        platforms=[Platform.TELEGRAM, Platform.DISCORD, Platform.TWITTER],
        template_text="""🎉 BIG NEWS: {{ title }}

{{ description }}

What's new:
{{ features }}

Available now for all {{ brand_name }} users! 

🔗 {{ website }}

{{ hashtags }}""",
        variables=["title", "description", "features", "brand_name", "website", "hashtags"],
        required_vars=["title", "brand_name", "website"],
        tags=["announcement", "product-update", "launch"],
    ),
}


# =========================================================================
# Content Engine
# =========================================================================

class ContentEngine:
    """
    Main content generation engine.

    Features:
    - Template-based generation
    - AI-powered content enhancement
    - A/B test variants
    - Hashtag optimization
    - Content calendar
    - Multi-platform formatting
    """

    def __init__(
        self,
        templates: Optional[dict[str, ContentTemplate]] = None,
        brand: Optional[BrandSettings] = None,
        ai_settings: Optional[AIModelSettings] = None,
        template_dir: Optional[Path] = None,
    ):
        self.templates = templates or DEFAULT_TEMPLATES.copy()
        self.brand = brand or get_settings().brand
        self.ai_settings = ai_settings or get_settings().ai
        self.template_dir = template_dir

        # Jinja2 environment for file-based templates
        self._jinja_env = None
        if template_dir and template_dir.exists():
            self._jinja_env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=select_autoescape(),
            )

        # Content calendar
        self._calendar: dict[str, str] = {}  # date -> template_name

        # Hashtag sets
        self._hashtag_sets: dict[str, list[str]] = {
            "default": ["#AI", "#BusinessAutomation", "#StartupIndonesia", "#SaaS", "#OpsoraAI"],
            "umkm": ["#UMKM", "#DigitalMarketing", "#SmallBusiness", "#Indonesia"],
            "tech": ["#AI", "#MachineLearning", "#Automation", "#TechIndonesia"],
            "engagement": ["#Discussion", "#Community", "#BusinessTips"],
            "promo": ["#Promo", "#Discount", "#LimitedTime"],
        }

        # AI client (lazy init)
        self._ai_client = None

    # =========================================================================
    # Template Management
    # =========================================================================

    def register_template(self, template: ContentTemplate) -> None:
        """Register a new template."""
        self.templates[template.name] = template
        log.info("Registered template: %s", template.name)

    def unregister_template(self, name: str) -> bool:
        """Unregister a template."""
        if name in self.templates:
            del self.templates[name]
            return True
        return False

    def get_template(self, name: str) -> Optional[ContentTemplate]:
        """Get template by name."""
        return self.templates.get(name)

    def list_templates(self, category: Optional[str] = None) -> list[ContentTemplate]:
        """List all templates."""
        templates = list(self.templates.values())
        if category:
            templates = [t for t in templates if t.category == category]
        return templates

    def load_templates_from_dir(self, directory: Path) -> int:
        """Load templates from JSON files in directory."""
        count = 0
        for file in directory.glob("*.json"):
            try:
                with open(file) as f:
                    data = json.load(f)
                template = ContentTemplate(**data)
                self.register_template(template)
                count += 1
            except Exception as e:
                log.error("Failed to load template %s: %s", file, e)
        return count

    # =========================================================================
    # Content Generation
    # =========================================================================

    def generate(
        self,
        template_name: str,
        variables: Optional[dict] = None,
        platform: Optional[Platform] = None,
        variant: Optional[ContentVariant] = None,
        hashtag_set: str = "default",
    ) -> GeneratedContent:
        """
        Generate content from template.

        Args:
            template_name: Template to use
            variables: Template variables
            platform: Target platform (for platform-specific formatting)
            variant: A/B test variant to apply
            hashtag_set: Hashtag set to use

        Returns:
            GeneratedContent with base content and variants
        """
        template = self.templates.get(template_name)
        if not template:
            raise ValueError(f"Template not found: {template_name}")

        # Merge variables with brand defaults
        vars_merged = {
            "brand_name": self.brand.name,
            "handle": self.brand.handle,
            "website": self.brand.website,
            "email": self.brand.email,
            "tagline": self.brand.tagline,
            "description": self.brand.description,
            "hashtags": " ".join(self._hashtag_sets.get(hashtag_set, self._hashtag_sets["default"])),
            **(variables or {}),
        }

        # Render template
        text = template.render(vars_merged)

        # Create base content
        base_content = create_post_content(
            text=text,
            brand=self.brand,
            platform=platform,
            campaign_id=vars_merged.get("campaign_id"),
            utm_source=vars_merged.get("utm_source", platform.value if platform else "content_engine"),
        )

        # Generate variants for A/B testing
        variants = self._generate_variants(template, vars_merged, platform)

        # Apply selected variant
        selected = variant
        if not selected and variants:
            # Weighted random selection
            total_weight = sum(v.weight for v in variants)
            r = random.uniform(0, total_weight)
            for v in variants:
                r -= v.weight
                if r <= 0:
                    selected = v
                    break

        return GeneratedContent(
            base_content=base_content,
            variants=variants,
            selected_variant=selected,
            metadata={
                "template": template_name,
                "variables": vars_merged,
                "platform": platform.value if platform else None,
                "hashtag_set": hashtag_set,
            },
        )

    def _generate_variants(
        self,
        template: ContentTemplate,
        variables: dict,
        platform: Optional[Platform],
    ) -> list[ContentVariant]:
        """Generate A/B test variants."""
        variants = []

        # Variant A: Original
        variants.append(ContentVariant(
            id="A",
            template_name=template.name,
            variables=variables.copy(),
            weight=1.0,
        ))

        # Variant B: Shorter version (for Twitter)
        if platform == Platform.TWITTER or template.name in ("tips", "engagement"):
            short_vars = variables.copy()
            # Could use AI to shorten
            variants.append(ContentVariant(
                id="B",
                template_name=template.name,
                variables=short_vars,
                weight=0.8,
                platform_overrides={
                    Platform.TWITTER: {"twitter_text": "Shortened version..."},
                },
            ))

        # Variant C: With emoji emphasis
        emoji_vars = variables.copy()
        variants.append(ContentVariant(
            id="C",
            template_name=template.name,
            variables=emoji_vars,
            weight=0.7,
            platform_overrides={
                Platform.TELEGRAM: {"text": "🎉 " + variables.get("text", "")},
                Platform.DISCORD: {"embeds": [{"description": "🎉 " + variables.get("text", "")}]},
            },
        ))

        return variants

    def generate_post(
        self,
        post_type: str = "random",
        **kwargs,
    ) -> PostContent:
        """
        Generate a post (simplified interface).

        Args:
            post_type: Template name or "random"
            **kwargs: Template variables

        Returns:
            PostContent ready for posting
        """
        if post_type == "random":
            post_type = random.choice(list(self.templates.keys()))

        generated = self.generate(post_type, **kwargs)
        content = generated.get_content(kwargs.get("platform"))

        return content

    # =========================================================================
    # AI Enhancement
    # =========================================================================

    async def enhance_with_ai(
        self,
        content: PostContent,
        prompt: str,
        platform: Optional[Platform] = None,
    ) -> PostContent:
        """
        Enhance content using AI model.

        Args:
            content: Base content to enhance
            prompt: Enhancement prompt
            platform: Target platform

        Returns:
            Enhanced PostContent
        """
        # Use Opsora's model routing for AI generation
        from opsora_cmd.opsora_routing import route
        from opsora_cmd.opsora_v2 import get_alibaba_client, get_nvidia_client

        provider, model = route(
            f"Marketing content enhancement: {prompt}",
            required_capability="creative",
        )

        client = None
        if provider == "alibaba":
            client = get_alibaba_client()
        elif provider == "nvidia":
            client = get_nvidia_client()

        if not client:
            log.warning("No AI client available, returning original content")
            return content

        # Build enhancement prompt
        system_prompt = f"""You are a marketing copywriter for {self.brand.name} ({self.brand.handle}).
Brand: {self.brand.description}
Tone: Professional, helpful, Indonesian business context
Platform: {platform.value if platform else "multi-platform"}

Enhance the following content based on the user's request."""

        user_prompt = f"""
Original content:
{content.text}

Enhancement request: {prompt}

Return only the enhanced content, optimized for {platform.value if platform else 'all platforms'}.
Include relevant hashtags.
"""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.ai_settings.temperature,
                max_tokens=self.ai_settings.max_tokens,
                top_p=self.ai_settings.top_p,
            )

            enhanced_text = response.choices[0].message.content.strip()

            # Create new content with enhanced text
            return create_post_content(
                text=enhanced_text,
                brand=self.brand,
                platform=platform,
                campaign_id=content.campaign_id,
                utm_source=content.utm_params.get("utm_source"),
            )

        except Exception as e:
            log.error("AI enhancement failed: %s", e)
            return content

    async def generate_from_prompt(
        self,
        prompt: str,
        platform: Optional[Platform] = None,
        content_type: Optional[str] = None,
    ) -> PostContent:
        """
        Generate content from a natural language prompt using AI.

        Args:
            prompt: Natural language description of desired content
            platform: Target platform
            content_type: Type hint (promo, educational, engagement, etc.)

        Returns:
            Generated PostContent
        """
        provider, model = route(
            f"Generate marketing content: {prompt}",
            required_capability="creative",
        )

        client = None
        if provider == "alibaba":
            client = get_alibaba_client()
        elif provider == "nvidia":
            client = get_nvidia_client()

        if not client:
            # Fallback to template
            return self.generate_post("random", platform=platform)

        system_prompt = f"""You are a marketing copywriter for {self.brand.name} ({self.brand.handle}).
Brand: {self.brand.description}
Website: {self.brand.website}
Tone: Professional, helpful, Indonesian business context, uses Bahasa Indonesia naturally
Platform: {platform.value if platform else "multi-platform"}
Content type: {content_type or "auto"}

Generate engaging marketing content based on the user's prompt.
Include a clear call-to-action and relevant hashtags.
Return only the content text."""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.ai_settings.temperature,
                max_tokens=self.ai_settings.max_tokens,
                top_p=self.ai_settings.top_p,
            )

            text = response.choices[0].message.content.strip()

            return create_post_content(
                text=text,
                brand=self.brand,
                platform=platform,
                utm_source=platform.value if platform else "ai_generated",
            )

        except Exception as e:
            log.error("AI generation failed: %s", e)
            return self.generate_post("random", platform=platform)

    # =========================================================================
    # Hashtag Management
    # =========================================================================

    def add_hashtag_set(self, name: str, hashtags: list[str]) -> None:
        """Add a hashtag set."""
        self._hashtag_sets[name] = hashtags

    def get_hashtag_set(self, name: str) -> list[str]:
        """Get hashtag set."""
        return self._hashtag_sets.get(name, self._hashtag_sets["default"])

    def suggest_hashtags(
        self,
        text: str,
        platform: Platform,
        max_tags: int = 10,
    ) -> list[str]:
        """Suggest hashtags based on content."""
        # Simple keyword-based suggestion
        # In production, could use AI or trending API
        keywords = [
            ("ai", ["#AI", "#ArtificialIntelligence", "#MachineLearning"]),
            ("umkm", ["#UMKM", "#SmallBusiness", "#SME"]),
            ("marketing", ["#DigitalMarketing", "#MarketingTips", "#SocialMediaMarketing"]),
            ("automation", ["#Automation", "#BusinessAutomation", "#NoCode"]),
            ("indonesia", ["#Indonesia", "#StartupIndonesia", "#TeknologiIndonesia"]),
            ("business", ["#Business", "#Entrepreneur", "#BusinessGrowth"]),
        ]

        suggested = set()
        text_lower = text.lower()
        for keyword, tags in keywords:
            if keyword in text_lower:
                suggested.update(tags)

        # Add platform-specific
        if platform == Platform.TWITTER:
            suggested.update(["#TwitterIndonesia", "#XIndonesia"])
        elif platform == Platform.TELEGRAM:
            suggested.update(["#TelegramIndonesia"])
        elif platform == Platform.DISCORD:
            suggested.update(["#DiscordIndonesia"])

        return list(suggested)[:max_tags]

    # =========================================================================
    # Content Calendar
    # =========================================================================

    def set_schedule(self, date: str, template_name: str) -> None:
        """Set template for a specific date (YYYY-MM-DD)."""
        self._calendar[date] = template_name

    def get_schedule(self, date: str) -> Optional[str]:
        """Get scheduled template for date."""
        return self._calendar.get(date)

    def get_todays_template(self) -> Optional[str]:
        """Get today's scheduled template."""
        today = datetime.now().strftime("%Y-%m-%d")
        return self._calendar.get(today)

    def get_week_schedule(self, start_date: Optional[str] = None) -> dict[str, Optional[str]]:
        """Get schedule for a week."""
        from datetime import timedelta
        if not start_date:
            start = datetime.now()
        else:
            start = datetime.strptime(start_date, "%Y-%m-%d")

        schedule = {}
        for i in range(7):
            date = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            schedule[date] = self._calendar.get(date)
        return schedule

    # =========================================================================
    # Default Schedule (backwards compatible)
    # =========================================================================

    DEFAULT_SCHEDULE = {
        "monday": "intro",
        "tuesday": "tips",
        "wednesday": "feature_highlight",
        "thursday": "engagement",
        "friday": "testimonial",
        "saturday": "tips",
        "sunday": "weekly_digest",
    }

    def get_todays_post(self) -> PostContent:
        """Get today's post based on default schedule."""
        day = datetime.now().strftime("%A").lower()
        template_name = self.DEFAULT_SCHEDULE.get(day, "random")
        return self.generate_post(template_name)

    # =========================================================================
    # Export/Import
    # =========================================================================

    def export_templates(self, directory: Path) -> int:
        """Export all templates to JSON files."""
        directory.mkdir(parents=True, exist_ok=True)
        count = 0
        for name, template in self.templates.items():
            file = directory / f"{name}.json"
            with open(file, "w") as f:
                json.dump({
                    "name": template.name,
                    "description": template.description,
                    "category": template.category,
                    "platforms": [p.value for p in template.platforms],
                    "template_text": template.template_text,
                    "template_file": template.template_file,
                    "variables": template.variables,
                    "required_vars": template.required_vars,
                    "default_vars": template.default_vars,
                    "tags": template.tags,
                    "created_at": template.created_at.isoformat(),
                    "updated_at": template.updated_at.isoformat(),
                }, f, indent=2)
            count += 1
        return count

    def import_templates(self, directory: Path) -> int:
        """Import templates from JSON files."""
        return self.load_templates_from_dir(directory)


# =========================================================================
# Convenience Functions (backwards compatible)
# =========================================================================

def generate_post(post_type: str = "random", **kwargs) -> str:
    """Generate a post (backwards compatible - returns text only)."""
    engine = ContentEngine()
    content = engine.generate_post(post_type, **kwargs)
    return content.text


def get_todays_post() -> str:
    """Get today's post (backwards compatible)."""
    engine = ContentEngine()
    return engine.get_todays_post().text


# =========================================================================
# Content Variant Selector (for A/B testing)
# =========================================================================

class VariantSelector:
    """Select content variants for A/B testing."""

    def __init__(self):
        self._assignments: dict[str, str] = {}  # user_id -> variant_id

    def assign(self, user_id: str, variants: list[ContentVariant]) -> ContentVariant:
        """Assign a variant to a user (consistent assignment)."""
        if user_id in self._assignments:
            variant_id = self._assignments[user_id]
            for v in variants:
                if v.id == variant_id:
                    return v

        # Weighted random assignment
        total = sum(v.weight for v in variants)
        r = random.uniform(0, total)
        for v in variants:
            r -= v.weight
            if r <= 0:
                self._assignments[user_id] = v.id
                return v

        return variants[0]

    def get_assignment(self, user_id: str) -> Optional[str]:
        """Get user's assigned variant."""
        return self._assignments.get(user_id)

    def reset(self, user_id: Optional[str] = None) -> None:
        """Reset assignment(s)."""
        if user_id:
            self._assignments.pop(user_id, None)
        else:
            self._assignments.clear()