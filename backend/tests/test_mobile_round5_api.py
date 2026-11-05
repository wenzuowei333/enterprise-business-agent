import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi import HTTPException, Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.mobile import mobile_bootstrap
from app.api.routes.mobile_round5 import (
    _create_ai_draft,
    _draft_context,
    _require_ai_drafts,
    _require_feedback_admin,
    mobile_adoption_summary,
    mobile_create_feedback,
    mobile_list_my_feedback,
    mobile_admin_update_feedback,
    parse_mobile_ai_draft,
)
from app.api.routes.mobile_tools import mobile_telemetry
from app.main import create_app
import app.api.routes.mobile_round5 as mobile_round5_routes
from app.models import MobileFeedback, MobileTelemetryRecord, User
from app.schemas.mobile import (
    MobileAssistantDraftRequest,
    MobileFeedbackCreate,
    MobileFeedbackUpdate,
    MobileTelemetryBatch,
    MobileTelemetryEvent,
)


class MobileRound5ApiTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        User.__table__.create(engine)
        MobileFeedback.__table__.create(engine)
        MobileTelemetryRecord.__table__.create(engine)
        self.db = Session(engine)
        self.user = User(
            username="sales",
            password_hash="hash",
            real_name="一线业务员",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)
        self.request = Request({"type": "http", "method": "POST", "path": "/mobile/feedback", "headers": []})

    def tearDown(self):
        self.db.close()

    def test_round5_routes_are_registered(self):
        paths = set(create_app().openapi()["paths"])
        expected = {
            "/api/v1/mobile/feedback",
            "/api/v1/mobile/feedback/mine",
            "/api/v1/mobile/feedback/attachments",
            "/api/v1/mobile/feedback/{feedback_id}/attachment",
            "/api/v1/mobile/admin/feedback",
            "/api/v1/mobile/admin/feedback/{feedback_id}",
            "/api/v1/mobile/admin/adoption/overview",
            "/api/v1/mobile/assistant/drafts/followup",
            "/api/v1/mobile/assistant/drafts/approval-opinion",
            "/api/v1/mobile/assistant/drafts/project-summary",
        }
        self.assertTrue(expected.issubset(paths), expected - paths)

    def test_feedback_only_persists_whitelisted_diagnostics(self):
        payload = MobileFeedbackCreate(
            category="bug",
            description="任务详情无法打开",
            current_route="tasks/12?customer_phone=13800000000",
            request_id="req-12",
            app_version="1.3.0",
            device_model="Pixel",
        )
        with patch("app.api.routes.mobile_round5.write_audit_log"):
            result = mobile_create_feedback(payload=payload, request=self.request, db=self.db, current_user=self.user)

        row = self.db.scalar(select(MobileFeedback))
        self.assertEqual(result.status, "open")
        self.assertEqual(row.current_route, "tasks/12")
        self.assertEqual(row.request_id, "req-12")
        self.assertNotIn("13800000000", row.current_route)

    def test_user_only_lists_own_feedback(self):
        other = User(
            username="other",
            password_hash="hash",
            real_name="其他人",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.db.add(other)
        self.db.commit()
        self.db.add_all(
            [
                MobileFeedback(user_id=self.user.id, category="bug", description="我的反馈", status="open"),
                MobileFeedback(user_id=other.id, category="bug", description="他人反馈", status="open"),
            ]
        )
        self.db.commit()

        result = mobile_list_my_feedback(limit=20, offset=0, db=self.db, current_user=self.user)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].description, "我的反馈")

    def test_feedback_hides_private_screenshot_storage_path(self):
        with tempfile.TemporaryDirectory() as directory:
            pending = Path(directory) / "pending"
            private = Path(directory) / "private"
            source = pending / str(self.user.id) / "safe.jpg"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"\xff\xd8\xffrest")
            payload = MobileFeedbackCreate(
                category="bug",
                description="附带截图的反馈",
                screenshot_path=f"mobile-feedback://{self.user.id}/safe.jpg",
            )
            with (
                patch("app.api.routes.mobile_round5._feedback_pending_root", return_value=pending),
                patch("app.api.routes.mobile_round5._feedback_storage_root", return_value=private),
                patch("app.api.routes.mobile_round5.write_audit_log"),
            ):
                result = mobile_create_feedback(payload=payload, request=self.request, db=self.db, current_user=self.user)

            stored = self.db.scalar(select(MobileFeedback))
            self.assertEqual(stored.screenshot_path, f"mobile-feedback://{self.user.id}/safe.jpg")
            self.assertEqual(result.screenshot_path, f"/api/v1/mobile/feedback/{stored.id}/attachment")

    def test_feedback_image_signature_must_match_declared_type(self):
        self.assertTrue(mobile_round5_routes._feedback_image_matches("image/png", b"\x89PNG\r\n\x1a\nrest"))
        self.assertFalse(mobile_round5_routes._feedback_image_matches("image/png", b"not-an-image"))

    def test_feedback_creation_moves_pending_screenshot_into_private_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            pending = Path(directory) / "pending"
            private = Path(directory) / "private"
            source = pending / str(self.user.id) / "safe.png"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"\x89PNG\r\n\x1a\nrest")
            payload = MobileFeedbackCreate(
                category="bug",
                description="截图反馈",
                screenshot_path=f"mobile-feedback://{self.user.id}/safe.png",
            )
            with (
                patch("app.api.routes.mobile_round5._feedback_pending_root", return_value=pending),
                patch("app.api.routes.mobile_round5._feedback_storage_root", return_value=private),
                patch("app.api.routes.mobile_round5.write_audit_log"),
            ):
                mobile_create_feedback(payload=payload, request=self.request, db=self.db, current_user=self.user)
            self.assertFalse(source.exists())
            self.assertTrue((private / str(self.user.id) / "safe.png").is_file())

    def test_resolved_feedback_requires_visible_resolution(self):
        admin = User(
            username="admin",
            password_hash="hash",
            real_name="管理员",
            role="admin",
            status="active",
            is_active=True,
        )
        row = MobileFeedback(user_id=self.user.id, category="bug", description="待处理问题", status="open")
        self.db.add_all([admin, row])
        self.db.commit()

        with self.assertRaises(HTTPException) as error:
            mobile_admin_update_feedback(
                feedback_id=row.id,
                payload=MobileFeedbackUpdate(status="resolved"),
                request=self.request,
                db=self.db,
                current_user=admin,
            )
        self.assertEqual(error.exception.status_code, 422)

    def test_ai_draft_parser_rejects_non_object_fields(self):
        with self.assertRaises(ValueError):
            parse_mobile_ai_draft('{"fields": "直接审批通过", "warnings": [], "source_refs": []}', "approval_opinion")

    def test_ai_drafts_and_feedback_admin_reject_salesperson(self):
        with self.assertRaises(HTTPException) as ai_error:
            _require_ai_drafts(self.user)
        self.assertEqual(ai_error.exception.status_code, 403)

        with patch("app.api.routes.mobile_round5.has_permission", return_value=False), self.assertRaises(HTTPException) as feedback_error:
            _require_feedback_admin(self.db, self.user)
        self.assertEqual(feedback_error.exception.status_code, 403)

    def test_ai_draft_parser_returns_structured_draft_only(self):
        result = parse_mobile_ai_draft(
            "```json\n{\"fields\": {\"comment\": \"资料完整，建议通过\"}, \"warnings\": [\"请人工核对\"], \"source_refs\": [\"approval:12\"]}\n```",
            "approval_opinion",
        )
        self.assertEqual(result["fields"]["comment"], "资料完整，建议通过")
        self.assertNotIn("action", result)

    def test_ai_context_rejects_task_outside_current_user_scope(self):
        payload = MobileAssistantDraftRequest(task_id=999)
        scoped_db = MagicMock()
        scoped_db.scalar.return_value = None
        with patch("app.api.routes.mobile_round5.has_permission", return_value=True), self.assertRaises(HTTPException) as error:
            _draft_context("followup", payload, scoped_db, self.user)
        self.assertEqual(error.exception.status_code, 404)

    def test_ai_conversation_does_not_persist_prompt_or_generated_business_text(self):
        admin = User(
            username="admin-ai",
            password_hash="hash",
            real_name="管理员",
            role="admin",
            status="active",
            is_active=True,
        )
        secret_prompt = "客户电话 13800000000，地址测试路 18 号"
        secret_draft = "建议回访 13800000000"
        payload = MobileAssistantDraftRequest(text=secret_prompt)
        draft_db = MagicMock()
        with (
            patch("app.api.routes.mobile_round5.settings.mobile_feature_ai_drafts", True),
            patch("app.api.routes.mobile_round5.hermes_configured", return_value=True),
            patch(
                "app.api.routes.mobile_round5.call_hermes_chat",
                return_value=f'{{"fields": {{"comment": "{secret_draft}"}}, "warnings": [], "source_refs": []}}',
            ),
            patch("app.api.routes.mobile_round5.write_audit_log"),
        ):
            _create_ai_draft("followup", payload, self.request, draft_db, admin)
        row = draft_db.add.call_args.args[0]
        self.assertNotIn(secret_prompt, row.user_message)
        self.assertNotIn(secret_prompt, str(row.payload_json))
        self.assertNotIn(secret_draft, row.assistant_message)

    def test_mobile_telemetry_is_not_written_to_user_audit_log(self):
        payload = MobileTelemetryBatch(
            installation_id="anonymous-installation",
            events=[
                MobileTelemetryEvent(
                    event_type="feature_usage",
                    occurred_at=datetime.now(timezone.utc).isoformat(),
                    code="voice_input",
                    app_version="1.3.0",
                )
            ],
        )
        mobile_telemetry(payload=payload, request=self.request, db=self.db, current_user=self.user)
        row = self.db.scalar(select(MobileTelemetryRecord))
        self.assertEqual(row.event_type, "feature_usage")
        self.assertFalse(hasattr(row, "user_id"))

    def test_adoption_summary_calculates_rate_without_business_content(self):
        now = datetime.now(timezone.utc)
        summary = mobile_adoption_summary(
            eligible_users=10,
            active_user_ids={1, 2, 3, 4},
            feedback_rows=[
                MagicMock(status="resolved", created_at=now - timedelta(hours=5), resolved_at=now),
                MagicMock(status="open", created_at=now, resolved_at=None),
            ],
            telemetry_events=[
                {"event_type": "feature_usage", "code": "voice_input"},
                {"event_type": "feature_usage", "code": "voice_input"},
                {"event_type": "feature_usage", "code": "ai_draft_requested"},
                {"event_type": "feature_usage", "code": "ai_draft_structured_success"},
                {"event_type": "feature_usage", "code": "ai_draft_adopted"},
                {"event_type": "form_timing", "code": "followup", "duration_ms": 120000},
            ],
        )
        self.assertEqual(summary["weekly_active_rate"], 40.0)
        self.assertEqual(summary["feature_usage"]["voice_input"], 2)
        self.assertEqual(summary["followup_form_p50_ms"], 120000)
        self.assertEqual(summary["followup_form_avg_ms"], 120000)
        self.assertEqual(summary["ai_draft_success_rate"], 100.0)
        self.assertEqual(summary["ai_draft_adoption_rate"], 100.0)
        self.assertNotIn("description", summary)

    def test_bootstrap_exposes_round5_contract(self):
        with (
            patch("app.api.routes.mobile.get_final_permission_codes", return_value=[]),
            patch("app.api.routes.mobile._visible_nav", return_value=[]),
            patch("app.api.routes.mobile._mobile_scope_revision", return_value="scope-round5"),
        ):
            payload = mobile_bootstrap(db=object(), current_user=self.user)
        self.assertEqual(payload["app"]["latest_version_code"], 7)
        self.assertIn("onboarding_version", payload["app"])
        self.assertIn("voice_input", payload["app"]["feature_flags"])
        self.assertIn("ai_drafts", payload["app"]["feature_flags"])


if __name__ == "__main__":
    unittest.main()
