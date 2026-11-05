from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    CustomerMaster,
    CustomerTag,
    CustomerTagAssignment,
    DeliveryAttachment,
    DeliveryEvent,
    DeliveryTask,
    ProductMaster,
    SalesOrder,
    SalesOrderLine,
    SalesOrderRequirementSnapshot,
    User,
)
from app.schemas.fulfillment import DeliveryEventCreate, SalesOrderCreate, SalesOrderLineCreate, SalesOrderUpdate
from app.services.audit_service import write_audit_log
from app.services.crm_project_service import generated_code
from app.services.customer_tagging_service import require_feature


ORDER_STATUSES = {"draft", "confirmed", "delivering", "completed", "cancelled"}
DELIVERY_STATUSES = {"pending", "planned", "delivering", "delivered", "exception", "cancelled"}
DELIVERY_TRANSITIONS = {
    "pending": {"planned", "delivering", "cancelled"},
    "planned": {"delivering", "cancelled", "exception"},
    "delivering": {"delivered", "exception", "cancelled"},
    "exception": {"planned", "delivering", "delivered", "cancelled"},
    "delivered": set(),
    "cancelled": set(),
}


def _model_values(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _customer_or_404(db: Session, customer_code: str) -> CustomerMaster:
    row = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return row


def _normalized_lines(db: Session, lines: list[SalesOrderLineCreate]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line in lines:
        product = db.scalar(select(ProductMaster).where(ProductMaster.product_code == line.product_code)) if line.product_code else None
        if line.product_code and product is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Product not found: {line.product_code}")
        result.append(
            {
                "product_code": product.product_code if product else None,
                "product_name": product.product_name if product else line.product_name.strip(),
                "quantity": line.quantity,
                "unit": line.unit or (product.unit if product else None),
                "remark": line.remark,
            }
        )
    return result


def _replace_lines(db: Session, order: SalesOrder, lines: list[SalesOrderLineCreate]) -> None:
    values = _normalized_lines(db, lines)
    db.execute(delete(SalesOrderLine).where(SalesOrderLine.order_id == order.id))
    for index, value in enumerate(values, start=1):
        db.add(SalesOrderLine(order_id=order.id, line_no=index, **value))


def create_order(
    db: Session,
    *,
    payload: SalesOrderCreate,
    operator: User,
    source: str = "web",
    request: Any | None = None,
) -> SalesOrder:
    require_feature(db, "fulfillment_enabled")
    customer = _customer_or_404(db, payload.customer_code)
    if payload.external_order_no and db.scalar(select(SalesOrder.id).where(SalesOrder.external_order_no == payload.external_order_no)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="External order number already exists")
    order = SalesOrder(
        order_no=generated_code("SO"),
        external_order_no=payload.external_order_no,
        customer_code=customer.customer_code,
        customer_name_snapshot=customer.customer_name,
        source=source,
        status="draft",
        planned_delivery_at=payload.planned_delivery_at,
        delivery_address=payload.delivery_address or customer.address,
        temporary_requirements_json=jsonable_encoder([item.model_dump() for item in payload.temporary_requirements]),
        created_by_user_id=operator.id,
        updated_by_user_id=operator.id,
    )
    db.add(order)
    db.flush()
    _replace_lines(db, order, payload.lines)
    write_audit_log(
        db,
        action_type="create_sales_order",
        resource_type="sales_order",
        resource_id=str(order.id),
        user=operator,
        request=request,
        after_data=jsonable_encoder({"order_no": order.order_no, "customer_code": order.customer_code, "source": source, "line_count": len(payload.lines)}),
    )
    return order


def update_order(
    db: Session,
    *,
    order: SalesOrder,
    payload: SalesOrderUpdate,
    operator: User,
    request: Any | None = None,
) -> SalesOrder:
    if order.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft orders can be edited")
    values = payload.model_dump(exclude_unset=True)
    before = jsonable_encoder({"planned_delivery_at": order.planned_delivery_at, "delivery_address": order.delivery_address, "temporary_requirements": order.temporary_requirements_json})
    if "planned_delivery_at" in values:
        order.planned_delivery_at = payload.planned_delivery_at
    if "delivery_address" in values:
        order.delivery_address = payload.delivery_address
    if "temporary_requirements" in values:
        order.temporary_requirements_json = jsonable_encoder([item.model_dump() for item in payload.temporary_requirements or []])
    if payload.lines is not None:
        _replace_lines(db, order, payload.lines)
    order.updated_by_user_id = operator.id
    write_audit_log(
        db,
        action_type="update_sales_order",
        resource_type="sales_order",
        resource_id=str(order.id),
        user=operator,
        request=request,
        before_data=before,
        after_data=jsonable_encoder({"planned_delivery_at": order.planned_delivery_at, "delivery_address": order.delivery_address, "temporary_requirements": order.temporary_requirements_json}),
    )
    return order


def cancel_order(
    db: Session,
    *,
    order: SalesOrder,
    operator: User,
    reason: str,
    request: Any | None = None,
) -> None:
    require_feature(db, "fulfillment_enabled")
    delivery = db.scalar(select(DeliveryTask).where(DeliveryTask.order_id == order.id))
    if order.status == "draft":
        if delivery is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft order cannot have a delivery task")
    elif order.status == "confirmed":
        if delivery is None or delivery.status not in {"pending", "planned"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pre-dispatch orders can be cancelled")
    else:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft or pre-dispatch orders can be cancelled")

    before = {"order_status": order.status, "delivery_status": delivery.status if delivery else None}
    now = datetime.now(timezone.utc)
    order.status = "cancelled"
    order.cancelled_at = now
    order.updated_by_user_id = operator.id
    if delivery is not None:
        previous_delivery_status = delivery.status
        delivery.status = "cancelled"
        db.add(
            DeliveryEvent(
                delivery_id=delivery.id,
                event_type="cancel",
                from_status=previous_delivery_status,
                to_status="cancelled",
                note=reason,
                operator_user_id=operator.id,
            )
        )
    write_audit_log(
        db,
        action_type="cancel_sales_order",
        resource_type="sales_order",
        resource_id=str(order.id),
        user=operator,
        request=request,
        before_data=before,
        after_data={"order_status": "cancelled", "delivery_status": "cancelled" if delivery else None, "reason": reason},
    )


def current_delivery_requirements(db: Session, customer_code: str) -> list[dict[str, Any]]:
    rows = list(
        db.execute(
            select(CustomerTagAssignment, CustomerTag)
            .join(CustomerTag, CustomerTag.id == CustomerTagAssignment.tag_id)
            .where(
                CustomerTagAssignment.customer_code == customer_code,
                CustomerTagAssignment.status == "effective",
                CustomerTagAssignment.attribute_type == "long_term",
                CustomerTag.category_key == "delivery_requirement",
                CustomerTag.is_active.is_(True),
            )
            .order_by(CustomerTag.sort_order, CustomerTagAssignment.id)
        ).all()
    )
    return [
        {
            "tag_id": tag.id,
            "tag_code": tag.stable_code,
            "tag_name": tag.name,
            "group_code": tag.group_code,
            "mutual_exclusion_key": tag.mutual_exclusion_key,
            "source_type": "long_term",
            "requirement_json": assignment.details_json or {},
            "source_assignment_id": assignment.id,
        }
        for assignment, tag in rows
    ]


def _temporary_requirements(db: Session, order: SalesOrder) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in order.temporary_requirements_json or []:
        if not isinstance(raw, dict):
            continue
        tag = db.get(CustomerTag, raw.get("tag_id")) if raw.get("tag_id") else None
        if tag is not None and (not tag.is_formal or tag.category_key != "delivery_requirement" or not tag.is_active):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Temporary delivery tag is unavailable: {raw.get('tag_id')}")
        if tag is not None and "temporary" not in ((tag.applicability_json or {}).get("attribute_types") or []):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Delivery tag does not support temporary use: {tag.name}")
        result.append(
            {
                "tag_id": tag.id if tag else None,
                "tag_code": tag.stable_code if tag else None,
                "tag_name": tag.name if tag else str(raw.get("tag_name") or "").strip(),
                "group_code": tag.group_code if tag else raw.get("group_code"),
                "mutual_exclusion_key": tag.mutual_exclusion_key if tag else None,
                "source_type": "temporary",
                "requirement_json": raw.get("details") if isinstance(raw.get("details"), dict) else {},
                "source_assignment_id": None,
            }
        )
    return result


def _validate_requirement_conflicts(long_term: list[dict[str, Any]], temporary: list[dict[str, Any]]) -> None:
    long_by_mutex = {item["mutual_exclusion_key"]: item for item in long_term if item.get("mutual_exclusion_key")}
    conflicts = [
        {"long_term": long_by_mutex[item["mutual_exclusion_key"]]["tag_name"], "temporary": item["tag_name"]}
        for item in temporary
        if item.get("mutual_exclusion_key") in long_by_mutex
        and item.get("tag_id") != long_by_mutex[item["mutual_exclusion_key"]].get("tag_id")
    ]
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Long-term and temporary delivery requirements conflict; choose one before confirmation", "conflicts": conflicts},
        )


def target_requirements(db: Session, order: SalesOrder) -> list[dict[str, Any]]:
    long_term = current_delivery_requirements(db, order.customer_code)
    temporary = _temporary_requirements(db, order)
    _validate_requirement_conflicts(long_term, temporary)
    return [*long_term, *temporary]


def requirement_diff(db: Session, order: SalesOrder) -> dict[str, list[dict[str, Any]]]:
    current = list(
        db.scalars(
            select(SalesOrderRequirementSnapshot).where(
                SalesOrderRequirementSnapshot.order_id == order.id,
                SalesOrderRequirementSnapshot.snapshot_version == order.requirement_snapshot_version,
            )
        ).all()
    ) if order.requirement_snapshot_version else []
    target = target_requirements(db, order)
    old = {(row.tag_code or row.tag_name, row.source_type): {"tag_name": row.tag_name, "source_type": row.source_type, "requirement_json": row.requirement_json or {}} for row in current}
    new = {(item.get("tag_code") or item["tag_name"], item["source_type"]): {"tag_name": item["tag_name"], "source_type": item["source_type"], "requirement_json": item.get("requirement_json") or {}} for item in target}
    return {
        "added": [new[key] for key in new.keys() - old.keys()],
        "removed": [old[key] for key in old.keys() - new.keys()],
        "changed": [
            {"before": old[key], "after": new[key]}
            for key in new.keys() & old.keys()
            if new[key] != old[key]
        ],
    }


def snapshot_requirements(db: Session, order: SalesOrder) -> list[SalesOrderRequirementSnapshot]:
    target = target_requirements(db, order)
    version = order.requirement_snapshot_version + 1
    rows: list[SalesOrderRequirementSnapshot] = []
    for item in target:
        row = SalesOrderRequirementSnapshot(
            order_id=order.id,
            snapshot_version=version,
            tag_id=item.get("tag_id"),
            tag_code=item.get("tag_code"),
            tag_name=item["tag_name"],
            group_code=item.get("group_code"),
            source_type=item["source_type"],
            requirement_json=item.get("requirement_json") or {},
            source_assignment_id=item.get("source_assignment_id"),
        )
        db.add(row)
        rows.append(row)
    order.requirement_snapshot_version = version
    db.flush()
    return rows


def confirm_order(db: Session, *, order: SalesOrder, operator: User, request: Any | None = None) -> DeliveryTask:
    require_feature(db, "fulfillment_enabled")
    if order.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft orders can be confirmed")
    if not order.delivery_address:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Delivery address is required before order confirmation")
    lines = list(db.scalars(select(SalesOrderLine).where(SalesOrderLine.order_id == order.id)).all())
    if not lines:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order must contain at least one line")
    snapshots = snapshot_requirements(db, order)
    now = datetime.now(timezone.utc)
    order.status = "confirmed"
    order.confirmed_at = now
    order.updated_by_user_id = operator.id
    delivery = DeliveryTask(
        delivery_no=generated_code("DEL"),
        order_id=order.id,
        status="pending",
        planned_at=order.planned_delivery_at,
        delivery_address=order.delivery_address,
        requirements_json=jsonable_encoder([
            {"tag_name": row.tag_name, "group_code": row.group_code, "source_type": row.source_type, "details": row.requirement_json or {}}
            for row in snapshots
        ]),
        created_by_user_id=operator.id,
    )
    db.add(delivery)
    db.flush()
    db.add(DeliveryEvent(delivery_id=delivery.id, event_type="created", from_status=None, to_status="pending", operator_user_id=operator.id))
    write_audit_log(
        db,
        action_type="confirm_sales_order",
        resource_type="sales_order",
        resource_id=str(order.id),
        user=operator,
        request=request,
        after_data=jsonable_encoder({"status": order.status, "snapshot_version": order.requirement_snapshot_version, "delivery_id": delivery.id}),
    )
    return delivery


def refresh_order_requirements(db: Session, *, order: SalesOrder, operator: User, request: Any | None = None) -> dict[str, list[dict[str, Any]]]:
    delivery = db.scalar(select(DeliveryTask).where(DeliveryTask.order_id == order.id))
    if order.status not in {"confirmed", "delivering"} or delivery is None or delivery.status not in {"pending", "planned"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Requirements can only be refreshed before dispatch")
    diff = requirement_diff(db, order)
    rows = snapshot_requirements(db, order)
    delivery.requirements_json = jsonable_encoder([
        {"tag_name": row.tag_name, "group_code": row.group_code, "source_type": row.source_type, "details": row.requirement_json or {}}
        for row in rows
    ])
    write_audit_log(
        db,
        action_type="refresh_sales_order_requirements",
        resource_type="sales_order",
        resource_id=str(order.id),
        user=operator,
        request=request,
        before_data={"snapshot_version": order.requirement_snapshot_version - 1},
        after_data=jsonable_encoder({"snapshot_version": order.requirement_snapshot_version, "diff": diff}),
    )
    return diff


def apply_delivery_event(
    db: Session,
    *,
    delivery: DeliveryTask,
    payload: DeliveryEventCreate,
    operator: User,
    request: Any | None = None,
) -> DeliveryEvent:
    if payload.to_status not in DELIVERY_STATUSES or payload.to_status not in DELIVERY_TRANSITIONS.get(delivery.status, set()):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Invalid delivery transition: {delivery.status} -> {payload.to_status}")
    before = delivery.status
    delivery.status = payload.to_status
    if payload.assignee_user_id is not None:
        if db.get(User, payload.assignee_user_id) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Delivery assignee not found")
        delivery.assignee_user_id = payload.assignee_user_id
    if payload.to_status == "delivered":
        delivery.signed_by = payload.signed_by
        delivery.signed_at = payload.signed_at or datetime.now(timezone.utc)
    if payload.to_status == "exception":
        delivery.exception_note = payload.note
    event = DeliveryEvent(
        delivery_id=delivery.id,
        event_type=payload.event_type,
        from_status=before,
        to_status=payload.to_status,
        note=payload.note,
        payload_json=jsonable_encoder(payload.payload_json),
        operator_user_id=operator.id,
    )
    db.add(event)
    order = db.get(SalesOrder, delivery.order_id)
    if order is not None:
        if payload.to_status == "delivering":
            order.status = "delivering"
        elif payload.to_status == "delivered":
            order.status = "completed"
            order.completed_at = datetime.now(timezone.utc)
        elif payload.to_status == "cancelled":
            order.status = "cancelled"
            order.cancelled_at = datetime.now(timezone.utc)
    write_audit_log(
        db,
        action_type="delivery_status_change",
        resource_type="delivery_task",
        resource_id=str(delivery.id),
        user=operator,
        request=request,
        before_data={"status": before},
        after_data=jsonable_encoder({"status": delivery.status, "event_type": payload.event_type, "note": payload.note}),
    )
    return event


def serialize_order(db: Session, order: SalesOrder, *, include_diff: bool = False) -> dict[str, Any]:
    lines = list(db.scalars(select(SalesOrderLine).where(SalesOrderLine.order_id == order.id).order_by(SalesOrderLine.line_no)).all())
    requirements = list(db.scalars(select(SalesOrderRequirementSnapshot).where(SalesOrderRequirementSnapshot.order_id == order.id, SalesOrderRequirementSnapshot.snapshot_version == order.requirement_snapshot_version).order_by(SalesOrderRequirementSnapshot.id)).all()) if order.requirement_snapshot_version else []
    delivery_id = db.scalar(select(DeliveryTask.id).where(DeliveryTask.order_id == order.id))
    return {
        **_model_values(order),
        "lines": [_model_values(row) for row in lines],
        "requirements": [_model_values(row) for row in requirements],
        "delivery_id": delivery_id,
        "requirement_diff": requirement_diff(db, order) if include_diff and order.requirement_snapshot_version else None,
    }


def serialize_delivery(db: Session, delivery: DeliveryTask) -> dict[str, Any]:
    order = db.get(SalesOrder, delivery.order_id)
    events = list(db.scalars(select(DeliveryEvent).where(DeliveryEvent.delivery_id == delivery.id).order_by(DeliveryEvent.id)).all())
    attachments = list(db.scalars(select(DeliveryAttachment).where(DeliveryAttachment.delivery_id == delivery.id).order_by(DeliveryAttachment.id.desc())).all())
    return {
        **_model_values(delivery),
        "order_no": order.order_no if order else None,
        "customer_code": order.customer_code if order else None,
        "customer_name": order.customer_name_snapshot if order else None,
        "events": [_model_values(row) for row in events],
        "attachments": [_model_values(row) for row in attachments],
    }
