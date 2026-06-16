"""APScheduler wrapper that manages one cron job per SyncRule."""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from backend.database import SessionLocal
from backend.models import SyncRule
from backend.sync.engine import run_sync

logger = logging.getLogger(__name__)


class SyncScheduler:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        self._scheduler.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    async def load_rules(self) -> None:
        """Load all enabled rules from DB and schedule them. Called at startup."""
        async with SessionLocal() as db:
            result = await db.execute(select(SyncRule).where(SyncRule.enabled.is_(True)))
            rules = list(result.scalars())

        for rule in rules:
            self.add_rule(rule)
        logger.info("Scheduled %d rule(s)", len(rules))

    def add_rule(self, rule: SyncRule) -> None:
        """Add or replace the cron job for a rule."""
        if not rule.enabled:
            self.remove_rule(rule.id)
            return
        try:
            trigger = CronTrigger.from_crontab(rule.schedule_cron, timezone="UTC")
        except ValueError as exc:
            logger.error("Invalid cron expression for rule %d (%r): %s", rule.id, rule.schedule_cron, exc)
            return

        self._scheduler.add_job(
            _run_sync_task,
            trigger=trigger,
            id=_job_id(rule.id),
            args=[rule.id],
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )
        logger.info("Scheduled rule %d: %s", rule.id, rule.schedule_cron)

    def remove_rule(self, rule_id: int) -> None:
        jid = _job_id(rule_id)
        if self._scheduler.get_job(jid):
            self._scheduler.remove_job(jid)
            logger.info("Removed schedule for rule %d", rule_id)

    def run_now(self, rule_id: int) -> None:
        """Trigger an immediate one-off run outside the normal schedule."""
        self._scheduler.add_job(
            _run_sync_task,
            args=[rule_id],
            id=f"manual_{rule_id}",
            replace_existing=True,
        )

    def next_run_time(self, rule_id: int) -> "datetime | None":
        job = self._scheduler.get_job(_job_id(rule_id))
        return job.next_run_time if job else None


def _job_id(rule_id: int) -> str:
    return f"rule_{rule_id}"


async def _run_sync_task(rule_id: int) -> None:
    try:
        await run_sync(rule_id)
    except Exception:
        logger.exception("Sync job %d failed", rule_id)
