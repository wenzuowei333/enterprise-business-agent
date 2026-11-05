from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    real_name: str
    employee_code: str | None
    role: str
    is_active: bool
    status: str = "active"
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    avatar_url: str | None = None
    avatar_object_key: str | None = None
    avatar_updated_at: datetime | None = None
    disabled_reason: str | None = None
    cancelled_reason: str | None = None
    cancelled_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=6, max_length=128)
    real_name: str = Field(min_length=1, max_length=120)
    employee_code: str | None = Field(default=None, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    status: str = "active"


class UserUpdate(BaseModel):
    real_name: str | None = Field(default=None, min_length=1, max_length=120)
    employee_code: str | None = Field(default=None, max_length=80)
    role: str | None = Field(default=None, min_length=1, max_length=80)


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class UserStatusChangeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class UserStatusHistoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    old_status: str | None
    new_status: str
    reason: str | None
    changed_by: int | None
    changed_at: datetime


class EmployeeProfileCreate(BaseModel):
    employee_code: str
    employee_name: str
    user_id: int | None = None
    department: str | None = None
    position: str | None = None
    role_code: str | None = None
    manager_employee_code: str | None = None
    status: str = "active"
    phone: str | None = None


class EmployeeProfileUpdate(BaseModel):
    employee_name: str | None = None
    user_id: int | None = None
    department: str | None = None
    position: str | None = None
    role_code: str | None = None
    manager_employee_code: str | None = None
    status: str | None = None
    phone: str | None = None


class EmployeeProfilePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_code: str
    employee_name: str
    user_id: int | None
    department: str | None
    position: str | None
    role_code: str | None
    manager_employee_code: str | None
    status: str
    phone: str | None
    created_at: datetime
    updated_at: datetime


class RolePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role_code: str
    role_name: str
    description: str | None
    is_system_role: bool


class PermissionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    permission_code: str
    permission_name: str
    resource_type: str
    action_type: str
    description: str | None


class RolePermissionsPublic(BaseModel):
    role: RolePublic
    permission_codes: list[str]


class RoleCreate(BaseModel):
    role_code: str = Field(min_length=2, max_length=80)
    role_name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    permission_codes: list[str] = Field(default_factory=list)


class RolePermissionsUpdate(BaseModel):
    permission_codes: list[str]


class UserPermissionOverrideItem(BaseModel):
    permission_code: str
    effect: str


class UserPermissionsPublic(BaseModel):
    user: UserPublic
    role_permission_codes: list[str]
    allow_permission_codes: list[str]
    deny_permission_codes: list[str]
    final_permission_codes: list[str]


class UserPermissionsUpdate(BaseModel):
    overrides: list[UserPermissionOverrideItem]


class AuthorityRootRulePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_code: str
    rule_name: str
    resource_type: str
    action_type: str
    allowed_roles: list[str]
    allowed_scope: dict | None
    requires_approval: bool
    approver_role: str | None
    is_active: bool
    description: str | None


class DataScopeRulePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_type: str
    subject_id: str
    resource_type: str
    scope_mode: str
    scope_value: dict[str, Any] | list[Any] | None
    is_active: bool


class FieldPermissionRulePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_type: str
    subject_id: str
    resource_type: str
    field_name: str
    permission_type: str
    mask_rule: str | None


class AuditLogPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    role_code: str | None
    action_type: str
    resource_type: str
    resource_id: str | None
    ip_address: str | None
    created_at: datetime
