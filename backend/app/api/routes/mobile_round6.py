from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_any_permission, require_crm_permission
from app.api.routes.crm_leads import (
    _scoped_lead,
    assign_lead,
    claim_lead,
    close_lead,
    create_lead,
    create_lead_conversion_approval_draft,
    create_lead_followup,
    duplicate_check,
    get_lead,
    lead_analytics,
    lead_dimensions,
    lead_summary,
    list_public_pool,
    list_leads,
    list_lead_sla_exceptions,
    recycle_lead,
    update_lead,
)
from app.core.database import get_db
from app.core.config import settings
from app.models import User
from app.schemas.crm import (
    ApprovalInstancePublic,
    CrmLeadAssignmentCreate,
    CrmLeadConversionApprovalDraftCreate,
    CrmLeadCreate,
    CrmLeadFollowupCreate,
    CrmLeadFollowupPublic,
    CrmLeadPage,
    CrmLeadPoolPage,
    CrmLeadPublic,
    CrmLeadRecycleRequest,
    CrmLeadSlaExceptionPage,
    CrmLeadUpdate,
)


def _lead_feature_unavailable() -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mobile lead feature is unavailable")


def _require_mobile_lead_pool() -> None:
    if not settings.mobile_feature_lead_pool:
        _lead_feature_unavailable()


def _require_mobile_lead_conversion() -> None:
    _require_mobile_lead_pool()
    if not settings.mobile_feature_lead_conversion:
        _lead_feature_unavailable()


def _require_mobile_lead_analytics() -> None:
    _require_mobile_lead_pool()
    if not settings.mobile_feature_lead_analytics:
        _lead_feature_unavailable()


def _require_mobile_lead_product_intent(product_intents: list[Any] | None) -> None:
    if product_intents and not settings.mobile_feature_lead_product_intent:
        _lead_feature_unavailable()


def _require_mobile_lead_public_pool() -> None:
    _require_mobile_lead_pool()
    if not settings.lead_public_pool:
        _lead_feature_unavailable()


def _require_mobile_lead_sla() -> None:
    _require_mobile_lead_pool()
    if not settings.lead_sla:
        _lead_feature_unavailable()


router = APIRouter(prefix="/leads", tags=["mobile-round6"], dependencies=[Depends(_require_mobile_lead_pool)])


@router.get("/duplicate-check")
def mobile_lead_duplicate_check(
    lead_name: str | None = None,
    contact_phone: str | None = None,
    exclude_lead_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_lead.create", "crm_lead.view")),
) -> dict[str, Any]:
    return duplicate_check(lead_name=lead_name, contact_phone=contact_phone, exclude_lead_id=exclude_lead_id, db=db, current_user=current_user)


@router.get("/summary", dependencies=[Depends(_require_mobile_lead_analytics)])
def mobile_lead_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.analytics")),
) -> dict[str, Any]:
    return lead_summary(db=db, current_user=current_user)


@router.get("/dimensions", dependencies=[Depends(_require_mobile_lead_analytics)])
def mobile_lead_dimensions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.analytics")),
) -> dict[str, Any]:
    return lead_dimensions(db=db, current_user=current_user)


@router.get("/analytics", dependencies=[Depends(_require_mobile_lead_analytics)])
def mobile_lead_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.analytics")),
) -> dict[str, Any]:
    return lead_analytics(db=db, current_user=current_user)


@router.get("", response_model=CrmLeadPage)
def mobile_list_leads(
    q: str | None = None,
    status_value: str | None = Query(default=None, alias="status"),
    source: str | None = None,
    region: str | None = None,
    assigned_user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.view")),
) -> CrmLeadPage:
    return list_leads(q=q, status_value=status_value, source=source, region=region, assigned_user_id=assigned_user_id, limit=limit, offset=offset, db=db, current_user=current_user)


@router.get(
    "/public-pool",
    response_model=CrmLeadPoolPage,
    dependencies=[Depends(_require_mobile_lead_public_pool), Depends(require_crm_permission("crm_lead.claim"))],
)
def mobile_list_public_pool(
    q: str | None = None,
    source: str | None = None,
    region: str | None = None,
    priority: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.view")),
) -> CrmLeadPoolPage:
    _require_mobile_lead_public_pool()
    return list_public_pool(
        q=q,
        source=source,
        region=region,
        priority=priority,
        limit=limit,
        offset=offset,
        db=db,
        current_user=current_user,
    )


