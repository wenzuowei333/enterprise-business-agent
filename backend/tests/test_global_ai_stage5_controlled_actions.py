from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.crm_assistant import router as crm_assistant_router
from app.api.routes.global_ai_actions import router
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import (
    AiActionExecution,
    AiActionProposal,
    AiSecurityEvent,
    CrmProjectInsight,
    ExceptionAction,
    ExceptionCase,
    ImportBatch,
    Permission,
    Role,
    RolePermission,
    User,
    WorkItem,
)
from app.services.crm_ai_migration_service import mirror_insight


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class TestGlobalAiStageFiveControlledActions:
    def setup_method(self) -> None:
        self.previous_flags = (
            settings.exception_ai_global_enabled,
            settings.exception_ai_crm_enabled,
            settings.exception_ai_global_actions_enabled,
            settings.exception_ai_high_risk_actions_enabled,
            settings.exception_actions_enabled,
        )
        settings.exception_ai_global_enabled = True
        settings.exception_ai_crm_enabled = True
        settings.exception_ai_global_actions_enabled = True
        settings.exception_ai_high_risk_actions_enabled = True
        settings.exception_actions_enabled = True
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        admin_role = Role(role_code="admin", role_name="Admin")
        limited_role = Role(role_code="limited", role_name="Limited")
        self.user = User(
            username="stage5-admin",
            password_hash="hash",
            real_name="Stage 5 Admin",
            role="admin",
            status="active",
            is_active=True,
        )
        self.limited_user = User(
            username="stage5-limited",
            password_hash="hash",
            real_name="Stage 5 Limited",
            role="limited",
            status="active",
            is_active=True,
        )
        permission_codes = (
            "crm_insight.review",
            "crm_project.view",
            "exception_center.view",
            "exception_center.action_execute",
            "import.view",
            "import.commit",
            "inventory_check.upload",
            "receivable.check",
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
        self.db.add_all([admin_role, limited_role, self.user, self.limited_user, *permissions])
        self.db.flush()
        self.db.add_all(
            [
                RolePermission(role_id=admin_role.id, permission_id=permission.id)
                for permission in permissions
            ]
        )
        batch = ImportBatch(
            batch_no="STAGE5-BATCH",
            file_name="stage5.xlsx",
            file_type="customer_master",
            data_date=date.today(),
            uploaded_by=self.user.id,
            uploaded_at=datetime.now(timezone.utc),
            status="uploaded",
            total_rows=1,
            success_rows=0,
            error_rows=0,
            raw_file_path="/private/stage5.xlsx",
        )
        self.db.add(batch)
        self.db.flush()
        self.case = ExceptionCase(
            case_no="EXC-STAGE5-1",
            fingerprint="stage5-controlled-action",
            domain="import",
            rule_code="import.validation_required",
            title="合成导入异常",
            severity="high",
            status="open",
            occurrence_type="new",
            resource_type="import_batch",
            resource_id=str(batch.id),
            source_type="import_batch",
            source_id=str(batch.id),
            source_batch_kind="import",
            source_batch_id=batch.id,
            evidence_version="stage5-evidence-v1",
            reason="合成测试证据",
        )
        self.insight = CrmProjectInsight(
            insight_no="INS-STAGE5-1",
            insight_type="execution_risk",
            summary="合成 CRM 风险",
            suggested_action="人工确认后转待支持",
            risk_level="high",
            confidence_score=88,
            status="draft",
            source="rule",
            generated_by_user_id=self.user.id,
        )
        self.db.add_all([self.case, self.insight])
        self.db.flush()
        mirror_insight(self.db, self.insight)
        self.db.commit()
        self.crm_proposal = self.db.scalar(
            select(AiActionProposal).where(AiActionProposal.source_system == "crm")
        )
        assert self.crm_proposal is not None

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.include_router(crm_assistant_router, prefix="/api/v1")

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(self.user.username)}"}
        self.limited_headers = {
            "Authorization": f"Bearer {create_access_token(self.limited_user.username)}"
        }

    def teardown_method(self) -> None:
        self.client.close()
        self.db.close()
        self.engine.dispose()
        (
            settings.exception_ai_global_enabled,
            settings.exception_ai_crm_enabled,
            settings.exception_ai_global_actions_enabled,
            settings.exception_ai_high_risk_actions_enabled,
            settings.exception_actions_enabled,
        ) = self.previous_flags

    def _validate_exception(self) -> dict:
        response = self.client.post(
            f"/api/v1/ai/actions/exceptions/{self.case.case_no}/validate",
            headers=self.headers,
            json={"action_type": "revalidate_import_batch", "parameters": {}},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def test_catalog_and_proposals_are_permission_scoped(self) -> None:
        catalog = self.client.get("/api/v1/ai/actions/catalog", headers=self.headers)
        assert catalog.status_code == 200, catalog.text
        items = {item["action_type"]: item for item in catalog.json()}
        assert items["crm_insight.review"]["available"] is True
        assert items["revalidate_import_batch"]["available"] is True
        assert all(item["requires_confirmation"] is True for item in items.values())

        page = self.client.get("/api/v1/ai/actions/proposals", headers=self.headers)
        assert page.status_code == 200, page.text
        assert page.json()["total"] == 1
        assert page.json()["items"][0]["proposal_no"] == self.crm_proposal.proposal_no

        denied = self.client.get("/api/v1/ai/actions/proposals", headers=self.limited_headers)
        assert denied.status_code == 403

    def test_flags_fail_closed_and_high_risk_is_separate(self) -> None:
        settings.exception_ai_global_actions_enabled = False
        disabled = self.client.get("/api/v1/ai/actions/proposals", headers=self.headers)
        assert disabled.status_code == 503

        settings.exception_ai_global_actions_enabled = True
        settings.exception_ai_high_risk_actions_enabled = False
        blocked = self.client.post(
            f"/api/v1/ai/actions/exceptions/{self.case.case_no}/validate",
            headers=self.headers,
            json={"action_type": "revalidate_import_batch", "parameters": {}},
        )
        assert blocked.status_code == 503
        catalog = self.client.get("/api/v1/ai/actions/catalog", headers=self.headers).json()
        import_action = next(item for item in catalog if item["action_type"] == "revalidate_import_batch")
        assert "feature_disabled:EXCEPTION_AI_HIGH_RISK_ACTIONS_ENABLED" in import_action["blockers"]

    def test_exception_validation_and_execution_are_confirmed_idempotent_and_token_safe(self) -> None:
        validated = self._validate_exception()
        proposal = validated["proposal"]
        token = validated["validation_token"]
        assert proposal["risk_level"] == "high"
        assert proposal["executable"] is True
        assert token

        persisted = self.db.scalar(
            select(AiActionProposal).where(AiActionProposal.proposal_no == proposal["proposal_no"])
        )
        assert persisted is not None
        assert token not in str(persisted.parameters_json)
        assert token not in str(persisted.impact_json)

        stale = self.client.post(
            f"/api/v1/ai/actions/proposals/{proposal['proposal_no']}/execute",
            headers=self.headers,
            json={
                "expected_updated_at": "2000-01-01T00:00:00Z",
                "confirmation": True,
                "idempotency_key": "stage5-exception-action-1",
                "validation_token": token,
            },
        )
        assert stale.status_code == 409

        def fake_execute(db, case, validation_token, idempotency_key, user):  # noqa: ANN001
            assert validation_token == token
            assert user.id == self.user.id
            action = db.scalar(select(ExceptionAction).where(ExceptionAction.case_id == case.id))
            assert action is not None
            now = datetime.now(timezone.utc)
            action.idempotency_key = idempotency_key
            action.status = "completed"
            action.started_at = now
            action.completed_at = now
            action.result_json = {"batch_id": self.case.source_batch_id, "status": "validated"}
            action.verification_json = {"case_status": "resolved"}
            return action

        payload = {
            "expected_updated_at": proposal["updated_at"],
            "confirmation": True,
            "idempotency_key": "stage5-exception-action-1",
            "validation_token": token,
        }
        with patch(
            "app.services.controlled_action_service.execute_action",
            side_effect=fake_execute,
        ):
            executed = self.client.post(
                f"/api/v1/ai/actions/proposals/{proposal['proposal_no']}/execute",
                headers=self.headers,
                json=payload,
            )
            replayed = self.client.post(
                f"/api/v1/ai/actions/proposals/{proposal['proposal_no']}/execute",
                headers=self.headers,
                json=payload,
            )
        assert executed.status_code == 200, executed.text
        assert replayed.status_code == 200, replayed.text
        assert executed.json()["execution_no"] == replayed.json()["execution_no"]
        assert self.db.scalar(select(func.count()).select_from(AiActionExecution)) == 1
        execution = self.db.scalar(select(AiActionExecution))
        assert execution is not None
        assert token not in str(execution.request_json)
        assert execution.verification_json["human_confirmed"] is True
        assert self.db.scalar(select(func.count()).select_from(AiSecurityEvent)) == 2

    def test_crm_review_creates_one_work_item_and_one_execution(self) -> None:
        body = {
            "expected_updated_at": self.crm_proposal.updated_at.isoformat(),
            "confirmation": True,
            "decision": "task",
            "idempotency_key": "stage5-crm-action-1",
            "note": "人工确认转待支持",
        }
        first = self.client.post(
            f"/api/v1/ai/actions/proposals/{self.crm_proposal.proposal_no}/crm-review",
            headers=self.headers,
            json=body,
        )
        replay = self.client.post(
            f"/api/v1/ai/actions/proposals/{self.crm_proposal.proposal_no}/crm-review",
            headers=self.headers,
            json=body,
        )
        assert first.status_code == 200, first.text
        assert replay.status_code == 200, replay.text
        assert first.json()["execution_no"] == replay.json()["execution_no"]
        conflicting = self.client.post(
            f"/api/v1/ai/actions/proposals/{self.crm_proposal.proposal_no}/crm-review",
            headers=self.headers,
            json={**body, "decision": "reject"},
        )
        assert conflicting.status_code == 409
        assert self.db.scalar(select(func.count()).select_from(WorkItem)) == 1
        assert self.db.scalar(select(func.count()).select_from(AiActionExecution)) == 1
        self.db.refresh(self.insight)
        assert self.insight.status == "accepted"
        execution = self.db.scalar(select(AiActionExecution))
        assert execution is not None
        assert execution.executor_identity == "human_confirmed_crm_workflow"
        assert execution.verification_json == {"human_confirmed": True}
        history = self.client.get("/api/v1/ai/actions/executions", headers=self.headers)
        assert history.status_code == 200, history.text
        assert history.json()["total"] == 1
        assert history.json()["items"][0]["execution_no"] == first.json()["execution_no"]

    def test_legacy_crm_review_path_also_records_controlled_execution(self) -> None:
        response = self.client.post(
            f"/api/v1/crm/assistant/insights/{self.insight.id}/review",
            headers=self.headers,
            json={"action": "accept", "note": "人工确认采纳"},
        )
        assert response.status_code == 200, response.text
        execution = self.db.scalar(select(AiActionExecution))
        assert execution is not None
        assert execution.request_json == {"action": "accept"}
        assert execution.executor_identity == "human_confirmed_crm_workflow"
        event = self.db.scalar(
            select(AiSecurityEvent).where(
                AiSecurityEvent.event_type == "controlled_action_executed"
            )
        )
        assert event is not None
        assert event.detail_json == {
            "action_type": "crm_insight.review",
            "decision": "accept",
            "status": "completed",
            "human_confirmed": True,
        }

    def test_confirmation_and_request_contract_reject_unsafe_payloads(self) -> None:
        validated = self._validate_exception()
        proposal = validated["proposal"]
        missing_confirmation = self.client.post(
            f"/api/v1/ai/actions/proposals/{proposal['proposal_no']}/execute",
            headers=self.headers,
            json={
                "expected_updated_at": proposal["updated_at"],
                "confirmation": False,
                "idempotency_key": "stage5-unsafe-action",
                "validation_token": validated["validation_token"],
            },
        )
        assert missing_confirmation.status_code == 422
        extra_payload = self.client.post(
            f"/api/v1/ai/actions/exceptions/{self.case.case_no}/validate",
            headers=self.headers,
            json={
                "action_type": "revalidate_import_batch",
                "parameters": {"sql": "delete from import_batch"},
            },
        )
        assert extra_payload.status_code == 422
