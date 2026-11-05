from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import case as sql_case, func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.core.config import settings
from app.models import (
    AuditLog,
    ExceptionAction,
    ExceptionBackgroundJob,
    ExceptionCase,
    ExceptionDiagnosis,
    ExceptionDiagnosisJob,
    ExceptionEvent,
    ExceptionEvidence,
    ExceptionNotification,
    ExceptionPolicy,
    User,
)
from app.schemas.exception_center import (
    ActionExecuteRequest,
    ActionResponse,
    ActionValidationRequest,
    AssignRequest,
    BatchAssignRequest,
    BatchExceptionMutationResponse,
    BatchIgnoreRequest,
    DiagnosisFeedbackRequest,
    DiagnosisJobResponse,
    DiagnosisRequest,
    ExceptionCaseDetail,
    ExceptionCasePage,
    ExceptionCaseItem,
    ExceptionAggregationResponse,
    ExceptionBaselineScanRequest,
    ExceptionBaselineScanResponse,
    ExceptionDiagnosisQualitySummary,
    ExceptionDiagnosisResponse,
    ExceptionJobCancelRequest,
    ExceptionJobPage,
    ExceptionJobRetryRequest,
    ExceptionOpsSummary,
    ExceptionRuleQualityResponse,
    ExceptionSummary,
    IgnoreRequest,
    NotificationItem,
    PolicyResponse,
    PolicyPatch,
    PolicyUpdate,
    VerifyRequest,
    VerifyResponse,
)
from app.services.exception_center_service import (
    AI_DIAGNOSIS_DOMAINS,
    acquire_exception_case_mutation_lock,
    can_view_case,
    can_run_global_exception_scan,
    create_diagnosis_job,
    default_policy,
    diagnosis_quality_summary,
    exception_case_sync_target,
    exception_domain_modes,
    exception_rule_quality_summary,
    exception_shadow_baseline_pending_domains,
    normalize_exception_domain_modes,
    execute_action,
    restore_default_assignment,
    serialize_action,
    serialize_case,
    serialize_cases,
    serialize_diagnoses,
    serialize_job,
    scoped_exception_stmt,
    summary_for_cases,
    sync_exception_cases,
    validate_action,
)
from app.services.exception_task_service import (
    ai_budget_status,
    complete_cancelled_diagnosis_job,
    exception_ops_summary,
)
from app.services.audit_service import write_audit_log
from app.services.controlled_action_service import (
    controlled_actions_enabled,
    mirror_exception_action_execution,
    mirror_exception_action_validation,
)


def require_exception_center_enabled() -> None:
    if not settings.exception_center_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception center is disabled")


def require_exception_ai_enabled() -> None:
    if not settings.exception_ai_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Exception AI diagnosis is disabled")


def require_exception_actions_enabled() -> None:
    if not settings.exception_actions_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Exception actions are disabled")


def require_exception_high_risk_actions_enabled() -> None:
    if controlled_actions_enabled() and not settings.exception_ai_high_risk_actions_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="High-risk controlled actions are disabled",
        )


router = APIRouter(tags=["exception-center"], dependencies=[Depends(require_exception_center_enabled)])
ASSIGNABLE_CASE_STATUSES = {"open", "action_required", "processing", "blocked"}
IGNORABLE_CASE_STATUSES = {"open", "action_required", "blocked"}
SOURCE_BATCH_KINDS = {"import", "inventory_check", "legacy"}
AGGREGATION_GROUP_LIMIT = 200
BASELINE_SCAN_AUDIT_ACTION = "run_exception_baseline_scan"
VERIFY_STILL_PRESENT_STATUS_TRANSITIONS = {
    "open": "action_required",
    "action_required": "action_required",
    "blocked": "action_required",
    "processing": "processing",
}
CASE_DOMAIN_PATTERN = "^(inventory|receivable|master_data|import|crm|approval)$"


def _validate_source_batch_filter(
    source_batch_kind: str | None,
    source_batch_id: int | None,
    source_batch_unassigned: bool,
) -> None:
    if source_batch_unassigned and (source_batch_id is not None or source_batch_kind is not None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_batch_unassigned cannot be combined with source_batch_kind or source_batch_id",
        )
    if source_batch_id is not None and source_batch_kind is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_batch_kind is required with source_batch_id",
        )


def _baseline_scan_result(domain: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "domains": [domain],
        "requested_domains": [domain],
        "domain_modes": {domain: "shadow"},
        "scan_trigger": "baseline",
        "scanned": max(0, int(result.get("scanned") or 0)),
        "created": max(0, int(result.get("created") or 0)),
        "new": max(0, int(result.get("new") or 0)),
        "reopened": max(0, int(result.get("reopened") or 0)),
        "evidence_updated": max(0, int(result.get("evidence_updated") or 0)),
        "resolved": max(0, int(result.get("resolved") or 0)),
    }


def _case_or_404(db: Session, case_no: str) -> ExceptionCase:
    case = db.scalar(select(ExceptionCase).where(ExceptionCase.case_no == case_no))
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception case not found")
    return case


def _visible_case_or_404(db: Session, user: User, case_no: str) -> ExceptionCase:
    case = _case_or_404(db, case_no)
    if not can_view_case(db, user, case):
        # Do not reveal whether an out-of-scope case exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception case not found")
    return case


def _visible_case_for_update_or_404(db: Session, user: User, case_no: str) -> ExceptionCase:
    visible = _visible_case_or_404(db, user, case_no)
    locked = db.scalar(
        select(ExceptionCase)
        .where(ExceptionCase.id == visible.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if locked is None or not can_view_case(db, user, locked):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception case not found")
    return locked


def _diagnosis_job_for_update(db: Session, job_id: int) -> ExceptionDiagnosisJob | None:
    return db.scalar(
        select(ExceptionDiagnosisJob)
        .where(ExceptionDiagnosisJob.id == job_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )


def _exception_case_for_update(db: Session, case_id: int) -> ExceptionCase | None:
    return db.scalar(
        select(ExceptionCase)
        .where(ExceptionCase.id == case_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )


def _locked_diagnosis_job_and_case_or_404(
    db: Session,
    user: User,
    job_id: int,
) -> tuple[ExceptionDiagnosisJob, ExceptionCase]:
    # Scans take this advisory lock before any case rows. Mutations follow the
    # same order, then serialize competing job operations before the case lock.
    acquire_exception_case_mutation_lock(db)
    job = _diagnosis_job_for_update(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diagnosis job not found")
    case = _exception_case_for_update(db, job.case_id)
    if case is None or not can_view_case(db, user, case):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diagnosis job not found")
    return job, case


def _diagnosis_not_supported_error(case: ExceptionCase) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": "exception_diagnosis_not_supported",
            "message": "该业务域仅支持确定性诊断，不能发起智能诊断。",
            "module": "exceptions",
            "resource_type": case.resource_type,
            "resource_id": case.resource_id,
            "case_no": case.case_no,
            "diagnosis_supported": False,
            "retryable": False,
            "action_path": f"/exceptions?open={case.case_no}",
        },
    )


def _visible_cases_or_404(db: Session, user: User, case_nos: list[str]) -> list[ExceptionCase]:
    rows = list(
        db.scalars(
            scoped_exception_stmt(db, user)
            .where(ExceptionCase.case_no.in_(case_nos))
            .order_by(ExceptionCase.id)
            .with_for_update()
        ).all()
    )
    by_case_no = {row.case_no: row for row in rows}
    if len(by_case_no) != len(case_nos):
        # Missing and out-of-scope cases intentionally share the same response.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception case not found")
    return [by_case_no[case_no] for case_no in case_nos]


def _validate_assignee(db: Session, assignee_user_id: int | None, cases: list[ExceptionCase]) -> None:
    if assignee_user_id is None:
        return
    assignee = db.get(User, assignee_user_id)
    if assignee is None or not assignee.is_active or assignee.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assignee is not active")
    if any(not can_view_case(db, assignee, case) for case in cases):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assignee cannot access every exception case")


def _validate_case_statuses(cases: list[ExceptionCase], allowed: set[str], operation: str) -> None:
    invalid = [case.case_no for case in cases if case.status not in allowed]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": f"Cases are not eligible for {operation}", "case_nos": invalid},
        )


def _assign_cases(
    db: Session,
    cases: list[ExceptionCase],
    *,
    assignee_user_id: int | None,
    due_at: datetime | None,
    actor_user_id: int,
    is_batch: bool,
    update_assignee: bool = True,
    update_due_at: bool = True,
) -> None:
    for case in cases:
        previous_assignee_user_id = case.assignee_user_id
        previous_due_at = case.due_at
        if update_assignee:
            case.assignee_user_id = assignee_user_id
        if update_due_at:
            case.due_at = due_at
        restoring_defaults = (
            (update_assignee and assignee_user_id is None)
            or (update_due_at and due_at is None)
        )
        if restoring_defaults:
            restore_default_assignment(db, case)
        db.add(
            ExceptionEvent(
                case_id=case.id,
                event_type="assignment_defaults_restored" if restoring_defaults else "assigned",
                actor_user_id=actor_user_id,
                detail_json={
                    "assignee_user_id": case.assignee_user_id,
                    "due_at": case.due_at.isoformat() if case.due_at else None,
                    "previous_assignee_user_id": previous_assignee_user_id,
                    "previous_due_at": previous_due_at.isoformat() if previous_due_at else None,
                    "updated_fields": [
                        field
                        for field, enabled in (("assignee_user_id", update_assignee), ("due_at", update_due_at))
                        if enabled
                    ],
                    "batch": is_batch,
                },
            )
        )


def _ignore_cases(
    db: Session,
    cases: list[ExceptionCase],
    *,
    reason: str,
    ignored_until: datetime,
    actor_user_id: int,
    is_batch: bool,
) -> None:
    for case in cases:
        previous = case.status
        case.status = "ignored"
        case.ignored_until = ignored_until
        case.resolution_note = reason
        db.add(
            ExceptionEvent(
                case_id=case.id,
                event_type="ignored",
                actor_user_id=actor_user_id,
                from_status=previous,
                to_status="ignored",
                detail_json={
                    "reason": reason,
                    "ignored_until": ignored_until.isoformat(),
                    "batch": is_batch,
                },
            )
        )


@router.get("/exceptions/summary", response_model=ExceptionSummary)
def exception_summary(
    occurrence_type: str | None = Query(default=None, pattern="^(baseline|new|reopened)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.view")),
) -> dict[str, Any]:
    return summary_for_cases(db, current_user, occurrence_type=occurrence_type)


@router.get("/exception-ops/summary", response_model=ExceptionOpsSummary)
def get_exception_ops_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.policy_manage")),
) -> dict[str, Any]:
    return exception_ops_summary(db)


