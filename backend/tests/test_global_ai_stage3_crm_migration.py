from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.crm_assistant import router
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import (
    AiActionExecution,
    AiActionProposal,
    AiContextSnapshotRecord,
    AiConversation,
    AiInsight,
    AiMessage,
    AiSecurityEvent,
    AiUsageEvent,
    AssistantConversation,
    CrmProjectInsight,
    Permission,
    Role,
    RolePermission,
    User,
    WorkItem,
)
from app.schemas.global_ai import AiContextSnapshot, AiUsage, GlobalAiResult
from app.services.crm_ai_migration_service import build_crm_context_snapshot, mirror_insight


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


def _result(request_id: str) -> GlobalAiResult:
    return GlobalAiResult(
        result_type="text",
        structured_fields={"text": "统一 AI 中文响应"},
        summary="统一 AI 中文响应",
        source_refs=["crm_project:7"],
        model="glm-5.2",
        usage=AiUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20),
        request_id=request_id,
        provider_request_id="provider-stage3",
        prompt_version="crm-assistant-legacy.v1",
        contract_version="global-ai-result.v1",
        latency_ms=18,
        attempts=1,
    )


class TestGlobalAiStageThreeCrmMigration:
    def setup_method(self) -> None:
        self.previous_flags = (
            settings.exception_ai_global_enabled,
            settings.exception_ai_crm_enabled,
            settings.exception_ai_data_enabled,
            settings.exception_ai_finance_enabled,
        )
        settings.exception_ai_global_enabled = True
        settings.exception_ai_crm_enabled = True
        settings.exception_ai_data_enabled = False
        settings.exception_ai_finance_enabled = False
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        role = Role(role_code="admin", role_name="Admin")
        user = User(
            username="crm-stage3-admin",
            password_hash="hash",
            real_name="CRM Stage 3 Admin",
            role="admin",
            status="active",
            is_active=True,
        )
        permission_codes = (
            "crm_insight.view",
            "crm_insight.generate",
            "crm_insight.review",
            "crm_task.view",
        )
        permissions = [
            Permission(
                permission_code=code,
                permission_name=code,
                resource_type=code.split(".")[0],
                action_type=code.split(".")[1],
            )
            for code in permission_codes
        ]
        self.db.add_all([role, user, *permissions])
        self.db.flush()
        self.db.add_all(
            [RolePermission(role_id=role.id, permission_id=permission.id) for permission in permissions]
        )
        self.db.commit()
        self.user = user
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
        (
            settings.exception_ai_global_enabled,
            settings.exception_ai_crm_enabled,
            settings.exception_ai_data_enabled,
            settings.exception_ai_finance_enabled,
        ) = self.previous_flags

    def _post_message(self) -> dict:
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
                json={"message": "请给出今日风险", "operation": "dashboard.summary"},
            )
        assert response.status_code == 200, response.text
        return response.json()["message"]

    def test_message_dual_write_unified_read_cancel_and_clear(self) -> None:
        message = self._post_message()
        assert self.db.scalar(select(func.count()).select_from(AssistantConversation)) == 1
        assert self.db.scalar(select(func.count()).select_from(AiConversation)) == 1
        assert self.db.scalar(select(func.count()).select_from(AiMessage)) == 2
        assert self.db.scalar(select(func.count()).select_from(AiContextSnapshotRecord)) == 1
        assert self.db.scalar(select(AiContextSnapshotRecord.domain)) == "global_business"
        assert self.db.scalar(select(func.count()).select_from(AiUsageEvent)) == 1
        assert self.db.scalar(select(func.count()).select_from(AiSecurityEvent)) == 1

        messages = self.client.get("/api/v1/crm/assistant/messages", headers=self.headers)
        assert messages.status_code == 200, messages.text
        assert messages.json()[0]["id"] == message["id"]
        assert messages.json()[0]["user_message"] == "请给出今日风险"
        assert messages.json()[0]["assistant_message"] == "统一 AI 中文响应"

        status = self.client.get("/api/v1/crm/assistant/agents", headers=self.headers)
        assert status.status_code == 200, status.text
        assert status.json()["runtime"]["source"] == "exception_center_global_ai"
        assert status.json()["migration_status"]["consistent"] is True
        assert status.json()["migration_status"]["read_source"] == "unified"

        cancelled = self.client.post(
            f"/api/v1/crm/assistant/messages/{message['id']}/cancel",
            headers=self.headers,
            json={"reason": "人工取消"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert self.db.scalar(select(AiConversation.status)) == "cancelled"
        assert set(self.db.scalars(select(AiMessage.status)).all()) == {"cancelled"}

        cleared = self.client.delete("/api/v1/crm/assistant/messages", headers=self.headers)
        assert cleared.status_code == 200, cleared.text
        assert cleared.json() == {"deleted": 1}
        assert self.db.scalar(select(func.count()).select_from(AssistantConversation)) == 0
        assert self.db.scalar(select(func.count()).select_from(AiConversation)) == 0
        assert self.db.scalar(select(func.count()).select_from(AiMessage)) == 0
        assert self.db.scalar(select(func.count()).select_from(AiContextSnapshotRecord)) == 0
        assert self.db.scalar(select(func.count()).select_from(AiUsageEvent)) == 1
        assert self.db.scalar(select(func.count()).select_from(AiSecurityEvent)) == 3

    def test_global_business_context_reaches_provider_without_hidden_content(self) -> None:
        captured_messages: list[dict[str, str]] = []
        snapshot = AiContextSnapshot(
            domain="global_business",
            context_version="global-business-context.v1",
            structured_fields={
                "crm": {"summary": {"active_projects": 2}},
                "sales": {"rows": 3, "amount_tax_total": "120.00"},
                "availability": {
                    "sales": {"available": True, "reason": None},
                    "finance": {
                        "available": False,
                        "reason": "missing_permission:account_ledger.view",
                    },
                },
            },
            source_refs=["sales_detail:scope-summary"],
        )

        def fake_chat(messages, **kwargs):  # noqa: ANN001
            captured_messages.extend(messages)
            result = _result(kwargs["request_id"])
            kwargs["on_result"](result)
            return result.summary

        with (
            patch("app.api.routes.crm_assistant.hermes_configured", return_value=True),
            patch(
                "app.api.routes.crm_assistant.build_global_business_context_snapshot",
                return_value=snapshot,
            ),
            patch("app.api.routes.crm_assistant.call_hermes_chat", side_effect=fake_chat),
        ):
            response = self.client.post(
                "/api/v1/crm/assistant/messages",
                headers=self.headers,
                json={"message": "查看授权经营摘要", "operation": "dashboard.summary"},
            )

        assert response.status_code == 200, response.text
        prompt = "\n".join(message["content"] for message in captured_messages)
        assert "availability" in prompt
        assert '"rows": 3' in prompt
        assert "missing_permission:account_ledger.view" in prompt
        assert "sales_detail:scope-summary" not in prompt
        assert "未授权客户" not in prompt
        assert "不得进入 AI 上下文的审批标题" not in prompt
        assert "不得进入 AI 上下文的案件证据" not in prompt

    def test_project_draft_and_daily_judgement_audits_use_unified_storage(self) -> None:
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
                json={"project_name": "阶段三项目", "customer_name": "合成客户"},
            )
        assert response.status_code == 200, response.text
        assert response.json()["message"]["operation"] == "project.draft"
        assert self.db.scalar(select(func.count()).select_from(AiConversation)) == 1
        assert self.db.scalar(select(func.count()).select_from(AiUsageEvent)) == 1

        judgement = self.client.post("/api/v1/crm/assistant/daily-judgements", headers=self.headers)
        assert judgement.status_code == 200, judgement.text
        assert judgement.json()["created"] == 0
        event_types = set(self.db.scalars(select(AiSecurityEvent.event_type)).all())
        assert "crm_assistant_project_draft" in event_types
        assert "crm_assistant_generate_judgements" in event_types

    def test_insight_unified_read_and_human_confirmed_task_execution(self) -> None:
        insight = CrmProjectInsight(
            insight_no="INS-STAGE3-1",
            insight_type="execution_risk",
            summary="合成执行风险",
            suggested_action="人工确认后转待支持",
            risk_level="high",
            confidence_score=88,
            status="draft",
            evidence_json={"source_refs": ["crm_task:9"]},
            source="rule",
            generated_by_user_id=self.user.id,
            payload_json={"generator": "stage3-test"},
        )
        self.db.add(insight)
        self.db.flush()
        mirror_insight(self.db, insight)
        self.db.commit()

        page = self.client.get("/api/v1/crm/assistant/insights/page", headers=self.headers)
        assert page.status_code == 200, page.text
        assert page.json()["total"] == 1
        assert page.json()["items"][0]["id"] == insight.id
        assert page.json()["items"][0]["confidence_score"] == 88

        reviewed = self.client.post(
            f"/api/v1/crm/assistant/insights/{insight.id}/review",
            headers=self.headers,
            json={"action": "task", "note": "已人工确认"},
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["status"] == "accepted"
        assert self.db.scalar(select(func.count()).select_from(WorkItem)) == 1
        proposal = self.db.scalar(select(AiActionProposal))
        assert proposal is not None
        assert proposal.review_status == "accepted"
        execution = self.db.scalar(select(AiActionExecution))
        assert execution is not None
        assert execution.executor_identity == "human_confirmed_crm_workflow"
        assert execution.verification_json == {"human_confirmed": True}
        assert self.db.scalar(select(AiInsight.review_status)) == "accepted"

    def test_inconsistency_falls_back_to_legacy_read(self) -> None:
        legacy = AssistantConversation(
            conversation_no="ASST-LEGACY-GAP",
            user_id=self.user.id,
            username_snapshot=self.user.username,
            channel="web",
            user_message="旧路径消息",
            assistant_message="旧路径回答",
            source="rule",
            status="completed",
        )
        self.db.add(legacy)
        self.db.commit()

        response = self.client.get("/api/v1/crm/assistant/messages", headers=self.headers)
        assert response.status_code == 200, response.text
        assert response.json()[0]["conversation_no"] == "ASST-LEGACY-GAP"
        status = self.client.get("/api/v1/crm/assistant/agents", headers=self.headers).json()
        assert status["migration_status"]["consistent"] is False
        assert status["migration_status"]["read_source"] == "legacy"
        assert status["migration_status"]["missing_conversations"] == 1

    def test_extra_unified_record_falls_back_to_legacy_read(self) -> None:
        self.db.add(
            AiConversation(
                conversation_no="AI-ORPHAN-STAGE3",
                domain="crm",
                channel="web",
                status="completed",
                actor_user_id=self.user.id,
                source_system="crm",
                legacy_type="assistant_conversation",
                legacy_id="999999",
            )
        )
        self.db.commit()

        status = self.client.get("/api/v1/crm/assistant/agents", headers=self.headers)
        assert status.status_code == 200, status.text
        assert status.json()["migration_status"]["consistent"] is False
        assert status.json()["migration_status"]["read_source"] == "legacy"
        assert status.json()["migration_status"]["extra_conversations"] == 1

    def test_ignored_insight_preserves_legacy_status_and_filter(self) -> None:
        insight = CrmProjectInsight(
            insight_no="INS-STAGE3-IGNORED",
            insight_type="execution_risk",
            summary="已人工忽略的合成风险",
            risk_level="low",
            confidence_score=25,
            status="ignored",
            source="rule",
            generated_by_user_id=self.user.id,
        )
        self.db.add(insight)
        self.db.flush()
        mirror_insight(self.db, insight)
        self.db.commit()

        ignored = self.client.get(
            "/api/v1/crm/assistant/insights/page?status_value=ignored",
            headers=self.headers,
        )
        assert ignored.status_code == 200, ignored.text
        assert ignored.json()["total"] == 1
        assert ignored.json()["items"][0]["status"] == "ignored"
        rejected = self.client.get(
            "/api/v1/crm/assistant/insights/page?status_value=rejected",
            headers=self.headers,
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["total"] == 0

    def test_context_snapshot_uses_endpoint_specific_permission(self) -> None:
        snapshot = build_crm_context_snapshot(
            {"summary": {"active_projects": 0}},
            actor_user_id=self.user.id,
            permission_codes=["crm_insight.generate"],
            required_permission="crm_insight.generate",
        )
        assert snapshot.structured_fields == {"summary": {"active_projects": 0}}

    def test_global_flags_off_preserve_legacy_only_behavior(self) -> None:
        settings.exception_ai_global_enabled = False
        message = self._post_message()
        assert message["conversation_no"].startswith("ASST")
        assert self.db.scalar(select(func.count()).select_from(AssistantConversation)) == 1
        assert self.db.scalar(select(func.count()).select_from(AiConversation)) == 0
        runtime = self.client.get("/api/v1/crm/assistant/runtime", headers=self.headers)
        assert runtime.status_code == 200
        assert runtime.json()["source"] == "project_base_hermes"
