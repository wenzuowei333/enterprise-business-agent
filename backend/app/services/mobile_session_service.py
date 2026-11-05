from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MobileSession, User


class MobileSessionError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def issue_mobile_session(
    db: Session,
    *,
    user: User,
    device_id: str,
    device_name: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    app_version: str | None = None,
    android_version: str | None = None,
    device_model: str | None = None,
) -> tuple[str, MobileSession]:
    normalized_device_id = device_id.strip()
    if not normalized_device_id:
        raise MobileSessionError("Device id is required")
    now = _now()
    existing = list(
        db.scalars(
            select(MobileSession).where(
                MobileSession.user_id == user.id,
                MobileSession.device_id == normalized_device_id,
                MobileSession.revoked_at.is_(None),
            )
        ).all()
    )
    for row in existing:
        row.revoked_at = now
    refresh_token = _new_refresh_token()
    session = MobileSession(
        user_id=user.id,
        device_id=normalized_device_id,
        device_name=(device_name or "").strip() or None,
        refresh_token_hash=_token_hash(refresh_token),
        expires_at=now + timedelta(days=settings.mobile_refresh_token_expire_days),
        last_used_at=now,
        ip_address=ip_address,
        user_agent=user_agent,
        app_version=(app_version or "").strip() or None,
        android_version=(android_version or "").strip() or None,
        device_model=(device_model or "").strip() or None,
    )
    db.add(session)
    db.flush()
    return refresh_token, session


def refresh_mobile_session(
    db: Session,
    *,
    refresh_token: str,
    device_id: str,
) -> tuple[str, MobileSession]:
    session = db.scalar(
        select(MobileSession).where(
            MobileSession.refresh_token_hash == _token_hash(refresh_token),
            MobileSession.device_id == device_id.strip(),
        )
    )
    now = _now()
    if session is None or session.revoked_at is not None or _as_utc(session.expires_at) <= now:
        raise MobileSessionError("Refresh token is invalid or expired")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active or user.status != "active":
        raise MobileSessionError("User is inactive")
    next_token = _new_refresh_token()
    session.refresh_token_hash = _token_hash(next_token)
    session.last_used_at = now
    session.expires_at = now + timedelta(days=settings.mobile_refresh_token_expire_days)
    db.flush()
    return next_token, session


def revoke_mobile_session(db: Session, *, refresh_token: str, device_id: str) -> MobileSession:
    session = db.scalar(
        select(MobileSession).where(
            MobileSession.refresh_token_hash == _token_hash(refresh_token),
            MobileSession.device_id == device_id.strip(),
        )
    )
    if session is None:
        raise MobileSessionError("Refresh token is invalid")
    if session.revoked_at is None:
        session.revoked_at = _now()
    db.flush()
    return session
