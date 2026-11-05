from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MasterCategoryBinding, MasterCategoryNode

MASTER_CATEGORY_KINDS = {"customers", "products", "customer_groups"}
MASTER_CATEGORY_RESOURCE_TYPES = {
    "customers": "customer",
    "products": "product",
    "customer_groups": "customer_group",
}


def normalize_category_kind(kind: str) -> str:
    normalized = (kind or "").strip()
    if normalized not in MASTER_CATEGORY_KINDS:
        raise ValueError(f"Invalid master category kind: {kind}")
    return normalized


def category_resource_type(kind: str) -> str:
    return MASTER_CATEGORY_RESOURCE_TYPES[normalize_category_kind(kind)]


def split_category_path(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_segments = [str(item) for item in value]
    else:
        normalized = str(value)
        for separator in ["\\", ">", "＞", ",", "，"]:
            normalized = normalized.replace(separator, "/")
        raw_segments = normalized.split("/")
    cleaned: list[str] = []
    seen: set[str] = set()
    for segment in raw_segments:
        text = str(segment).strip()
        if not text or text in seen:
            continue
        cleaned.append(text[:160])
        seen.add(text)
    return cleaned


def generate_category_node_code(kind: str) -> str:
    return f"CAT-{normalize_category_kind(kind).upper()}-{uuid4().hex[:12]}"


def ensure_category_path(
    db: Session,
    *,
    kind: str,
    path: list[str] | str | None,
    created_by_user_id: int | None = None,
    source_remark: str | None = None,
) -> MasterCategoryNode | None:
    normalized_kind = normalize_category_kind(kind)
    segments = split_category_path(path)
    if not segments:
        return None
    parent_id: int | None = None
    current: MasterCategoryNode | None = None
    for index, label in enumerate(segments):
        stmt = select(MasterCategoryNode).where(
            MasterCategoryNode.kind == normalized_kind,
            MasterCategoryNode.parent_id.is_(None) if parent_id is None else MasterCategoryNode.parent_id == parent_id,
            MasterCategoryNode.label == label,
        )
        node = db.scalar(stmt)
        if node is None:
            node = MasterCategoryNode(
                node_code=generate_category_node_code(normalized_kind),
                kind=normalized_kind,
                label=label,
                parent_id=parent_id,
                sort_order=index,
                is_enabled=True,
                remark=source_remark,
                created_by_user_id=created_by_user_id,
                updated_by_user_id=created_by_user_id,
            )
            db.add(node)
            db.flush()
        elif not node.is_enabled:
            node.is_enabled = True
            node.updated_by_user_id = created_by_user_id
        parent_id = node.id
        current = node
    return current


def bind_resource_to_category(
    db: Session,
    *,
    category: MasterCategoryNode,
    resource_code: str,
    is_primary: bool = True,
    source: str = "manual",
    created_by_user_id: int | None = None,
) -> MasterCategoryBinding:
    resource_type = category_resource_type(category.kind)
    normalized_code = str(resource_code or "").strip()
    if not normalized_code:
        raise ValueError("resource_code is required")
    if is_primary:
        for row in db.scalars(
            select(MasterCategoryBinding).where(
                MasterCategoryBinding.resource_type == resource_type,
                MasterCategoryBinding.resource_code == normalized_code,
                MasterCategoryBinding.is_primary.is_(True),
            )
        ).all():
            if row.category_id != category.id:
                db.delete(row)
    binding = db.scalar(
        select(MasterCategoryBinding).where(
            MasterCategoryBinding.category_id == category.id,
            MasterCategoryBinding.resource_type == resource_type,
            MasterCategoryBinding.resource_code == normalized_code,
        )
    )
    if binding is None:
        binding = MasterCategoryBinding(
            category_id=category.id,
            resource_type=resource_type,
            resource_code=normalized_code,
            is_primary=is_primary,
            source=source,
            created_by_user_id=created_by_user_id,
        )
        db.add(binding)
    else:
        binding.is_primary = is_primary
        binding.source = source
    return binding


def ensure_category_binding(
    db: Session,
    *,
    kind: str,
    path: list[str] | str | None,
    resource_code: str,
    is_primary: bool = True,
    source: str = "manual",
    user_id: int | None = None,
) -> MasterCategoryBinding | None:
    category = ensure_category_path(db, kind=kind, path=path, created_by_user_id=user_id, source_remark=source)
    if category is None:
        return None
    return bind_resource_to_category(
        db,
        category=category,
        resource_code=resource_code,
        is_primary=is_primary,
        source=source,
        created_by_user_id=user_id,
    )
