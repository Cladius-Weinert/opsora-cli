"""
Scheduler - APScheduler-based job scheduler with WITA timezone support.

Features:
- Persistent job store (SQLite/Redis)
- Timezone: Asia/Makassar (WITA/Bali)
- Recurring schedules: cron, interval, date
- Media attachment scheduling
- Job persistence across restarts
- Webhook callbacks for job events
- CLI integration
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any, Callable, Optional
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.events import (
    EVENT_JOB_EXECUTED,
    EVENT_JOB_ERROR,
    EVENT_JOB_MISSED,
    EVENT_JOB_ADDED,
    EVENT_JOB_REMOVED,
    JobExecutionEvent,
)
from pydantic import BaseModel, Field

from .settings import get_settings, SchedulerSettings
from .posting import UnifiedPoster, PostContent, PostTarget, Platform, MediaAttachment, create_post_content

log = logging.getLogger("marketing.scheduler")


class JobType(str, Enum):
    """Types of scheduled jobs."""
    POST = "post"           # Single post
    BROADCAST = "broadcast"  # Broadcast to multiple targets
    CAMPAIGN = "campaign"    # Multi-post campaign


class JobStatus(str, Enum):
    """Job status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    REMOVED = "removed"


@dataclass(slots=True)
class ScheduledJob:
    """Scheduled job configuration."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    type: JobType = JobType.POST
    status: JobStatus = JobStatus.PENDING

    # Schedule
    trigger_type: Literal["cron", "interval", "date"] = "cron"
    cron_expression: Optional[str] = None  # e.g., "0 9 * * 1-5" for weekdays 9am
    interval_seconds: Optional[int] = None  # e.g., 3600 for hourly
    run_date: Optional[datetime] = None  # For one-time jobs
    timezone: str = "Asia/Makassar"

    # Content
    content: Optional[PostContent] = None
    content_template: Optional[str] = None  # Template name from content_engine
    template_vars: dict = field(default_factory=dict)

    # Targets
    targets: list[PostTarget] = field(default_factory=list)
    use_configured_targets: bool = False  # Use settings.target_channels/groups

    # Metadata
    campaign_id: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    max_runs: Optional[int] = None
    run_count: int = 0

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    next_run: Optional[datetime] = None
    last_run: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Serialize to dict for storage."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "status": self.status.value,
            "trigger_type": self.trigger_type,
            "cron_expression": self.cron_expression,
            "interval_seconds": self.interval_seconds,
            "run_date": self.run_date.isoformat() if self.run_date else None,
            "timezone": self.timezone,
            "content": self.content.__dict__ if self.content else None,
            "content_template": self.content_template,
            "template_vars": self.template_vars,
            "targets": [
                {"platform": t.platform.value, "identifier": str(t.identifier), "name": t.name, "metadata": t.metadata}
                for t in self.targets
            ],
            "use_configured_targets": self.use_configured_targets,
            "campaign_id": self.campaign_id,
            "tags": self.tags,
            "max_runs": self.max_runs,
            "run_count": self.run_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "last_run": self.last_run.isoformat() if self.last_run else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScheduledJob:
        """Deserialize from dict."""
        job = cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", ""),
            type=JobType(data.get("type", "post")),
            status=JobStatus(data.get("status", "pending")),
            trigger_type=data.get("trigger_type", "cron"),
            cron_expression=data.get("cron_expression"),
            interval_seconds=data.get("interval_seconds"),
            run_date=datetime.fromisoformat(data["run_date"]) if data.get("run_date") else None,
            timezone=data.get("timezone", "Asia/Makassar"),
            content_template=data.get("content_template"),
            template_vars=data.get("template_vars", {}),
            use_configured_targets=data.get("use_configured_targets", False),
            campaign_id=data.get("campaign_id"),
            tags=data.get("tags", []),
            max_runs=data.get("max_runs"),
            run_count=data.get("run_count", 0),
        )

        # Parse content
        if data.get("content"):
            c = data["content"]
            job.content = PostContent(**c)

        # Parse targets
        for t in data.get("targets", []):
            job.targets.append(PostTarget(
                platform=Platform(t["platform"]),
                identifier=t["identifier"],
                name=t.get("name"),
                metadata=t.get("metadata", {}),
            ))

        # Parse timestamps
        if data.get("next_run"):
            job.next_run = datetime.fromisoformat(data["next_run"])
        if data.get("last_run"):
            job.last_run = datetime.fromisoformat(data["last_run"])
        if data.get("created_at"):
            job.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("updated_at"):
            job.updated_at = datetime.fromisoformat(data["updated_at"])

        return job


class SchedulerCallbacks:
    """Callback handlers for scheduler events."""

    def __init__(self):
        self.on_job_added: list[Callable[[ScheduledJob], None]] = []
        self.on_job_removed: list[Callable[[str], None]] = []
        self.on_job_executed: list[Callable[[ScheduledJob, list], None]] = []  # job, results
        self.on_job_error: list[Callable[[ScheduledJob, Exception], None]] = []
        self.on_job_missed: list[Callable[[ScheduledJob], None]] = []

    def register(self, event: str, callback: Callable) -> None:
        """Register a callback."""
        if hasattr(self, f"on_{event}"):
            getattr(self, f"on_{event}").append(callback)

    def _emit(self, event: str, *args) -> None:
        """Emit event to callbacks."""
        for cb in getattr(self, f"on_{event}", []):
            try:
                cb(*args)
            except Exception as e:
                log.error("Callback error for %s: %s", event, e)


class MarketingScheduler:
    """
    Marketing job scheduler with APScheduler backend.

    Features:
    - WITA timezone (Asia/Makassar) by default
    - Persistent job store (SQLite/Redis/Memory)
    - Cron, interval, and date triggers
    - Content templates from content_engine
    - Multi-platform posting via UnifiedPoster
    - Job persistence across restarts
    - Event callbacks for monitoring
    """

    def __init__(
        self,
        settings: Optional[SchedulerSettings] = None,
        poster: Optional[UnifiedPoster] = None,
        job_store_url: Optional[str] = None,
    ):
        self.settings = settings or get_settings().scheduler
        self.poster = poster
        self._callbacks = SchedulerCallbacks()

        # Determine job store
        job_store_url = job_store_url or self.settings.job_store_url
        self._job_store_url = job_store_url

        # Create scheduler
        self._scheduler = AsyncIOScheduler(
            timezone=self.settings.timezone,
            jobstores=self._create_jobstores(),
            job_defaults={
                "coalesce": self.settings.coalesce,
                "max_instances": self.settings.max_instances,
                "misfire_grace_time": self.settings.misfire_grace_time,
            },
        )

        # Register event listeners
        self._scheduler.add_listener(self._on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED | EVENT_JOB_ADDED | EVENT_JOB_REMOVED)

        self._running = False

    def _create_jobstores(self) -> dict:
        """Create job stores based on configuration."""
        stores = {"default": MemoryJobStore()}

        if self._job_store_url:
            if self._job_store_url.startswith("sqlite"):
                stores["default"] = SQLAlchemyJobStore(url=self._job_store_url)
            elif self._job_store_url.startswith("redis"):
                stores["default"] = RedisJobStore.from_url(self._job_store_url)
            elif self._job_store_url.startswith("postgresql") or self._job_store_url.startswith("mysql"):
                stores["default"] = SQLAlchemyJobStore(url=self._job_store_url)

        return stores

    def _on_job_event(self, event: JobExecutionEvent) -> None:
        """Handle APScheduler events."""
        job_id = event.job_id
        job = self.get_job(job_id)

        if event.code == EVENT_JOB_ADDED:
            self._callbacks._emit("job_added", job)
        elif event.code == EVENT_JOB_REMOVED:
            self._callbacks._emit("job_removed", job_id)
        elif event.code == EVENT_JOB_EXECUTED:
            # Get results from job's return value
            results = getattr(event, "retval", [])
            self._callbacks._emit("job_executed", job, results)
            if job:
                job.run_count += 1
                job.last_run = datetime.now()
                job.status = JobStatus.COMPLETED
                self._update_job(job)
        elif event.code == EVENT_JOB_ERROR:
            self._callbacks._emit("job_error", job, event.exception)
            if job:
                job.status = JobStatus.FAILED
                self._update_job(job)
        elif event.code == EVENT_JOB_MISSED:
            self._callbacks._emit("job_missed", job)
            if job:
                job.status = JobStatus.FAILED
                self._update_job(job)

    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            return

        # Connect poster if provided
        if self.poster and not hasattr(self.poster, "_connected"):
            await self.poster.connect()

        self._scheduler.start()
        self._running = True
        log.info("Scheduler started (timezone: %s)", self.settings.timezone)

    async def shutdown(self, wait: bool = True) -> None:
        """Shutdown the scheduler."""
        if not self._running:
            return

        self._scheduler.shutdown(wait=wait)
        self._running = False

        if self.poster:
            await self.poster.disconnect()

        log.info("Scheduler stopped")

    # =========================================================================
    # Job Management
    # =========================================================================

    def add_job(self, job: ScheduledJob) -> str:
        """Add a scheduled job."""
        trigger = self._create_trigger(job)

        aps_job = self._scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=job.id,
            name=job.name,
            args=[job],
            max_instances=job.max_runs or self.settings.max_instances,
            coalesce=self.settings.coalesce,
            misfire_grace_time=self.settings.misfire_grace_time,
        )

        job.next_run = aps_job.next_run_time
        job.status = JobStatus.PENDING
        self._update_job(job)

        self._callbacks._emit("job_added", job)
        log.info("Added job: %s (%s)", job.name, job.id)
        return job.id

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job."""
        try:
            self._scheduler.remove_job(job_id)
            job = self.get_job(job_id)
            if job:
                job.status = JobStatus.REMOVED
                self._update_job(job)
            self._callbacks._emit("job_removed", job_id)
            log.info("Removed job: %s", job_id)
            return True
        except Exception:
            return False

    def pause_job(self, job_id: str) -> bool:
        """Pause a job."""
        try:
            self._scheduler.pause_job(job_id)
            job = self.get_job(job_id)
            if job:
                job.status = JobStatus.PAUSED
                self._update_job(job)
            return True
        except Exception:
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        try:
            self._scheduler.resume_job(job_id)
            job = self.get_job(job_id)
            if job:
                job.status = JobStatus.PENDING
                job.next_run = self._scheduler.get_job(job_id).next_run_time
                self._update_job(job)
            return True
        except Exception:
            return False

    def run_job_now(self, job_id: str) -> bool:
        """Trigger a job to run immediately."""
        try:
            self._scheduler.modify_job(job_id, next_run_time=datetime.now())
            return True
        except Exception:
            return False

    def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        """Get job by ID."""
        aps_job = self._scheduler.get_job(job_id)
        if not aps_job:
            return None

        # Reconstruct from stored data
        return self._deserialize_job(aps_job)

    def list_jobs(self, status: Optional[JobStatus] = None) -> list[ScheduledJob]:
        """List all jobs."""
        jobs = []
        for aps_job in self._scheduler.get_jobs():
            job = self._deserialize_job(aps_job)
            if job and (status is None or job.status == status):
                jobs.append(job)
        return jobs

    def _deserialize_job(self, aps_job) -> Optional[ScheduledJob]:
        """Deserialize job from APScheduler job."""
        # Job data is stored in job.kwargs or we can use a separate store
        # For simplicity, we'll store minimal data in job kwargs
        job_data = getattr(aps_job, "kwargs", {}).get("job_data")
        if job_data:
            job = ScheduledJob.from_dict(job_data)
            job.next_run = aps_job.next_run_time
            return job

        # Fallback: create minimal job
        return ScheduledJob(
            id=aps_job.id,
            name=aps_job.name,
            next_run=aps_job.next_run_time,
        )

    def _update_job(self, job: ScheduledJob) -> None:
        """Update job in APScheduler."""
        aps_job = self._scheduler.get_job(job.id)
        if aps_job:
            aps_job.kwargs["job_data"] = job.to_dict()

    def _create_trigger(self, job: ScheduledJob):
        """Create APScheduler trigger from job config."""
        tz = job.timezone or self.settings.timezone

        if job.trigger_type == "cron":
            if not job.cron_expression:
                raise ValueError("Cron expression required for cron trigger")
            return CronTrigger.from_crontab(job.cron_expression, timezone=tz)

        elif job.trigger_type == "interval":
            if not job.interval_seconds:
                raise ValueError("Interval seconds required for interval trigger")
            return IntervalTrigger(seconds=job.interval_seconds, timezone=tz)

        elif job.trigger_type == "date":
            if not job.run_date:
                raise ValueError("Run date required for date trigger")
            return DateTrigger(run_date=job.run_date, timezone=tz)

        raise ValueError(f"Unknown trigger type: {job.trigger_type}")

    # =========================================================================
    # Job Execution
    # =========================================================================

    async def _execute_job(self, job: ScheduledJob) -> list:
        """Execute a scheduled job."""
        log.info("Executing job: %s (%s)", job.name, job.id)
        job.status = JobStatus.RUNNING
        job.last_run = datetime.now()
        self._update_job(job)

        try:
            # Resolve content
            content = await self._resolve_content(job)

            # Resolve targets
            targets = await self._resolve_targets(job)

            if not targets:
                log.warning("No targets for job: %s", job.id)
                return []

            # Execute based on type
            if job.type == JobType.POST:
                results = await self._execute_post(job, targets, content)
            elif job.type == JobType.BROADCAST:
                results = await self._execute_broadcast(job, targets, content)
            elif job.type == JobType.CAMPAIGN:
                results = await self._execute_campaign(job, targets, content)
            else:
                results = []

            # Check max runs
            if job.max_runs and job.run_count + 1 >= job.max_runs:
                self.remove_job(job.id)

            return results

        except Exception as e:
            log.error("Job execution failed: %s", e)
            raise

    async def _resolve_content(self, job: ScheduledJob) -> PostContent:
        """Resolve content from template or direct content."""
        if job.content:
            return job.content

        if job.content_template:
            # Import content engine
            from .content_engine import generate_post
            text = generate_post(job.content_template, **job.template_vars)
            return create_post_content(
                text,
                campaign_id=job.campaign_id,
                utm_source="scheduler",
            )

        # Default: today's post
        from .content_engine import get_todays_post
        text = get_todays_post()
        return create_post_content(text, campaign_id=job.campaign_id, utm_source="scheduler")

    async def _resolve_targets(self, job: ScheduledJob) -> list[PostTarget]:
        """Resolve targets from job config or configured targets."""
        if job.targets:
            return job.targets

        if job.use_configured_targets:
            targets = []
            tg_settings = get_settings().telegram
            dc_settings = get_settings().discord

            for ch_id in tg_settings.target_channels:
                targets.append(PostTarget(Platform.TELEGRAM, ch_id))
            for ch_id in dc_settings.target_channels:
                targets.append(PostTarget(Platform.DISCORD, ch_id))

            return targets

        # No targets configured
        return []

    async def _execute_post(
        self,
        job: ScheduledJob,
        targets: list[PostTarget],
        content: PostContent,
    ) -> list:
        """Execute a single post to first target."""
        if not self.poster:
            raise RuntimeError("No poster configured")

        # Post to first target only
        results = await self.poster.post(targets[:1], content)
        return results

    async def _execute_broadcast(
        self,
        job: ScheduledJob,
        targets: list[PostTarget],
        content: PostContent,
    ) -> list:
        """Execute broadcast to all targets."""
        if not self.poster:
            raise RuntimeError("No poster configured")

        results = await self.poster.post(targets, content)
        return results

    async def _execute_campaign(
        self,
        job: ScheduledJob,
        targets: list[PostTarget],
        content: PostContent,
    ) -> list:
        """Execute a multi-post campaign."""
        # For now, just broadcast
        return await self._execute_broadcast(job, targets, content)

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def schedule_daily_post(
        self,
        name: str,
        hour: int = 9,
        minute: int = 0,
        content_template: Optional[str] = None,
        template_vars: Optional[dict] = None,
        platforms: Optional[list[Platform]] = None,
        campaign_id: Optional[str] = None,
    ) -> str:
        """Schedule a daily post at specific time."""
        cron = f"{minute} {hour} * * *"
        return self._create_schedule_job(
            name=name,
            cron_expression=cron,
            content_template=content_template,
            template_vars=template_vars,
            platforms=platforms,
            campaign_id=campaign_id,
        )

    def schedule_weekly_post(
        self,
        name: str,
        day_of_week: str,  # mon, tue, wed, thu, fri, sat, sun
        hour: int = 9,
        minute: int = 0,
        content_template: Optional[str] = None,
        template_vars: Optional[dict] = None,
        platforms: Optional[list[Platform]] = None,
        campaign_id: Optional[str] = None,
    ) -> str:
        """Schedule a weekly post."""
        cron = f"{minute} {hour} * * {day_of_week[:3].lower()}"
        return self._create_schedule_job(
            name=name,
            cron_expression=cron,
            content_template=content_template,
            template_vars=template_vars,
            platforms=platforms,
            campaign_id=campaign_id,
        )

    def schedule_interval_post(
        self,
        name: str,
        interval_seconds: int,
        content_template: Optional[str] = None,
        template_vars: Optional[dict] = None,
        platforms: Optional[list[Platform]] = None,
        max_runs: Optional[int] = None,
        campaign_id: Optional[str] = None,
    ) -> str:
        """Schedule a recurring post at interval."""
        job = ScheduledJob(
            name=name,
            type=JobType.BROADCAST,
            trigger_type="interval",
            interval_seconds=interval_seconds,
            content_template=content_template,
            template_vars=template_vars or {},
            use_configured_targets=True,
            max_runs=max_runs,
            campaign_id=campaign_id,
        )

        if platforms:
            job.targets = [PostTarget(p, 0) for p in platforms]  # Will be resolved

        self.add_job(job)
        return job.id

    def schedule_one_time_post(
        self,
        name: str,
        run_date: datetime,
        content: Optional[PostContent] = None,
        content_template: Optional[str] = None,
        template_vars: Optional[dict] = None,
        platforms: Optional[list[Platform]] = None,
        campaign_id: Optional[str] = None,
    ) -> str:
        """Schedule a one-time post."""
        job = ScheduledJob(
            name=name,
            type=JobType.BROADCAST,
            trigger_type="date",
            run_date=run_date,
            content=content,
            content_template=content_template,
            template_vars=template_vars or {},
            use_configured_targets=True,
            campaign_id=campaign_id,
        )

        if platforms:
            job.targets = [PostTarget(p, 0) for p in platforms]

        self.add_job(job)
        return job.id

    def _create_schedule_job(
        self,
        name: str,
        cron_expression: str,
        content_template: Optional[str],
        template_vars: Optional[dict],
        platforms: Optional[list[Platform]],
        campaign_id: Optional[str],
    ) -> str:
        """Create a scheduled job from common params."""
        job = ScheduledJob(
            name=name,
            type=JobType.BROADCAST,
            trigger_type="cron",
            cron_expression=cron_expression,
            content_template=content_template,
            template_vars=template_vars or {},
            use_configured_targets=True,
            campaign_id=campaign_id,
        )

        if platforms:
            job.targets = [PostTarget(p, 0) for p in platforms]

        self.add_job(job)
        return job.id

    # =========================================================================
    # Callbacks
    # =========================================================================

    def on_job_added(self, callback: Callable[[ScheduledJob], None]) -> None:
        self._callbacks.on_job_added.append(callback)

    def on_job_removed(self, callback: Callable[[str], None]) -> None:
        self._callbacks.on_job_removed.append(callback)

    def on_job_executed(self, callback: Callable[[ScheduledJob, list], None]) -> None:
        self._callbacks.on_job_executed.append(callback)

    def on_job_error(self, callback: Callable[[ScheduledJob, Exception], None]) -> None:
        self._callbacks.on_job_error.append(callback)

    def on_job_missed(self, callback: Callable[[ScheduledJob], None]) -> None:
        self._callbacks.on_job_missed.append(callback)

    # =========================================================================
    # Status
    # =========================================================================

    @property
    def running(self) -> bool:
        return self._running

    @property
    def timezone(self) -> str:
        return self.settings.timezone

    def get_next_runs(self, limit: int = 10) -> list[dict]:
        """Get next scheduled runs."""
        jobs = self.list_jobs()
        runs = []
        for job in jobs:
            if job.next_run and job.status == JobStatus.PENDING:
                runs.append({
                    "job_id": job.id,
                    "name": job.name,
                    "next_run": job.next_run.isoformat(),
                    "timezone": job.timezone,
                })
        runs.sort(key=lambda x: x["next_run"])
        return runs[:limit]


