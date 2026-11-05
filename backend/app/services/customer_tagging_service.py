from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from statistics import mean, pstdev
from typing import Any

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ApprovalInstance,
    CustomerMaster,
    CustomerTag,
    CustomerTagAssignment,
    CustomerTagCatalogVersion,
    CustomerTagChangeItem,
    CustomerTagChangeRequest,
    CustomerTagGovernanceSettings,
    CustomerTagLegacyMapping,
    CustomerTagRecommendation,
    CustomerTagRuleVersion,
    SalesDetail,
    User,
    WorkItem,
)
from app.schemas.customer_tagging import CustomerTagChangeItemCreate, CustomerTagChangeRequestCreate
from app.services.approval_service import create_approval_instance, transition_approval
from app.services.audit_service import write_audit_log
from app.services.crm_project_service import generated_code
from app.services.customer_tag_service import normalized_tag_name


EFFECTIVE_ASSIGNMENT_STATUSES = {"effective"}
TERMINAL_ASSIGNMENT_STATUSES = {"expired", "cancelled", "superseded"}
ITEM_REVIEW_STATUSES = {"approved", "need_supplement", "rejected"}


def governance_settings(db: Session, *, create: bool = True) -> CustomerTagGovernanceSettings | None:
    row = db.scalar(select(CustomerTagGovernanceSettings).where(CustomerTagGovernanceSettings.settings_key == "default"))
    if row is None and create:
        row = CustomerTagGovernanceSettings(settings_key="default")
        db.add(row)
        db.flush()
    return row


def require_feature(db: Session, feature: str) -> CustomerTagGovernanceSettings:
    settings = governance_settings(db)
    assert settings is not None
    if not bool(getattr(settings, feature, False)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Feature is not enabled: {feature}",
        )
    return settings


