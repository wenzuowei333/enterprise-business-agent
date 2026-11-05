from __future__ import annotations

import math
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterator
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case as sql_case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.exception_center import (
    ExceptionCase,
    ExceptionBackgroundJob,
    ExceptionDiagnosis,
    ExceptionDiagnosisJob,
    ExceptionEvent,
    ExceptionEvidence,
    ExceptionNotification,
    ExceptionPolicy,
    ExceptionServiceHeartbeat,
)
from app.models.identity import AuditLog
from app.services.hermes_ai_service import (
    HermesCancelledError,
    HermesResponseError,
    HermesUnavailableError,
    call_hermes_exception_diagnosis,
    hermes_circuit_status,
    hermes_configured,
    hermes_provider_host,
)
from app.services.exception_quota import (
    quota_batch_capacity,
    quota_exhausted,
    quota_is_unlimited,
    quota_remaining,
)
from app.services.exception_center_service import (
    AI_DIAGNOSIS_DOMAINS,
    DOMAIN_ROOT_CAUSE_CODES,
    EXCEPTION_SYNC_ADVISORY_LOCK_KEY,
    TARGET_RESOURCE_DOMAINS,
    acquire_exception_case_mutation_lock,
)


class JobLeaseLostError(RuntimeError):
    """Raised when a worker can no longer prove ownership of a leased job."""


class DiagnosisJobObsoleteError(RuntimeError):
    """Raised when a case became terminal or its evidence was superseded."""


