from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import Counter
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import require_any_permission, require_crm_permission
from app.core.config import settings
from app.core.database import get_db
from app.models import ApprovalInstance, CrmLead, CrmLeadAssignmentEvent, CrmLeadCampaign, CrmLeadFollowup, CrmLeadOperationPolicy, CrmLeadProductIntent, User
from app.schemas.crm import (
    ApprovalInstancePublic,
    CrmLeadAssignmentCreate,
    CrmLeadCampaignCreate,
    CrmLeadCampaignPublic,
    CrmLeadCampaignUpdate,
    CrmLeadConversionApprovalDraftCreate,
    CrmLeadCreate,
    CrmLeadFollowupCreate,
    CrmLeadFollowupPublic,
    CrmLeadPage,
    CrmLeadPageSummary,
    CrmLeadOperationPolicyPublic,
    CrmLeadOperationPolicyUpdate,
    CrmLeadPoolPage,
    CrmLeadPoolPublic,
    CrmLeadPublic,
    CrmLeadRecycleRequest,
    CrmLeadSlaExceptionPage,
    CrmLeadSlaExceptionPublic,
    CrmLeadUpdate,
)
from app.services.access_control_service import serialize_with_field_rules
from app.services.audit_service import write_audit_log
from app.services.approval_service import create_approval_instance
from app.services.crm_access_service import crm_lead_scope_filter
from app.services.crm_lead_service import (
    acquire_lead_conversion_draft_lock,
    acquire_lead_claim_lock,
    acquire_lead_duplicate_locks,
    lead_conversion_guard_snapshot,
    find_lead_duplicate_candidates,
    generated_lead_code,
    get_lead_operation_policy,
    is_lead_pool_eligible,
    lead_audit_snapshot,
    lead_followup_audit_snapshot,
    lead_public_pool_projection,
    lead_sla_snapshot,
    normalize_lead_name,
    normalize_lead_phone,
    validate_lead_status_transition,
)
from app.services.permission_service import has_permission


router = APIRouter(prefix="/crm/leads", tags=["crm-leads"])
operations_router = APIRouter(prefix="/crm", tags=["crm-lead-operations"])


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 100))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


def _require_lead_operation_flag(flag_name: str) -> None:
    if not getattr(settings, flag_name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客户线索运营功能暂未开放")


def _require_flag_dependency(flag_name: str):
    def dependency() -> None:
        _require_lead_operation_flag(flag_name)

    return dependency


def _campaign_public(campaign: CrmLeadCampaign) -> CrmLeadCampaignPublic:
    return CrmLeadCampaignPublic.model_validate(campaign)


def _policy_public(policy: CrmLeadOperationPolicy) -> CrmLeadOperationPolicyPublic:
    return CrmLeadOperationPolicyPublic.model_validate(policy)


def _campaign_for_write(db: Session, campaign_id: int | None) -> CrmLeadCampaign | None:
    if campaign_id is None:
        return None
    campaign = db.get(CrmLeadCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="活动不存在或已删除")
    if campaign.status != "active":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="活动未启用，不能关联线索")
    return campaign


def _scoped_lead(db: Session, current_user: User, lead_id: int) -> CrmLead:
    lead = db.scalar(crm_lead_scope_filter(select(CrmLead).where(CrmLead.id == lead_id), db, current_user))
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM lead not found")
    return lead


def _require_active_user(db: Session, user_id: int | None, field_name: str) -> User | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active or user.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} points to an inactive or missing user")
    return user


def _ensure_unique_lead_no(db: Session, lead_no: str) -> None:
    if db.scalar(select(CrmLead.id).where(CrmLead.lead_no == lead_no)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lead number already exists")


def _require_lead_assignment_permission(db: Session, current_user: User) -> None:
    if not has_permission(db, current_user, "crm_lead.assign"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CRM permission: crm_lead.assign")


def _fixed_conversion_handler(db: Session) -> User:
    handler = db.scalar(
        select(User).where(
            User.username == "admin",
            User.status == "active",
            User.is_active.is_(True),
        )
    )
    if handler is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="线索转正审批人账号不存在或未启用：admin")
    return handler


def _blocking_duplicate_detail(blockers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "message": "Blocking CRM lead duplicate",
        "blocking_duplicate_count": len(blockers),
        "blocking_reasons": sorted({reason for blocker in blockers for reason in blocker["reasons"] if reason.startswith("exact_")}),
    }


def _acknowledgement_required_detail(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "message": "CRM lead duplicate acknowledgement required",
        "duplicate_candidate_count": len(candidates),
        "duplicate_reasons": sorted({reason for candidate in candidates for reason in candidate["reasons"]}),
    }


def _exact_phone_duplicates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if "exact_phone" in candidate["reasons"]]


def _acknowledgeable_duplicates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if "exact_phone" not in candidate["reasons"]]


def _replace_product_intents(db: Session, lead: CrmLead, intents: list[Any]) -> None:
    for existing in db.scalars(select(CrmLeadProductIntent).where(CrmLeadProductIntent.lead_id == lead.id)).all():
        db.delete(existing)
    for intent in intents:
        intent_data = intent if isinstance(intent, dict) else intent.model_dump()
        db.add(CrmLeadProductIntent(lead_id=lead.id, **intent_data))