@router.get("/exceptions/page", response_model=ExceptionCasePage)
def exception_page(
    domain: str | None = Query(default=None, pattern=CASE_DOMAIN_PATTERN),
    severity: str | None = Query(default=None, pattern="^(warning|high|critical)$"),
    case_status: str | None = Query(default=None, alias="status", pattern="^(open|action_required|processing|blocked|resolved|ignored)$"),
    assignee_user_id: int | None = None,
    assignment: str | None = Query(default=None, pattern="^(mine|assigned|unassigned)$"),
    sla_status: str | None = Query(default=None, pattern="^(overdue|due_soon|on_track|no_due_date)$"),
    rule_code: str | None = Query(default=None, max_length=160),
    source_batch_kind: str | None = Query(default=None, pattern="^(import|inventory_check|legacy)$"),
    source_batch_id: int | None = Query(default=None, ge=1),
    source_batch_unassigned: bool = False,
    occurrence_type: str | None = Query(default=None, pattern="^(baseline|new|reopened)$"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.view")),
) -> dict[str, Any]:
    _validate_source_batch_filter(source_batch_kind, source_batch_id, source_batch_unassigned)
    stmt = scoped_exception_stmt(db, current_user)
    if domain:
        stmt = stmt.where(ExceptionCase.domain == domain)
    if severity:
        stmt = stmt.where(ExceptionCase.severity == severity)
    if case_status:
        stmt = stmt.where(ExceptionCase.status == case_status)
    if assignee_user_id is not None:
        stmt = stmt.where(ExceptionCase.assignee_user_id == assignee_user_id)
    if assignment == "mine":
        stmt = stmt.where(ExceptionCase.assignee_user_id == current_user.id)
    elif assignment == "assigned":
        stmt = stmt.where(ExceptionCase.assignee_user_id.is_not(None))
    elif assignment == "unassigned":
        stmt = stmt.where(ExceptionCase.assignee_user_id.is_(None))
    now = datetime.now(timezone.utc)
    due_soon_at = now + timedelta(hours=24)
    if sla_status == "overdue":
        stmt = stmt.where(ExceptionCase.due_at.is_not(None), ExceptionCase.due_at < now)
    elif sla_status == "due_soon":
        stmt = stmt.where(ExceptionCase.due_at >= now, ExceptionCase.due_at <= due_soon_at)
    elif sla_status == "on_track":
        stmt = stmt.where(ExceptionCase.due_at > due_soon_at)
    elif sla_status == "no_due_date":
        stmt = stmt.where(ExceptionCase.due_at.is_(None))
    if rule_code:
        stmt = stmt.where(ExceptionCase.rule_code == rule_code.strip())
    if source_batch_kind is not None:
        stmt = stmt.where(ExceptionCase.source_batch_kind == source_batch_kind)
    if source_batch_id is not None:
        stmt = stmt.where(ExceptionCase.source_batch_id == source_batch_id)
    elif source_batch_unassigned:
        stmt = stmt.where(ExceptionCase.source_batch_id.is_(None))
    if occurrence_type:
        stmt = stmt.where(ExceptionCase.occurrence_type == occurrence_type)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ExceptionCase.case_no.ilike(like),
                ExceptionCase.title.ilike(like),
                ExceptionCase.resource_code.ilike(like),
                ExceptionCase.resource_name.ilike(like),
                ExceptionCase.reason.ilike(like),
            )
        )
    filtered = stmt.order_by(None).subquery()
    total = db.scalar(select(func.count()).select_from(filtered)) or 0
    rows = list(
        db.scalars(
            stmt.order_by(
                sql_case(
                    (ExceptionCase.status.in_(("open", "action_required", "blocked")), 0),
                    (ExceptionCase.status == "processing", 1),
                    else_=2,
                ),
                sql_case(
                    (ExceptionCase.severity == "critical", 0),
                    (ExceptionCase.severity == "high", 1),
                    else_=2,
                ),
                ExceptionCase.last_seen_at.desc(),
                ExceptionCase.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return {
        "items": serialize_cases(db, rows, current_user_id=current_user.id),
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/exceptions/aggregations", response_model=ExceptionAggregationResponse)
def exception_aggregations(
    group_by: str = Query(pattern="^(rule|batch)$"),
    domain: str | None = Query(default=None, pattern=CASE_DOMAIN_PATTERN),
    severity: str | None = Query(default=None, pattern="^(warning|high|critical)$"),
    case_status: str | None = Query(default=None, alias="status", pattern="^(open|action_required|processing|blocked|resolved|ignored)$"),
    occurrence_type: str | None = Query(default=None, pattern="^(baseline|new|reopened)$"),
    assignee_user_id: int | None = None,
    assignment: str | None = Query(default=None, pattern="^(mine|assigned|unassigned)$"),
    sla_status: str | None = Query(default=None, pattern="^(overdue|due_soon|on_track|no_due_date)$"),
    rule_code: str | None = Query(default=None, max_length=160),
    source_batch_kind: str | None = Query(default=None, pattern="^(import|inventory_check|legacy)$"),
    source_batch_id: int | None = Query(default=None, ge=1),
    source_batch_unassigned: bool = False,
    q: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.view")),
) -> dict[str, Any]:
    _validate_source_batch_filter(source_batch_kind, source_batch_id, source_batch_unassigned)
    stmt = scoped_exception_stmt(db, current_user)
    if domain:
        stmt = stmt.where(ExceptionCase.domain == domain)
    if severity:
        stmt = stmt.where(ExceptionCase.severity == severity)
    if case_status:
        stmt = stmt.where(ExceptionCase.status == case_status)
    if assignee_user_id is not None:
        stmt = stmt.where(ExceptionCase.assignee_user_id == assignee_user_id)
    if occurrence_type:
        stmt = stmt.where(ExceptionCase.occurrence_type == occurrence_type)
    if assignment == "mine":
        stmt = stmt.where(ExceptionCase.assignee_user_id == current_user.id)
    elif assignment == "assigned":
        stmt = stmt.where(ExceptionCase.assignee_user_id.is_not(None))
    elif assignment == "unassigned":
        stmt = stmt.where(ExceptionCase.assignee_user_id.is_(None))
    now = datetime.now(timezone.utc)
    due_soon_at = now + timedelta(hours=24)
    if sla_status == "overdue":
        stmt = stmt.where(ExceptionCase.due_at.is_not(None), ExceptionCase.due_at < now)
    elif sla_status == "due_soon":
        stmt = stmt.where(ExceptionCase.due_at >= now, ExceptionCase.due_at <= due_soon_at)
    elif sla_status == "on_track":
        stmt = stmt.where(ExceptionCase.due_at > due_soon_at)
    elif sla_status == "no_due_date":
        stmt = stmt.where(ExceptionCase.due_at.is_(None))
    if rule_code:
        stmt = stmt.where(ExceptionCase.rule_code == rule_code.strip())
    if source_batch_kind is not None:
        stmt = stmt.where(ExceptionCase.source_batch_kind == source_batch_kind)
    if source_batch_id is not None:
        stmt = stmt.where(ExceptionCase.source_batch_id == source_batch_id)
    elif source_batch_unassigned:
        stmt = stmt.where(ExceptionCase.source_batch_id.is_(None))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ExceptionCase.case_no.ilike(like),
                ExceptionCase.title.ilike(like),
                ExceptionCase.resource_code.ilike(like),
                ExceptionCase.resource_name.ilike(like),
                ExceptionCase.reason.ilike(like),
            )
        )
    filtered = stmt.order_by(None).subquery()
    metric_columns = (
        func.count(),
        func.sum(sql_case((filtered.c.severity == "critical", 1), else_=0)),
        func.sum(sql_case((filtered.c.severity == "high", 1), else_=0)),
        func.sum(sql_case((filtered.c.severity == "warning", 1), else_=0)),
        func.sum(
            sql_case(
                (
                    (filtered.c.due_at.is_not(None))
                    & (filtered.c.due_at < now)
                    & filtered.c.status.notin_(("resolved", "ignored")),
                    1,
                ),
                else_=0,
            )
        ),
    )
    if group_by == "rule":
        group_column = filtered.c.rule_code
        aggregate_stmt = select(group_column, *metric_columns).where(group_column.is_not(None)).group_by(group_column)
        ordered_stmt = aggregate_stmt.order_by(
            func.count().desc(),
            group_column,
        )
    else:
        batch_id_column = filtered.c.source_batch_id
        batch_kind_column = sql_case(
            (batch_id_column.is_(None), "unassigned"),
            else_=func.coalesce(filtered.c.source_batch_kind, "legacy"),
        )
        aggregate_stmt = select(batch_kind_column, batch_id_column, *metric_columns).group_by(
            batch_kind_column,
            batch_id_column,
        )
        # Keep the unassigned bucket visible even when more than 200 concrete
        # batches exist; it is an operational drill-down, not an optional tail.
        ordered_stmt = aggregate_stmt.order_by(
            sql_case((batch_id_column.is_(None), 0), else_=1),
            func.count().desc(),
            batch_kind_column,
            batch_id_column,
        )
    group_total = int(db.scalar(select(func.count()).select_from(aggregate_stmt.order_by(None).subquery())) or 0)
    rows = db.execute(ordered_stmt.limit(AGGREGATION_GROUP_LIMIT)).all()
    groups = []
    for row in rows:
        if group_by == "rule":
            raw_key, count, critical, high, warning, overdue = row
            batch_kind = None
            batch_id = None
            key_text = str(raw_key)
            label = key_text
        else:
            raw_kind, raw_batch_id, count, critical, high, warning, overdue = row
            unassigned_batch = raw_batch_id is None
            batch_kind = None if unassigned_batch else str(raw_kind)
            batch_id = None if unassigned_batch else int(raw_batch_id)
            key_text = "unassigned" if unassigned_batch else f"{batch_kind}:{batch_id}"
            label = (
                "未关联批次"
                if unassigned_batch
                else {
                    "import": f"导入批次 {batch_id}",
                    "inventory_check": f"库存核验批次 {batch_id}",
                    "legacy": f"历史批次 {batch_id}",
                }[batch_kind]
            )
        groups.append(
            {
                "key": key_text,
                "label": label,
                "source_batch_kind": batch_kind,
                "source_batch_id": batch_id,
                "count": int(count),
                "critical": int(critical or 0),
                "high": int(high or 0),
                "warning": int(warning or 0),
                "overdue": int(overdue or 0),
            }
        )
    return {
        "group_by": group_by,
        "groups": groups,
        "total": group_total,
        "truncated": group_total > len(groups),
    }


@router.get("/exceptions/rule-quality", response_model=ExceptionRuleQualityResponse)
def exception_rule_quality(
    domain: str | None = Query(default=None, pattern=CASE_DOMAIN_PATTERN),
    rule_code: str | None = Query(default=None, max_length=160),
    scan_window_days: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.policy_manage")),
) -> dict[str, Any]:
    return exception_rule_quality_summary(
        db,
        current_user,
        domain=domain,
        rule_code=rule_code.strip() if rule_code and rule_code.strip() else None,
        scan_window_days=scan_window_days,
    )


@router.get("/exceptions/{case_no}", response_model=ExceptionCaseDetail)
def exception_detail(
    case_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.view")),
) -> dict[str, Any]:
    case = _visible_case_or_404(db, current_user, case_no)
    payload = serialize_case(db, case, current_user_id=current_user.id)
    evidence = db.scalar(
        select(ExceptionEvidence).where(
            ExceptionEvidence.case_id == case.id,
            ExceptionEvidence.evidence_version == case.evidence_version,
        )
    )
    diagnoses = list(db.scalars(select(ExceptionDiagnosis).where(ExceptionDiagnosis.case_id == case.id).order_by(ExceptionDiagnosis.diagnosed_at.desc())).all())
    active_job = db.scalar(
        select(ExceptionDiagnosisJob)
        .where(
            ExceptionDiagnosisJob.case_id == case.id,
            ExceptionDiagnosisJob.evidence_version == case.evidence_version,
            ExceptionDiagnosisJob.status.in_(("queued", "processing")),
        )
        .order_by(ExceptionDiagnosisJob.id.desc())
        .limit(1)
    )
    actions = list(db.scalars(select(ExceptionAction).where(ExceptionAction.case_id == case.id).order_by(ExceptionAction.id.desc())).all())
    events = list(db.scalars(select(ExceptionEvent).where(ExceptionEvent.case_id == case.id).order_by(ExceptionEvent.created_at.desc(), ExceptionEvent.id.desc())).all())
    payload.update(
        {
            "evidence": evidence.data_json if evidence else None,
            "diagnoses": serialize_diagnoses(db, diagnoses),
            "active_diagnosis_job": serialize_job(active_job, case.case_no) if active_job else None,
            "actions": [serialize_action(row, case.case_no) for row in actions],
            "events": [
                {
                    "id": row.id,
                    "event_type": row.event_type,
                    "actor_user_id": row.actor_user_id,
                    "from_status": row.from_status,
                    "to_status": row.to_status,
                    "detail": row.detail_json or {},
                    "created_at": row.created_at,
                }
                for row in events
            ],
        }
    )
    return payload


@router.post("/exceptions/{case_no}/diagnoses", response_model=DiagnosisJobResponse, status_code=status.HTTP_202_ACCEPTED)
def request_diagnosis(
    case_no: str,
    body: DiagnosisRequest,
    db: Session = Depends(get_db),
    feature_enabled: None = Depends(require_exception_ai_enabled),
    current_user: User = Depends(require_permission("exception_center.diagnose")),
) -> dict[str, Any]:
    # Do not hold a case row lock while the deterministic refresh acquires the
    # global scan advisory lock. The case is locked and revalidated afterwards.
    case = _visible_case_or_404(db, current_user, case_no)
    case_domain = case.domain
    if case.domain not in AI_DIAGNOSIS_DOMAINS:
        raise _diagnosis_not_supported_error(case)
    manual_budget = ai_budget_status(db, trigger_type="manual")
    if not manual_budget["policy_enabled"] or not manual_budget["enabled"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "exception_manual_ai_disabled",
                "message": "Manual exception diagnosis is disabled by policy",
                "module": "exceptions",
                "case_no": case.case_no,
                "retryable": False,
                "action_path": f"/exceptions?open={case.case_no}",
            },
        )
    if not manual_budget["available"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "exception_manual_ai_daily_limit_reached",
                "message": "Manual exception diagnosis daily limit reached",
                "module": "exceptions",
                "case_no": case.case_no,
                "retryable": True,
                "action_path": f"/exceptions?open={case.case_no}",
            },
        )
    # Refresh deterministic evidence before spending model budget. The latest
    # source batch may have changed since this case was first detected.
    sync_exception_cases(db, domains={case_domain}, **exception_case_sync_target(case))
    case = _visible_case_for_update_or_404(db, current_user, case_no)
    if case.status == "resolved":
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "exception_already_resolved",
                "message": "最新确定性复检已不再发现该异常，无需发起智能诊断。",
                "module": "exceptions",
                "resource_type": case.resource_type,
                "resource_id": case.resource_id,
                "case_no": case.case_no,
                "action_path": f"/exceptions?open={case.case_no}",
            },
        )
    job, reused = create_diagnosis_job(db, case, current_user.id, force=body.force)
    db.commit()
    db.refresh(job)
    return serialize_job(job, case.case_no, reused)


