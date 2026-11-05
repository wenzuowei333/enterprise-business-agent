from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import CrmLead, CrmLeadFollowup, CrmLeadOperationPolicy, CrmLeadProductIntent
from app.models.crm import CRM_LEAD_STATUSES


_NAME_SEPARATORS = re.compile(r"[^\w]+", re.UNICODE)
_PHONE_SEPARATORS = re.compile(r"\D+")
_FUZZY_NAME_THRESHOLD = 0.72
CONVERSION_GUARD_FIELDS = (
    "lead_no",
    "lead_name",
    "company_name",
    "contact_name",
    "contact_phone",
    "source",
    "campaign_id",
    "region",
    "address",
    "customer_group_name",
    "business_line",
    "priority",
    "owner_user_id",
    "assigned_user_id",
)

# Conversion lifecycle transitions are deliberately reserved for the approval flow.
_EDITABLE_STATUS_TRANSITIONS = {
    "draft": {"draft", "active", "qualified", "closed", "rejected"},
    "active": {"active", "qualified", "closed", "rejected"},
    "qualified": {"qualified", "active", "closed", "rejected"},
    "conversion_pending": {"conversion_pending"},
    "converted": {"converted"},
    "closed": {"closed", "active"},
    "rejected": {"rejected", "active"},
}


def normalize_lead_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    normalized = _PHONE_SEPARATORS.sub("", phone)
    if normalized.startswith("86") and len(normalized) == 13 and normalized[2] == "1":
        normalized = normalized[2:]
    return normalized or None


def normalize_lead_name(name: str | None) -> str:
    return _NAME_SEPARATORS.sub("", (name or "").casefold())


def lead_duplicate_lock_keys(*, lead_name: str | None, contact_phone: str | None) -> list[tuple[str, int]]:
    """Build deterministic PostgreSQL advisory-lock keys for exact duplicate checks."""
    normalized_name = normalize_lead_name(lead_name)
    normalized_phone = normalize_lead_phone(contact_phone)
    key_names = []
    if normalized_name:
        key_names.append(f"crm_lead:name:{normalized_name}")
    if normalized_phone:
        key_names.append(f"crm_lead:phone:{normalized_phone}")
    return [
        (
            key_name,
            int.from_bytes(hashlib.sha256(key_name.encode("utf-8")).digest()[:8], byteorder="big", signed=True),
        )
        for key_name in sorted(set(key_names))
    ]


def acquire_lead_duplicate_locks(db: Session, *, lead_name: str | None, contact_phone: str | None) -> None:
    """Serialize PostgreSQL duplicate checks; SQLite remains a compatible no-op."""
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    for _key_name, lock_key in lead_duplicate_lock_keys(lead_name=lead_name, contact_phone=contact_phone):
        db.execute(select(func.pg_advisory_xact_lock(lock_key)))


def lead_conversion_draft_lock_key(lead_id: int) -> int:
    key_name = f"crm_lead:conversion_draft:{lead_id}"
    return int.from_bytes(hashlib.sha256(key_name.encode("utf-8")).digest()[:8], byteorder="big", signed=True)


def acquire_lead_conversion_draft_lock(db: Session, *, lead_id: int) -> None:
    """Serialize conversion-draft checks for one lead on PostgreSQL."""
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    db.execute(select(func.pg_advisory_xact_lock(lead_conversion_draft_lock_key(lead_id))))


def lead_claim_lock_key(user_id: int) -> int:
    key_name = f"crm_lead:claim_quota:{user_id}"
    return int.from_bytes(hashlib.sha256(key_name.encode("utf-8")).digest()[:8], byteorder="big", signed=True)


def acquire_lead_claim_lock(db: Session, *, user_id: int) -> None:
    """Serialize per-user claim quota checks on PostgreSQL without locking the whole pool."""
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    db.execute(select(func.pg_advisory_xact_lock(lead_claim_lock_key(user_id))))


def lead_conversion_guard_snapshot(lead: CrmLead) -> dict[str, Any]:
    """Capture conversion-relevant fields after the approval draft is bound."""
    return {field_name: getattr(lead, field_name) for field_name in CONVERSION_GUARD_FIELDS}


def changed_lead_conversion_guard_fields(lead: CrmLead, guard: dict[str, Any]) -> list[str]:
    """List only fields that changed after a conversion approval was created."""
    return [
        field_name
        for field_name in CONVERSION_GUARD_FIELDS
        if guard.get(field_name) != getattr(lead, field_name)
    ]