def _lead_public(db: Session, current_user: User, lead: CrmLead, *, include_history: bool = False) -> CrmLeadPublic:
    data = serialize_with_field_rules(db, current_user, "crm_lead", lead)
    data["product_intents"] = list(
        db.scalars(
            select(CrmLeadProductIntent)
            .where(CrmLeadProductIntent.lead_id == lead.id)
            .order_by(CrmLeadProductIntent.sort_order, CrmLeadProductIntent.id)
        ).all()
    )
    if include_history:
        data["followups"] = list(
            db.scalars(
                select(CrmLeadFollowup)
                .where(CrmLeadFollowup.lead_id == lead.id)
                .order_by(CrmLeadFollowup.created_at.desc(), CrmLeadFollowup.id.desc())
            ).all()
        )
        data["assignments"] = list(
            db.scalars(
                select(CrmLeadAssignmentEvent)
                .where(CrmLeadAssignmentEvent.lead_id == lead.id)
                .order_by(CrmLeadAssignmentEvent.created_at.desc(), CrmLeadAssignmentEvent.id.desc())
            ).all()
        )
    return CrmLeadPublic.model_validate(data)


def _visible_duplicate_candidates(db: Session, current_user: User, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return []
    candidate_ids = [item["lead_id"] for item in candidates]
    visible_ids = set(db.scalars(crm_lead_scope_filter(select(CrmLead.id).where(CrmLead.id.in_(candidate_ids)), db, current_user)).all())
    return [item for item in candidates if item["lead_id"] in visible_ids]


def _duplicate_payload(
    db: Session,
    current_user: User,
    visible_candidates: list[dict[str, Any]],
    *,
    all_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidates = all_candidates if all_candidates is not None else visible_candidates
    items = []
    for candidate in visible_candidates:
        lead_data = serialize_with_field_rules(db, current_user, "crm_lead", candidate["lead"])
        items.append(
            {
                "lead_id": candidate["lead_id"],
                "lead_no": lead_data["lead_no"],
                "lead_name": lead_data["lead_name"],
                "contact_phone": lead_data["contact_phone"],
                "reasons": candidate["reasons"],
                "blocking": "exact_phone" in candidate["reasons"],
                "similarity": candidate["similarity"],
            }
        )
    visible_ids = {candidate["lead_id"] for candidate in visible_candidates}
    return {
        "has_blocking_duplicates": bool(_exact_phone_duplicates(candidates)),
        "requires_acknowledgement": bool(_acknowledgeable_duplicates(candidates)),
        "has_hidden_duplicates": any(candidate["lead_id"] not in visible_ids for candidate in candidates),
        "items": items,
    }


def _analytics(db: Session, current_user: User) -> dict[str, Any]:
    # Keep analytics on exactly the same scope predicate as the lead list.
    leads = list(db.scalars(crm_lead_scope_filter(select(CrmLead), db, current_user)).all())
    total = len(leads)
    by_status = dict(Counter(lead.status for lead in leads))
    now = datetime.now(timezone.utc)
    policy = get_lead_operation_policy(db)
    sla_by_lead_id = {lead.id: lead_sla_snapshot(lead, policy, now) for lead in leads}
    sla_states = Counter(snapshot["state"] for snapshot in sla_by_lead_id.values())

    def dimensions(field_name: str) -> list[dict[str, Any]]:
        counts = Counter(str(getattr(lead, field_name) or "未填写") for lead in leads)
        return [{"value": value, "count": count} for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]

    user_ids = {
        user_id
        for lead in leads
        for user_id in (lead.owner_user_id, lead.assigned_user_id)
        if user_id is not None
    }
    users = {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}
    campaign_ids = {lead.campaign_id for lead in leads if lead.campaign_id is not None}
    campaigns = {
        campaign.id: campaign
        for campaign in db.scalars(select(CrmLeadCampaign).where(CrmLeadCampaign.id.in_(campaign_ids))).all()
    } if campaign_ids else {}

    def _user_label(user_id: int | None) -> str:
        if user_id is None:
            return "未分配"
        user = users.get(user_id)
        return (user.real_name or user.username) if user is not None else "已删除账号"

    def _funnel_bucket(bucket: dict[str, Any], lead: CrmLead) -> None:
        bucket["total"] += 1
        bucket["by_status"][lead.status] += 1

    team_buckets: dict[int | None, dict[str, Any]] = {}
    source_buckets: dict[str, dict[str, Any]] = {}
    campaign_buckets: dict[int | None, dict[str, Any]] = {}
    assignment_buckets: dict[int, dict[str, Any]] = {}
    terminal_statuses = {"converted", "closed", "rejected"}
    for lead in leads:
        responsible_user_id = lead.assigned_user_id or lead.owner_user_id
        team_bucket = team_buckets.setdefault(
            responsible_user_id,
            {"user_id": responsible_user_id, "user_label": _user_label(responsible_user_id), "total": 0, "by_status": Counter()},
        )
        _funnel_bucket(team_bucket, lead)

        source = str(lead.source or "未填写")
        source_bucket = source_buckets.setdefault(source, {"source": source, "total": 0, "by_status": Counter()})
        _funnel_bucket(source_bucket, lead)

        campaign = campaigns.get(lead.campaign_id) if lead.campaign_id is not None else None
        campaign_bucket = campaign_buckets.setdefault(
            lead.campaign_id,
            {
                "campaign_id": lead.campaign_id,
                "campaign_code": campaign.campaign_code if campaign is not None else None,
                "campaign_name": campaign.campaign_name if campaign is not None else ("未关联活动" if lead.campaign_id is None else "已删除活动"),
                "total": 0,
                "by_status": Counter(),
            },
        )
        _funnel_bucket(campaign_bucket, lead)

        if lead.assigned_user_id is not None:
            assignment_bucket = assignment_buckets.setdefault(
                lead.assigned_user_id,
                {
                    "user_id": lead.assigned_user_id,
                    "user_label": _user_label(lead.assigned_user_id),
                    "assigned_total": 0,
                    "open_total": 0,
                    "overdue": 0,
                    "due_soon": 0,
                },
            )
            assignment_bucket["assigned_total"] += 1
            if lead.status not in terminal_statuses:
                assignment_bucket["open_total"] += 1
            if sla_by_lead_id[lead.id]["state"] == "overdue":
                assignment_bucket["overdue"] += 1
            elif sla_by_lead_id[lead.id]["state"] == "due_soon":
                assignment_bucket["due_soon"] += 1

    def _serializable_funnel(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {**item, "by_status": dict(item["by_status"])}
            for item in sorted(items, key=lambda item: (-item["total"], str(item.get("user_label") or item.get("source") or item.get("campaign_name"))))
        ]

    visible_ids = [lead.id for lead in leads]
    recycled_events = 0
    claimed_events = 0
    if visible_ids:
        event_rows = db.execute(
            select(CrmLeadAssignmentEvent.event_type, func.count(CrmLeadAssignmentEvent.id))
            .where(CrmLeadAssignmentEvent.lead_id.in_(visible_ids))
            .group_by(CrmLeadAssignmentEvent.event_type)
        ).all()
        event_counts = {event_type: count for event_type, count in event_rows}
        recycled_events = event_counts.get("recycled", 0)
        claimed_events = event_counts.get("claimed", 0)

    return {
        "summary": {
            "total": total,
            "by_status": by_status,
            "overdue_next_followup": sla_states.get("overdue", 0),
        },
        "dimensions": {
            "sources": dimensions("source"),
            "regions": dimensions("region"),
            "business_lines": dimensions("business_line"),
        },
        "operations": {
            "team_funnel": _serializable_funnel(list(team_buckets.values())),
            "source_funnel": _serializable_funnel(list(source_buckets.values())),
            "campaign_funnel": _serializable_funnel(list(campaign_buckets.values())),
            "sla_exceptions": {
                "overdue": sla_states.get("overdue", 0),
                "due_soon": sla_states.get("due_soon", 0),
                "unassigned": sla_states.get("unassigned", 0),
            },
            "assignment_load": sorted(assignment_buckets.values(), key=lambda item: (-item["open_total"], item["user_label"])),
            "recycle_metrics": {
                "recycled_leads": sum(1 for lead in leads if lead.recycle_count > 0),
                "recycle_total": sum(lead.recycle_count for lead in leads),
                "recycle_events": recycled_events,
                "claim_events": claimed_events,
            },
        },
    }


@router.get("/duplicate-check")
def duplicate_check(
    lead_name: str | None = None,
    contact_phone: str | None = None,
    exclude_lead_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_lead.create", "crm_lead.view")),
) -> dict[str, Any]:
    candidates = find_lead_duplicate_candidates(
        db,
        lead_name=lead_name,
        contact_phone=contact_phone,
        exclude_lead_id=exclude_lead_id,
    )
    if not has_permission(db, current_user, "crm_lead.view"):
        return _duplicate_payload(db, current_user, [], all_candidates=candidates)
    visible_candidates = _visible_duplicate_candidates(db, current_user, candidates)
    return _duplicate_payload(db, current_user, visible_candidates, all_candidates=candidates)


@router.get("/summary")
def lead_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.analytics")),
) -> dict[str, Any]:
    return _analytics(db, current_user)["summary"]


@router.get("/dimensions")
def lead_dimensions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.analytics")),
) -> dict[str, Any]:
    return _analytics(db, current_user)["dimensions"]


