from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AiActionExecution,
    AiActionProposal,
    AiSecurityEvent,
    CrmProject,
    CrmProjectCustomerTask,
    CrmProjectInsight,
    ExceptionAction,
    ExceptionCase,
    User,
    WorkItem,
)
from app.services.crm_access_service import crm_project_scope_filter, crm_task_scope_filter
from app.services.crm_ai_migration_service import mirror_insight_review
from app.services.crm_project_service import generated_code
from app.services.exception_center_service import (
    ACTION_SOURCE_PERMISSIONS,
    can_view_case,
    configured_exception_action_types,
    execute_action,
    scoped_exception_stmt,
    validate_action,
)
from app.services.permission_service import get_final_permission_codes, has_permission


ACTION_CATALOG = (
    {
        "action_type": "crm_insight.review",
        "domain": "crm",
        "label": "复核 CRM 智能判断",
        "risk_level": "medium",
        "required_permissions": ["crm_insight.review"],
    },
    {
        "action_type": "rebuild_inventory_flow",
        "domain": "inventory",
        "label": "重建库存流转",
        "risk_level": "high",
        "required_permissions": ["exception_center.action_execute", "inventory_check.upload"],
    },
    {
        "action_type": "rerun_inventory_check",
        "domain": "inventory",
        "label": "重新执行库存核验",
        "risk_level": "high",
        "required_permissions": ["exception_center.action_execute", "inventory_check.upload"],
    },
    {
        "action_type": "rebuild_receivable_checks",
        "domain": "receivable",
        "label": "重建应收核验",
        "risk_level": "high",
        "required_permissions": ["exception_center.action_execute", "receivable.check"],
    },
    {
        "action_type": "rebuild_master_link_issues",
        "domain": "master_data",
        "label": "重建主数据关联检查",
        "risk_level": "high",
        "required_permissions": ["exception_center.action_execute", "import.commit"],
    },
    {
        "action_type": "revalidate_import_batch",
        "domain": "import",
        "label": "重新校验导入批次",
        "risk_level": "high",
        "required_permissions": ["exception_center.action_execute", "import.commit"],
    },
)


def controlled_actions_enabled() -> bool:
    return settings.exception_ai_global_enabled and settings.exception_ai_global_actions_enabled


def require_controlled_actions_enabled() -> None:
    if not controlled_actions_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Global controlled actions are disabled",
        )


def require_high_risk_actions_enabled() -> None:
    require_controlled_actions_enabled()
    if not settings.exception_ai_high_risk_actions_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="High-risk controlled actions are disabled",
        )


def controlled_action_catalog(db: Session, user: User) -> list[dict[str, Any]]:
    permissions = set(get_final_permission_codes(db, user))
    configured_high_risk_actions = configured_exception_action_types(db)
    items: list[dict[str, Any]] = []
    for spec in ACTION_CATALOG:
        blockers: list[str] = []
        if not settings.exception_ai_global_enabled:
            blockers.append("feature_disabled:EXCEPTION_AI_GLOBAL_ENABLED")
        if not settings.exception_ai_global_actions_enabled:
            blockers.append("feature_disabled:EXCEPTION_AI_GLOBAL_ACTIONS_ENABLED")
        if spec["risk_level"] == "high" and not settings.exception_ai_high_risk_actions_enabled:
            blockers.append("feature_disabled:EXCEPTION_AI_HIGH_RISK_ACTIONS_ENABLED")
        if spec["risk_level"] == "high" and not settings.exception_actions_enabled:
            blockers.append("feature_disabled:EXCEPTION_ACTIONS_ENABLED")
        if (
            spec["risk_level"] == "high"
            and spec["action_type"] not in configured_high_risk_actions
        ):
            blockers.append("action_disabled_by_policy")
        blockers.extend(
            f"missing_permission:{permission}"
            for permission in spec["required_permissions"]
            if permission not in permissions
        )
        items.append(
            {
                **spec,
                "requires_confirmation": True,
                "available": not blockers,
                "blockers": blockers,
            }
        )
    return items


