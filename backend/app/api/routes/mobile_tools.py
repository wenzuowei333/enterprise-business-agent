from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.routes.crm_assistant import get_crm_assistant_runtime, list_crm_assistant_messages, send_crm_assistant_message
from app.api.routes.crm_reports import _processed_notification_ids, crm_report_notifications, process_crm_report_notification
from app.api.routes.dashboard import dashboard_overview
from app.core.database import get_db
from app.models import CrmLead, CrmProjectCustomerTask, CustomerMaster, InventoryCheckBatch, MobileTelemetryRecord, ProductMaster, ReceivableCheckResult, User
from app.schemas.crm import CrmAssistantMessageRequest, CrmReportNotificationProcessRequest
from app.schemas.mobile import MobileNotificationProcessRequest, MobileTelemetryBatch
from app.core.config import settings
from app.services.permission_service import has_permission
from app.services.crm_access_service import crm_lead_scope_filter, crm_task_scope_filter

router = APIRouter(prefix="/mobile", tags=["mobile-tools"])


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该能力仅管理员可用")


def _lead_reminders(db: Session, current_user: User, now: datetime) -> list[dict[str, Any]]:
    if not has_permission(db, current_user, "crm_lead.view"):
        return []
    leads = list(
        db.scalars(
            crm_lead_scope_filter(
                select(CrmLead).where(
                    CrmLead.next_followup_at.is_not(None),
                    CrmLead.next_followup_at <= now,
                    CrmLead.status.not_in(["conversion_pending", "converted", "closed", "rejected"]),
                ),
                db,
                current_user,
            )
            .order_by(CrmLead.next_followup_at.asc(), CrmLead.id.asc())
            .limit(80)
        ).all()
    )
    reminders = []
    for lead in leads:
        due_at = lead.next_followup_at
        if due_at is None:
            continue
        due_at = due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
        reminder_key = f"{lead.id}:{due_at.isoformat()}"
        reminders.append(
            {
                "notification_id": f"lead_followup:crm_lead:{reminder_key}",
                "notification_type": "lead_followup",
                "title": "线索跟进提醒",
                "detail": None,
                "status": "pending",
                "priority": "high" if due_at < now else "normal",
                "source_type": "crm_lead",
                "source_id": reminder_key,
                "action_path": f"/leads/{lead.id}",
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
                "due_at": due_at.isoformat(),
                "is_mine": lead.assigned_user_id == current_user.id or lead.owner_user_id == current_user.id,
            }
        )
    return reminders


@router.get("/notifications")
def mobile_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    now = datetime.now(timezone.utc)
    center = crm_report_notifications(db=db, current_user=current_user)
    items = [item.model_dump(mode="json") for item in center.items]
    lead_reminders = _lead_reminders(db, current_user, now) if settings.mobile_feature_lead_pool else []
    data_risks: list[dict[str, Any]] = []

    if has_permission(db, current_user, "inventory_check.view"):
        batch = db.scalar(
            select(InventoryCheckBatch)
            .where(InventoryCheckBatch.difference_rows > 0)
            .order_by(InventoryCheckBatch.data_date.desc().nullslast(), InventoryCheckBatch.id.desc())
            .limit(1)
        )
        if batch is not None:
            data_risks.append(
                {
                    "notification_id": f"data_risk:inventory_check:{batch.id}",
                    "notification_type": "data_risk",
                    "title": f"库存核验存在 {batch.difference_rows} 项差异",
                    "detail": f"核验日期 {batch.data_date.isoformat() if batch.data_date else '未识别'}，点击查看差异明细",
                    "status": "pending",
                    "priority": "high",
                    "source_type": "inventory_check",
                    "source_id": str(batch.id),
                    "action_path": f"/inventory?tab=check&batch_id={batch.id}",
                    "created_at": batch.created_at.isoformat() if batch.created_at else None,
                    "due_at": None,
                    "is_mine": False,
                }
            )

    if has_permission(db, current_user, "receivable.view"):
        latest_date = db.scalar(select(func.max(ReceivableCheckResult.data_date)))
        if latest_date is not None:
            difference_count = int(
                db.scalar(
                    select(func.count(ReceivableCheckResult.id)).where(ReceivableCheckResult.data_date == latest_date)
                )
                or 0
            )
            if difference_count > 0:
                data_risks.append(
                    {
                        "notification_id": f"data_risk:receivable_check:{latest_date.isoformat()}",
                        "notification_type": "data_risk",
                        "title": f"应收校验存在 {difference_count} 项差异",
                        "detail": f"核验日期 {latest_date.isoformat()}，点击查看结算单位差异",
                        "status": "pending",
                        "priority": "high",
                        "source_type": "receivable_check",
                        "source_id": latest_date.isoformat(),
                        "action_path": "/account-ledger?tab=receivable-check",
                        "created_at": None,
                        "due_at": None,
                        "is_mine": False,
                    }
                )

    processed_ids = _processed_notification_ids(db, [item["notification_id"] for item in [*data_risks, *lead_reminders]])
    for item in [*data_risks, *lead_reminders]:
        if item["notification_id"] in processed_ids:
            item["status"] = "processed"
    items.extend(lead_reminders)
    items.extend(data_risks)
    items.sort(key=lambda item: (item.get("status") == "processed", item.get("priority") not in {"urgent", "high"}))
    summary = center.summary.model_dump()
    summary["data_risk"] = len(data_risks)
    summary["lead_reminder"] = len(lead_reminders)
    summary["total"] = len(items)
    summary["pending"] = sum(1 for item in items if item.get("status") != "processed")
    summary["processed"] = len(items) - summary["pending"]
    return {"summary": summary, "items": items, "generated_at": center.generated_at.isoformat()}


