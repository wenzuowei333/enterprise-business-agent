from __future__ import annotations

import logging
import os
import signal
import socket
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.database import SessionLocal, engine
from sqlalchemy import text


logger = logging.getLogger(__name__)
_FULL_SCAN_LOCK_KEY = 742_028_230_001
_DIGEST_LOCK_KEY = 742_028_230_002
_local_scheduler_locks = {
    _FULL_SCAN_LOCK_KEY: threading.Lock(),
    _DIGEST_LOCK_KEY: threading.Lock(),
}


def scheduler_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def persist_scheduler_heartbeat() -> None:
    from app.services.exception_task_service import record_service_heartbeat

    record_service_heartbeat(
        service_type="scheduler",
        instance_id=scheduler_identity(),
        metadata={
            "schedule_enabled": settings.exception_schedule_enabled,
            "timezone": settings.exception_schedule_timezone,
        },
    )


@contextmanager
def scheduler_advisory_lock(lock_key: int) -> Iterator[bool]:
    """Use a dedicated PostgreSQL connection so the session lock is always released."""
    if engine.dialect.name != "postgresql":
        lock = _local_scheduler_locks.setdefault(lock_key, threading.Lock())
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()
        return
    with engine.connect() as connection:
        acquired = bool(
            connection.scalar(text("select pg_try_advisory_lock(:lock_key)"), {"lock_key": lock_key})
        )
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(text("select pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key})


def run_full_scan_schedule() -> None:
    if not settings.exception_center_enabled or not settings.exception_schedule_enabled:
        return
    from app.services.exception_task_service import enqueue_background_job, load_exception_runtime_policy

    with scheduler_advisory_lock(_FULL_SCAN_LOCK_KEY) as acquired:
        if not acquired:
            logger.info("Scheduled exception scan skipped because another scheduler owns the lock")
            return
        with SessionLocal() as db:
            policy = load_exception_runtime_policy(db)
            if not policy.is_enabled or not policy.full_scan_enabled:
                return
            local_date = datetime.now(ZoneInfo(settings.exception_schedule_timezone)).date().isoformat()
            job, reused = enqueue_background_job(
                db,
                job_type="full_scan",
                dedupe_key=f"scheduled-full-scan:{local_date}",
            )
            db.commit()
            logger.info("Scheduled exception scan queued: job=%s reused=%s", job.job_no, reused)


def run_digest_schedule() -> None:
    if not settings.exception_center_enabled or not settings.exception_schedule_enabled:
        return
    from app.services.exception_task_service import enqueue_background_job, load_exception_runtime_policy

    with scheduler_advisory_lock(_DIGEST_LOCK_KEY) as acquired:
        if not acquired:
            logger.info("Scheduled exception digest skipped because another scheduler owns the lock")
            return
        with SessionLocal() as db:
            policy = load_exception_runtime_policy(db)
            if not policy.is_enabled or not policy.digest_enabled:
                return
            local_date = datetime.now(ZoneInfo(settings.exception_schedule_timezone)).date().isoformat()
            job, reused = enqueue_background_job(
                db,
                job_type="digest",
                dedupe_key=f"scheduled-digest:{local_date}",
            )
            db.commit()
            logger.info("Scheduled exception digest queued: job=%s reused=%s", job.job_no, reused)


def refresh_scheduler_policy(scheduler: BlockingScheduler) -> None:
    from app.services.exception_task_service import load_exception_runtime_policy

    try:
        with SessionLocal() as db:
            policy = load_exception_runtime_policy(db)
        scheduler.reschedule_job(
            "exception-full-scan",
            trigger=CronTrigger.from_crontab(policy.full_scan_cron, timezone=settings.exception_schedule_timezone),
        )
        scheduler.reschedule_job(
            "exception-digest",
            trigger=CronTrigger.from_crontab(policy.digest_cron, timezone=settings.exception_schedule_timezone),
        )
        globally_enabled = policy.is_enabled and settings.exception_center_enabled and settings.exception_schedule_enabled
        if globally_enabled and policy.full_scan_enabled:
            scheduler.resume_job("exception-full-scan")
        else:
            scheduler.pause_job("exception-full-scan")
        if globally_enabled and policy.digest_enabled:
            scheduler.resume_job("exception-digest")
        else:
            scheduler.pause_job("exception-digest")
    except Exception as exc:
        logger.error(
            "Failed to reload exception scheduler policy; retaining previous schedule: %s",
            exc.__class__.__name__,
        )


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(
        timezone=settings.exception_schedule_timezone,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )
    scheduler.add_job(
        run_full_scan_schedule,
        CronTrigger(hour=2, minute=30, timezone=settings.exception_schedule_timezone),
        id="exception-full-scan",
        replace_existing=True,
    )
    scheduler.add_job(
        run_digest_schedule,
        CronTrigger(hour=8, minute=30, timezone=settings.exception_schedule_timezone),
        id="exception-digest",
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_scheduler_policy,
        "interval",
        minutes=1,
        args=[scheduler],
        id="exception-policy-refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        persist_scheduler_heartbeat,
        "interval",
        seconds=max(5, settings.exception_runtime_heartbeat_seconds),
        id="exception-runtime-heartbeat",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return scheduler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    scheduler = build_scheduler()
    refresh_scheduler_policy(scheduler)
    persist_scheduler_heartbeat()

    def shutdown(signum, frame) -> None:  # noqa: ANN001, ARG001
        logger.info("Exception scheduler received shutdown signal")
        if scheduler.running:
            scheduler.shutdown(wait=True)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    logger.info("Exception scheduler started, timezone=%s", settings.exception_schedule_timezone)
    scheduler.start()


if __name__ == "__main__":
    main()