@router.get("/exception-jobs/page", response_model=ExceptionJobPage)
def diagnosis_jobs_page(
    job_kind: str = Query(default="diagnosis", pattern="^(all|diagnosis|background)$"),
    job_status: str | None = Query(default=None, alias="status", pattern="^(queued|processing|completed|failed|cancelled)$"),
    trigger_type: str | None = Query(default=None, pattern="^(manual|scheduled)$"),
    case_no: str | None = Query(default=None, max_length=120),
    requested_by_user_id: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.policy_manage")),
) -> dict[str, Any]:
    visible = scoped_exception_stmt(db, current_user).with_only_columns(ExceptionCase.id).subquery()
    diagnosis_stmt = (
        select(ExceptionDiagnosisJob, ExceptionCase)
        .join(ExceptionCase, ExceptionCase.id == ExceptionDiagnosisJob.case_id)
        .where(ExceptionDiagnosisJob.case_id.in_(select(visible.c.id)))
    )
    if job_status:
        diagnosis_stmt = diagnosis_stmt.where(ExceptionDiagnosisJob.status == job_status)
    if trigger_type:
        diagnosis_stmt = diagnosis_stmt.where(ExceptionDiagnosisJob.trigger_type == trigger_type)
    if case_no:
        diagnosis_stmt = diagnosis_stmt.where(ExceptionCase.case_no == case_no.strip())
    if requested_by_user_id is not None:
        diagnosis_stmt = diagnosis_stmt.where(ExceptionDiagnosisJob.requested_by_user_id == requested_by_user_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        diagnosis_stmt = diagnosis_stmt.where(
            or_(
                ExceptionDiagnosisJob.job_no.ilike(like),
                ExceptionCase.case_no.ilike(like),
                ExceptionCase.title.ilike(like),
                ExceptionCase.resource_code.ilike(like),
                ExceptionCase.resource_name.ilike(like),
            )
        )

    diagnosis_projection = diagnosis_stmt.with_only_columns(
        ExceptionDiagnosisJob.id.label("id"),
        ExceptionDiagnosisJob.job_no.label("job_no"),
        literal("diagnosis").label("job_kind"),
        literal("diagnosis").label("job_type"),
        ExceptionCase.case_no.label("case_no"),
        ExceptionDiagnosisJob.evidence_version.label("evidence_version"),
        ExceptionDiagnosisJob.trigger_type.label("trigger_type"),
        ExceptionDiagnosisJob.status.label("status"),
        ExceptionDiagnosisJob.attempts.label("attempts"),
        ExceptionDiagnosisJob.requested_by_user_id.label("requested_by_user_id"),
        literal(None).label("requested_by_name"),
        ExceptionDiagnosisJob.available_at.label("available_at"),
        ExceptionDiagnosisJob.lease_owner.label("lease_owner"),
        ExceptionDiagnosisJob.lease_expires_at.label("lease_expires_at"),
        ExceptionDiagnosisJob.cancel_requested_at.label("cancel_requested_at"),
        ExceptionDiagnosisJob.cancel_requested_by_user_id.label("cancel_requested_by_user_id"),
        ExceptionDiagnosisJob.error_message.label("error_message"),
        ExceptionDiagnosisJob.created_at.label("created_at"),
        ExceptionDiagnosisJob.updated_at.label("updated_at"),
        ExceptionDiagnosisJob.started_at.label("started_at"),
        ExceptionDiagnosisJob.completed_at.label("completed_at"),
    )

    background_stmt = select(ExceptionBackgroundJob)
    if job_status:
        background_stmt = background_stmt.where(ExceptionBackgroundJob.status == job_status)
    if trigger_type or case_no or requested_by_user_id is not None:
        background_stmt = background_stmt.where(False)
    if q and q.strip():
        like = f"%{q.strip()}%"
        background_stmt = background_stmt.where(
            or_(ExceptionBackgroundJob.job_no.ilike(like), ExceptionBackgroundJob.job_type.ilike(like))
        )
    background_projection = background_stmt.with_only_columns(
        ExceptionBackgroundJob.id.label("id"),
        ExceptionBackgroundJob.job_no.label("job_no"),
        literal("background").label("job_kind"),
        ExceptionBackgroundJob.job_type.label("job_type"),
        literal(None).label("case_no"),
        literal(None).label("evidence_version"),
        literal(None).label("trigger_type"),
        ExceptionBackgroundJob.status.label("status"),
        ExceptionBackgroundJob.attempts.label("attempts"),
        literal(None).label("requested_by_user_id"),
        literal(None).label("requested_by_name"),
        ExceptionBackgroundJob.available_at.label("available_at"),
        ExceptionBackgroundJob.lease_owner.label("lease_owner"),
        ExceptionBackgroundJob.lease_expires_at.label("lease_expires_at"),
        literal(None).label("cancel_requested_at"),
        literal(None).label("cancel_requested_by_user_id"),
        ExceptionBackgroundJob.error_message.label("error_message"),
        ExceptionBackgroundJob.created_at.label("created_at"),
        ExceptionBackgroundJob.updated_at.label("updated_at"),
        ExceptionBackgroundJob.started_at.label("started_at"),
        ExceptionBackgroundJob.completed_at.label("completed_at"),
    )

    if job_kind == "diagnosis":
        combined = diagnosis_projection
    elif job_kind == "background":
        combined = background_projection
    else:
        combined = union_all(diagnosis_projection, background_projection)
    jobs = combined.subquery()
    total = int(db.scalar(select(func.count()).select_from(jobs)) or 0)
    rows = db.execute(
        select(jobs)
        .order_by(jobs.c.created_at.desc(), jobs.c.job_kind, jobs.c.id.desc())
        .offset(offset)
        .limit(limit)
    ).mappings().all()
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/exception-jobs/{job_id}", response_model=DiagnosisJobResponse)
def diagnosis_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.diagnose")),
) -> dict[str, Any]:
    job = db.get(ExceptionDiagnosisJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diagnosis job not found")
    case = db.get(ExceptionCase, job.case_id)
    if case is None or not can_view_case(db, current_user, case):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diagnosis job not found")
    return serialize_job(job, case.case_no)


@router.post("/exception-jobs/{job_id}/retry", response_model=DiagnosisJobResponse)
def retry_diagnosis_job(
    job_id: int,
    body: ExceptionJobRetryRequest,
    db: Session = Depends(get_db),
    feature_enabled: None = Depends(require_exception_ai_enabled),
    current_user: User = Depends(require_permission("exception_center.policy_manage")),
) -> dict[str, Any]:
    job, case = _locked_diagnosis_job_and_case_or_404(db, current_user, job_id)
    if case.domain not in AI_DIAGNOSIS_DOMAINS:
        raise _diagnosis_not_supported_error(case)
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed or cancelled jobs can be retried")
    if case.status in {"resolved", "ignored"} or case.evidence_version != job.evidence_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The case or evidence is no longer retryable")
    active_job = db.scalar(
        select(ExceptionDiagnosisJob)
        .where(
            ExceptionDiagnosisJob.case_id == case.id,
            ExceptionDiagnosisJob.evidence_version == case.evidence_version,
            ExceptionDiagnosisJob.id != job.id,
            ExceptionDiagnosisJob.status.in_(("queued", "processing")),
        )
        .order_by(ExceptionDiagnosisJob.id.desc())
        .limit(1)
    )
    if active_job is not None:
        raise _active_diagnosis_job_conflict(case, active_job)
    budget = ai_budget_status(db, trigger_type="manual" if job.trigger_type == "manual" else "scheduled")
    if not budget["policy_enabled"] or not budget["enabled"]:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Diagnosis workflow is disabled")
    if not budget["available"]:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Diagnosis daily limit reached")
    previous_status = case.status
    try:
        with db.begin_nested():
            job.status = "queued"
            if body.reset_attempts:
                job.attempts = 0
            job.available_at = datetime.now(timezone.utc)
            job.lease_owner = None
            job.lease_expires_at = None
            job.started_at = None
            job.completed_at = None
            job.error_message = None
            job.cancel_requested_at = None
            job.cancel_requested_by_user_id = None
            db.flush()
    except IntegrityError as exc:
        active_job = db.scalar(
            select(ExceptionDiagnosisJob)
            .where(
                ExceptionDiagnosisJob.case_id == case.id,
                ExceptionDiagnosisJob.evidence_version == case.evidence_version,
                ExceptionDiagnosisJob.id != job.id,
                ExceptionDiagnosisJob.status.in_(("queued", "processing")),
            )
            .order_by(ExceptionDiagnosisJob.id.desc())
            .limit(1)
        )
        if active_job is not None:
            raise _active_diagnosis_job_conflict(case, active_job) from exc
        raise
    case.status = "processing"
    retry_reason = body.reason or "Manual diagnosis retry requested"
    db.add(
        ExceptionEvent(
            case_id=case.id,
            event_type="diagnosis_retried",
            actor_user_id=current_user.id,
            from_status=previous_status,
            to_status="processing",
            detail_json={"job_no": job.job_no, "reason": retry_reason, "reset_attempts": body.reset_attempts},
        )
    )
    db.commit()
    db.refresh(job)
    return serialize_job(job, case.case_no)


@router.post("/exception-jobs/{job_id}/cancel", response_model=DiagnosisJobResponse)
def cancel_diagnosis_job(
    job_id: int,
    body: ExceptionJobCancelRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.policy_manage")),
) -> dict[str, Any]:
    job, case = _locked_diagnosis_job_and_case_or_404(db, current_user, job_id)
    if job.status not in {"queued", "processing"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only queued or processing jobs can be cancelled")
    now = datetime.now(timezone.utc)
    job.cancel_requested_at = now
    job.cancel_requested_by_user_id = current_user.id
    job.error_message = body.reason
    # Cancellation is terminal immediately, including for an in-flight provider
    # call. The worker's post-call ownership check will discard that result.
    complete_cancelled_diagnosis_job(
        db,
        job,
        message=body.reason,
        audit_detail={"evidence_current": case.evidence_version == job.evidence_version},
    )
    db.commit()
    db.refresh(job)
    return serialize_job(job, case.case_no)


@router.get("/exception-diagnoses/quality", response_model=ExceptionDiagnosisQualitySummary)
def exception_diagnosis_quality(
    domain: str | None = Query(default=None, pattern="^(inventory|receivable|master_data|import)$"),
    rule_code: str | None = Query(default=None, max_length=160),
    diagnosed_from: datetime | None = None,
    diagnosed_to: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.policy_manage")),
) -> dict[str, Any]:
    if diagnosed_from and diagnosed_to and diagnosed_from > diagnosed_to:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid diagnosis date range")
    return diagnosis_quality_summary(
        db,
        current_user,
        domain=domain,
        rule_code=rule_code,
        diagnosed_from=diagnosed_from,
        diagnosed_to=diagnosed_to,
    )


@router.post("/exception-diagnoses/{diagnosis_id}/feedback", response_model=ExceptionDiagnosisResponse)
def submit_diagnosis_feedback(
    diagnosis_id: int,
    body: DiagnosisFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.diagnose")),
) -> dict[str, Any]:
    diagnosis = db.get(ExceptionDiagnosis, diagnosis_id)
    if diagnosis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception diagnosis not found")
    case = db.get(ExceptionCase, diagnosis.case_id)
    if case is None or not can_view_case(db, current_user, case):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception diagnosis not found")
    previous_rating = diagnosis.feedback_rating
    previous_note = diagnosis.feedback_note
    diagnosis.feedback_rating = body.rating
    diagnosis.feedback_note = body.note
    diagnosis.feedback_by_user_id = current_user.id
    diagnosis.feedback_at = datetime.now(timezone.utc)
    db.add(
        ExceptionEvent(
            case_id=case.id,
            event_type="diagnosis_feedback",
            actor_user_id=current_user.id,
            detail_json={
                "diagnosis_id": diagnosis.id,
                "rating": body.rating,
                "note": body.note,
                "previous_rating": previous_rating,
                "previous_note": previous_note,
                "evidence_version": diagnosis.evidence_version,
            },
        )
    )
    db.commit()
    db.refresh(diagnosis)
    return serialize_diagnoses(db, [diagnosis])[0]


@router.post("/exceptions/{case_no}/actions/validate", response_model=ActionResponse)
def validate_exception_action(
    case_no: str,
    body: ActionValidationRequest,
    db: Session = Depends(get_db),
    feature_enabled: None = Depends(require_exception_actions_enabled),
    high_risk_enabled: None = Depends(require_exception_high_risk_actions_enabled),
    current_user: User = Depends(require_permission("exception_center.action_execute")),
) -> dict[str, Any]:
    case = _visible_case_for_update_or_404(db, current_user, case_no)
    action, token = validate_action(db, case, body.action_type, body.parameters, current_user)
    if controlled_actions_enabled():
        mirror_exception_action_validation(db, action, case, current_user)
    db.commit()
    db.refresh(action)
    return serialize_action(action, case.case_no, token=token)


@router.post("/exceptions/{case_no}/actions", response_model=ActionResponse)
def execute_exception_action(
    case_no: str,
    body: ActionExecuteRequest,
    db: Session = Depends(get_db),
    feature_enabled: None = Depends(require_exception_actions_enabled),
    high_risk_enabled: None = Depends(require_exception_high_risk_actions_enabled),
    current_user: User = Depends(require_permission("exception_center.action_execute")),
) -> dict[str, Any]:
    # execute_action owns the scan-advisory-lock -> case-row-lock ordering and
    # performs its own second authorization and token validation under lock.
    case = _visible_case_or_404(db, current_user, case_no)
    action = execute_action(db, case, body.validation_token, body.idempotency_key, current_user)
    if controlled_actions_enabled():
        proposal = mirror_exception_action_validation(db, action, case, current_user)
        mirror_exception_action_execution(
            db,
            action,
            proposal,
            current_user,
            body.idempotency_key,
        )
    db.commit()
    db.refresh(action)
    return serialize_action(action, case.case_no)


@router.get("/exception-actions/{action_id}", response_model=ActionResponse)
def exception_action(
    action_id: int,
    db: Session = Depends(get_db),
    feature_enabled: None = Depends(require_exception_actions_enabled),
    current_user: User = Depends(require_permission("exception_center.action_execute")),
) -> dict[str, Any]:
    action = db.get(ExceptionAction, action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception action not found")
    case = db.get(ExceptionCase, action.case_id)
    if case is None or not can_view_case(db, current_user, case):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception action not found")
    return serialize_action(action, case.case_no)


@router.post("/exceptions/batch/assign", response_model=BatchExceptionMutationResponse)
def batch_assign_exceptions(
    body: BatchAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.manage")),
) -> dict[str, Any]:
    update_assignee = "assignee_user_id" in body.model_fields_set
    update_due_at = "due_at" in body.model_fields_set
    if not update_assignee and not update_due_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="assignee_user_id or due_at must be provided",
        )
    acquire_exception_case_mutation_lock(db)
    cases = _visible_cases_or_404(db, current_user, body.case_nos)
    _validate_case_statuses(cases, ASSIGNABLE_CASE_STATUSES, "assignment")
    if update_assignee:
        _validate_assignee(db, body.assignee_user_id, cases)
    _assign_cases(
        db,
        cases,
        assignee_user_id=body.assignee_user_id,
        due_at=body.due_at,
        actor_user_id=current_user.id,
        is_batch=True,
        update_assignee=update_assignee,
        update_due_at=update_due_at,
    )
    db.commit()
    return {"updated_count": len(cases), "items": serialize_cases(db, cases)}


@router.post("/exceptions/batch/ignore", response_model=BatchExceptionMutationResponse)
def batch_ignore_exceptions(
    body: BatchIgnoreRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.manage")),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    ignored_until = body.ignored_until if body.ignored_until.tzinfo else body.ignored_until.replace(tzinfo=timezone.utc)
    if ignored_until <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ignored_until must be in the future")
    acquire_exception_case_mutation_lock(db)
    cases = _visible_cases_or_404(db, current_user, body.case_nos)
    _validate_case_statuses(cases, IGNORABLE_CASE_STATUSES, "ignore")
    _ignore_cases(
        db,
        cases,
        reason=body.reason.strip(),
        ignored_until=ignored_until,
        actor_user_id=current_user.id,
        is_batch=True,
    )
    db.commit()
    return {"updated_count": len(cases), "items": serialize_cases(db, cases)}


@router.post("/exceptions/{case_no}/assign", response_model=ExceptionCaseItem)
def assign_exception(
    case_no: str,
    body: AssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.manage")),
) -> dict[str, Any]:
    acquire_exception_case_mutation_lock(db)
    case = _visible_case_for_update_or_404(db, current_user, case_no)
    _validate_case_statuses([case], ASSIGNABLE_CASE_STATUSES, "assignment")
    update_assignee = "assignee_user_id" in body.model_fields_set
    update_due_at = "due_at" in body.model_fields_set
    if not update_assignee and not update_due_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="assignee_user_id or due_at must be provided",
        )
    if update_assignee:
        _validate_assignee(db, body.assignee_user_id, [case])
    _assign_cases(
        db,
        [case],
        assignee_user_id=body.assignee_user_id,
        due_at=body.due_at,
        actor_user_id=current_user.id,
        is_batch=False,
        update_assignee=update_assignee,
        update_due_at=update_due_at,
    )
    db.commit()
    db.refresh(case)
    return serialize_case(db, case, current_user_id=current_user.id)


@router.post("/exceptions/{case_no}/ignore", response_model=ExceptionCaseItem)
def ignore_exception(
    case_no: str,
    body: IgnoreRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.manage")),
) -> dict[str, Any]:
    acquire_exception_case_mutation_lock(db)
    case = _visible_case_for_update_or_404(db, current_user, case_no)
    _validate_case_statuses([case], IGNORABLE_CASE_STATUSES, "ignore")
    now = datetime.now(timezone.utc)
    ignored_until = body.ignored_until if body.ignored_until.tzinfo else body.ignored_until.replace(tzinfo=timezone.utc)
    if ignored_until <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ignored_until must be in the future")
    _ignore_cases(
        db,
        [case],
        reason=body.reason.strip(),
        ignored_until=ignored_until,
        actor_user_id=current_user.id,
        is_batch=False,
    )
    db.commit()
    db.refresh(case)
    return serialize_case(db, case, current_user_id=current_user.id)


@router.post("/exceptions/{case_no}/verify", response_model=VerifyResponse)
def verify_exception(
    case_no: str,
    body: VerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.manage")),
) -> dict[str, Any]:
    # Compare the caller's snapshot before scanning without taking a row lock.
    # sync_exception_cases owns the advisory scan lock; only after that lock is
    # acquired do we lock and revalidate the case before writing verification.
    case = _visible_case_or_404(db, current_user, case_no)
    if body.expected_evidence_version != case.evidence_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "exception_evidence_version_conflict",
                "message": "The exception evidence changed; reload the case before verifying",
                "module": "exceptions",
                "case_no": case.case_no,
                "resource_type": case.resource_type,
                "resource_id": case.resource_id,
                "retryable": True,
                "action_path": f"/exceptions?open={case.case_no}",
                "expected_evidence_version": body.expected_evidence_version,
                "current_evidence_version": case.evidence_version,
            },
        )
    before = {
        "status": case.status,
        "evidence_version": case.evidence_version,
        "affected_rows": case.affected_rows,
        "affected_amount": case.affected_amount,
        "affected_quantity": case.affected_quantity,
        "summary": case.reason,
    }
    scan_result = sync_exception_cases(
        db,
        domains={case.domain},
        scan_trigger="verification",
        **exception_case_sync_target(case),
    )
    case = db.scalar(
        select(ExceptionCase)
        .where(ExceptionCase.id == case.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if case is None or not can_view_case(db, current_user, case):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception case not found")
    if body.expected_evidence_version != case.evidence_version:
        # Keep the deterministic refresh, but never apply a verification based
        # on a snapshot that changed while the request was running.
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "exception_evidence_version_conflict",
                "message": "The exception evidence changed during verification; reload the case before retrying",
                "module": "exceptions",
                "case_no": case.case_no,
                "resource_type": case.resource_type,
                "resource_id": case.resource_id,
                "retryable": True,
                "action_path": f"/exceptions?open={case.case_no}",
                "expected_evidence_version": body.expected_evidence_version,
                "current_evidence_version": case.evidence_version,
            },
        )
    note = body.note.strip() if body.note else None
    if case.status != "resolved":
        previous = case.status
        if case.status == "ignored":
            ignored_until = case.ignored_until
            comparison_now = (
                datetime.now(timezone.utc).replace(tzinfo=None)
                if ignored_until is not None and ignored_until.tzinfo is None
                else datetime.now(timezone.utc)
            )
            keep_ignored = ignored_until is not None and ignored_until > comparison_now
            next_status = "ignored" if keep_ignored else "action_required"
        else:
            next_status = VERIFY_STILL_PRESENT_STATUS_TRANSITIONS.get(case.status, "action_required")
        case.status = next_status
        if next_status == "action_required":
            case.resolution_note = note or "复核后异常仍然存在。"
        outcome = "still_present"
    else:
        previous = before["status"]
        case.verified_at = datetime.now(timezone.utc)
        if note:
            case.resolution_note = note
        outcome = "resolved"
    after = {
        "status": case.status,
        "evidence_version": case.evidence_version,
        "affected_rows": case.affected_rows,
        "affected_amount": case.affected_amount,
        "affected_quantity": case.affected_quantity,
        "summary": case.reason,
    }
    evidence_changed = before["evidence_version"] != after["evidence_version"]
    db.add(
        ExceptionEvent(
            case_id=case.id,
            event_type="verified" if outcome == "resolved" else "verification_failed",
            actor_user_id=current_user.id,
            from_status=previous,
            to_status=case.status,
            detail_json=jsonable_encoder({
                "note": note,
                "expected_evidence_version": body.expected_evidence_version,
                "expected_outcome": body.expected_outcome,
                "observed_result": body.observed_result,
                "before": before,
                "after": after,
                "evidence_changed": evidence_changed,
                "status_preserved": outcome == "still_present" and before["status"] == case.status,
                "scan_result": scan_result,
            }),
        )
    )
    db.commit()
    db.refresh(case)
    return {
        "case": serialize_case(db, case, current_user_id=current_user.id),
        "resolved": outcome == "resolved",
        "before": before,
        "after": after,
        "note": note,
        "evidence_changed": evidence_changed,
        "scan_result": scan_result,
    }