# =========================================================================
# CLI Integration
# =========================================================================

async def cmd_schedule_add(args) -> None:
    """CLI: Add a scheduled job."""
    from .content_engine import generate_post

    scheduler = MarketingScheduler()
    await scheduler.start()

    try:
        if args.cron:
            job_id = scheduler.schedule_interval_post(
                name=args.name,
                interval_seconds=args.interval,
                content_template=args.type,
                max_runs=args.max_runs,
            )
        elif args.daily:
            job_id = scheduler.schedule_daily_post(
                name=args.name,
                hour=args.hour,
                minute=args.minute,
                content_template=args.type,
            )
        elif args.weekly:
            job_id = scheduler.schedule_weekly_post(
                name=args.name,
                day_of_week=args.day,
                hour=args.hour,
                minute=args.minute,
                content_template=args.type,
            )
        elif args.once:
            from datetime import timedelta
            run_date = datetime.now() + timedelta(seconds=args.in_seconds)
            job_id = scheduler.schedule_one_time_post(
                name=args.name,
                run_date=run_date,
                content_template=args.type,
            )
        else:
            print("Specify --cron, --daily, --weekly, or --once")
            return

        print(f"✅ Scheduled job: {job_id}")
        job = scheduler.get_job(job_id)
        if job and job.next_run:
            print(f"   Next run: {job.next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    finally:
        await scheduler.shutdown()


async def cmd_schedule_list(args) -> None:
    """CLI: List scheduled jobs."""
    scheduler = MarketingScheduler()
    await scheduler.start()

    try:
        jobs = scheduler.list_jobs()
        if not jobs:
            print("No scheduled jobs.")
            return

        print(f"{'ID':<10} {'Name':<20} {'Type':<12} {'Status':<12} {'Next Run':<25}")
        print("-" * 80)
        for job in jobs:
            next_run = job.next_run.strftime("%Y-%m-%d %H:%M %Z") if job.next_run else "N/A"
            print(f"{job.id:<10} {job.name:<20} {job.type.value:<12} {job.status.value:<12} {next_run:<25}")

    finally:
        await scheduler.shutdown()


async def cmd_schedule_remove(args) -> None:
    """CLI: Remove a scheduled job."""
    scheduler = MarketingScheduler()
    await scheduler.start()

    try:
        if scheduler.remove_job(args.job_id):
            print(f"✅ Removed job: {args.job_id}")
        else:
            print(f"❌ Job not found: {args.job_id}")
    finally:
        await scheduler.shutdown()


async def cmd_schedule_run(args) -> None:
    """CLI: Run a job immediately."""
    scheduler = MarketingScheduler()
    await scheduler.start()

    try:
        if scheduler.run_job_now(args.job_id):
            print(f"✅ Triggered job: {args.job_id}")
        else:
            print(f"❌ Job not found: {args.job_id}")
    finally:
        await scheduler.shutdown()


async def cmd_schedule_next(args) -> None:
    """CLI: Show next scheduled runs."""
    scheduler = MarketingScheduler()
    await scheduler.start()

    try:
        runs = scheduler.get_next_runs(args.limit)
        if not runs:
            print("No upcoming runs.")
            return

        print(f"{'Job ID':<10} {'Name':<20} {'Next Run':<25}")
        print("-" * 55)
        for r in runs:
            print(f"{r['job_id']:<10} {r['name']:<20} {r['next_run']:<25}")

    finally:
        await scheduler.shutdown()


# =========================================================================
# Factory
# =========================================================================

async def create_scheduler(
    poster: Optional[UnifiedPoster] = None,
    job_store_url: Optional[str] = None,
    auto_start: bool = True,
) -> MarketingScheduler:
    """Create and optionally start a scheduler."""
    scheduler = MarketingScheduler(poster=poster, job_store_url=job_store_url)
    if auto_start:
        await scheduler.start()
    return scheduler