@router.post("/notifications/{notification_id}/process")
def mobile_process_notification(
    notification_id: str,
    payload: MobileNotificationProcessRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    return process_crm_report_notification(
        notification_id=notification_id,
        payload=CrmReportNotificationProcessRequest(action=payload.action, note=payload.note),
        request=request,
        db=db,
        current_user=current_user,
    )


@router.get("/scan/resolve")
def mobile_scan_resolve(
    value: str = Query(min_length=1, max_length=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    query = value.strip()
    matches: list[dict[str, Any]] = []
    if has_permission(db, current_user, "product.view"):
        product = db.scalar(select(ProductMaster).where(or_(ProductMaster.barcode == query, ProductMaster.product_code == query)))
        if product is not None:
            matches.append({"type": "product", "code": product.product_code, "name": product.product_name, "barcode": product.barcode, "target": {"module": "products", "query": product.product_code}})
    can_customer_master = has_permission(db, current_user, "customer.view")
    can_linked_customer = False
    if not can_customer_master and has_permission(db, current_user, "crm_task.view"):
        task_stmt = crm_task_scope_filter(
            select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.customer_code == query),
            db,
            current_user,
        )
        can_linked_customer = db.scalar(task_stmt.limit(1)) is not None
    if can_customer_master or can_linked_customer:
        customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == query))
        if customer is not None:
            matches.append({"type": "customer", "code": customer.customer_code, "name": customer.customer_name, "target": {"module": "customers", "query": customer.customer_code}})
    match_type = matches[0]["type"] if len(matches) == 1 else ("multiple" if matches else "none")
    return {"match_type": match_type, "matches": matches, "query": query}


@router.post("/telemetry/batch")
def mobile_telemetry(
    payload: MobileTelemetryBatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    installation = payload.installation_id or "legacy-anonymous-client"
    installation_hash = hashlib.sha256(f"{settings.jwt_secret}:{installation}".encode()).hexdigest()
    rows: list[MobileTelemetryRecord] = []
    for event in payload.events:
        try:
            occurred_at = datetime.fromisoformat(event.occurred_at.replace("Z", "+00:00"))
        except ValueError:
            occurred_at = datetime.now(timezone.utc)
        rows.append(
            MobileTelemetryRecord(
                installation_hash=installation_hash,
                event_type=event.event_type,
                occurred_at=occurred_at,
                route=_safe_telemetry_route(event.route),
                code=event.code,
                duration_ms=event.duration_ms,
                app_version=event.app_version,
                device_model=event.device_model,
                android_version=event.android_version,
            )
        )
    db.add_all(rows)
    db.commit()
    return {"accepted": len(rows)}


def _safe_telemetry_route(value: str | None) -> str | None:
    if not value:
        return None
    return value.split("?", 1)[0].split("#", 1)[0][:240]


@router.get("/dashboard/overview")
def mobile_dashboard_overview(
    range_key: str = Query("7d", alias="range", pattern="^(today|7d|30d|month)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    payload = dashboard_overview(range_key=range_key, db=db, current_user=current_user)
    conclusion = payload.get("conclusion")
    if isinstance(conclusion, dict):
        return {
            **payload,
            "conclusion": conclusion.get("title") or conclusion.get("detail") or "经营数据已刷新",
            "conclusion_card": conclusion,
        }
    return payload


@router.get("/assistant/runtime")
def mobile_assistant_runtime(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _require_admin(current_user)
    return get_crm_assistant_runtime(db=db, current_user=current_user)


@router.get("/assistant/messages")
def mobile_assistant_messages(
    channel: str | None = "android",
    limit: int = Query(30, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _require_admin(current_user)
    return list_crm_assistant_messages(channel=channel, limit=limit, db=db, current_user=current_user)


@router.post("/assistant/messages")
def mobile_send_assistant_message(
    payload: CrmAssistantMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _require_admin(current_user)
    return send_crm_assistant_message(
        payload=payload.model_copy(update={"channel": "android"}),
        request=request,
        db=db,
        current_user=current_user,
    )