@router.post("/exceptions/scan")
def scan_exceptions(
    domains: list[str] | None = Query(default=None),
    source_batch_kind: str | None = Query(default=None, pattern="^(import|inventory_check|legacy)$"),
    source_batch_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.manage")),
) -> dict[str, Any]:
    _validate_source_batch_filter(source_batch_kind, source_batch_id, False)
    selected_domains = set(domains) if domains else None
    if not can_run_global_exception_scan(db, current_user, selected_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "exception_global_scan_scope_required",
                "message": "Global exception scans require every source permission and unrestricted data scope",
                "module": "exceptions",
                "retryable": False,
                "action_path": "/exceptions",
            },
        )
    requested_domains = selected_domains or set(exception_domain_modes(db))
    baseline_pending_domains = exception_shadow_baseline_pending_domains(db, requested_domains)
    if baseline_pending_domains:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "exception_baseline_required",
                "message": "Complete the controlled baseline before running a regular scan for shadow domains",
                "module": "exceptions",
                "domains": sorted(baseline_pending_domains),
                "retryable": False,
                "action_path": "/exceptions?view=operations",
            },
        )
    try:
        result = sync_exception_cases(
            db,
            domains=selected_domains,
            source_batch_id=source_batch_id,
            source_batch_kind=source_batch_kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return result


@router.post("/exceptions/baseline-scan", response_model=ExceptionBaselineScanResponse)
def baseline_scan_exceptions(
    body: ExceptionBaselineScanRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.policy_manage")),
) -> dict[str, Any]:
    acquire_exception_case_mutation_lock(db)
    default_policy(db)
    policy = db.scalar(
        select(ExceptionPolicy)
        .where(ExceptionPolicy.policy_key == "default")
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception policy not found")
    if _utc_policy_timestamp(body.expected_policy_updated_at) != _utc_policy_timestamp(policy.updated_at):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "exception_policy_version_conflict",
                "message": "The exception policy changed; reload it before running the baseline scan",
                "module": "exceptions",
                "retryable": True,
                "action_path": "/exceptions?view=operations",
                "expected_updated_at": body.expected_policy_updated_at.isoformat(),
                "current_updated_at": policy.updated_at.isoformat(),
            },
        )
    domain_modes = exception_domain_modes(db)
    domain_mode = domain_modes.get(body.domain, "off")
    if domain_mode != "shadow":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "exception_baseline_requires_shadow_domain",
                "message": "A controlled baseline scan is only available while the domain is in shadow mode",
                "module": "exceptions",
                "domain": body.domain,
                "domain_mode": domain_mode,
                "retryable": False,
                "action_path": "/exceptions?view=operations",
            },
        )
    if not can_run_global_exception_scan(db, current_user, {body.domain}):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "exception_global_scan_scope_required",
                "message": "Baseline scans require every source permission and unrestricted data scope",
                "module": "exceptions",
                "domain": body.domain,
                "retryable": False,
                "action_path": "/exceptions?view=operations",
            },
        )
    policy_settings = dict(policy.settings_json or {})
    rollout = (
        dict(policy_settings.get("domain_rollout") or {})
        if isinstance(policy_settings.get("domain_rollout"), dict)
        else {}
    )
    rollout_state = (
        dict(rollout.get(body.domain) or {})
        if isinstance(rollout.get(body.domain), dict)
        else {}
    )
    try:
        shadow_cycle = max(1, int(rollout_state.get("shadow_cycle") or 1))
    except (TypeError, ValueError):
        shadow_cycle = 1
    if rollout_state.get("baseline_completed_at"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "exception_baseline_already_completed",
                "message": "The controlled baseline scan has already completed for this shadow cycle",
                "module": "exceptions",
                "domain": body.domain,
                "shadow_cycle": shadow_cycle,
                "baseline_audit_id": rollout_state.get("baseline_audit_id"),
                "scan_reference": rollout_state.get("baseline_scan_reference"),
                "baseline_completed_at": rollout_state.get("baseline_completed_at"),
                "retryable": False,
                "action_path": "/exceptions?view=operations",
            },
        )
    if not rollout_state.get("shadow_started_at"):
        legacy_audit = db.scalar(
            select(AuditLog)
            .where(
                AuditLog.action_type == BASELINE_SCAN_AUDIT_ACTION,
                AuditLog.resource_type == "exception_domain",
                AuditLog.resource_id == body.domain,
            )
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
        legacy_baseline_cases = int(
            db.scalar(
                select(func.count())
                .select_from(ExceptionCase)
                .where(
                    ExceptionCase.domain == body.domain,
                    ExceptionCase.occurrence_type == "baseline",
                )
            )
            or 0
        )
        if legacy_audit is not None or legacy_baseline_cases:
            legacy_result = (
                legacy_audit.after_data
                if legacy_audit is not None and isinstance(legacy_audit.after_data, dict)
                else {}
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "exception_baseline_already_completed",
                    "message": "A legacy baseline marker already exists for this shadow domain",
                    "module": "exceptions",
                    "domain": body.domain,
                    "shadow_cycle": shadow_cycle,
                    "baseline_audit_id": legacy_audit.id if legacy_audit else None,
                    "scan_reference": legacy_result.get("scan_reference"),
                    "baseline_case_count": legacy_baseline_cases,
                    "retryable": False,
                    "action_path": "/exceptions?view=operations",
                },
            )
        rollout_state.update(
            {
                "mode": "shadow",
                "shadow_cycle": shadow_cycle,
                "shadow_started_at": policy.updated_at.isoformat(),
                "shadow_started_by_user_id": current_user.id,
            }
        )
    try:
        raw_result = sync_exception_cases(
            db,
            domains={body.domain},
            scan_trigger="baseline",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    result = _baseline_scan_result(body.domain, raw_result)
    scan_reference = f"baseline:{body.domain}:{uuid4().hex}"
    completed_at = datetime.now(timezone.utc)
    rollout_state.update(
        {
            "mode": "shadow",
            "shadow_cycle": shadow_cycle,
            "baseline_completed_at": completed_at.isoformat(),
            "baseline_completed_by_user_id": current_user.id,
            "baseline_scan_reference": scan_reference,
            "baseline_result_summary": result,
        }
    )
    rollout[body.domain] = rollout_state
    policy_settings["domain_rollout"] = rollout
    policy.settings_json = policy_settings
    policy.updated_by_user_id = current_user.id
    policy.updated_at = completed_at
    db.flush()
    audit = write_audit_log(
        db,
        action_type=BASELINE_SCAN_AUDIT_ACTION,
        resource_type="exception_domain",
        resource_id=body.domain,
        user=current_user,
        request=request,
        before_data=jsonable_encoder(
            {
                "domain": body.domain,
                "domain_mode": domain_mode,
                "shadow_cycle": shadow_cycle,
                "expected_policy_updated_at": body.expected_policy_updated_at,
                "current_policy_updated_at": body.expected_policy_updated_at,
            }
        ),
        after_data=jsonable_encoder(
            {
                "scan_reference": scan_reference,
                "domain": body.domain,
                "domain_mode": domain_mode,
                "shadow_cycle": shadow_cycle,
                "policy_updated_at": policy.updated_at,
                "result": result,
            }
        ),
    )
    db.flush()
    rollout_state_with_audit = dict(rollout_state)
    rollout_state_with_audit["baseline_audit_id"] = audit.id
    rollout_with_audit = dict(rollout)
    rollout_with_audit[body.domain] = rollout_state_with_audit
    policy_settings_with_audit = dict(policy_settings)
    policy_settings_with_audit["domain_rollout"] = rollout_with_audit
    policy.settings_json = policy_settings_with_audit
    db.flush()
    response = {
        "scan_reference": scan_reference,
        "audit_id": audit.id,
        "domain": body.domain,
        "domain_mode": "shadow",
        "shadow_cycle": shadow_cycle,
        "policy_updated_at": policy.updated_at,
        "reused": False,
        "result": result,
    }
    db.commit()
    return response


@router.get("/exception-notifications", response_model=list[NotificationItem])
def exception_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.view")),
) -> list[dict[str, Any]]:
    stmt = select(ExceptionNotification).where(
        ExceptionNotification.user_id == current_user.id,
        ExceptionNotification.archived_at.is_(None),
    )
    if unread_only:
        stmt = stmt.where(ExceptionNotification.is_read.is_(False))
    rows = list(db.scalars(stmt.order_by(ExceptionNotification.created_at.desc()).limit(limit)).all())
    result = []
    for row in rows:
        case = db.get(ExceptionCase, row.case_id)
        if case is None or not can_view_case(db, current_user, case):
            continue
        result.append(
            {
                "id": row.id,
                "case_no": case.case_no,
                "notification_type": row.notification_type,
                "title": row.title,
                "message": row.message,
                "is_read": row.is_read,
                "read_at": row.read_at,
                "acknowledged_at": row.acknowledged_at,
                "created_at": row.created_at,
            }
        )
    return result


