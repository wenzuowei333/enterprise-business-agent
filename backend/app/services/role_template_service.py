import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Permission, Role, RolePermission


ROLE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,79}$")


class RoleTemplateCreateError(ValueError):
    pass


def create_role_template(
    db: Session,
    *,
    role_code: str,
    role_name: str,
    description: str | None = None,
    permission_codes: list[str] | None = None,
) -> Role:
    code = role_code.strip().lower()
    name = role_name.strip()
    normalized_description = description.strip() if description else None

    if not ROLE_CODE_PATTERN.match(code):
        raise RoleTemplateCreateError("角色模板编码只能使用小写字母、数字和下划线，并以字母开头。")
    if not name:
        raise RoleTemplateCreateError("角色模板名称不能为空。")
    if db.scalar(select(Role).where(Role.role_code == code)) is not None:
        raise RoleTemplateCreateError("角色模板编码已存在。")

    requested_codes = sorted(set(permission_codes or []))
    existing_permissions: list[Permission] = []
    if requested_codes:
        existing_permissions = list(
            db.scalars(select(Permission).where(Permission.permission_code.in_(requested_codes))).all()
        )
        found_codes = {permission.permission_code for permission in existing_permissions}
        missing_codes = sorted(set(requested_codes) - found_codes)
        if missing_codes:
            raise RoleTemplateCreateError(f"未知权限：{', '.join(missing_codes)}")

    role = Role(
        role_code=code,
        role_name=name,
        description=normalized_description,
        is_system_role=False,
    )
    db.add(role)
    db.flush()

    for permission in existing_permissions:
        db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.flush()
    return role
