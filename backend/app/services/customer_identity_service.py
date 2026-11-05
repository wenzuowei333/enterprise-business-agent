from __future__ import annotations

import hashlib
import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CustomerMaster


_NAME_SEPARATORS = re.compile(r"[^\w]+", re.UNICODE)
_PHONE_SEPARATORS = re.compile(r"\D+")


def normalize_customer_name(name: str | None) -> str:
    return _NAME_SEPARATORS.sub("", (name or "").casefold())


def normalize_customer_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    normalized = _PHONE_SEPARATORS.sub("", phone)
    if normalized.startswith("86") and len(normalized) == 13 and normalized[2] == "1":
        normalized = normalized[2:]
    return normalized or None


def customer_identity_lock_keys(*, customer_name: str | None, contact_phone: str | None) -> list[tuple[str, int]]:
    """Build deterministic PostgreSQL transaction-lock keys for exact customer identities."""
    normalized_name = normalize_customer_name(customer_name)
    normalized_phone = normalize_customer_phone(contact_phone)
    key_names: list[str] = []
    if normalized_name:
        key_names.append(f"customer_master:name:{normalized_name}")
    if normalized_phone:
        key_names.append(f"customer_master:phone:{normalized_phone}")
    return [
        (
            key_name,
            int.from_bytes(hashlib.sha256(key_name.encode("utf-8")).digest()[:8], byteorder="big", signed=True),
        )
        for key_name in sorted(set(key_names))
    ]


def acquire_customer_identity_locks(db: Session, *, customer_name: str | None, contact_phone: str | None) -> None:
    """Serialize exact identity checks on PostgreSQL; SQLite remains a compatible no-op."""
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    for _key_name, lock_key in customer_identity_lock_keys(customer_name=customer_name, contact_phone=contact_phone):
        db.execute(select(func.pg_advisory_xact_lock(lock_key)))


def find_customer_identity_matches(
    db: Session,
    *,
    customer_name: str | None,
    contact_phone: str | None,
    exclude_customer_code: str | None = None,
) -> list[dict[str, Any]]:
    """Return exact normalized name/phone matches without assuming a clean legacy data set."""
    normalized_name = normalize_customer_name(customer_name)
    normalized_phone = normalize_customer_phone(contact_phone)
    if not normalized_name and not normalized_phone:
        return []

    matches: list[dict[str, Any]] = []
    for customer in db.scalars(select(CustomerMaster)).all():
        if customer.customer_code == exclude_customer_code:
            continue
        reasons: list[str] = []
        if normalized_name and normalize_customer_name(customer.customer_name) == normalized_name:
            reasons.append("exact_normalized_name")
        if normalized_phone and normalize_customer_phone(customer.contact_phone) == normalized_phone:
            reasons.append("exact_phone")
        if reasons:
            matches.append({"customer": customer, "reasons": reasons})
    return matches


def assert_customer_identity_available(
    db: Session,
    *,
    customer_name: str | None,
    contact_phone: str | None,
    exclude_customer_code: str | None = None,
    conflict_message: str = "Blocking customer master duplicate",
) -> None:
    """Lock and reject an exact normalized identity collision, excluding the current record when updating."""
    acquire_customer_identity_locks(db, customer_name=customer_name, contact_phone=contact_phone)
    matches = find_customer_identity_matches(
        db,
        customer_name=customer_name,
        contact_phone=contact_phone,
        exclude_customer_code=exclude_customer_code,
    )
    if matches:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": conflict_message,
                "blocking_duplicate_count": len(matches),
                "blocking_reasons": sorted({reason for match in matches for reason in match["reasons"]}),
            },
        )