@router.post("/exception-notifications/{notification_id}/read", response_model=NotificationItem)
def read_exception_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.view")),
) -> dict[str, Any]:
    row = db.get(ExceptionNotification, notification_id)
    if row is None or row.user_id != current_user.id or row.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    case = db.get(ExceptionCase, row.case_id)
    if case is None or not can_view_case(db, current_user, case):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    row.is_read = True
    row.read_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "case_no": case.case_no,
        "notification_type": row.notification_type,
        "title": row.title,
        "message": row.message,
        "is_read": row.is_read,
        "read_at": row.read_at,
        "acknowledged_at": row.acknowledged_at,
        "created_at": row.created_at,
    }


@router.post("/exception-notifications/{notification_id}/acknowledge", response_model=NotificationItem)
def acknowledge_exception_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.view")),
) -> dict[str, Any]:
    row = db.get(ExceptionNotification, notification_id)
    if row is None or row.user_id != current_user.id or row.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    case = db.get(ExceptionCase, row.case_id)
    if case is None or not can_view_case(db, current_user, case):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    now = datetime.now(timezone.utc)
    row.is_read = True
    row.read_at = row.read_at or now
    row.acknowledged_at = now
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "case_no": case.case_no,
        "notification_type": row.notification_type,
        "title": row.title,
        "message": row.message,
        "is_read": row.is_read,
        "read_at": row.read_at,
        "acknowledged_at": row.acknowledged_at,
        "created_at": row.created_at,
    }