@router.get("/analytics")
def lead_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.analytics")),
) -> dict[str, Any]:
    return _analytics(db, current_user)


@router.get("/assignee-options")
def lead_assignee_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.assign")),
) -> list[dict[str, Any]]:
    active_users = list(
        db.scalars(
            select(User)
            .where(User.status == "active", User.is_active.is_(True))
            .order_by(User.real_name.asc(), User.username.asc(), User.id.asc())
        ).all()
    )
    return [
        {
            "id": user.id,
            "name": user.real_name or user.username,
            "username": user.username,
            "label": f"{user.real_name}（{user.username}）" if user.real_name and user.real_name != user.username else user.username,
        }
        for user in active_users
    ]


@router.get(
    "/public-pool",
    response_model=CrmLeadPoolPage,
    dependencies=[Depends(_require_flag_dependency("lead_public_pool"))],
)
def list_public_pool(
    q: str | None = None,
    source: str | None = None,
    region: str | None = None,
    priority: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.claim")),
) -> CrmLeadPoolPage:
    _require_lead_operation_flag("lead_public_pool")
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    policy = get_lead_operation_policy(db)
    stmt = select(CrmLead).where(
        CrmLead.pool_status == "public",
        CrmLead.assigned_user_id.is_(None),
        CrmLead.status.in_(["draft", "active", "qualified"]),
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(CrmLead.lead_no.ilike(like), CrmLead.lead_name.ilike(like), CrmLead.company_name.ilike(like)))
    if source:
        stmt = stmt.where(CrmLead.source == source)
    if region:
        stmt = stmt.where(CrmLead.region == region)
    if priority:
        stmt = stmt.where(CrmLead.priority == priority)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    leads = list(
        db.scalars(
            stmt.order_by(CrmLead.recycled_at.desc().nullslast(), CrmLead.created_at.asc(), CrmLead.id.asc())
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    return CrmLeadPoolPage(
        items=[CrmLeadPoolPublic.model_validate(lead_public_pool_projection(lead, policy)) for lead in leads],
        total=total,
        limit=safe_limit,
        offset=safe_offset,
    )


@router.post(
    "/{lead_id}/claim",
    response_model=CrmLeadPublic,
    dependencies=[Depends(_require_flag_dependency("lead_public_pool"))],
)
def claim_lead(
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.claim")),
) -> CrmLeadPublic:
    _require_lead_operation_flag("lead_public_pool")
    candidate = db.get(CrmLead, lead_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM lead not found")
    if not is_lead_pool_eligible(candidate):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该线索当前不可认领或已被其他人员处理")

    policy = get_lead_operation_policy(db)
    now = datetime.now(timezone.utc)
    acquire_lead_claim_lock(db, user_id=current_user.id)
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    next_day_start = day_start + timedelta(days=1)
    claim_count = db.scalar(
        select(func.count(CrmLeadAssignmentEvent.id)).where(
            CrmLeadAssignmentEvent.event_type == "claimed",
            CrmLeadAssignmentEvent.assigned_by_user_id == current_user.id,
            CrmLeadAssignmentEvent.created_at >= day_start,
            CrmLeadAssignmentEvent.created_at < next_day_start,
        )
    ) or 0
    if claim_count >= policy.daily_claim_limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="已达到今日公海线索认领上限")

    before_data = jsonable_encoder(lead_audit_snapshot(db, candidate))
    result = db.execute(
        update(CrmLead)
        .where(
            CrmLead.id == lead_id,
            CrmLead.pool_status == "public",
            CrmLead.assigned_user_id.is_(None),
            CrmLead.status.in_(["draft", "active", "qualified"]),
        )
        .values(
            owner_user_id=current_user.id,
            assigned_user_id=current_user.id,
            pool_status="private",
            assigned_at=now,
            assignment_expires_at=now + timedelta(hours=policy.assignment_hold_hours),
            first_response_due_at=func.coalesce(CrmLead.first_response_due_at, now + timedelta(hours=policy.first_response_hours)),
            last_activity_at=now,
            updated_by_user_id=current_user.id,
        )
        .returning(CrmLead.id)
    )
    claimed_id = result.scalar_one_or_none()
    if claimed_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该线索已被其他人员认领")
    db.expire_all()
    lead = db.get(CrmLead, claimed_id)
    if lead is None:  # pragma: no cover - defensive transaction guard
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="线索认领未完成")
    db.add(
        CrmLeadAssignmentEvent(
            lead_id=lead.id,
            event_type="claimed",
            from_assignee_user_id=None,
            to_assignee_user_id=current_user.id,
            assigned_by_user_id=current_user.id,
            note="从公海认领",
        )
    )
    db.flush()
    write_audit_log(
        db,
        action_type="claim_crm_lead",
        resource_type="crm_lead",
        resource_id=str(lead.id),
        user=current_user,
        request=request,
        before_data=before_data,
        after_data=jsonable_encoder(lead_audit_snapshot(db, lead)),
    )
    db.commit()
    db.refresh(lead)
    return _lead_public(db, current_user, lead)


@router.post(
    "/{lead_id}/recycle",
    response_model=CrmLeadPublic,
    dependencies=[Depends(_require_flag_dependency("lead_public_pool"))],
)
def recycle_lead(
    lead_id: int,
    payload: CrmLeadRecycleRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.recycle")),
) -> CrmLeadPublic:
    _require_lead_operation_flag("lead_public_pool")
    lead = _scoped_lead(db, current_user, lead_id)
    if lead.status not in {"draft", "active", "qualified"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前线索状态不能回收到公海")
    before_data = jsonable_encoder(lead_audit_snapshot(db, lead))
    previous_assignee_id = lead.assigned_user_id
    now = datetime.now(timezone.utc)
    lead.owner_user_id = None
    lead.assigned_user_id = None
    lead.assigned_at = None
    lead.assignment_expires_at = None
    lead.pool_status = "public"
    lead.recycled_at = now
    lead.recycle_count += 1
    lead.last_activity_at = now
    lead.updated_by_user_id = current_user.id
    db.add(
        CrmLeadAssignmentEvent(
            lead_id=lead.id,
            event_type="recycled",
            from_assignee_user_id=previous_assignee_id,
            to_assignee_user_id=None,
            assigned_by_user_id=current_user.id,
            note=payload.note,
        )
    )
    db.flush()
    write_audit_log(
        db,
        action_type="recycle_crm_lead",
        resource_type="crm_lead",
        resource_id=str(lead.id),
        user=current_user,
        request=request,
        before_data=before_data,
        after_data=jsonable_encoder(lead_audit_snapshot(db, lead)),
    )
    db.commit()
    db.refresh(lead)
    return _lead_public(db, current_user, lead)


@operations_router.get(
    "/lead-campaigns",
    response_model=dict[str, Any],
    dependencies=[Depends(_require_flag_dependency("lead_campaign"))],
)
def list_lead_campaigns(
    status_value: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead_campaign.view")),
) -> dict[str, Any]:
    _require_lead_operation_flag("lead_campaign")
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(CrmLeadCampaign)
    if status_value:
        stmt = stmt.where(CrmLeadCampaign.status == status_value)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(CrmLeadCampaign.campaign_code.ilike(like), CrmLeadCampaign.campaign_name.ilike(like), CrmLeadCampaign.source.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    campaigns = list(
        db.scalars(stmt.order_by(CrmLeadCampaign.created_at.desc(), CrmLeadCampaign.id.desc()).offset(safe_offset).limit(safe_limit)).all()
    )
    return {
        "items": [_campaign_public(campaign).model_dump(mode="json") for campaign in campaigns],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@operations_router.post(
    "/lead-campaigns",
    response_model=CrmLeadCampaignPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_require_flag_dependency("lead_campaign"))],
)
def create_lead_campaign(
    payload: CrmLeadCampaignCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead_campaign.manage")),
) -> CrmLeadCampaignPublic:
    _require_lead_operation_flag("lead_campaign")
    if db.scalar(select(CrmLeadCampaign.id).where(CrmLeadCampaign.campaign_code == payload.campaign_code)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="活动编号已存在")
    _require_active_user(db, payload.owner_user_id, "owner_user_id")
    campaign = CrmLeadCampaign(
        **payload.model_dump(),
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
    )
    db.add(campaign)
    db.flush()
    write_audit_log(
        db,
        action_type="create_crm_lead_campaign",
        resource_type="crm_lead_campaign",
        resource_id=str(campaign.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder(_campaign_public(campaign).model_dump()),
    )
    db.commit()
    db.refresh(campaign)
    return _campaign_public(campaign)


@operations_router.patch(
    "/lead-campaigns/{campaign_id}",
    response_model=CrmLeadCampaignPublic,
    dependencies=[Depends(_require_flag_dependency("lead_campaign"))],
)
def update_lead_campaign(
    campaign_id: int,
    payload: CrmLeadCampaignUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead_campaign.manage")),
) -> CrmLeadCampaignPublic:
    _require_lead_operation_flag("lead_campaign")
    campaign = db.get(CrmLeadCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="活动不存在")
    changes = payload.model_dump(exclude_unset=True)
    _require_active_user(db, changes.get("owner_user_id"), "owner_user_id")
    merged_start_date = changes.get("start_date", campaign.start_date)
    merged_end_date = changes.get("end_date", campaign.end_date)
    if merged_start_date and merged_end_date and merged_end_date < merged_start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="活动结束日期不能早于开始日期")
    before_data = jsonable_encoder(_campaign_public(campaign).model_dump())
    for field_name, value in changes.items():
        setattr(campaign, field_name, value)
    campaign.updated_by_user_id = current_user.id
    db.flush()
    write_audit_log(
        db,
        action_type="update_crm_lead_campaign",
        resource_type="crm_lead_campaign",
        resource_id=str(campaign.id),
        user=current_user,
        request=request,
        before_data=before_data,
        after_data=jsonable_encoder(_campaign_public(campaign).model_dump()),
    )
    db.commit()
    db.refresh(campaign)
    return _campaign_public(campaign)


def _persisted_lead_operation_policy(db: Session) -> CrmLeadOperationPolicy:
    policy = get_lead_operation_policy(db)
    if policy.id is None:
        db.add(policy)
        db.flush()
    return policy


@operations_router.get(
    "/lead-operation-policy",
    response_model=CrmLeadOperationPolicyPublic,
    dependencies=[Depends(_require_flag_dependency("lead_sla"))],
)
def get_lead_operation_policy_route(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead_policy.manage")),
) -> CrmLeadOperationPolicyPublic:
    _require_lead_operation_flag("lead_sla")
    return _policy_public(_persisted_lead_operation_policy(db))


@operations_router.patch(
    "/lead-operation-policy",
    response_model=CrmLeadOperationPolicyPublic,
    dependencies=[Depends(_require_flag_dependency("lead_sla"))],
)
def update_lead_operation_policy(
    payload: CrmLeadOperationPolicyUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead_policy.manage")),
) -> CrmLeadOperationPolicyPublic:
    _require_lead_operation_flag("lead_sla")
    policy = _persisted_lead_operation_policy(db)
    before_data = jsonable_encoder(_policy_public(policy).model_dump())
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(policy, field_name, value)
    policy.updated_by_user_id = current_user.id
    db.flush()
    write_audit_log(
        db,
        action_type="update_crm_lead_operation_policy",
        resource_type="crm_lead_operation_policy",
        resource_id=str(policy.id),
        user=current_user,
        request=request,
        before_data=before_data,
        after_data=jsonable_encoder(_policy_public(policy).model_dump()),
    )
    db.commit()
    db.refresh(policy)
    return _policy_public(policy)


@router.get(
    "/sla-exceptions",
    response_model=CrmLeadSlaExceptionPage,
    dependencies=[Depends(_require_flag_dependency("lead_sla"))],
)
def list_lead_sla_exceptions(
    state_value: str | None = None,
    today_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.view")),
) -> CrmLeadSlaExceptionPage:
    _require_lead_operation_flag("lead_sla")
    states = {"overdue", "due_soon", "unassigned"}
    if state_value and state_value not in states:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="SLA 状态仅支持 overdue、due_soon 或 unassigned")
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    now = datetime.now(timezone.utc)
    policy = get_lead_operation_policy(db)
    leads = list(db.scalars(crm_lead_scope_filter(select(CrmLead), db, current_user)).all())
    rows = [
        (lead, lead_sla_snapshot(lead, policy, now))
        for lead in leads
    ]
    rows = [
        row
        for row in rows
        if row[1]["state"] in states
        and (state_value is None or row[1]["state"] == state_value)
        and (
            not today_only
            or (row[1]["deadline"] is not None and row[1]["deadline"].astimezone(timezone.utc).date() == now.date())
        )
    ]
    rank = {"overdue": 0, "due_soon": 1, "unassigned": 2}
    rows.sort(
        key=lambda row: (
            rank[row[1]["state"]],
            row[1]["deadline"] is None,
            row[1]["deadline"] or datetime.max.replace(tzinfo=timezone.utc),
            row[0].id,
        )
    )
    selected_rows = rows[safe_offset : safe_offset + safe_limit]
    return CrmLeadSlaExceptionPage(
        items=[
            CrmLeadSlaExceptionPublic(lead=_lead_public(db, current_user, lead), sla=sla)
            for lead, sla in selected_rows
        ],
        total=len(rows),
        limit=safe_limit,
        offset=safe_offset,
    )


@router.get("", response_model=CrmLeadPage)
def list_leads(
    q: str | None = None,
    status_value: str | None = None,
    status_group: Literal["followup_pending"] | None = None,
    source: str | None = None,
    region: str | None = None,
    assigned_user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.view")),
) -> CrmLeadPage:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    base_stmt = crm_lead_scope_filter(select(CrmLead), db, current_user)
    if q:
        like = f"%{q}%"
        base_stmt = base_stmt.where(or_(CrmLead.lead_no.ilike(like), CrmLead.lead_name.ilike(like), CrmLead.company_name.ilike(like), CrmLead.contact_name.ilike(like)))
    if source:
        base_stmt = base_stmt.where(CrmLead.source == source)
    if region:
        base_stmt = base_stmt.where(CrmLead.region == region)
    if assigned_user_id is not None:
        base_stmt = base_stmt.where(CrmLead.assigned_user_id == assigned_user_id)

    summary_source = base_stmt.order_by(None).subquery()
    status_counts = {
        status_name: count
        for status_name, count in db.execute(
            select(summary_source.c.status, func.count()).group_by(summary_source.c.status)
        ).all()
    }
    summary = CrmLeadPageSummary(total=sum(status_counts.values()), by_status=status_counts)

    stmt = base_stmt
    if status_group == "followup_pending":
        stmt = stmt.where(CrmLead.status.in_(["draft", "active"]))
    elif status_value:
        stmt = stmt.where(CrmLead.status == status_value)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    leads = list(db.scalars(stmt.order_by(CrmLead.updated_at.desc(), CrmLead.id.desc()).offset(safe_offset).limit(safe_limit)).all())
    return CrmLeadPage(
        items=[_lead_public(db, current_user, lead) for lead in leads],
        total=total,
        limit=safe_limit,
        offset=safe_offset,
        summary=summary,
    )


@router.post("", response_model=CrmLeadPublic, status_code=status.HTTP_201_CREATED)
def create_lead(
    payload: CrmLeadCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.create")),
) -> CrmLeadPublic:
    data = payload.model_dump()
    duplicate_acknowledged = data.pop("duplicate_acknowledged")
    policy = get_lead_operation_policy(db)
    now = datetime.now(timezone.utc)
    _campaign_for_write(db, data.get("campaign_id"))
    if data.get("owner_user_id") is None:
        data["owner_user_id"] = current_user.id
    assignment_targets = ("owner_user_id", "assigned_user_id")
    if any(data.get(field_name) not in {None, current_user.id} for field_name in assignment_targets):
        _require_lead_assignment_permission(db, current_user)
    for field_name in assignment_targets:
        _require_active_user(db, data.get(field_name), field_name)
    acquire_lead_duplicate_locks(db, lead_name=data["lead_name"], contact_phone=data.get("contact_phone"))
    candidates = find_lead_duplicate_candidates(db, lead_name=data["lead_name"], contact_phone=data.get("contact_phone"))
    blockers = _exact_phone_duplicates(candidates)
    if blockers:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_blocking_duplicate_detail(blockers))
    acknowledged_candidates = _acknowledgeable_duplicates(candidates)
    if acknowledged_candidates and not duplicate_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_acknowledgement_required_detail(acknowledged_candidates),
        )
    lead_no = data.pop("lead_no") or generated_lead_code("LEAD-")
    _ensure_unique_lead_no(db, lead_no)
    product_intents = data.pop("product_intents")
    data["normalized_name"] = normalize_lead_name(data["lead_name"])
    data["normalized_phone"] = normalize_lead_phone(data.get("contact_phone"))
    data["first_response_due_at"] = now + timedelta(hours=policy.first_response_hours)
    data["last_activity_at"] = now
    if data.get("assigned_user_id"):
        data["assigned_at"] = now
        data["assignment_expires_at"] = now + timedelta(hours=policy.assignment_hold_hours)
    lead = CrmLead(**data, lead_no=lead_no, created_by_user_id=current_user.id, updated_by_user_id=current_user.id)
    db.add(lead)
    db.flush()
    _replace_product_intents(db, lead, product_intents)
    db.flush()
    if lead.assigned_user_id is not None:
        db.add(CrmLeadAssignmentEvent(lead_id=lead.id, event_type="assigned", to_assignee_user_id=lead.assigned_user_id, assigned_by_user_id=current_user.id, note="Initial assignment"))
    db.flush()
    audit_after = jsonable_encoder(lead_audit_snapshot(db, lead))
    if acknowledged_candidates:
        audit_after["duplicate_override"] = {
            "acknowledged": True,
            "candidate_count": len(acknowledged_candidates),
            "reasons": sorted({reason for candidate in acknowledged_candidates for reason in candidate["reasons"]}),
        }
    write_audit_log(db, action_type="create_crm_lead", resource_type="crm_lead", resource_id=str(lead.id), user=current_user, request=request, after_data=audit_after)
    db.commit()
    db.refresh(lead)
    return _lead_public(db, current_user, lead)


