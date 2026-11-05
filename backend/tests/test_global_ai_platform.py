from __future__ import annotations

import inspect
from unittest.mock import Mock, patch

import pytest

from app.schemas.global_ai import (
    AiContextPayload,
    AiContextRequest,
    AiInvocationRequest,
    AiUsage,
    GlobalAiResult,
)
from app.services import global_ai_orchestrator as orchestrator_module
from app.services.ai_context_service import AiContextProvider
from app.services.ai_draft_service import AiDraftService
from app.services.ai_insight_service import AiInsightService
from app.services.global_ai_orchestrator import (
    AiExecution,
    AiProviderResult,
    GlobalAiOrchestrator,
    UnregisteredAiToolError,
)
from app.services.hermes_ai_service import (
    ExceptionDiagnosis,
    HermesCallMetadata,
    HermesStructuredDiagnosis,
    call_hermes_chat,
    call_hermes_exception_diagnosis,
)


def _invocation(result_type: str, *, domain: str = "crm", tools: list[str] | None = None) -> AiInvocationRequest:
    return AiInvocationRequest(
        request_id="global-ai-test-request",
        result_type=result_type,
        domain=domain,
        operation=f"{domain}.test",
        requested_tools=tools or [],
        prompt_version="test-prompt.v1",
        contract_version="global-ai-result.v1",
    )


def _provider_result(value: dict | str, *, summary: str = "完成") -> AiProviderResult:
    fields = value if isinstance(value, dict) else {"text": value}
    return AiProviderResult(
        value=value,
        summary=summary,
        structured_fields=fields,
        source_refs=("case:1",),
        model="glm-5.2",
        usage=AiUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        latency_ms=12,
        attempts=1,
    )


def test_orchestrator_returns_unified_contract_and_safe_audit(caplog: pytest.LogCaptureFixture) -> None:
    audits = []
    orchestrator = GlobalAiOrchestrator()
    with caplog.at_level("INFO", logger="app.ai.audit"):
        execution = orchestrator.invoke(
            _invocation("text"),
            lambda: _provider_result("CRM answer"),
            audit_sink=audits.append,
        )
    assert execution.value == "CRM answer"
    assert execution.result.result_type == "text"
    assert execution.result.structured_fields == {"text": "CRM answer"}
    assert execution.result.usage.total_tokens == 15
    assert audits[0].service_identity == "exception_ai_service"
    assert audits[0].status == "completed"
    assert "CRM answer" not in caplog.text
    assert "customer phone 13800138000" not in caplog.text
    assert "secret-provider-token" not in caplog.text


def test_unregistered_tool_is_rejected_before_provider_access() -> None:
    provider = Mock()
    with pytest.raises(UnregisteredAiToolError):
        GlobalAiOrchestrator().invoke(
            _invocation("text", tools=["database.execute"]),
            provider,
        )
    provider.assert_not_called()


def test_provider_failure_can_use_controlled_degraded_result() -> None:
    execution = GlobalAiOrchestrator().invoke(
        _invocation("text"),
        lambda: (_ for _ in ()).throw(TimeoutError("provider secret body")),
        fallback=lambda _exc: _provider_result("规则降级结果"),
    )
    assert execution.result.status == "degraded"
    assert execution.value == "规则降级结果"
    assert execution.result.warnings == ["AI Provider 不可用，已使用受控降级结果。"]


def test_orchestrator_has_no_database_or_credential_dependency() -> None:
    source = inspect.getsource(orchestrator_module)
    assert "sqlalchemy" not in source.casefold()
    assert "database_url" not in source.casefold()
    assert "api_key" not in source.casefold()