@router.get("/exception-policies", response_model=PolicyResponse)
def get_exception_policy(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.policy_manage")),
) -> dict[str, Any]:
    row = default_policy(db)
    db.commit()
    db.refresh(row)
    return _policy_payload(row)


@router.put("/exception-policies", response_model=PolicyResponse)
def update_exception_policy(
    body: PolicyUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.policy_manage")),
) -> dict[str, Any]:
    default_policy(db)
    row = db.scalar(
        select(ExceptionPolicy)
        .where(ExceptionPolicy.policy_key == "default")
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception policy not found")
    _apply_policy_changes(
        db,
        row,
        body.model_dump(),
        current_user=current_user,
        request=request,
    )
    db.commit()
    db.refresh(row)
    return _policy_payload(row)


@router.patch("/exception-policies", response_model=PolicyResponse)
def patch_exception_policy(
    body: PolicyPatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.policy_manage")),
) -> dict[str, Any]:
    default_policy(db)
    row = db.scalar(
        select(ExceptionPolicy)
        .where(ExceptionPolicy.policy_key == "default")
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception policy not found")
    if _utc_policy_timestamp(body.expected_updated_at) != _utc_policy_timestamp(row.updated_at):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "exception_policy_version_conflict",
                "message": "The exception policy changed; reload it before saving",
                "module": "exceptions",
                "retryable": True,
                "action_path": "/exceptions?view=operations",
                "expected_updated_at": body.expected_updated_at.isoformat(),
                "current_updated_at": row.updated_at.isoformat(),
            },
        )
    _apply_policy_changes(
        db,
        row,
        body.model_dump(exclude_unset=True, exclude={"expected_updated_at"}),
        current_user=current_user,
        request=request,
    )
    db.commit()
    db.refresh(row)
    return _policy_payload(row)