def _visible_crm_insight_ids(db: Session, user: User) -> list[int]:
    filters: list[Any] = [CrmProjectInsight.generated_by_user_id == user.id]
    if has_permission(db, user, "crm_project.view"):
        project_ids = crm_project_scope_filter(select(CrmProject.id), db, user)
        filters.append(CrmProjectInsight.project_id.in_(project_ids))
    if has_permission(db, user, "crm_task.view"):
        task_ids = crm_task_scope_filter(select(CrmProjectCustomerTask.id), db, user)
        filters.append(CrmProjectInsight.task_id.in_(task_ids))
    return list(db.scalars(select(CrmProjectInsight.id).where(or_(*filters))).all())


def _visible_exception_action_ids(db: Session, user: User) -> list[int]:
    if not has_permission(db, user, "exception_center.action_execute"):
        return []
    case_ids = scoped_exception_stmt(db, user).with_only_columns(ExceptionCase.id).order_by(None)
    return list(db.scalars(select(ExceptionAction.id).where(ExceptionAction.case_id.in_(case_ids))).all())


def visible_action_proposals_stmt(db: Session, user: User) -> Select[tuple[AiActionProposal]]:
    conditions: list[Any] = []
    if has_permission(db, user, "crm_insight.review"):
        crm_ids = _visible_crm_insight_ids(db, user)
        if crm_ids:
            conditions.append(
                and_(
                    AiActionProposal.source_system == "crm",
                    AiActionProposal.legacy_type == "crm_project_insight.action_proposal",
                    AiActionProposal.legacy_id.in_([str(item) for item in crm_ids]),
                )
            )
    exception_ids = _visible_exception_action_ids(db, user)
    if exception_ids:
        conditions.append(
            and_(
                AiActionProposal.source_system == "exception",
                AiActionProposal.legacy_type == "exception_action",
                AiActionProposal.legacy_id.in_([str(item) for item in exception_ids]),
            )
        )
    return select(AiActionProposal).where(or_(*conditions) if conditions else false())


