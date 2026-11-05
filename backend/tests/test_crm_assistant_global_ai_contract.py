from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.crm_assistant import router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import AuditLog, Permission, Role, RolePermission, User
from app.schemas.global_ai import AiUsage, GlobalAiResult
from app.services.hermes_ai_service import HermesUnavailableError


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


def _result(request_id: str) -> GlobalAiResult:
    return GlobalAiResult(
        result_type="text",
        structured_fields={"text": "统一 AI 响应"},
        summary="统一 AI 响应",
        source_refs=["project:7"],
        model="glm-5.2",
        usage=AiUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20),
        request_id=request_id,
        prompt_version="crm-assistant-legacy.v1",
        contract_version="global-ai-result.v1",
        latency_ms=18,
        attempts=1,
    )


class TestCrmAssistantGlobalAiContract:
    def setup_method(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        role = Role(role_code="admin", role_name="Admin")
        user = User(
            username="global-ai-admin",
            password_hash="hash",
            real_name="Global AI Admin",
            role="admin",
            status="active",
            is_active=True,
        )
        permissions = [
            Permission(
                permission_code="crm_insight.view",
                permission_name="View CRM insight",
                resource_type="crm_insight",
                action_type="view",
            ),
            Permission(
                permission_code="crm_insight.generate",
                permission_name="Generate CRM insight",
                resource_type="crm_insight",
                action_type="generate",
            ),
        ]
        self.db.add_all([role, user, *permissions])
        self.db.flush()
        self.db.add_all(
            [RolePermission(role_id=role.id, permission_id=permission.id) for permission in permissions]
        )
        self.db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(user.username)}"}

    def teardown_method(self) -> None:
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def test_success_persists_unified_contract_and_safe_audit_metadata(self) -> None:
        def fake_chat(_messages, **kwargs):  # noqa: ANN001
            result = _result(kwargs["request_id"])
            kwargs["on_result"](result)
            return result.summary

        with (
            patch("app.api.routes.crm_assistant.hermes_configured", return_value=True),
            patch("app.api.routes.crm_assistant.call_hermes_chat", side_effect=fake_chat),
        ):
            response = self.client.post(
                "/api/v1/crm/assistant/messages",
                headers=self.headers,
                json={"message": "请给出今日摘要", "operation": "dashboard.summary"},
            )
        assert response.status_code == 200, response.text
        message = response.json()["message"]
        contract = message["payload_json"]["global_ai_result"]
        assert contract["result_type"] == "text"
        assert contract["contract_version"] == "global-ai-result.v1"
        assert contract["usage"]["total_tokens"] == 20
        audit = self.db.scalar(select(AuditLog).where(AuditLog.action_type == "crm_assistant_message"))
        assert audit is not None
        assert audit.after_data["ai_request_id"] == contract["request_id"]
        assert audit.after_data["ai_usage"]["total_tokens"] == 20
        assert "请给出今日摘要" not in str(audit.after_data)

    def test_provider_failure_keeps_rule_fallback_and_audits_degraded_status(self) -> None:
        with (
            patch("app.api.routes.crm_assistant.hermes_configured", return_value=True),
            patch(
                "app.api.routes.crm_assistant.call_hermes_chat",
                side_effect=HermesUnavailableError("Hermes request failed: network error"),
            ),
        ):
            response = self.client.post(
                "/api/v1/crm/assistant/messages",
                headers=self.headers,
                json={"message": "查看风险", "operation": "dashboard.summary"},
            )
        assert response.status_code == 200, response.text
        message = response.json()["message"]
        assert message["source"] == "rule_fallback"
        assert message["status"] == "completed_with_warning"
        assert message["payload_json"]["global_ai_result"] is None
        audit = self.db.scalar(select(AuditLog).where(AuditLog.action_type == "crm_assistant_message"))
        assert audit is not None
        assert audit.after_data["ai_status"] == "degraded"
        assert audit.after_data["ai_request_id"].startswith("crm-ai-")

    def test_project_draft_uses_the_same_contract(self) -> None:
        def fake_chat(_messages, **kwargs):  # noqa: ANN001
            result = _result(kwargs["request_id"])
            kwargs["on_result"](result)
            return result.summary

        with (
            patch("app.api.routes.crm_assistant.hermes_configured", return_value=True),
            patch("app.api.routes.crm_assistant.call_hermes_chat", side_effect=fake_chat),
        ):
            response = self.client.post(
                "/api/v1/crm/assistant/project-draft",
                headers=self.headers,
                json={"project_name": "测试项目", "customer_name": "测试客户"},
            )
        assert response.status_code == 200, response.text
        contract = response.json()["message"]["payload_json"]["global_ai_result"]
        assert contract["contract_version"] == "global-ai-result.v1"
        audit = self.db.scalar(
            select(AuditLog).where(AuditLog.action_type == "crm_assistant_project_draft")
        )
        assert audit is not None
        assert audit.after_data["ai_request_id"] == contract["request_id"]
