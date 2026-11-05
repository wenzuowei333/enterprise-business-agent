from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import DataScopeRule, FieldPermissionRule, User

ALL_SCOPE = "all"
OWN_SCOPE = "own"
DEPARTMENT_SCOPE = "department"
ASSIGNED_SCOPE = "assigned"
CUSTOM_SCOPE = "custom"

HIDDEN_FIELD_VALUE = None
MASKED_FIELD_VALUE = "******"


def get_data_scope_rule(db: Session, user: User, resource_type: str) -> DataScopeRule | None:
    user_rule = db.scalar(
        select(DataScopeRule).where(
            DataScopeRule.subject_type == "user",
            DataScopeRule.subject_id == str(user.id),
            DataScopeRule.resource_type == resource_type,
            DataScopeRule.is_active.is_(True),
        )
    )
    if user_rule is not None:
        return user_rule
    return db.scalar(
        select(DataScopeRule).where(
            DataScopeRule.subject_type == "role",
            DataScopeRule.subject_id == user.role,
            DataScopeRule.resource_type == resource_type,
            DataScopeRule.is_active.is_(True),
        )
    )


def apply_data_scope(stmt: Select[tuple[Any, ...]], model: type[Any], db: Session, user: User, resource_type: str) -> Select[tuple[Any, ...]]:
    rule = get_data_scope_rule(db, user, resource_type)
    if rule is None or rule.scope_mode == ALL_SCOPE:
        return stmt

    if rule.scope_mode == OWN_SCOPE and resource_type == "customer":
        if not user.employee_code:
            return stmt.where(model.salesperson_employee_code.is_(None))
        return stmt.where(model.salesperson_employee_code == user.employee_code)

    if rule.scope_mode == ASSIGNED_SCOPE:
        assigned_values = _scope_values(rule.scope_value)
        if assigned_values and hasattr(model, "customer_code"):
            return stmt.where(model.customer_code.in_(assigned_values))
        if assigned_values and hasattr(model, "employee_code"):
            return stmt.where(model.employee_code.in_(assigned_values))
        return stmt.where(False)

    if rule.scope_mode == DEPARTMENT_SCOPE:
        scope_value = rule.scope_value if isinstance(rule.scope_value, dict) else {}
        values = scope_value.get("values") if isinstance(scope_value.get("values"), list) else None
        if values and hasattr(model, "department"):
            return stmt.where(model.department.in_(values))

    if rule.scope_mode == CUSTOM_SCOPE:
        scope_value = rule.scope_value if isinstance(rule.scope_value, dict) else {}
        if scope_value.get("mode") == "none":
            return stmt.where(False)

    return stmt


def get_field_permission_rules(db: Session, user: User, resource_type: str) -> list[FieldPermissionRule]:
    user_rules = list(
        db.scalars(
            select(FieldPermissionRule).where(
                FieldPermissionRule.subject_type == "user",
                FieldPermissionRule.subject_id == str(user.id),
                FieldPermissionRule.resource_type == resource_type,
            )
        ).all()
    )
    user_fields = {rule.field_name for rule in user_rules}
    role_rules = list(
        db.scalars(
            select(FieldPermissionRule).where(
                FieldPermissionRule.subject_type == "role",
                FieldPermissionRule.subject_id == user.role,
                FieldPermissionRule.resource_type == resource_type,
            )
        ).all()
    )
    return [rule for rule in role_rules if rule.field_name not in user_fields] + user_rules


def serialize_with_field_rules(db: Session, user: User, resource_type: str, row: Any) -> dict[str, Any]:
    data = _serialize_row(row)
    for rule in get_field_permission_rules(db, user, resource_type):
        if rule.field_name not in data:
            continue
        if rule.permission_type == "hidden":
            data[rule.field_name] = HIDDEN_FIELD_VALUE
        elif rule.permission_type == "masked":
            data[rule.field_name] = _mask_value(data[rule.field_name], rule.mask_rule)
    return data


def serialize_many_with_field_rules(db: Session, user: User, resource_type: str, rows: Sequence[Any]) -> list[dict[str, Any]]:
    return [serialize_with_field_rules(db, user, resource_type, row) for row in rows]


def _scope_values(scope_value: Any) -> list[str]:
    if isinstance(scope_value, list):
        return [str(value) for value in scope_value]
    if isinstance(scope_value, dict) and isinstance(scope_value.get("values"), list):
        return [str(value) for value in scope_value["values"]]
    return []


def _serialize_row(row: Any) -> dict[str, Any]:
    columns = getattr(row, "__table__").columns
    return {column.name: _jsonable(getattr(row, column.name)) for column in columns}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return value
    return value


def _mask_value(value: Any, mask_rule: str | None) -> Any:
    if value is None:
        return None
    text = str(value)
    if mask_rule == "phone":
        if len(text) >= 7:
            return f"{text[:3]}****{text[-4:]}"
        return MASKED_FIELD_VALUE
    if mask_rule == "money":
        return MASKED_FIELD_VALUE
    if mask_rule == "risk_only":
        return MASKED_FIELD_VALUE
    return MASKED_FIELD_VALUE