def list_action_proposals(
    db: Session,
    user: User,
    *,
    domain: str | None,
    review_status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[AiActionProposal], int]:
    stmt = visible_action_proposals_stmt(db, user)
    if domain:
        stmt = stmt.where(AiActionProposal.domain == domain)
    if review_status:
        stmt = stmt.where(AiActionProposal.review_status == review_status)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(AiActionProposal.created_at.desc(), AiActionProposal.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, total


def list_action_executions(
    db: Session,
    user: User,
    *,
    domain: str | None,
    execution_status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[AiActionExecution, AiActionProposal]], int]:
    visible_proposal_ids = visible_action_proposals_stmt(db, user).with_only_columns(
        AiActionProposal.id
    )
    stmt = (
        select(AiActionExecution, AiActionProposal)
        .join(AiActionProposal, AiActionProposal.id == AiActionExecution.proposal_id)
        .where(AiActionExecution.proposal_id.in_(visible_proposal_ids))
    )
    if domain:
        stmt = stmt.where(AiActionProposal.domain == domain)
    if execution_status:
        stmt = stmt.where(AiActionExecution.status == execution_status)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(
        db.execute(
            stmt.order_by(AiActionExecution.created_at.desc(), AiActionExecution.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, total


def visible_action_proposal_or_404(
    db: Session,
    user: User,
    proposal_no: str,
    *,
    for_update: bool = False,
) -> AiActionProposal:
    stmt = visible_action_proposals_stmt(db, user).where(AiActionProposal.proposal_no == proposal_no)
    if for_update:
        stmt = stmt.with_for_update()
    proposal = db.scalar(stmt)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI action proposal not found")
    return proposal


def _normal_time(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def assert_proposal_version(proposal: AiActionProposal, expected_updated_at: datetime) -> None:
    if _normal_time(proposal.updated_at) != _normal_time(expected_updated_at):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AI action proposal changed; refresh and retry",
        )


def proposal_blockers(db: Session, user: User, proposal: AiActionProposal) -> list[str]:
    blockers: list[str] = []
    if not controlled_actions_enabled():
        blockers.append("feature_disabled:EXCEPTION_AI_GLOBAL_ACTIONS_ENABLED")
    if proposal.review_status != "pending":
        blockers.append(f"review_status:{proposal.review_status}")
    if proposal.status not in {"proposed", "validated"}:
        blockers.append(f"status:{proposal.status}")
    if proposal.risk_level == "high" and not settings.exception_ai_high_risk_actions_enabled:
        blockers.append("feature_disabled:EXCEPTION_AI_HIGH_RISK_ACTIONS_ENABLED")
    if proposal.source_system == "crm" and not has_permission(db, user, "crm_insight.review"):
        blockers.append("missing_permission:crm_insight.review")
    if proposal.source_system == "exception":
        if not settings.exception_actions_enabled:
            blockers.append("feature_disabled:EXCEPTION_ACTIONS_ENABLED")
        if not has_permission(db, user, "exception_center.action_execute"):
            blockers.append("missing_permission:exception_center.action_execute")
        source_permission = ACTION_SOURCE_PERMISSIONS.get(proposal.action_type)
        if source_permission and not has_permission(db, user, source_permission):
            blockers.append(f"missing_permission:{source_permission}")
        action_id = int(proposal.legacy_id or 0)
        action = db.get(ExceptionAction, action_id)
        case = db.get(ExceptionCase, action.case_id) if action is not None else None
        if action is None or case is None:
            blockers.append("source_action_missing")
        else:
            expires_at = action.validation_expires_at
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if action.status == "validated" and (
                expires_at is None or expires_at <= datetime.now(timezone.utc)
            ):
                blockers.append("validation_expired")
            if action.evidence_version != case.evidence_version:
                blockers.append("evidence_changed")
            if (action.impact_json or {}).get("batch_id") != case.source_batch_id:
                blockers.append("source_batch_changed")
    return blockers


def serialize_action_proposal(db: Session, user: User, proposal: AiActionProposal) -> dict[str, Any]:
    blockers = proposal_blockers(db, user, proposal)
    return {
        "id": proposal.id,
        "proposal_no": proposal.proposal_no,
        "domain": proposal.domain,
        "action_type": proposal.action_type,
        "resource_type": proposal.resource_type,
        "resource_id": proposal.resource_id,
        "status": proposal.status,
        "review_status": proposal.review_status,
        "risk_level": proposal.risk_level,
        "requires_confirmation": proposal.requires_confirmation,
        "parameters": proposal.parameters_json or {},
        "impact": proposal.impact_json or {},
        "source_refs": proposal.source_refs_json or [],
        "executable": not blockers,
        "blockers": blockers,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
        "reviewed_at": proposal.reviewed_at,
    }


def _security_event(
    db: Session,
    *,
    event_type: str,
    outcome: str,
    user: User,
    proposal: AiActionProposal,
    legacy_type: str,
    legacy_id: str,
    detail: dict[str, Any],
) -> None:
    existing = db.scalar(
        select(AiSecurityEvent.id).where(
            AiSecurityEvent.source_system == "global_ai",
            AiSecurityEvent.legacy_type == legacy_type,
            AiSecurityEvent.legacy_id == legacy_id,
        )
    )
    if existing is not None:
        return
    db.add(
        AiSecurityEvent(
            event_no=f"AI-ACTION-{uuid4()}",
            event_type=event_type,
            severity="warning" if proposal.risk_level == "high" else "info",
            outcome=outcome,
            actor_user_id=user.id,
            service_identity="human_confirmed_action_center",
            domain=proposal.domain,
            resource_type=proposal.resource_type,
            resource_id=proposal.resource_id,
            detail_json=detail,
            source_system="global_ai",
            legacy_type=legacy_type,
            legacy_id=legacy_id,
        )
    )


def record_controlled_crm_execution_event(
    db: Session,
    *,
    user: User,
    proposal: AiActionProposal,
    execution: AiActionExecution,
    decision: str,
) -> None:
    _security_event(
        db,
        event_type="controlled_action_executed",
        outcome=execution.status,
        user=user,
        proposal=proposal,
        legacy_type="controlled_action.execution",
        legacy_id=str(execution.id),
        detail={
            "action_type": "crm_insight.review",
            "decision": decision,
            "status": execution.status,
            "human_confirmed": True,
        },
    )


def mirror_exception_action_validation(
    db: Session,
    action: ExceptionAction,
    case: ExceptionCase,
    user: User,
) -> AiActionProposal:
    legacy_id = str(action.id)
    proposal = db.scalar(
        select(AiActionProposal).where(
            AiActionProposal.source_system == "exception",
            AiActionProposal.legacy_type == "exception_action",
            AiActionProposal.legacy_id == legacy_id,
        )
    )
    if proposal is None:
        proposal = AiActionProposal(
            proposal_no=f"AI-EXC-PROP-{action.id}",
            domain=case.domain,
            action_type=action.action_type,
            resource_type="exception_case",
            resource_id=case.case_no,
            status="validated" if action.allowed else "blocked",
            review_status="pending" if action.allowed else "rejected",
            risk_level="high",
            requires_confirmation=True,
            parameters_json=action.parameters_json or {},
            impact_json=action.impact_json or {},
            source_refs_json=[f"exception_case:{case.id}", f"exception_action:{action.id}"],
            created_by_user_id=user.id,
            source_system="exception",
            legacy_type="exception_action",
            legacy_id=legacy_id,
        )
        db.add(proposal)
        db.flush()
    _security_event(
        db,
        event_type="controlled_action_validated",
        outcome="allowed" if action.allowed else "blocked",
        user=user,
        proposal=proposal,
        legacy_type="controlled_action.validation",
        legacy_id=legacy_id,
        detail={
            "action_type": action.action_type,
            "allowed": action.allowed,
            "blockers": action.blockers_json or [],
            "evidence_version": action.evidence_version,
        },
    )
    return proposal


def _execution_for_key(
    db: Session,
    proposal: AiActionProposal,
    idempotency_key: str,
) -> AiActionExecution | None:
    existing = db.scalar(
        select(AiActionExecution).where(AiActionExecution.idempotency_key == idempotency_key)
    )
    if existing is not None and existing.proposal_id != proposal.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key belongs to another AI action",
        )
    return existing


def mirror_exception_action_execution(
    db: Session,
    action: ExceptionAction,
    proposal: AiActionProposal,
    user: User,
    idempotency_key: str,
) -> AiActionExecution:
    existing = _execution_for_key(db, proposal, idempotency_key)
    if existing is not None:
        return existing
    proposal.review_status = "accepted"
    proposal.status = "completed" if action.status == "completed" else action.status
    proposal.reviewed_by_user_id = user.id
    proposal.reviewed_at = datetime.now(timezone.utc)
    execution = AiActionExecution(
        execution_no=f"AI-EXC-EXEC-{action.id}",
        proposal_id=proposal.id,
        idempotency_key=idempotency_key,
        status=action.status,
        attempts=1,
        requested_by_user_id=user.id,
        approved_by_user_id=user.id,
        executor_identity="human_confirmed_exception_workflow",
        request_json={"action_type": action.action_type, "case_no": proposal.resource_id},
        result_json=action.result_json,
        verification_json={
            "human_confirmed": True,
            "evidence_version": action.evidence_version,
            "business_verification": action.verification_json or {},
        },
        error_code=action.error_message if action.status == "failed" else None,
        error_message=action.error_message,
        started_at=action.started_at,
        completed_at=action.completed_at,
        source_system="exception",
        legacy_type="exception_action.execution",
        legacy_id=str(action.id),
    )
    db.add(execution)
    db.flush()
    _security_event(
        db,
        event_type="controlled_action_executed",
        outcome=action.status,
        user=user,
        proposal=proposal,
        legacy_type="controlled_action.execution",
        legacy_id=str(execution.id),
        detail={
            "action_type": action.action_type,
            "status": action.status,
            "human_confirmed": True,
            "attempts": execution.attempts,
        },
    )
    return execution


def validate_exception_controlled_action(
    db: Session,
    user: User,
    *,
    case_no: str,
    action_type: str,
    parameters: dict[str, Any],
) -> tuple[AiActionProposal, ExceptionAction, str]:
    require_high_risk_actions_enabled()
    if not has_permission(db, user, "exception_center.action_execute"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission: exception_center.action_execute",
        )
    case = db.scalar(scoped_exception_stmt(db, user).where(ExceptionCase.case_no == case_no))
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception case not found")
    action, token = validate_action(db, case, action_type, parameters, user)
    proposal = mirror_exception_action_validation(db, action, case, user)
    return proposal, action, token


def execute_exception_controlled_action(
    db: Session,
    user: User,
    proposal: AiActionProposal,
    *,
    expected_updated_at: datetime,
    validation_token: str | None,
    idempotency_key: str,
) -> AiActionExecution:
    require_high_risk_actions_enabled()
    if proposal.source_system != "exception" or proposal.legacy_type != "exception_action":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Proposal is not an exception action")
    action_id = int(proposal.legacy_id or 0)
    action = db.get(ExceptionAction, action_id)
    case = db.get(ExceptionCase, action.case_id) if action is not None else None
    if action is None or case is None or not can_view_case(db, user, case):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI action proposal not found")
    existing = _execution_for_key(db, proposal, idempotency_key)
    if existing is not None:
        return existing
    assert_proposal_version(proposal, expected_updated_at)
    if validation_token is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="validation_token is required")
    blockers = proposal_blockers(db, user, proposal)
    if blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "AI action proposal is not executable", "blockers": blockers},
        )
    executed = execute_action(db, case, validation_token, idempotency_key, user)
    return mirror_exception_action_execution(db, executed, proposal, user, idempotency_key)