def get_lead_operation_policy(db: Session) -> CrmLeadOperationPolicy:
    policy = db.scalar(
        select(CrmLeadOperationPolicy)
        .where(CrmLeadOperationPolicy.policy_key == "default", CrmLeadOperationPolicy.is_active.is_(True))
        .order_by(CrmLeadOperationPolicy.id.asc())
    )
    # The migration creates the persisted default. The fallback only keeps a
    # mixed-version deployment from crashing before migration is applied.
    # SQLAlchemy column defaults are applied on INSERT, so materialize every
    # value here instead of returning an unflushed object with None fields.
    return policy or CrmLeadOperationPolicy(
        policy_key="default",
        first_response_hours=24,
        next_followup_hours=72,
        assignment_hold_hours=168,
        due_soon_hours=4,
        daily_claim_limit=10,
        is_active=True,
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def lead_sla_snapshot(
    lead: CrmLead,
    policy: CrmLeadOperationPolicy,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a stable operational SLA state without changing the lead status machine."""
    current = _as_utc(now) or datetime.now(timezone.utc)
    if lead.status in {"converted", "closed", "rejected"}:
        return {"state": "normal", "phase": "closed", "deadline": None, "remaining_seconds": None}

    if lead.first_responded_at is None:
        deadline = _as_utc(lead.first_response_due_at)
        if deadline is None and lead.created_at is not None:
            deadline = _as_utc(lead.created_at) + timedelta(hours=policy.first_response_hours)
        phase = "first_response"
    else:
        deadline = _as_utc(lead.next_followup_at)
        if deadline is None and lead.last_activity_at is not None:
            deadline = _as_utc(lead.last_activity_at) + timedelta(hours=policy.next_followup_hours)
        phase = "next_followup"

    if lead.assigned_user_id is None:
        return {
            "state": "unassigned",
            "phase": phase,
            "deadline": deadline,
            "remaining_seconds": None if deadline is None else int((deadline - current).total_seconds()),
        }
    if deadline is None:
        return {"state": "normal", "phase": phase, "deadline": None, "remaining_seconds": None}

    remaining_seconds = int((deadline - current).total_seconds())
    if remaining_seconds < 0:
        state = "overdue"
    elif remaining_seconds <= policy.due_soon_hours * 3600:
        state = "due_soon"
    else:
        state = "normal"
    return {"state": state, "phase": phase, "deadline": deadline, "remaining_seconds": remaining_seconds}


def is_lead_pool_eligible(lead: CrmLead) -> bool:
    return lead.status in {"draft", "active", "qualified"} and lead.pool_status == "public" and lead.assigned_user_id is None


def lead_public_pool_projection(lead: CrmLead, policy: CrmLeadOperationPolicy, now: datetime | None = None) -> dict[str, Any]:
    """Return the strictly minimal public-pool payload; never add contact fields here."""
    return {
        "id": lead.id,
        "lead_no": lead.lead_no,
        "lead_name": lead.lead_name,
        "company_name": lead.company_name,
        "source": lead.source,
        "region": lead.region,
        "business_line": lead.business_line,
        "priority": lead.priority,
        "pool_status": lead.pool_status,
        "status": lead.status,
        "first_response_due_at": lead.first_response_due_at,
        "recycled_at": lead.recycled_at,
        "recycle_count": lead.recycle_count,
        "created_at": lead.created_at,
        "sla": lead_sla_snapshot(lead, policy, now),
    }


def find_lead_duplicate_candidates(
    db: Session,
    *,
    lead_name: str | None,
    contact_phone: str | None,
    exclude_lead_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return exact blockers and close name matches without changing any records."""
    normalized_name = normalize_lead_name(lead_name)
    normalized_phone = normalize_lead_phone(contact_phone)
    if not normalized_name and not normalized_phone:
        return []

    filters = []
    if normalized_name:
        filters.append(CrmLead.normalized_name == normalized_name)
    if normalized_phone:
        filters.append(CrmLead.normalized_phone == normalized_phone)
    exact_rows = list(db.scalars(select(CrmLead).where(or_(*filters))).all()) if filters else []

    # SequenceMatcher cannot reach the threshold outside this length range. The
    # prefilter is complete for possible fuzzy matches, including older rows.
    fuzzy_rows: list[CrmLead] = []
    if normalized_name:
        normalized_name_length = len(normalized_name)
        minimum_length = math.ceil(_FUZZY_NAME_THRESHOLD * normalized_name_length / (2 - _FUZZY_NAME_THRESHOLD))
        maximum_length = math.floor((2 - _FUZZY_NAME_THRESHOLD) * normalized_name_length / _FUZZY_NAME_THRESHOLD)
        fuzzy_rows = list(
            db.scalars(
                select(CrmLead).where(
                    func.length(CrmLead.normalized_name) >= minimum_length,
                    func.length(CrmLead.normalized_name) <= maximum_length,
                )
            ).all()
        )
    rows_by_id = {row.id: row for row in [*exact_rows, *fuzzy_rows]}
    candidates: list[dict[str, Any]] = []
    for lead in rows_by_id.values():
        if lead.id == exclude_lead_id:
            continue
        reasons: list[str] = []
        if normalized_phone and lead.normalized_phone == normalized_phone:
            reasons.append("exact_phone")
        if normalized_name and lead.normalized_name == normalized_name:
            reasons.append("exact_normalized_name")
        similarity = 0.0
        if normalized_name and lead.normalized_name:
            similarity = SequenceMatcher(None, normalized_name, lead.normalized_name).ratio()
            if similarity >= _FUZZY_NAME_THRESHOLD and "exact_normalized_name" not in reasons:
                reasons.append("similar_name")
        if reasons:
            candidates.append(
                {
                    "lead": lead,
                    "lead_id": lead.id,
                    "reasons": reasons,
                    "blocking": any(reason in {"exact_phone", "exact_normalized_name"} for reason in reasons),
                    "similarity": round(similarity, 4),
                }
            )
    candidates.sort(key=lambda item: (not item["blocking"], -item["similarity"], -item["lead_id"]))
    return candidates[: max(1, min(limit, 100))]


def validate_lead_status_transition(current_status: str, next_status: str) -> None:
    current_status = str(getattr(current_status, "value", current_status))
    next_status = str(getattr(next_status, "value", next_status))
    if current_status not in CRM_LEAD_STATUSES or next_status not in CRM_LEAD_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CRM lead status")
    if next_status not in _EDITABLE_STATUS_TRANSITIONS[current_status]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid CRM lead status transition: {current_status} -> {next_status}",
        )


def generated_lead_code(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:16].upper()}"


