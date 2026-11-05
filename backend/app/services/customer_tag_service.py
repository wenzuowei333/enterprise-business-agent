from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CustomerMaster, CustomerTag, User
from app.services.audit_service import write_audit_log


CUSTOMER_TAG_COLOR_KEYS = ("blue", "green", "cyan", "yellow", "red", "purple", "pink", "gray")
MAX_CUSTOMER_TAGS = 20
MAX_CUSTOMER_TAG_NAME_LENGTH = 30


def clean_tag_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", normalized).strip()


def normalized_tag_name(value: Any) -> str:
    return clean_tag_name(value).casefold()


def default_tag_color(value: str) -> str:
    digest = hashlib.sha256(normalized_tag_name(value).encode("utf-8")).digest()
    return CUSTOMER_TAG_COLOR_KEYS[digest[0] % len(CUSTOMER_TAG_COLOR_KEYS)]


def _validated_names(value: list | None) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    keys: set[str] = set()
    for item in value:
        name = clean_tag_name(item)
        if not name:
            continue
        if len(name) > MAX_CUSTOMER_TAG_NAME_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Customer tag must not exceed {MAX_CUSTOMER_TAG_NAME_LENGTH} characters",
            )
        key = normalized_tag_name(name)
        if key in keys:
            continue
        keys.add(key)
        names.append(name)
    if len(names) > MAX_CUSTOMER_TAGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A customer can have at most {MAX_CUSTOMER_TAGS} tags",
        )
    return names


def canonicalize_customer_tags(
    db: Session,
    value: list | None,
    *,
    created_by_user_id: int | None = None,
) -> list[str]:
    names = _validated_names(value)
    if not names:
        return []
    keys = [normalized_tag_name(name) for name in names]
    rows = list(db.scalars(select(CustomerTag).where(CustomerTag.normalized_name.in_(keys))).all())
    by_key = {row.normalized_name: row for row in rows}
    result: list[str] = []
    for name, key in zip(names, keys, strict=True):
        row = by_key.get(key)
        if row is None:
            try:
                with db.begin_nested():
                    row = CustomerTag(
                        name=name,
                        normalized_name=key,
                        color_key=default_tag_color(name),
                        is_active=True,
                        created_by_user_id=created_by_user_id,
                    )
                    db.add(row)
                    db.flush()
            except IntegrityError:
                row = db.scalar(select(CustomerTag).where(CustomerTag.normalized_name == key))
            if row is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer tag already exists")
            by_key[key] = row
        if not row.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Customer tag is disabled: {row.name}")
        result.append(row.name)
    return result


def customer_tag_usage_counts(db: Session) -> Counter[str]:
    counts: Counter[str] = Counter()
    for tags in db.scalars(select(CustomerMaster.customer_tags)).all():
        if not isinstance(tags, list):
            continue
        seen: set[str] = set()
        for value in tags:
            key = normalized_tag_name(value)
            if key and key not in seen:
                counts[key] += 1
                seen.add(key)
    return counts


def create_customer_tag(
    db: Session,
    *,
    name: str,
    color_key: str,
    operator: User,
    request: Request | None = None,
) -> CustomerTag:
    cleaned = clean_tag_name(name)
    if not cleaned or len(cleaned) > MAX_CUSTOMER_TAG_NAME_LENGTH:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer tag name must contain 1 to 30 characters")
    key = normalized_tag_name(cleaned)
    if db.scalar(select(CustomerTag.id).where(CustomerTag.normalized_name == key)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer tag already exists")
    row = CustomerTag(
        name=cleaned,
        normalized_name=key,
        color_key=color_key,
        is_active=True,
        created_by_user_id=operator.id,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer tag already exists") from exc
    write_audit_log(
        db,
        action_type="customer_tag_create",
        resource_type="customer_tag",
        resource_id=str(row.id),
        user=operator,
        request=request,
        after_data={"name": row.name, "color_key": row.color_key, "is_active": row.is_active},
    )
    return row


def update_customer_tag(
    db: Session,
    *,
    row: CustomerTag,
    changes: dict[str, Any],
    operator: User,
    request: Request | None = None,
) -> tuple[CustomerTag, int]:
    before = {"name": row.name, "color_key": row.color_key, "is_active": row.is_active}
    next_name = row.name
    next_key = row.normalized_name
    if "name" in changes:
        next_name = clean_tag_name(changes["name"])
        if not next_name or len(next_name) > MAX_CUSTOMER_TAG_NAME_LENGTH:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer tag name must contain 1 to 30 characters")
        next_key = normalized_tag_name(next_name)
        duplicate = db.scalar(select(CustomerTag.id).where(CustomerTag.normalized_name == next_key, CustomerTag.id != row.id))
        if duplicate is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer tag already exists")

    next_active = bool(changes.get("is_active")) if "is_active" in changes else row.is_active
    affected = 0
    customer_changes: list[tuple[CustomerMaster, list[str], list[str]]] = []
    if next_name != row.name or (row.is_active and not next_active):
        old_key = row.normalized_name
        for customer in db.scalars(select(CustomerMaster)).all():
            current = list(customer.customer_tags) if isinstance(customer.customer_tags, list) else []
            updated: list[str] = []
            changed = False
            for value in current:
                if normalized_tag_name(value) != old_key:
                    updated.append(str(value))
                elif not next_active:
                    changed = True
                else:
                    updated.append(next_name)
                    changed = changed or str(value) != next_name
            if changed:
                affected += 1
                customer_changes.append((customer, current, updated))

    row.name = next_name
    row.normalized_name = next_key
    if "color_key" in changes:
        row.color_key = changes["color_key"]
    row.is_active = next_active
    for customer, old_tags, new_tags in customer_changes:
        customer.customer_tags = new_tags
        write_audit_log(
            db,
            action_type="customer_tag_assignment_sync",
            resource_type="customer",
            resource_id=customer.customer_code,
            user=operator,
            request=request,
            before_data={"customer_tags": old_tags},
            after_data={"customer_tags": new_tags, "customer_tag_id": row.id},
        )
    after = {
        "name": row.name,
        "color_key": row.color_key,
        "is_active": row.is_active,
        "affected_customer_count": affected,
    }
    if before != {key: after[key] for key in before}:
        write_audit_log(
            db,
            action_type="customer_tag_update",
            resource_type="customer_tag",
            resource_id=str(row.id),
            user=operator,
            request=request,
            before_data=before,
            after_data=after,
        )
    return row, affected
