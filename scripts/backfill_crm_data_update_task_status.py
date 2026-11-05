from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import ApprovalInstance, CrmProjectCustomerTask  # noqa: E402


DATA_UPDATE_APPROVAL_TYPES = {"customer_profile_update", "customer_business_profile_update"}
ACTIVE_STATUSES = {"submitted", "under_review", "need_supplement", "approved", "completed"}


def _payload_task_id(approval: ApprovalInstance) -> int | None:
    payload = approval.payload_json if isinstance(approval.payload_json, dict) else {}
    raw_task_id = payload.get("task_id")
    if raw_task_id in {"", None}:
        return None
    try:
        return int(raw_task_id)
    except (TypeError, ValueError):
        return None


def main() -> None:
    updated_count = 0
    inspected_count = 0
    with SessionLocal() as db:
        approvals = list(
            db.scalars(
                select(ApprovalInstance)
                .where(
                    ApprovalInstance.approval_type.in_(sorted(DATA_UPDATE_APPROVAL_TYPES)),
                    ApprovalInstance.status.in_(sorted(ACTIVE_STATUSES)),
                )
                .order_by(ApprovalInstance.id.asc())
            ).all()
        )
        for approval in approvals:
            task_id = _payload_task_id(approval)
            if task_id is None:
                continue
            inspected_count += 1
            task = db.get(CrmProjectCustomerTask, task_id)
            if task is None or task.is_closed or task.status == "closed":
                continue
            changed = False
            if task.status == "not_started":
                task.status = "in_progress"
                changed = True
            if not task.minimum_action_done:
                task.minimum_action_done = True
                changed = True
            if task.latest_owner_next_status in {"", None}:
                task.latest_owner_next_status = "资料更新已提交"
                changed = True
            if task.latest_owner_next_action in {"", None}:
                task.latest_owner_next_action = "等待资料更新审批"
                changed = True
            if changed:
                updated_count += 1
        db.commit()
    print(f"inspected={inspected_count} updated={updated_count}")


if __name__ == "__main__":
    main()
