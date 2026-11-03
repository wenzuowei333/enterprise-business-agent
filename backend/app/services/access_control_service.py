"""New minimal showcase adapter over the retained identity/permission tables."""
from fastapi import HTTPException
from sqlalchemy import select, false, or_
from app import models as m


def permission_codes(db, user):
    if not user or not user.is_active or user.status != "active":
        return set()
    result=set(db.scalars(select(m.Permission.permission_code)
        .join(m.RolePermission,m.RolePermission.permission_id==m.Permission.id)
        .join(m.Role,m.Role.id==m.RolePermission.role_id).where(m.Role.role_code==user.role)))
    overrides=db.execute(select(m.Permission.permission_code,m.UserPermissionOverride.effect)
        .join(m.UserPermissionOverride,m.UserPermissionOverride.permission_id==m.Permission.id)
        .where(m.UserPermissionOverride.user_id==user.id)).all()
    for code,effect in overrides:
        if effect=='allow': result.add(code)
        else: result.discard(code)  # unknown effects fail closed
    return result


def require_permission(db,user,code):
    if code not in permission_codes(db,user):
        raise HTTPException(403,detail={"code":"permission_denied","message":"当前账号无此操作权限"})


def scoped_cases(db,user):
    stmt=select(m.ExceptionCase).join(m.InventoryAnomalyCase,m.InventoryAnomalyCase.id==m.ExceptionCase.inventory_anomaly_case_id)
    stmt=stmt.join(m.InventorySnapshot,m.InventorySnapshot.id==m.InventoryAnomalyCase.snapshot_id)
    stmt=stmt.where(m.ExceptionCase.domain=='inventory')
    if 'exception.view' not in permission_codes(db,user):
        return stmt.where(false())
    common=[m.DataScopeRule.resource_type=='exception_case',m.DataScopeRule.is_active.is_(True)]
    rules=db.scalars(select(m.DataScopeRule).where(*common,m.DataScopeRule.subject_type=='user',m.DataScopeRule.subject_id==str(user.id))).all()
    if not rules:
        rules=db.scalars(select(m.DataScopeRule).where(*common,m.DataScopeRule.subject_type=='role',m.DataScopeRule.subject_id==user.role)).all()
    if not rules or any(r.scope_mode not in {'all','warehouse'} for r in rules):
        return stmt.where(false())
    if any(r.scope_mode=='all' for r in rules):
        return stmt
    warehouses=set()
    for rule in rules:
        if isinstance(rule.scope_value,dict):
            values=rule.scope_value.get('warehouse_names',[])
            if isinstance(values,list): warehouses.update(v for v in values if isinstance(v,str))
    # Authoritative snapshot warehouse, not a client field or stale case metadata.
    return stmt.where(m.InventorySnapshot.warehouse_name.in_(warehouses)) if warehouses else stmt.where(false())


def visible_case(db,user,case_id):
    require_permission(db,user,'exception.view')
    case=db.scalar(scoped_cases(db,user).where(m.ExceptionCase.id==case_id).execution_options(populate_existing=True))
    if case is None:
        raise HTTPException(404,detail={"code":"case_not_found","message":"案件不存在或不可见"})
    return case


def requester_may_diagnose(db,job):
    user=db.get(m.User,job.requested_by_user_id) if job.requested_by_user_id else None
    return bool(user and 'exception.diagnose' in permission_codes(db,user)
                and db.scalar(scoped_cases(db,user).where(m.ExceptionCase.id==job.case_id)))