_TERMINAL_CASE_STATUSES = {"resolved", "ignored"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ExceptionRuntimePolicy:
    is_enabled: bool
    manual_ai_enabled: bool
    scheduled_ai_enabled: bool
    full_scan_enabled: bool
    digest_enabled: bool
    full_scan_cron: str
    digest_cron: str
    manual_ai_daily_limit: int
    scheduled_ai_daily_limit: int
    scheduled_ai_batch_limit: int
    ai_concurrency: int
    stale_diagnosis_hours: int


def load_exception_runtime_policy(db: Session) -> ExceptionRuntimePolicy:
    row = db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
    if row is None:
        return ExceptionRuntimePolicy(
            is_enabled=True,
            manual_ai_enabled=False,
            scheduled_ai_enabled=False,
            full_scan_enabled=False,
            digest_enabled=False,
            full_scan_cron="30 2 * * *",
            digest_cron="30 8 * * *",
            manual_ai_daily_limit=max(0, settings.exception_manual_ai_daily_limit),
            scheduled_ai_daily_limit=max(0, settings.exception_scheduled_ai_daily_limit),
            scheduled_ai_batch_limit=max(1, settings.exception_scheduled_ai_batch_size),
            ai_concurrency=1,
            stale_diagnosis_hours=24,
        )
    return ExceptionRuntimePolicy(
        is_enabled=bool(row.is_enabled),
        manual_ai_enabled=bool(row.manual_ai_enabled),
        scheduled_ai_enabled=bool(row.scheduled_ai_enabled),
        full_scan_enabled=bool(row.full_scan_enabled),
        digest_enabled=bool(row.digest_enabled),
        full_scan_cron=row.full_scan_cron,
        digest_cron=row.digest_cron,
        manual_ai_daily_limit=max(0, row.manual_ai_daily_limit),
        scheduled_ai_daily_limit=max(0, row.scheduled_ai_daily_limit),
        scheduled_ai_batch_limit=max(1, row.scheduled_ai_batch_limit),
        ai_concurrency=max(1, row.ai_concurrency),
        stale_diagnosis_hours=max(1, row.stale_diagnosis_hours),
    )


def current_exception_runtime_policy() -> ExceptionRuntimePolicy:
    with SessionLocal() as db:
        return load_exception_runtime_policy(db)


def exception_ops_summary(db: Session) -> dict:
    now = utcnow()
    policy = load_exception_runtime_policy(db)
    diagnosis_counts = {
        str(status): int(count)
        for status, count in db.execute(
            select(ExceptionDiagnosisJob.status, func.count(ExceptionDiagnosisJob.id)).group_by(
                ExceptionDiagnosisJob.status
            )
        ).all()
    }
    trigger_counts: dict[str, dict[str, int]] = {}
    for trigger_type, status, count in db.execute(
        select(
            ExceptionDiagnosisJob.trigger_type,
            ExceptionDiagnosisJob.status,
            func.count(ExceptionDiagnosisJob.id),
        ).group_by(ExceptionDiagnosisJob.trigger_type, ExceptionDiagnosisJob.status)
    ).all():
        trigger_counts.setdefault(str(trigger_type), {})[str(status)] = int(count)
    background_counts = {
        str(status): int(count)
        for status, count in db.execute(
            select(ExceptionBackgroundJob.status, func.count(ExceptionBackgroundJob.id)).group_by(
                ExceptionBackgroundJob.status
            )
        ).all()
    }
    oldest_manual = db.scalar(
        select(func.min(ExceptionDiagnosisJob.created_at)).where(
            ExceptionDiagnosisJob.status == "queued",
            ExceptionDiagnosisJob.trigger_type == "manual",
        )
    )
    oldest_scheduled = db.scalar(
        select(func.min(ExceptionDiagnosisJob.created_at)).where(
            ExceptionDiagnosisJob.status == "queued",
            ExceptionDiagnosisJob.trigger_type != "manual",
        )
    )
    oldest_background = db.scalar(
        select(func.min(ExceptionBackgroundJob.created_at)).where(ExceptionBackgroundJob.status == "queued")
    )
    heartbeat_cutoff = now - timedelta(seconds=max(10, settings.exception_runtime_heartbeat_seconds * 2))
    heartbeats = list(
        db.scalars(
            select(ExceptionServiceHeartbeat)
            .where(ExceptionServiceHeartbeat.last_heartbeat_at >= now - timedelta(days=30))
            .order_by(ExceptionServiceHeartbeat.last_heartbeat_at.desc())
            .limit(50)
        ).all()
    )
    ai_heartbeats = [row for row in heartbeats if row.service_type == "ai_worker"]
    latest_ai_heartbeat = max(ai_heartbeats, key=lambda row: row.last_heartbeat_at) if ai_heartbeats else None
    worker_circuit = None
    if latest_ai_heartbeat is not None:
        raw_circuit = (latest_ai_heartbeat.metadata_json or {}).get("circuit")
        if (
            isinstance(raw_circuit, dict)
            and isinstance(raw_circuit.get("open"), bool)
            and isinstance(raw_circuit.get("consecutive_failures"), int)
            and not isinstance(raw_circuit.get("consecutive_failures"), bool)
            and isinstance(raw_circuit.get("retry_after_seconds"), int)
            and not isinstance(raw_circuit.get("retry_after_seconds"), bool)
        ):
            cutoff = heartbeat_cutoff if latest_ai_heartbeat.last_heartbeat_at.tzinfo else heartbeat_cutoff.replace(tzinfo=None)
            worker_circuit = {
                "open": raw_circuit["open"],
                "consecutive_failures": max(0, raw_circuit["consecutive_failures"]),
                "retry_after_seconds": max(0, raw_circuit["retry_after_seconds"]),
                "stale": latest_ai_heartbeat.last_heartbeat_at < cutoff,
                "source": "ai_worker",
            }
    since_24h = now - timedelta(hours=24)
    completed_24h = int(
        db.scalar(
            select(func.count(ExceptionDiagnosisJob.id)).where(
                ExceptionDiagnosisJob.status == "completed",
                ExceptionDiagnosisJob.completed_at >= since_24h,
            )
        )
        or 0
    )
    failed_24h = int(
        db.scalar(
            select(func.count(ExceptionDiagnosisJob.id)).where(
                ExceptionDiagnosisJob.status == "failed",
                ExceptionDiagnosisJob.completed_at >= since_24h,
            )
        )
        or 0
    )
    last_scan = db.scalar(
        select(ExceptionBackgroundJob)
        .where(ExceptionBackgroundJob.job_type == "full_scan", ExceptionBackgroundJob.status == "completed")
        .order_by(ExceptionBackgroundJob.completed_at.desc(), ExceptionBackgroundJob.id.desc())
        .limit(1)
    )
    last_digest = db.scalar(
        select(ExceptionBackgroundJob)
        .where(ExceptionBackgroundJob.job_type == "digest", ExceptionBackgroundJob.status == "completed")
        .order_by(ExceptionBackgroundJob.completed_at.desc(), ExceptionBackgroundJob.id.desc())
        .limit(1)
    )
    scan_result = ((last_scan.payload_json or {}).get("result") or {}) if last_scan else {}
    scan_duration_ms = None
    if last_scan and last_scan.started_at and last_scan.completed_at:
        scan_duration_ms = max(0, int((last_scan.completed_at - last_scan.started_at).total_seconds() * 1000))
    manual_used = _today_ai_call_count(db, trigger_type="manual")
    scheduled_used = _today_ai_call_count(db, trigger_type="scheduled")
    return {
        "generated_at": now,
        "global_ai_enabled": bool(settings.exception_ai_enabled),
        "provider_configured": hermes_configured(),
        "provider_host": hermes_provider_host(),
        "model": settings.hermes_model,
        # The web process has an unrelated process-local circuit. Returning it
        # would misreport the worker that actually calls the provider.
        "circuit": worker_circuit,
        "diagnosis_jobs_by_status": diagnosis_counts,
        "diagnosis_jobs_by_trigger": trigger_counts,
        "background_jobs_by_status": background_counts,
        "manual_queue_depth": trigger_counts.get("manual", {}).get("queued", 0),
        "scheduled_queue_depth": sum(
            values.get("queued", 0) for trigger, values in trigger_counts.items() if trigger != "manual"
        ),
        "background_queue_depth": background_counts.get("queued", 0),
        "oldest_manual_queued_at": oldest_manual,
        "oldest_scheduled_queued_at": oldest_scheduled,
        "oldest_background_queued_at": oldest_background,
        "heartbeats": [
            {
                "service_type": row.service_type,
                "instance_id": row.instance_id,
                "started_at": row.started_at,
                "last_heartbeat_at": row.last_heartbeat_at,
                "is_stale": row.last_heartbeat_at
                < (heartbeat_cutoff if row.last_heartbeat_at.tzinfo else heartbeat_cutoff.replace(tzinfo=None)),
                "metadata": row.metadata_json or {},
            }
            for row in heartbeats
        ],
        "policy": {
            "is_enabled": policy.is_enabled,
            "manual_ai_enabled": policy.manual_ai_enabled,
            "scheduled_ai_enabled": policy.scheduled_ai_enabled,
            "full_scan_enabled": policy.full_scan_enabled,
            "digest_enabled": policy.digest_enabled,
            "ai_concurrency": policy.ai_concurrency,
            "scheduled_ai_batch_limit": policy.scheduled_ai_batch_limit,
        },
        "manual_budget": {
            "limit": policy.manual_ai_daily_limit,
            "used": manual_used,
            "remaining": quota_remaining(policy.manual_ai_daily_limit, manual_used),
            "unlimited": quota_is_unlimited(policy.manual_ai_daily_limit),
        },
        "scheduled_budget": {
            "limit": policy.scheduled_ai_daily_limit,
            "used": scheduled_used,
            "remaining": quota_remaining(policy.scheduled_ai_daily_limit, scheduled_used),
            "unlimited": quota_is_unlimited(policy.scheduled_ai_daily_limit),
        },
        "diagnosis_completed_24h": completed_24h,
        "diagnosis_failed_24h": failed_24h,
        "last_full_scan_at": last_scan.completed_at if last_scan else None,
        "last_digest_at": last_digest.completed_at if last_digest else None,
        "last_scan_duration_ms": scan_duration_ms,
        "last_scan_created": int(scan_result.get("created") or 0),
        "last_scan_new": int(scan_result.get("new") or 0),
        "last_scan_reopened": int(scan_result.get("reopened") or 0),
        "last_scan_evidence_updated": int(scan_result.get("evidence_updated") or 0),
        "last_scan_resolved": int(scan_result.get("resolved") or 0),
        "last_scan_scanned": int(scan_result.get("scanned") or 0),
    }


def record_service_heartbeat(
    *,
    service_type: str,
    instance_id: str,
    metadata: dict | None = None,
) -> None:
    """Persist liveness without coupling callers to their job transaction."""
    now = utcnow()
    persisted_metadata = dict(metadata or {})
    if service_type != "ai_worker":
        persisted_metadata.pop("circuit", None)
    else:
        raw_circuit = persisted_metadata.get("circuit")
        if (
            isinstance(raw_circuit, dict)
            and isinstance(raw_circuit.get("open"), bool)
            and isinstance(raw_circuit.get("consecutive_failures"), int)
            and not isinstance(raw_circuit.get("consecutive_failures"), bool)
            and isinstance(raw_circuit.get("retry_after_seconds"), int)
            and not isinstance(raw_circuit.get("retry_after_seconds"), bool)
        ):
            persisted_metadata["circuit"] = {
                "open": raw_circuit["open"],
                "consecutive_failures": max(0, raw_circuit["consecutive_failures"]),
                "retry_after_seconds": max(0, raw_circuit["retry_after_seconds"]),
            }
        else:
            persisted_metadata.pop("circuit", None)
    with SessionLocal() as db:
        db.execute(
            delete(ExceptionServiceHeartbeat).where(
                ExceptionServiceHeartbeat.last_heartbeat_at < now - timedelta(days=30)
            )
        )
        row = db.scalar(
            select(ExceptionServiceHeartbeat).where(
                ExceptionServiceHeartbeat.service_type == service_type,
                ExceptionServiceHeartbeat.instance_id == instance_id,
            )
        )
        if row is None:
            row = ExceptionServiceHeartbeat(
                service_type=service_type,
                instance_id=instance_id,
                started_at=now,
            )
            db.add(row)
        row.last_heartbeat_at = now
        row.metadata_json = persisted_metadata
        db.commit()


def latest_persisted_ai_circuit_state() -> dict[str, int | bool] | None:
    """Return the latest worker circuit with wall-clock cooldown already elapsed."""
    now = utcnow()
    with SessionLocal() as db:
        row = db.scalar(
            select(ExceptionServiceHeartbeat)
            .where(ExceptionServiceHeartbeat.service_type == "ai_worker")
            .order_by(
                ExceptionServiceHeartbeat.last_heartbeat_at.desc(),
                ExceptionServiceHeartbeat.id.desc(),
            )
            .limit(1)
        )
        if row is None:
            return None
        raw_circuit = (row.metadata_json or {}).get("circuit")
        if (
            not isinstance(raw_circuit, dict)
            or not isinstance(raw_circuit.get("open"), bool)
            or not isinstance(raw_circuit.get("consecutive_failures"), int)
            or isinstance(raw_circuit.get("consecutive_failures"), bool)
            or not isinstance(raw_circuit.get("retry_after_seconds"), int)
            or isinstance(raw_circuit.get("retry_after_seconds"), bool)
        ):
            return None
        heartbeat_at = row.last_heartbeat_at
        comparable_now = now if heartbeat_at.tzinfo else now.replace(tzinfo=None)
        elapsed_seconds = max(0.0, (comparable_now - heartbeat_at).total_seconds())
        failures = max(0, raw_circuit["consecutive_failures"])
        stored_retry_after = max(0, raw_circuit["retry_after_seconds"])
        retry_after = (
            max(0, math.ceil(stored_retry_after - elapsed_seconds))
            if raw_circuit["open"]
            else 0
        )
        return {
            "open": bool(raw_circuit["open"] and failures > 0),
            "consecutive_failures": failures,
            "retry_after_seconds": retry_after,
        }


def claim_diagnosis_job(
    db: Session,
    *,
    worker_id: str,
    trigger_type: str | None = None,
) -> ExceptionDiagnosisJob | None:
    """Atomically lease the next available job without blocking other workers."""
    now = utcnow()
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(742028230004)))
    policy = load_exception_runtime_policy(db)
    allowed_triggers: list[str] = []
    if settings.exception_ai_enabled and policy.is_enabled:
        if policy.manual_ai_enabled:
            allowed_triggers.append("manual")
        if policy.scheduled_ai_enabled:
            allowed_triggers.append("scheduled")
    if trigger_type is not None and trigger_type not in allowed_triggers:
        db.rollback()
        return None
    if not allowed_triggers:
        db.rollback()
        return None
    active_leases = int(
        db.scalar(
            select(func.count(ExceptionDiagnosisJob.id)).where(
                ExceptionDiagnosisJob.status == "processing",
                ExceptionDiagnosisJob.lease_expires_at.is_not(None),
                ExceptionDiagnosisJob.lease_expires_at > now,
            )
        )
        or 0
    )
    if active_leases >= policy.ai_concurrency:
        db.rollback()
        return None
    claimable = or_(
        and_(
            ExceptionDiagnosisJob.status == "queued",
            or_(ExceptionDiagnosisJob.available_at.is_(None), ExceptionDiagnosisJob.available_at <= now),
        ),
        and_(
            ExceptionDiagnosisJob.status == "processing",
            or_(
                ExceptionDiagnosisJob.lease_expires_at.is_(None),
                ExceptionDiagnosisJob.lease_expires_at < now,
            ),
        ),
    )
    stmt = select(ExceptionDiagnosisJob).where(
        claimable,
        ExceptionDiagnosisJob.trigger_type.in_(allowed_triggers),
    )
    if trigger_type is not None:
        stmt = stmt.where(ExceptionDiagnosisJob.trigger_type == trigger_type)
    job = db.scalar(
        stmt.order_by(
            sql_case((ExceptionDiagnosisJob.trigger_type == "manual", 0), else_=1),
            ExceptionDiagnosisJob.available_at.asc().nullsfirst(),
            ExceptionDiagnosisJob.created_at.asc(),
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        db.rollback()
        return None
    job.status = "processing"
    job.lease_owner = worker_id
    job.lease_expires_at = now + timedelta(seconds=max(30, settings.exception_job_lease_seconds))
    job.started_at = job.started_at or now
    job.attempts = (job.attempts or 0) + 1
    job.error_message = None
    db.commit()
    db.refresh(job)
    return job


def enqueue_background_job(
    db: Session,
    *,
    job_type: str,
    payload: dict | None = None,
    dedupe_key: str | None = None,
) -> tuple[ExceptionBackgroundJob, bool]:
    if dedupe_key:
        existing = db.scalar(select(ExceptionBackgroundJob).where(ExceptionBackgroundJob.dedupe_key == dedupe_key))
        if existing is not None:
            return existing, True
    now = utcnow()
    job = ExceptionBackgroundJob(
        job_no=f"EXBG-{now:%Y%m%d%H%M%S}-{__import__('secrets').token_hex(4).upper()}",
        job_type=job_type,
        payload_json=payload or {},
        status="queued",
        available_at=now,
        dedupe_key=dedupe_key,
    )
    db.add(job)
    db.flush()
    return job, False


def enqueue_incremental_scan(
    db: Session,
    *,
    domains: list[str] | set[str] | tuple[str, ...] | None = None,
    source_batch_kind: str | None = None,
    source_batch_id: int | None = None,
    target_resource_type: str | None = None,
    target_resource_id: str | int | None = None,
) -> tuple[ExceptionBackgroundJob, bool]:
    if (source_batch_kind is None) != (source_batch_id is None):
        raise ValueError("source_batch_kind and source_batch_id must be provided together")
    if source_batch_kind is not None and source_batch_kind not in {"import", "inventory_check", "legacy"}:
        raise ValueError(f"Unsupported source batch kind: {source_batch_kind}")
    if (target_resource_type is None) != (target_resource_id is None):
        raise ValueError("target_resource_type and target_resource_id must be provided together")
    normalized_domains = sorted(set(domains or []))
    normalized_target_id: str | None = None
    if target_resource_type is not None:
        if len(normalized_domains) != 1:
            raise ValueError("Target exception scans require exactly one domain")
        target_domain = normalized_domains[0]
        if target_resource_type not in TARGET_RESOURCE_DOMAINS.get(target_domain, set()):
            raise ValueError(f"Unsupported target resource for {target_domain}: {target_resource_type}")
        try:
            target_id = int(target_resource_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("target_resource_id must be a positive integer") from exc
        if target_id <= 0:
            raise ValueError("target_resource_id must be a positive integer")
        normalized_target_id = str(target_id)
    payload: dict[str, object] = {}
    if normalized_domains:
        payload["domains"] = normalized_domains
    if source_batch_id is not None:
        payload["source_batch_kind"] = source_batch_kind
        payload["source_batch_id"] = source_batch_id
    if target_resource_type is not None:
        payload["target_resource_type"] = target_resource_type
        payload["target_resource_id"] = normalized_target_id
        dedupe_key = f"incremental:target:{normalized_domains[0]}:{target_resource_type}:{normalized_target_id}"
    else:
        dedupe_key = (
            f"incremental:{source_batch_kind}:{source_batch_id}"
            if source_batch_id is not None
            else "incremental:global"
        )
    if dedupe_key:
        existing = db.scalar(
            select(ExceptionBackgroundJob)
            .where(ExceptionBackgroundJob.dedupe_key == dedupe_key)
            .with_for_update()
        )
        if existing is not None and existing.status == "queued":
            current_payload = existing.payload_json or {}
            current_domains = set(current_payload.get("domains") or [])
            requested_domains = set(payload.get("domains") or [])
            if not current_domains or not requested_domains:
                current_payload.pop("domains", None)
            else:
                current_payload["domains"] = sorted(current_domains | requested_domains)
            existing.payload_json = current_payload
            db.flush()
            return existing, True
        if existing is not None:
            # A processing worker may already have read its payload. Move the stable
            # key to a follow-up job so concurrent arrivals cannot be swallowed.
            existing.dedupe_key = None
            db.flush()
    return enqueue_background_job(db, job_type="incremental_scan", payload=payload, dedupe_key=dedupe_key)


def claim_background_job(db: Session, *, worker_id: str) -> ExceptionBackgroundJob | None:
    now = utcnow()
    claimable = or_(
        and_(
            ExceptionBackgroundJob.status == "queued",
            or_(ExceptionBackgroundJob.available_at.is_(None), ExceptionBackgroundJob.available_at <= now),
        ),
        and_(
            ExceptionBackgroundJob.status == "processing",
            or_(
                ExceptionBackgroundJob.lease_expires_at.is_(None),
                ExceptionBackgroundJob.lease_expires_at < now,
            ),
        ),
    )
    job = db.scalar(
        select(ExceptionBackgroundJob)
        .where(claimable)
        .order_by(ExceptionBackgroundJob.available_at.asc().nullsfirst(), ExceptionBackgroundJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        db.rollback()
        return None
    job.status = "processing"
    job.lease_owner = worker_id
    job.lease_expires_at = now + timedelta(seconds=max(30, settings.exception_job_lease_seconds))
    job.started_at = job.started_at or now
    job.attempts = (job.attempts or 0) + 1
    job.error_message = None
    db.commit()
    db.refresh(job)
    return job


def heartbeat_diagnosis_job(*, job_id: int, worker_id: str, lease_generation: int | None = None) -> bool:
    now = utcnow()
    with SessionLocal() as db:
        ownership = [
            ExceptionDiagnosisJob.id == job_id,
            ExceptionDiagnosisJob.status == "processing",
            ExceptionDiagnosisJob.lease_owner == worker_id,
        ]
        if lease_generation is not None:
            ownership.append(ExceptionDiagnosisJob.attempts == lease_generation)
        result = db.execute(
            update(ExceptionDiagnosisJob)
            .where(*ownership)
            .values(lease_expires_at=now + timedelta(seconds=max(30, settings.exception_job_lease_seconds)))
        )
        db.commit()
        renewed = bool(result.rowcount)
    if renewed:
        try:
            record_service_heartbeat(
                service_type="ai_worker",
                instance_id=worker_id,
                metadata={"active_job_id": job_id, "circuit": hermes_circuit_status()},
            )
        except Exception:
            pass
    return renewed


def heartbeat_background_job(*, job_id: int, worker_id: str, lease_generation: int | None = None) -> bool:
    now = utcnow()
    with SessionLocal() as db:
        ownership = [
            ExceptionBackgroundJob.id == job_id,
            ExceptionBackgroundJob.status == "processing",
            ExceptionBackgroundJob.lease_owner == worker_id,
        ]
        if lease_generation is not None:
            ownership.append(ExceptionBackgroundJob.attempts == lease_generation)
        result = db.execute(
            update(ExceptionBackgroundJob)
            .where(*ownership)
            .values(lease_expires_at=now + timedelta(seconds=max(30, settings.exception_job_lease_seconds)))
        )
        db.commit()
        renewed = bool(result.rowcount)
    if renewed:
        try:
            record_service_heartbeat(
                service_type="worker",
                instance_id=worker_id,
                metadata={"active_job_id": job_id},
            )
        except Exception:
            pass
    return renewed


@contextmanager
def diagnosis_job_heartbeat(
    *,
    job_id: int,
    worker_id: str,
    lease_generation: int | None = None,
) -> Iterator[None]:
    stop = threading.Event()
    lease_lost = threading.Event()

    def beat() -> None:
        interval = max(5, settings.exception_worker_heartbeat_seconds)
        while not stop.wait(interval):
            try:
                renewed = heartbeat_diagnosis_job(
                    job_id=job_id,
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                )
            except Exception:
                lease_lost.set()
                return
            if not renewed:
                lease_lost.set()
                return

    thread = threading.Thread(target=beat, name=f"exception-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)
    if lease_lost.is_set():
        raise JobLeaseLostError("Diagnosis job lease was lost during model execution")


@contextmanager
def background_job_heartbeat(
    *,
    job_id: int,
    worker_id: str,
    lease_generation: int | None = None,
) -> Iterator[None]:
    stop = threading.Event()
    lease_lost = threading.Event()

    def beat() -> None:
        interval = max(5, settings.exception_worker_heartbeat_seconds)
        while not stop.wait(interval):
            try:
                renewed = heartbeat_background_job(
                    job_id=job_id,
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                )
            except Exception:
                lease_lost.set()
                return
            if not renewed:
                lease_lost.set()
                return

    thread = threading.Thread(target=beat, name=f"exception-background-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)
    if lease_lost.is_set():
        raise JobLeaseLostError("Background job lease was lost during execution")


def _today_ai_call_count(db: Session, *, trigger_type: str) -> int:
    now = utcnow()
    local_now = now.astimezone(ZoneInfo(settings.exception_schedule_timezone))
    local_day_start = datetime(
        local_now.year,
        local_now.month,
        local_now.day,
        tzinfo=ZoneInfo(settings.exception_schedule_timezone),
    )
    day_start = local_day_start.astimezone(timezone.utc)
    details = db.scalars(
        select(ExceptionEvent.detail_json).where(
            ExceptionEvent.event_type == "diagnosis_ai_call_started",
            ExceptionEvent.created_at >= day_start,
        )
    ).all()
    diagnosis_calls = sum(1 for detail in details if (detail or {}).get("trigger_type") == trigger_type)
    if trigger_type != "manual":
        return diagnosis_calls
    canary_calls = int(
        db.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.action_type == "exception_provider_call_started",
                AuditLog.resource_type == "exception_provider_canary",
                AuditLog.created_at >= day_start,
            )
        )
        or 0
    )
    return diagnosis_calls + canary_calls


def ai_budget_status(db: Session, *, trigger_type: str) -> dict[str, int | bool | None]:
    policy = load_exception_runtime_policy(db)
    is_manual = trigger_type == "manual"
    enabled = policy.manual_ai_enabled if is_manual else policy.scheduled_ai_enabled
    limit = policy.manual_ai_daily_limit if is_manual else policy.scheduled_ai_daily_limit
    used = _today_ai_call_count(db, trigger_type="manual" if is_manual else "scheduled")
    unlimited = quota_is_unlimited(limit)
    return {
        "policy_enabled": policy.is_enabled,
        "enabled": enabled,
        "limit": limit,
        "used": used,
        "remaining": quota_remaining(limit, used),
        "unlimited": unlimited,
        "available": bool(
            settings.exception_ai_enabled
            and policy.is_enabled
            and enabled
            and not quota_exhausted(limit, used)
        ),
    }


def _lock_owned_diagnosis_context(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    lease_generation: int | None = None,
) -> tuple[ExceptionDiagnosisJob | None, ExceptionCase | None]:
    """Lock a leased job and its case in the same order used by case mutations."""
    acquire_exception_case_mutation_lock(db)
    ownership = [
        ExceptionDiagnosisJob.id == job_id,
        ExceptionDiagnosisJob.status == "processing",
        ExceptionDiagnosisJob.lease_owner == worker_id,
        ExceptionDiagnosisJob.lease_expires_at.is_not(None),
        ExceptionDiagnosisJob.lease_expires_at > utcnow(),
    ]
    if lease_generation is not None:
        ownership.append(ExceptionDiagnosisJob.attempts == lease_generation)
    job = db.scalar(
        select(ExceptionDiagnosisJob)
        .where(*ownership)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if job is None:
        return None, None
    case = db.scalar(
        select(ExceptionCase)
        .where(ExceptionCase.id == job.case_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    return job, case


def _obsolete_diagnosis_detail(
    case: ExceptionCase,
    job: ExceptionDiagnosisJob,
    *,
    phase: str,
    request_id: str | None = None,
) -> tuple[str, dict] | None:
    detail: dict[str, object] = {
        "phase": phase,
        "lease_generation": int(job.attempts or 0),
        "job_evidence_version": job.evidence_version,
        "current_evidence_version": case.evidence_version,
    }
    if request_id:
        detail["request_id"] = request_id
    if case.status in _TERMINAL_CASE_STATUSES:
        detail.update({"reason_code": "case_terminal", "case_status": case.status})
        return f"Exception case is already {case.status}", detail
    if case.evidence_version != job.evidence_version:
        detail["reason_code"] = "evidence_superseded"
        return "Evidence version was superseded during diagnosis", detail
    return None


def _cancel_if_obsolete_locked(
    db: Session,
    *,
    job: ExceptionDiagnosisJob,
    case: ExceptionCase,
    phase: str,
    request_id: str | None = None,
) -> bool:
    obsolete = _obsolete_diagnosis_detail(case, job, phase=phase, request_id=request_id)
    if obsolete is None:
        return False
    message, detail = obsolete
    complete_cancelled_diagnosis_job(db, job, message=message, audit_detail=detail)
    return True


def _reserve_ai_call_budget(
    db: Session,
    *,
    case: ExceptionCase,
    job: ExceptionDiagnosisJob,
    request_id: str,
    http_attempt: int = 1,
    worker_id: str | None = None,
    lease_generation: int | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[bool, str | None]:
    """Atomically reserve budget for one imminent provider HTTP attempt."""
    if not settings.exception_ai_enabled:
        return False, "Exception AI diagnosis is disabled"
    if worker_id is None and lease_generation is not None:
        raise ValueError("worker_id and lease_generation must be provided together")
    if worker_id is None:
        worker_id = job.lease_owner
    if not worker_id:
        raise JobLeaseLostError("Diagnosis job lease was lost before provider request")
    reservation_job, locked_case = _lock_owned_diagnosis_context(
        db,
        job_id=job.id,
        worker_id=worker_id,
        lease_generation=lease_generation,
    )
    if reservation_job is None:
        raise JobLeaseLostError("Diagnosis job lease was lost before provider request")
    if locked_case is None:
        raise DiagnosisJobObsoleteError("Exception case no longer exists")
    if reservation_job.cancel_requested_at is not None:
        complete_cancelled_diagnosis_job(
            db,
            reservation_job,
            message=reservation_job.error_message or "Diagnosis cancellation requested",
        )
        db.commit()
        raise DiagnosisJobObsoleteError("Diagnosis cancellation requested")
    if _cancel_if_obsolete_locked(
        db,
        job=reservation_job,
        case=locked_case,
        phase="before_http_attempt",
        request_id=request_id,
    ):
        db.commit()
        raise DiagnosisJobObsoleteError("Diagnosis job became obsolete before provider request")
    if cancel_event is not None and cancel_event.is_set():
        raise HermesCancelledError("Exception AI worker is stopping")
    policy_row = db.scalar(
        select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default").with_for_update()
    )
    if policy_row is None:
        policy_row = ExceptionPolicy(
            policy_key="default",
            is_enabled=True,
            manual_ai_enabled=False,
            scheduled_ai_enabled=False,
            full_scan_enabled=False,
            digest_enabled=False,
            full_scan_cron="30 2 * * *",
            digest_cron="30 8 * * *",
            ai_daily_limit=max(0, settings.exception_ai_daily_limit),
            ai_batch_limit=max(1, settings.exception_ai_scheduled_batch_size),
            manual_ai_daily_limit=max(0, settings.exception_manual_ai_daily_limit),
            scheduled_ai_daily_limit=max(0, settings.exception_scheduled_ai_daily_limit),
            scheduled_ai_batch_limit=max(1, settings.exception_scheduled_ai_batch_size),
            ai_concurrency=1,
            stale_diagnosis_hours=24,
        )
        db.add(policy_row)
        db.flush()
    if not policy_row.is_enabled:
        return False, "Exception policy is disabled"
    budget_type = "manual" if reservation_job.trigger_type == "manual" else "scheduled"
    enabled = policy_row.manual_ai_enabled if budget_type == "manual" else policy_row.scheduled_ai_enabled
    daily_limit = (
        policy_row.manual_ai_daily_limit
        if budget_type == "manual"
        else policy_row.scheduled_ai_daily_limit
    )
    if not enabled:
        return False, f"{budget_type.title()} AI diagnosis is disabled"
    if quota_exhausted(daily_limit, _today_ai_call_count(db, trigger_type=budget_type)):
        return False, f"{budget_type.title()} AI diagnosis daily limit reached"
    db.add(
        ExceptionEvent(
            case_id=locked_case.id,
            event_type="diagnosis_ai_call_started",
            detail_json={
                "job_no": reservation_job.job_no,
                "model": settings.hermes_model,
                "request_id": request_id,
                "trigger_type": budget_type,
                "http_attempt": max(1, http_attempt),
            },
        )
    )
    db.commit()
    return True, None


def _reschedule_job(
    db: Session,
    job: ExceptionDiagnosisJob,
    case: ExceptionCase,
    message: str,
    *,
    seconds: int,
    case_status: str,
) -> None:
    if job.cancel_requested_at is not None:
        complete_cancelled_diagnosis_job(
            db,
            job,
            message=job.error_message or "Diagnosis cancellation requested",
        )
        db.commit()
        return
    if _cancel_if_obsolete_locked(db, job=job, case=case, phase="before_deferral"):
        db.commit()
        return
    job.status = "queued"
    job.available_at = utcnow() + timedelta(seconds=max(1, seconds))
    job.lease_owner = None
    job.lease_expires_at = None
    job.error_message = message[:2000]
    previous_status = case.status
    case.status = case_status
    db.add(
        ExceptionEvent(
            case_id=case.id,
            event_type="diagnosis_deferred",
            from_status=previous_status,
            to_status=case_status,
            detail_json={"job_no": job.job_no, "reason": message},
        )
    )
    db.commit()


def complete_cancelled_diagnosis_job(
    db: Session,
    job: ExceptionDiagnosisJob,
    *,
    message: str = "Diagnosis cancellation requested",
    audit_detail: dict | None = None,
) -> None:
    previous_job_status = job.status
    job.status = "cancelled"
    job.completed_at = utcnow()
    job.error_message = message[:2000]
    job.lease_owner = None
    job.lease_expires_at = None
    case = db.get(ExceptionCase, job.case_id)
    previous_case_status = case.status if case else None
    if case is not None and case.evidence_version == job.evidence_version:
        other_active = db.scalar(
            select(ExceptionDiagnosisJob.id).where(
                ExceptionDiagnosisJob.case_id == case.id,
                ExceptionDiagnosisJob.evidence_version == case.evidence_version,
                ExceptionDiagnosisJob.id != job.id,
                ExceptionDiagnosisJob.status.in_(("queued", "processing")),
            ).limit(1)
        )
        if other_active is None and case.status == "processing":
            lifecycle_events = list(
                db.scalars(
                    select(ExceptionEvent)
                    .where(
                        ExceptionEvent.case_id == case.id,
                        ExceptionEvent.event_type.in_(("diagnosis_queued", "diagnosis_retried")),
                    )
                    .order_by(ExceptionEvent.id.desc())
                ).all()
            )
            restore_event = next(
                (
                    event
                    for event in lifecycle_events
                    if (event.detail_json or {}).get("job_no") == job.job_no
                ),
                None,
            )
            diagnosis = db.scalar(
                select(ExceptionDiagnosis)
                .where(
                    ExceptionDiagnosis.case_id == case.id,
                    ExceptionDiagnosis.evidence_version == case.evidence_version,
                )
                .order_by(ExceptionDiagnosis.id.desc())
                .limit(1)
            )
            restored_status = restore_event.from_status if restore_event is not None else None
            if restored_status in {"open", "action_required", "blocked"}:
                case.status = restored_status
            else:
                case.status = (
                    {"actionable": "action_required", "manual_review": "open", "blocked": "blocked"}.get(
                        diagnosis.disposition,
                        "open",
                    )
                    if diagnosis is not None
                    else "open"
                )
    cancel_requested_at = job.cancel_requested_at.isoformat() if job.cancel_requested_at else None
    cancellation_key = {
        "job_id": job.id,
        "lease_generation": int(job.attempts or 0),
        "cancel_requested_at": cancel_requested_at,
    }
    existing_cancelled_events = list(
        db.scalars(
            select(ExceptionEvent)
            .where(
                ExceptionEvent.case_id == job.case_id,
                ExceptionEvent.event_type == "diagnosis_cancelled",
            )
            .order_by(ExceptionEvent.id.desc())
            .limit(100)
        ).all()
    )
    already_recorded = any(
        all((event.detail_json or {}).get(key) == value for key, value in cancellation_key.items())
        for event in existing_cancelled_events
    )
    if case is not None and not already_recorded:
        db.add(
            ExceptionEvent(
                case_id=case.id,
                event_type="diagnosis_cancelled",
                actor_user_id=job.cancel_requested_by_user_id,
                from_status=previous_case_status,
                to_status=case.status,
                detail_json={
                    "job_no": job.job_no,
                    **cancellation_key,
                    "previous_job_status": previous_job_status,
                    "reason": message,
                    **(audit_detail or {}),
                },
            )
        )


def _finalize_failed_attempt_locked(
    db: Session,
    *,
    job: ExceptionDiagnosisJob,
    case: ExceptionCase,
    error: Exception,
) -> None:
    if isinstance(error, HermesUnavailableError):
        message = "AI provider is temporarily unavailable"
    elif isinstance(error, HermesResponseError):
        message = "AI provider returned an invalid structured diagnosis"
    elif isinstance(error, IntegrityError):
        message = "Diagnosis persistence conflict"
    else:
        message = f"Diagnosis failed ({error.__class__.__name__})"
    job.lease_owner = None
    job.lease_expires_at = None
    if job.attempts < max(1, settings.exception_job_max_attempts):
        job.status = "queued"
        job.available_at = utcnow() + timedelta(seconds=min(60 * (2 ** max(0, job.attempts - 1)), 900))
        previous_status = None
    else:
        job.status = "failed"
        job.completed_at = utcnow()
        previous_status = case.status
        case.status = "blocked"
    job.error_message = message
    db.add(
        ExceptionEvent(
            case_id=job.case_id,
            event_type="diagnosis_retry" if job.status == "queued" else "diagnosis_failed",
            from_status=previous_status if job.status == "failed" else None,
            to_status="blocked" if job.status == "failed" else "processing",
            detail_json={"job_no": job.job_no, "attempts": job.attempts, "error": message},
        )
    )


def _fail_or_retry_job(
    db: Session,
    job: ExceptionDiagnosisJob,
    error: Exception,
    *,
    worker_id: str | None = None,
    lease_generation: int | None = None,
) -> None:
    """Finalize a failed attempt only after locking and revalidating the case."""
    acquire_exception_case_mutation_lock(db)
    conditions = [
        ExceptionDiagnosisJob.id == job.id,
        ExceptionDiagnosisJob.status == "processing",
    ]
    if worker_id is not None:
        conditions.append(ExceptionDiagnosisJob.lease_owner == worker_id)
    if lease_generation is not None:
        conditions.append(ExceptionDiagnosisJob.attempts == lease_generation)
    locked_job = db.scalar(
        select(ExceptionDiagnosisJob)
        .where(*conditions)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if locked_job is None:
        raise JobLeaseLostError("Diagnosis job lease was lost before failure handling")
    locked_case = db.scalar(
        select(ExceptionCase)
        .where(ExceptionCase.id == locked_job.case_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if locked_case is None:
        locked_job.status = "failed"
        locked_job.completed_at = utcnow()
        locked_job.error_message = "Exception case no longer exists"
        locked_job.lease_owner = None
        locked_job.lease_expires_at = None
        db.commit()
        return
    if locked_job.cancel_requested_at is not None:
        complete_cancelled_diagnosis_job(
            db,
            locked_job,
            message=locked_job.error_message or "Diagnosis cancellation requested",
        )
        db.commit()
        return
    if _cancel_if_obsolete_locked(db, job=locked_job, case=locked_case, phase="after_provider_failure"):
        db.commit()
        return
    _finalize_failed_attempt_locked(db, job=locked_job, case=locked_case, error=error)
    db.commit()


def _handoff_stopping_job(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    lease_generation: int,
) -> str:
    """Release a healthy in-flight job so another worker can resume it."""
    job, case = _lock_owned_diagnosis_context(
        db,
        job_id=job_id,
        worker_id=worker_id,
        lease_generation=lease_generation,
    )
    if job is None:
        db.rollback()
        current_status = db.scalar(
            select(ExceptionDiagnosisJob.status).where(ExceptionDiagnosisJob.id == job_id)
        )
        return str(current_status) if current_status in {"cancelled", "completed", "failed"} else "lease_lost"
    if case is None:
        job.status = "failed"
        job.completed_at = utcnow()
        job.error_message = "Exception case no longer exists"
        job.lease_owner = None
        job.lease_expires_at = None
        db.commit()
        return job.status
    if job.cancel_requested_at is not None:
        complete_cancelled_diagnosis_job(
            db,
            job,
            message=job.error_message or "Diagnosis cancellation requested",
        )
        db.commit()
        return job.status
    if _cancel_if_obsolete_locked(db, job=job, case=case, phase="worker_shutdown"):
        db.commit()
        return job.status

    job.status = "queued"
    job.available_at = utcnow()
    job.lease_owner = None
    job.lease_expires_at = None
    job.error_message = "Exception AI worker shutdown requested"
    db.add(
        ExceptionEvent(
            case_id=case.id,
            event_type="diagnosis_deferred",
            from_status=case.status,
            to_status=case.status,
            detail_json={
                "job_no": job.job_no,
                "reason": "Exception AI worker shutdown requested",
                "reason_code": "worker_shutdown",
                "lease_generation": lease_generation,
            },
        )
    )
    db.commit()
    return job.status


def handoff_diagnosis_jobs_for_worker(
    *,
    worker_id: str,
    reason: str = "Exception AI worker shutdown requested",
) -> int:
    """Atomically release all diagnosis leases owned by a stopping worker."""
    with SessionLocal() as db:
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            acquired = bool(
                db.scalar(select(func.pg_try_advisory_xact_lock(EXCEPTION_SYNC_ADVISORY_LOCK_KEY)))
            )
            if not acquired:
                db.rollback()
                return 0
        else:
            acquire_exception_case_mutation_lock(db)
        jobs = list(
            db.scalars(
                select(ExceptionDiagnosisJob)
                .where(
                    ExceptionDiagnosisJob.status == "processing",
                    ExceptionDiagnosisJob.lease_owner == worker_id,
                )
                .order_by(ExceptionDiagnosisJob.id)
                .with_for_update(skip_locked=True)
            ).all()
        )
        if not jobs:
            db.commit()
            return 0
        case_ids = sorted({job.case_id for job in jobs})
        cases = {
            case.id: case
            for case in db.scalars(
                select(ExceptionCase)
                .where(ExceptionCase.id.in_(case_ids))
                .order_by(ExceptionCase.id)
                .with_for_update(skip_locked=True)
            ).all()
        }
        handed_off = 0
        for job in jobs:
            case = cases.get(job.case_id)
            if case is None:
                # A skipped case lock remains owned by another transaction; do
                # not detach its job without revalidating that case.
                continue
            if job.cancel_requested_at is not None:
                complete_cancelled_diagnosis_job(
                    db,
                    job,
                    message=job.error_message or "Diagnosis cancellation requested",
                )
            elif _cancel_if_obsolete_locked(db, job=job, case=case, phase="worker_shutdown"):
                pass
            else:
                generation = int(job.attempts or 0)
                job.status = "queued"
                job.available_at = utcnow()
                job.lease_owner = None
                job.lease_expires_at = None
                job.error_message = reason[:2000]
                db.add(
                    ExceptionEvent(
                        case_id=case.id,
                        event_type="diagnosis_deferred",
                        from_status=case.status,
                        to_status=case.status,
                        detail_json={
                            "job_no": job.job_no,
                            "reason": reason,
                            "reason_code": "worker_shutdown",
                            "lease_generation": generation,
                        },
                    )
                )
            handed_off += 1
        db.commit()
        return handed_off


def _status_after_ownership_loss(db: Session, job_id: int) -> str:
    db.rollback()
    current_status = db.scalar(
        select(ExceptionDiagnosisJob.status).where(ExceptionDiagnosisJob.id == job_id)
    )
    return str(current_status) if current_status in {"cancelled", "completed", "failed"} else "lease_lost"


def _notification_recipients(case: ExceptionCase, job: ExceptionDiagnosisJob) -> set[int]:
    return {
        user_id
        for user_id in (job.requested_by_user_id, case.assignee_user_id)
        if user_id is not None
    }


def _store_diagnosis(
    db: Session,
    *,
    job: ExceptionDiagnosisJob,
    case: ExceptionCase,
    result,
) -> ExceptionDiagnosis:
    if case.status in _TERMINAL_CASE_STATUSES or case.evidence_version != job.evidence_version:
        raise DiagnosisJobObsoleteError("Diagnosis result no longer matches the active case")
    output = result.diagnosis
    diagnosis = ExceptionDiagnosis(
        case_id=case.id,
        job_id=job.id,
        evidence_version=job.evidence_version,
        root_cause_code=output.root_cause_code,
        summary=output.summary,
        confidence=Decimal(str(output.confidence)),
        disposition=output.disposition,
        evidence_refs_json=output.evidence_refs,
        impact_json={"summary": output.impact},
        recommended_steps_json=output.recommended_steps,
        missing_evidence_json=output.missing_evidence,
        model_name=result.metadata.model,
        request_id=result.metadata.request_id,
        prompt_version=result.metadata.prompt_version,
        contract_version=result.metadata.contract_version,
        provider_request_id=result.metadata.provider_request_id,
        latency_ms=result.metadata.latency_ms,
        prompt_tokens=result.metadata.prompt_tokens,
        completion_tokens=result.metadata.completion_tokens,
        total_tokens=result.metadata.total_tokens,
        diagnosed_at=result.metadata.completed_at,
    )
    db.add(diagnosis)
    db.flush()

    previous_status = case.status
    case.status = {
        "actionable": "action_required",
        "manual_review": "open",
        "blocked": "blocked",
    }[output.disposition]
    job.status = "completed"
    job.completed_at = utcnow()
    job.lease_owner = None
    job.lease_expires_at = None
    job.error_message = None
    metadata = result.metadata.model_dump(mode="json")
    db.add(
        ExceptionEvent(
            case_id=case.id,
            event_type="diagnosed",
            from_status=previous_status,
            to_status=case.status,
            detail_json={
                "diagnosis_id": diagnosis.id,
                "job_id": job.id,
                "job_no": job.job_no,
                "evidence_version": diagnosis.evidence_version,
                "diagnosis": output.model_dump(mode="json"),
                "model_call": metadata,
            },
        )
    )
    for user_id in _notification_recipients(case, job):
        duplicate = db.scalar(
            select(ExceptionNotification.id).where(
                ExceptionNotification.case_id == case.id,
                ExceptionNotification.user_id == user_id,
                ExceptionNotification.notification_type == "diagnosis_completed",
                ExceptionNotification.evidence_version == job.evidence_version,
                ExceptionNotification.occurrence_cycle == case.occurrence_cycle,
            )
        )
        if duplicate is None:
            db.add(
                ExceptionNotification(
                    case_id=case.id,
                    user_id=user_id,
                    notification_type="diagnosis_completed",
                    evidence_version=job.evidence_version,
                    occurrence_cycle=case.occurrence_cycle,
                    title=f"异常 {case.case_no} 智能诊断完成",
                    message=output.summary,
                )
            )
    db.commit()
    db.refresh(diagnosis)
    return diagnosis


def execute_diagnosis_job(
    *,
    job_id: int,
    worker_id: str,
    lease_generation: int | None = None,
    stop_event: threading.Event | None = None,
) -> str:
    """Execute one already-leased diagnosis job and return its terminal/current status."""
    with SessionLocal() as db:
        job, case = _lock_owned_diagnosis_context(
            db,
            job_id=job_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        if job is None:
            db.rollback()
            return "lease_lost"
        active_generation = int(job.attempts or 0)
        if job.cancel_requested_at is not None:
            complete_cancelled_diagnosis_job(
                db,
                job,
                message=job.error_message or "Diagnosis cancellation requested",
            )
            db.commit()
            return job.status
        if case is None:
            job.status = "failed"
            job.completed_at = utcnow()
            job.error_message = "Exception case no longer exists"
            job.lease_owner = None
            job.lease_expires_at = None
            db.commit()
            return job.status
        if _cancel_if_obsolete_locked(db, job=job, case=case, phase="before_generation"):
            db.commit()
            return job.status
        if stop_event is not None and stop_event.is_set():
            db.rollback()
            return _handoff_stopping_job(
                db,
                job_id=job_id,
                worker_id=worker_id,
                lease_generation=active_generation,
            )
        if case.domain not in AI_DIAGNOSIS_DOMAINS:
            previous_status = case.status
            job.status = "failed"
            job.completed_at = utcnow()
            job.error_message = f"AI diagnosis is not supported for the {case.domain} exception domain"
            job.lease_owner = None
            job.lease_expires_at = None
            case.status = "blocked"
            db.add(
                ExceptionEvent(
                    case_id=case.id,
                    event_type="diagnosis_failed",
                    from_status=previous_status,
                    to_status="blocked",
                    detail_json={
                        "job_no": job.job_no,
                        "reason_code": "exception_diagnosis_not_supported",
                        "domain": case.domain,
                    },
                )
            )
            db.commit()
            return job.status
        if not settings.exception_center_enabled or not settings.exception_ai_enabled:
            _reschedule_job(
                db,
                job,
                case,
                "Exception AI diagnosis is disabled",
                seconds=3600,
                case_status="blocked",
            )
            return job.status
        evidence = db.scalar(
            select(ExceptionEvidence).where(
                ExceptionEvidence.case_id == case.id,
                ExceptionEvidence.evidence_version == job.evidence_version,
            )
        )
        if evidence is None:
            _finalize_failed_attempt_locked(
                db,
                job=job,
                case=case,
                error=RuntimeError("Evidence snapshot is missing"),
            )
            db.commit()
            return job.status
        allowed_codes = evidence.data_json.get("allowed_root_cause_codes")
        if not isinstance(allowed_codes, list):
            allowed_codes = DOMAIN_ROOT_CAUSE_CODES[case.domain]
        request_id = f"exception-ai-{job.job_no}"
        evidence_data = evidence.data_json
        case_domain = case.domain
        trigger_type = job.trigger_type
        # Never hold case locks during provider I/O. Every attempt and every
        # terminal path reacquires the shared mutation lock and row locks.
        db.rollback()
        try:
            if stop_event is not None and stop_event.is_set():
                return _handoff_stopping_job(
                    db,
                    job_id=job_id,
                    worker_id=worker_id,
                    lease_generation=active_generation,
                )
            budget = ai_budget_status(db, trigger_type="manual" if trigger_type == "manual" else "scheduled")
            if not budget["available"]:
                if not settings.exception_ai_enabled:
                    blocked_reason = "Exception AI diagnosis is disabled"
                elif not budget["policy_enabled"]:
                    blocked_reason = "Exception policy is disabled"
                elif not budget["enabled"]:
                    blocked_reason = f"{trigger_type.title()} AI diagnosis is disabled"
                else:
                    blocked_reason = f"{trigger_type.title()} AI diagnosis daily limit reached"
                db.rollback()
                locked_job, locked_case = _lock_owned_diagnosis_context(
                    db,
                    job_id=job_id,
                    worker_id=worker_id,
                    lease_generation=active_generation,
                )
                if locked_job is None:
                    return _status_after_ownership_loss(db, job_id)
                if locked_case is None:
                    locked_job.status = "failed"
                    locked_job.completed_at = utcnow()
                    locked_job.error_message = "Exception case no longer exists"
                    locked_job.lease_owner = None
                    locked_job.lease_expires_at = None
                    db.commit()
                    return locked_job.status
                _reschedule_job(
                    db,
                    locked_job,
                    locked_case,
                    blocked_reason,
                    seconds=3600,
                    case_status="blocked" if blocked_reason == "Exception policy is disabled" else "open",
                )
                return job.status

            def reserve_http_attempt(http_attempt: int) -> None:
                reserved, blocked_reason = _reserve_ai_call_budget(
                    db,
                    case=case,
                    job=job,
                    request_id=request_id,
                    http_attempt=http_attempt,
                    worker_id=worker_id,
                    lease_generation=active_generation,
                    cancel_event=stop_event,
                )
                if not reserved:
                    raise HermesUnavailableError(blocked_reason or "AI diagnosis budget is unavailable")

            with diagnosis_job_heartbeat(
                job_id=job.id,
                worker_id=worker_id,
                lease_generation=active_generation,
            ):
                result = call_hermes_exception_diagnosis(
                    evidence_data,
                    domain=case_domain,
                    allowed_root_cause_codes=allowed_codes,
                    request_id=request_id,
                    before_http_attempt=reserve_http_attempt,
                    cancel_event=stop_event,
                    require_complete_usage=(
                        trigger_type == "manual"
                        and settings.exception_manual_ai_require_provider_usage
                    ),
                )
            # End the model-call read transaction before acquiring persistence locks.
            db.rollback()
            if stop_event is not None and stop_event.is_set():
                return _handoff_stopping_job(
                    db,
                    job_id=job_id,
                    worker_id=worker_id,
                    lease_generation=active_generation,
                )
            locked_job, locked_case = _lock_owned_diagnosis_context(
                db,
                job_id=job_id,
                worker_id=worker_id,
                lease_generation=active_generation,
            )
            if locked_job is None:
                return _status_after_ownership_loss(db, job_id)
            if locked_job.cancel_requested_at is not None:
                complete_cancelled_diagnosis_job(
                    db,
                    locked_job,
                    message=locked_job.error_message or "Diagnosis cancellation requested",
                )
                db.commit()
                return locked_job.status
            if locked_case is None:
                locked_job.status = "failed"
                locked_job.completed_at = utcnow()
                locked_job.error_message = "Exception case no longer exists"
                locked_job.lease_owner = None
                locked_job.lease_expires_at = None
                db.commit()
                return locked_job.status
            if _cancel_if_obsolete_locked(
                db,
                job=locked_job,
                case=locked_case,
                phase="after_generation",
                request_id=request_id,
            ):
                db.commit()
                return locked_job.status
            _store_diagnosis(db, job=locked_job, case=locked_case, result=result)
            return locked_job.status
        except DiagnosisJobObsoleteError:
            return _status_after_ownership_loss(db, job_id)
        except HermesCancelledError:
            db.rollback()
            return _handoff_stopping_job(
                db,
                job_id=job_id,
                worker_id=worker_id,
                lease_generation=active_generation,
            )
        except JobLeaseLostError:
            return _status_after_ownership_loss(db, job_id)
        except Exception as exc:
            db.rollback()
            try:
                _fail_or_retry_job(
                    db,
                    job,
                    exc,
                    worker_id=worker_id,
                    lease_generation=active_generation,
                )
            except JobLeaseLostError:
                return _status_after_ownership_loss(db, job_id)
            current_status = db.scalar(
                select(ExceptionDiagnosisJob.status).where(ExceptionDiagnosisJob.id == job_id)
            )
            return str(current_status) if current_status is not None else "failed"


def run_one_diagnosis_job(
    *,
    worker_id: str,
    trigger_type: str | None = None,
    stop_event: threading.Event | None = None,
) -> str | None:
    if stop_event is not None and stop_event.is_set():
        return "stopped"
    with SessionLocal() as db:
        if not settings.exception_ai_enabled:
            return None
        manual = ai_budget_status(db, trigger_type="manual")
        scheduled = ai_budget_status(db, trigger_type="scheduled")
        allowed_manual = bool(manual["available"])
        allowed_scheduled = bool(scheduled["available"])
        effective_trigger = trigger_type
        if trigger_type == "manual" and not allowed_manual:
            return None
        if trigger_type == "scheduled" and not allowed_scheduled:
            return None
        if trigger_type is None:
            if allowed_manual and not allowed_scheduled:
                effective_trigger = "manual"
            elif allowed_scheduled and not allowed_manual:
                effective_trigger = "scheduled"
            elif not allowed_manual and not allowed_scheduled:
                return None
        job = claim_diagnosis_job(db, worker_id=worker_id, trigger_type=effective_trigger)
        job_id = job.id if job else None
        lease_generation = int(job.attempts or 0) if job else None
    if job_id is None:
        return None
    return execute_diagnosis_job(
        job_id=job_id,
        worker_id=worker_id,
        lease_generation=lease_generation,
        stop_event=stop_event,
    )


def _fail_or_retry_background_job(db: Session, job: ExceptionBackgroundJob, error: Exception) -> None:
    job.lease_owner = None
    job.lease_expires_at = None
    job.error_message = f"Background job failed ({error.__class__.__name__})"
    if job.attempts < max(1, settings.exception_job_max_attempts):
        job.status = "queued"
        job.available_at = utcnow() + timedelta(seconds=min(60 * (2 ** max(0, job.attempts - 1)), 900))
    else:
        job.status = "failed"
        job.completed_at = utcnow()
        if job.job_type == "incremental_scan":
            job.dedupe_key = None
    db.commit()


def execute_background_job(
    *,
    job_id: int,
    worker_id: str,
    lease_generation: int | None = None,
) -> str:
    from app.services.exception_center_service import (
        create_exception_digest_notifications,
        enqueue_due_ai_diagnoses,
        run_full_exception_scan,
        run_incremental_exception_scan,
    )

    with SessionLocal() as db:
        ownership = [
            ExceptionBackgroundJob.id == job_id,
            ExceptionBackgroundJob.status == "processing",
            ExceptionBackgroundJob.lease_owner == worker_id,
        ]
        if lease_generation is not None:
            ownership.append(ExceptionBackgroundJob.attempts == lease_generation)
        job = db.scalar(
            select(ExceptionBackgroundJob).where(*ownership)
        )
        if job is None:
            return "lease_lost"
        active_generation = int(job.attempts or 0)
        try:
            with background_job_heartbeat(
                job_id=job.id,
                worker_id=worker_id,
                lease_generation=active_generation,
            ):
                if job.job_type == "full_scan":
                    policy = load_exception_runtime_policy(db)
                    if not policy.is_enabled or not policy.full_scan_enabled:
                        result = {"skipped": True, "reason": "Full exception scan is disabled"}
                    else:
                        result = run_full_exception_scan(db)
                    scheduled_capacity = quota_batch_capacity(
                        policy.scheduled_ai_daily_limit,
                        _today_ai_call_count(db, trigger_type="scheduled"),
                        policy.scheduled_ai_batch_limit,
                    )
                    queued_ai = (
                        enqueue_due_ai_diagnoses(
                            db,
                            limit=scheduled_capacity,
                        )
                        if (
                            not result.get("skipped")
                            and settings.exception_ai_enabled
                            and policy.is_enabled
                            and policy.scheduled_ai_enabled
                            and scheduled_capacity > 0
                        )
                        else []
                    )
                    result["queued_ai"] = len(queued_ai)
                elif job.job_type == "incremental_scan":
                    result = run_incremental_exception_scan(db, job.payload_json or {})
                    policy = load_exception_runtime_policy(db)
                    scheduled_capacity = quota_batch_capacity(
                        policy.scheduled_ai_daily_limit,
                        _today_ai_call_count(db, trigger_type="scheduled"),
                        policy.scheduled_ai_batch_limit,
                    )
                    queued_ai = (
                        enqueue_due_ai_diagnoses(
                            db,
                            limit=scheduled_capacity,
                        )
                        if (
                            settings.exception_ai_enabled
                            and policy.is_enabled
                            and policy.scheduled_ai_enabled
                            and scheduled_capacity > 0
                        )
                        else []
                    )
                    result["queued_ai"] = len(queued_ai)
                elif job.job_type == "digest":
                    policy = load_exception_runtime_policy(db)
                    result = (
                        {"notifications_created": create_exception_digest_notifications(db)}
                        if policy.is_enabled and policy.digest_enabled
                        else {"skipped": True, "reason": "Exception digest is disabled"}
                    )
                else:
                    raise ValueError(f"Unsupported exception background job type: {job.job_type}")
            locked_job = db.scalar(
                select(ExceptionBackgroundJob)
                .where(
                    ExceptionBackgroundJob.id == job_id,
                    ExceptionBackgroundJob.status == "processing",
                    ExceptionBackgroundJob.lease_owner == worker_id,
                    ExceptionBackgroundJob.attempts == active_generation,
                )
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if locked_job is None:
                db.rollback()
                return "lease_lost"
            locked_job.payload_json = {"input": locked_job.payload_json or {}, "result": result}
            locked_job.status = "completed"
            locked_job.completed_at = utcnow()
            if locked_job.job_type == "incremental_scan":
                locked_job.dedupe_key = None
            locked_job.lease_owner = None
            locked_job.lease_expires_at = None
            locked_job.error_message = None
            db.commit()
            return locked_job.status
        except JobLeaseLostError:
            db.rollback()
            return "lease_lost"
        except Exception as exc:
            db.rollback()
            job = db.scalar(
                select(ExceptionBackgroundJob)
                .where(
                    ExceptionBackgroundJob.id == job_id,
                    ExceptionBackgroundJob.status == "processing",
                    ExceptionBackgroundJob.lease_owner == worker_id,
                    ExceptionBackgroundJob.attempts == active_generation,
                )
                .with_for_update()
            )
            if job is None:
                return "lease_lost"
            _fail_or_retry_background_job(db, job, exc)
            return job.status


def run_one_background_job(*, worker_id: str) -> str | None:
    with SessionLocal() as db:
        job = claim_background_job(db, worker_id=worker_id)
        job_id = job.id if job else None
        lease_generation = int(job.attempts or 0) if job else None
    if job_id is None:
        return None
    return execute_background_job(
        job_id=job_id,
        worker_id=worker_id,
        lease_generation=lease_generation,
    )


def run_one_exception_job(*, worker_id: str) -> str | None:
    """Backward-compatible worker entry; deterministic background work only."""
    return run_one_background_job(worker_id=worker_id)