def test_context_provider_enforces_permission_allowlist_and_redaction() -> None:
    provider = AiContextProvider()
    adapter = Mock(
        return_value=AiContextPayload(
            context_version="crm-v1",
            fields={
                "summary": {"open_tasks": 3},
                "contact_phone": "13800138000",
                "notes": "token=super-secret-value",
                "unapproved": "must not leave the provider",
            },
            source_refs=["project:7", "project:7"],
        )
    )
    provider.register(
        "crm",
        adapter,
        allowed_fields={"summary", "contact_phone", "notes"},
        required_permissions={"crm_insight.view"},
    )
    denied = AiContextRequest(domain="crm", actor_user_id=1)
    with pytest.raises(PermissionError):
        provider.build(denied)
    adapter.assert_not_called()

    snapshot = provider.build(
        AiContextRequest(
            domain="crm",
            actor_user_id=1,
            permission_codes=["crm_insight.view"],
        )
    )
    assert snapshot.structured_fields["contact_phone"] == "[REDACTED]"
    assert snapshot.structured_fields["notes"] == "[REDACTED_SECRET]"
    assert snapshot.redacted_fields == ["unapproved"]
    assert snapshot.source_refs == ["project:7"]


def _context_provider() -> AiContextProvider:
    provider = AiContextProvider()
    provider.register(
        "crm",
        lambda _request: AiContextPayload(
            context_version="crm-v1",
            fields={"summary": {"open_tasks": 2}},
            source_refs=["project:7"],
        ),
        allowed_fields={"summary"},
        required_permissions={"crm_insight.view"},
    )
    return provider


def test_insight_and_draft_services_share_context_and_orchestrator() -> None:
    context_request = AiContextRequest(
        domain="crm",
        actor_user_id=1,
        permission_codes=["crm_insight.view"],
    )
    orchestrator = GlobalAiOrchestrator()
    insight = AiInsightService(_context_provider(), orchestrator).generate(
        context_request,
        _invocation("insight"),
        lambda fields, refs: _provider_result(
            {"risk": "overdue", "open_tasks": fields["summary"]["open_tasks"], "refs": refs}
        ),
    )
    draft = AiDraftService(_context_provider(), orchestrator).generate(
        context_request,
        _invocation("draft"),
        lambda fields, refs: _provider_result({"draft": f"{fields['summary']['open_tasks']} tasks", "refs": refs}),
    )
    assert insight.result.result_type == "insight"
    assert insight.value["refs"] == ["project:7"]
    assert draft.result.result_type == "draft"
    assert draft.value["refs"] == ["project:7"]


def _global_result(result_type: str, request_id: str) -> GlobalAiResult:
    return GlobalAiResult(
        result_type=result_type,
        structured_fields={},
        summary="统一结果",
        request_id=request_id,
        prompt_version="test.v1",
        contract_version="global-ai-result.v1",
        latency_ms=1,
    )


def test_crm_and_exception_calls_use_the_same_orchestrator() -> None:
    invocations = []

    def fake_invoke(invocation, _provider_call, **_kwargs):  # noqa: ANN001
        invocations.append(invocation)
        if invocation.result_type == "text":
            return AiExecution(value="CRM answer", result=_global_result("text", invocation.request_id))
        diagnosis = HermesStructuredDiagnosis(
            diagnosis=ExceptionDiagnosis(
                root_cause_code="known_cause",
                summary="需要人工复核。",
                confidence=0.8,
                evidence_refs=[],
                impact="影响待确认。",
                recommended_steps=["请人工检查证据。"],
                missing_evidence=["缺少关键证据。"],
                disposition="blocked",
            ),
            metadata=HermesCallMetadata(
                provider_host="provider.example",
                model="glm-5.2",
                request_id=invocation.request_id,
                started_at="2026-08-30T00:00:00Z",
                completed_at="2026-08-30T00:00:01Z",
                latency_ms=1,
                attempts=1,
            ),
        )
        return AiExecution(value=diagnosis, result=_global_result("diagnosis", invocation.request_id))

    with patch.object(orchestrator_module.global_ai_orchestrator, "invoke", side_effect=fake_invoke):
        assert call_hermes_chat([{"role": "user", "content": "question"}]) == "CRM answer"
        result = call_hermes_exception_diagnosis({}, domain="inventory")
    assert result.diagnosis.root_cause_code == "known_cause"
    assert [item.result_type for item in invocations] == ["text", "diagnosis"]
    assert {item.service_identity for item in invocations} == {"exception_ai_service"}
