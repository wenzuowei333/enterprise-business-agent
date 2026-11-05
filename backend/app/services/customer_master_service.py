from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models import CustomerMaster, User
from app.schemas.master_data import CustomerMasterUpdate
from app.services.audit_service import write_audit_log
from app.services.customer_identity_service import assert_customer_identity_available
from app.services.customer_tag_service import canonicalize_customer_tags


CUSTOMER_EDITABLE_FIELDS = {
    "customer_name",
    "customer_short_name",
    "customer_type",
    "region",
    "salesperson_employee_code",
    "salesperson_name",
    "contact_name",
    "contact_phone",
    "contact_channel",
    "customer_group_name",
    "customer_tags",
    "address",
    "status",
    "profile_updated_at",
    "base_remark",
}

CUSTOMER_STATUS_VALUES = {"active", "disabled", "dormant", "lost", "pending", "closed"}


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def clean_customer_tags(value: list | None) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        tag = clean_text(str(item))
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:20]


def normalize_customer_profile_update_value(field: str, value: Any) -> Any:
    if field == "customer_tags":
        return clean_customer_tags(value if isinstance(value, list) else [])
    if isinstance(value, str):
        return clean_text(value)
    return value


def build_customer_profile_patch(
    before_data: dict[str, Any] | None,
    incoming_data: dict[str, Any],
    labels: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    before = before_data or {}
    label_map = labels or {}
    patch: dict[str, Any] = {}
    change_items: list[dict[str, Any]] = []
    for field, raw_after in incoming_data.items():
        if field not in CUSTOMER_EDITABLE_FIELDS:
            continue
        after_value = normalize_customer_profile_update_value(field, raw_after)
        before_value = normalize_customer_profile_update_value(field, before.get(field))
        encoded_before = jsonable_encoder(before_value)
        encoded_after = jsonable_encoder(after_value)
        if encoded_before == encoded_after:
            continue
        patch[field] = after_value
        change_items.append({
            "field": field,
            "label": label_map.get(field, field),
            "before": encoded_before,
            "after": encoded_after,
        })
    return patch, change_items


def customer_profile_patch_from_change_items(change_items: Any) -> dict[str, Any]:
    if not isinstance(change_items, list):
        return {}
    patch: dict[str, Any] = {}
    for item in change_items:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        if not isinstance(field, str) or field not in CUSTOMER_EDITABLE_FIELDS or "after" not in item:
            continue
        patch[field] = normalize_customer_profile_update_value(field, item.get("after"))
    return patch


def customer_audit_snapshot(customer: CustomerMaster) -> dict:
    return {
        "customer_code": customer.customer_code,
        "customer_name": customer.customer_name,
        "customer_short_name": customer.customer_short_name,
        "customer_type": customer.customer_type,
        "region": customer.region,
        "salesperson_employee_code": customer.salesperson_employee_code,
        "salesperson_name": customer.salesperson_name,
        "contact_name": customer.contact_name,
        "contact_phone": customer.contact_phone,
        "contact_channel": customer.contact_channel,
        "customer_group_name": customer.customer_group_name,
        "customer_tags": clean_customer_tags(customer.customer_tags),
        "address": customer.address,
        "status": customer.status,
        "profile_updated_at": customer.profile_updated_at.isoformat() if customer.profile_updated_at else None,
        "base_remark": customer.base_remark,
    }


def apply_customer_master_update(
    db: Session,
    *,
    customer: CustomerMaster,
    payload: CustomerMasterUpdate,
    operator: User,
    audit_action_type: str,
    audit_extra: dict[str, Any] | None = None,
    request: Request | None = None,
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True)
    if "customer_code" in changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer code cannot be changed")
    if "customer_name" in changes and not clean_text(changes["customer_name"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer name is required")
    if "status" in changes and changes["status"] not in CUSTOMER_STATUS_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid customer status")
    if "contact_phone" in changes and changes["contact_phone"] and len(str(changes["contact_phone"]).strip()) > 80:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contact phone is too long")
    if "customer_tags" in changes:
        changes["customer_tags"] = canonicalize_customer_tags(
            db,
            changes["customer_tags"],
            created_by_user_id=operator.id,
        )

    next_customer_name = normalize_customer_profile_update_value(
        "customer_name",
        changes["customer_name"],
    ) if "customer_name" in changes else customer.customer_name
    next_contact_phone = normalize_customer_profile_update_value(
        "contact_phone",
        changes["contact_phone"],
    ) if "contact_phone" in changes else customer.contact_phone
    if (
        next_customer_name != customer.customer_name
        or next_contact_phone != customer.contact_phone
    ):
        assert_customer_identity_available(
            db,
            customer_name=next_customer_name,
            contact_phone=next_contact_phone,
            exclude_customer_code=customer.customer_code,
        )

    before_data = customer_audit_snapshot(customer)
    changed = False
    changed_fields: list[str] = []
    for field, value in changes.items():
        if field not in CUSTOMER_EDITABLE_FIELDS:
            continue
        next_value = normalize_customer_profile_update_value(field, value)
        if getattr(customer, field) != next_value:
            setattr(customer, field, next_value)
            changed = True
            changed_fields.append(field)

    if changed and "profile_updated_at" not in changes:
        customer.profile_updated_at = datetime.now(timezone.utc)
        if "profile_updated_at" not in changed_fields:
            changed_fields.append("profile_updated_at")
    audit_log = None
    if changed:
        if audit_action_type == "approval_update_customer_profile":
            customer.source = "crm_approval"
        elif audit_action_type == "crm_customer_profile_update_direct":
            customer.source = "crm_profile_update"
        else:
            customer.source = customer.source or "manual"
        after_data = customer_audit_snapshot(customer)
        if audit_extra:
            after_data = {**after_data, "audit_extra": audit_extra}
        audit_log = write_audit_log(
            db,
            action_type=audit_action_type,
            resource_type="customer",
            resource_id=customer.customer_code,
            user=operator,
            request=request,
            before_data=before_data,
            after_data=after_data,
        )
    return {
        "customer": customer,
        "changed": changed,
        "changed_fields": changed_fields,
        "before_data": before_data,
        "after_data": customer_audit_snapshot(customer),
        "audit_log": audit_log,
    }