POLICY_MUTABLE_FIELDS = {
    "is_enabled",
    "manual_ai_enabled",
    "scheduled_ai_enabled",
    "full_scan_enabled",
    "digest_enabled",
    "full_scan_cron",
    "digest_cron",
    "ai_daily_limit",
    "ai_batch_limit",
    "manual_ai_daily_limit",
    "scheduled_ai_daily_limit",
    "scheduled_ai_batch_limit",
    "ai_concurrency",
    "stale_diagnosis_hours",
}


def _apply_policy_changes(
    db: Session,
    row: Any,
    changes: dict[str, Any],
    *,
    current_user: User,
    request: Request,
) -> None:
    before = _policy_payload(row)
    previous_modes = normalize_exception_domain_modes(row.settings_json)
    previous_settings = dict(row.settings_json or {})
    previous_rollout = (
        dict(previous_settings.get("domain_rollout") or {})
        if isinstance(previous_settings.get("domain_rollout"), dict)
        else {}
    )
    candidate_settings = dict(previous_settings)
    if "settings" in changes:
        candidate_settings = dict(changes["settings"])
        candidate_settings.pop("domain_modes", None)
        candidate_settings.pop("domain_rollout", None)
        candidate_settings["domain_modes"] = previous_modes
        if previous_rollout:
            candidate_settings["domain_rollout"] = previous_rollout
    if "domain_modes" in changes:
        candidate_settings["domain_modes"] = dict(changes["domain_modes"])
    candidate_modes = normalize_exception_domain_modes(candidate_settings)
    for domain in ("crm", "approval"):
        previous_mode = previous_modes[domain]
        next_mode = candidate_modes[domain]
        if next_mode != "visible" or previous_mode == "visible":
            continue
        rollout_state = (
            previous_rollout.get(domain)
            if isinstance(previous_rollout.get(domain), dict)
            else {}
        )
        if previous_mode != "shadow" or not rollout_state.get("baseline_completed_at"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "exception_baseline_required",
                    "message": "Complete the controlled baseline in the current shadow cycle before making the domain visible",
                    "module": "exceptions",
                    "domain": domain,
                    "current_mode": previous_mode,
                    "requested_mode": next_mode,
                    "shadow_cycle": rollout_state.get("shadow_cycle"),
                    "retryable": False,
                    "action_path": "/exceptions?view=operations",
                },
            )
    for field in POLICY_MUTABLE_FIELDS & changes.keys():
        setattr(row, field, changes[field])
    if "settings" in changes or "domain_modes" in changes:
        row.settings_json = candidate_settings
    next_modes = candidate_modes
    now = datetime.now(timezone.utc)
    if next_modes != previous_modes:
        next_settings = dict(row.settings_json or {})
        rollout = (
            dict(next_settings.get("domain_rollout") or {})
            if isinstance(next_settings.get("domain_rollout"), dict)
            else {}
        )
        for domain in ("crm", "approval"):
            previous_mode = previous_modes[domain]
            next_mode = next_modes[domain]
            if previous_mode == next_mode:
                continue
            state = dict(rollout.get(domain) or {}) if isinstance(rollout.get(domain), dict) else {}
            if next_mode == "shadow":
                try:
                    previous_cycle = max(0, int(state.get("shadow_cycle") or 0))
                except (TypeError, ValueError):
                    previous_cycle = 0
                state.update(
                    {
                        "mode": "shadow",
                        "shadow_cycle": previous_cycle + 1,
                        "shadow_started_at": now.isoformat(),
                        "shadow_started_by_user_id": current_user.id,
                    }
                )
                for key in (
                    "shadow_ended_at",
                    "baseline_completed_at",
                    "baseline_completed_by_user_id",
                    "baseline_audit_id",
                    "baseline_scan_reference",
                    "baseline_result_summary",
                ):
                    state.pop(key, None)
            elif previous_mode == "shadow":
                state.update(
                    {
                        "mode": next_mode,
                        "shadow_ended_at": now.isoformat(),
                    }
                )
            rollout[domain] = state
        next_settings["domain_rollout"] = rollout
        row.settings_json = next_settings
    row.updated_by_user_id = current_user.id
    row.updated_at = now
    db.flush()
    write_audit_log(
        db,
        action_type="update_exception_policy",
        resource_type="exception_policy",
        resource_id=row.policy_key,
        user=current_user,
        request=request,
        before_data=jsonable_encoder(before),
        after_data=jsonable_encoder(_policy_payload(row)),
    )


