"""Adapted pinned ERP functions. See docs/phase3-adaptations.md for exact changes."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import and_, or_, select, func, case as sql_case
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import (ExceptionCase, ExceptionDiagnosisJob, ExceptionDiagnosis,
                        ExceptionPolicy, ExceptionEvent, ExceptionNotification)
from app.services.workflow_lock import acquire_exception_case_mutation_lock

_TERMINAL_CASE_STATUSES = {"resolved", "ignored"}


class DiagnosisJobObsoleteError(RuntimeError):
    pass


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
    job.lease_expires_at = now + timedelta(seconds=settings.exception_job_lease_seconds)
    job.started_at = job.started_at or now
    job.attempts = (job.attempts or 0) + 1
    job.error_message = None
    db.add(ExceptionEvent(case_id=job.case_id, event_type="job_claimed",
        detail_json={"job_id":job.id,"worker_id":worker_id,"generation":job.attempts,
                     "evidence_version":job.evidence_version}))
    db.commit()
    db.refresh(job)
    return job


def _lock_owned_diagnosis_context(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    lease_generation: int | None = None,
) -> tuple[ExceptionDiagnosisJob | None, ExceptionCase | None]:
    """Lock a leased job and its case in the same order used by case mutations."""
    if lease_generation is None:
        raise ValueError("Generation is mandatory in the showcase worker")
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
