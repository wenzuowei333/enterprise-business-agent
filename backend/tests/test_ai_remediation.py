from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.ai_remediations import router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import (
    AiCaseRemediation,
    AiCaseRemediationRun,
    AiConversation,
    AiMessage,
    ExceptionCase,
    Permission,
    Role,
    RolePermission,
    User,
    WorkItem,
)
from app.schemas.ai_remediation import RemediationActionCandidate, RemediationFormSchema, RemediationPlan
from app.services.ai_remediation_service import run_sandbox


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class TestAiRemediation:
    def setup_method(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory() as db:
            role = Role(role_code="remediation-user", role_name="Remediation User")
            permissions = [
                Permission(permission_code=code, permission_name=code, resource_type=code.split(".", 1)[0], action_type="view")
                for code in ("exception_center.view", "crm_insight.view", "inventory_snapshot.view")
            ]
            user = User(username="remediation-user", password_hash="hash", real_name="Remediation User", role=role.role_code, status="active", is_active=True)
            db.add_all([role, *permissions, user])
            db.flush()
            db.add_all([RolePermission(role_id=role.id, permission_id=permission.id) for permission in permissions])
            case = ExceptionCase(
                case_no="EXC-REMED-001",
                fingerprint="remediation-fingerprint-001",
                domain="inventory",
                rule_code="inventory.negative_stock",
                title="库存数量异常",
                severity="critical",
                status="open",
                occurrence_type="new",
                source_type="inventory_snapshot_quality",
                evidence_version="evidence-v1",
                reason="库存结存为负数",
            )
            db.add(case)
            db.flush()
            conversation = AiConversation(
                conversation_no="AI-CONV-REMED-001",
                domain="exception",
                channel="exception_center_web",
                context_type="exception_case",
                context_id=case.case_no,
                operation="exception.case_analysis",
                status="completed",
                actor_user_id=user.id,
                created_by_user_id=user.id,
                model_name="GLM-5.2",
                source_system="global_ai_chat",
                metadata_json={"evidence_version": case.evidence_version},
            )
            db.add(conversation)
            db.flush()
            message = AiMessage(
                message_no="AI-MSG-REMED-001",
                conversation_id=conversation.id,
                sequence_no=2,
                role="assistant",
                content="库存异常由来源批次不一致导致。",
                status="completed",
                created_by_user_id=user.id,
                model_name="GLM-5.2",
                source_system="global_ai_chat",
                payload_json={"context_meta": {"case_no": case.case_no, "evidence_version": case.evidence_version}},
            )
            db.add(message)
            db.commit()

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        def override_db():
            with self.session_factory() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token('remediation-user')}"}

    def teardown_method(self) -> None:
        self.client.close()
        self.engine.dispose()

    def _patches(self):
        stack = ExitStack()
        for name in ("exception_ai_remediation_enabled", "exception_ai_enabled", "exception_ai_global_enabled", "exception_ai_chat_enabled"):
            stack.enter_context(patch(f"app.services.ai_remediation_service.settings.{name}", True))
        stack.enter_context(patch("app.services.ai_remediation_service._case_analysis_context", return_value=({"case": "safe"}, [], {}, {}, [{"available_actions": []}], {})))
        return stack

    @staticmethod
    def _form_result(*args, **kwargs):  # noqa: ANN002, ANN003
        return RemediationFormSchema(
            title="补充异常修复信息",
            reason="确认修复范围",
            fields=[{"field_id": "note", "field_type": "long_text", "label": "核查结果", "required": True}],
        ), {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, "model": "GLM-5.2", "operation": "exception.remediation.form"}

    @staticmethod
    def _plan_result(*args, **kwargs):  # noqa: ANN002, ANN003
        return RemediationPlan(
            summary="建议转人工复核",
            confirmed_facts=["库存异常存在"],
            steps=["核对来源批次"],
            expected_impact="不自动写入业务数据",
            verification_steps=["重新查看异常案件"],
            rollback="无需回滚",
            action_candidate=RemediationActionCandidate(action_type=None, rationale="无确定性动作"),
        ), {"usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}, "model": "GLM-5.2", "operation": "exception.remediation.plan"}

    def test_create_is_idempotent_and_plan_falls_back_to_unassigned_work_item(self) -> None:
        with self._patches(), patch("app.services.ai_remediation_service.call_hermes_json", side_effect=[self._form_result(), self._plan_result()]), patch("app.services.ai_remediation_service.settings.exception_ai_remediation_execution_enabled", True):
            created = self.client.post("/api/v1/ai/remediations", headers=self.headers, json={"source_message_no": "AI-MSG-REMED-001", "client_request_id": "create-request-0001"})
            assert created.status_code == 201, created.text
            duplicate = self.client.post("/api/v1/ai/remediations", headers=self.headers, json={"source_message_no": "AI-MSG-REMED-001", "client_request_id": "create-request-0001"})
            assert duplicate.status_code == 201
            workflow = created.json()
            assert duplicate.json()["workflow_no"] == workflow["workflow_no"]

            answers = self.client.put(
                f"/api/v1/ai/remediations/{workflow['workflow_no']}/answers",
                headers=self.headers,
                json={"expected_lock_version": workflow["lock_version"], "answers": {"note": "已核对来源文件"}},
            )
            assert answers.status_code == 200, answers.text
            plan = self.client.post(
                f"/api/v1/ai/remediations/{workflow['workflow_no']}/plan",
                headers=self.headers,
                json={"expected_lock_version": answers.json()["lock_version"], "client_request_id": "plan-request-0001"},
            )
            assert plan.status_code == 200, plan.text
            execute = self.client.post(
                f"/api/v1/ai/remediations/{workflow['workflow_no']}/confirm-execute",
                headers=self.headers,
                json={"expected_lock_version": plan.json()["lock_version"], "confirmation": True, "idempotency_key": "execute-request-0001"},
            )
            assert execute.status_code == 200, execute.text
            assert execute.json()["result"]["mode"] == "work_item"
            replay = self.client.post(
                f"/api/v1/ai/remediations/{workflow['workflow_no']}/confirm-execute",
                headers=self.headers,
                json={"expected_lock_version": plan.json()["lock_version"], "confirmation": True, "idempotency_key": "execute-request-0001"},
            )
            assert replay.status_code == 200
            assert replay.json()["result"] == execute.json()["result"]
            with self.session_factory() as db:
                assert db.scalar(select(WorkItem)).assignee_user_id is None
                assert len(db.scalars(select(AiCaseRemediation)).all()) == 1
                assert len(db.scalars(select(AiCaseRemediationRun)).all()) == 3

    def test_cross_user_without_permissions_is_denied(self) -> None:
        with self.session_factory() as db:
            db.add(User(username="blocked-user", password_hash="hash", real_name="Blocked", role="none", status="active", is_active=True))
            db.commit()
        headers = {"Authorization": f"Bearer {create_access_token('blocked-user')}"}
        with self._patches():
            response = self.client.post("/api/v1/ai/remediations", headers=headers, json={"source_message_no": "AI-MSG-REMED-001", "client_request_id": "blocked-request-001"})
        assert response.status_code == 403

    def test_sandbox_requires_pinned_image_and_podman(self) -> None:
        candidate = {"language": "shell", "code": "echo safe"}
        with patch("app.services.ai_remediation_service.settings.exception_ai_sandbox_enabled", True), patch("app.services.ai_remediation_service.settings.ai_remediation_sandbox_image", "sandbox:latest"), patch("app.services.ai_remediation_service.shutil.which", return_value="/usr/bin/podman"):
            assert run_sandbox(candidate)["error_code"] == "sandbox_unavailable"

    def test_form_rejects_secret_collection(self) -> None:
        try:
            RemediationFormSchema(
                title="补充信息",
                reason="核查",
                fields=[{"field_id": "secret", "field_type": "short_text", "label": "请输入 API Key"}],
            )
        except ValueError as exc:
            assert "密码、Token 或密钥" in str(exc)
        else:
            raise AssertionError("secret collection field must be rejected")

    def test_action_candidate_discards_untrusted_model_parameters(self) -> None:
        candidate = RemediationActionCandidate(
            action_type="rebuild_inventory_flow",
            parameters={"case_no": "EXC-REMED-001", "warehouse_code": "SYNTHETIC"},
            rationale="由服务端根据案件证据决定执行参数",
        )
        assert candidate.parameters == {}

        candidate_with_batch = RemediationActionCandidate(
            action_type="revalidate_import_batch",
            parameters={"batch_id": 42, "source": "model"},
        )
        assert candidate_with_batch.parameters == {"batch_id": 42}

        invalid_batch = RemediationActionCandidate(
            action_type="revalidate_import_batch",
            parameters={"batch_id": "42"},
        )
        assert invalid_batch.parameters == {}

    def test_required_business_reference_without_visible_options_becomes_optional(self) -> None:
        form = RemediationFormSchema(
            title="补充异常修复信息",
            reason="确认修复范围",
            fields=[
                {
                    "field_id": "warehouse",
                    "field_type": "business_reference",
                    "reference_type": "warehouse",
                    "label": "仓库",
                    "required": True,
                }
            ],
        )
        result = (
            form,
            {
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "model": "GLM-5.2",
                "operation": "exception.remediation.form",
            },
        )
        with (
            self._patches(),
            patch("app.services.ai_remediation_service.call_hermes_json", return_value=result),
            patch("app.services.ai_remediation_service.business_reference_options", return_value=[]),
        ):
            response = self.client.post(
                "/api/v1/ai/remediations",
                headers=self.headers,
                json={
                    "source_message_no": "AI-MSG-REMED-001",
                    "client_request_id": "reference-scope-request-001",
                },
            )
        assert response.status_code == 201, response.text
        payload = response.json()["form_schema"]
        assert payload["fields"][0]["required"] is False
        assert "当前数据范围内无可选项" in payload["missing_evidence"][0]

    def test_attachment_requires_exact_mime_before_scan(self) -> None:
        with self._patches(), patch("app.services.ai_remediation_service.call_hermes_json", return_value=self._form_result()), patch("app.services.ai_remediation_service.settings.exception_ai_supplement_upload_enabled", True):
            created = self.client.post("/api/v1/ai/remediations", headers=self.headers, json={"source_message_no": "AI-MSG-REMED-001", "client_request_id": "create-upload-0001"})
            assert created.status_code == 201
            workflow_no = created.json()["workflow_no"]
            rejected = self.client.post(
                f"/api/v1/ai/remediations/{workflow_no}/attachments",
                headers=self.headers,
                files={"file": ("evidence.pdf", b"%PDF-1.7\n%%EOF", "application/octet-stream")},
            )
            assert rejected.status_code == 422
            with patch("app.services.ai_remediation_service._scan_file"), patch("app.services.ai_remediation_service._extract_attachment", return_value="脱敏证据摘要"):
                accepted = self.client.post(
                    f"/api/v1/ai/remediations/{workflow_no}/attachments",
                    headers=self.headers,
                    files={"file": ("evidence.pdf", b"%PDF-1.7\n%%EOF", "application/pdf")},
                )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["attachments"][0]["content_type"] == "application/pdf"