@router.get("/{lead_id}", response_model=CrmLeadPublic)
def get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.view")),
) -> CrmLeadPublic:
    return _lead_public(db, current_user, _scoped_lead(db, current_user, lead_id), include_history=True)


@router.patch("/{lead_id}", response_model=CrmLeadPublic)
def update_lead(
    lead_id: int,
    payload: CrmLeadUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.edit")),
) -> CrmLeadPublic:
    lead = _scoped_lead(db, current_user, lead_id)
    changes = payload.model_dump(exclude_unset=True)
    duplicate_acknowledged = changes.pop("duplicate_acknowledged", False)
    product_intents = changes.pop("product_intents", None)
    if "status" in changes and changes["status"] is not None:
        validate_lead_status_transition(lead.status, changes["status"])
    assignment_targets = ("owner_user_id", "assigned_user_id")
    if any(field_name in changes and changes[field_name] != getattr(lead, field_name) for field_name in assignment_targets):
        _require_lead_assignment_permission(db, current_user)
    for field_name in assignment_targets:
        if field_name in changes:
            _require_active_user(db, changes[field_name], field_name)
    candidate_name = changes.get("lead_name", lead.lead_name)
    candidate_phone = changes.get("contact_phone", lead.contact_phone)
    if "lead_name" in changes or "contact_phone" in changes:
        acquire_lead_duplicate_locks(db, lead_name=candidate_name, contact_phone=candidate_phone)
        candidates = find_lead_duplicate_candidates(db, lead_name=candidate_name, contact_phone=candidate_phone, exclude_lead_id=lead.id)
        blockers = _exact_phone_duplicates(candidates)
        if blockers:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_blocking_duplicate_detail(blockers))
        acknowledged_candidates = _acknowledgeable_duplicates(candidates)
        if acknowledged_candidates and not duplicate_acknowledged:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_acknowledgement_required_detail(acknowledged_candidates),
            )
        changes["normalized_name"] = normalize_lead_name(candidate_name)
        changes["normalized_phone"] = normalize_lead_phone(candidate_phone)
    else:
        acknowledged_candidates = []
    if "campaign_id" in changes:
        _campaign_for_write(db, changes["campaign_id"])
    before_data = jsonable_encoder(lead_audit_snapshot(db, lead))
    previous_assignee_id = lead.assigned_user_id
    for field_name, value in changes.items():
        setattr(lead, field_name, value)
    lead.updated_by_user_id = current_user.id
    if "assigned_user_id" in changes and previous_assignee_id != lead.assigned_user_id:
        now = datetime.now(timezone.utc)
        policy = get_lead_operation_policy(db)
        lead.assigned_at = now if lead.assigned_user_id else None
        lead.assignment_expires_at = now + timedelta(hours=policy.assignment_hold_hours) if lead.assigned_user_id else None
        if lead.assigned_user_id is not None:
            lead.pool_status = "private"
        lead.last_activity_at = now
        db.add(CrmLeadAssignmentEvent(lead_id=lead.id, event_type="assigned", from_assignee_user_id=previous_assignee_id, to_assignee_user_id=lead.assigned_user_id, assigned_by_user_id=current_user.id, note="Updated with lead"))
    if product_intents is not None:
        _replace_product_intents(db, lead, product_intents)
    db.flush()
    audit_after = jsonable_encoder(lead_audit_snapshot(db, lead))
    if acknowledged_candidates:
        audit_after["duplicate_override"] = {
            "acknowledged": True,
            "candidate_count": len(acknowledged_candidates),
            "reasons": sorted({reason for candidate in acknowledged_candidates for reason in candidate["reasons"]}),
        }
    write_audit_log(db, action_type="update_crm_lead", resource_type="crm_lead", resource_id=str(lead.id), user=current_user, request=request, before_data=before_data, after_data=audit_after)
    db.commit()
    db.refresh(lead)
    return _lead_public(db, current_user, lead)


