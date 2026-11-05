from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.models import (
    CustomerMaster,
    CustomerTag,
    CustomerTagAssignment,
    CustomerTagCatalogVersion,
    CustomerTagChangeRequest,
    CustomerTagGovernanceSettings,
    CustomerTagLegacyMapping,
    CustomerTagRecommendation,
    CustomerTagRuleVersion,
    User,
)
from app.schemas.customer_tagging import (
    CustomerTagCatalogPublic,
    CustomerTagCatalogDefinitionCreate,
    CustomerTagCatalogReplacementCreate,
    CustomerTagCatalogVersionCreate,
    CustomerTagCatalogVersionPublic,
    CustomerTagChangeRequestCreate,
    CustomerTagChangeRequestPublic,
    CustomerTagLegacyReview,
    CustomerTagProfilePublic,
    CustomerTagRecommendationDecision,
    CustomerTagRecommendationPublic,
    CustomerTagReviewRequest,
    CustomerTagRuleVersionCreate,
    CustomerTagRuleVersionPublic,
    CustomerTagSettingsPublic,
    CustomerTagSettingsUpdate,
    CustomerTagSupplementRequest,
)
from app.services.access_control_service import apply_data_scope
from app.services.audit_service import write_audit_log
from app.services.customer_tagging_service import (
    accept_recommendation,
    activate_catalog_version,
    activate_rule_version,
    create_rule_version,
    create_catalog_definition,
    create_catalog_version,
    customer_tag_profile,
    generate_purchase_recommendations,
    governance_settings,
    review_change_request,
    schedule_catalog_replacement,
    serialize_change_request,
    submit_change_request,
    supplement_change_request,
    sync_review_due_work_items,
)
from app.services.permission_service import has_permission


router = APIRouter(prefix="/customer-tagging", tags=["customer-tagging"])


def _safe_limit(value: int, maximum: int = 200) -> int:
    return max(1, min(value, maximum))


def _safe_offset(value: int) -> int:
    return max(0, value)


def _scoped_customer(db: Session, user: User, customer_code: str) -> CustomerMaster:
    stmt = apply_data_scope(
        select(CustomerMaster).where(CustomerMaster.customer_code == customer_code),
        CustomerMaster,
        db,
        user,
        "customer",
    )
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return row


@router.get("/catalog/versions", response_model=list[CustomerTagCatalogVersionPublic])
def catalog_versions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer.view", "customer_tag.catalog_manage")),
) -> list[CustomerTagCatalogVersion]:
    return list(db.scalars(select(CustomerTagCatalogVersion).order_by(CustomerTagCatalogVersion.id.desc())).all())