def _visible_crm_insight_or_404(
    db: Session,
    user: User,
    proposal: AiActionProposal,
) -> CrmProjectInsight:
    if proposal.source_system != "crm" or proposal.legacy_type != "crm_project_insight.action_proposal":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Proposal is not a CRM insight action")
    insight_id = int(proposal.legacy_id or 0)
    if insight_id not in set(_visible_crm_insight_ids(db, user)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI action proposal not found")
    insight = db.get(CrmProjectInsight, insight_id)
    if insight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI action proposal not found")
    return insight


def review_crm_controlled_action(
    db: Session,
    user: User,
    proposal: AiActionProposal,
    *,
    expected_updated_at: datetime,
    decision: str,
    note: str | None,
    idempotency_key: str,
) -> tuple[CrmProjectInsight, AiActionExecution, bool]:
    require_controlled_actions_enabled()
    if not has_permission(db, user, "crm_insight.review"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: crm_insight.review")
    insight = _visible_crm_insight_or_404(db, user, proposal)
    existing = _execution_for_key(db, proposal, idempotency_key)
    if existing is not None:
        if (existing.request_json or {}).get("action") != decision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key was already used with another CRM decision",
            )
        return insight, existing, False
    assert_proposal_version(proposal, expected_updated_at)
    blockers = proposal_blockers(db, user, proposal)
    if blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "AI action proposal is not executable", "blockers": blockers},
        )
    now = datetime.now(timezone.utc)
    work_item_created = False
    if decision == "reject":
        insight.status = "rejected"
        insight.review_note = note
    elif decision == "accept":
        insight.status = "accepted"
        insight.review_note = note
    elif decision == "task":
        existing_item = db.scalar(
            select(WorkItem).where(
                WorkItem.source_type == "crm_ai_insight",
                WorkItem.source_id == insight.insight_no,
            )
        )
        if existing_item is None:
            db.add(
                WorkItem(
                    item_no=generated_code("WI"),
                    source_type="crm_ai_insight",
                    source_id=insight.insight_no,
                    resource_type="crm_project_insight",
                    resource_id=str(insight.id),
                    project_id=insight.project_id,
                    customer_code=insight.customer_code,
                    item_type="crm_ai_insight",
                    title=insight.summary[:255],
                    detail=insight.suggested_action,
                    priority="high" if insight.risk_level == "high" else "normal",
                    status="open",
                    assignee_user_id=user.id,
                )
            )
            work_item_created = True
        insight.status = "accepted"
        insight.review_note = note or "已转为待支持事项"
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported CRM decision")
    insight.reviewed_by_user_id = user.id
    insight.reviewed_at = now
    execution = mirror_insight_review(
        db,
        insight,
        action=decision,
        reviewer_user_id=user.id,
        work_item_created=work_item_created,
        idempotency_key=idempotency_key,
    )
    if execution is None:
        raise RuntimeError("Unified CRM action execution was not created")
    record_controlled_crm_execution_event(
        db,
        user=user,
        proposal=proposal,
        execution=execution,
        decision=decision,
    )
    return insight, execution, work_item_created


def serialize_action_execution(
    execution: AiActionExecution,
    proposal: AiActionProposal,
) -> dict[str, Any]:
    return {
        "execution_no": execution.execution_no,
        "proposal_no": proposal.proposal_no,
        "status": execution.status,
        "idempotency_key": execution.idempotency_key,
        "attempts": execution.attempts,
        "executor_identity": execution.executor_identity,
        "result": execution.result_json or {},
        "verification": execution.verification_json or {},
        "error_code": execution.error_code,
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
    }
