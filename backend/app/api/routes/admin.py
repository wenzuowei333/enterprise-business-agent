from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.models import (
    AuditLog,
    AuthorityRootRule,
    CustomerMaster,
    DataScopeRule,
    EmployeeProfile,
    FieldPermissionRule,
    ImportBatch,
    Permission,
    ProductMaster,
    Role,
    RolePermission,
    SupplierMaster,
    User,
)
from app.schemas.identity import (
    AuditLogPublic,
    AuthorityRootRulePublic,
    DataScopeRulePublic,
    FieldPermissionRulePublic,
    PermissionPublic,
    RoleCreate,
    RolePermissionsPublic,
    RolePermissionsUpdate,
    RolePublic,
)
from app.services.audit_service import write_audit_log
from app.services.role_template_service import RoleTemplateCreateError, create_role_template

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stage1/summary")
def stage1_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_any_permission(
            "authority.view",
            "audit.view",
            "user.view",
            "user.create",
            "user.edit",
            "user.permission_config",
            "dashboard.view",
            "employee.view",
            "customer.view",
            "product.view",
            "supplier.view",
            "import.view",
            "import.upload",
            "import.commit",
        )
    ),
) -> dict[str, int]:
    return {
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "employees": db.scalar(select(func.count()).select_from(EmployeeProfile)) or 0,
        "roles": db.scalar(select(func.count()).select_from(Role)) or 0,
        "permissions": db.scalar(select(func.count()).select_from(Permission)) or 0,
        "authority_root_rules": db.scalar(select(func.count()).select_from(AuthorityRootRule)) or 0,
        "audit_logs": db.scalar(select(func.count()).select_from(AuditLog)) or 0,
        "import_batches": db.scalar(select(func.count()).select_from(ImportBatch)) or 0,
        "customers": db.scalar(select(func.count()).select_from(CustomerMaster)) or 0,
        "products": db.scalar(select(func.count()).select_from(ProductMaster)) or 0,
        "suppliers": db.scalar(select(func.count()).select_from(SupplierMaster)) or 0,
    }


@router.get("/roles", response_model=list[RolePublic])
def list_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("authority.view", "user.view", "user.create", "user.edit", "user.permission_config")),
) -> list[Role]:
    return list(db.scalars(select(Role).order_by(Role.role_code)).all())


@router.post("/roles", response_model=RolePermissionsPublic, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("authority.edit")),
) -> RolePermissionsPublic:
    try:
        role = create_role_template(
            db,
            role_code=payload.role_code,
            role_name=payload.role_name,
            description=payload.description,
            permission_codes=payload.permission_codes,
        )
    except RoleTemplateCreateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    write_audit_log(
        db,
        action_type="create_role_template",
        resource_type="role",
        resource_id=role.role_code,
        user=current_user,
        request=request,
        after_data={
            "role_code": role.role_code,
            "role_name": role.role_name,
            "permission_codes": sorted(set(payload.permission_codes)),
        },
    )
    db.commit()
    return get_role_permissions(role.role_code, db, current_user)


@router.get("/permissions", response_model=list[PermissionPublic])
def list_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("authority.view", "user.permission_config")),
) -> list[Permission]:
    return list(db.scalars(select(Permission).order_by(Permission.resource_type, Permission.action_type)).all())


@router.get("/roles/{role_code}/permissions", response_model=RolePermissionsPublic)
def get_role_permissions(
    role_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("authority.view", "user.permission_config")),
) -> RolePermissionsPublic:
    role = db.scalar(select(Role).where(Role.role_code == role_code))
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    stmt = (
        select(Permission.permission_code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role.id)
        .order_by(Permission.permission_code)
    )
    return RolePermissionsPublic(role=RolePublic.model_validate(role), permission_codes=list(db.scalars(stmt).all()))


@router.put("/roles/{role_code}/permissions", response_model=RolePermissionsPublic)
def update_role_permissions(
    role_code: str,
    payload: RolePermissionsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("authority.edit")),
) -> RolePermissionsPublic:
    role = db.scalar(select(Role).where(Role.role_code == role_code))
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    requested_codes = sorted(set(payload.permission_codes))
    existing_permissions = list(db.scalars(select(Permission).where(Permission.permission_code.in_(requested_codes))).all())
    found_codes = {permission.permission_code for permission in existing_permissions}
    missing_codes = sorted(set(requested_codes) - found_codes)
    if missing_codes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown permissions: {', '.join(missing_codes)}")

    before_stmt = (
        select(Permission.permission_code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role.id)
        .order_by(Permission.permission_code)
    )
    before_codes = list(db.scalars(before_stmt).all())
    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete(synchronize_session=False)
    for permission in existing_permissions:
        db.add(RolePermission(role_id=role.id, permission_id=permission.id))

    write_audit_log(
        db,
        action_type="update_role_permissions",
        resource_type="role",
        resource_id=role.role_code,
        user=current_user,
        request=request,
        before_data={"permission_codes": before_codes},
        after_data={"permission_codes": requested_codes},
    )
    db.commit()
    return get_role_permissions(role_code, db, current_user)


@router.get("/authority-root-rules", response_model=list[AuthorityRootRulePublic])
def list_authority_root_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("authority.view", "user.permission_config")),
) -> list[AuthorityRootRule]:
    stmt = select(AuthorityRootRule).order_by(AuthorityRootRule.resource_type, AuthorityRootRule.action_type)
    return list(db.scalars(stmt).all())


@router.get("/data-scope-rules", response_model=list[DataScopeRulePublic])
def list_data_scope_rules(
    subject_type: str | None = None,
    subject_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("authority.view", "user.permission_config")),
) -> list[DataScopeRule]:
    stmt = select(DataScopeRule).order_by(DataScopeRule.subject_type, DataScopeRule.subject_id, DataScopeRule.resource_type)
    if subject_type:
        stmt = stmt.where(DataScopeRule.subject_type == subject_type)
    if subject_id:
        stmt = stmt.where(DataScopeRule.subject_id == subject_id)
    return list(db.scalars(stmt).all())


@router.get("/field-permission-rules", response_model=list[FieldPermissionRulePublic])
def list_field_permission_rules(
    subject_type: str | None = None,
    subject_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("authority.view", "user.permission_config")),
) -> list[FieldPermissionRule]:
    stmt = select(FieldPermissionRule).order_by(
        FieldPermissionRule.subject_type,
        FieldPermissionRule.subject_id,
        FieldPermissionRule.resource_type,
        FieldPermissionRule.field_name,
    )
    if subject_type:
        stmt = stmt.where(FieldPermissionRule.subject_type == subject_type)
    if subject_id:
        stmt = stmt.where(FieldPermissionRule.subject_id == subject_id)
    return list(db.scalars(stmt).all())


@router.get("/audit-logs", response_model=list[AuditLogPublic])
def list_audit_logs(
    limit: int = 100,
    resource_type: str | None = None,
    resource_id: str | None = None,
    user_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("audit.view")),
) -> list[AuditLog]:
    safe_limit = max(1, min(limit, 500))
    stmt = select(AuditLog)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    stmt = stmt.order_by(AuditLog.id.desc()).limit(safe_limit)
    return list(db.scalars(stmt).all())
