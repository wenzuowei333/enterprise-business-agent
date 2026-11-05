from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, String, and_, cast, false, or_, select, union
from sqlalchemy.orm import Session

from app.models import ApprovalInstance, CrmLead, DataScopeRule, User
from app.services.access_control_service import (
    ALL_SCOPE,
    ASSIGNED_SCOPE,
    CUSTOM_SCOPE,
    OWN_SCOPE,
    get_data_scope_rule,
)
from app.services.crm_access_service import crm_lead_scope_filter
from app.services.permission_service import has_permission

LEAD_CONVERSION_APPROVAL_TYPE = "crm_lead_convert"


def _is_all_scope(rule: DataScopeRule | None) -> bool:
    return rule is None or rule.scope_mode == ALL_SCOPE


def approval_scope_filter(
    stmt: Select[tuple[ApprovalInstance]],
    db: Session,
    user: User,
) -> Select[tuple[ApprovalInstance]]:
    rule = get_data_scope_rule(db, user, "approval")
    if _is_all_scope(rule):
        return stmt
    if rule and rule.scope_mode in {OWN_SCOPE, ASSIGNED_SCOPE}:
        return stmt.where(
            or_(
                ApprovalInstance.applicant_user_id == user.id,
                ApprovalInstance.current_handler_user_id == user.id,
            )
        )
    if rule and rule.scope_mode == CUSTOM_SCOPE:
        value = rule.scope_value if isinstance(rule.scope_value, dict) else {}
        if value.get("mode") == "none":
            return stmt.where(false())
        approval_types = value.get("approval_types")
        if isinstance(approval_types, list) and approval_types:
            return stmt.where(ApprovalInstance.approval_type.in_([str(item) for item in approval_types]))
    return stmt.where(false())


def lead_conversion_visibility_clause(db: Session, current_user: User) -> Any:
    lead_conditions = [ApprovalInstance.approval_type != LEAD_CONVERSION_APPROVAL_TYPE]
    if has_permission(db, current_user, "crm_lead.view"):
        visible_lead_ids = crm_lead_scope_filter(select(cast(CrmLead.id, String)), db, current_user)
        lead_conditions.append(
            and_(
                ApprovalInstance.approval_type == LEAD_CONVERSION_APPROVAL_TYPE,
                ApprovalInstance.resource_id.in_(visible_lead_ids),
            )
        )
    if has_permission(db, current_user, "crm_lead.approve"):
        lead_conditions.append(
            and_(
                ApprovalInstance.approval_type == LEAD_CONVERSION_APPROVAL_TYPE,
                ApprovalInstance.current_handler_user_id == current_user.id,
            )
        )
    return or_(*lead_conditions)


def visible_approval_ids_stmt(db: Session, current_user: User) -> Select[tuple[int]]:
    visible_id_stmts = [
        select(ApprovalInstance.id).where(
            ApprovalInstance.approval_type != LEAD_CONVERSION_APPROVAL_TYPE,
            or_(
                ApprovalInstance.applicant_user_id == current_user.id,
                ApprovalInstance.current_handler_user_id == current_user.id,
            ),
        ),
        approval_scope_filter(select(ApprovalInstance.id), db, current_user).where(
            lead_conversion_visibility_clause(db, current_user)
        )
        if has_permission(db, current_user, "approval.view")
        else select(ApprovalInstance.id).where(false())
    ]
    if has_permission(db, current_user, "approval.approve"):
        visible_id_stmts.append(
            select(ApprovalInstance.id).where(
                ApprovalInstance.approval_type != LEAD_CONVERSION_APPROVAL_TYPE,
                ApprovalInstance.current_handler_user_id == current_user.id,
            )
        )
    if has_permission(db, current_user, "crm_lead.approve"):
        visible_id_stmts.append(
            select(ApprovalInstance.id).where(
                ApprovalInstance.approval_type == LEAD_CONVERSION_APPROVAL_TYPE,
                ApprovalInstance.current_handler_user_id == current_user.id,
            )
        )
    if has_permission(db, current_user, "crm_lead.view"):
        visible_lead_ids = crm_lead_scope_filter(select(cast(CrmLead.id, String)), db, current_user)
        visible_id_stmts.append(
            select(ApprovalInstance.id).where(
                ApprovalInstance.approval_type == LEAD_CONVERSION_APPROVAL_TYPE,
                ApprovalInstance.resource_id.in_(visible_lead_ids),
            )
        )
    if has_permission(db, current_user, "customer_tag.review"):
        visible_id_stmts.append(
            select(ApprovalInstance.id).where(
                ApprovalInstance.approval_type == "customer_tag_change",
                ApprovalInstance.current_handler_user_id == current_user.id,
            )
        )
    visible_ids = union(*visible_id_stmts).subquery()
    return select(visible_ids.c.id)


def visible_approval_resource_ids_stmt(db: Session, current_user: User) -> Select[tuple[str]]:
    ids = visible_approval_ids_stmt(db, current_user).subquery()
    return select(cast(ids.c.id, String))


def visible_approvals_stmt(db: Session, current_user: User) -> Select[tuple[ApprovalInstance]]:
    return select(ApprovalInstance).where(ApprovalInstance.id.in_(visible_approval_ids_stmt(db, current_user)))


def visible_approval_or_404(db: Session, current_user: User, approval_id: int) -> ApprovalInstance:
    approval = db.scalar(visible_approvals_stmt(db, current_user).where(ApprovalInstance.id == approval_id))
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return approval
