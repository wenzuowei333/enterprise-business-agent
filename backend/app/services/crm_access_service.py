from typing import Any

from sqlalchemy import Select, false, or_
from sqlalchemy.orm import Session

from app.models import CrmFollowup, CrmLead, CrmProject, CrmProjectCustomerTask, DataScopeRule, User, WorkItem
from app.services.access_control_service import ALL_SCOPE, ASSIGNED_SCOPE, CUSTOM_SCOPE, OWN_SCOPE, get_data_scope_rule
from app.services.permission_service import get_final_permission_codes

CRM_PERMISSION_RESOURCES = {
    "crm_project",
    "crm_task",
    "crm_followup",
    "crm_issue",
    "approval",
    "crm_insight",
    "crm_image",
    "crm_business_profile",
    "crm_customer_profile",
    "crm_lead",
    "crm_lead_campaign",
    "crm_lead_policy",
}

CRM_AUDIT_RESOURCE_TYPES = {
    "crm_project",
    "crm_project_task",
    "crm_followup",
    "approval_instance",
    "approval_event",
    "approval_attachment",
    "crm_image",
    "crm_business_profile",
    "crm_customer_profile",
    "crm_lead",
    "crm_lead_followup",
    "crm_lead_assignment_event",
    "crm_lead_product_intent",
    "crm_lead_campaign",
    "crm_lead_operation_policy",
    "image_processing_job",
    "work_item",
}


def is_crm_permission_code(permission_code: str) -> bool:
    return permission_code.split(".", 1)[0] in CRM_PERMISSION_RESOURCES


def get_crm_permission_codes(db: Session, user: User) -> list[str]:
    return [code for code in get_final_permission_codes(db, user) if is_crm_permission_code(code)]


def crm_project_scope_filter(stmt: Select[tuple[Any, ...]], db: Session, user: User) -> Select[tuple[Any, ...]]:
    rule = get_data_scope_rule(db, user, "crm_project")
    if _is_all_scope(rule):
        return stmt
    if rule and rule.scope_mode in {OWN_SCOPE, ASSIGNED_SCOPE}:
        return stmt.where(
            or_(
                CrmProject.owner_user_id == user.id,
                CrmProject.project_manager_user_id == user.id,
                CrmProject.applicant_user_id == user.id,
                CrmProject.landing_approver_user_id == user.id,
                CrmProject.created_by_user_id == user.id,
                CrmProject.participant_user_ids.contains([user.id]),
                CrmProject.progress_cc_user_ids.contains([user.id]),
            )
        )
    if rule and rule.scope_mode == CUSTOM_SCOPE:
        return _custom_scope_filter(stmt, rule, CrmProject)
    return stmt.where(false())


def crm_task_scope_filter(stmt: Select[tuple[Any, ...]], db: Session, user: User) -> Select[tuple[Any, ...]]:
    rule = get_data_scope_rule(db, user, "crm_task")
    if _is_all_scope(rule):
        return stmt
    if rule and rule.scope_mode == OWN_SCOPE:
        filters = [CrmProjectCustomerTask.executor_user_id == user.id]
        if user.employee_code:
            filters.append(CrmProjectCustomerTask.executor_employee_code == user.employee_code)
        return stmt.where(or_(*filters))
    if rule and rule.scope_mode == ASSIGNED_SCOPE:
        return stmt.where(CrmProjectCustomerTask.executor_user_id == user.id)
    if rule and rule.scope_mode == CUSTOM_SCOPE:
        return _custom_scope_filter(stmt, rule, CrmProjectCustomerTask)
    return stmt.where(false())


def crm_followup_scope_filter(stmt: Select[tuple[Any, ...]], db: Session, user: User) -> Select[tuple[Any, ...]]:
    rule = get_data_scope_rule(db, user, "crm_followup")
    if _is_all_scope(rule):
        return stmt
    if rule and rule.scope_mode in {OWN_SCOPE, ASSIGNED_SCOPE}:
        return stmt.where(CrmFollowup.executor_user_id == user.id)
    if rule and rule.scope_mode == CUSTOM_SCOPE:
        return _custom_scope_filter(stmt, rule, CrmFollowup)
    return stmt.where(false())


def crm_lead_scope_filter(stmt: Select[tuple[Any, ...]], db: Session, user: User) -> Select[tuple[Any, ...]]:
    rule = get_data_scope_rule(db, user, "crm_lead")
    if _is_all_scope(rule):
        return stmt
    if rule and rule.scope_mode == OWN_SCOPE:
        return stmt.where(
            or_(
                CrmLead.owner_user_id == user.id,
                CrmLead.assigned_user_id == user.id,
                CrmLead.created_by_user_id == user.id,
            )
        )
    if rule and rule.scope_mode == ASSIGNED_SCOPE:
        return stmt.where(CrmLead.assigned_user_id == user.id)
    if rule and rule.scope_mode == CUSTOM_SCOPE:
        return _crm_lead_custom_scope_filter(stmt, rule)
    return stmt.where(false())


def crm_work_item_scope_filter(stmt: Select[tuple[Any, ...]], db: Session, user: User) -> Select[tuple[Any, ...]]:
    rule = get_data_scope_rule(db, user, "crm_issue")
    if _is_all_scope(rule):
        return stmt
    if rule and rule.scope_mode in {OWN_SCOPE, ASSIGNED_SCOPE}:
        return stmt.where(WorkItem.assignee_user_id == user.id)
    if rule and rule.scope_mode == CUSTOM_SCOPE:
        return _custom_scope_filter(stmt, rule, WorkItem)
    return stmt.where(false())


def _is_all_scope(rule: DataScopeRule | None) -> bool:
    return rule is None or rule.scope_mode == ALL_SCOPE


def _crm_lead_custom_scope_filter(stmt: Select[tuple[Any, ...]], rule: DataScopeRule) -> Select[tuple[Any, ...]]:
    value = rule.scope_value if isinstance(rule.scope_value, dict) else {}
    if value.get("mode") == "none":
        return stmt.where(false())

    filters = []
    lead_ids = _positive_int_scope_values(value.get("lead_ids"))
    if lead_ids:
        filters.append(CrmLead.id.in_(lead_ids))
    owner_user_ids = _positive_int_scope_values(value.get("owner_user_ids"))
    if owner_user_ids:
        filters.append(CrmLead.owner_user_id.in_(owner_user_ids))
    return stmt.where(or_(*filters)) if filters else stmt.where(false())


def _positive_int_scope_values(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    ids = []
    for raw_value in value:
        try:
            value_id = int(raw_value)
        except (TypeError, ValueError):
            continue
        if value_id > 0 and value_id not in ids:
            ids.append(value_id)
    return ids


def _custom_scope_filter(stmt: Select[tuple[Any, ...]], rule: DataScopeRule, model: type[Any]) -> Select[tuple[Any, ...]]:
    value = rule.scope_value if isinstance(rule.scope_value, dict) else {}
    if value.get("mode") == "none":
        return stmt.where(false())
    customer_codes = value.get("customer_codes")
    if isinstance(customer_codes, list) and customer_codes and hasattr(model, "customer_code"):
        return stmt.where(model.customer_code.in_([str(code) for code in customer_codes]))
    project_ids = value.get("project_ids")
    if isinstance(project_ids, list) and project_ids and hasattr(model, "project_id"):
        return stmt.where(model.project_id.in_([int(project_id) for project_id in project_ids]))
    return stmt.where(false())