def create_catalog_version(
    db: Session,
    *,
    version_code: str,
    name: str,
    description: str | None,
    operator: User,
    request: Any | None = None,
) -> CustomerTagCatalogVersion:
    code = version_code.strip()
    if db.scalar(select(CustomerTagCatalogVersion.id).where(CustomerTagCatalogVersion.version_code == code)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer tag catalog version already exists")
    row = CustomerTagCatalogVersion(
        version_code=code,
        name=name.strip(),
        description=description.strip() if description else None,
        status="draft",
        created_by_user_id=operator.id,
    )
    db.add(row)
    db.flush()
    write_audit_log(
        db,
        action_type="create_customer_tag_catalog_version",
        resource_type="customer_tag_catalog_version",
        resource_id=str(row.id),
        user=operator,
        request=request,
        after_data={"version_code": row.version_code, "name": row.name, "status": row.status},
    )
    return row


def create_catalog_definition(
    db: Session,
    *,
    version: CustomerTagCatalogVersion,
    values: dict[str, Any],
    operator: User,
    request: Any | None = None,
) -> CustomerTag:
    if version.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Definitions can only be added to a draft catalog version")
    definition = dict(values)
    name = str(definition.pop("name")).strip()
    normalized = normalized_tag_name(name)
    stable_code = str(definition.pop("stable_code")).strip()
    duplicate = db.scalar(
        select(CustomerTag.id).where(
            (CustomerTag.normalized_name == normalized) | (CustomerTag.stable_code == stable_code)
        )
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer tag name or stable code already exists")
    attribute_types = list(dict.fromkeys(definition.pop("attribute_types", ["long_term"])))
    row = CustomerTag(
        **definition,
        name=name,
        stable_code=stable_code,
        normalized_name=normalized,
        applicability_json={"attribute_types": attribute_types},
        catalog_version_id=version.id,
        created_by_user_id=operator.id,
        is_formal=True,
        is_active=False,
    )
    db.add(row)
    db.flush()
    write_audit_log(
        db,
        action_type="create_customer_tag_catalog_definition",
        resource_type="customer_tag",
        resource_id=str(row.id),
        user=operator,
        request=request,
        after_data={"stable_code": row.stable_code, "name": row.name, "catalog_version_id": version.id},
    )
    return row


def schedule_catalog_replacement(
    db: Session,
    *,
    current: CustomerTag,
    replacement: CustomerTag,
    operator: User,
    request: Any | None = None,
) -> None:
    version = db.get(CustomerTagCatalogVersion, replacement.catalog_version_id) if replacement.catalog_version_id else None
    if not current.is_formal or not current.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only an active formal tag can be replaced")
    if version is None or version.status != "draft" or replacement.is_active or not replacement.is_formal:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Replacement must belong to a draft catalog version")
    if current.id == replacement.id or current.category_key != replacement.category_key:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Replacement must be a different tag in the same category")
    before = current.replaced_by_tag_id
    current.replaced_by_tag_id = replacement.id
    write_audit_log(
        db,
        action_type="schedule_customer_tag_catalog_replacement",
        resource_type="customer_tag",
        resource_id=str(current.id),
        user=operator,
        request=request,
        before_data={"replaced_by_tag_id": before},
        after_data={"replaced_by_tag_id": replacement.id, "activation_version_id": version.id},
    )


def activate_catalog_version(
    db: Session,
    *,
    version: CustomerTagCatalogVersion,
    operator: User,
    request: Any | None = None,
) -> None:
    if version.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a draft catalog version can be activated")
    new_tags = list(db.scalars(select(CustomerTag).where(CustomerTag.catalog_version_id == version.id, CustomerTag.is_formal.is_(True))).all())
    if not new_tags:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Catalog version must contain at least one definition")
    now = datetime.now(timezone.utc)
    for active_version in db.scalars(select(CustomerTagCatalogVersion).where(CustomerTagCatalogVersion.status == "active")).all():
        active_version.status = "retired"
        active_version.retired_at = now
    new_tag_ids = {tag.id for tag in new_tags}
    replaced_tags = list(
        db.scalars(
            select(CustomerTag).where(
                CustomerTag.replaced_by_tag_id.in_(new_tag_ids),
                CustomerTag.is_active.is_(True),
            )
        ).all()
    )
    for tag in new_tags:
        tag.is_active = True
    for tag in replaced_tags:
        tag.is_active = False
    version.status = "active"
    version.activated_at = now
    version.retired_at = None
    write_audit_log(
        db,
        action_type="activate_customer_tag_catalog_version",
        resource_type="customer_tag_catalog_version",
        resource_id=str(version.id),
        user=operator,
        request=request,
        after_data={
            "version_code": version.version_code,
            "activated_definition_ids": sorted(new_tag_ids),
            "retired_definition_ids": sorted(tag.id for tag in replaced_tags),
        },
    )


def _user_labels(db: Session, user_ids: set[int | None]) -> dict[int, str]:
    ids = {value for value in user_ids if value is not None}
    if not ids:
        return {}
    return {
        user.id: (user.real_name or user.username)
        for user in db.scalars(select(User).where(User.id.in_(ids))).all()
    }


def assignment_snapshot(assignment: CustomerTagAssignment, tag: CustomerTag | None = None) -> dict[str, Any]:
    return jsonable_encoder(
        {
            "id": assignment.id,
            "customer_code": assignment.customer_code,
            "tag_id": assignment.tag_id,
            "tag_code": tag.stable_code if tag else None,
            "tag_name": tag.name if tag else None,
            "attribute_type": assignment.attribute_type,
            "source": assignment.source,
            "evidence": assignment.evidence,
            "effective_date": assignment.effective_date,
            "review_date": assignment.review_date,
            "status": assignment.status,
            "owner_user_id": assignment.owner_user_id,
            "is_primary": assignment.is_primary,
            "details_json": assignment.details_json or {},
        }
    )


def serialize_assignment(
    assignment: CustomerTagAssignment,
    tag: CustomerTag,
    owner_labels: dict[int, str] | None = None,
) -> dict[str, Any]:
    return {
        **{column.name: getattr(assignment, column.name) for column in assignment.__table__.columns},
        "tag_code": tag.stable_code,
        "tag_name": tag.name,
        "category_key": tag.category_key,
        "category_name": tag.category_name,
        "group_code": tag.group_code,
        "group_name": tag.group_name,
        "color_key": tag.color_key,
        "owner_user_label": (owner_labels or {}).get(assignment.owner_user_id),
    }


def serialize_legacy_mapping(mapping: CustomerTagLegacyMapping, tag: CustomerTag | None) -> dict[str, Any]:
    return {
        **{column.name: getattr(mapping, column.name) for column in mapping.__table__.columns},
        "target_tag_name": tag.name if tag else None,
    }


def customer_tag_profile(db: Session, customer: CustomerMaster, *, include_history: bool = False) -> dict[str, Any]:
    assignment_stmt = (
        select(CustomerTagAssignment, CustomerTag)
        .join(CustomerTag, CustomerTag.id == CustomerTagAssignment.tag_id)
        .where(CustomerTagAssignment.customer_code == customer.customer_code)
        .order_by(CustomerTag.category_key, CustomerTag.group_code, CustomerTag.sort_order, CustomerTagAssignment.id)
    )
    if not include_history:
        assignment_stmt = assignment_stmt.where(CustomerTagAssignment.status == "effective")
    assignment_rows = list(db.execute(assignment_stmt).all())
    labels = _user_labels(db, {assignment.owner_user_id for assignment, _tag in assignment_rows})
    assignments = [serialize_assignment(assignment, tag, labels) for assignment, tag in assignment_rows]
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in assignments:
        by_category[str(item.get("category_key") or "legacy")].append(item)
    legacy_rows = list(
        db.execute(
            select(CustomerTagLegacyMapping, CustomerTag)
            .outerjoin(CustomerTag, CustomerTag.id == CustomerTagLegacyMapping.target_tag_id)
            .where(CustomerTagLegacyMapping.customer_code == customer.customer_code)
            .order_by(CustomerTagLegacyMapping.status, CustomerTagLegacyMapping.legacy_tag_name)
        ).all()
    )
    today = date.today()
    return {
        "customer_code": customer.customer_code,
        "customer_name": customer.customer_name,
        "assignments": assignments,
        "by_category": dict(by_category),
        "legacy_tags": [serialize_legacy_mapping(mapping, tag) for mapping, tag in legacy_rows],
        "review_due_count": sum(
            1
            for assignment, _tag in assignment_rows
            if assignment.status == "effective" and assignment.review_date and assignment.review_date <= today
        ),
        "compatibility_tags": list(customer.customer_tags or []),
    }


def external_customer_tag_profile(db: Session, customer: CustomerMaster) -> dict[str, Any]:
    profile = customer_tag_profile(db, customer, include_history=False)
    active_version = db.scalar(
        select(CustomerTagCatalogVersion)
        .where(CustomerTagCatalogVersion.status == "active")
        .order_by(CustomerTagCatalogVersion.activated_at.desc(), CustomerTagCatalogVersion.id.desc())
    )
    return {
        "catalog_version": active_version.version_code if active_version else None,
        "categories": profile["by_category"],
        "review_due_count": profile["review_due_count"],
    }


def _formal_tag_or_400(db: Session, tag_id: int) -> CustomerTag:
    tag = db.get(CustomerTag, tag_id)
    if tag is None or not tag.is_formal or not tag.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Formal customer tag is unavailable: {tag_id}")
    return tag


def _assignment_or_400(db: Session, assignment_id: int | None, customer_code: str) -> CustomerTagAssignment:
    assignment = db.get(CustomerTagAssignment, assignment_id) if assignment_id else None
    if assignment is None or assignment.customer_code != customer_code or assignment.status != "effective":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Active customer tag assignment not found: {assignment_id}")
    return assignment


def _validate_item_details(item: CustomerTagChangeItemCreate, tag: CustomerTag) -> None:
    details = item.details_json or {}
    allowed_attributes = ((tag.applicability_json or {}).get("attribute_types") or ["long_term"])
    if item.attribute_type not in allowed_attributes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name} does not support {item.attribute_type}")
    if tag.category_key == "classification" and item.attribute_type != "long_term":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer classification must be long-term")
    if tag.category_key == "product_opportunity" and item.action != "cancel":
        if not str(details.get("product_category") or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: product_category is required")
        if not str(details.get("product_name") or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: product_name is required")
        if not str(details.get("opportunity_note") or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: opportunity_note is required")
        if not str(details.get("next_action") or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: next_action is required")
        if not details.get("plan_date") or item.owner_user_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: owner_user_id and plan_date are required")
        if item.review_date is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: review_date is required")
        opportunity_status = str(details.get("opportunity_status") or "").strip()
        if opportunity_status not in {"pending", "engaging", "won", "lost"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: opportunity_status is invalid")
        if opportunity_status == "lost" and not str(details.get("invalid_reason") or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: invalid_reason is required when opportunity is lost")
    if tag.category_key == "purchase_characteristic" and item.action != "cancel":
        if item.review_date is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: review_date is required")
        required_fields = (
            "statistics_start",
            "statistics_end",
            "order_count",
            "average_purchase_interval_days",
            "average_order_quantity",
            "manual_result",
        )
        missing = [field for field in required_fields if details.get(field) is None or details.get(field) == ""]
        if missing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: purchase statistics are incomplete: {', '.join(missing)}")
        try:
            if int(details["order_count"]) < 1:
                raise ValueError
            if Decimal(str(details["average_purchase_interval_days"])) < 0 or Decimal(str(details["average_order_quantity"])) < 0:
                raise ValueError
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: purchase statistics must be non-negative numbers") from exc
    if item.attribute_type == "temporary":
        if tag.category_key != "delivery_requirement":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only delivery requirements can be temporary")
        if not str(details.get("order_no") or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{tag.name}: temporary requirement must bind an order_no")


def validate_request_items(db: Session, customer_code: str, items: list[CustomerTagChangeItemCreate]) -> dict[int, CustomerTag]:
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    tags: dict[int, CustomerTag] = {}
    effective = list(
        db.scalars(
            select(CustomerTagAssignment).where(
                CustomerTagAssignment.customer_code == customer_code,
                CustomerTagAssignment.status == "effective",
            )
        ).all()
    )
    final: dict[int | str, tuple[int, bool]] = {assignment.id: (assignment.tag_id, assignment.is_primary) for assignment in effective}
    for index, item in enumerate(items):
        tag = _formal_tag_or_400(db, item.tag_id)
        tags[item.tag_id] = tag
        _validate_item_details(item, tag)
        if item.action in {"update", "cancel"}:
            current = _assignment_or_400(db, item.assignment_id, customer_code)
            final.pop(current.id, None)
        if item.action != "cancel":
            final[f"candidate-{index}"] = (item.tag_id, item.is_primary)

    final_tag_ids = [tag_id for tag_id, _primary in final.values()]
    if len(final_tag_ids) != len(set(final_tag_ids)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate effective customer tag is not allowed")
    missing_tag_ids = set(final_tag_ids) - set(tags)
    if missing_tag_ids:
        tags.update({tag.id: tag for tag in db.scalars(select(CustomerTag).where(CustomerTag.id.in_(missing_tag_ids))).all()})
    classifications = [tag_id for tag_id in final_tag_ids if tags[tag_id].category_key == "classification"]
    if len(classifications) > 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A customer can have only one effective primary classification")
    primary_purchase: dict[str, list[int]] = defaultdict(list)
    exclusions: dict[str, list[int]] = defaultdict(list)
    for tag_id, is_primary in final.values():
        tag = tags[tag_id]
        if tag.category_key == "purchase_characteristic" and is_primary and tag.group_code:
            primary_purchase[tag.group_code].append(tag_id)
        if tag.mutual_exclusion_key:
            exclusions[tag.mutual_exclusion_key].append(tag_id)
    duplicate_primary = next((group for group, ids in primary_purchase.items() if len(ids) > 1), None)
    if duplicate_primary:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Only one primary purchase tag is allowed in group: {duplicate_primary}")
    conflict = next((key for key, ids in exclusions.items() if len(ids) > 1), None)
    if conflict:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Mutually exclusive tags cannot be effective together: {conflict}")
    return tags


def _request_item_snapshot(item: CustomerTagChangeItem, tag: CustomerTag) -> dict[str, Any]:
    return jsonable_encoder(
        {
            "item_id": item.id,
            "action": item.action,
            "assignment_id": item.assignment_id,
            "tag_id": item.tag_id,
            "tag_code": tag.stable_code,
            "tag_name": tag.name,
            "category_key": tag.category_key,
            "group_code": tag.group_code,
            "attribute_type": item.attribute_type,
            "source": item.source,
            "evidence": item.evidence,
            "effective_date": item.effective_date,
            "review_date": item.review_date,
            "owner_user_id": item.owner_user_id,
            "is_primary": item.is_primary,
            "details_json": item.details_json or {},
            "before": item.before_json,
        }
    )


def submit_change_request(
    db: Session,
    *,
    payload: CustomerTagChangeRequestCreate,
    applicant: User,
    request: Any | None = None,
) -> CustomerTagChangeRequest:
    settings = require_feature(db, "tag_workflow_enabled")
    tags = validate_request_items(db, payload.customer_code, payload.items)
    reviewer_id = payload.reviewer_user_id or settings.default_reviewer_user_id or settings.backup_reviewer_user_id
    reviewer = db.get(User, reviewer_id) if reviewer_id else None
    if reviewer is None or not reviewer.is_active or reviewer.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Configure an active default or backup customer-tag reviewer")
    row = CustomerTagChangeRequest(
        request_no=generated_code("CTAG"),
        customer_code=payload.customer_code,
        applicant_user_id=applicant.id,
        reviewer_user_id=reviewer.id,
        backup_reviewer_user_id=settings.backup_reviewer_user_id,
        status="submitted",
        reason=payload.reason,
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    created_items: list[CustomerTagChangeItem] = []
    for model in payload.items:
        current = _assignment_or_400(db, model.assignment_id, payload.customer_code) if model.action in {"update", "cancel"} else None
        item = CustomerTagChangeItem(
            request_id=row.id,
            action=model.action,
            assignment_id=model.assignment_id,
            tag_id=model.tag_id,
            attribute_type=model.attribute_type,
            source=model.source,
            evidence=model.evidence.strip(),
            effective_date=model.effective_date,
            review_date=model.review_date,
            owner_user_id=model.owner_user_id,
            is_primary=model.is_primary,
            details_json=jsonable_encoder(model.details_json),
            before_json=assignment_snapshot(current, tags.get(current.tag_id)) if current else None,
            status="pending",
        )
        db.add(item)
        db.flush()
        created_items.append(item)
    approval = create_approval_instance(
        db,
        approval_type="customer_tag_change",
        resource_type="customer_tag_change_request",
        resource_id=str(row.id),
        title=f"客户标签变更申请 {row.request_no}",
        description=payload.reason,
        applicant=applicant,
        current_handler_user_id=reviewer.id,
        priority="normal",
        payload_json={
            "request_id": row.id,
            "request_no": row.request_no,
            "customer_code": row.customer_code,
            "items": [_request_item_snapshot(item, tags[item.tag_id]) for item in created_items],
        },
        submit=True,
    )
    row.approval_instance_id = approval.id
    write_audit_log(
        db,
        action_type="submit_customer_tag_change",
        resource_type="customer_tag_change_request",
        resource_id=str(row.id),
        user=applicant,
        request=request,
        after_data=jsonable_encoder({"request_no": row.request_no, "customer_code": row.customer_code, "item_count": len(created_items)}),
    )
    return row


def _materialize_customer_cache(db: Session, customer_code: str) -> None:
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if customer is None:
        return
    assignments = list(
        db.execute(
            select(CustomerTagAssignment, CustomerTag)
            .join(CustomerTag, CustomerTag.id == CustomerTagAssignment.tag_id)
            .where(CustomerTagAssignment.customer_code == customer_code, CustomerTagAssignment.status == "effective")
            .order_by(CustomerTag.category_key, CustomerTag.sort_order)
        ).all()
    )
    approved_legacy_names = set(
        db.scalars(
            select(CustomerTagLegacyMapping.legacy_tag_name).where(
                CustomerTagLegacyMapping.customer_code == customer_code,
                CustomerTagLegacyMapping.status.in_(["approved", "submitted"]),
            )
        ).all()
    )
    assignment_history = list(
        db.execute(
            select(CustomerTagAssignment, CustomerTag)
            .join(CustomerTag, CustomerTag.id == CustomerTagAssignment.tag_id)
            .where(CustomerTagAssignment.customer_code == customer_code)
        ).all()
    )
    structured_names = {tag.name for _assignment, tag in assignment_history}
    existing = [str(name) for name in customer.customer_tags or []]
    retained_legacy = [
        name
        for name in existing
        if name not in approved_legacy_names and name not in structured_names
    ]
    effective_names = [tag.name for _assignment, tag in assignments]
    customer.customer_tags = list(dict.fromkeys([*effective_names, *retained_legacy]))
    classification = next((tag.name for _assignment, tag in assignments if tag.category_key == "classification"), None)
    if classification or any(tag.category_key == "classification" for _assignment, tag in assignment_history):
        customer.customer_type = classification


def _apply_approved_item(db: Session, item: CustomerTagChangeItem, reviewer: User) -> CustomerTagAssignment | None:
    now = datetime.now(timezone.utc)
    current = _assignment_or_400(db, item.assignment_id, db.get(CustomerTagChangeRequest, item.request_id).customer_code) if item.action in {"update", "cancel"} else None
    if current is not None:
        current.status = "cancelled" if item.action == "cancel" else "superseded"
        current.ended_at = now
    if item.action == "cancel":
        return None
    request_row = db.get(CustomerTagChangeRequest, item.request_id)
    tag = db.get(CustomerTag, item.tag_id)
    terminal_opportunity = bool(
        tag
        and tag.category_key == "product_opportunity"
        and str((item.details_json or {}).get("opportunity_status") or "") in {"won", "lost"}
    )
    assignment = CustomerTagAssignment(
        customer_code=request_row.customer_code,
        tag_id=item.tag_id,
        attribute_type=item.attribute_type,
        source=item.source,
        evidence=item.evidence,
        effective_date=item.effective_date,
        review_date=item.review_date,
        status="expired" if terminal_opportunity else "effective",
        ended_at=now if terminal_opportunity else None,
        owner_user_id=item.owner_user_id,
        is_primary=item.is_primary,
        details_json=item.details_json,
        source_request_item_id=item.id,
        approved_by_user_id=reviewer.id,
        approved_at=now,
    )
    db.add(assignment)
    db.flush()
    return assignment


def review_change_request(
    db: Session,
    *,
    request_row: CustomerTagChangeRequest,
    decisions: list[dict[str, Any]],
    reviewer: User,
    comment: str | None = None,
    request: Any | None = None,
    manage_approval: bool = True,
) -> CustomerTagChangeRequest:
    if request_row.status not in {"submitted", "partially_completed", "need_supplement"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Request is not reviewable: {request_row.status}")
    if reviewer.id not in {request_row.reviewer_user_id, request_row.backup_reviewer_user_id}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only configured customer-tag reviewer can review this request")
    items = {
        item.id: item
        for item in db.scalars(
            select(CustomerTagChangeItem)
            .where(CustomerTagChangeItem.request_id == request_row.id)
            .with_for_update()
        ).all()
    }
    decision_ids = [int(decision["item_id"]) for decision in decisions]
    if len(decision_ids) != len(set(decision_ids)) or any(item_id not in items for item_id in decision_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Review decisions contain duplicate or unknown item IDs")
    now = datetime.now(timezone.utc)
    affected: list[dict[str, Any]] = []
    ordered_decisions = sorted(
        decisions,
        key=lambda decision: 0 if items[int(decision["item_id"])].action in {"cancel", "update"} else 1,
    )
    for decision in ordered_decisions:
        item = items[int(decision["item_id"])]
        if item.status not in {"pending", "need_supplement"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Item has already been reviewed: {item.id}")
        decision_value = str(decision["decision"])
        if decision_value not in ITEM_REVIEW_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid decision: {decision_value}")
        if decision_value == "approved":
            model = CustomerTagChangeItemCreate(
                action=item.action,
                assignment_id=item.assignment_id,
                tag_id=item.tag_id,
                attribute_type=item.attribute_type,
                source=item.source,
                evidence=item.evidence,
                effective_date=item.effective_date,
                review_date=item.review_date,
                owner_user_id=item.owner_user_id,
                is_primary=item.is_primary,
                details_json=item.details_json or {},
            )
            validate_request_items(db, request_row.customer_code, [model])
            assignment = _apply_approved_item(db, item, reviewer)
            affected.append({"item_id": item.id, "assignment_id": assignment.id if assignment else None, "action": item.action})
        item.status = decision_value
        item.review_comment = decision.get("comment")
        item.reviewed_by_user_id = reviewer.id
        item.reviewed_at = now
    statuses = {item.status for item in items.values()}
    if "pending" in statuses:
        request_row.status = "partially_completed"
    elif "need_supplement" in statuses:
        request_row.status = "need_supplement"
    elif statuses == {"rejected"}:
        request_row.status = "rejected"
        request_row.reviewed_at = now
    else:
        request_row.status = "completed"
        request_row.reviewed_at = now
    approval = db.get(ApprovalInstance, request_row.approval_instance_id) if request_row.approval_instance_id else None
    if approval is not None and manage_approval:
        approval.payload_json = {
            **(approval.payload_json if isinstance(approval.payload_json, dict) else {}),
            "items": [
                {
                    **next((raw for raw in (approval.payload_json or {}).get("items", []) if raw.get("item_id") == item.id), {}),
                    "status": item.status,
                    "review_comment": item.review_comment,
                }
                for item in items.values()
            ],
        }
        approval_status = "need_supplement" if request_row.status == "need_supplement" else "rejected" if request_row.status == "rejected" else "completed" if request_row.status == "completed" else "under_review"
        transition_approval(
            db,
            approval=approval,
            operator=reviewer,
            event_type="item_review",
            to_status=approval_status,
            comment=comment,
            result_json={"request_id": request_row.id, "request_status": request_row.status, "decisions": decisions, "affected": affected},
        )
    _materialize_customer_cache(db, request_row.customer_code)
    write_audit_log(
        db,
        action_type="review_customer_tag_change",
        resource_type="customer_tag_change_request",
        resource_id=str(request_row.id),
        user=reviewer,
        request=request,
        after_data=jsonable_encoder({"status": request_row.status, "decisions": decisions, "affected": affected}),
    )
    return request_row


def supplement_change_request(
    db: Session,
    *,
    request_row: CustomerTagChangeRequest,
    updates: list[dict[str, Any]],
    applicant: User,
    comment: str | None = None,
) -> CustomerTagChangeRequest:
    if request_row.applicant_user_id != applicant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the applicant can supplement this request")
    if request_row.status != "need_supplement":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request does not need supplementation")
    items = {
        item.id: item
        for item in db.scalars(select(CustomerTagChangeItem).where(CustomerTagChangeItem.request_id == request_row.id)).all()
    }
    for update in updates:
        item = items.get(int(update["item_id"]))
        if item is None or item.status != "need_supplement":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Item does not need supplementation: {update['item_id']}")
        item.evidence = str(update["evidence"]).strip()
        item.review_date = update.get("review_date", item.review_date)
        item.owner_user_id = update.get("owner_user_id", item.owner_user_id)
        item.details_json = jsonable_encoder(update.get("details_json") or item.details_json or {})
        item.status = "pending"
        item.review_comment = None
        item.reviewed_by_user_id = None
        item.reviewed_at = None
        model = CustomerTagChangeItemCreate(
            action=item.action,
            assignment_id=item.assignment_id,
            tag_id=item.tag_id,
            attribute_type=item.attribute_type,
            source=item.source,
            evidence=item.evidence,
            effective_date=item.effective_date,
            review_date=item.review_date,
            owner_user_id=item.owner_user_id,
            is_primary=item.is_primary,
            details_json=item.details_json or {},
        )
        validate_request_items(db, request_row.customer_code, [model])
    request_row.status = "submitted"
    approval = db.get(ApprovalInstance, request_row.approval_instance_id) if request_row.approval_instance_id else None
    if approval is not None:
        transition_approval(
            db,
            approval=approval,
            operator=applicant,
            event_type="supplement",
            to_status="submitted",
            comment=comment,
        )
    return request_row


def serialize_change_request(db: Session, row: CustomerTagChangeRequest) -> dict[str, Any]:
    items = list(db.scalars(select(CustomerTagChangeItem).where(CustomerTagChangeItem.request_id == row.id).order_by(CustomerTagChangeItem.id)).all())
    tags = {
        tag.id: tag
        for tag in db.scalars(select(CustomerTag).where(CustomerTag.id.in_({item.tag_id for item in items}))).all()
    } if items else {}
    labels = _user_labels(db, {row.applicant_user_id, row.reviewer_user_id})
    customer_name = db.scalar(select(CustomerMaster.customer_name).where(CustomerMaster.customer_code == row.customer_code))
    return {
        **{column.name: getattr(row, column.name) for column in row.__table__.columns},
        "customer_name": customer_name,
        "applicant_user_label": labels.get(row.applicant_user_id),
        "reviewer_user_label": labels.get(row.reviewer_user_id),
        "items": [
            {
                **{column.name: getattr(item, column.name) for column in item.__table__.columns},
                "tag_code": tags[item.tag_id].stable_code,
                "tag_name": tags[item.tag_id].name,
                "category_key": tags[item.tag_id].category_key,
                "group_code": tags[item.tag_id].group_code,
            }
            for item in items
        ],
    }


def sync_review_due_work_items(db: Session, *, customer_code: str | None = None) -> int:
    today = date.today()
    stmt = select(CustomerTagAssignment, CustomerTag).join(CustomerTag, CustomerTag.id == CustomerTagAssignment.tag_id).where(
        CustomerTagAssignment.status == "effective",
        CustomerTagAssignment.review_date.is_not(None),
        CustomerTagAssignment.review_date <= today,
    )
    if customer_code:
        stmt = stmt.where(CustomerTagAssignment.customer_code == customer_code)
    created = 0
    for assignment, tag in db.execute(stmt).all():
        existing = db.scalar(
            select(WorkItem.id).where(
                WorkItem.source_type == "customer_tag_assignment",
                WorkItem.source_id == str(assignment.id),
                WorkItem.item_type == "tag_review_due",
                WorkItem.status.in_(["open", "processing"]),
            )
        )
        if existing:
            continue
        due_at = datetime.combine(assignment.review_date or today, time.min, tzinfo=timezone.utc)
        db.add(
            WorkItem(
                item_no=generated_code("WI"),
                source_type="customer_tag_assignment",
                source_id=str(assignment.id),
                resource_type="customer_tag_assignment",
                resource_id=str(assignment.id),
                customer_code=assignment.customer_code,
                item_type="tag_review_due",
                title=f"客户标签到期复核：{tag.name}",
                detail=assignment.evidence,
                priority="normal",
                status="open",
                assignee_user_id=assignment.owner_user_id,
                due_at=due_at,
            )
        )
        created += 1
    return created


def create_rule_version(db: Session, *, rule_code: str, name: str, parameters: dict[str, Any], operator: User) -> CustomerTagRuleVersion:
    latest = db.scalar(select(func.max(CustomerTagRuleVersion.version_no)).where(CustomerTagRuleVersion.rule_code == rule_code)) or 0
    row = CustomerTagRuleVersion(
        rule_code=rule_code,
        version_no=int(latest) + 1,
        name=name,
        status="draft",
        parameters_json=jsonable_encoder(parameters),
        created_by_user_id=operator.id,
    )
    db.add(row)
    db.flush()
    return row


def activate_rule_version(db: Session, row: CustomerTagRuleVersion) -> None:
    for old in db.scalars(select(CustomerTagRuleVersion).where(CustomerTagRuleVersion.rule_code == row.rule_code, CustomerTagRuleVersion.status == "active")).all():
        old.status = "retired"
    row.status = "active"
    row.activated_at = datetime.now(timezone.utc)


def generate_purchase_recommendations(db: Session, *, customer_code: str | None = None) -> list[CustomerTagRecommendation]:
    require_feature(db, "recommendation_enabled")
    rule = db.scalar(select(CustomerTagRuleVersion).where(CustomerTagRuleVersion.rule_code == "purchase_characteristic", CustomerTagRuleVersion.status == "active").order_by(CustomerTagRuleVersion.version_no.desc()))
    if rule is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Activate a purchase-characteristic rule version first")
    params = rule.parameters_json or {}
    window_days = max(30, min(int(params.get("window_days", 180)), 730))
    high_frequency_days = Decimal(str(params.get("high_frequency_days", 7)))
    high_quantity = Decimal(str(params.get("high_quantity", 50)))
    stability_cv = Decimal(str(params.get("stability_cv", 0.35)))
    end_date = db.scalar(select(func.max(SalesDetail.document_date)))
    if end_date is None:
        return []
    start_date = end_date - timedelta(days=window_days - 1)
    stmt = select(SalesDetail).where(SalesDetail.document_date >= start_date, SalesDetail.document_date <= end_date, SalesDetail.customer_code.is_not(None))
    if customer_code:
        stmt = stmt.where(SalesDetail.customer_code == customer_code)
    rows_by_customer: dict[str, list[SalesDetail]] = defaultdict(list)
    for row in db.scalars(stmt).all():
        rows_by_customer[str(row.customer_code)].append(row)
    tags_by_name = {tag.name: tag for tag in db.scalars(select(CustomerTag).where(CustomerTag.is_formal.is_(True))).all()}
    created: list[CustomerTagRecommendation] = []
    for code, rows in rows_by_customer.items():
        document_qty: dict[str, Decimal] = defaultdict(Decimal)
        document_dates: dict[str, date] = {}
        for row in rows:
            key = str(row.document_no or f"row-{row.id}")
            document_qty[key] += Decimal(row.sale_qty_base or row.sale_qty_unit or 0)
            if row.document_date:
                document_dates[key] = row.document_date
        dates = sorted(set(document_dates.values()))
        intervals = [(right - left).days for left, right in zip(dates, dates[1:])]
        avg_interval = Decimal(str(mean(intervals))) if intervals else Decimal(window_days)
        quantities = list(document_qty.values()) or [Decimal(0)]
        avg_quantity = sum(quantities) / Decimal(len(quantities))
        cv = Decimal(str(pstdev([float(value) for value in quantities]) / float(avg_quantity))) if len(quantities) > 1 and avg_quantity else Decimal(0)
        if avg_interval <= high_frequency_days:
            frequency_name = "高频大量" if avg_quantity >= high_quantity else "高频少量"
        else:
            frequency_name = "低频大单" if avg_quantity >= high_quantity else "低频少量"
        if avg_interval <= Decimal("1.5"):
            cycle_name = "每日采购"
        elif avg_interval <= Decimal("8"):
            cycle_name = "每周采购"
        elif avg_interval <= Decimal("18"):
            cycle_name = "半月采购"
        elif avg_interval <= Decimal("35"):
            cycle_name = "每月采购"
        else:
            cycle_name = "不定期采购"
        stability_name = "采购量相对稳定" if cv <= stability_cv else "采购量波动较大"
        metrics = {
            "statistics_start": start_date.isoformat(),
            "statistics_end": end_date.isoformat(),
            "order_count": len(document_qty),
            "average_purchase_interval_days": float(avg_interval),
            "average_order_quantity": float(avg_quantity),
            "quantity_cv": float(cv),
            "matched_rule_version": rule.version_no,
        }
        for name in (frequency_name, cycle_name, stability_name):
            tag = tags_by_name.get(name)
            if tag is None:
                continue
            existing = db.scalar(
                select(CustomerTagRecommendation.id).where(
                    CustomerTagRecommendation.customer_code == code,
                    CustomerTagRecommendation.tag_id == tag.id,
                    CustomerTagRecommendation.rule_version_id == rule.id,
                    CustomerTagRecommendation.statistics_start == start_date,
                    CustomerTagRecommendation.statistics_end == end_date,
                    CustomerTagRecommendation.status == "pending",
                )
            )
            if existing:
                continue
            confidence = min(Decimal("0.98"), Decimal("0.60") + Decimal(min(len(document_qty), 20)) / Decimal("50"))
            recommendation = CustomerTagRecommendation(
                customer_code=code,
                tag_id=tag.id,
                rule_version_id=rule.id,
                statistics_start=start_date,
                statistics_end=end_date,
                metrics_json=metrics,
                confidence=confidence,
                status="pending",
            )
            db.add(recommendation)
            created.append(recommendation)
    db.flush()
    return created


def accept_recommendation(
    db: Session,
    *,
    recommendation: CustomerTagRecommendation,
    operator: User,
    manual_result: str | None,
    manual_note: str,
    reviewer_user_id: int | None,
) -> CustomerTagChangeRequest:
    recommendation.status = "accepted"
    recommendation.manual_result = manual_result
    recommendation.manual_note = manual_note
    recommendation.reviewed_by_user_id = operator.id
    recommendation.reviewed_at = datetime.now(timezone.utc)
    return submit_change_request(
        db,
        payload=CustomerTagChangeRequestCreate(
            customer_code=recommendation.customer_code,
            reason=f"采购特征自动推荐人工确认：{manual_note}",
            reviewer_user_id=reviewer_user_id,
            items=[
                CustomerTagChangeItemCreate(
                    action="add",
                    tag_id=recommendation.tag_id,
                    source="system_recommendation",
                    evidence=f"统计区间 {recommendation.statistics_start} 至 {recommendation.statistics_end}；{manual_note}",
                    review_date=date.today() + timedelta(days=365),
                    details_json={
                        **(recommendation.metrics_json or {}),
                        "system_result": recommendation.tag_id,
                        "manual_result": manual_result or recommendation.tag_id,
                    },
                )
            ],
        ),
        applicant=operator,
    )