@router.post("/catalog/versions", response_model=CustomerTagCatalogVersionPublic, status_code=status.HTTP_201_CREATED)
def add_catalog_version(
    payload: CustomerTagCatalogVersionCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> CustomerTagCatalogVersion:
    row = create_catalog_version(db, **payload.model_dump(), operator=current_user, request=request)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer tag catalog version already exists") from exc
    db.refresh(row)
    return row


@router.get("/catalog/versions/{version_id}/tags", response_model=list[CustomerTagCatalogPublic])
def catalog_version_tags(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer.view", "customer_tag.catalog_manage")),
) -> list[CustomerTag]:
    if db.get(CustomerTagCatalogVersion, version_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer tag catalog version not found")
    return list(db.scalars(select(CustomerTag).where(CustomerTag.catalog_version_id == version_id, CustomerTag.is_formal.is_(True)).order_by(CustomerTag.category_key, CustomerTag.sort_order, CustomerTag.id)).all())


@router.post("/catalog/versions/{version_id}/tags", response_model=CustomerTagCatalogPublic, status_code=status.HTTP_201_CREATED)
def add_catalog_definition(
    version_id: int,
    payload: CustomerTagCatalogDefinitionCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> CustomerTag:
    version = db.get(CustomerTagCatalogVersion, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer tag catalog version not found")
    row = create_catalog_definition(db, version=version, values=payload.model_dump(), operator=current_user, request=request)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer tag name or stable code already exists") from exc
    db.refresh(row)
    return row


@router.post("/catalog/tags/{tag_id}/replacement", response_model=CustomerTagCatalogPublic)
def replace_catalog_definition(
    tag_id: int,
    payload: CustomerTagCatalogReplacementCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> CustomerTag:
    current = db.get(CustomerTag, tag_id)
    replacement = db.get(CustomerTag, payload.replacement_tag_id)
    if current is None or replacement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer tag definition not found")
    schedule_catalog_replacement(db, current=current, replacement=replacement, operator=current_user, request=request)
    db.commit()
    db.refresh(current)
    return current


@router.post("/catalog/versions/{version_id}/activate", response_model=CustomerTagCatalogVersionPublic)
def activate_catalog(
    version_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> CustomerTagCatalogVersion:
    version = db.get(CustomerTagCatalogVersion, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer tag catalog version not found")
    activate_catalog_version(db, version=version, operator=current_user, request=request)
    db.commit()
    db.refresh(version)
    return version


@router.get("/catalog", response_model=list[CustomerTagCatalogPublic])
def catalog(
    category_key: str | None = None,
    group_code: str | None = None,
    include_inactive: bool = False,
    include_legacy: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer.view")),
) -> list[CustomerTag]:
    stmt = select(CustomerTag).order_by(CustomerTag.category_key, CustomerTag.sort_order, CustomerTag.name)
    if not include_inactive:
        stmt = stmt.where(CustomerTag.is_active.is_(True))
    if not include_legacy:
        stmt = stmt.where(CustomerTag.is_formal.is_(True))
    if category_key:
        stmt = stmt.where(CustomerTag.category_key == category_key)
    if group_code:
        stmt = stmt.where(CustomerTag.group_code == group_code)
    return list(db.scalars(stmt).all())


@router.get("/settings", response_model=CustomerTagSettingsPublic)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer.view", "customer_tag.catalog_manage")),
) -> CustomerTagGovernanceSettings:
    row = governance_settings(db)
    db.commit()
    assert row is not None
    db.refresh(row)
    return row


@router.get("/customers")
def list_tagged_customers(
    q: str | None = None,
    category_key: str | None = None,
    group_code: str | None = None,
    tag_ids: str | None = None,
    assignment_status: str | None = None,
    owner_user_id: int | None = None,
    review_date_from: date | None = None,
    review_date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer.view")),
) -> dict[str, Any]:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(CustomerMaster).order_by(CustomerMaster.customer_code)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(CustomerMaster.customer_code.ilike(like), CustomerMaster.customer_name.ilike(like)))
    parsed_tag_ids = {
        int(value)
        for value in (tag_ids or "").split(",")
        if value.strip().isdigit()
    }
    assignment_filters = []
    if category_key:
        assignment_filters.append(CustomerTag.category_key == category_key)
    if group_code:
        assignment_filters.append(CustomerTag.group_code == group_code)
    if parsed_tag_ids:
        assignment_filters.append(CustomerTagAssignment.tag_id.in_(parsed_tag_ids))
    if assignment_status:
        assignment_filters.append(CustomerTagAssignment.status == assignment_status)
    if owner_user_id is not None:
        assignment_filters.append(CustomerTagAssignment.owner_user_id == owner_user_id)
    if review_date_from is not None:
        assignment_filters.append(CustomerTagAssignment.review_date >= review_date_from)
    if review_date_to is not None:
        assignment_filters.append(CustomerTagAssignment.review_date <= review_date_to)
    if assignment_filters:
        stmt = stmt.where(
            select(CustomerTagAssignment.id)
            .join(CustomerTag, CustomerTag.id == CustomerTagAssignment.tag_id)
            .where(CustomerTagAssignment.customer_code == CustomerMaster.customer_code, *assignment_filters)
            .exists()
        )
    stmt = apply_data_scope(stmt, CustomerMaster, db, current_user, "customer")
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    customers = list(db.scalars(stmt.offset(safe_offset).limit(safe_limit)).all())
    customer_codes = [row.customer_code for row in customers]
    assignment_rows = list(
        db.execute(
            select(CustomerTagAssignment, CustomerTag)
            .join(CustomerTag, CustomerTag.id == CustomerTagAssignment.tag_id)
            .where(
                CustomerTagAssignment.customer_code.in_(customer_codes),
                CustomerTagAssignment.status == "effective",
            )
            .order_by(CustomerTag.category_key, CustomerTag.sort_order)
        ).all()
    ) if customer_codes else []
    assignments_by_customer: dict[str, list[dict[str, Any]]] = {}
    for assignment, tag in assignment_rows:
        assignments_by_customer.setdefault(assignment.customer_code, []).append(
            {
                "assignment_id": assignment.id,
                "tag_id": tag.id,
                "tag_name": tag.name,
                "category_key": tag.category_key,
                "group_code": tag.group_code,
                "group_name": tag.group_name,
                "color_key": tag.color_key,
                "owner_user_id": assignment.owner_user_id,
                "review_date": assignment.review_date,
                "is_primary": assignment.is_primary,
            }
        )
    return {
        "items": [
            {
                "customer_code": customer.customer_code,
                "customer_name": customer.customer_name,
                "customer_type": customer.customer_type,
                "region": customer.region,
                "salesperson_name": customer.salesperson_name,
                "status": customer.status,
                "customer_tags": list(customer.customer_tags or []),
                "assignments": assignments_by_customer.get(customer.customer_code, []),
            }
            for customer in customers
        ],
        "total": int(total),
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.patch("/settings", response_model=CustomerTagSettingsPublic)
def update_settings(
    payload: CustomerTagSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> CustomerTagGovernanceSettings:
    row = governance_settings(db)
    assert row is not None
    changes = payload.model_dump(exclude_unset=True)
    for key in ("default_reviewer_user_id", "backup_reviewer_user_id"):
        if key in changes and changes[key] is not None and db.get(User, changes[key]) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"User not found: {changes[key]}")
    before = {key: getattr(row, key) for key in changes}
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by_user_id = current_user.id
    write_audit_log(db, action_type="update_customer_tag_settings", resource_type="customer_tag_settings", resource_id="default", user=current_user, request=request, before_data=before, after_data=changes)
    db.commit()
    db.refresh(row)
    return row


@router.get("/customers/{customer_code}/profile", response_model=CustomerTagProfilePublic)
def get_profile(
    customer_code: str,
    include_history: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer.view")),
) -> dict[str, Any]:
    customer = _scoped_customer(db, current_user, customer_code)
    if include_history and not has_permission(db, current_user, "customer_tag.history"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: customer_tag.history")
    sync_review_due_work_items(db, customer_code=customer_code)
    db.commit()
    return customer_tag_profile(db, customer, include_history=include_history)


@router.post("/requests", response_model=CustomerTagChangeRequestPublic, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: CustomerTagChangeRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.submit")),
) -> dict[str, Any]:
    _scoped_customer(db, current_user, payload.customer_code)
    row = submit_change_request(db, payload=payload, applicant=current_user, request=request)
    db.commit()
    db.refresh(row)
    return serialize_change_request(db, row)


@router.get("/requests")
def list_requests(
    status_value: str | None = None,
    customer_code: str | None = None,
    mine: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer_tag.submit", "customer_tag.review", "customer_tag.history")),
) -> dict[str, Any]:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(CustomerTagChangeRequest).order_by(CustomerTagChangeRequest.id.desc())
    if status_value:
        stmt = stmt.where(CustomerTagChangeRequest.status == status_value)
    if customer_code:
        stmt = stmt.where(CustomerTagChangeRequest.customer_code == customer_code)
    if mine:
        stmt = stmt.where(CustomerTagChangeRequest.applicant_user_id == current_user.id)
    elif has_permission(db, current_user, "customer_tag.review"):
        stmt = stmt.where(or_(CustomerTagChangeRequest.reviewer_user_id == current_user.id, CustomerTagChangeRequest.backup_reviewer_user_id == current_user.id))
    elif not has_permission(db, current_user, "customer_tag.history"):
        stmt = stmt.where(CustomerTagChangeRequest.applicant_user_id == current_user.id)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.offset(safe_offset).limit(safe_limit)).all())
    return {"items": [serialize_change_request(db, row) for row in rows], "total": total, "limit": safe_limit, "offset": safe_offset}


@router.get("/requests/{request_id}", response_model=CustomerTagChangeRequestPublic)
def get_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer_tag.submit", "customer_tag.review", "customer_tag.history")),
) -> dict[str, Any]:
    row = db.get(CustomerTagChangeRequest, request_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer tag request not found")
    if row.applicant_user_id != current_user.id and current_user.id not in {row.reviewer_user_id, row.backup_reviewer_user_id} and not has_permission(db, current_user, "customer_tag.history"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer tag request is outside your scope")
    return serialize_change_request(db, row)


@router.post("/requests/{request_id}/review", response_model=CustomerTagChangeRequestPublic)
def review_request(
    request_id: int,
    payload: CustomerTagReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.review")),
) -> dict[str, Any]:
    row = db.get(CustomerTagChangeRequest, request_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer tag request not found")
    review_change_request(
        db,
        request_row=row,
        decisions=[item.model_dump() for item in payload.decisions],
        reviewer=current_user,
        comment=payload.comment,
        request=request,
    )
    db.commit()
    db.refresh(row)
    return serialize_change_request(db, row)


@router.post("/requests/{request_id}/supplement", response_model=CustomerTagChangeRequestPublic)
def supplement_request(
    request_id: int,
    payload: CustomerTagSupplementRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.submit")),
) -> dict[str, Any]:
    row = db.get(CustomerTagChangeRequest, request_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer tag request not found")
    supplement_change_request(db, request_row=row, updates=[item.model_dump() for item in payload.items], applicant=current_user, comment=payload.comment)
    db.commit()
    db.refresh(row)
    return serialize_change_request(db, row)


@router.get("/customers/{customer_code}/history")
def customer_history(
    customer_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.history")),
) -> dict[str, Any]:
    customer = _scoped_customer(db, current_user, customer_code)
    requests = list(db.scalars(select(CustomerTagChangeRequest).where(CustomerTagChangeRequest.customer_code == customer_code).order_by(CustomerTagChangeRequest.id.desc())).all())
    return {"profile": customer_tag_profile(db, customer, include_history=True), "requests": [serialize_change_request(db, row) for row in requests]}


@router.get("/export")
def export_tags(
    category_key: str | None = None,
    group_code: str | None = None,
    tag_ids: str | None = None,
    status_value: str | None = "effective",
    owner_user_id: int | None = None,
    review_date_from: date | None = None,
    review_date_to: date | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.export")),
) -> Response:
    stmt = select(CustomerTagAssignment, CustomerTag, CustomerMaster).join(CustomerTag, CustomerTag.id == CustomerTagAssignment.tag_id).join(CustomerMaster, CustomerMaster.customer_code == CustomerTagAssignment.customer_code).order_by(CustomerMaster.customer_code, CustomerTag.sort_order)
    if category_key:
        stmt = stmt.where(CustomerTag.category_key == category_key)
    if group_code:
        stmt = stmt.where(CustomerTag.group_code == group_code)
    parsed_tag_ids = {int(value) for value in (tag_ids or "").split(",") if value.strip().isdigit()}
    if parsed_tag_ids:
        stmt = stmt.where(CustomerTagAssignment.tag_id.in_(parsed_tag_ids))
    if status_value:
        stmt = stmt.where(CustomerTagAssignment.status == status_value)
    if owner_user_id is not None:
        stmt = stmt.where(CustomerTagAssignment.owner_user_id == owner_user_id)
    if review_date_from is not None:
        stmt = stmt.where(CustomerTagAssignment.review_date >= review_date_from)
    if review_date_to is not None:
        stmt = stmt.where(CustomerTagAssignment.review_date <= review_date_to)
    stmt = apply_data_scope(stmt, CustomerMaster, db, current_user, "customer")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["客户编号", "客户名称", "标签大类", "标签分组", "标签名称", "属性", "来源", "依据", "生效日期", "复核日期", "状态", "责任人ID"])
    for assignment, tag, customer in db.execute(stmt).all():
        writer.writerow([customer.customer_code, customer.customer_name, tag.category_name, tag.group_name, tag.name, assignment.attribute_type, assignment.source, assignment.evidence, assignment.effective_date, assignment.review_date, assignment.status, assignment.owner_user_id])
    return Response(content="\ufeff" + buffer.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=customer-tag-profile.csv"})


@router.post("/review-reminders/sync")
def sync_reminders(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.review")),
) -> dict[str, int]:
    created = sync_review_due_work_items(db)
    db.commit()
    return {"created": created}


@router.get("/rules", response_model=list[CustomerTagRuleVersionPublic])
def list_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> list[CustomerTagRuleVersion]:
    return list(db.scalars(select(CustomerTagRuleVersion).order_by(CustomerTagRuleVersion.rule_code, CustomerTagRuleVersion.version_no.desc())).all())


@router.post("/rules", response_model=CustomerTagRuleVersionPublic, status_code=status.HTTP_201_CREATED)
def add_rule(
    payload: CustomerTagRuleVersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> CustomerTagRuleVersion:
    row = create_rule_version(db, rule_code=payload.rule_code, name=payload.name, parameters=payload.parameters_json, operator=current_user)
    db.commit()
    db.refresh(row)
    return row


@router.post("/rules/{rule_id}/activate", response_model=CustomerTagRuleVersionPublic)
def activate_rule(
    rule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> CustomerTagRuleVersion:
    row = db.get(CustomerTagRuleVersion, rule_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer tag rule version not found")
    activate_rule_version(db, row)
    write_audit_log(db, action_type="activate_customer_tag_rule", resource_type="customer_tag_rule_version", resource_id=str(row.id), user=current_user, request=request, after_data={"rule_code": row.rule_code, "version_no": row.version_no})
    db.commit()
    db.refresh(row)
    return row


@router.post("/recommendations/generate", response_model=list[CustomerTagRecommendationPublic])
def generate_recommendations(
    customer_code: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> list[dict[str, Any]]:
    rows = generate_purchase_recommendations(db, customer_code=customer_code)
    db.commit()
    tag_names = {tag.id: tag.name for tag in db.scalars(select(CustomerTag).where(CustomerTag.id.in_({row.tag_id for row in rows}))).all()} if rows else {}
    return [{**{column.name: getattr(row, column.name) for column in row.__table__.columns}, "tag_name": tag_names.get(row.tag_id)} for row in rows]


@router.get("/recommendations", response_model=list[CustomerTagRecommendationPublic])
def list_recommendations(
    customer_code: str | None = None,
    status_value: str | None = "pending",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer_tag.submit", "customer_tag.review", "customer_tag.catalog_manage")),
) -> list[dict[str, Any]]:
    stmt = (
        select(CustomerTagRecommendation, CustomerTag)
        .join(CustomerTag, CustomerTag.id == CustomerTagRecommendation.tag_id)
        .join(CustomerMaster, CustomerMaster.customer_code == CustomerTagRecommendation.customer_code)
        .order_by(CustomerTagRecommendation.id.desc())
    )
    if customer_code:
        stmt = stmt.where(CustomerTagRecommendation.customer_code == customer_code)
    if status_value:
        stmt = stmt.where(CustomerTagRecommendation.status == status_value)
    stmt = apply_data_scope(stmt, CustomerMaster, db, current_user, "customer")
    return [{**{column.name: getattr(row, column.name) for column in row.__table__.columns}, "tag_name": tag.name} for row, tag in db.execute(stmt).all()]


@router.post("/recommendations/{recommendation_id}/decision", response_model=CustomerTagChangeRequestPublic | CustomerTagRecommendationPublic)
def decide_recommendation(
    recommendation_id: int,
    payload: CustomerTagRecommendationDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.submit")),
) -> Any:
    row = db.get(CustomerTagRecommendation, recommendation_id)
    if row is None or row.status != "pending":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending recommendation not found")
    _scoped_customer(db, current_user, row.customer_code)
    if payload.decision == "reject":
        row.status = "rejected"
        row.manual_result = payload.manual_result
        row.manual_note = payload.manual_note
        row.reviewed_by_user_id = current_user.id
        row.reviewed_at = datetime.now(timezone.utc)
        db.commit()
        tag = db.get(CustomerTag, row.tag_id)
        return {**{column.name: getattr(row, column.name) for column in row.__table__.columns}, "tag_name": tag.name if tag else None}
    request_row = accept_recommendation(db, recommendation=row, operator=current_user, manual_result=payload.manual_result, manual_note=payload.manual_note, reviewer_user_id=payload.reviewer_user_id)
    db.commit()
    return serialize_change_request(db, request_row)


@router.get("/legacy-mappings")
def legacy_mappings(
    status_value: str | None = "pending",
    customer_code: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> list[dict[str, Any]]:
    stmt = select(CustomerTagLegacyMapping, CustomerTag).outerjoin(CustomerTag, CustomerTag.id == CustomerTagLegacyMapping.target_tag_id).order_by(CustomerTagLegacyMapping.id)
    if status_value:
        stmt = stmt.where(CustomerTagLegacyMapping.status == status_value)
    if customer_code:
        stmt = stmt.where(CustomerTagLegacyMapping.customer_code == customer_code)
    return [{**{column.name: getattr(mapping, column.name) for column in mapping.__table__.columns}, "target_tag_name": tag.name if tag else None} for mapping, tag in db.execute(stmt).all()]


@router.post("/legacy-mappings/{mapping_id}/review")
def review_legacy_mapping(
    mapping_id: int,
    payload: CustomerTagLegacyReview,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> dict[str, Any]:
    mapping = db.get(CustomerTagLegacyMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legacy mapping not found")
    mapping.reviewed_by_user_id = current_user.id
    mapping.reviewed_at = datetime.now(timezone.utc)
    if payload.decision != "submit":
        mapping.status = payload.decision
        db.commit()
        return {"mapping_id": mapping.id, "status": mapping.status}
    target_tag_id = payload.target_tag_id or mapping.target_tag_id
    if target_tag_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_tag_id is required")
    mapping.target_tag_id = target_tag_id
    mapping.status = "submitted"
    request_row = submit_change_request(
        db,
        payload=CustomerTagChangeRequestCreate(
            customer_code=mapping.customer_code,
            reason=f"旧标签“{mapping.legacy_tag_name}”映射复核",
            reviewer_user_id=payload.reviewer_user_id,
            items=[
                {
                    "action": "add",
                    "tag_id": target_tag_id,
                    "attribute_type": payload.attribute_type,
                    "evidence": payload.evidence,
                    "review_date": payload.review_date,
                    "owner_user_id": payload.owner_user_id,
                    "is_primary": payload.is_primary,
                    "details_json": payload.details_json,
                }
            ],
        ),
        applicant=current_user,
    )
    db.commit()
    return {"mapping_id": mapping.id, "status": mapping.status, "request": serialize_change_request(db, request_row)}