@router.delete("/{lead_id}")
def close_lead(
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.edit")),
) -> dict[str, Any]:
    lead = _scoped_lead(db, current_user, lead_id)
    validate_lead_status_transition(lead.status, "closed")
    before_data = jsonable_encoder(lead_audit_snapshot(db, lead))
    lead.status = "closed"
    lead.updated_by_user_id = current_user.id
    db.flush()
    write_audit_log(
        db,
        action_type="close_crm_lead",
        resource_type="crm_lead",
        resource_id=str(lead.id),
        user=current_user,
        request=request,
        before_data=before_data,
        after_data=jsonable_encoder(lead_audit_snapshot(db, lead)),
    )
    db.commit()
    db.refresh(lead)
    return {"message": "CRM lead closed", "lead": _lead_public(db, current_user, lead)}


@router.post("/{lead_id}/conversion-approval-draft", response_model=ApprovalInstancePublic, status_code=status.HTTP_201_CREATED)
def create_lead_conversion_approval_draft(
    lead_id: int,
    payload: CrmLeadConversionApprovalDraftCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.convert")),
) -> ApprovalInstance:
    acquire_lead_conversion_draft_lock(db, lead_id=lead_id)
    lead = _scoped_lead(db, current_user, lead_id)
    if lead.status == "converted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="CRM lead has already been converted")
    if lead.status not in {"qualified", "conversion_pending"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"CRM lead cannot be converted from status: {lead.status}")
    if lead.status == "conversion_pending" and lead.current_approval_id:
        current_approval = db.get(ApprovalInstance, lead.current_approval_id)
        if current_approval and current_approval.status in {"draft", "submitted", "under_review", "need_supplement"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="CRM lead already has an active conversion approval")

    handler = _fixed_conversion_handler(db)
    before = jsonable_encoder(lead_audit_snapshot(db, lead))
    after = {
        "status": "converted",
        "customer_name": lead.company_name or lead.lead_name,
        "customer_code_pattern": f"KHCRMYYYYMMDD{lead.id:06d}",
    }
    approval = create_approval_instance(
        db,
        approval_type="crm_lead_convert",
        resource_type="crm_lead",
        resource_id=str(lead.id),
        title=f"客户线索转正：{lead.company_name or lead.lead_name}",
        description=payload.note,
        applicant=current_user,
        current_handler_user_id=handler.id,
        priority=payload.priority,
        payload_json={
            "lead_id": lead.id,
            "lead": before,
            "before": before,
            "after": after,
            "note": payload.note,
        },
        status_value="draft",
        submit=payload.submit,
    )
    lead.status = "conversion_pending"
    lead.current_approval_id = approval.id
    lead.updated_by_user_id = current_user.id
    db.flush()
    approval_payload = dict(approval.payload_json) if isinstance(approval.payload_json, dict) else {}
    approval_payload["conversion_guard"] = lead_conversion_guard_snapshot(lead)
    approval.payload_json = jsonable_encoder(approval_payload)
    db.flush()
    write_audit_log(
        db,
        action_type="create_crm_lead_conversion_approval_draft",
        resource_type="crm_lead",
        resource_id=str(lead.id),
        user=current_user,
        request=request,
        before_data=before,
        after_data=jsonable_encoder({
            "lead": lead_audit_snapshot(db, lead),
            "approval": {
                "approval_id": approval.id,
                "approval_no": approval.approval_no,
                "status": approval.status,
                "current_handler_user_id": approval.current_handler_user_id,
            },
        }),
    )
    db.commit()
    db.refresh(approval)
    return approval


