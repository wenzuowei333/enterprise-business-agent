from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Permission, Role, RolePermission, User, UserPermissionOverride

ALLOW = "allow"
DENY = "deny"
VALID_EFFECTS = {ALLOW, DENY}


def get_role_permission_codes(db: Session, role_code: str) -> list[str]:
    role = db.scalar(select(Role).where(Role.role_code == role_code))
    if role is None:
        return []
    stmt = (
        select(Permission.permission_code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role.id)
        .order_by(Permission.permission_code)
    )
    return list(db.scalars(stmt).all())


def get_user_override_codes(db: Session, user_id: int) -> tuple[list[str], list[str]]:
    stmt = (
        select(Permission.permission_code, UserPermissionOverride.effect)
        .join(UserPermissionOverride, UserPermissionOverride.permission_id == Permission.id)
        .where(UserPermissionOverride.user_id == user_id)
        .order_by(Permission.permission_code)
    )
    allow_codes: list[str] = []
    deny_codes: list[str] = []
    for permission_code, effect in db.execute(stmt).all():
        if effect == ALLOW:
            allow_codes.append(permission_code)
        elif effect == DENY:
            deny_codes.append(permission_code)
    return allow_codes, deny_codes


def get_final_permission_codes(db: Session, user: User) -> list[str]:
    role_codes = set(get_role_permission_codes(db, user.role))
    allow_codes, deny_codes = get_user_override_codes(db, user.id)
    return sorted((role_codes | set(allow_codes)) - set(deny_codes))


def has_permission(db: Session, user: User, permission_code: str) -> bool:
    return permission_code in set(get_final_permission_codes(db, user))
