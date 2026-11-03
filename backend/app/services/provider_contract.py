"""Metadata contracts extracted from the pinned ERP diagnosis provider."""
from datetime import datetime
from pydantic import BaseModel, Field
from app.services.evidence_contract import ExceptionDiagnosis

class HermesCallMetadata(BaseModel):
    provider_host: str | None
    model: str
    request_id: str
    provider_request_id: str | None = None
    started_at: datetime
    completed_at: datetime
    latency_ms: int = Field(ge=0)
    attempts: int = Field(ge=1)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    prompt_version: str = "exception-diagnosis-2026-08-30.v4"
    contract_version: str = "exception-diagnosis-json.zh-cn.v2"
    evidence_bytes: int = Field(default=0, ge=0)
    evidence_approx_tokens: int = Field(default=0, ge=0)
    evidence_truncated: bool = False


class HermesStructuredDiagnosis(BaseModel):
    diagnosis: ExceptionDiagnosis
    metadata: HermesCallMetadata
