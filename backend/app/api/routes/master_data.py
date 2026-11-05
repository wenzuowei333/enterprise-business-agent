import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.models import (
    AccountBalanceSnapshot,
    CrmProject,
    CrmProjectCustomerTask,
    CustomerAlias,
    CustomerBusinessProduct,
    CustomerBusinessProfile,
    CustomerBusinessProfileHistory,
    CustomerMaster,
    CustomerTag,
    CustomerOwnerHistory,
    CustomerPortraitSnapshot,
    CustomerPortraitTask,
    MasterCategoryBinding,
    MasterCategoryNode,
    ProductMaster,
    SalesDetail,
    SupplierAlias,
    SupplierMaster,
    User,
)
from app.schemas.master_data import (
    CustomerBusinessProfileHistoryPublic,
    CustomerBusinessProfileResponse,
    CustomerBusinessProfileUpsert,
    CustomerMasterCreate,
    CustomerMasterPublic,
    CustomerMasterUpdate,
    CustomerTagCreate,
    CustomerTagPublic,
    CustomerTagUpdate,
    MasterCategoryBindingCreate,
    MasterCategoryBindingPublic,
    MasterCategoryNodePublic,
    MasterCategoryNodeUpsert,
    ProductMasterPublic,
    ProductMasterCreate,
    ProductMasterUpdate,
    SupplierMasterCreate,
    SupplierMasterPublic,
    SupplierMasterUpdate,
)
from app.services.access_control_service import (
    apply_data_scope,
    get_field_permission_rules,
    serialize_many_with_field_rules,
    serialize_with_field_rules,
)
from app.services.audit_service import write_audit_log
from app.services.customer_business_profile_service import customer_business_profile_response as build_customer_business_profile_response
from app.services.customer_identity_service import assert_customer_identity_available
from app.services.customer_master_service import apply_customer_master_update, clean_customer_tags
from app.services.customer_tag_service import (
    canonicalize_customer_tags,
    create_customer_tag,
    customer_tag_usage_counts,
    update_customer_tag,
)
from app.services.master_category_service import (
    bind_resource_to_category,
    category_resource_type,
    generate_category_node_code,
    normalize_category_kind,
)
from app.services.permission_service import has_permission

router = APIRouter(prefix="/master-data", tags=["master-data"])

MASTER_STATUS_VALUES = {"active", "disabled"}
CUSTOMER_BUSINESS_UPDATE_SOURCES = {"业务员反馈", "现场拜访", "客户群信息", "订单变化", "人工核实", "电话沟通", "微信沟通", "客户群反馈", "系统整理", "其他"}
CUSTOMER_BUSINESS_UPDATE_TYPES = {"新增资料", "修正资料", "定期复核", "客户变化"}
CUSTOMER_BUSINESS_TYPES = {"餐饮", "批发", "零售", "团餐", "冻品店", "其他"}
CUSTOMER_BUSINESS_STATUS_TAGS = {"传统夫妻老婆店", "现代夫妻老婆店", "完善团队经营", "批发型客户"}
CUSTOMER_BUSINESS_PRICE_SENSITIVITY = {"高", "一般", "低", "未确认"}
CUSTOMER_BUSINESS_COOPERATION_STATUS = {"已合作", "可开发", "竞品占用", "暂不做", "暂停", "未确认"}
CUSTOMER_BUSINESS_PRODUCT_CHANGE_TYPES = {"新增", "修改", "无变化", "停用"}
CUSTOMER_ATTENTION_REASONS = (
    ("inactive", "已停用"),
    ("missing_contact", "缺联系人"),
    ("missing_phone", "缺电话"),
    ("missing_address", "缺地址"),
)
PRODUCT_EDITABLE_FIELDS = {
    "product_name",
    "spec",
    "unit",
    "category",
    "brand",
    "barcode",
    "reference_sale_price",
    "reference_cost",
    "status",
}
SUPPLIER_EDITABLE_FIELDS = {
    "supplier_name",
    "supplier_short_name",
    "supplier_type",
    "region",
    "contact_name",
    "contact_phone",
    "address",
    "status",
}


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 50))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


