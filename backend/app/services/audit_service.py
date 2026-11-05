from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def write_audit_log(
    db: Session,
    *,
    action_type: str,
    resource_type: str,
    resource_id: str | None = None,
    user: User | None = None,
    request: Request | None = None,
    before_data: dict | list | None = None,
    after_data: dict | list | None = None,
) -> AuditLog:
    log = AuditLog(
        user_id=user.id if user else None,
        role_code=user.role if user else None,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        before_data=before_data,
        after_data=after_data,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )
    db.add(log)
    return log
