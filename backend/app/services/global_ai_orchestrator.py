from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from app.schemas.global_ai import AiCallAuditRecord, AiInvocationRequest, AiUsage, GlobalAiResult

T = TypeVar("T")
logger = logging.getLogger("app.ai.audit")


class UnregisteredAiToolError(PermissionError):
    """Raised before provider access when a request names an unregistered tool."""


@dataclass(frozen=True)
class AiProviderResult(Generic[T]):
    value: T
    summary: str
    structured_fields: dict[str, Any]
    source_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    model: str | None = None
    usage: AiUsage = field(default_factory=AiUsage)
    provider_request_id: str | None = None
    latency_ms: int | None = None
    attempts: int = 1


@dataclass(frozen=True)
class AiExecution(Generic[T]):
    value: T
    result: GlobalAiResult


AiAuditSink = Callable[[AiCallAuditRecord], None]
AiProviderCall = Callable[[], AiProviderResult[T]]
AiFallbackCall = Callable[[Exception], AiProviderResult[T]]


def _error_code(exc: Exception) -> str:
    name = type(exc).__name__
    normalized = "".join(f"_{char.lower()}" if char.isupper() else char for char in name).lstrip("_")
    return normalized[:120] or "ai_provider_error"


class GlobalAiOrchestrator:
    """Provider-neutral orchestration without database, credentials or business writes."""

    def __init__(self, *, registered_tools: Iterable[str] = ()) -> None:
        self._registered_tools = frozenset(item.strip() for item in registered_tools if item.strip())

    @property
    def registered_tools(self) -> frozenset[str]:
        return self._registered_tools

    def invoke(
        self,
        request: AiInvocationRequest,
        provider_call: AiProviderCall[T],
        *,
        fallback: AiFallbackCall[T] | None = None,
        audit_sink: AiAuditSink | None = None,
    ) -> AiExecution[T]:
        unknown_tools = sorted(set(request.requested_tools) - self._registered_tools)
        if unknown_tools:
            record = AiCallAuditRecord(
                request_id=request.request_id,
                service_identity=request.service_identity,
                domain=request.domain,
                operation=request.operation,
                result_type=request.result_type,
                status="rejected",
                requested_tools=request.requested_tools,
                prompt_version=request.prompt_version,
                contract_version=request.contract_version,
                latency_ms=0,
                error_code="unregistered_ai_tool",
            )
            self._emit_audit(record, audit_sink)
            raise UnregisteredAiToolError(f"Unregistered AI tools: {', '.join(unknown_tools)}")

        started = time.monotonic()
        status = "completed"
        provider_error: Exception | None = None
        try:
            provider_result = provider_call()
        except Exception as exc:
            provider_error = exc
            if fallback is None:
                record = self._audit_record(
                    request,
                    status="failed",
                    latency_ms=max(0, int((time.monotonic() - started) * 1000)),
                    error_code=_error_code(exc),
                )
                self._emit_audit(record, audit_sink)
                raise
            provider_result = fallback(exc)
            status = "degraded"

        latency_ms = provider_result.latency_ms
        if latency_ms is None:
            latency_ms = max(0, int((time.monotonic() - started) * 1000))
        warnings = list(provider_result.warnings)
        if provider_error is not None:
            warnings.append("AI Provider 不可用，已使用受控降级结果。")
        result = GlobalAiResult(
            result_type=request.result_type,
            structured_fields=provider_result.structured_fields,
            summary=provider_result.summary,
            warnings=warnings,
            source_refs=list(provider_result.source_refs),
            model=provider_result.model,
            usage=provider_result.usage,
            request_id=request.request_id,
            provider_request_id=provider_result.provider_request_id,
            prompt_version=request.prompt_version,
            contract_version=request.contract_version,
            status=status,
            latency_ms=latency_ms,
            attempts=provider_result.attempts,
        )
        record = self._audit_record(
            request,
            status=status,
            latency_ms=latency_ms,
            model=result.model,
            usage=result.usage,
            attempts=result.attempts,
            error_code=_error_code(provider_error) if provider_error else None,
        )
        self._emit_audit(record, audit_sink)
        return AiExecution(value=provider_result.value, result=result)

    @staticmethod
    def _audit_record(
        request: AiInvocationRequest,
        *,
        status: str,
        latency_ms: int,
        model: str | None = None,
        usage: AiUsage | None = None,
        attempts: int = 1,
        error_code: str | None = None,
    ) -> AiCallAuditRecord:
        return AiCallAuditRecord(
            request_id=request.request_id,
            service_identity=request.service_identity,
            domain=request.domain,
            operation=request.operation,
            result_type=request.result_type,
            status=status,
            model=model,
            usage=usage or AiUsage(),
            requested_tools=request.requested_tools,
            prompt_version=request.prompt_version,
            contract_version=request.contract_version,
            latency_ms=latency_ms,
            attempts=attempts,
            error_code=error_code,
        )

    @staticmethod
    def _emit_audit(record: AiCallAuditRecord, audit_sink: AiAuditSink | None) -> None:
        # This event intentionally excludes prompts, context fields, responses and credentials.
        logger.info("global_ai_call %s", json.dumps(record.model_dump(mode="json"), ensure_ascii=True, sort_keys=True))
        if audit_sink is not None:
            try:
                audit_sink(record)
            except Exception:
                logger.error("global_ai_audit_sink_failed request_id=%s", record.request_id)


global_ai_orchestrator = GlobalAiOrchestrator()
