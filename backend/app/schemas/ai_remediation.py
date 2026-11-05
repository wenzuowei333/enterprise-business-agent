from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_SECRET_REQUEST_RE = re.compile(
    r"(?:密码|口令|密钥|私钥|token|api[ _-]?key|password|secret)",
    re.IGNORECASE,
)


class RemediationFieldOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=120)


class RemediationFormField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str = Field(min_length=1, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    field_type: Literal[
        "short_text",
        "long_text",
        "number",
        "date",
        "datetime",
        "boolean",
        "single_select",
        "multi_select",
        "business_reference",
        "file",
    ]
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    required: bool = False
    options: list[RemediationFieldOption] = Field(default_factory=list, max_length=20)
    reference_type: Literal["import_batch", "product", "customer", "warehouse"] | None = None
    min_value: float | None = None
    max_value: float | None = None
    max_length: int | None = Field(default=None, ge=1, le=2000)

    @model_validator(mode="after")
    def validate_shape(self) -> "RemediationFormField":
        if _SECRET_REQUEST_RE.search(f"{self.label} {self.description}"):
            raise ValueError("表单不得要求用户提供密码、Token 或密钥")
        if self.field_type in {"single_select", "multi_select"} and not self.options:
            raise ValueError("选择字段必须提供选项")
        if self.field_type not in {"single_select", "multi_select"} and self.options:
            raise ValueError("非选择字段不能提供选项")
        if self.field_type == "business_reference" and self.reference_type is None:
            raise ValueError("业务引用字段必须指定 reference_type")
        if self.field_type != "business_reference" and self.reference_type is not None:
            raise ValueError("只有业务引用字段可以指定 reference_type")
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError("数值范围无效")
        return self


class RemediationFormSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["remediation-form.v1"] = "remediation-form.v1"
    title: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=1000)
    fields: list[RemediationFormField] = Field(default_factory=list, max_length=12)
    missing_evidence: list[str] = Field(default_factory=list, max_length=20)
    generation_notes: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("fields")
    @classmethod
    def unique_field_ids(cls, value: list[RemediationFormField]) -> list[RemediationFormField]:
        ids = [item.field_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("field_id 不得重复")
        return value

    @field_validator("missing_evidence", "generation_notes")
    @classmethod
    def bounded_text_list(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if any(len(item) > 500 or _SECRET_REQUEST_RE.search(item) for item in normalized):
            raise ValueError("补充信息说明包含不安全或过长内容")
        return normalized


class RemediationActionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: Literal[
        "rebuild_inventory_flow",
        "rerun_inventory_check",
        "rebuild_receivable_checks",
        "rebuild_master_link_issues",
        "revalidate_import_batch",
    ] | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(default="", max_length=1000)

    @field_validator("parameters", mode="before")
    @classmethod
    def validate_parameters(cls, value: Any) -> dict[str, Any]:
        # Model-proposed parameters are untrusted. Keep only the one value the
        # deterministic action validator understands; it will still re-check
        # the batch against the latest case evidence before execution.
        if not isinstance(value, dict):
            return {}
        batch_id = value.get("batch_id")
        if isinstance(batch_id, int) and not isinstance(batch_id, bool) and batch_id > 0:
            return {"batch_id": batch_id}
        return {}


class RemediationSandboxCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Literal["sql", "shell", "http"]
    purpose: str = Field(min_length=1, max_length=1000)
    code: str = Field(min_length=1, max_length=10000)


class RemediationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["remediation-plan.v1"] = "remediation-plan.v1"
    summary: str = Field(min_length=1, max_length=2000)
    confirmed_facts: list[str] = Field(default_factory=list, max_length=30)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    steps: list[str] = Field(default_factory=list, min_length=1, max_length=20)
    expected_impact: str = Field(min_length=1, max_length=2000)
    verification_steps: list[str] = Field(default_factory=list, min_length=1, max_length=20)
    rollback: str = Field(min_length=1, max_length=2000)
    risks: list[str] = Field(default_factory=list, max_length=20)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    action_candidate: RemediationActionCandidate = Field(default_factory=RemediationActionCandidate)
    sandbox_candidate: RemediationSandboxCandidate | None = None

    @field_validator("confirmed_facts", "assumptions", "steps", "verification_steps", "risks", "missing_information")
    @classmethod
    def validate_lists(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if any(len(item) > 2000 for item in normalized):
            raise ValueError("方案条目过长")
        return normalized


class RemediationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_message_no: str = Field(min_length=8, max_length=120)
    client_request_id: str = Field(min_length=8, max_length=120)


class RemediationAnswersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_lock_version: int = Field(ge=1)
    answers: dict[str, Any]


class RemediationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_lock_version: int = Field(ge=1)
    client_request_id: str = Field(min_length=8, max_length=120)


class RemediationConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_lock_version: int = Field(ge=1)
    confirmation: Literal[True]
    idempotency_key: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class RemediationAttachmentPublic(BaseModel):
    attachment_no: str
    original_name: str
    content_type: str
    size_bytes: int
    sha256: str
    scan_status: str
    parse_status: str
    error_code: str | None = None
    created_at: datetime


class RemediationWorkflowPublic(BaseModel):
    workflow_no: str
    case_no: str
    source_message_no: str
    evidence_version: str
    status: str
    lock_version: int
    form_schema: RemediationFormSchema | None = None
    answers: dict[str, Any] = Field(default_factory=dict)
    plan: RemediationPlan | None = None
    sandbox: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    attachments: list[RemediationAttachmentPublic] = Field(default_factory=list)
    can_execute: bool = False
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class RemediationCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_lock_version: int = Field(ge=1)
