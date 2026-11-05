from __future__ import annotations

from collections.abc import Callable

from app.schemas.global_ai import AiContextRequest, AiInvocationRequest
from app.services.ai_context_service import AiContextProvider
from app.services.global_ai_orchestrator import (
    AiAuditSink,
    AiExecution,
    AiProviderResult,
    GlobalAiOrchestrator,
)

AiInsightGenerator = Callable[[dict, list[str]], AiProviderResult[dict]]


class AiInsightService:
    def __init__(self, context_provider: AiContextProvider, orchestrator: GlobalAiOrchestrator) -> None:
        self._context_provider = context_provider
        self._orchestrator = orchestrator

    def generate(
        self,
        context_request: AiContextRequest,
        invocation: AiInvocationRequest,
        generator: AiInsightGenerator,
        *,
        audit_sink: AiAuditSink | None = None,
    ) -> AiExecution[dict]:
        if invocation.result_type != "insight" or invocation.domain != context_request.domain:
            raise ValueError("Insight invocation must match the requested context domain")
        snapshot = self._context_provider.build(context_request)
        return self._orchestrator.invoke(
            invocation,
            lambda: generator(snapshot.structured_fields, snapshot.source_refs),
            audit_sink=audit_sink,
        )
