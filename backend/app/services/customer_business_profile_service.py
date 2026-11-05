from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    CustomerBusinessProduct,
    CustomerBusinessProfile,
    CustomerBusinessProfileHistory,
    CustomerMaster,
    CustomerOwnerHistory,
    SalesDetail,
    User,
)
from app.schemas.master_data import CustomerBusinessProfileUpsert
from app.services.access_control_service import apply_data_scope, serialize_with_field_rules
from app.services.audit_service import write_audit_log
from app.services.customer_master_service import clean_customer_tags
from app.services.permission_service import has_permission

CUSTOMER_BUSINESS_UPDATE_SOURCES = {"业务员反馈", "现场拜访", "客户群信息", "订单变化", "人工核实", "电话沟通", "微信沟通", "客户群反馈", "系统整理", "其他"}
CUSTOMER_BUSINESS_UPDATE_TYPES = {"新增资料", "修正资料", "定期复核", "客户变化"}
CUSTOMER_BUSINESS_TYPES = {"餐饮", "批发", "零售", "团餐", "冻品店", "其他"}
CUSTOMER_BUSINESS_STATUS_TAGS = {"传统夫妻老婆店", "现代夫妻老婆店", "完善团队经营", "批发型客户"}
CUSTOMER_BUSINESS_PRICE_SENSITIVITY = {"高", "一般", "低", "未确认"}
CUSTOMER_BUSINESS_COOPERATION_STATUS = {"已合作", "可开发", "竞品占用", "暂不做", "暂停", "未确认"}
CUSTOMER_BUSINESS_PRODUCT_CHANGE_TYPES = {"新增", "修改", "无变化", "停用"}


def customer_business_products(db: Session, customer_code: str) -> list[CustomerBusinessProduct]:
    return list(
        db.scalars(
            select(CustomerBusinessProduct)
            .where(CustomerBusinessProduct.customer_code == customer_code)
            .order_by(CustomerBusinessProduct.sort_order, CustomerBusinessProduct.id)
        ).all()
    )


def customer_business_profile_response(
    db: Session,
    current_user: User,
    customer: CustomerMaster,
    *,
    include_history: bool = True,
) -> dict[str, Any]:
    profile = db.scalar(select(CustomerBusinessProfile).where(CustomerBusinessProfile.customer_code == customer.customer_code))
    products = customer_business_products(db, customer.customer_code) if profile else []
    history = []
    if include_history:
        history = list(
            db.scalars(
                select(CustomerBusinessProfileHistory)
                .where(CustomerBusinessProfileHistory.customer_code == customer.customer_code)
                .order_by(CustomerBusinessProfileHistory.version_no.desc(), CustomerBusinessProfileHistory.id.desc())
                .limit(5)
            ).all()
        )
    return {
        "customer": _serialize_customer(db, current_user, customer),
        "profile": profile,
        "products": products,
        "history_summary": history,
        "current_sales_products": current_sales_products(db, current_user, customer),
    }


def current_sales_products(db: Session, current_user: User, customer: CustomerMaster) -> list[dict[str, Any]]:
    if not has_permission(db, current_user, "sales_detail.view"):
        return []
    rows = _customer_sales_rows(db, current_user, customer)
    dated_rows = [(row, row.document_date or row.data_date) for row in rows if (row.document_date or row.data_date)]
    dated_rows = [
        (row, row_date)
        for row, row_date in dated_rows
        if _clean_text(row.product_code) or _clean_text(row.product_name)
    ]
    if not dated_rows:
        return []

    latest_date = max(row_date for _, row_date in dated_rows)
    current_month = _month_start(latest_date)
    next_month = _add_months(current_month, 1)
    quarter_start = _add_months(current_month, -2)
    buckets: dict[str, dict[str, Any]] = {}
    for row, row_date in dated_rows:
        if row_date < quarter_start or row_date >= next_month:
            continue
        product_code = _clean_text(row.product_code)
        product_name = _clean_text(row.product_name)
        key = product_code or f"name:{product_name}"
        if not key:
            continue
        bucket = buckets.setdefault(
            key,
            {
                "product_code": product_code,
                "product_name": product_name,
                "monthly_sales_qty": Decimal("0"),
                "quarter_sales_qty": Decimal("0"),
            },
        )
        if not bucket.get("product_name") and product_name:
            bucket["product_name"] = product_name
        if not bucket.get("product_code") and product_code:
            bucket["product_code"] = product_code
        qty = _decimal(row.sale_qty_base)
        bucket["quarter_sales_qty"] += qty
        if row_date >= current_month:
            bucket["monthly_sales_qty"] += qty

    return sorted(
        buckets.values(),
        key=lambda item: (item["quarter_sales_qty"], item["monthly_sales_qty"], item.get("product_code") or item.get("product_name") or ""),
        reverse=True,
    )[:10]