def _page_response(items: list, total: int, limit: int, offset: int) -> dict:
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _count_stmt(db: Session, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _parse_category_path(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value.split("/")
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _split_category_value(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = value
    for separator in ["\\", ">", "＞", ",", "，"]:
        normalized = normalized.replace(separator, "/")
    return [segment.strip() for segment in normalized.split("/") if segment.strip()]


def _customer_category_path(customer: CustomerMaster) -> list[str]:
    segments = [*_split_category_value(customer.customer_group_name), *_split_category_value(customer.customer_type), *_split_category_value(customer.region)]
    return list(dict.fromkeys(segments)) or ["未分类客户"]


def _product_category_path(product: ProductMaster) -> list[str]:
    segments = [*_split_category_value(product.category), *_split_category_value(product.brand)]
    return list(dict.fromkeys(segments)) or ["未分类商品"]


def _path_matches(row_path: list[str], selected_path: list[str]) -> bool:
    if not selected_path:
        return True
    root_labels = {"全部客户", "全部商品", "全部库存"}

    def normalize(path: list[str]) -> list[str]:
        normalized = [segment for segment in path if segment and segment not in root_labels]
        return list(dict.fromkeys(normalized))

    normalized_row_path = normalize(row_path)
    normalized_selected_path = normalize(selected_path)
    if not normalized_selected_path:
        return True
    return normalized_row_path[: len(normalized_selected_path)] == normalized_selected_path


def _customer_abnormal(customer: CustomerMaster) -> bool:
    return customer.status != "active" or not customer.contact_phone or not customer.address or not customer.contact_name


def _customer_attention_reason_codes(customer: CustomerMaster) -> list[str]:
    reasons: list[str] = []
    if customer.status != "active":
        reasons.append("inactive")
    if not customer.contact_name:
        reasons.append("missing_contact")
    if not customer.contact_phone:
        reasons.append("missing_phone")
    if not customer.address:
        reasons.append("missing_address")
    return reasons


def _customer_attention_payload(customer: CustomerMaster) -> dict[str, Any]:
    reason_codes = _customer_attention_reason_codes(customer)
    labels = dict(CUSTOMER_ATTENTION_REASONS)
    return {
        "attention_state": "needs_attention" if reason_codes else "normal",
        "attention_reasons": [{"code": code, "label": labels[code]} for code in reason_codes],
    }


def _customer_attention_conditions(columns: Any = CustomerMaster) -> dict[str, Any]:
    return {
        "inactive": columns.status != "active",
        "missing_contact": or_(columns.contact_name.is_(None), columns.contact_name == ""),
        "missing_phone": or_(columns.contact_phone.is_(None), columns.contact_phone == ""),
        "missing_address": or_(columns.address.is_(None), columns.address == ""),
    }


def _customer_attention_summary_from_rows(rows: list[dict]) -> dict[str, Any]:
    by_reason_counts = {code: 0 for code, _label in CUSTOMER_ATTENTION_REASONS}
    needs_attention = 0
    for row in rows:
        reasons = row.get("attention_reasons") or []
        if reasons:
            needs_attention += 1
        for reason in reasons:
            code = str(reason.get("code") or "")
            if code in by_reason_counts:
                by_reason_counts[code] += 1
    total = len(rows)
    return {
        "total": total,
        "normal": total - needs_attention,
        "needs_attention": needs_attention,
        "by_reason": [
            {"code": code, "label": label, "count": by_reason_counts[code]}
            for code, label in CUSTOMER_ATTENTION_REASONS
        ],
    }


def _customer_attention_summary_from_stmt(db: Session, stmt) -> dict[str, Any]:
    filtered = stmt.order_by(None).subquery()
    conditions = _customer_attention_conditions(filtered.c)
    needs_attention_condition = or_(*conditions.values())
    row = db.execute(
        select(
            func.count().label("total"),
            func.count().filter(needs_attention_condition).label("needs_attention"),
            *[
                func.count().filter(conditions[code]).label(code)
                for code, _label in CUSTOMER_ATTENTION_REASONS
            ],
        ).select_from(filtered)
    ).mappings().one()
    total = int(row["total"] or 0)
    needs_attention = int(row["needs_attention"] or 0)
    return {
        "total": total,
        "normal": total - needs_attention,
        "needs_attention": needs_attention,
        "by_reason": [
            {"code": code, "label": label, "count": int(row[code] or 0)}
            for code, label in CUSTOMER_ATTENTION_REASONS
        ],
    }


def _customer_matches_attention(row: dict, attention_state: str | None, attention_reason: str | None) -> bool:
    if attention_state and row.get("attention_state") != attention_state:
        return False
    if attention_reason:
        return any(reason.get("code") == attention_reason for reason in row.get("attention_reasons") or [])
    return True


def _product_abnormal(product: ProductMaster) -> bool:
    return product.status != "active" or _product_category_path(product)[0] == "未分类商品"


def _master_row_search_text(row: CustomerMaster | ProductMaster) -> str:
    if isinstance(row, CustomerMaster):
        values = [
            row.customer_code,
            row.customer_name,
            row.customer_short_name,
            row.customer_type,
            row.region,
            row.salesperson_employee_code,
            row.salesperson_name,
            row.contact_name,
            row.contact_phone,
            row.customer_group_name,
            row.address,
        ]
        if isinstance(row.customer_tags, list):
            values.extend(str(tag) for tag in row.customer_tags)
    else:
        values = [
            row.product_code,
            row.product_name,
            row.spec,
            row.unit,
            row.category,
            row.brand,
            row.barcode,
        ]
    return " ".join(str(value).strip() for value in values if value not in (None, ""))


def _create_category_node(kind: str, path: list[str], label: str) -> dict:
    return {
        "id": f"{kind}:{'root' if not path else ' / '.join(path)}",
        "label": label,
        "path": path,
        "count": 0,
        "abnormal_count": 0,
        "search_text": "",
        "children": [],
    }


def _append_node_search_text(node: dict, text: str) -> None:
    if not text:
        return
    existing = node.get("search_text") or ""
    node["search_text"] = f"{existing} {text}".strip()


def _add_category_path(root: dict, kind: str, path: list[str], abnormal: bool, search_text: str = "") -> None:
    root["count"] += 1
    if abnormal:
        root["abnormal_count"] += 1
    _append_node_search_text(root, search_text)
    current = root
    for index, segment in enumerate(path):
        next_path = path[: index + 1]
        child = next((item for item in current["children"] if item["label"] == segment), None)
        if child is None:
            child = _create_category_node(kind, next_path, segment)
            current["children"].append(child)
        child["count"] += 1
        if abnormal:
            child["abnormal_count"] += 1
        _append_node_search_text(child, search_text)
        current = child


def _sort_category_node(node: dict) -> dict:
    node["children"].sort(key=lambda item: (item.get("sort_order", 0), -item["count"], item["label"]))
    for child in node["children"]:
        _sort_category_node(child)
    return node


def _category_kind_or_400(kind: str) -> str:
    try:
        return normalize_category_kind(kind)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _category_or_404(db: Session, category_id: int) -> MasterCategoryNode:
    category = db.get(MasterCategoryNode, category_id)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Master category not found")
    return category


def _category_descendant_ids(db: Session, category_id: int) -> set[int]:
    descendant_ids: set[int] = {category_id}
    pending = [category_id]
    while pending:
        parent_id = pending.pop()
        child_ids = list(db.scalars(select(MasterCategoryNode.id).where(MasterCategoryNode.parent_id == parent_id)).all())
        for child_id in child_ids:
            if child_id not in descendant_ids:
                descendant_ids.add(child_id)
                pending.append(child_id)
    return descendant_ids


def _category_path_from_node(node: MasterCategoryNode, node_by_id: dict[int, MasterCategoryNode]) -> list[str]:
    segments = [node.label]
    current = node
    guard = 0
    while current.parent_id and guard < 20:
        parent = node_by_id.get(current.parent_id)
        if parent is None:
            break
        segments.append(parent.label)
        current = parent
        guard += 1
    return list(reversed(segments))


def _node_audit_snapshot(node: MasterCategoryNode) -> dict:
    return {
        "id": node.id,
        "node_code": node.node_code,
        "kind": node.kind,
        "label": node.label,
        "parent_id": node.parent_id,
        "sort_order": node.sort_order,
        "is_enabled": node.is_enabled,
        "remark": node.remark,
    }


def _binding_audit_snapshot(binding: MasterCategoryBinding) -> dict:
    return {
        "id": binding.id,
        "category_id": binding.category_id,
        "resource_type": binding.resource_type,
        "resource_code": binding.resource_code,
        "is_primary": binding.is_primary,
        "sort_order": binding.sort_order,
        "source": binding.source,
    }


def _resource_category_paths(
    db: Session,
    *,
    kind: str,
    resource_codes: list[str],
) -> dict[str, list[list[str]]]:
    if not resource_codes:
        return {}
    normalized_kind = _category_kind_or_400(kind)
    resource_type = category_resource_type(normalized_kind)
    nodes = list(db.scalars(select(MasterCategoryNode).where(MasterCategoryNode.kind == normalized_kind, MasterCategoryNode.is_enabled.is_(True))).all())
    node_by_id = {node.id: node for node in nodes}
    bindings = list(
        db.scalars(
            select(MasterCategoryBinding).where(
                MasterCategoryBinding.resource_type == resource_type,
                MasterCategoryBinding.resource_code.in_(resource_codes),
                MasterCategoryBinding.category_id.in_(list(node_by_id.keys()) or [-1]),
            )
        ).all()
    )
    result: dict[str, list[list[str]]] = defaultdict(list)
    for binding in bindings:
        node = node_by_id.get(binding.category_id)
        if node is None:
            continue
        result[binding.resource_code].append(_category_path_from_node(node, node_by_id))
    return result


def _row_matches_category(paths: list[list[str]], selected_path: list[str]) -> bool:
    if not selected_path:
        return True
    return any(_path_matches(path, selected_path) for path in paths)


def _persistent_category_tree(
    db: Session,
    *,
    kind: str,
    root_label: str,
    rows: list[CustomerMaster] | list[ProductMaster],
    code_getter,
    fallback_path_getter,
    abnormal_getter,
) -> dict:
    normalized_kind = _category_kind_or_400(kind)
    root = _create_category_node(normalized_kind, [], root_label)
    root["persisted"] = False
    root["category_id"] = None
    nodes = list(
        db.scalars(
            select(MasterCategoryNode)
            .where(MasterCategoryNode.kind == normalized_kind, MasterCategoryNode.is_enabled.is_(True))
            .order_by(MasterCategoryNode.sort_order.asc(), MasterCategoryNode.id.asc())
        ).all()
    )
    node_by_id = {node.id: node for node in nodes}
    tree_node_by_id: dict[int, dict] = {}
    children_by_parent: dict[int | None, list[MasterCategoryNode]] = defaultdict(list)
    for node in nodes:
        children_by_parent[node.parent_id].append(node)

    def attach(parent: dict, parent_id: int | None, parent_path: list[str]) -> None:
        for node in children_by_parent.get(parent_id, []):
            path = [*parent_path, node.label]
            item = _create_category_node(normalized_kind, path, node.label)
            item.update(
                {
                    "id": f"category:{node.id}",
                    "category_id": node.id,
                    "node_code": node.node_code,
                    "persisted": True,
                    "is_enabled": node.is_enabled,
                    "sort_order": node.sort_order,
                    "remark": node.remark,
                    "count": 0,
                    "abnormal_count": 0,
                }
            )
            parent["children"].append(item)
            tree_node_by_id[node.id] = item
            attach(item, node.id, path)

    attach(root, None, [])
    resource_codes = [code_getter(row) for row in rows]
    resource_type = category_resource_type(normalized_kind)
    bindings_by_code: dict[str, list[int]] = defaultdict(list)
    if tree_node_by_id:
        binding_rows = list(
            db.scalars(
                select(MasterCategoryBinding).where(
                    MasterCategoryBinding.resource_type == resource_type,
                    MasterCategoryBinding.resource_code.in_([code for code in resource_codes if code]),
                    MasterCategoryBinding.category_id.in_(list(tree_node_by_id.keys())),
                )
            ).all()
        )
        for binding in binding_rows:
            bindings_by_code[binding.resource_code].append(binding.category_id)
    for row in rows:
        abnormal = abnormal_getter(row)
        resource_code = code_getter(row)
        search_text = _master_row_search_text(row)
        bound_node_ids = list(dict.fromkeys(bindings_by_code.get(resource_code, [])))
        if bound_node_ids:
            root["count"] += 1
            if abnormal:
                root["abnormal_count"] += 1
            _append_node_search_text(root, search_text)
            for node_id in bound_node_ids:
                current_id: int | None = node_id
                while current_id:
                    item = tree_node_by_id.get(current_id)
                    if item is not None:
                        item["count"] += 1
                        if abnormal:
                            item["abnormal_count"] += 1
                        _append_node_search_text(item, search_text)
                    parent = node_by_id.get(current_id)
                    current_id = parent.parent_id if parent else None
        else:
            _add_category_path(root, normalized_kind, fallback_path_getter(row), abnormal, search_text)
    return _sort_category_node(root)


def _normalize_match_text(value: str | None) -> str:
    return "".join(str(value or "").strip().lower().split())


def _decimal_abs(value: str | float | int | None) -> float:
    if value in (None, ""):
        return 0
    try:
        return abs(float(str(value).replace(",", "")))
    except ValueError:
        return 0


def _balance_direction(
    ar_balance: str | float | int | None,
    ap_balance: str | float | int | None,
    advance_receipt_balance: str | float | int | None,
    advance_payment_balance: str | float | int | None,
) -> str:
    customer_weight = _decimal_abs(ar_balance) + _decimal_abs(advance_receipt_balance)
    supplier_weight = _decimal_abs(ap_balance) + _decimal_abs(advance_payment_balance)
    if customer_weight > 0 and supplier_weight == 0:
        return "customer"
    if supplier_weight > 0 and customer_weight == 0:
        return "supplier"
    if customer_weight > supplier_weight * 1.5:
        return "customer"
    if supplier_weight > customer_weight * 1.5:
        return "supplier"
    return "unknown"


def _candidate_score(
    *,
    kind: str,
    code: str,
    name: str,
    short_name: str | None,
    status_value: str | None,
    input_code: str | None,
    input_name: str | None,
    direction: str,
    match_type: str,
) -> dict:
    score_by_match = {
        "code_exact": 100,
        "name_exact": 86,
        "short_name_exact": 78,
        "alias_exact": 82,
        "name_contains": 54,
        "alias_contains": 50,
        "code_contains": 46,
    }
    score = score_by_match.get(match_type, 20)
    reasons = [match_type]
    if direction == kind:
        score += 12
        reasons.append("balance_direction")
    elif direction != "unknown":
        score -= 8
        reasons.append("balance_direction_conflict")
    if status_value == "active":
        score += 3
        reasons.append("active")
    if input_code and _normalize_match_text(input_code) == _normalize_match_text(code):
        reasons.append("code_matched")
    if input_name and _normalize_match_text(input_name) in {_normalize_match_text(name), _normalize_match_text(short_name)}:
        reasons.append("name_matched")
    return {
        "kind": kind,
        "code": code,
        "name": name,
        "score": max(0, min(100, score)),
        "match_type": match_type,
        "reasons": reasons,
    }


def _append_unique_candidate(candidates: list[dict], candidate: dict) -> None:
    key = (candidate["kind"], candidate["code"])
    existing = next((item for item in candidates if (item["kind"], item["code"]) == key), None)
    if existing is None:
        candidates.append(candidate)
        return
    if candidate["score"] > existing["score"]:
        existing.update(candidate)


def _collect_customer_candidates(db: Session, current_user: User, input_code: str | None, input_name: str | None, direction: str) -> list[dict]:
    candidates: list[dict] = []
    normalized_name = _normalize_match_text(input_name)
    like_name = f"%{input_name}%" if input_name else None
    statements = []
    if input_code:
        statements.append((select(CustomerMaster).where(CustomerMaster.customer_code == input_code), "code_exact"))
    if input_name:
        statements.extend(
            [
                (select(CustomerMaster).where(CustomerMaster.customer_name == input_name), "name_exact"),
                (select(CustomerMaster).where(CustomerMaster.customer_short_name == input_name), "short_name_exact"),
            ]
        )
        if like_name and len(normalized_name) >= 2:
            statements.append((select(CustomerMaster).where(CustomerMaster.customer_name.ilike(like_name)), "name_contains"))
        statements.append((select(CustomerMaster).join(CustomerAlias).where(CustomerAlias.alias_name == input_name), "alias_exact"))
        if like_name and len(normalized_name) >= 2:
            statements.append((select(CustomerMaster).join(CustomerAlias).where(CustomerAlias.alias_name.ilike(like_name)), "alias_contains"))
    for stmt, match_type in statements:
        scoped = apply_data_scope(stmt, CustomerMaster, db, current_user, "customer").limit(8)
        for customer in db.scalars(scoped).all():
            _append_unique_candidate(
                candidates,
                _candidate_score(
                    kind="customer",
                    code=customer.customer_code,
                    name=customer.customer_name,
                    short_name=customer.customer_short_name,
                    status_value=customer.status,
                    input_code=input_code,
                    input_name=input_name,
                    direction=direction,
                    match_type=match_type,
                ),
            )
    return candidates


def _collect_supplier_candidates(db: Session, current_user: User, input_code: str | None, input_name: str | None, direction: str) -> list[dict]:
    candidates: list[dict] = []
    normalized_name = _normalize_match_text(input_name)
    like_name = f"%{input_name}%" if input_name else None
    statements = []
    if input_code:
        statements.append((select(SupplierMaster).where(SupplierMaster.supplier_code == input_code), "code_exact"))
    if input_name:
        statements.extend(
            [
                (select(SupplierMaster).where(SupplierMaster.supplier_name == input_name), "name_exact"),
                (select(SupplierMaster).where(SupplierMaster.supplier_short_name == input_name), "short_name_exact"),
            ]
        )
        if like_name and len(normalized_name) >= 2:
            statements.append((select(SupplierMaster).where(SupplierMaster.supplier_name.ilike(like_name)), "name_contains"))
        statements.append((select(SupplierMaster).join(SupplierAlias).where(SupplierAlias.alias_name == input_name), "alias_exact"))
        if like_name and len(normalized_name) >= 2:
            statements.append((select(SupplierMaster).join(SupplierAlias).where(SupplierAlias.alias_name.ilike(like_name)), "alias_contains"))
    for stmt, match_type in statements:
        scoped = apply_data_scope(stmt, SupplierMaster, db, current_user, "supplier").limit(8)
        for supplier in db.scalars(scoped).all():
            _append_unique_candidate(
                candidates,
                _candidate_score(
                    kind="supplier",
                    code=supplier.supplier_code,
                    name=supplier.supplier_name,
                    short_name=supplier.supplier_short_name,
                    status_value=supplier.status,
                    input_code=input_code,
                    input_name=input_name,
                    direction=direction,
                    match_type=match_type,
                ),
            )
    return candidates


@router.get("/settlement-unit/resolve")
def resolve_settlement_unit(
    code: str | None = None,
    name: str | None = None,
    ar_balance: str | None = None,
    ap_balance: str | None = None,
    advance_receipt_balance: str | None = None,
    advance_payment_balance: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer.view", "supplier.view")),
) -> dict:
    input_code = _clean_text(code)
    input_name = _clean_text(name)
    direction = _balance_direction(ar_balance, ap_balance, advance_receipt_balance, advance_payment_balance)
    candidates = [
        *_collect_customer_candidates(db, current_user, input_code, input_name, direction),
        *_collect_supplier_candidates(db, current_user, input_code, input_name, direction),
    ]
    candidates.sort(key=lambda item: (-item["score"], item["kind"], item["code"]))
    best = candidates[0] if candidates and candidates[0]["score"] >= 60 else None
    return {
        "input": {"code": input_code, "name": input_name},
        "direction": direction,
        "best_kind": best["kind"] if best else "unknown",
        "confidence": best["score"] if best else 0,
        "target": {"kind": f"{best['kind']}s", "code": best["code"], "name": best["name"]} if best else None,
        "reason": "matched_master_data" if best else ("balance_direction_only" if direction != "unknown" else "unresolved"),
        "candidates": candidates[:6],
    }


@router.get("/customers", response_model=list[CustomerMasterPublic])
def list_customers(
    q: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer.view")),
) -> list[dict]:
    safe_limit = max(1, min(limit, 5000))
    stmt = select(CustomerMaster).order_by(CustomerMaster.customer_code)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((CustomerMaster.customer_code.ilike(like)) | (CustomerMaster.customer_name.ilike(like)))
    stmt = apply_data_scope(stmt, CustomerMaster, db, current_user, "customer").limit(safe_limit)
    rows = list(db.scalars(stmt).all())
    return [_serialize_customer(db, current_user, row) for row in rows]


@router.get("/customers/page")
def list_customers_page(
    q: str | None = None,
    category_path: str | None = None,
    portrait_scale: str | None = None,
    portrait_payment_level: str | None = None,
    portrait_category: str | None = None,
    portrait_margin: str | None = None,
    portrait_return: str | None = None,
    portrait_growth: str | None = None,
    customer_tags: str | None = None,
    customer_tag_match: Literal["any", "all"] = "all",
    assignment_scope: str | None = None,
    missing_phone: bool | None = None,
    missing_contact: bool | None = None,
    missing_address: bool | None = None,
    missing_group: bool | None = None,
    missing_business_profile: bool | None = None,
    missing_business_products: bool | None = None,
    second_assignment_candidate: bool | None = None,
    attention_state: Literal["normal", "needs_attention"] | None = None,
    attention_reason: Literal["inactive", "missing_contact", "missing_phone", "missing_address"] | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(CustomerMaster).order_by(CustomerMaster.customer_code)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                CustomerMaster.customer_code.ilike(like),
                CustomerMaster.customer_name.ilike(like),
                CustomerMaster.customer_short_name.ilike(like),
                CustomerMaster.contact_name.ilike(like),
                CustomerMaster.contact_phone.ilike(like),
                CustomerMaster.customer_group_name.ilike(like),
                CustomerMaster.address.ilike(like),
            )
        )
    tag_filters = [tag.strip() for tag in (customer_tags or "").replace("，", ",").split(",") if tag.strip()]
    tag_conditions = [CustomerMaster.customer_tags.contains([tag]) for tag in tag_filters]
    tag_filter_in_python = bool(tag_conditions) and db.get_bind().dialect.name != "postgresql"
    if tag_conditions and not tag_filter_in_python:
        stmt = stmt.where(or_(*tag_conditions) if customer_tag_match == "any" else and_(*tag_conditions))
    stmt = apply_data_scope(stmt, CustomerMaster, db, current_user, "customer")
    selected_path = _parse_category_path(category_path)
    portrait_filters = _portrait_filter_values(
        scale=portrait_scale,
        payment_level=portrait_payment_level,
        category=portrait_category,
        margin=portrait_margin,
        return_tag=portrait_return,
        growth=portrait_growth,
    )
    can_view_portrait = has_permission(db, current_user, "customer_portrait.view")
    if portrait_filters and not can_view_portrait:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: customer_portrait.view")
    missing_filter_values = {
        "缺电话": bool(missing_phone),
        "缺联系人": bool(missing_contact),
        "缺地址": bool(missing_address),
        "缺客户群": bool(missing_group),
        "缺经营资料": bool(missing_business_profile),
        "缺经营产品": bool(missing_business_products),
    }
    needs_python_filter = (
        selected_path
        or portrait_filters
        or assignment_scope in {"assigned", "unassigned", "active", "historical"}
        or any(missing_filter_values.values())
        or bool(second_assignment_candidate)
        or tag_filter_in_python
    )
    if needs_python_filter:
        candidates = list(db.scalars(stmt).all())
        category_paths_by_code = _resource_category_paths(
            db,
            kind="customers",
            resource_codes=[row.customer_code for row in candidates],
        ) if selected_path else {}
        base_matched = []
        for row in candidates:
            if tag_filter_in_python:
                row_tags = {str(tag) for tag in row.customer_tags or []}
                matches = [tag in row_tags for tag in tag_filters]
                if customer_tag_match == "any" and not any(matches):
                    continue
                if customer_tag_match == "all" and not all(matches):
                    continue
            paths = [*category_paths_by_code.get(row.customer_code, []), _customer_category_path(row)]
            if selected_path and not _row_matches_category(paths, selected_path):
                continue
            if portrait_filters:
                portrait = _build_customer_portrait_tags(db, current_user, row)
                if not _portrait_matches_filters(portrait, portrait_filters):
                    continue
            serialized = _serialize_customer(db, current_user, row, include_portrait_summary=can_view_portrait)
            if assignment_scope == "assigned" and int(serialized.get("crm_project_count") or 0) <= 0:
                continue
            if assignment_scope == "unassigned" and int(serialized.get("crm_project_count") or 0) > 0:
                continue
            if assignment_scope == "active" and int(serialized.get("crm_active_project_count") or 0) <= 0:
                continue
            if assignment_scope == "historical" and not (int(serialized.get("crm_project_count") or 0) > 0 and int(serialized.get("crm_active_project_count") or 0) <= 0):
                continue
            missing_fields = set(serialized.get("missing_fields") or [])
            if any(enabled and label not in missing_fields for label, enabled in missing_filter_values.items()):
                continue
            if second_assignment_candidate and not (
                int(serialized.get("crm_project_count") or 0) == 0
                and bool(missing_fields.intersection({"缺电话", "缺联系人", "缺地址", "缺客户群", "缺经营资料", "缺经营产品"}))
            ):
                continue
            base_matched.append(serialized)
        attention_summary = _customer_attention_summary_from_rows(base_matched)
        matched = [
            row for row in base_matched
            if _customer_matches_attention(row, attention_state, attention_reason)
        ]
        total = len(matched)
        page_rows = matched[safe_offset : safe_offset + safe_limit]
        response = _page_response(page_rows, total, safe_limit, safe_offset)
        response["attention_summary"] = attention_summary
        return response
    attention_summary = _customer_attention_summary_from_stmt(db, stmt)
    attention_conditions = _customer_attention_conditions()
    if attention_state == "needs_attention":
        stmt = stmt.where(or_(*attention_conditions.values()))
    elif attention_state == "normal":
        stmt = stmt.where(~or_(*attention_conditions.values()))
    if attention_reason:
        stmt = stmt.where(attention_conditions[attention_reason])
    total = _count_stmt(db, stmt)
    rows = list(db.scalars(stmt.offset(safe_offset).limit(safe_limit)).all())
    response = _page_response([_serialize_customer(db, current_user, row, include_portrait_summary=can_view_portrait) for row in rows], total, safe_limit, safe_offset)
    response["attention_summary"] = attention_summary
    return response


@router.get("/customers/hierarchy")
def customer_hierarchy(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer.view")),
) -> dict:
    stmt = apply_data_scope(select(CustomerMaster).order_by(CustomerMaster.customer_code), CustomerMaster, db, current_user, "customer")
    customers = list(db.scalars(stmt).all())
    return _persistent_category_tree(
        db,
        kind="customers",
        root_label="全部客户",
        rows=customers,
        code_getter=lambda row: row.customer_code,
        fallback_path_getter=_customer_category_path,
        abnormal_getter=_customer_abnormal,
    )


@router.get("/customer-tags", response_model=list[CustomerTagPublic])
def list_customer_tags(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer.view")),
) -> list[dict]:
    stmt = select(CustomerTag).order_by(CustomerTag.is_active.desc(), CustomerTag.name, CustomerTag.id)
    if not include_inactive:
        stmt = stmt.where(CustomerTag.is_active.is_(True))
    rows = list(db.scalars(stmt).all())
    counts = customer_tag_usage_counts(db)
    creator_ids = {row.created_by_user_id for row in rows if row.created_by_user_id is not None}
    creators = dict(db.execute(select(User.id, User.real_name).where(User.id.in_(creator_ids))).all()) if creator_ids else {}
    return [
        {
            "id": row.id,
            "name": row.name,
            "color_key": row.color_key,
            "is_active": row.is_active,
            "usage_count": counts[row.normalized_name],
            "created_by_user_id": row.created_by_user_id,
            "created_by_name": creators.get(row.created_by_user_id),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.post("/customer-tags", response_model=CustomerTagPublic, status_code=status.HTTP_201_CREATED)
def add_customer_tag(
    payload: CustomerTagCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> dict:
    row = create_customer_tag(
        db,
        name=payload.name,
        color_key=payload.color_key,
        operator=current_user,
        request=request,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer tag already exists") from exc
    db.refresh(row)
    return {
        "id": row.id,
        "name": row.name,
        "color_key": row.color_key,
        "is_active": row.is_active,
        "usage_count": 0,
        "created_by_user_id": row.created_by_user_id,
        "created_by_name": current_user.real_name,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.patch("/customer-tags/{tag_id}", response_model=CustomerTagPublic)
def edit_customer_tag(
    tag_id: int,
    payload: CustomerTagUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_tag.catalog_manage")),
) -> dict:
    row = db.get(CustomerTag, tag_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer tag not found")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one tag field is required")
    if row.is_formal and ({"name", "is_active"} & set(changes)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Formal catalog tags are versioned; create a replacement definition instead of renaming or disabling in place",
        )
    row, _affected = update_customer_tag(
        db,
        row=row,
        changes=changes,
        operator=current_user,
        request=request,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer tag already exists") from exc
    db.refresh(row)
    counts = customer_tag_usage_counts(db)
    creator_name = db.scalar(select(User.real_name).where(User.id == row.created_by_user_id)) if row.created_by_user_id else None
    return {
        "id": row.id,
        "name": row.name,
        "color_key": row.color_key,
        "is_active": row.is_active,
        "usage_count": counts[row.normalized_name],
        "created_by_user_id": row.created_by_user_id,
        "created_by_name": creator_name,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/customers/{customer_code}", response_model=CustomerMasterPublic)
def get_customer(
    customer_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer.view")),
) -> dict:
    stmt = select(CustomerMaster).where(CustomerMaster.customer_code == customer_code)
    stmt = apply_data_scope(stmt, CustomerMaster, db, current_user, "customer")
    customer = db.scalar(stmt)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return _serialize_customer(db, current_user, customer)


@router.post("/customers", response_model=CustomerMasterPublic, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerMasterCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer.edit")),
) -> dict:
    customer_code = _clean_text(payload.customer_code)
    customer_name = _clean_text(payload.customer_name)
    if not customer_code or not customer_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer code and name are required")
    if db.scalar(select(CustomerMaster.id).where(CustomerMaster.customer_code == customer_code)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer code already exists")
    values = payload.model_dump(exclude_unset=True)
    values["customer_code"] = customer_code
    values["customer_name"] = customer_name
    if values.get("status") and values["status"] not in MASTER_STATUS_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid customer status")
    contact_phone = _clean_text(values.get("contact_phone"))
    assert_customer_identity_available(db, customer_name=customer_name, contact_phone=contact_phone)
    customer = CustomerMaster(
        customer_code=customer_code,
        customer_name=customer_name,
        customer_short_name=_clean_text(values.get("customer_short_name")),
        customer_type=_clean_text(values.get("customer_type")),
        region=_clean_text(values.get("region")),
        salesperson_employee_code=_clean_text(values.get("salesperson_employee_code")),
        salesperson_name=_clean_text(values.get("salesperson_name")),
        contact_name=_clean_text(values.get("contact_name")),
        contact_phone=contact_phone,
        contact_channel=_clean_text(values.get("contact_channel")),
        customer_group_name=_clean_text(values.get("customer_group_name")),
        customer_tags=canonicalize_customer_tags(db, values.get("customer_tags"), created_by_user_id=current_user.id),
        address=_clean_text(values.get("address")),
        status=values.get("status") or "active",
        source="manual",
        profile_updated_at=values.get("profile_updated_at"),
        base_remark=_clean_text(values.get("base_remark")),
    )
    db.add(customer)
    db.flush()
    write_audit_log(
        db,
        action_type="create_customer",
        resource_type="customer",
        resource_id=customer.customer_code,
        user=current_user,
        request=request,
        after_data=_customer_audit_snapshot(customer),
    )
    from app.services.master_link_service import rebuild_master_link_issues

    rebuild_master_link_issues(db)
    db.commit()
    db.refresh(customer)
    return _serialize_customer(db, current_user, customer)


@router.get("/customers/{customer_code}/business-profile", response_model=CustomerBusinessProfileResponse)
def get_customer_business_profile(
    customer_code: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_business.view")),
) -> dict:
    customer = _get_scoped_customer(db, current_user, customer_code)
    result = build_customer_business_profile_response(db, current_user, customer)
    write_audit_log(
        db,
        action_type="view_customer_business_profile",
        resource_type="customer_business_profile",
        resource_id=customer.customer_code,
        user=current_user,
        request=request,
        after_data={
            "has_profile": result["profile"] is not None,
            "product_count": len(result["products"]),
        },
    )
    db.commit()
    return result


@router.put("/customers/{customer_code}/business-profile", response_model=CustomerBusinessProfileResponse)
def upsert_customer_business_profile(
    customer_code: str,
    payload: CustomerBusinessProfileUpsert,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_business.edit")),
) -> dict:
    customer = _get_scoped_customer(db, current_user, customer_code)
    profile = db.scalar(select(CustomerBusinessProfile).where(CustomerBusinessProfile.customer_code == customer.customer_code))
    existing_products = _customer_business_products(db, customer.customer_code)
    before_data = _customer_business_snapshot(profile, existing_products) if profile else None
    changes = payload.model_dump(exclude_unset=True)
    _validate_business_profile_payload(changes)

    if profile is None:
        profile = CustomerBusinessProfile(
            customer_code=customer.customer_code,
            customer_name_snapshot=customer.customer_name,
            business_customer_type=_clean_text(changes.get("business_customer_type")) or _business_customer_type_default(customer),
            confirmed_at=changes.get("confirmed_at") or date.today(),
            filled_by=_clean_text(changes.get("filled_by")) or current_user.real_name or current_user.username,
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
            confirmed_by=_clean_text(changes.get("confirmed_by")) or current_user.real_name or current_user.username,
            created_by_user_id=current_user.id,
            updated_by_user_id=current_user.id,
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
        profile.updated_by_user_id = current_user.id

    db.flush()
    if "products" in changes:
        db.execute(delete(CustomerBusinessProduct).where(CustomerBusinessProduct.customer_code == customer.customer_code))
        db.flush()
        for index, item in enumerate(_clean_business_products(changes["products"], profile.confirmed_at)):
            db.add(CustomerBusinessProduct(customer_code=customer.customer_code, sort_order=index + 1, **item))
        db.flush()

    saved_products = _customer_business_products(db, customer.customer_code)
    after_data = _customer_business_snapshot(profile, saved_products)
    changed_fields = _changed_keys(before_data or {}, after_data)
    history = CustomerBusinessProfileHistory(
        customer_code=customer.customer_code,
        version_no=profile.version_no,
        update_source=profile.update_source,
        update_type=profile.update_type,
        filled_by=profile.filled_by,
        update_note=profile.latest_update_note,
        confirmed_by=profile.confirmed_by,
        snapshot_json=after_data,
        created_by_user_id=current_user.id,
    )
    db.add(history)
    write_audit_log(
        db,
        action_type="update_customer_business_profile",
        resource_type="customer_business_profile",
        resource_id=customer.customer_code,
        user=current_user,
        request=request,
        before_data=before_data,
        after_data={
            "version_no": profile.version_no,
            "product_count": len(saved_products),
            "product_change_counts": _business_product_change_counts(saved_products),
            "update_source": profile.update_source,
            "update_type": profile.update_type,
            "filled_by": profile.filled_by,
            "update_note": profile.latest_update_note,
            "changed_fields": changed_fields,
        },
    )
    db.commit()
    db.refresh(profile)
    return build_customer_business_profile_response(db, current_user, customer)


@router.get("/customers/{customer_code}/business-profile/history", response_model=list[CustomerBusinessProfileHistoryPublic])
def list_customer_business_profile_history(
    customer_code: str,
    request: Request,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_business.history")),
) -> list[CustomerBusinessProfileHistory]:
    customer = _get_scoped_customer(db, current_user, customer_code)
    rows = list(
        db.scalars(
            select(CustomerBusinessProfileHistory)
            .where(CustomerBusinessProfileHistory.customer_code == customer.customer_code)
            .order_by(CustomerBusinessProfileHistory.version_no.desc(), CustomerBusinessProfileHistory.id.desc())
            .offset(_safe_offset(offset))
            .limit(max(1, min(limit, 100)))
        ).all()
    )
    write_audit_log(
        db,
        action_type="view_customer_business_history",
        resource_type="customer_business_profile",
        resource_id=customer.customer_code,
        user=current_user,
        request=request,
        after_data={"count": len(rows), "limit": limit, "offset": offset},
    )
    db.commit()
    return rows


@router.get("/customers/{customer_code}/portrait/tags")
def get_customer_portrait_tags(
    customer_code: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_portrait.view")),
) -> dict:
    stmt = select(CustomerMaster).where(CustomerMaster.customer_code == customer_code)
    stmt = apply_data_scope(stmt, CustomerMaster, db, current_user, "customer")
    customer = db.scalar(stmt)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    snapshot = _latest_customer_portrait_snapshot(db, customer.customer_code)
    source = "snapshot"
    task: CustomerPortraitTask | None = None
    if snapshot is None:
        snapshot, task = _generate_customer_portrait_snapshot(db, current_user, customer, "auto_single")
        source = "auto_generated"
    result = _portrait_snapshot_response(snapshot, source=source, task=task)
    write_audit_log(
        db,
        action_type="view_customer_portrait",
        resource_type="customer_portrait",
        resource_id=customer.customer_code,
        user=current_user,
        request=request,
        after_data={
            "snapshot_id": snapshot.id,
            "source": source,
            "task_no": task.task_no if task else snapshot.task_no,
            "status": snapshot.status,
        },
    )
    db.commit()
    return result


@router.post("/customers/{customer_code}/portrait/tags/refresh")
def refresh_customer_portrait_tags(
    customer_code: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer_portrait.refresh")),
) -> dict:
    stmt = select(CustomerMaster).where(CustomerMaster.customer_code == customer_code)
    stmt = apply_data_scope(stmt, CustomerMaster, db, current_user, "customer")
    customer = db.scalar(stmt)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    snapshot, task = _generate_customer_portrait_snapshot(db, current_user, customer, "manual_single")
    result = _portrait_snapshot_response(snapshot, source="manual_refresh", task=task)
    write_audit_log(
        db,
        action_type="refresh_customer_portrait",
        resource_type="customer_portrait",
        resource_id=customer.customer_code,
        user=current_user,
        request=request,
        after_data={
            "snapshot_id": snapshot.id,
            "task_no": task.task_no,
            "status": snapshot.status,
            "rule_version": snapshot.rule_version,
        },
    )
    db.commit()
    return result


@router.patch("/customers/{customer_code}", response_model=CustomerMasterPublic)
def update_customer(
    customer_code: str,
    payload: CustomerMasterUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("customer.edit")),
) -> dict:
    stmt = select(CustomerMaster).where(CustomerMaster.customer_code == customer_code)
    stmt = apply_data_scope(stmt, CustomerMaster, db, current_user, "customer")
    customer = db.scalar(stmt)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    apply_customer_master_update(
        db,
        customer=customer,
        payload=payload,
        operator=current_user,
        audit_action_type="update_customer",
        request=request,
    )
    db.commit()
    db.refresh(customer)
    return _serialize_customer(db, current_user, customer)


def _get_scoped_customer(db: Session, current_user: User, customer_code: str) -> CustomerMaster:
    stmt = select(CustomerMaster).where(CustomerMaster.customer_code == customer_code)
    stmt = apply_data_scope(stmt, CustomerMaster, db, current_user, "customer")
    customer = db.scalar(stmt)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


def _customer_business_products(db: Session, customer_code: str) -> list[CustomerBusinessProduct]:
    return list(
        db.scalars(
            select(CustomerBusinessProduct)
            .where(CustomerBusinessProduct.customer_code == customer_code)
            .order_by(CustomerBusinessProduct.sort_order, CustomerBusinessProduct.id)
        ).all()
    )


def _customer_business_profile_response(db: Session, current_user: User, customer: CustomerMaster) -> dict:
    profile = db.scalar(select(CustomerBusinessProfile).where(CustomerBusinessProfile.customer_code == customer.customer_code))
    products = _customer_business_products(db, customer.customer_code) if profile else []
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
    }


def _validate_business_profile_payload(changes: dict) -> None:
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


def _clean_business_products(products: list[dict], default_confirmed_at: date | None) -> list[dict]:
    cleaned_products: list[dict] = []
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
        if not any(
            cleaned.get(field)
            for field in ["product_category", "spec", "common_brand", "monthly_usage", "opportunity_note"]
        ):
            continue
        if not cleaned["product_category"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Business product category is required")
        cleaned_products.append(cleaned)
    return cleaned_products


def _business_product_snapshot(product: CustomerBusinessProduct) -> dict:
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
) -> dict:
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


def _business_product_change_counts(products: list[CustomerBusinessProduct]) -> dict:
    counts = {key: 0 for key in CUSTOMER_BUSINESS_PRODUCT_CHANGE_TYPES}
    for product in products:
        change_type = product.change_type or "无变化"
        counts[change_type] = counts.get(change_type, 0) + 1
    return counts


def _changed_keys(before_data: dict, after_data: dict) -> list[str]:
    before_profile = before_data.get("profile") or {}
    after_profile = after_data.get("profile") or {}
    keys = sorted(set(before_profile) | set(after_profile))
    changed = [key for key in keys if before_profile.get(key) != after_profile.get(key)]
    if before_data.get("products", []) != after_data.get("products", []):
        changed.append("products")
    return changed


def _serialize_customer(db: Session, current_user: User, customer: CustomerMaster, include_portrait_summary: bool = False) -> dict:
    data = serialize_with_field_rules(db, current_user, "customer", customer)
    data["customer_tags"] = clean_customer_tags(data.get("customer_tags"))
    data["base_info_completeness"] = _customer_completeness(data)
    data["historical_salespersons"] = _historical_salespersons(db, customer.customer_code)
    data.update(_customer_crm_assignment_summary(db, customer))
    data["missing_fields"] = _customer_missing_fields(db, customer)
    data.update(_customer_attention_payload(customer))
    if include_portrait_summary:
        data.update(_customer_portrait_summary_fields(db, current_user, customer))
    return data


def _customer_crm_assignment_summary(db: Session, customer: CustomerMaster) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(CrmProjectCustomerTask, CrmProject)
            .join(CrmProject, CrmProject.id == CrmProjectCustomerTask.project_id)
            .where(CrmProjectCustomerTask.customer_code == customer.customer_code)
            .order_by(CrmProjectCustomerTask.updated_at.desc(), CrmProjectCustomerTask.id.desc())
        ).all()
    )
    project_by_id = {project.id: project for _task, project in rows}
    active_projects = [
        project for project in project_by_id.values()
        if project.status not in {"closed", "cancelled", "voided", "archived"}
    ]
    latest_task: CrmProjectCustomerTask | None = None
    latest_project: CrmProject | None = None
    if rows:
        latest_task, latest_project = rows[0]
    return {
        "crm_project_count": len(project_by_id),
        "crm_active_project_count": len(active_projects),
        "latest_crm_project_id": latest_project.id if latest_project else None,
        "latest_crm_project_name": latest_project.project_name if latest_project else None,
        "latest_crm_project_status": latest_project.status if latest_project else None,
        "latest_crm_assigned_at": latest_task.created_at if latest_task else None,
    }


def _customer_missing_fields(db: Session, customer: CustomerMaster) -> list[str]:
    missing: list[str] = []
    if not customer.contact_phone:
        missing.append("缺电话")
    if not customer.contact_name:
        missing.append("缺联系人")
    if not customer.address:
        missing.append("缺地址")
    if not customer.customer_group_name:
        missing.append("缺客户群")
    if any(label in missing for label in ["缺电话", "缺联系人", "缺地址", "缺客户群"]):
        missing.append("缺基本资料")
    profile = db.scalar(select(CustomerBusinessProfile).where(CustomerBusinessProfile.customer_code == customer.customer_code))
    if profile is None:
        missing.append("缺经营资料")
        missing.append("缺经营产品")
        return missing
    active_product_count = db.scalar(
        select(func.count(CustomerBusinessProduct.id))
        .where(
            CustomerBusinessProduct.customer_code == customer.customer_code,
            CustomerBusinessProduct.is_active.is_(True),
        )
    ) or 0
    if int(active_product_count) <= 0:
        missing.append("缺经营产品")
    return missing


def _latest_customer_portrait_snapshot(db: Session, customer_code: str) -> CustomerPortraitSnapshot | None:
    return db.scalar(
        select(CustomerPortraitSnapshot)
        .where(CustomerPortraitSnapshot.customer_code == customer_code)
        .order_by(CustomerPortraitSnapshot.generated_at.desc(), CustomerPortraitSnapshot.id.desc())
    )


def _generate_customer_portrait_snapshot(
    db: Session,
    current_user: User,
    customer: CustomerMaster,
    task_type: str,
) -> tuple[CustomerPortraitSnapshot, CustomerPortraitTask]:
    now = datetime.now(timezone.utc)
    task = CustomerPortraitTask(
        task_no=_customer_portrait_task_no(now),
        task_type=task_type,
        status="running",
        customer_code=customer.customer_code,
        total_customers=1,
        success_count=0,
        failed_count=0,
        started_at=now,
        created_by=current_user.id,
    )
    db.add(task)
    db.flush()
    try:
        portrait = _build_customer_portrait_tags(db, current_user, customer)
        encoded = jsonable_encoder(portrait)
        summary_json = {
            key: encoded.get(key)
            for key in ("rule_version", "generated_at", "data_cutoff_date", "match_confidence", "customer", "metrics")
        }
        metrics = portrait.get("metrics") if isinstance(portrait.get("metrics"), dict) else {}
        period_start = _date_or_none(metrics.get("first_purchase_date"))
        period_end = _date_or_none(metrics.get("last_purchase_date")) or _date_or_none(portrait.get("data_cutoff_date"))
        data_cutoff = _date_or_none(portrait.get("data_cutoff_date"))
        quality = encoded.get("quality") if isinstance(encoded.get("quality"), dict) else {}
        snapshot = CustomerPortraitSnapshot(
            customer_code=customer.customer_code,
            customer_name=customer.customer_name,
            period_start=period_start,
            period_end=period_end,
            data_cutoff_date=data_cutoff,
            rule_version=str(encoded.get("rule_version") or "portrait-tag-v0.1"),
            status="partial" if quality.get("status") == "partial" else "generated",
            task_no=task.task_no,
            summary_json=summary_json,
            tag_json=encoded.get("tags") if isinstance(encoded.get("tags"), list) else [],
            payment_json=encoded.get("payment") if isinstance(encoded.get("payment"), dict) else None,
            profile_json=encoded.get("profile") if isinstance(encoded.get("profile"), dict) else None,
            quality_json=quality,
            generated_at=now,
        )
        db.add(snapshot)
        task.status = "success"
        task.success_count = 1
        task.finished_at = datetime.now(timezone.utc)
        db.flush()
        return snapshot, task
    except Exception as exc:
        task.status = "failed"
        task.failed_count = 1
        task.error_json = {"message": str(exc)}
        task.finished_at = datetime.now(timezone.utc)
        db.flush()
        raise


def _portrait_snapshot_response(
    snapshot: CustomerPortraitSnapshot,
    *,
    source: str,
    task: CustomerPortraitTask | None = None,
) -> dict:
    result = dict(snapshot.summary_json or {})
    result["rule_version"] = result.get("rule_version") or snapshot.rule_version
    result["generated_at"] = result.get("generated_at") or snapshot.generated_at.isoformat()
    result["data_cutoff_date"] = result.get("data_cutoff_date") or (snapshot.data_cutoff_date.isoformat() if snapshot.data_cutoff_date else None)
    result["match_confidence"] = result.get("match_confidence") or "strong"
    result["customer"] = result.get("customer") or {"customer_code": snapshot.customer_code, "customer_name": snapshot.customer_name}
    result["metrics"] = result.get("metrics") or {}
    result["quality"] = snapshot.quality_json or {"status": "ok", "issues": []}
    result["tags"] = snapshot.tag_json or []
    result["payment"] = snapshot.payment_json
    result["profile"] = snapshot.profile_json
    result["snapshot"] = {
        "id": snapshot.id,
        "status": snapshot.status,
        "source": source,
        "task_no": snapshot.task_no,
        "generated_at": snapshot.generated_at.isoformat(),
        "period_start": snapshot.period_start.isoformat() if snapshot.period_start else None,
        "period_end": snapshot.period_end.isoformat() if snapshot.period_end else None,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "updated_at": snapshot.updated_at.isoformat() if snapshot.updated_at else None,
    }
    if task is not None:
        result["task"] = _portrait_task_public(task)
    return result


def _portrait_task_public(task: CustomerPortraitTask) -> dict:
    return {
        "id": task.id,
        "task_no": task.task_no,
        "task_type": task.task_type,
        "status": task.status,
        "customer_code": task.customer_code,
        "total_customers": task.total_customers,
        "success_count": task.success_count,
        "failed_count": task.failed_count,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


def _customer_portrait_task_no(now: datetime) -> str:
    return f"CPT{now.strftime('%Y%m%d%H%M%S')}-{now.microsecond:06d}"


def _date_or_none(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _portrait_filter_values(
    scale: str | None,
    payment_level: str | None,
    category: str | None,
    margin: str | None,
    return_tag: str | None,
    growth: str | None,
) -> dict[str, str]:
    values = {
        "scale": scale,
        "payment_level": payment_level,
        "category": category,
        "margin": margin,
        "return": return_tag,
        "growth": growth,
    }
    return {key: str(value).strip() for key, value in values.items() if value is not None and str(value).strip()}


def _customer_portrait_summary_fields(db: Session, current_user: User, customer: CustomerMaster) -> dict:
    portrait = _build_customer_portrait_tags(db, current_user, customer)
    tag_values = _portrait_tag_values(portrait)
    payment = portrait.get("payment") if isinstance(portrait.get("payment"), dict) else {}
    payment_level = str(payment.get("level") or "-")
    payment_score = payment.get("score")
    summary_parts = [
        tag_values.get("scale", "-"),
        tag_values.get("category", "-"),
        f"{payment_level}{'' if payment_score is None else f'/{payment_score}分'}",
    ]
    return {
        "portrait_scale": tag_values.get("scale"),
        "portrait_payment_level": payment_level,
        "portrait_category": tag_values.get("category"),
        "portrait_margin": tag_values.get("margin"),
        "portrait_return": tag_values.get("return"),
        "portrait_growth": tag_values.get("growth"),
        "portrait_summary": " · ".join(part for part in summary_parts if part and part != "-"),
    }


def _portrait_tag_values(portrait: dict) -> dict[str, str]:
    tags = portrait.get("tags") if isinstance(portrait.get("tags"), list) else []
    return {str(item.get("key")): str(item.get("value") or "") for item in tags if isinstance(item, dict)}


def _portrait_matches_filters(portrait: dict, filters: dict[str, str]) -> bool:
    tag_values = _portrait_tag_values(portrait)
    payment = portrait.get("payment") if isinstance(portrait.get("payment"), dict) else {}
    values = {
        "scale": tag_values.get("scale", ""),
        "payment_level": str(payment.get("level") or ""),
        "category": tag_values.get("category", ""),
        "margin": tag_values.get("margin", ""),
        "return": tag_values.get("return", ""),
        "growth": tag_values.get("growth", ""),
    }
    return all(values.get(key) == value for key, value in filters.items())


def _build_customer_portrait_tags(db: Session, current_user: User, customer: CustomerMaster) -> dict:
    sales_rows, sales_match = _customer_sales_rows(db, customer)
    balance_rows, balance_match = _customer_balance_rows(db, customer)
    generated_at = datetime.now(timezone.utc)
    cutoff_date = _portrait_cutoff_date(sales_rows, balance_rows)
    sales_metrics = _sales_metrics(sales_rows, cutoff_date)
    balance_metrics = _balance_metrics(balance_rows)
    hide_margin = _has_hidden_field(db, current_user, "sales_detail", {"gross_profit", "cost_amount"})
    tags = _portrait_tag_cards(customer, sales_rows, sales_metrics, hide_margin)
    payment_profile = _payment_risk_profile(balance_rows, sales_metrics)
    deep_profile = _deep_customer_profile(customer, tags, payment_profile, sales_metrics, balance_metrics)
    quality_issues: list[str] = []
    if not sales_rows:
        quality_issues.append("当前客户暂无销售明细，交易类标签以数据不足展示。")
    if not balance_rows:
        quality_issues.append("当前客户暂无往来对账，回款风险以数据不足展示。")
    quality_issues.extend(payment_profile["quality_issues"])
    if sales_match == "weak" or balance_match == "weak":
        quality_issues.append("存在按客户名称弱匹配的数据，结果仅供辅助判断。")
    if hide_margin:
        quality_issues.append("当前账号字段权限隐藏毛利或成本，毛利标签不展示结论。")

    return {
        "rule_version": "portrait-tag-v0.1",
        "generated_at": generated_at.isoformat(),
        "data_cutoff_date": cutoff_date.isoformat() if cutoff_date else None,
        "match_confidence": "weak" if sales_match == "weak" or balance_match == "weak" else "strong",
        "customer": {
            "customer_code": customer.customer_code,
            "customer_name": customer.customer_name,
            "customer_type": customer.customer_type,
            "region": customer.region,
            "salesperson_name": customer.salesperson_name,
            "status": customer.status,
            "profile_updated_at": customer.profile_updated_at.isoformat() if customer.profile_updated_at else None,
            "base_info_completeness": _customer_completeness(_serialize_row_for_completeness(customer)),
        },
        "metrics": {
            **sales_metrics,
            **balance_metrics,
            "sales_match": sales_match,
            "balance_match": balance_match,
            "sales_rows": len(sales_rows),
            "balance_rows": len(balance_rows),
        },
        "quality": {
            "status": "partial" if quality_issues else "ok",
            "issues": quality_issues,
        },
        "tags": tags,
        "payment": payment_profile,
        "profile": deep_profile,
    }


def _serialize_row_for_completeness(customer: CustomerMaster) -> dict:
    return {
        "contact_phone": customer.contact_phone,
        "address": customer.address,
        "contact_name": customer.contact_name,
    }


def _customer_sales_rows(db: Session, customer: CustomerMaster) -> tuple[list[SalesDetail], str]:
    stmt = select(SalesDetail).where(SalesDetail.customer_code == customer.customer_code).order_by(SalesDetail.document_date, SalesDetail.id)
    rows = list(db.scalars(stmt).all())
    if rows:
        return rows, "strong"
    if not customer.customer_name:
        return [], "none"
    weak_rows = list(
        db.scalars(
            select(SalesDetail)
            .where(SalesDetail.customer_name == customer.customer_name)
            .order_by(SalesDetail.document_date, SalesDetail.id)
        ).all()
    )
    return weak_rows, "weak" if weak_rows else "none"


def _customer_balance_rows(db: Session, customer: CustomerMaster) -> tuple[list[AccountBalanceSnapshot], str]:
    stmt = (
        select(AccountBalanceSnapshot)
        .where(AccountBalanceSnapshot.settlement_unit_code == customer.customer_code)
        .order_by(AccountBalanceSnapshot.data_date, AccountBalanceSnapshot.id)
    )
    rows = list(db.scalars(stmt).all())
    if rows:
        return rows, "strong"
    if not customer.customer_name:
        return [], "none"
    weak_rows = list(
        db.scalars(
            select(AccountBalanceSnapshot)
            .where(AccountBalanceSnapshot.settlement_unit_name == customer.customer_name)
            .order_by(AccountBalanceSnapshot.data_date, AccountBalanceSnapshot.id)
        ).all()
    )
    return weak_rows, "weak" if weak_rows else "none"


def _portrait_cutoff_date(sales_rows: list[SalesDetail], balance_rows: list[AccountBalanceSnapshot]) -> date | None:
    dates: list[date] = []
    dates.extend(row.document_date for row in sales_rows if row.document_date)
    dates.extend(row.data_date for row in balance_rows if row.data_date)
    return max(dates) if dates else None


def _has_hidden_field(db: Session, user: User, resource_type: str, fields: set[str]) -> bool:
    return any(
        rule.field_name in fields and rule.permission_type == "hidden"
        for rule in get_field_permission_rules(db, user, resource_type)
    )


def _decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _float(value: object) -> float:
    return float(_decimal(value))


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def _is_return_row(row: SalesDetail) -> bool:
    document_type = (row.document_type or "").lower()
    return _decimal(row.sale_qty_base) < 0 or _decimal(row.amount_tax_total) < 0 or "退货" in document_type or "return" in document_type


def _sales_amount(row: SalesDetail) -> Decimal:
    return _decimal(row.amount_tax_total)


def _sales_metrics(rows: list[SalesDetail], cutoff_date: date | None) -> dict:
    dated_rows = [row for row in rows if row.document_date]
    total_amount = sum((_sales_amount(row) for row in rows), Decimal("0"))
    total_abs_amount = sum((abs(_sales_amount(row)) for row in rows), Decimal("0"))
    total_gross_profit = sum((_decimal(row.gross_profit) for row in rows), Decimal("0"))
    document_nos = {row.document_no for row in rows if row.document_no}
    document_count = len(document_nos) if document_nos else len(rows)
    product_amounts: dict[str, Decimal] = defaultdict(Decimal)
    monthly_amounts: dict[date, Decimal] = defaultdict(Decimal)
    purchase_dates = sorted({row.document_date for row in dated_rows if row.document_date})
    for row in rows:
        product_name = row.product_name or "未命名商品"
        product_amounts[product_name] += abs(_sales_amount(row))
        if row.document_date:
            monthly_amounts[_month_start(row.document_date)] += _sales_amount(row)
    effective_cutoff = cutoff_date or (max(purchase_dates) if purchase_dates else None)
    if effective_cutoff:
        current_month = _month_start(effective_cutoff)
        last_month = _add_months(current_month, -1)
        recent_three_months = [_add_months(current_month, offset) for offset in (-2, -1, 0)]
        previous_three_months = [_add_months(current_month, offset) for offset in (-5, -4, -3)]
        last_month_amount = monthly_amounts.get(last_month, Decimal("0"))
        recent_30_start = effective_cutoff - timedelta(days=30)
        recent_30_amount = sum((_sales_amount(row) for row in dated_rows if row.document_date and row.document_date >= recent_30_start), Decimal("0"))
        recent_3m_avg = sum((monthly_amounts.get(month, Decimal("0")) for month in recent_three_months), Decimal("0")) / Decimal("3")
        previous_3m_avg = sum((monthly_amounts.get(month, Decimal("0")) for month in previous_three_months), Decimal("0")) / Decimal("3")
    else:
        last_month_amount = Decimal("0")
        recent_30_amount = Decimal("0")
        recent_3m_avg = Decimal("0")
        previous_3m_avg = Decimal("0")
    active_months = [amount for amount in monthly_amounts.values() if amount != 0]
    average_monthly_amount = total_amount / Decimal(max(1, len(monthly_amounts))) if monthly_amounts else Decimal("0")
    average_document_amount = total_amount / Decimal(max(1, document_count))
    return_count = sum(1 for row in rows if _is_return_row(row))
    return_ratio = Decimal(return_count) / Decimal(max(1, len(rows)))
    top_product = None
    top_product_ratio = Decimal("0")
    if product_amounts and total_abs_amount != 0:
        top_product, top_amount = max(product_amounts.items(), key=lambda item: item[1])
        top_product_ratio = top_amount / total_abs_amount
    interval_days: list[int] = []
    for index, day in enumerate(purchase_dates[1:], start=1):
        interval_days.append((day - purchase_dates[index - 1]).days)
    return {
        "total_amount": total_amount,
        "total_abs_amount": total_abs_amount,
        "total_gross_profit": total_gross_profit,
        "document_count": document_count,
        "transaction_rows": len(rows),
        "first_purchase_date": purchase_dates[0] if purchase_dates else None,
        "last_purchase_date": purchase_dates[-1] if purchase_dates else None,
        "last_month_amount": last_month_amount,
        "recent_30_amount": recent_30_amount,
        "recent_3m_avg": recent_3m_avg,
        "previous_3m_avg": previous_3m_avg,
        "average_monthly_amount": average_monthly_amount,
        "average_document_amount": average_document_amount,
        "active_month_count": len(active_months),
        "empty_month_count": max(0, len(monthly_amounts) - len(active_months)),
        "monthly_amounts": monthly_amounts,
        "return_count": return_count,
        "return_ratio": return_ratio,
        "top_product": top_product,
        "top_product_ratio": top_product_ratio,
        "purchase_dates": purchase_dates,
        "interval_days": interval_days,
    }


def _balance_metrics(rows: list[AccountBalanceSnapshot]) -> dict:
    latest = max(rows, key=lambda row: (row.data_date or date.min, row.id)) if rows else None
    latest_ar = _decimal(latest.ar_balance) if latest else Decimal("0")
    latest_advance_receipt = _decimal(latest.advance_receipt_balance) if latest else Decimal("0")
    return {
        "latest_ar_balance": latest_ar,
        "latest_advance_receipt_balance": latest_advance_receipt,
        "latest_balance_date": latest.data_date if latest else None,
    }


def _payment_risk_profile(balance_rows: list[AccountBalanceSnapshot], sales_metrics: dict) -> dict:
    latest = max(balance_rows, key=lambda row: (row.data_date or date.min, row.id)) if balance_rows else None
    latest_ar = _decimal(latest.ar_balance) if latest else Decimal("0")
    latest_advance_receipt = _decimal(latest.advance_receipt_balance) if latest else Decimal("0")
    recent_30_amount = _decimal(sales_metrics.get("recent_30_amount"))
    trend_value, trend_tone, trend_detail = _payment_debt_trend(balance_rows)
    aging_days = _payment_aging_days(balance_rows)
    aging_value, aging_tone, aging_detail = _payment_aging_tag(aging_days, latest_ar, bool(balance_rows))
    health_value, health_tone, health_detail = _payment_health_tag(latest_ar, trend_value)
    supply_risk_value, supply_risk_tone, supply_risk_detail = _payment_supply_risk_tag(latest_ar, recent_30_amount, trend_value)
    credit_value, credit_tone, credit_detail = "无额度", "neutral", "当前系统尚未维护客户信用额度，信用超额不参与本阶段评分。"
    supply_status_value, supply_status_tone, supply_status_detail = _payment_supply_status_tag(latest_ar, recent_30_amount)
    collection_value, collection_tone, collection_detail = "待设", "neutral", "催收状态为人工维护字段，本阶段只预留入口。"
    score, score_reasons = _payment_risk_score(latest_ar, aging_days, recent_30_amount, trend_value, sales_metrics)
    level, level_tone, action = _payment_risk_level(score)
    tags = [
        _tag_card("repayment_health", "回款健康度", health_value, health_tone, health_detail),
        _tag_card("aging", "账龄", aging_value, aging_tone, aging_detail),
        _tag_card("supply_risk", "供货风险", supply_risk_value, supply_risk_tone, supply_risk_detail),
        _tag_card("credit_overrun", "信用超额", credit_value, credit_tone, credit_detail),
        _tag_card("debt_trend", "欠款趋势", trend_value, trend_tone, trend_detail),
        _tag_card("supply_status", "是否供货", supply_status_value, supply_status_tone, supply_status_detail),
        _tag_card("collection_status", "催收状态", collection_value, collection_tone, collection_detail),
    ]
    quality_issues: list[str] = ["当前仅有往来快照，缺少逐笔回款明细，回款率相关评分因子暂不加分。"]
    if not balance_rows:
        quality_issues.append("当前客户暂无往来对账，账龄、欠款趋势和回款健康度无法精确判断。")
    return {
        "rule_version": "payment-risk-v0.1",
        "score": score,
        "level": level,
        "level_tone": level_tone,
        "action": action,
        "tags": tags,
        "score_reasons": score_reasons,
        "quality_issues": quality_issues,
        "metrics": {
            "latest_ar_balance": latest_ar,
            "latest_advance_receipt_balance": latest_advance_receipt,
            "latest_balance_date": latest.data_date if latest else None,
            "aging_days": aging_days,
            "recent_30_sales_amount": recent_30_amount,
            "repayment_rate_available": False,
            "credit_limit_available": False,
        },
    }


def _payment_debt_trend(rows: list[AccountBalanceSnapshot]) -> tuple[str, str, str]:
    dated_rows = [row for row in rows if row.data_date]
    if len(dated_rows) < 2:
        return "持平", "neutral", "往来快照不足 2 期，暂按持平展示。"
    recent_rows = sorted(dated_rows, key=lambda row: (row.data_date or date.min, row.id))[-3:]
    first = _decimal(recent_rows[0].ar_balance)
    latest = _decimal(recent_rows[-1].ar_balance)
    delta = latest - first
    if first == 0:
        ratio = Decimal("1") if delta > 0 else Decimal("0")
    else:
        ratio = delta / abs(first)
    if delta > Decimal("100000") or ratio > Decimal("0.5"):
        return "快速上升", "bad", f"最近 {len(recent_rows)} 期应收从 {first:.2f} 变为 {latest:.2f}。"
    if ratio > Decimal("0.1"):
        return "上升", "warn", f"最近 {len(recent_rows)} 期应收上升 {ratio:.1%}。"
    if ratio < Decimal("-0.1"):
        return "下降", "ok", f"最近 {len(recent_rows)} 期应收下降 {abs(ratio):.1%}。"
    return "持平", "neutral", f"最近 {len(recent_rows)} 期应收变化 {ratio:.1%}。"


def _payment_aging_days(rows: list[AccountBalanceSnapshot]) -> int | None:
    positive_dates = sorted(row.data_date for row in rows if row.data_date and _decimal(row.ar_balance) > 0)
    if not positive_dates:
        return 0 if rows else None
    return max(0, (positive_dates[-1] - positive_dates[0]).days)


def _payment_aging_tag(aging_days: int | None, latest_ar: Decimal, has_balance: bool) -> tuple[str, str, str]:
    if not has_balance:
        return "暂无往来数据", "neutral", "当前客户没有往来快照，无法近似账龄。"
    if latest_ar <= 0:
        return "正常", "ok", "当前应收余额不大于 0，账龄按正常展示。"
    days = aging_days or 0
    if days > 180:
        return "超长", "bad", f"连续有应收余额跨度约 {days} 天。"
    if days > 90:
        return "长期", "bad", f"连续有应收余额跨度约 {days} 天。"
    if days > 30:
        return "中期", "warn", f"连续有应收余额跨度约 {days} 天。"
    if days > 0:
        return "短期", "neutral", f"连续有应收余额跨度约 {days} 天。"
    return "正常", "ok", "仅最新快照存在应收或跨度不足 1 天。"


def _payment_health_tag(latest_ar: Decimal, trend: str) -> tuple[str, str, str]:
    if latest_ar <= 0:
        return "已结清", "ok", f"最新应收余额 {latest_ar:.2f}，无未清应收压力。"
    if latest_ar > Decimal("300000") or trend == "快速上升":
        return "高危", "bad", f"最新应收 {latest_ar:.2f}，且欠款趋势为{trend}。"
    if latest_ar > Decimal("100000") or trend == "上升":
        return "预警", "warn", f"最新应收 {latest_ar:.2f}，需要纳入催收跟踪。"
    if latest_ar > Decimal("50000"):
        return "关注", "warn", f"最新应收 {latest_ar:.2f}，超过关注阈值。"
    return "健康", "ok", f"最新应收 {latest_ar:.2f}，未触发高风险阈值。"


def _payment_supply_risk_tag(latest_ar: Decimal, recent_30_amount: Decimal, trend: str) -> tuple[str, str, str]:
    if latest_ar > Decimal("50000") and recent_30_amount > 0:
        return "高欠仍供", "bad", f"应收 {latest_ar:.2f}，近 30 天仍销售 {recent_30_amount:.2f}。"
    if latest_ar > 0 and trend in {"上升", "快速上升"}:
        return "欠款增长", "warn", f"应收 {latest_ar:.2f}，欠款趋势为{trend}。"
    if latest_ar > 0 and recent_30_amount <= 0:
        return "只欠不买", "warn", f"应收 {latest_ar:.2f}，近 30 天销售 {recent_30_amount:.2f}。"
    if latest_ar > 0 and recent_30_amount > 0 and trend == "下降":
        return "边买边还", "neutral", f"仍有应收 {latest_ar:.2f}，但欠款趋势下降。"
    return "低风险", "ok", "未发现高欠仍供、欠款增长或只欠不买信号。"


def _payment_supply_status_tag(latest_ar: Decimal, recent_30_amount: Decimal) -> tuple[str, str, str]:
    if latest_ar > 0 and recent_30_amount > 0:
        return "欠款仍供货", "warn", f"应收 {latest_ar:.2f}，近 30 天销售 {recent_30_amount:.2f}。"
    if latest_ar > 0 and recent_30_amount <= 0:
        return "暂停交易", "neutral", f"仍有应收 {latest_ar:.2f}，近 30 天无正向销售。"
    if latest_ar <= 0 and recent_30_amount > 0:
        return "现款交易", "ok", f"应收 {latest_ar:.2f}，近 30 天有销售 {recent_30_amount:.2f}。"
    return "无交易", "neutral", "近 30 天无正向销售，且无未清应收。"


def _payment_risk_score(
    latest_ar: Decimal,
    aging_days: int | None,
    recent_30_amount: Decimal,
    trend: str,
    sales_metrics: dict,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = ["缺少逐笔回款明细，回款率 0% 和回款恶化因子暂不计分。"]
    if latest_ar > Decimal("300000"):
        score += 35
        reasons.append("欠款 > 300000：+35")
    elif latest_ar > Decimal("100000"):
        score += 20
        reasons.append("欠款 > 100000：+20")
    days = aging_days or 0
    if days > 180:
        score += 50
        reasons.append("近似账龄 > 180 天：+50")
    elif days > 90:
        score += 35
        reasons.append("近似账龄 > 90 天：+35")
    elif days >= 30:
        score += 20
        reasons.append("近似账龄 30-90 天：+20")
    if latest_ar > Decimal("50000") and recent_30_amount > 0:
        score += 30
        reasons.append("欠款 > 50000 且近 30 天仍供货：+30")
    active_month_count = int(sales_metrics.get("active_month_count") or 0)
    if active_month_count <= 3 and latest_ar > 0:
        reasons.append("活跃月 <= 3 且欠款 > 0，但缺少回款率，暂不加新客惩罚分。")
    if trend == "快速上升" and latest_ar > 0:
        reasons.append("欠款快速上升，已反映在健康度与供货风险标签。")
    return score, reasons


def _payment_risk_level(score: int) -> tuple[str, str, str]:
    if score >= 90:
        return "一级", "bad", "冻结供货 + 老板介入 + 法律途径评估"
    if score >= 60:
        return "二级", "bad", "限制供货 + 本周催收 + 设置账期上限"
    if score >= 30:
        return "三级", "warn", "持续关注 + 季度复查"
    return "观察", "ok", "正常跟踪 + 不预警"


def _deep_customer_profile(customer: CustomerMaster, tags: list[dict], payment: dict, sales_metrics: dict, balance_metrics: dict) -> dict:
    tag_map = {item["key"]: item for item in tags}
    customer_name = customer.customer_name
    scale = _tag_value(tag_map, "scale")
    rfm = _tag_value(tag_map, "rfm")
    category = _tag_value(tag_map, "category")
    top_product = _tag_value(tag_map, "top_product")
    margin = _tag_value(tag_map, "margin")
    return_tag = _tag_value(tag_map, "return")
    lifecycle = _tag_value(tag_map, "lifecycle")
    repurchase = _tag_value(tag_map, "repurchase")
    growth = _tag_value(tag_map, "growth")
    payment_level = str(payment.get("level") or "观察")
    payment_action = str(payment.get("action") or "正常跟踪 + 不预警")
    payment_score = int(payment.get("score") or 0)
    latest_ar = _decimal(balance_metrics.get("latest_ar_balance"))
    total_amount = _decimal(sales_metrics.get("total_amount"))
    total_abs_amount = _decimal(sales_metrics.get("total_abs_amount"))
    gross_profit = _decimal(sales_metrics.get("total_gross_profit"))
    document_count = int(sales_metrics.get("document_count") or 0)
    recent_30_amount = _decimal(sales_metrics.get("recent_30_amount"))
    top_product_ratio = _decimal(sales_metrics.get("top_product_ratio"))
    first_purchase = sales_metrics.get("first_purchase_date")
    last_purchase = sales_metrics.get("last_purchase_date")
    positioning = f"{scale} / {payment_level}"
    headline = f"{customer_name}：{positioning}"
    conclusions = [
        f"不是简单按客户名称归档，而是按「{scale}、{rfm}、{lifecycle}」综合定位。",
        f"经营上累计销售 {total_amount:.2f}，共 {document_count} 单，主力品类为「{category}」。",
        f"回款风险当前为「{payment_level}」，评分 {payment_score} 分，建议动作：{payment_action}。"
    ]
    sections = [
        {
            "key": "positioning",
            "title": "一、客户定位",
            "summary": f"{customer_name} 当前定位为「{positioning}」，不是单一交易客户，而是需要结合交易活跃度、品类和回款风险共同判断。",
            "items": [
                {"label": "客户等级", "value": scale, "detail": _tag_detail(tag_map, "scale")},
                {"label": "风险类型", "value": payment_level, "detail": payment_action},
                {"label": "RFM", "value": rfm, "detail": _tag_detail(tag_map, "rfm")},
                {"label": "生命周期", "value": lifecycle, "detail": _tag_detail(tag_map, "lifecycle")},
                {"label": "渠道", "value": _tag_value(tag_map, "channel"), "detail": _tag_detail(tag_map, "channel")},
                {"label": "品类", "value": category, "detail": _tag_detail(tag_map, "category")},
                {"label": "大单品", "value": top_product, "detail": _tag_detail(tag_map, "top_product")},
                {"label": "业务员", "value": customer.salesperson_name or "-", "detail": "业务责任归属来自客户档案。"},
                {"label": "区域", "value": customer.region or "-", "detail": "区域来自客户档案。"},
            ],
            "bullets": [
                f"该客户的管理重点不是先扩大供货，而是先确认「{payment_level}」风险是否稳定。",
                f"如果后续补齐销售与回款流水，可进一步校准 {rfm} 与 {payment_level}。"
            ],
        },
        {
            "key": "performance",
            "title": "二、经营表现",
            "summary": f"累计销售 {total_amount:.2f}，近 30 天销售 {recent_30_amount:.2f}，单据数 {document_count}。",
            "items": [
                {"label": "累计销售额", "value": f"{total_amount:.2f}", "detail": "来自当前已导入销售明细。"},
                {"label": "累计毛利", "value": f"{gross_profit:.2f}", "detail": f"毛利标签：{margin}。"},
                {"label": "单据数", "value": str(document_count), "detail": "按销售单号去重，不足时按明细行数。"},
                {"label": "近 30 天销售", "value": f"{recent_30_amount:.2f}", "detail": "按画像数据截止日向前滚动 30 天。"},
            ],
            "bullets": [
                f"增长趋势为「{growth}」，需要结合近期导入周期判断是否为真实趋势。",
                f"退货标签为「{return_tag}」，若持续偏高，应复核商品、价格和开单口径。",
                f"回购周期为「{repurchase}」，可以作为后续拜访频率参考。"
            ],
        },
        {
            "key": "preference",
            "title": "三、采购偏好",
            "summary": f"当前识别主品类为「{category}」，代表商品为「{top_product}」。",
            "items": [
                {"label": "主品类", "value": category, "detail": _tag_detail(tag_map, "category")},
                {"label": "代表商品", "value": top_product, "detail": _tag_detail(tag_map, "top_product")},
                {"label": "单品集中度", "value": f"{top_product_ratio:.1%}", "detail": "最大单品销售额占客户总销售额比例。"},
            ],
            "bullets": [
                f"若「{top_product}」持续占比高，后续报价、库存和替代品策略应围绕该商品展开。",
                "当前品类词库仍偏基础，后续接商品分类和品牌后可进一步细化。"
            ],
        },
        {
            "key": "strengths",
            "title": "四、客户优势",
            "summary": "本段只列有数据依据的正向信号。",
            "bullets": _profile_strengths(scale, rfm, category, payment_level, total_abs_amount, latest_ar),
        },
        {
            "key": "weaknesses",
            "title": "五、客户短板",
            "summary": "本段覆盖资料、交易、退货、毛利和回款风险中的主要短板。",
            "bullets": _profile_weaknesses(customer, margin, return_tag, repurchase, payment_level, latest_ar, total_amount),
        },
        {
            "key": "max_risk",
            "title": "六、最大风险",
            "summary": _profile_max_risk(customer_name, payment_level, latest_ar, recent_30_amount, return_tag),
            "items": [
                {"label": "风险等级", "value": payment_level, "detail": payment_action},
                {"label": "最新应收", "value": f"{latest_ar:.2f}", "detail": "来自最新往来快照。"},
                {"label": "近 30 天销售", "value": f"{recent_30_amount:.2f}", "detail": "用于判断是否欠款仍供。"},
            ],
        },
        {
            "key": "advice",
            "title": "七、管理建议",
            "summary": "建议优先做到可执行、可复查、可追责。",
            "bullets": [
                f"供货策略：按「{payment_level}」执行，当前建议为「{payment_action}」。",
                "额度策略：当前无信用额度字段，暂不自动判断超额；建议先维护客户额度后再启用信用超额评分。",
                "催收策略：缺少逐笔回款明细，本阶段不推导回款率；建议补充应收清单或回款流水。",
                "复查节点：每次导入销售明细和往来对账后刷新客户画像。"
            ],
        },
        {
            "key": "actions",
            "title": "八、建议动作",
            "summary": "按 P0/P1/P2 给出可落地动作。",
            "items": [
                {"label": "P0", "value": "复核回款风险", "detail": f"负责人：{customer.salesperson_name or '当前业务员'}；时间：本周内。"},
                {"label": "P1", "value": "补齐客户资料", "detail": "补联系电话、地址、联系人，减少资料缺口。"},
                {"label": "P2", "value": "跟踪商品偏好", "detail": f"围绕「{category} / {top_product}」观察后续销售和退货。"},
            ],
        },
        {
            "key": "final",
            "title": "九、最终判断",
            "summary": f"{customer_name} 当前不是只看销售额的客户，而是「{scale}、{category}、{payment_level}」共同决定管理策略的客户。",
            "bullets": [
                f"管理关键词：{scale}",
                f"管理关键词：{category}",
                f"管理关键词：{payment_level}",
                f"管理关键词：{growth}",
                f"管理关键词：{return_tag}",
            ],
        },
    ]
    return {
        "rule_version": "deep-profile-v0.1",
        "headline": headline,
        "positioning": positioning,
        "conclusions": conclusions,
        "sections": sections,
        "keywords": [scale, category, payment_level, growth, return_tag],
        "evidence": {
            "first_purchase_date": first_purchase,
            "last_purchase_date": last_purchase,
            "total_amount": total_amount,
            "document_count": document_count,
            "latest_ar_balance": latest_ar,
        },
    }


def _tag_value(tag_map: dict[str, dict], key: str) -> str:
    return str((tag_map.get(key) or {}).get("value") or "-")


def _tag_detail(tag_map: dict[str, dict], key: str) -> str:
    return str((tag_map.get(key) or {}).get("detail") or "暂无说明。")


def _profile_strengths(scale: str, rfm: str, category: str, payment_level: str, total_abs_amount: Decimal, latest_ar: Decimal) -> list[str]:
    strengths: list[str] = []
    if total_abs_amount > 0:
        strengths.append(f"已有可追溯交易数据，累计交易绝对额 {total_abs_amount:.2f}，不是空白客户。")
    if category not in {"暂无足够交易数据", "-", "综合"}:
        strengths.append(f"品类偏好较清晰，当前主品类为「{category}」。")
    if payment_level == "观察" and latest_ar <= 0:
        strengths.append("当前回款风险处于观察且无正向应收压力。")
    if "活跃" in rfm:
        strengths.append(f"RFM 显示为「{rfm}」，近期仍有业务信号。")
    if scale in {"A类", "B类"}:
        strengths.append(f"规模标签为「{scale}」，具备重点经营价值。")
    return strengths or ["当前正向信号不足，建议先补齐交易和回款数据后再判断客户优势。"]


def _profile_weaknesses(
    customer: CustomerMaster,
    margin: str,
    return_tag: str,
    repurchase: str,
    payment_level: str,
    latest_ar: Decimal,
    total_amount: Decimal,
) -> list[str]:
    weaknesses: list[str] = []
    missing = _customer_completeness(_serialize_row_for_completeness(customer))
    if missing != "完整":
        weaknesses.append(f"基础资料不完整：{missing}。")
    if margin in {"低", "负"}:
        weaknesses.append(f"毛利标签为「{margin}」，需要复核报价、成本或退货影响。")
    if return_tag == "偏高":
        weaknesses.append("退货比例偏高，可能影响真实销售和毛利判断。")
    if repurchase in {"单次", "长周期"}:
        weaknesses.append(f"回购周期为「{repurchase}」，客户粘性仍需验证。")
    if payment_level in {"一级", "二级", "三级"} or latest_ar > 0:
        weaknesses.append(f"存在回款关注点，当前应收 {latest_ar:.2f}。")
    if total_amount <= 0:
        weaknesses.append(f"累计销售额 {total_amount:.2f}，可能受退货或负向单据影响。")
    return weaknesses or ["当前未发现明显短板，建议继续跟踪销售、回款和资料完整度。"]


def _profile_max_risk(customer_name: str, payment_level: str, latest_ar: Decimal, recent_30_amount: Decimal, return_tag: str) -> str:
    if payment_level in {"一级", "二级"}:
        return f"{customer_name} 最大风险是应收压力扩大后仍继续供货，可能形成资金占用；当前应收 {latest_ar:.2f}，近 30 天销售 {recent_30_amount:.2f}。"
    if latest_ar > 0 and recent_30_amount > 0:
        return f"{customer_name} 当前风险是欠款仍供货，应收 {latest_ar:.2f} 且近 30 天仍有销售 {recent_30_amount:.2f}。"
    if return_tag == "偏高":
        return f"{customer_name} 当前最大异常是退货偏高，可能扭曲销售额、毛利和增长趋势。"
    return f"{customer_name} 当前没有触发高等级回款风险，最大风险是数据不足导致判断偏差。"


def _portrait_tag_cards(customer: CustomerMaster, rows: list[SalesDetail], metrics: dict, hide_margin: bool) -> list[dict]:
    has_sales = len(rows) > 0
    cutoff_date = metrics.get("last_purchase_date")
    no_sales_detail = "暂无足够交易数据"
    tags = [
        _tag_card("scale", "规模", *_tag_scale(metrics) if has_sales else (no_sales_detail, "neutral", "当前客户暂无销售明细，无法按上月销售额分层。")),
        _tag_card("rfm", "RFM", *_tag_rfm(metrics, cutoff_date) if has_sales else (no_sales_detail, "neutral", "缺少最近购买、频次和金额数据。")),
        _tag_card("channel", "渠道", *_tag_channel(customer)),
        _tag_card("category", "品类", *_tag_category(rows) if has_sales else (no_sales_detail, "neutral", "缺少商品销售明细，无法识别品类。")),
        _tag_card("top_product", "大单品", *_tag_top_product(metrics) if has_sales else (no_sales_detail, "neutral", "缺少商品销售明细，无法识别大单品。")),
        _tag_card("margin", "毛利", *_tag_margin(metrics, hide_margin) if has_sales else (no_sales_detail, "neutral", "缺少销售额和毛利数据。")),
        _tag_card("return", "退货", *_tag_return(metrics) if has_sales else (no_sales_detail, "neutral", "缺少销售明细，无法识别退货比例。")),
        _tag_card("stability", "稳定性", *_tag_stability(metrics) if has_sales else (no_sales_detail, "neutral", "缺少月度销售额，无法判断稳定性。")),
        _tag_card("lifecycle", "生命周期", *_tag_lifecycle(metrics, cutoff_date) if has_sales else (no_sales_detail, "neutral", "缺少首次和最近购买日期。")),
        _tag_card("avg_order", "客单价", *_tag_average_order(metrics) if has_sales else (no_sales_detail, "neutral", "缺少单据金额，无法判断客单价。")),
        _tag_card("repurchase", "回购周期", *_tag_repurchase(metrics) if has_sales else (no_sales_detail, "neutral", "缺少购买间隔，无法判断回购周期。")),
        _tag_card("growth", "增长趋势", *_tag_growth(metrics) if has_sales else (no_sales_detail, "neutral", "缺少最近 3 月和前 3 月对比数据。")),
    ]
    return tags


def _tag_card(key: str, label: str, value: str, tone: str, detail: str) -> dict:
    return {"key": key, "label": label, "value": value, "tone": tone, "detail": detail}


def _tag_scale(metrics: dict) -> tuple[str, str, str]:
    amount = abs(_decimal(metrics.get("last_month_amount")))
    if amount >= Decimal("50000"):
        return "A类", "ok", f"上月销售额 {amount:.2f}，达到 A 类阈值。"
    if amount >= Decimal("5000"):
        return "B类", "neutral", f"上月销售额 {amount:.2f}，处于 B 类区间。"
    return "C类", "warn", f"上月销售额 {amount:.2f}，低于 5000。"


def _tag_rfm(metrics: dict, cutoff_date: date | None) -> tuple[str, str, str]:
    last_purchase = metrics.get("last_purchase_date")
    if not last_purchase or not cutoff_date:
        return "暂无足够交易数据", "neutral", "缺少最近购买日期。"
    recency_days = max(0, (cutoff_date - last_purchase).days)
    average_monthly_count = Decimal(metrics.get("document_count") or 0) / Decimal(max(1, metrics.get("active_month_count") or 1))
    average_monthly_amount = abs(_decimal(metrics.get("average_monthly_amount")))
    if recency_days <= 14 and average_monthly_count >= 3 and average_monthly_amount >= Decimal("10000"):
        value = "活跃高频高值"
        tone = "ok"
    elif recency_days <= 30 and average_monthly_count >= 1:
        value = "活跃中值"
        tone = "neutral"
    elif recency_days > 90:
        value = "沉默低频"
        tone = "warn"
    else:
        value = "低频观察"
        tone = "warn"
    return value, tone, f"最近购买 {recency_days} 天前，月均 {average_monthly_count:.1f} 单，月均销售 {average_monthly_amount:.2f}。"


def _tag_channel(customer: CustomerMaster) -> tuple[str, str, str]:
    code = (customer.customer_code or "").upper()
    if code.startswith("LSS"):
        return "快马", "neutral", "客户编号以 LSS 开头，按快马渠道识别。"
    return "门面", "neutral", "客户编号非 LSS 开头，按门面渠道识别。"


def _tag_category(rows: list[SalesDetail]) -> tuple[str, str, str]:
    total = sum((abs(_sales_amount(row)) for row in rows), Decimal("0"))
    chicken_keywords = ("鸡", "腿", "翅", "胸", "排")
    chicken_amount = sum(
        (abs(_sales_amount(row)) for row in rows if any(keyword in (row.product_name or "") for keyword in chicken_keywords)),
        Decimal("0"),
    )
    ratio = chicken_amount / total if total else Decimal("0")
    if ratio > Decimal("0.5"):
        return "鸡肉", "ok", f"鸡肉相关商品销售占比 {ratio:.1%}，超过 50%。"
    return "综合", "neutral", f"鸡肉相关商品销售占比 {ratio:.1%}，暂归为综合品类。"


def _tag_top_product(metrics: dict) -> tuple[str, str, str]:
    product = metrics.get("top_product")
    ratio = _decimal(metrics.get("top_product_ratio"))
    if product and ratio > Decimal("0.4"):
        return str(product), "ok", f"单一商品销售占比 {ratio:.1%}，超过 40%。"
    return "综合", "neutral", f"最大单品销售占比 {ratio:.1%}，未超过 40%。"


def _tag_margin(metrics: dict, hide_margin: bool) -> tuple[str, str, str]:
    if hide_margin:
        return "权限隐藏", "neutral", "当前账号无毛利或成本字段查看权限，不展示毛利画像结论。"
    total = _decimal(metrics.get("total_amount"))
    gross = _decimal(metrics.get("total_gross_profit"))
    if total == 0:
        return "-", "neutral", "累计销售额为 0，毛利率无法计算。"
    ratio = gross / total
    if ratio < 0:
        return "负", "bad", f"累计毛利率 {ratio:.1%}，低于 0。"
    if ratio > Decimal("0.25"):
        return "高", "ok", f"累计毛利率 {ratio:.1%}，高于 25%。"
    if ratio >= Decimal("0.10"):
        return "中", "neutral", f"累计毛利率 {ratio:.1%}，处于 10%-25%。"
    return "低", "warn", f"累计毛利率 {ratio:.1%}，低于 10%。"


def _tag_return(metrics: dict) -> tuple[str, str, str]:
    ratio = _decimal(metrics.get("return_ratio"))
    count = int(metrics.get("return_count") or 0)
    if ratio > Decimal("0.1"):
        return "偏高", "warn", f"退货 {count} 笔，占比 {ratio:.1%}，超过 10%。"
    return "正常", "ok", f"退货 {count} 笔，占比 {ratio:.1%}。"


def _tag_stability(metrics: dict) -> tuple[str, str, str]:
    rows = int(metrics.get("transaction_rows") or 0)
    if rows < 3:
        return "新客期", "neutral", f"总交易明细 {rows} 行，低于 3 行。"
    monthly_amounts = [_float(value) for value in metrics.get("monthly_amounts", {}).values()]
    if not monthly_amounts:
        return "暂无足够交易数据", "neutral", "缺少月度销售数据。"
    if any(value == 0 for value in monthly_amounts) or int(metrics.get("empty_month_count") or 0) > 0:
        return "间歇", "warn", "月度销售存在空月或断档。"
    mean = sum(monthly_amounts) / len(monthly_amounts)
    if mean == 0:
        return "间歇", "warn", "月均销售额为 0。"
    variance = sum((value - mean) ** 2 for value in monthly_amounts) / len(monthly_amounts)
    cv = (variance ** 0.5) / abs(mean)
    if cv > 0.5:
        return "波动", "warn", f"月度销售额变异系数 {cv:.2f}，超过 0.5。"
    return "稳定", "ok", f"月度销售额变异系数 {cv:.2f}。"


def _tag_lifecycle(metrics: dict, cutoff_date: date | None) -> tuple[str, str, str]:
    first_purchase = metrics.get("first_purchase_date")
    last_purchase = metrics.get("last_purchase_date")
    if not first_purchase or not last_purchase or not cutoff_date:
        return "暂无足够交易数据", "neutral", "缺少首次或最近购买日期。"
    first_days = (cutoff_date - first_purchase).days
    silent_days = (cutoff_date - last_purchase).days
    if first_days <= 90:
        return "新客", "neutral", f"首次购买距数据截止日 {first_days} 天。"
    if silent_days > 90:
        return "沉默", "warn", f"最近购买距数据截止日 {silent_days} 天。"
    return "成熟", "ok", f"首次购买 {first_days} 天前，最近购买 {silent_days} 天前。"


def _tag_average_order(metrics: dict) -> tuple[str, str, str]:
    average = abs(_decimal(metrics.get("average_document_amount")))
    monthly = abs(_decimal(metrics.get("average_monthly_amount")))
    if average >= monthly * Decimal("1.5") and monthly > 0:
        return "高", "ok", f"平均单据销售额 {average:.2f}，高于客户月均销售额参考。"
    if monthly > 0 and average <= monthly * Decimal("0.5"):
        return "低", "warn", f"平均单据销售额 {average:.2f}，低于客户月均销售额参考。"
    return "中", "neutral", f"平均单据销售额 {average:.2f}。"


def _tag_repurchase(metrics: dict) -> tuple[str, str, str]:
    intervals = metrics.get("interval_days") or []
    if not intervals:
        return "单次", "warn", "只有一次或没有可计算购买间隔。"
    median_interval = median(intervals)
    if median_interval <= 3:
        return "高频", "ok", f"购买间隔中位数 {median_interval:.0f} 天。"
    if median_interval <= 14:
        return "常规", "neutral", f"购买间隔中位数 {median_interval:.0f} 天。"
    return "长周期", "warn", f"购买间隔中位数 {median_interval:.0f} 天。"


def _tag_growth(metrics: dict) -> tuple[str, str, str]:
    recent = _decimal(metrics.get("recent_3m_avg"))
    previous = _decimal(metrics.get("previous_3m_avg"))
    if previous == 0 and recent == 0:
        return "平稳", "neutral", "最近 3 月和前 3 月月均销售额均为 0。"
    if previous == 0:
        if recent > 0:
            return "上升", "ok", f"前 3 月为 0，最近 3 月月均销售 {recent:.2f}。"
        return "下降", "warn", f"前 3 月为 0，最近 3 月月均销售 {recent:.2f}。"
    change = (recent - previous) / abs(previous)
    if change > Decimal("0.3"):
        return "上升", "ok", f"最近 3 月月均较前 3 月上升 {change:.1%}。"
    if change < Decimal("-0.3"):
        return "下降", "warn", f"最近 3 月月均较前 3 月下降 {abs(change):.1%}。"
    return "平稳", "neutral", f"最近 3 月月均较前 3 月变化 {change:.1%}。"


def _customer_completeness(data: dict) -> str:
    missing = []
    if not data.get("contact_phone"):
        missing.append("缺电话")
    if not data.get("address"):
        missing.append("缺地址")
    if not data.get("contact_name"):
        missing.append("缺联系人")
    return "完整" if not missing else " / ".join(missing)


def _historical_salespersons(db: Session, customer_code: str) -> str | None:
    rows = list(
        db.scalars(
            select(CustomerOwnerHistory)
            .where(CustomerOwnerHistory.customer_code == customer_code)
            .order_by(CustomerOwnerHistory.changed_at.desc())
            .limit(5)
        ).all()
    )
    history = [row.old_employee_code for row in rows if row.old_employee_code]
    unique_history = list(dict.fromkeys(history))
    return "、".join(unique_history) if unique_history else None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _customer_audit_snapshot(customer: CustomerMaster) -> dict:
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


def _product_audit_snapshot(product: ProductMaster) -> dict:
    return {
        "product_code": product.product_code,
        "product_name": product.product_name,
        "spec": product.spec,
        "unit": product.unit,
        "category": product.category,
        "brand": product.brand,
        "barcode": product.barcode,
        "reference_sale_price": str(product.reference_sale_price) if product.reference_sale_price is not None else None,
        "reference_cost": str(product.reference_cost) if product.reference_cost is not None else None,
        "status": product.status,
        "source": product.source,
    }


def _supplier_audit_snapshot(supplier: SupplierMaster) -> dict:
    return {
        "supplier_code": supplier.supplier_code,
        "supplier_name": supplier.supplier_name,
        "supplier_short_name": supplier.supplier_short_name,
        "supplier_type": supplier.supplier_type,
        "region": supplier.region,
        "contact_name": supplier.contact_name,
        "contact_phone": supplier.contact_phone,
        "address": supplier.address,
        "status": supplier.status,
        "source": supplier.source,
    }


@router.get("/products", response_model=list[ProductMasterPublic])
def list_products(
    q: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("product.view")),
) -> list[dict]:
    safe_limit = max(1, min(limit, 5000))
    stmt = select(ProductMaster).order_by(ProductMaster.product_code)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((ProductMaster.product_code.ilike(like)) | (ProductMaster.product_name.ilike(like)))
    stmt = apply_data_scope(stmt, ProductMaster, db, current_user, "product").limit(safe_limit)
    rows = list(db.scalars(stmt).all())
    return serialize_many_with_field_rules(db, current_user, "product", rows)


@router.get("/products/page")
def list_products_page(
    q: str | None = None,
    category_path: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("product.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(ProductMaster).order_by(ProductMaster.product_code)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((ProductMaster.product_code.ilike(like)) | (ProductMaster.product_name.ilike(like)))
    stmt = apply_data_scope(stmt, ProductMaster, db, current_user, "product")
    selected_path = _parse_category_path(category_path)
    if selected_path:
        candidates = list(db.scalars(stmt).all())
        category_paths_by_code = _resource_category_paths(
            db,
            kind="products",
            resource_codes=[row.product_code for row in candidates],
        )
        matched = [
            row for row in candidates
            if _row_matches_category([*category_paths_by_code.get(row.product_code, []), _product_category_path(row)], selected_path)
        ]
        total = len(matched)
        page_rows = matched[safe_offset : safe_offset + safe_limit]
        return _page_response(serialize_many_with_field_rules(db, current_user, "product", page_rows), total, safe_limit, safe_offset)
    total = _count_stmt(db, stmt)
    rows = list(db.scalars(stmt.offset(safe_offset).limit(safe_limit)).all())
    return _page_response(serialize_many_with_field_rules(db, current_user, "product", rows), total, safe_limit, safe_offset)


@router.get("/products/hierarchy")
def product_hierarchy(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("product.view")),
) -> dict:
    stmt = apply_data_scope(select(ProductMaster).order_by(ProductMaster.product_code), ProductMaster, db, current_user, "product")
    products = list(db.scalars(stmt).all())
    return _persistent_category_tree(
        db,
        kind="products",
        root_label="全部商品",
        rows=products,
        code_getter=lambda row: row.product_code,
        fallback_path_getter=_product_category_path,
        abnormal_getter=_product_abnormal,
    )


@router.get("/categories/{kind}/nodes", response_model=list[MasterCategoryNodePublic])
def list_master_category_nodes(
    kind: str,
    include_disabled: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer.view", "product.view")),
) -> list[MasterCategoryNode]:
    normalized_kind = _category_kind_or_400(kind)
    stmt = select(MasterCategoryNode).where(MasterCategoryNode.kind == normalized_kind)
    if not include_disabled:
        stmt = stmt.where(MasterCategoryNode.is_enabled.is_(True))
    return list(db.scalars(stmt.order_by(MasterCategoryNode.parent_id.asc().nullsfirst(), MasterCategoryNode.sort_order.asc(), MasterCategoryNode.id.asc())).all())


@router.post("/categories/{kind}/nodes", response_model=MasterCategoryNodePublic, status_code=status.HTTP_201_CREATED)
def create_master_category_node(
    kind: str,
    payload: MasterCategoryNodeUpsert,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer.edit", "product.edit", "import.commit")),
) -> MasterCategoryNode:
    normalized_kind = _category_kind_or_400(kind)
    label = _clean_text(payload.label)
    if not label:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category label is required")
    if payload.parent_id is not None:
        parent = _category_or_404(db, payload.parent_id)
        if parent.kind != normalized_kind:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent category kind mismatch")
    duplicate = db.scalar(
        select(MasterCategoryNode).where(
            MasterCategoryNode.kind == normalized_kind,
            MasterCategoryNode.parent_id.is_(None) if payload.parent_id is None else MasterCategoryNode.parent_id == payload.parent_id,
            MasterCategoryNode.label == label,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category label already exists under this parent")
    node = MasterCategoryNode(
        node_code=generate_category_node_code(normalized_kind),
        kind=normalized_kind,
        label=label,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
        is_enabled=payload.is_enabled,
        remark=_clean_text(payload.remark),
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
    )
    db.add(node)
    db.flush()
    write_audit_log(
        db,
        action_type="create_master_category",
        resource_type="master_category",
        resource_id=str(node.id),
        user=current_user,
        request=request,
        after_data=_node_audit_snapshot(node),
    )
    db.commit()
    db.refresh(node)
    return node


@router.patch("/categories/nodes/{category_id}", response_model=MasterCategoryNodePublic)
def update_master_category_node(
    category_id: int,
    payload: MasterCategoryNodeUpsert,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer.edit", "product.edit", "import.commit")),
) -> MasterCategoryNode:
    node = _category_or_404(db, category_id)
    label = _clean_text(payload.label)
    if not label:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category label is required")
    if payload.parent_id == node.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category cannot be its own parent")
    if payload.parent_id is not None:
        parent = _category_or_404(db, payload.parent_id)
        if parent.kind != node.kind:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent category kind mismatch")
        if parent.id in _category_descendant_ids(db, node.id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category cannot move under its descendant")
    duplicate = db.scalar(
        select(MasterCategoryNode).where(
            MasterCategoryNode.id != node.id,
            MasterCategoryNode.kind == node.kind,
            MasterCategoryNode.parent_id.is_(None) if payload.parent_id is None else MasterCategoryNode.parent_id == payload.parent_id,
            MasterCategoryNode.label == label,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category label already exists under this parent")
    before = _node_audit_snapshot(node)
    node.label = label
    node.parent_id = payload.parent_id
    node.sort_order = payload.sort_order
    node.is_enabled = payload.is_enabled
    node.remark = _clean_text(payload.remark)
    node.updated_by_user_id = current_user.id
    write_audit_log(
        db,
        action_type="update_master_category",
        resource_type="master_category",
        resource_id=str(node.id),
        user=current_user,
        request=request,
        before_data=before,
        after_data=_node_audit_snapshot(node),
    )
    db.commit()
    db.refresh(node)
    return node


@router.delete("/categories/nodes/{category_id}")
def delete_master_category_node(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer.edit", "product.edit", "import.commit")),
) -> dict:
    node = _category_or_404(db, category_id)
    before = _node_audit_snapshot(node)
    descendant_ids = _category_descendant_ids(db, node.id)
    binding_count = db.scalar(select(func.count()).select_from(MasterCategoryBinding).where(MasterCategoryBinding.category_id.in_(descendant_ids))) or 0
    db.execute(delete(MasterCategoryBinding).where(MasterCategoryBinding.category_id.in_(descendant_ids)))
    db.execute(delete(MasterCategoryNode).where(MasterCategoryNode.id.in_(descendant_ids)))
    write_audit_log(
        db,
        action_type="delete_master_category",
        resource_type="master_category",
        resource_id=str(category_id),
        user=current_user,
        request=request,
        before_data=before,
        after_data={"deleted_category_ids": sorted(descendant_ids), "deleted_bindings": binding_count},
    )
    db.commit()
    return {"status": "deleted", "deleted_category_ids": sorted(descendant_ids), "deleted_bindings": binding_count}


@router.post("/categories/nodes/{category_id}/bindings", response_model=MasterCategoryBindingPublic, status_code=status.HTTP_201_CREATED)
def bind_master_category_resource(
    category_id: int,
    payload: MasterCategoryBindingCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer.edit", "product.edit", "import.commit")),
) -> MasterCategoryBinding:
    node = _category_or_404(db, category_id)
    if node.kind not in {"customers", "products"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only customer/product categories can bind records")
    resource_code = payload.resource_code.strip()
    if node.kind == "customers" and not db.scalar(select(CustomerMaster.customer_code).where(CustomerMaster.customer_code == resource_code)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    if node.kind == "products" and not db.scalar(select(ProductMaster.product_code).where(ProductMaster.product_code == resource_code)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    binding = bind_resource_to_category(
        db,
        category=node,
        resource_code=resource_code,
        is_primary=payload.is_primary,
        source=payload.source,
        created_by_user_id=current_user.id,
    )
    db.flush()
    write_audit_log(
        db,
        action_type="bind_master_category",
        resource_type="master_category_binding",
        resource_id=str(binding.id),
        user=current_user,
        request=request,
        after_data=_binding_audit_snapshot(binding),
    )
    db.commit()
    db.refresh(binding)
    return binding


@router.delete("/categories/nodes/{category_id}/bindings/{resource_code}")
def unbind_master_category_resource(
    category_id: int,
    resource_code: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("customer.edit", "product.edit", "import.commit")),
) -> dict:
    node = _category_or_404(db, category_id)
    resource_type = category_resource_type(node.kind)
    binding = db.scalar(
        select(MasterCategoryBinding).where(
            MasterCategoryBinding.category_id == category_id,
            MasterCategoryBinding.resource_type == resource_type,
            MasterCategoryBinding.resource_code == resource_code,
        )
    )
    if binding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category binding not found")
    before = _binding_audit_snapshot(binding)
    db.delete(binding)
    write_audit_log(
        db,
        action_type="unbind_master_category",
        resource_type="master_category_binding",
        resource_id=str(binding.id),
        user=current_user,
        request=request,
        before_data=before,
        after_data={"status": "deleted"},
    )
    db.commit()
    return {"status": "deleted", "resource_code": resource_code, "category_id": category_id}


@router.get("/products/{product_code}", response_model=ProductMasterPublic)
def get_product(
    product_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("product.view")),
) -> dict:
    stmt = select(ProductMaster).where(ProductMaster.product_code == product_code)
    stmt = apply_data_scope(stmt, ProductMaster, db, current_user, "product")
    product = db.scalar(stmt)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return serialize_with_field_rules(db, current_user, "product", product)


@router.post("/products", response_model=ProductMasterPublic, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductMasterCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("product.edit")),
) -> dict:
    product_code = _clean_text(payload.product_code)
    product_name = _clean_text(payload.product_name)
    if not product_code or not product_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product code and name are required")
    if db.scalar(select(ProductMaster.id).where(ProductMaster.product_code == product_code)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product code already exists")
    values = payload.model_dump(exclude_unset=True)
    if values.get("status") and values["status"] not in MASTER_STATUS_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid product status")
    product = ProductMaster(
        product_code=product_code,
        product_name=product_name,
        spec=_clean_text(values.get("spec")),
        unit=_clean_text(values.get("unit")),
        category=_clean_text(values.get("category")),
        brand=_clean_text(values.get("brand")),
        barcode=_clean_text(values.get("barcode")),
        reference_sale_price=values.get("reference_sale_price"),
        reference_cost=values.get("reference_cost"),
        status=values.get("status") or "active",
        source="manual",
    )
    db.add(product)
    db.flush()
    write_audit_log(
        db,
        action_type="create_product",
        resource_type="product",
        resource_id=product.product_code,
        user=current_user,
        request=request,
        after_data=_product_audit_snapshot(product),
    )
    from app.services.master_link_service import rebuild_master_link_issues

    rebuild_master_link_issues(db)
    db.commit()
    db.refresh(product)
    return serialize_with_field_rules(db, current_user, "product", product)


@router.patch("/products/{product_code}", response_model=ProductMasterPublic)
def update_product(
    product_code: str,
    payload: ProductMasterUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("product.edit")),
) -> dict:
    stmt = select(ProductMaster).where(ProductMaster.product_code == product_code)
    stmt = apply_data_scope(stmt, ProductMaster, db, current_user, "product")
    product = db.scalar(stmt)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    changes = payload.model_dump(exclude_unset=True)
    if "product_name" in changes and not _clean_text(changes["product_name"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product name is required")
    if "status" in changes and changes["status"] not in MASTER_STATUS_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid product status")

    before_data = _product_audit_snapshot(product)
    changed = False
    for field, value in changes.items():
        if field not in PRODUCT_EDITABLE_FIELDS:
            continue
        next_value = _clean_text(value) if isinstance(value, str) else value
        if getattr(product, field) != next_value:
            setattr(product, field, next_value)
            changed = True
    if changed:
        product.source = product.source or "manual"
        write_audit_log(
            db,
            action_type="update_product",
            resource_type="product",
            resource_id=product.product_code,
            user=current_user,
            before_data=before_data,
            after_data=_product_audit_snapshot(product),
        )
    db.commit()
    db.refresh(product)
    return serialize_with_field_rules(db, current_user, "product", product)


@router.get("/suppliers", response_model=list[SupplierMasterPublic])
def list_suppliers(
    q: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier.view")),
) -> list[dict]:
    safe_limit = max(1, min(limit, 500))
    stmt = select(SupplierMaster).order_by(SupplierMaster.supplier_code)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((SupplierMaster.supplier_code.ilike(like)) | (SupplierMaster.supplier_name.ilike(like)))
    stmt = apply_data_scope(stmt, SupplierMaster, db, current_user, "supplier").limit(safe_limit)
    rows = list(db.scalars(stmt).all())
    return serialize_many_with_field_rules(db, current_user, "supplier", rows)


@router.get("/suppliers/page")
def list_suppliers_page(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(SupplierMaster).order_by(SupplierMaster.supplier_code)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((SupplierMaster.supplier_code.ilike(like)) | (SupplierMaster.supplier_name.ilike(like)))
    stmt = apply_data_scope(stmt, SupplierMaster, db, current_user, "supplier")
    total = _count_stmt(db, stmt)
    rows = list(db.scalars(stmt.offset(safe_offset).limit(safe_limit)).all())
    return _page_response(serialize_many_with_field_rules(db, current_user, "supplier", rows), total, safe_limit, safe_offset)


@router.get("/suppliers/{supplier_code}", response_model=SupplierMasterPublic)
def get_supplier(
    supplier_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier.view")),
) -> dict:
    stmt = select(SupplierMaster).where(SupplierMaster.supplier_code == supplier_code)
    stmt = apply_data_scope(stmt, SupplierMaster, db, current_user, "supplier")
    supplier = db.scalar(stmt)
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return serialize_with_field_rules(db, current_user, "supplier", supplier)


@router.post("/suppliers", response_model=SupplierMasterPublic, status_code=status.HTTP_201_CREATED)
def create_supplier(
    payload: SupplierMasterCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier.edit")),
) -> dict:
    supplier_code = _clean_text(payload.supplier_code)
    supplier_name = _clean_text(payload.supplier_name)
    if not supplier_code or not supplier_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier code and name are required")
    if db.scalar(select(SupplierMaster.id).where(SupplierMaster.supplier_code == supplier_code)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier code already exists")
    values = payload.model_dump(exclude_unset=True)
    if values.get("status") and values["status"] not in MASTER_STATUS_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid supplier status")
    if values.get("contact_phone") and len(str(values["contact_phone"]).strip()) > 80:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contact phone is too long")
    supplier = SupplierMaster(
        supplier_code=supplier_code,
        supplier_name=supplier_name,
        supplier_short_name=_clean_text(values.get("supplier_short_name")),
        supplier_type=_clean_text(values.get("supplier_type")),
        region=_clean_text(values.get("region")),
        contact_name=_clean_text(values.get("contact_name")),
        contact_phone=_clean_text(values.get("contact_phone")),
        address=_clean_text(values.get("address")),
        status=values.get("status") or "active",
        source="manual",
    )
    db.add(supplier)
    db.flush()
    write_audit_log(
        db,
        action_type="create_supplier",
        resource_type="supplier",
        resource_id=supplier.supplier_code,
        user=current_user,
        request=request,
        after_data=_supplier_audit_snapshot(supplier),
    )
    from app.services.master_link_service import rebuild_master_link_issues

    rebuild_master_link_issues(db)
    db.commit()
    db.refresh(supplier)
    return serialize_with_field_rules(db, current_user, "supplier", supplier)


@router.patch("/suppliers/{supplier_code}", response_model=SupplierMasterPublic)
def update_supplier(
    supplier_code: str,
    payload: SupplierMasterUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier.edit")),
) -> dict:
    stmt = select(SupplierMaster).where(SupplierMaster.supplier_code == supplier_code)
    stmt = apply_data_scope(stmt, SupplierMaster, db, current_user, "supplier")
    supplier = db.scalar(stmt)
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")

    changes = payload.model_dump(exclude_unset=True)
    if "supplier_name" in changes and not _clean_text(changes["supplier_name"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier name is required")
    if "status" in changes and changes["status"] not in MASTER_STATUS_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid supplier status")
    if "contact_phone" in changes and changes["contact_phone"] and len(str(changes["contact_phone"]).strip()) > 80:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contact phone is too long")

    before_data = _supplier_audit_snapshot(supplier)
    changed = False
    for field, value in changes.items():
        if field not in SUPPLIER_EDITABLE_FIELDS:
            continue
        next_value = _clean_text(value) if isinstance(value, str) else value
        if getattr(supplier, field) != next_value:
            setattr(supplier, field, next_value)
            changed = True
    if changed:
        supplier.source = supplier.source or "manual"
        write_audit_log(
            db,
            action_type="update_supplier",
            resource_type="supplier",
            resource_id=supplier.supplier_code,
            user=current_user,
            before_data=before_data,
            after_data=_supplier_audit_snapshot(supplier),
        )
    db.commit()
    db.refresh(supplier)
    return serialize_with_field_rules(db, current_user, "supplier", supplier)
