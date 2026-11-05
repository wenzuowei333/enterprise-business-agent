import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import Request
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.mobile import mobile_bootstrap
from app.api.routes.mobile_round4 import _process_operation, mobile_sync_pull
from app.api.routes.mobile_tools import mobile_notifications
from app.core.config import settings
from app.core.database import Base
from app.main import create_app
from app.models import CrmLead, CrmLeadFollowup, MobileOperationLog, Permission, Role, RolePermission, User
from app.schemas.mobile import MobileSyncOperation
from app.services.mobile_sync_service import current_mobile_scope_revision


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class MobileRound6ApiTest(unittest.TestCase):
    def setUp(self):
        self._lead_pool_flag = settings.mobile_feature_lead_pool
        self._lead_offline_flag = settings.mobile_feature_lead_offline
        settings.mobile_feature_lead_pool = True
        settings.mobile_feature_lead_offline = True
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = self._seed_user()
        self.request = Request({"type": "http", "method": "POST", "path": "/mobile/sync/operations", "headers": []})

    def tearDown(self):
        settings.mobile_feature_lead_pool = self._lead_pool_flag
        settings.mobile_feature_lead_offline = self._lead_offline_flag
        self.db.close()

    def _seed_user(self):
        role = Role(role_code="salesperson", role_name="业务员")
        permissions = [
            Permission(permission_code=code, permission_name=code, resource_type="crm_lead", action_type="view")
            for code in ("crm_lead.view", "crm_lead.create", "crm_lead.edit", "crm_lead.assign", "crm_lead.convert")
        ]
        user = User(
            username="salesperson",
            password_hash="hash",
            real_name="一线业务员",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.db.add_all([role, *permissions, user])
        self.db.flush()
        self.db.add_all([RolePermission(role_id=role.id, permission_id=permission.id) for permission in permissions])
        self.db.commit()
        return user

    def _lead(self, *, status="active", next_followup_at=None):
        lead = CrmLead(
            lead_no=f"LEAD-{self.db.scalar(select(func.count(CrmLead.id))) + 1}",
            lead_name="苏州恒力纺织",
            normalized_name="苏州恒力纺织",
            company_name="苏州恒力纺织有限公司",
            contact_phone="13800138000",
            normalized_phone="13800138000",
            status=status,
            owner_user_id=self.user.id,
            assigned_user_id=self.user.id,
            created_by_user_id=self.user.id,
            updated_by_user_id=self.user.id,
            next_followup_at=next_followup_at,
        )
        self.db.add(lead)
        self.db.commit()
        return lead

    def test_round6_routes_are_registered(self):
        paths = set(create_app().openapi()["paths"])
        expected = {
            "/api/v1/mobile/leads",
            "/api/v1/mobile/leads/duplicate-check",
            "/api/v1/mobile/leads/{lead_id}",
            "/api/v1/mobile/leads/{lead_id}/assign",
            "/api/v1/mobile/leads/{lead_id}/followups",
            "/api/v1/mobile/leads/{lead_id}/conversion-approval-draft",
            "/api/v1/mobile/leads/{lead_id}/project-prefill",
            "/api/v1/mobile/leads/analytics",
        }
        self.assertTrue(expected.issubset(paths), expected - paths)

    def test_bootstrap_exposes_disabled_round6_feature_flags(self):
        with (
            patch("app.api.routes.mobile.settings.mobile_feature_lead_pool", False),
            patch("app.api.routes.mobile.settings.mobile_feature_lead_offline", False),
            patch("app.api.routes.mobile.get_final_permission_codes", return_value=[]),
            patch("app.api.routes.mobile._visible_nav", return_value=[]),
            patch("app.api.routes.mobile._mobile_scope_revision", return_value="scope-round6"),
        ):
            payload = mobile_bootstrap(db=object(), current_user=self.user)

        flags = payload["app"]["feature_flags"]
        self.assertEqual(
            {key: flags[key] for key in ("lead_pool", "lead_ocr", "lead_offline", "lead_conversion", "lead_product_intent", "lead_analytics")},
            {
                "lead_pool": False,
                "lead_ocr": False,
                "lead_offline": False,
                "lead_conversion": False,
                "lead_product_intent": False,
                "lead_analytics": False,
            },
        )

    def test_lead_scope_revision_and_full_sync_are_authoritative(self):
        before = current_mobile_scope_revision(self.db, self.user, ["crm_lead.view"])
        lead = self._lead()
        after = current_mobile_scope_revision(self.db, self.user, ["crm_lead.view"])

        payload = mobile_sync_pull(cursor=None, client_scope_revision=None, device_id=None, db=self.db, current_user=self.user)

        self.assertNotEqual(before, after)
        self.assertTrue(payload["full_snapshot"])
        self.assertEqual([item["id"] for item in payload["upserts"]["leads"]], [lead.id])
        self.assertEqual(payload["deletions"]["leads"], [])
        self.assertEqual(payload["authoritative_keys"]["leads"], [str(lead.id)])

    def test_outbox_applies_existing_server_lead_followup_once(self):
        lead = self._lead()
        operation = MobileSyncOperation(
            client_operation_id="lead-followup-0001",
            device_id="device-1",
            action_type="crm_lead_followup_create",
            resource_type="crm_lead",
            resource_id=str(lead.id),
            payload={"content": "客户确认样品需求", "method": "phone"},
        )

        first = _process_operation(operation, request=self.request, db=self.db, current_user=self.user)
        second = _process_operation(operation, request=self.request, db=self.db, current_user=self.user)

        self.assertEqual(first.status, "applied")
        self.assertEqual(second.status, "applied")
        self.assertEqual(first.resource_type, "crm_lead_followup")
        self.assertEqual(self.db.scalar(select(func.count(CrmLeadFollowup.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(MobileOperationLog.id))), 1)

    def test_outbox_rejects_followup_without_an_existing_server_lead(self):
        operation = MobileSyncOperation(
            client_operation_id="lead-followup-0002",
            device_id="device-1",
            action_type="crm_lead_followup_create",
            resource_type="crm_lead",
            resource_id="99999",
            payload={"content": "不能为离线草稿自动创建线索"},
        )

        result = _process_operation(operation, request=self.request, db=self.db, current_user=self.user)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error["code"], "http_404")
        self.assertEqual(self.db.scalar(select(func.count(CrmLeadFollowup.id))), 0)

    def test_lead_reminder_has_stable_identity_and_clears_after_followup_or_terminal_status(self):
        due_at = datetime.now(timezone.utc) - timedelta(hours=1)
        lead = self._lead(next_followup_at=due_at)

        with patch("app.api.routes.mobile_tools.settings.mobile_feature_lead_pool", True):
            first = mobile_notifications(db=self.db, current_user=self.user)
            second = mobile_notifications(db=self.db, current_user=self.user)
            reminders = [item for item in first["items"] if item["source_type"] == "crm_lead"]

            self.assertEqual(len(reminders), 1)
            self.assertEqual(reminders[0]["notification_id"], [item for item in second["items"] if item["source_type"] == "crm_lead"][0]["notification_id"])
            self.assertEqual(reminders[0]["action_path"], f"/leads/{lead.id}")

            operation = MobileSyncOperation(
                client_operation_id="lead-followup-0003",
                device_id="device-1",
                action_type="crm_lead_followup_create",
                resource_type="crm_lead",
                resource_id=str(lead.id),
                payload={"content": "本次跟进已完成"},
            )
            _process_operation(operation, request=self.request, db=self.db, current_user=self.user)
            self.assertFalse([item for item in mobile_notifications(db=self.db, current_user=self.user)["items"] if item["source_type"] == "crm_lead"])

            lead.next_followup_at = due_at
            lead.status = "closed"
            self.db.commit()
            self.assertFalse([item for item in mobile_notifications(db=self.db, current_user=self.user)["items"] if item["source_type"] == "crm_lead"])

    def test_disabled_lead_pool_does_not_query_or_emit_reminders(self):
        db = unittest.mock.MagicMock()
        center = unittest.mock.MagicMock(items=[], summary=unittest.mock.MagicMock(model_dump=lambda: {}), generated_at=datetime.now(timezone.utc))
        with (
            patch("app.api.routes.mobile_tools.settings.mobile_feature_lead_pool", False),
            patch("app.api.routes.mobile_tools.crm_report_notifications", return_value=center),
            patch("app.api.routes.mobile_tools._lead_reminders", return_value=[]) as lead_reminders,
        ):
            result = mobile_notifications(db=db, current_user=self.user)

        lead_reminders.assert_not_called()
        self.assertEqual(result["summary"]["lead_reminder"], 0)
        self.assertFalse([item for item in result["items"] if item.get("source_type") == "crm_lead"])


if __name__ == "__main__":
    unittest.main()
