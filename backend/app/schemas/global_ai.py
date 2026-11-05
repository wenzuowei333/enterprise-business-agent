from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AiUsage(BaseModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class AiInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=8, max_length=160)
    result_type: Literal["text", "diagnosis", "insight", "draft"]
    domain: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    operation: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,119}$")
    service_identity: Literal["exception_ai_service"] = "exception_ai_service"
    actor_user_id: int | None = Field(default=None, ge=1)
    requested_tools: list[str] = Field(default_factory=list, max_length=20)
    prompt_version: str = Field(min_length=1, max_length=120)
    contract_version: str = Field(min_length=1, max_length=120)
    max_retries: int = Field(default=0, ge=0, le=5)

    @field_validator("requested_tools")
    @classmethod
    def normalize_requested_tools(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("requested_tools must not contain duplicates")
        if any(not re.fullmatch(r"[a-z][a-z0-9_.]{0,119}", item) for item in normalized):
            raise ValueError("requested_tools contains an invalid tool name")
        return normalized


class GlobalAiResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_type: Literal["text", "diagnosis", "insight", "draft"]
    structured_fields: dict[str, Any] = Field(default_factory=dict)
    summary: str
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    model: str | None = None
    usage: AiUsage = Field(default_factory=AiUsage)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str
    provider_request_id: str | None = None
    prompt_version: str
    contract_version: str
    status: Literal["completed", "degraded"] = "completed"
    latency_ms: int = Field(ge=0)
    attempts: int = Field(default=1, ge=1)


class AiCallAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    service_identity: Literal["exception_ai_service"]
    domain: str
    operation: str
    result_type: str
    status: Literal["completed", "degraded", "failed", "rejected"]
    model: str | None = None
    usage: AiUsage = Field(default_factory=AiUsage)
    requested_tools: list[str] = Field(default_factory=list)
    prompt_version: str
    contract_version: str
    latency_ms: int = Field(ge=0)
    attempts: int = Field(default=1, ge=1)
    error_code: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AiContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    actor_user_id: int = Field(ge=1)
    permission_codes: list[str] = Field(default_factory=list, max_length=200)
    scope_revision: str | None = Field(default=None, max_length=160)
    resource_type: str | None = Field(default=None, max_length=120)
    resource_id: str | None = Field(default=None, max_length=160)


class AiContextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_version: str = Field(min_length=1, max_length=160)
    fields: dict[str, Any]
    source_refs: list[str] = Field(default_factory=list, max_length=200)


class AiContextSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    context_version: str
    structured_fields: dict[str, Any]
    source_refs: list[str] = Field(default_factory=list)
    redacted_fields: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ControlledActionCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: str
    domain: str
    label: str
    risk_level: Literal["low", "medium", "high"]
    required_permissions: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    available: bool
    blockers: list[str] = Field(default_factory=list)


class ControlledActionProposalPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    proposal_no: str
    domain: str
    action_type: str
    resource_type: str | None = None
    resource_id: str | None = None
    status: str
    review_status: str
    risk_level: str | None = None
    requires_confirmation: bool
    parameters: dict[str, Any] = Field(default_factory=dict)
    impact: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list)
    executable: bool
    blockers: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None


class ControlledActionProposalPage(BaseModel):
    items: list[ControlledActionProposalPublic]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)


class ControlledExceptionActionValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: Literal[
        "rebuild_inventory_flow",
        "rerun_inventory_check",
        "rebuild_receivable_checks",
        "rebuild_master_link_issues",
        "revalidate_import_batch",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        if set(value) - {"batch_id"}:
            raise ValueError("Only batch_id is supported")
        batch_id = value.get("batch_id")
        if batch_id is not None and (
            isinstance(batch_id, bool) or not isinstance(batch_id, int) or batch_id <= 0
        ):
            raise ValueError("batch_id must be a positive integer")
        return value


class ControlledActionValidationResponse(BaseModel):
    proposal: ControlledActionProposalPublic
    validation_token: str | None = None
    validation_expires_at: datetime | None = None


class ControlledActionExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime
    confirmation: Literal[True]
    idempotency_key: str = Field(
        min_length=8,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    validation_token: str | None = Field(
        default=None,
        min_length=20,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class ControlledCrmActionReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime
    confirmation: Literal[True]
    decision: Literal["accept", "reject", "task"]
    idempotency_key: str = Field(
        min_length=8,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ControlledActionExecutionPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_no: str
    proposal_no: str
    status: str
    idempotency_key: str
    attempts: int = Field(ge=0)
    executor_identity: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ControlledActionExecutionPage(BaseModel):
    items: list[ControlledActionExecutionPublic]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
