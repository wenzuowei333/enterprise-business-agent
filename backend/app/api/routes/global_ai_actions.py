from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.models import User
from app.schemas.global_ai import (
    ControlledActionCatalogItem,
    ControlledActionExecuteRequest,
    ControlledActionExecutionPage,
    ControlledActionExecutionPublic,
    ControlledActionProposalPage,
    ControlledActionProposalPublic,
    ControlledActionValidationResponse,
    ControlledCrmActionReviewRequest,
    ControlledExceptionActionValidationRequest,
)
from app.services.audit_service import write_audit_log
from app.services.controlled_action_service import (
    controlled_action_catalog,
    execute_exception_controlled_action,
    list_action_executions,
    list_action_proposals,
    require_controlled_actions_enabled,
    review_crm_controlled_action,
    serialize_action_execution,
    serialize_action_proposal,
    validate_exception_controlled_action,
    visible_action_proposal_or_404,
)


router = APIRouter(prefix="/ai/actions", tags=["global-ai-actions"])
ACTION_CENTER_ACCESS = require_any_permission(
    "crm_insight.review",
    "exception_center.action_execute",
)


@router.get("/catalog", response_model=list[ControlledActionCatalogItem])
def get_controlled_action_catalog(
    db: Session = Depends(get_db),
    current_user: User = Depends(ACTION_CENTER_ACCESS),
) -> list[dict]:
    return controlled_action_catalog(db, current_user)


@router.get("/proposals", response_model=ControlledActionProposalPage)
def get_controlled_action_proposals(
    domain: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9_]{0,59}$"),
    review_status: str | None = Query(default=None, pattern="^(pending|accepted|rejected)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(ACTION_CENTER_ACCESS),
) -> ControlledActionProposalPage:
    require_controlled_actions_enabled()
    rows, total = list_action_proposals(
        db,
        current_user,
        domain=domain,
        review_status=review_status,
        limit=limit,
        offset=offset,
    )
    return ControlledActionProposalPage(
        items=[serialize_action_proposal(db, current_user, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/proposals/{proposal_no}", response_model=ControlledActionProposalPublic)
def get_controlled_action_proposal(
    proposal_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(ACTION_CENTER_ACCESS),
) -> dict:
    require_controlled_actions_enabled()
    proposal = visible_action_proposal_or_404(db, current_user, proposal_no)
    return serialize_action_proposal(db, current_user, proposal)


@router.get("/executions", response_model=ControlledActionExecutionPage)
def get_controlled_action_executions(
    domain: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9_]{0,59}$"),
    execution_status: str | None = Query(
        default=None,
        alias="status",
        pattern="^(pending|completed|failed|cancelled)$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(ACTION_CENTER_ACCESS),
) -> ControlledActionExecutionPage:
    require_controlled_actions_enabled()
    rows, total = list_action_executions(
        db,
        current_user,
        domain=domain,
        execution_status=execution_status,
        limit=limit,
        offset=offset,
    )
    return ControlledActionExecutionPage(
        items=[serialize_action_execution(execution, proposal) for execution, proposal in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/exceptions/{case_no}/validate",
    response_model=ControlledActionValidationResponse,
)
def validate_controlled_exception_action(
    case_no: str,
    body: ControlledExceptionActionValidationRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.action_execute")),
) -> ControlledActionValidationResponse:
    proposal, action, token = validate_exception_controlled_action(
        db,
        current_user,
        case_no=case_no,
        action_type=body.action_type,
        parameters=body.parameters,
    )
    write_audit_log(
        db,
        action_type="validate_global_ai_controlled_action",
        resource_type="ai_action_proposal",
        resource_id=proposal.proposal_no,
        user=current_user,
        request=request,
        after_data={
            "action_type": proposal.action_type,
            "domain": proposal.domain,
            "allowed": action.allowed,
            "blockers": action.blockers_json or [],
            "risk_level": proposal.risk_level,
            "human_confirmation_required": True,
        },
    )
    db.commit()
    db.refresh(proposal)
    db.refresh(action)
    return ControlledActionValidationResponse(
        proposal=ControlledActionProposalPublic.model_validate(
            serialize_action_proposal(db, current_user, proposal)
        ),
        validation_token=token if action.allowed else None,
        validation_expires_at=action.validation_expires_at,
    )


@router.post(
    "/proposals/{proposal_no}/execute",
    response_model=ControlledActionExecutionPublic,
)
def execute_controlled_action(
    proposal_no: str,
    body: ControlledActionExecuteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exception_center.action_execute")),
) -> dict:
    proposal = visible_action_proposal_or_404(db, current_user, proposal_no, for_update=True)
    execution = execute_exception_controlled_action(
        db,
        current_user,
        proposal,
        expected_updated_at=body.expected_updated_at,
        validation_token=body.validation_token,
        idempotency_key=body.idempotency_key,
    )
    write_audit_log(
        db,
        action_type="execute_global_ai_controlled_action",
        resource_type="ai_action_proposal",
        resource_id=proposal.proposal_no,
        user=current_user,
        request=request,
        after_data={
            "action_type": proposal.action_type,
            "domain": proposal.domain,
            "status": execution.status,
            "risk_level": proposal.risk_level,
            "human_confirmed": True,
            "idempotent": True,
        },
    )
    db.commit()
    db.refresh(execution)
    return serialize_action_execution(execution, proposal)


@router.post(
    "/proposals/{proposal_no}/crm-review",
    response_model=ControlledActionExecutionPublic,
)
def review_controlled_crm_action(
    proposal_no: str,
    body: ControlledCrmActionReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("crm_insight.review")),
) -> dict:
    proposal = visible_action_proposal_or_404(db, current_user, proposal_no, for_update=True)
    _insight, execution, work_item_created = review_crm_controlled_action(
        db,
        current_user,
        proposal,
        expected_updated_at=body.expected_updated_at,
        decision=body.decision,
        note=body.note,
        idempotency_key=body.idempotency_key,
    )
    write_audit_log(
        db,
        action_type="review_global_ai_crm_action",
        resource_type="ai_action_proposal",
        resource_id=proposal.proposal_no,
        user=current_user,
        request=request,
        after_data={
            "action_type": proposal.action_type,
            "domain": proposal.domain,
            "decision": body.decision,
            "status": execution.status,
            "work_item_created": work_item_created,
            "human_confirmed": True,
            "idempotent": True,
        },
    )
    db.commit()
    db.refresh(execution)
    return serialize_action_execution(execution, proposal)