@router.get("/sla-exceptions", response_model=CrmLeadSlaExceptionPage, dependencies=[Depends(_require_mobile_lead_sla)])
def mobile_list_lead_sla_exceptions(
    state_value: str | None = Query(default=None, alias="state"),
    today_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.view")),
) -> CrmLeadSlaExceptionPage:
    _require_mobile_lead_sla()
    return list_lead_sla_exceptions(
        state_value=state_value,
        today_only=today_only,
        limit=limit,
        offset=offset,
        db=db,
        current_user=current_user,
    )


@router.post("", response_model=CrmLeadPublic, status_code=status.HTTP_201_CREATED)
def mobile_create_lead(
    payload: CrmLeadCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.create")),
) -> CrmLeadPublic:
    _require_mobile_lead_product_intent(payload.product_intents)
    return create_lead(payload=payload, request=request, db=db, current_user=current_user)


@router.get("/{lead_id}", response_model=CrmLeadPublic)
def mobile_get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.view")),
) -> CrmLeadPublic:
    return get_lead(lead_id=lead_id, db=db, current_user=current_user)


@router.patch("/{lead_id}", response_model=CrmLeadPublic)
def mobile_update_lead(
    lead_id: int,
    payload: CrmLeadUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.edit")),
) -> CrmLeadPublic:
    _require_mobile_lead_product_intent(payload.product_intents)
    return update_lead(lead_id=lead_id, payload=payload, request=request, db=db, current_user=current_user)


@router.delete("/{lead_id}")
def mobile_close_lead(
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.edit")),
) -> dict[str, Any]:
    return close_lead(lead_id=lead_id, request=request, db=db, current_user=current_user)


@router.post("/{lead_id}/assign", response_model=CrmLeadPublic)
def mobile_assign_lead(
    lead_id: int,
    payload: CrmLeadAssignmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.assign")),
) -> CrmLeadPublic:
    return assign_lead(lead_id=lead_id, payload=payload, request=request, db=db, current_user=current_user)


@router.post(
    "/{lead_id}/claim",
    response_model=CrmLeadPublic,
    dependencies=[Depends(_require_mobile_lead_public_pool), Depends(require_crm_permission("crm_lead.claim"))],
)
def mobile_claim_lead(
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.view")),
) -> CrmLeadPublic:
    _require_mobile_lead_public_pool()
    return claim_lead(lead_id=lead_id, request=request, db=db, current_user=current_user)


@router.post("/{lead_id}/recycle", response_model=CrmLeadPublic, dependencies=[Depends(_require_mobile_lead_public_pool)])
def mobile_recycle_lead(
    lead_id: int,
    payload: CrmLeadRecycleRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.recycle")),
) -> CrmLeadPublic:
    _require_mobile_lead_public_pool()
    return recycle_lead(lead_id=lead_id, payload=payload, request=request, db=db, current_user=current_user)


@router.post("/{lead_id}/followups", response_model=CrmLeadFollowupPublic, status_code=status.HTTP_201_CREATED)
def mobile_create_lead_followup(
    lead_id: int,
    payload: CrmLeadFollowupCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.edit")),
) -> CrmLeadFollowupPublic:
    return create_lead_followup(lead_id=lead_id, payload=payload, request=request, db=db, current_user=current_user)


@router.post(
    "/{lead_id}/conversion-approval-draft",
    response_model=ApprovalInstancePublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_require_mobile_lead_conversion)],
)
def mobile_create_lead_conversion_approval_draft(
    lead_id: int,
    payload: CrmLeadConversionApprovalDraftCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.convert")),
) -> Any:
    return create_lead_conversion_approval_draft(lead_id=lead_id, payload=payload, request=request, db=db, current_user=current_user)


@router.get("/{lead_id}/project-prefill", dependencies=[Depends(_require_mobile_lead_conversion)])
def mobile_lead_project_prefill(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.view")),
) -> dict[str, Any]:
    lead = _scoped_lead(db, current_user, lead_id)
    if lead.status != "converted" or not lead.converted_customer_code:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="CRM lead has not been converted")
    customer_name = lead.company_name or lead.lead_name
    return {
        "customer_code": lead.converted_customer_code,
        "customer_name": customer_name,
        "project_name": f"{customer_name}客户开发项目",
        "project_type": "客户开发",
        "customer_scope_note": f"由CRM线索 {lead.lead_no} 转正后预填，需人工确认创建项目。",
        "business_line": lead.business_line,
        "owner_user_id": lead.assigned_user_id or lead.owner_user_id,
        "source_lead_id": lead.id,
        "source_lead_no": lead.lead_no,
    }
