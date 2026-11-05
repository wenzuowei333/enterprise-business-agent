import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.mobile_round4 import (
    _process_operation,
    mobile_scope_revision,
    normalize_mobile_operation_payload,
)
from app.api.routes.mobile import mobile_bootstrap
from app.main import create_app
from app.models import MobileOperationLog, User
from app.schemas.mobile import MobileSyncOperation


class MobileRound4ApiTest(unittest.TestCase):
    def setUp(self):
        self.user = User(
            id=7,
            username="sales",
            password_hash="hash",
            real_name="一线业务员",
            role="salesperson",
            status="active",
            is_active=True,
        )

    def test_round4_routes_are_registered(self):
        paths = set(create_app().openapi()["paths"])
        expected = {
            "/api/v1/mobile/sync/pull",
            "/api/v1/mobile/sync/operations",
            "/api/v1/mobile/sync/status",
            "/api/v1/mobile/devices",
            "/api/v1/mobile/devices/{session_id}",
            "/api/v1/mobile/operations/{client_operation_id}",
            "/api/v1/mobile/operations/summary",
            "/api/v1/mobile/admin/operations/overview",
            "/api/v1/mobile/admin/devices",
            "/api/v1/mobile/admin/devices/{session_id}",
        }
        self.assertTrue(expected.issubset(paths), expected - paths)

    def test_scope_revision_is_stable_and_changes_with_scope(self):
        first = mobile_scope_revision(
            user_id=7,
            role="salesperson",
            permissions=["crm_task.view", "crm_followup.submit"],
            resource_keys=["task:1", "task:2"],
        )
        reordered = mobile_scope_revision(
            user_id=7,
            role="salesperson",
            permissions=["crm_followup.submit", "crm_task.view"],
            resource_keys=["task:2", "task:1"],
        )
        changed = mobile_scope_revision(
            user_id=7,
            role="salesperson",
            permissions=["crm_task.view", "crm_followup.submit"],
            resource_keys=["task:1"],
        )
        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)

    def test_operation_payload_normalization_is_deterministic(self):
        first = normalize_mobile_operation_payload({"b": 2, "a": {"d": 4, "c": 3}})
        second = normalize_mobile_operation_payload({"a": {"c": 3, "d": 4}, "b": 2})
        self.assertEqual(first, second)

    def test_bootstrap_exposes_round4_update_and_scope_contract(self):
        with (
            patch("app.api.routes.mobile.get_final_permission_codes", return_value=["crm_task.view"]),
            patch("app.api.routes.mobile._visible_nav", return_value=[]),
            patch("app.api.routes.mobile._mobile_scope_revision", return_value="scope-abc"),
        ):
            payload = mobile_bootstrap(db=object(), current_user=self.user)

        self.assertEqual(payload["scope_revision"], "scope-abc")
        self.assertEqual(payload["app"]["latest_version_code"], 7)
        self.assertEqual(payload["app"]["minimum_supported_version_code"], 1)
        self.assertTrue(payload["app"]["apk_sha256"])
        self.assertIn(payload["app"]["update_mode"], {"optional", "required"})
        self.assertIn("offline_read", payload["app"]["feature_flags"])
        self.assertIn("in_app_feedback", payload["app"]["feature_flags"])

    def test_same_operation_is_applied_only_once(self):
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        User.__table__.create(engine)
        MobileOperationLog.__table__.create(engine)
        db = Session(engine)
        user = User(
            username="sales",
            password_hash="hash",
            real_name="业务员",
            role="salesperson",
            status="active",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        operation = MobileSyncOperation(
            client_operation_id="operation-0001",
            device_id="device-1",
            action_type="followup.create",
            payload={"followup": {"project_id": 1, "task_id": 2}},
        )
        request = Request({"type": "http", "method": "POST", "path": "/mobile/sync/operations", "headers": []})

        with patch(
            "app.api.routes.mobile_round4._apply_operation",
            return_value=("approval_instance", "88", {"approval_id": 88}),
        ) as apply_operation:
            first = _process_operation(operation, request=request, db=db, current_user=user)
            second = _process_operation(operation, request=request, db=db, current_user=user)

        self.assertEqual(first.status, "applied")
        self.assertEqual(second.status, "applied")
        self.assertEqual(first.resource_id, "88")
        self.assertEqual(apply_operation.call_count, 1)
        self.assertEqual(db.scalar(select(func.count(MobileOperationLog.id))), 1)
        db.close()

    def test_reusing_operation_id_with_other_payload_is_rejected(self):
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        User.__table__.create(engine)
        MobileOperationLog.__table__.create(engine)
        db = Session(engine)
        user = User(
            username="sales",
            password_hash="hash",
            real_name="业务员",
            role="salesperson",
            status="active",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        request = Request({"type": "http", "method": "POST", "path": "/mobile/sync/operations", "headers": []})
        first = MobileSyncOperation(
            client_operation_id="operation-0002",
            device_id="device-1",
            action_type="followup.create",
            payload={"followup": {"project_id": 1, "task_id": 2}},
        )
        changed = first.model_copy(update={"payload": {"followup": {"project_id": 1, "task_id": 3}}})
        with patch(
            "app.api.routes.mobile_round4._apply_operation",
            return_value=("approval_instance", "99", {"approval_id": 99}),
        ):
            _process_operation(first, request=request, db=db, current_user=user)
            with self.assertRaises(HTTPException) as error:
                _process_operation(changed, request=request, db=db, current_user=user)

        self.assertEqual(error.exception.status_code, 409)
        db.close()


if __name__ == "__main__":
    unittest.main()
