import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app.api.routes.mobile_v2 import (
    mobile_v2_customer_panorama,
    mobile_v2_customer_tags,
    mobile_v2_add_delivery_event,
    mobile_v2_deliveries,
    mobile_v2_exception_detail,
    mobile_v2_exceptions,
    mobile_v2_diagnosis_job,
    mobile_v2_execute_ai_action,
    mobile_v2_execution,
    mobile_v2_request_diagnosis,
    mobile_v2_validate_ai_action,
    mobile_v2_workbench,
)
from app.main import create_app
from app.models import ApprovalInstance, CrmProject, CrmProjectCustomerTask, CustomerMaster, DeliveryTask, User, WorkItem
from app.schemas.exception_center import DiagnosisRequest
from app.schemas.global_ai import ControlledActionExecuteRequest
from app.schemas.mobile import MobileDeliveryEventRequest
from app.services.mobile_sync_service import mobile_operation_payload_hash


class MobileV2WorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.user = User(
            id=7,
            username="field-user",
            password_hash="hash",
            real_name="现场业务",
            role="salesperson",
            status="active",
            is_active=True,
        )

    def test_route_is_registered_under_mobile_v2(self):
        self.assertIn("/api/v1/mobile/v2/workbench", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/execution", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/customers/{customer_code}/panorama", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/exceptions", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/exceptions/{case_no}", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/exceptions/{case_no}/diagnoses", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/diagnosis-jobs/{job_id}", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/ai/actions", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/ai/actions/{proposal_no}/validate", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/ai/actions/{proposal_no}/execute", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/customers/{customer_code}/tags", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/deliveries", create_app().openapi()["paths"])
        self.assertIn("/api/v1/mobile/v2/deliveries/{delivery_id}/events", create_app().openapi()["paths"])

    def test_mobile_customer_tags_reuses_scoped_panorama_projection(self):
        panorama = {
            "generated_at": "2026-08-31T00:00:00Z",
            "customer": {"customer_code": "C-1", "customer_name": "客户一"},
            "tags": {"items": [{"name": "冷链"}], "compatibility_tags": [], "review_due_count": 0},
        }
        with (
            patch("app.api.routes.mobile_v2.settings.mobile_feature_customer_tags", True),
            patch("app.api.routes.mobile_v2.mobile_v2_customer_panorama", return_value=panorama) as scoped_panorama,
            patch("app.api.routes.mobile_v2._can", side_effect=lambda _db, _user, code: code == "customer_tag.history"),
        ):
            result = mobile_v2_customer_tags("C-1", db=MagicMock(), current_user=self.user)

        self.assertEqual(result["tags"]["items"][0]["name"], "冷链")
        self.assertTrue(result["capabilities"]["view_history"])
        scoped_panorama.assert_called_once()

    def test_mobile_delivery_event_requires_note_for_cancellation(self):
        with self.assertRaises(ValueError):
            MobileDeliveryEventRequest(
                expected_updated_at=datetime.now(timezone.utc),
                idempotency_key="android:delivery-cancel-1",
                event_type="cancel",
                to_status="cancelled",
            )

    def test_mobile_deliveries_are_scoped_and_drop_attachment_metadata(self):
        delivery = MagicMock(id=11)
        rows = MagicMock()
        rows.all.return_value = [delivery]
        db = MagicMock()
        db.scalars.return_value = rows
        serialized = {
            "id": 11,
            "delivery_no": "DEL-11",
            "status": "planned",
            "updated_at": datetime.now(timezone.utc),
            "events": [],
            "attachments": [{"file_name": "private.jpg", "storage_path": "secret/path"}],
        }
        with (
            patch("app.api.routes.mobile_v2.settings.mobile_feature_fulfillment", True),
            patch("app.api.routes.mobile_v2._can", return_value=True),
            patch("app.api.routes.mobile_v2.require_feature"),
            patch("app.api.routes.mobile_v2.apply_data_scope", side_effect=lambda stmt, *_args: stmt) as scope,
            patch("app.api.routes.mobile_v2._count", return_value=1),
            patch("app.api.routes.mobile_v2.serialize_delivery", return_value=serialized),
        ):
            result = mobile_v2_deliveries(
                q=None, delivery_status=None, limit=20, offset=0, db=db, current_user=self.user,
            )

        self.assertEqual(result["total"], 1)
        self.assertNotIn("attachments", result["items"][0])
        self.assertNotIn("storage_path", str(result))
        self.assertEqual(scope.call_args.args[-1], "customer")

    def test_mobile_delivery_event_requires_current_version_and_records_idempotency(self):
        now = datetime.now(timezone.utc)
        delivery = MagicMock(id=12, updated_at=now)
        db = MagicMock()
        db.scalar.side_effect = [delivery, None]
        body = MobileDeliveryEventRequest(
            expected_updated_at=now,
            idempotency_key="android:delivery-operation-12",
            event_type="dispatch",
            to_status="delivering",
        )
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        serialized = {"id": 12, "delivery_no": "DEL-12", "status": "delivering", "updated_at": now, "events": []}
        with (
            patch("app.api.routes.mobile_v2._require_mobile_fulfillment"),
            patch("app.api.routes.mobile_v2._visible_delivery_stmt", return_value=select(DeliveryTask)),
            patch("app.api.routes.mobile_v2.apply_delivery_event") as apply_event,
            patch("app.api.routes.mobile_v2.serialize_delivery", return_value=serialized),
        ):
            result = mobile_v2_add_delivery_event(12, body, request, db=db, current_user=self.user)

        self.assertEqual(result["status"], "delivering")
        apply_event.assert_called_once()
        operation = db.add.call_args.args[0]
        self.assertEqual(operation.client_operation_id, "android:delivery-operation-12")
        self.assertEqual(operation.status, "applied")
        db.commit.assert_called_once()

    def test_mobile_delivery_event_replay_returns_original_result_without_writing(self):
        now = datetime.now(timezone.utc)
        body = MobileDeliveryEventRequest(
            expected_updated_at=now,
            idempotency_key="android:delivery-operation-13",
            event_type="dispatch",
            to_status="delivering",
        )
        payload_hash = mobile_operation_payload_hash(body.model_dump(mode="json", exclude={"idempotency_key"}))
        delivery = MagicMock(id=13, updated_at=now)
        operation = MagicMock(payload_hash=payload_hash, status="applied", result_json={"id": 13, "status": "delivering"})
        db = MagicMock()
        db.scalar.side_effect = [delivery, operation]
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        with (
            patch("app.api.routes.mobile_v2._require_mobile_fulfillment"),
            patch("app.api.routes.mobile_v2._visible_delivery_stmt", return_value=select(DeliveryTask)),
            patch("app.api.routes.mobile_v2.apply_delivery_event") as apply_event,
        ):
            result = mobile_v2_add_delivery_event(13, body, request, db=db, current_user=self.user)

        self.assertEqual(result["status"], "delivering")
        apply_event.assert_not_called()
        db.commit.assert_not_called()

    def test_mobile_delivery_event_rejects_stale_version(self):
        current = datetime.now(timezone.utc)
        body = MobileDeliveryEventRequest(
            expected_updated_at=current - timedelta(minutes=1),
            idempotency_key="android:delivery-operation-stale",
            event_type="dispatch",
            to_status="delivering",
        )
        db = MagicMock()
        db.scalar.side_effect = [MagicMock(id=14, updated_at=current), None]
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        with (
            patch("app.api.routes.mobile_v2._require_mobile_fulfillment"),
            patch("app.api.routes.mobile_v2._visible_delivery_stmt", return_value=select(DeliveryTask)),
            patch("app.api.routes.mobile_v2.apply_delivery_event") as apply_event,
        ):
            with self.assertRaises(HTTPException) as conflict:
                mobile_v2_add_delivery_event(14, body, request, db=db, current_user=self.user)

        self.assertEqual(conflict.exception.status_code, 409)
        apply_event.assert_not_called()
        db.commit.assert_not_called()

    def test_mobile_delivery_event_rejects_reused_idempotency_key_for_other_payload(self):
        now = datetime.now(timezone.utc)
        body = MobileDeliveryEventRequest(
            expected_updated_at=now,
            idempotency_key="android:delivery-operation-reused",
            event_type="dispatch",
            to_status="delivering",
        )
        delivery = MagicMock(id=15, updated_at=now)
        operation = MagicMock(payload_hash="different-payload", status="applied", result_json={"id": 15})
        db = MagicMock()
        db.scalar.side_effect = [delivery, operation]
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        with (
            patch("app.api.routes.mobile_v2._require_mobile_fulfillment"),
            patch("app.api.routes.mobile_v2._visible_delivery_stmt", return_value=select(DeliveryTask)),
            patch("app.api.routes.mobile_v2.apply_delivery_event") as apply_event,
        ):
            with self.assertRaises(HTTPException) as conflict:
                mobile_v2_add_delivery_event(15, body, request, db=db, current_user=self.user)

        self.assertEqual(conflict.exception.status_code, 409)
        apply_event.assert_not_called()
        db.commit.assert_not_called()

    def test_mobile_diagnosis_reuses_existing_service_and_permission(self):
        expected = {"id": 9, "job_no": "JOB-9", "status": "queued"}
        with (
            patch("app.api.routes.mobile_v2.settings.exception_center_enabled", True),
            patch("app.api.routes.mobile_v2.settings.mobile_feature_exception_center", True),
            patch("app.api.routes.mobile_v2.settings.exception_ai_enabled", True),
            patch("app.api.routes.mobile_v2._can", return_value=True),
            patch("app.api.routes.mobile_v2.request_diagnosis", return_value=expected) as request_diagnosis,
        ):
            result = mobile_v2_request_diagnosis("EX-9", DiagnosisRequest(), db=MagicMock(), current_user=self.user)

        self.assertEqual(result, expected)
        self.assertEqual(request_diagnosis.call_args.kwargs["case_no"], "EX-9")

    def test_mobile_diagnosis_returns_503_when_ai_is_disabled(self):
        with (
            patch("app.api.routes.mobile_v2.settings.exception_center_enabled", True),
            patch("app.api.routes.mobile_v2.settings.mobile_feature_exception_center", True),
            patch("app.api.routes.mobile_v2.settings.exception_ai_enabled", False),
            patch("app.api.routes.mobile_v2._can", return_value=True),
        ):
            with self.assertRaises(HTTPException) as unavailable:
                mobile_v2_request_diagnosis("EX-9", DiagnosisRequest(), db=MagicMock(), current_user=self.user)
        self.assertEqual(unavailable.exception.status_code, 503)

    def test_mobile_diagnosis_job_requires_diagnose_permission(self):
        with (
            patch("app.api.routes.mobile_v2.settings.exception_center_enabled", True),
            patch("app.api.routes.mobile_v2.settings.mobile_feature_exception_center", True),
            patch("app.api.routes.mobile_v2._can", side_effect=lambda _db, _user, code: code == "exception_center.view"),
        ):
            with self.assertRaises(HTTPException) as forbidden:
                mobile_v2_diagnosis_job(9, db=MagicMock(), current_user=self.user)
        self.assertEqual(forbidden.exception.status_code, 403)

    def test_mobile_action_validation_rebuilds_token_from_current_evidence(self):
        proposal = MagicMock(
            source_system="exception",
            resource_type="exception_case",
            resource_id="EX-10",
            action_type="rerun_inventory_check",
            parameters_json={"batch_id": 12},
        )
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        expected = {"proposal": {"proposal_no": "AI-EXC-PROP-10"}, "validation_token": "ephemeral"}
        with (
            patch("app.api.routes.mobile_v2._require_mobile_action_access"),
            patch("app.api.routes.mobile_v2.visible_action_proposal_or_404", return_value=proposal),
            patch("app.api.routes.mobile_v2.validate_controlled_exception_action", return_value=expected) as validate,
        ):
            result = mobile_v2_validate_ai_action("AI-EXC-PROP-9", request, db=MagicMock(), current_user=self.user)

        self.assertEqual(result, expected)
        self.assertEqual(validate.call_args.kwargs["case_no"], "EX-10")
        self.assertEqual(validate.call_args.kwargs["body"].parameters, {"batch_id": 12})

    def test_mobile_action_validation_rejects_non_exception_proposal(self):
        proposal = MagicMock(
            source_system="crm",
            resource_type="crm_project_insight",
            resource_id="INSIGHT-1",
        )
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        with (
            patch("app.api.routes.mobile_v2._require_mobile_action_access"),
            patch("app.api.routes.mobile_v2.visible_action_proposal_or_404", return_value=proposal),
        ):
            with self.assertRaises(HTTPException) as conflict:
                mobile_v2_validate_ai_action("AI-CRM-PROP-1", request, db=MagicMock(), current_user=self.user)
        self.assertEqual(conflict.exception.status_code, 409)

    def test_mobile_action_execution_preserves_confirmation_version_token_and_idempotency(self):
        body = ControlledActionExecuteRequest(
            expected_updated_at=datetime.now(timezone.utc),
            confirmation=True,
            idempotency_key="android:operation-1",
            validation_token="a" * 24,
        )
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        with (
            patch("app.api.routes.mobile_v2._require_mobile_action_access"),
            patch(
                "app.api.routes.mobile_v2.visible_action_proposal_or_404",
                return_value=MagicMock(source_system="exception", resource_type="exception_case"),
            ),
            patch("app.api.routes.mobile_v2.execute_controlled_action", return_value={"status": "completed"}) as execute,
        ):
            result = mobile_v2_execute_ai_action("AI-EXC-PROP-10", body, request, db=MagicMock(), current_user=self.user)

        self.assertEqual(result["status"], "completed")
        self.assertIs(execute.call_args.kwargs["body"], body)

    def test_mobile_action_execution_rejects_non_exception_proposal(self):
        body = ControlledActionExecuteRequest(
            expected_updated_at=datetime.now(timezone.utc),
            confirmation=True,
            idempotency_key="android:operation-2",
            validation_token="b" * 24,
        )
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        with (
            patch("app.api.routes.mobile_v2._require_mobile_action_access"),
            patch(
                "app.api.routes.mobile_v2.visible_action_proposal_or_404",
                return_value=MagicMock(source_system="crm", resource_type="crm_project_insight"),
            ),
        ):
            with self.assertRaises(HTTPException) as conflict:
                mobile_v2_execute_ai_action("AI-CRM-PROP-2", body, request, db=MagicMock(), current_user=self.user)
        self.assertEqual(conflict.exception.status_code, 409)

    def test_mobile_action_access_returns_503_when_actions_are_disabled(self):
        from app.api.routes.mobile_v2 import _require_mobile_action_access

        with (
            patch("app.api.routes.mobile_v2._require_mobile_exception_access"),
            patch("app.api.routes.mobile_v2._can", return_value=True),
            patch("app.api.routes.mobile_v2.controlled_actions_enabled", return_value=False),
        ):
            with self.assertRaises(HTTPException) as unavailable:
                _require_mobile_action_access(MagicMock(), self.user)
        self.assertEqual(unavailable.exception.status_code, 503)

    def test_mobile_exception_list_is_scoped_and_drops_web_only_payload(self):
        from sqlalchemy import select
        from app.models import ExceptionCase

        db = MagicMock()
        rows = MagicMock()
        rows.all.return_value = [object()]
        db.scalars.return_value = rows
        serialized = {
            "id": 1,
            "case_no": "EX-1",
            "domain": "inventory",
            "diagnosis_supported": True,
            "rule_code": "inventory_gap",
            "title": "库存差异",
            "severity": "high",
            "status": "open",
            "source_type": "inventory_check",
            "evidence_version": "ev-1",
            "reason": "账实不一致",
            "last_seen_at": datetime.now(timezone.utc),
            "metadata": {"private": "不得下发"},
            "diagnosis": {"raw": "不得下发"},
        }
        with (
            patch("app.api.routes.mobile_v2.settings.exception_center_enabled", True),
            patch("app.api.routes.mobile_v2.settings.mobile_feature_exception_center", True),
            patch("app.api.routes.mobile_v2._can", side_effect=lambda _db, _user, code: code in {"exception_center.view", "exception_center.diagnose"}),
            patch("app.api.routes.mobile_v2.scoped_exception_stmt", return_value=select(ExceptionCase)),
            patch("app.api.routes.mobile_v2._count", return_value=1),
            patch("app.api.routes.mobile_v2.serialize_cases", return_value=[serialized]),
            patch("app.api.routes.mobile_v2.summary_for_cases", return_value={"total": 1, "open": 1}),
            patch("app.api.routes.mobile_v2.settings.exception_ai_enabled", True),
        ):
            result = mobile_v2_exceptions(
                domain=None, severity=None, case_status=None, assignment=None, q=None, limit=20, offset=0,
                db=db, current_user=self.user,
            )

        self.assertEqual(result["items"][0]["case_no"], "EX-1")
        self.assertNotIn("metadata", result["items"][0])
        self.assertNotIn("diagnosis", result["items"][0])
        self.assertTrue(result["capabilities"]["diagnose"])

    def test_mobile_exception_detail_never_returns_validation_token(self):
        payload = {
            "id": 1,
            "case_no": "EX-2",
            "domain": "master_data",
            "diagnosis_supported": True,
            "rule_code": "missing_link",
            "title": "主数据关联缺失",
            "severity": "critical",
            "status": "action_required",
            "source_type": "master_data",
            "evidence_version": "ev-2",
            "reason": "商品关联缺失",
            "last_seen_at": datetime.now(timezone.utc),
            "evidence": {"summary": "缺少关联"},
            "diagnoses": [],
            "events": [],
            "actions": [{"id": 8, "status": "validated", "validation_token": "secret-token", "result": {"private": True}}],
            "active_diagnosis_job": None,
        }
        with (
            patch("app.api.routes.mobile_v2.settings.exception_center_enabled", True),
            patch("app.api.routes.mobile_v2.settings.mobile_feature_exception_center", True),
            patch("app.api.routes.mobile_v2._can", side_effect=lambda _db, _user, code: code == "exception_center.view"),
            patch("app.api.routes.mobile_v2.exception_detail", return_value=payload),
        ):
            result = mobile_v2_exception_detail("EX-2", db=MagicMock(), current_user=self.user)

        self.assertEqual(result["evidence"], {"summary": "缺少关联"})
        self.assertEqual(result["actions"], [{"id": 8, "status": "validated"}])

    def test_mobile_exception_center_requires_feature_and_view_permission(self):
        with (
            patch("app.api.routes.mobile_v2.settings.exception_center_enabled", False),
            patch("app.api.routes.mobile_v2.settings.mobile_feature_exception_center", False),
        ):
            with self.assertRaises(HTTPException) as disabled:
                mobile_v2_exceptions(
                    domain=None, severity=None, case_status=None, assignment=None, q=None, limit=20, offset=0,
                    db=MagicMock(), current_user=self.user,
                )
        self.assertEqual(disabled.exception.status_code, 404)

        with (
            patch("app.api.routes.mobile_v2.settings.exception_center_enabled", True),
            patch("app.api.routes.mobile_v2.settings.mobile_feature_exception_center", True),
            patch("app.api.routes.mobile_v2._can", return_value=False),
        ):
            with self.assertRaises(HTTPException) as forbidden:
                mobile_v2_exceptions(
                    domain=None, severity=None, case_status=None, assignment=None, q=None, limit=20, offset=0,
                    db=MagicMock(), current_user=self.user,
                )
        self.assertEqual(forbidden.exception.status_code, 403)

    def test_customer_panorama_redacts_tag_evidence_and_orders_timeline(self):
        customer = CustomerMaster(customer_code="C-11", customer_name="测试客户", customer_tags=["重点客户"])
        db = MagicMock()
        db.scalar.return_value = customer
        context = {
            "customer": {"customer_code": "C-11", "customer_name": "测试客户"},
            "business_profile": None,
            "crm": {
                "projects": [{"id": 3, "project_code": "P-3", "project_name": "项目", "status": "active"}],
                "tasks": [{"id": 4, "project_id": 3, "task_code": "T-4", "status": "in_progress", "updated_at": "2026-08-31T08:30:00+08:00"}],
                "followups": [{"id": 5, "task_id": 4, "customer_feedback": "已确认", "review_status": "approved", "created_at": "2026-08-31T01:00:00Z"}],
                "work_items": [],
                "approvals": [],
                "stats": {"project_total": 1, "task_open": 1},
            },
        }
        tag_profile = {
            "assignments": [{"id": 9, "tag_name": "高频配送", "category_name": "履约", "status": "effective", "evidence": "不得下发的证据"}],
            "compatibility_tags": ["重点客户"],
            "review_due_count": 1,
        }
        with (
            patch("app.api.routes.mobile_v2.get_crm_linked_customer_context", return_value=context),
            patch("app.api.routes.mobile_v2.customer_tag_profile", return_value=tag_profile),
            patch(
                "app.api.routes.mobile_v2._can",
                side_effect=lambda _db, _user, code: code in {"crm_customer_profile.view", "crm_customer_profile.submit"},
            ),
        ):
            result = mobile_v2_customer_panorama("C-11", db=db, current_user=self.user)

        self.assertEqual(result["tags"]["items"][0]["name"], "高频配送")
        self.assertNotIn("不得下发的证据", str(result))
        self.assertEqual([item["kind"] for item in result["timeline"]], ["followup", "task"])
        self.assertTrue(result["capabilities"]["edit_profile"])
        self.assertFalse(result["capabilities"]["view_tag_history"])

    def test_customer_panorama_does_not_expand_field_permissions_for_task_only_user(self):
        customer = CustomerMaster(customer_code="C-12", customer_name="权限客户", customer_tags=["敏感标签"])
        db = MagicMock()
        db.scalar.return_value = customer
        context = {
            "customer": {"customer_code": "C-12", "customer_name": "权限客户"},
            "business_profile": None,
            "crm": {
                "projects": [],
                "tasks": [{"id": 6, "project_id": 7, "task_code": "T-6", "status": "in_progress"}],
                "followups": [],
                "work_items": [],
                "approvals": [],
            },
        }
        with (
            patch("app.api.routes.mobile_v2.get_crm_linked_customer_context", return_value=context),
            patch("app.api.routes.mobile_v2.customer_tag_profile") as tag_profile,
            patch("app.api.routes.mobile_v2._can", side_effect=lambda _db, _user, code: code == "crm_task.view"),
        ):
            result = mobile_v2_customer_panorama("C-12", db=db, current_user=self.user)

        tag_profile.assert_not_called()
        self.assertEqual(result["tags"]["items"], [])
        self.assertEqual(result["tags"]["compatibility_tags"], [])
        self.assertNotIn("contact_phone", result["customer"])

    def test_customer_panorama_rejects_customer_outside_visible_context(self):
        with patch(
            "app.api.routes.mobile_v2.get_crm_linked_customer_context",
            return_value={"customer": {"customer_code": "C-404"}, "business_profile": None, "crm": {}},
        ):
            with self.assertRaises(HTTPException) as error:
                mobile_v2_customer_panorama("C-404", db=MagicMock(), current_user=self.user)
        self.assertEqual(error.exception.status_code, 404)

    def test_execution_without_permissions_returns_no_business_data(self):
        with patch("app.api.routes.mobile_v2._can", return_value=False):
            result = mobile_v2_execution(db=MagicMock(), current_user=self.user)

        self.assertEqual(result["projects"], {"items": [], "total": 0})
        self.assertEqual(result["my_tasks"], {"items": [], "total": 0})
        self.assertEqual(result["summary"]["active_projects"], 0)
        self.assertEqual(result["summary"]["my_open_tasks"], 0)
        self.assertEqual(result["capabilities"], {
            "create_project": False,
            "submit_followup": False,
            "view_approvals": False,
        })

    def test_execution_my_work_is_bound_to_current_executor_and_task_scope(self):
        db = MagicMock()
        empty = MagicMock()
        empty.all.return_value = []
        db.scalars.side_effect = [empty, empty]
        captured_statements = []

        def scoped(stmt, _db, _user):
            captured_statements.append(stmt)
            return stmt

        with (
            patch("app.api.routes.mobile_v2._can", side_effect=lambda _db, _user, code: code == "crm_task.view"),
            patch("app.api.routes.mobile_v2._count", return_value=0),
            patch("app.api.routes.mobile_v2.crm_task_scope_filter", side_effect=scoped),
        ):
            result = mobile_v2_execution(db=db, current_user=self.user)

        self.assertEqual(result["my_tasks"], {"items": [], "total": 0})
        self.assertGreaterEqual(len(captured_statements), 2)
        my_work_sql = str(captured_statements[-1].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("crm_project_customer_task.executor_user_id = 7", my_work_sql)

    def test_execution_does_not_calculate_project_task_counts_without_task_permission(self):
        project = CrmProject(id=22, project_code="P-22", project_name="仅项目可见", status="active")
        db = MagicMock()
        project_rows = MagicMock()
        project_rows.all.return_value = [project]
        db.scalars.return_value = project_rows

        with (
            patch("app.api.routes.mobile_v2._can", side_effect=lambda _db, _user, code: code == "crm_project.view"),
            patch("app.api.routes.mobile_v2._count", side_effect=[1, 1, 0]),
            patch("app.api.routes.mobile_v2._visible_project_stmt", return_value=__import__("sqlalchemy").select(CrmProject)),
            patch("app.api.routes.mobile_v2.crm_task_scope_filter") as task_scope,
        ):
            result = mobile_v2_execution(db=db, current_user=self.user)

        task_scope.assert_not_called()
        db.execute.assert_not_called()
        self.assertEqual(result["projects"]["items"][0]["task_total"], 0)
        self.assertEqual(result["summary"]["my_open_tasks"], 0)

    def test_empty_workbench_does_not_expand_permissions(self):
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        with (
            patch("app.api.routes.mobile_v2._can", return_value=False),
            patch("app.api.routes.mobile_v2._count", return_value=0),
            patch("app.api.routes.mobile_v2._visible_project_stmt") as project_stmt,
            patch("app.api.routes.mobile_v2.visible_approvals_stmt") as approval_stmt,
        ):
            from sqlalchemy import select

            project_stmt.return_value = select(CrmProject).where(CrmProject.id == -1)
            approval_stmt.return_value = select(ApprovalInstance).where(ApprovalInstance.id == -1)
            result = mobile_v2_workbench(db=db, current_user=self.user)

        self.assertEqual(result["summary"], {
            "active_projects": 0,
            "open_tasks": 0,
            "pending_approvals": 0,
            "overdue_tasks": 0,
            "open_support": 0,
        })
        self.assertEqual(result["today_queue"], {"items": [], "total": 0})
        self.assertEqual(result["shortcuts"], {
            "create_project": False,
            "view_approvals": False,
            "view_support": False,
        })

    def test_today_queue_uses_real_totals_and_priority_order(self):
        now = datetime.now(timezone.utc)
        task = CrmProjectCustomerTask(
            id=11,
            project_id=21,
            task_code="TASK-11",
            customer_code="C-11",
            customer_name_snapshot="测试客户",
            feedback_due_at=now - timedelta(hours=2),
            status="in_progress",
            is_closed=False,
        )
        approval = ApprovalInstance(
            id=31,
            approval_no="APP-31",
            approval_type="crm_project_create",
            resource_type="crm_project",
            resource_id="21",
            title="项目申请",
            status="submitted",
            priority="high",
            current_handler_user_id=self.user.id,
            submitted_at=now,
        )
        support = WorkItem(
            id=41,
            item_no="WI-41",
            source_type="crm",
            source_id="11",
            item_type="support",
            title="需要协调",
            priority="normal",
            status="open",
        )
        project = CrmProject(
            id=21,
            project_code="P-21",
            project_name="城配项目",
            status="active",
            approval_status="approved",
            due_date=date.today() - timedelta(days=1),
        )

        def scalars_result(items):
            result = MagicMock()
            result.all.return_value = items
            return result

        db = MagicMock()
        db.scalars.side_effect = [
            scalars_result([task]),
            scalars_result([approval]),
            scalars_result([support]),
            scalars_result([project]),
        ]
        db.execute.return_value.all.return_value = [(21, 2, 1)]
        allowed = {"crm_task.view", "crm_project.view", "crm_issue.view", "crm_project.create", "approval.view"}
        with (
            patch("app.api.routes.mobile_v2._can", side_effect=lambda _db, _user, code: code in allowed),
            patch("app.api.routes.mobile_v2._count", side_effect=[4, 2, 3, 1, 1, 2]),
            patch("app.api.routes.mobile_v2.crm_task_scope_filter", side_effect=lambda stmt, _db, _user: stmt),
            patch("app.api.routes.mobile_v2.crm_project_scope_filter", side_effect=lambda stmt, _db, _user: stmt),
            patch("app.api.routes.mobile_v2.work_item_scope_filter", side_effect=lambda stmt, _db, _user: stmt),
            patch("app.api.routes.mobile_v2.visible_approvals_stmt", side_effect=lambda _db, _user: __import__("sqlalchemy").select(ApprovalInstance)),
        ):
            result = mobile_v2_workbench(db=db, current_user=self.user)

        self.assertEqual(result["today_queue"]["total"], 5)
        self.assertEqual([item["kind"] for item in result["today_queue"]["items"]], ["task_overdue", "approval", "support"])
        self.assertEqual(result["projects"]["items"][0]["open_tasks"], 1)
        self.assertTrue(result["projects"]["items"][0]["overdue"])


if __name__ == "__main__":
    unittest.main()
