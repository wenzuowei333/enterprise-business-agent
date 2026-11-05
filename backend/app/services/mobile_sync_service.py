from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CrmLead, CrmProjectCustomerTask, User
from app.services.crm_access_service import crm_lead_scope_filter, crm_task_scope_filter


def normalize_mobile_operation_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def mobile_operation_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(normalize_mobile_operation_payload(payload).encode("utf-8")).hexdigest()


def mobile_scope_revision(
    *,
    user_id: int,
    role: str,
    permissions: list[str],
    resource_keys: list[str],
) -> str:
    raw = normalize_mobile_operation_payload(
        {
            "user_id": user_id,
            "role": role,
            "permissions": sorted(set(permissions)),
            "resource_keys": sorted(set(resource_keys)),
        }
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def current_mobile_scope_revision(
    db: Session,
    user: User,
    permissions: list[str],
    *,
    include_leads: bool | None = None,
) -> str:
    if include_leads is None:
        include_leads = settings.mobile_feature_lead_pool
    task_ids = list(
        db.scalars(
            crm_task_scope_filter(
                select(CrmProjectCustomerTask.id),
                db,
                user,
            ).order_by(CrmProjectCustomerTask.id.asc())
        ).all()
    )
    lead_ids = []
    if "crm_lead.view" in permissions and include_leads:
        lead_ids = list(
            db.scalars(
                crm_lead_scope_filter(
                    select(CrmLead.id),
                    db,
                    user,
                ).order_by(CrmLead.id.asc())
            ).all()
        )
    return mobile_scope_revision(
        user_id=user.id,
        role=user.role,
        permissions=permissions,
        resource_keys=[
            *[f"task:{task_id}" for task_id in task_ids],
            f"mobile_lead_pool:{int(include_leads)}",
            *[f"lead:{lead_id}" for lead_id in lead_ids],
        ],
    )


def parse_sync_cursor(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_newer_than_cursor(value: Any, cursor: datetime | None) -> bool:
    if cursor is None or value is None:
        return cursor is None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    if not isinstance(value, datetime):
        return False
    normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return normalized > cursor