@router.post("/{lead_id}/assign", response_model=CrmLeadPublic)
def assign_lead(
    lead_id: int,
    payload: CrmLeadAssignmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.assign")),
) -> CrmLeadPublic:
    lead = _scoped_lead(db, current_user, lead_id)
    _require_active_user(db, payload.assigned_user_id, "assigned_user_id")
    before_data = jsonable_encoder(lead_audit_snapshot(db, lead))
    previous_assignee_id = lead.assigned_user_id
    now = datetime.now(timezone.utc)
    policy = get_lead_operation_policy(db)
    lead.assigned_user_id = payload.assigned_user_id
    lead.assigned_at = now if payload.assigned_user_id else None
    lead.assignment_expires_at = now + timedelta(hours=policy.assignment_hold_hours) if payload.assigned_user_id else None
    if payload.assigned_user_id is not None:
        lead.pool_status = "private"
    lead.last_activity_at = now
    lead.updated_by_user_id = current_user.id
    db.add(CrmLeadAssignmentEvent(lead_id=lead.id, event_type="assigned", from_assignee_user_id=previous_assignee_id, to_assignee_user_id=payload.assigned_user_id, assigned_by_user_id=current_user.id, note=payload.note))
    db.flush()
    write_audit_log(db, action_type="assign_crm_lead", resource_type="crm_lead", resource_id=str(lead.id), user=current_user, request=request, before_data=before_data, after_data=jsonable_encoder(lead_audit_snapshot(db, lead)))
    db.commit()
    db.refresh(lead)
    return _lead_public(db, current_user, lead)