def lead_audit_snapshot(db: Session, lead: CrmLead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "lead_no": lead.lead_no,
        "lead_name": lead.lead_name,
        "normalized_name": lead.normalized_name,
        "company_name": lead.company_name,
        "contact_name": lead.contact_name,
        "contact_phone": lead.contact_phone,
        "normalized_phone": lead.normalized_phone,
        "source": lead.source,
        "campaign_id": lead.campaign_id,
        "region": lead.region,
        "address": lead.address,
        "customer_group_name": lead.customer_group_name,
        "business_line": lead.business_line,
        "intent_summary": lead.intent_summary,
        "status": lead.status,
        "priority": lead.priority,
        "pool_status": lead.pool_status,
        "qualification_note": lead.qualification_note,
        "owner_user_id": lead.owner_user_id,
        "assigned_user_id": lead.assigned_user_id,
        "assigned_at": lead.assigned_at,
        "assignment_expires_at": lead.assignment_expires_at,
        "first_response_due_at": lead.first_response_due_at,
        "first_responded_at": lead.first_responded_at,
        "last_activity_at": lead.last_activity_at,
        "last_followup_at": lead.last_followup_at,
        "next_followup_at": lead.next_followup_at,
        "recycled_at": lead.recycled_at,
        "recycle_count": lead.recycle_count,
        "current_approval_id": lead.current_approval_id,
        "converted_customer_code": lead.converted_customer_code,
        "converted_at": lead.converted_at,
        "converted_by_user_id": lead.converted_by_user_id,
        "created_by_user_id": lead.created_by_user_id,
        "updated_by_user_id": lead.updated_by_user_id,
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
        "product_intents": [
            {
                "id": intent.id,
                "lead_id": intent.lead_id,
                "product_code": intent.product_code,
                "product_name": intent.product_name,
                "quantity_note": intent.quantity_note,
                "interest_level": intent.interest_level,
                "note": intent.note,
                "sort_order": intent.sort_order,
                "created_at": intent.created_at,
                "updated_at": intent.updated_at,
            }
            for intent in db.scalars(
                select(CrmLeadProductIntent)
                .where(CrmLeadProductIntent.lead_id == lead.id)
                .order_by(CrmLeadProductIntent.sort_order, CrmLeadProductIntent.id)
            ).all()
        ],
    }


def lead_followup_audit_snapshot(db: Session, lead: CrmLead, followup: CrmLeadFollowup | None) -> dict[str, Any]:
    return {
        "lead": lead_audit_snapshot(db, lead),
        "followup": None
        if followup is None
        else {
            "id": followup.id,
            "lead_id": followup.lead_id,
            "followup_no": followup.followup_no,
            "content": followup.content,
            "method": followup.method,
            "outcome": followup.outcome,
            "next_action": followup.next_action,
            "next_followup_at": followup.next_followup_at,
            "created_by_user_id": followup.created_by_user_id,
            "created_at": followup.created_at,
            "updated_at": followup.updated_at,
        },
    }