def _customer_sales_rows(db: Session, current_user: User, customer: CustomerMaster) -> list[SalesDetail]:
    def scoped_rows(stmt):
        return list(db.scalars(apply_data_scope(stmt, SalesDetail, db, current_user, "sales_detail")).all())

    if customer.customer_code:
        strong_rows = scoped_rows(select(SalesDetail).where(SalesDetail.customer_code == customer.customer_code))
        if strong_rows:
            return strong_rows
    if not customer.customer_name:
        return []
    return scoped_rows(select(SalesDetail).where(SalesDetail.customer_name == customer.customer_name))


def apply_customer_business_profile_update(
    db: Session,
    *,
    customer: CustomerMaster,
    payload: CustomerBusinessProfileUpsert,
    operator: User,
    request: Request | None = None,
    audit_action_type: str = "update_customer_business_profile",
    audit_extra: dict[str, Any] | None = None,
    recommended_products: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = db.scalar(select(CustomerBusinessProfile).where(CustomerBusinessProfile.customer_code == customer.customer_code))
    existing_products = customer_business_products(db, customer.customer_code)
    before_data = _customer_business_snapshot(profile, existing_products) if profile else None
    changes = payload.model_dump(exclude_unset=True)
    inline_recommended_products = changes.pop("recommended_products", None)
    cleaned_recommended_products = _clean_recommended_products(
        recommended_products if recommended_products is not None else inline_recommended_products
    )
    _validate_business_profile_payload(changes)

    if profile is None:
        profile = CustomerBusinessProfile(
            customer_code=customer.customer_code,
            customer_name_snapshot=customer.customer_name,
            business_customer_type=_clean_text(changes.get("business_customer_type")) or _business_customer_type_default(customer),
            confirmed_at=changes.get("confirmed_at") or date.today(),
            filled_by=_clean_text(changes.get("filled_by")) or operator.real_name or operator.username,
            update_source=_clean_text(changes.get("update_source")),
            update_type=_clean_text(changes.get("update_type")) or "新增资料",
            current_salesperson=_clean_text(changes.get("current_salesperson")) or customer.salesperson_name,
            sales_channels=_clean_sales_channels(changes.get("sales_channels", [])),
            business_status_tags=_clean_business_status_tags(changes.get("business_status_tags", [])),
            business_status_label=_clean_text(changes.get("business_status_label")),
            business_status_note=_clean_text(changes.get("business_status_note")),
            other_status_label=_clean_text(changes.get("other_status_label")),
            other_status_note=_clean_text(changes.get("other_status_note")),
            latest_update_note=_clean_text(changes.get("latest_update_note")),
            version_no=1,
            confirmed_by=_clean_text(changes.get("confirmed_by")) or operator.real_name or operator.username,
            created_by_user_id=operator.id,
            updated_by_user_id=operator.id,
        )
        db.add(profile)
    else:
        for field in [
            "business_customer_type",
            "filled_by",
            "update_source",
            "update_type",
            "current_salesperson",
            "business_status_label",
            "business_status_note",
            "other_status_label",
            "other_status_note",
            "latest_update_note",
            "confirmed_by",
        ]:
            if field in changes:
                setattr(profile, field, _clean_text(changes[field]))
        if "confirmed_at" in changes:
            profile.confirmed_at = changes["confirmed_at"]
        if "sales_channels" in changes:
            profile.sales_channels = _clean_sales_channels(changes["sales_channels"])
        if "business_status_tags" in changes:
            profile.business_status_tags = _clean_business_status_tags(changes["business_status_tags"])
        profile.customer_name_snapshot = customer.customer_name
        profile.version_no += 1
        profile.updated_by_user_id = operator.id

    db.flush()
    if "products" in changes:
        db.execute(delete(CustomerBusinessProduct).where(CustomerBusinessProduct.customer_code == customer.customer_code))
        db.flush()
        for index, item in enumerate(_clean_business_products(changes["products"], profile.confirmed_at)):
            db.add(CustomerBusinessProduct(customer_code=customer.customer_code, sort_order=index + 1, **item))
        db.flush()

    saved_products = customer_business_products(db, customer.customer_code)
    after_data = _customer_business_snapshot(profile, saved_products)
    if cleaned_recommended_products:
        after_data["recommended_products"] = cleaned_recommended_products
    changed_fields = _changed_keys(before_data or {}, after_data)
    db.add(
        CustomerBusinessProfileHistory(
            customer_code=customer.customer_code,
            version_no=profile.version_no,
            update_source=profile.update_source,
            update_type=profile.update_type,
            filled_by=profile.filled_by,
            update_note=profile.latest_update_note,
            confirmed_by=profile.confirmed_by,
            snapshot_json=after_data,
            created_by_user_id=operator.id,
        )
    )
    audit_after = {
        "version_no": profile.version_no,
        "product_count": len(saved_products),
        "recommended_product_count": len(cleaned_recommended_products),
        "product_change_counts": _business_product_change_counts(saved_products),
        "update_source": profile.update_source,
        "update_type": profile.update_type,
        "filled_by": profile.filled_by,
        "update_note": profile.latest_update_note,
        "changed_fields": changed_fields,
    }
    if audit_extra:
        audit_after.update(audit_extra)
    write_audit_log(
        db,
        action_type=audit_action_type,
        resource_type="customer_business_profile",
        resource_id=customer.customer_code,
        user=operator,
        request=request,
        before_data=before_data,
        after_data=audit_after,
    )
    return {
        **customer_business_profile_response(db, operator, customer),
        "recommended_products": cleaned_recommended_products,
        "changed_fields": changed_fields,
    }


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def _customer_completeness(data: dict[str, Any]) -> str:
    missing = []
    if not data.get("contact_phone"):
        missing.append("电话")
    if not data.get("address"):
        missing.append("地址")
    if not data.get("contact_name"):
        missing.append("联系人")
    return "完整" if not missing else "缺" + "、".join(missing)


def _historical_salespersons(db: Session, customer_code: str) -> str | None:
    rows = list(
        db.scalars(
            select(CustomerOwnerHistory.old_employee_code)
            .where(CustomerOwnerHistory.customer_code == customer_code)
            .order_by(CustomerOwnerHistory.id.desc())
            .limit(10)
        ).all()
    )
    unique = [row for row in dict.fromkeys(rows) if row]
    return "、".join(unique) if unique else None


def _serialize_customer(db: Session, current_user: User, customer: CustomerMaster) -> dict[str, Any]:
    data = serialize_with_field_rules(db, current_user, "customer", customer)
    data["customer_tags"] = clean_customer_tags(data.get("customer_tags"))
    data["base_info_completeness"] = _customer_completeness(data)
    data["historical_salespersons"] = _historical_salespersons(db, customer.customer_code)
    return data


def _validate_business_profile_payload(changes: dict[str, Any]) -> None:
    business_customer_type = _clean_text(changes.get("business_customer_type"))
    if business_customer_type and business_customer_type not in CUSTOMER_BUSINESS_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid business customer type")
    update_source = _clean_text(changes.get("update_source"))
    if update_source and update_source not in CUSTOMER_BUSINESS_UPDATE_SOURCES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid business update source")
    update_type = _clean_text(changes.get("update_type"))
    if update_type and update_type not in CUSTOMER_BUSINESS_UPDATE_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid business update type")
    for tag in _clean_business_status_tags(changes.get("business_status_tags", [])):
        if tag not in CUSTOMER_BUSINESS_STATUS_TAGS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid business status tag")
    products = changes.get("products")
    if products is None:
        return
    if len(products) > 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many business product rows")
    for row in products:
        price_sensitivity = _clean_text(row.get("price_sensitivity"))
        cooperation_status = _clean_text(row.get("cooperation_status"))
        change_type = _clean_text(row.get("change_type"))
        if price_sensitivity and price_sensitivity not in CUSTOMER_BUSINESS_PRICE_SENSITIVITY:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid price sensitivity")
        if cooperation_status and cooperation_status not in CUSTOMER_BUSINESS_COOPERATION_STATUS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cooperation status")
        if change_type and change_type not in CUSTOMER_BUSINESS_PRODUCT_CHANGE_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid product change type")


def _clean_sales_channels(value: list | None) -> list[str]:
    if not value:
        return []
    channels = [_clean_text(str(item)) for item in value]
    return list(dict.fromkeys([item for item in channels if item]))[:50]


def _clean_business_status_tags(value: list | None) -> list[str]:
    if not value:
        return []
    tags = [_clean_text(str(item)) for item in value]
    return list(dict.fromkeys([item for item in tags if item]))[:20]


def _business_customer_type_default(customer: CustomerMaster) -> str | None:
    customer_type = _clean_text(customer.customer_type)
    if not customer_type:
        return None
    return customer_type if customer_type in CUSTOMER_BUSINESS_TYPES else "其他"


def _clean_business_products(products: list[dict[str, Any]], default_confirmed_at: date | None) -> list[dict[str, Any]]:
    cleaned_products: list[dict[str, Any]] = []
    for row in products:
        change_type = _clean_text(row.get("change_type")) or "无变化"
        cleaned = {
            "product_category": _clean_text(row.get("product_category")),
            "spec": _clean_text(row.get("spec")),
            "common_brand": _clean_text(row.get("common_brand")),
            "monthly_usage": _clean_text(row.get("monthly_usage")),
            "price_sensitivity": _clean_text(row.get("price_sensitivity")) or "未确认",
            "cooperation_status": _clean_text(row.get("cooperation_status")) or "未确认",
            "change_type": change_type,
            "opportunity_note": _clean_text(row.get("opportunity_note")),
            "last_confirmed_at": row.get("last_confirmed_at") or default_confirmed_at,
            "is_active": False if change_type == "停用" else bool(row.get("is_active", True)),
        }
        if not any(cleaned.get(field) for field in ["product_category", "spec", "common_brand", "monthly_usage", "opportunity_note"]):
            continue
        if not cleaned["product_category"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Business product category is required")
        cleaned_products.append(cleaned)
    return cleaned_products


def _clean_recommended_products(products: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not products:
        return []
    cleaned_products: list[dict[str, Any]] = []
    for row in products:
        if not isinstance(row, dict):
            continue
        cleaned = {
            "product_name": _clean_text(row.get("product_name")),
            "spec": _clean_text(row.get("spec")),
            "recommended_quote": _clean_text(row.get("recommended_quote")),
            "recommend_reason": _clean_text(row.get("recommend_reason")),
            "customer_feedback": _clean_text(row.get("customer_feedback")),
            "next_action": _clean_text(row.get("next_action")),
        }
        if any(cleaned.values()):
            cleaned_products.append(cleaned)
    return cleaned_products[:50]


def _business_product_snapshot(product: CustomerBusinessProduct) -> dict[str, Any]:
    return {
        "id": product.id,
        "product_category": product.product_category,
        "spec": product.spec,
        "common_brand": product.common_brand,
        "monthly_usage": product.monthly_usage,
        "price_sensitivity": product.price_sensitivity,
        "cooperation_status": product.cooperation_status,
        "change_type": product.change_type,
        "opportunity_note": product.opportunity_note,
        "last_confirmed_at": product.last_confirmed_at,
        "sort_order": product.sort_order,
        "is_active": product.is_active,
    }


def _customer_business_snapshot(
    profile: CustomerBusinessProfile | None,
    products: list[CustomerBusinessProduct],
) -> dict[str, Any]:
    if profile is None:
        return {"profile": None, "products": []}
    snapshot = {
        "profile": {
            "customer_code": profile.customer_code,
            "customer_name_snapshot": profile.customer_name_snapshot,
            "business_customer_type": profile.business_customer_type,
            "confirmed_at": profile.confirmed_at,
            "filled_by": profile.filled_by,
            "update_source": profile.update_source,
            "update_type": profile.update_type,
            "current_salesperson": profile.current_salesperson,
            "sales_channels": profile.sales_channels or [],
            "business_status_tags": profile.business_status_tags or [],
            "business_status_label": profile.business_status_label,
            "business_status_note": profile.business_status_note,
            "other_status_label": profile.other_status_label,
            "other_status_note": profile.other_status_note,
            "latest_update_note": profile.latest_update_note,
            "version_no": profile.version_no,
            "confirmed_by": profile.confirmed_by,
        },
        "products": [_business_product_snapshot(product) for product in products],
    }
    return jsonable_encoder(snapshot)


def _business_product_change_counts(products: list[CustomerBusinessProduct]) -> dict[str, int]:
    counts = {key: 0 for key in CUSTOMER_BUSINESS_PRODUCT_CHANGE_TYPES}
    for product in products:
        change_type = product.change_type or "无变化"
        counts[change_type] = counts.get(change_type, 0) + 1
    return counts


def _changed_keys(before_data: dict[str, Any], after_data: dict[str, Any]) -> list[str]:
    before_profile = before_data.get("profile") or {}
    after_profile = after_data.get("profile") or {}
    keys = sorted(set(before_profile) | set(after_profile))
    changed = [key for key in keys if before_profile.get(key) != after_profile.get(key)]
    if before_data.get("products", []) != after_data.get("products", []):
        changed.append("products")
    if before_data.get("recommended_products", []) != after_data.get("recommended_products", []):
        changed.append("recommended_products")
    return changed
