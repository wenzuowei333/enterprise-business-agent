from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import ApprovalInstance, CustomerMaster  # noqa: E402
from app.services.customer_master_service import (  # noqa: E402
    CUSTOMER_EDITABLE_FIELDS,
    build_customer_profile_patch,
    customer_audit_snapshot,
)


FIELD_LABELS = {
    "customer_name": "客户名称",
    "customer_short_name": "客户简称",
    "customer_type": "客户类型",
    "region": "所属区域",
    "salesperson_employee_code": "业务员工号",
    "salesperson_name": "当前业务员",
    "contact_name": "联系人",
    "contact_phone": "联系电话",
    "contact_channel": "微信/对接方式",
    "customer_group_name": "客户群名称",
    "customer_tags": "客户标签",
    "address": "详细地址",
    "status": "客户状态",
    "profile_updated_at": "资料更新时间",
    "base_remark": "基础备注",
}


def _payload_record(approval: ApprovalInstance) -> dict[str, Any]:
    return approval.payload_json if isinstance(approval.payload_json, dict) else {}


def _profile_record(payload: dict[str, Any]) -> dict[str, Any]:
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        return {}
    return {key: value for key, value in profile.items() if key in CUSTOMER_EDITABLE_FIELDS}


def _customer_code(approval: ApprovalInstance, payload: dict[str, Any]) -> str:
    return str(payload.get("customer_code") or approval.resource_id or "").strip()


def _fallback_change_items(profile: dict[str, Any], before_profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "field": field,
            "label": FIELD_LABELS.get(field, field),
            "before": before_profile.get(field),
            "after": after,
        }
        for field, after in profile.items()
    ]


def main() -> None:
    inspected = 0
    updated = 0
    with SessionLocal() as db:
        approvals = list(
            db.scalars(
                select(ApprovalInstance)
                .where(ApprovalInstance.approval_type == "customer_profile_update")
                .order_by(ApprovalInstance.id.asc())
            ).all()
        )
        for approval in approvals:
            payload = _payload_record(approval)
            profile = _profile_record(payload)
            if not profile:
                continue
            has_change_items = isinstance(payload.get("change_items"), list) and bool(payload.get("change_items"))
            has_before_profile = isinstance(payload.get("before_profile"), dict)
            if has_change_items and has_before_profile:
                continue

            inspected += 1
            customer_code = _customer_code(approval, payload)
            customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code)) if customer_code else None
            before_profile = payload.get("before_profile") if isinstance(payload.get("before_profile"), dict) else {}
            if not before_profile and customer is not None:
                before_profile = customer_audit_snapshot(customer)

            _, change_items = build_customer_profile_patch(before_profile, profile, FIELD_LABELS)
            if not change_items:
                change_items = _fallback_change_items(profile, before_profile)

            new_payload = dict(payload)
            if not has_before_profile:
                new_payload["before_profile"] = before_profile
            if not has_change_items:
                new_payload["change_items"] = change_items
            approval.payload_json = new_payload
            updated += 1

        db.commit()
    print(f"inspected={inspected} updated={updated}")


if __name__ == "__main__":
    main()