@router.post("/{lead_id}/followups", response_model=CrmLeadFollowupPublic, status_code=status.HTTP_201_CREATED)
def create_lead_followup(
    lead_id: int,
    payload: CrmLeadFollowupCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_lead.edit")),
) -> CrmLeadFollowupPublic:
    lead = _scoped_lead(db, current_user, lead_id)
    data = payload.model_dump()
    followup_no = data.pop("followup_no") or generated_lead_code("LEADF-")
    if db.scalar(select(CrmLeadFollowup.id).where(CrmLeadFollowup.followup_no == followup_no)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lead followup number already exists")
    followup = CrmLeadFollowup(lead_id=lead.id, followup_no=followup_no, created_by_user_id=current_user.id, **data)
    before_data = jsonable_encoder(lead_followup_audit_snapshot(db, lead, None))
    lead.last_followup_at = datetime.now(timezone.utc)
    if lead.first_responded_at is None:
        lead.first_responded_at = lead.last_followup_at
    lead.last_activity_at = lead.last_followup_at
    lead.next_followup_at = followup.next_followup_at
    lead.updated_by_user_id = current_user.id
    db.add(followup)
    db.flush()
    write_audit_log(db, action_type="create_crm_lead_followup", resource_type="crm_lead_followup", resource_id=str(followup.id), user=current_user, request=request, before_data=before_data, after_data=jsonable_encoder(lead_followup_audit_snapshot(db, lead, followup)))
    db.commit()
    db.refresh(followup)
    return CrmLeadFollowupPublic.model_validate(followup)