def _policy_payload(row) -> dict[str, Any]:  # noqa: ANN001
    return {
        "policy_key": row.policy_key,
        "is_enabled": row.is_enabled,
        "manual_ai_enabled": row.manual_ai_enabled,
        "scheduled_ai_enabled": row.scheduled_ai_enabled,
        "full_scan_enabled": row.full_scan_enabled,
        "digest_enabled": row.digest_enabled,
        "full_scan_cron": row.full_scan_cron,
        "digest_cron": row.digest_cron,
        "ai_daily_limit": row.ai_daily_limit,
        "ai_batch_limit": row.ai_batch_limit,
        "manual_ai_daily_limit": row.manual_ai_daily_limit,
        "scheduled_ai_daily_limit": row.scheduled_ai_daily_limit,
        "scheduled_ai_batch_limit": row.scheduled_ai_batch_limit,
        "ai_concurrency": row.ai_concurrency,
        "stale_diagnosis_hours": row.stale_diagnosis_hours,
        "domain_modes": normalize_exception_domain_modes(row.settings_json),
        "settings": row.settings_json or {},
        "updated_at": row.updated_at,
    }


def _utc_policy_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _active_diagnosis_job_conflict(
    case: ExceptionCase,
    active_job: ExceptionDiagnosisJob,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": "exception_active_diagnosis_exists",
            "message": "An active diagnosis already exists for the current evidence",
            "module": "exceptions",
            "case_no": case.case_no,
            "retryable": True,
            "action_path": f"/exceptions?open={case.case_no}",
            "active_job_id": active_job.id,
            "active_job_no": active_job.job_no,
        },
    )
