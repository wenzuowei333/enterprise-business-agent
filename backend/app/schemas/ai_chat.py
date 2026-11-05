from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AiChatContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["current_filters", "selected_cases", "case"] = "current_filters"
    filters: dict[str, str | int | bool | None] = Field(default_factory=dict)
    case_nos: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("case_nos")
    @classmethod
    def normalize_case_nos(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("case_nos must not contain duplicates")
        return normalized


class AiChatStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_id: str = Field(min_length=8, max_length=120)
    conversation_no: str | None = Field(default=None, max_length=120)
    message: str = Field(min_length=1, max_length=4000)
    channel: Literal["exception_center_web"] = "exception_center_web"
    operation: str = Field(default="assistant.message", max_length=120)
    context: AiChatContextRequest = Field(default_factory=AiChatContextRequest)


class AiChatMessagePublic(BaseModel):
    message_no: str
    sequence_no: int
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    status: str
    request_id: str | None = None
    model_name: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    context_meta: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class AiChatConversationPublic(BaseModel):
    conversation_no: str
    channel: str
    status: str
    title: str
    model_name: str | None = None
    message_count: int = 0
    last_message: str = ""
    context_type: str | None = None
    context_id: str | None = None
    operation: str | None = None
    evidence_version: str | None = None
    created_at: datetime
    updated_at: datetime


class AiChatRunPublic(BaseModel):
    run_no: str
    conversation_no: str
    status: str
    request_id: str
    model_name: str | None = None
    provider_request_id: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class AiChatCancelResponse(BaseModel):
    run_no: str
    status: str
