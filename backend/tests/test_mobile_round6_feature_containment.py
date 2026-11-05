import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Barrier
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.mobile_round4 import _process_operation, mobile_sync_pull
from app.api.routes.mobile_round4 import router as mobile_round4_router
from app.api.routes.mobile_round6 import router as mobile_round6_router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import CrmLead, CrmLeadFollowup, MobileOperationLog, Permission, Role, RolePermission, User
from app.schemas.mobile import MobileSyncOperation


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class MobileRound6FeatureContainmentTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = self._seed_user()
        self.lead = self._lead()
        self.request = Request({"type": "http", "method": "POST", "path": "/mobile/sync/operations", "headers": []})

        app = FastAPI()
        app.include_router(mobile_round6_router, prefix="/api/v1/mobile")
        app.include_router(mobile_round4_router, prefix="/api/v1")

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()

    def _seed_user(self):
        role = Role(role_code="salesperson", role_name="Sales")
        permissions = [
            Permission(permission_code=code, permission_name=code, resource_type="crm_lead", action_type="view")
            for code in ("crm_lead.view", "crm_lead.create", "crm_lead.edit", "crm_lead.assign", "crm_lead.convert")
        ]
        user = User(
            username="salesperson",
            password_hash="hash",
            real_name="Private Lead Owner",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.db.add_all([role, *permissions, user])
        self.db.flush()
        self.db.add_all([RolePermission(role_id=role.id, permission_id=permission.id) for permission in permissions])
        self.db.commit()
        return user

    def _lead(self):
        lead = CrmLead(
            lead_no="LEAD-CONTAINMENT-001",
            lead_name="Private Lead Name",
            normalized_name="Private Lead Name",
            company_name="Private Lead Company",
            contact_phone="13800138000",
            normalized_phone="13800138000",
            status="active",
            owner_user_id=self.user.id,
            assigned_user_id=self.user.id,
            created_by_user_id=self.user.id,
            updated_by_user_id=self.user.id,
        )
        self.db.add(lead)
        self.db.commit()
        return lead

    def _headers(self):
        return {"Authorization": f"Bearer {create_access_token(self.user.username)}"}

    def _operation(self, client_operation_id="lead-offline-operation-001"):
        return MobileSyncOperation(
            client_operation_id=client_operation_id,
            device_id="device-1",
            action_type="crm_lead_followup_create",
            resource_type="crm_lead",
            resource_id=str(self.lead.id),
            payload={"content": "Private follow-up payload", "method": "phone"},
        )

    def test_lead_pool_off_makes_every_mobile_lead_endpoint_unavailable_without_pii(self):
        calls = [
            ("get", "/api/v1/mobile/leads/duplicate-check", None),
            ("get", "/api/v1/mobile/leads/summary", None),
            ("get", "/api/v1/mobile/leads/dimensions", None),
            ("get", "/api/v1/mobile/leads/analytics", None),
            ("get", "/api/v1/mobile/leads", None),
            ("post", "/api/v1/mobile/leads", {"lead_name": "Attempted lead"}),
            ("get", f"/api/v1/mobile/leads/{self.lead.id}", None),
            ("patch", f"/api/v1/mobile/leads/{self.lead.id}", {"lead_name": "Attempted change"}),
            ("delete", f"/api/v1/mobile/leads/{self.lead.id}", None),
            ("post", f"/api/v1/mobile/leads/{self.lead.id}/assign", {"assigned_user_id": self.user.id}),
            ("post", f"/api/v1/mobile/leads/{self.lead.id}/followups", {"content": "Attempted follow-up"}),
            ("post", f"/api/v1/mobile/leads/{self.lead.id}/conversion-approval-draft", {}),
            ("get", f"/api/v1/mobile/leads/{self.lead.id}/project-prefill", None),
        ]

        with patch("app.api.routes.mobile_round6.settings.mobile_feature_lead_pool", False):
            for method, path, payload in calls:
                response = self.client.request(method.upper(), path, headers=self._headers(), json=payload)
                self.assertEqual(response.status_code, 404, path)
                self.assertNotIn("Private Lead Name", response.text)
                self.assertNotIn("13800138000", response.text)

    def test_capability_flags_reject_conversion_analytics_and_product_intent_writes(self):
        with patch("app.api.routes.mobile_round6.settings.mobile_feature_lead_pool", True):
            with patch("app.api.routes.mobile_round6.settings.mobile_feature_lead_conversion", False):
                response = self.client.post(
                    f"/api/v1/mobile/leads/{self.lead.id}/conversion-approval-draft",
                    headers=self._headers(),
                    json={},
                )
                self.assertEqual(response.status_code, 404)

            with patch("app.api.routes.mobile_round6.settings.mobile_feature_lead_analytics", False):
                response = self.client.get("/api/v1/mobile/leads/analytics", headers=self._headers())
                self.assertEqual(response.status_code, 404)

            with patch("app.api.routes.mobile_round6.settings.mobile_feature_lead_product_intent", False):
                response = self.client.post(
                    "/api/v1/mobile/leads",
                    headers=self._headers(),
                    json={"lead_name": "Blocked product intent", "product_intents": [{"product_name": "Private SKU"}]},
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(self.db.scalar(select(func.count(CrmLead.id))), 1)

    def test_sync_purges_leads_when_pool_is_disabled_without_emitting_pii(self):
        with patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_pool", True):
            enabled = mobile_sync_pull(cursor=None, client_scope_revision=None, device_id=None, db=self.db, current_user=self.user)

        with patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_pool", False):
            disabled = mobile_sync_pull(
                cursor=enabled["next_cursor"],
                client_scope_revision=enabled["scope_revision"],
                device_id=None,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual([item["id"] for item in enabled["upserts"]["leads"]], [self.lead.id])
        self.assertTrue(disabled["full_snapshot"])
        self.assertNotEqual(disabled["scope_revision"], enabled["scope_revision"])
        self.assertEqual(disabled["upserts"]["leads"], [])
        self.assertEqual(disabled["deletions"]["leads"], [])
        self.assertEqual(disabled["authoritative_keys"]["leads"], [])
        self.assertNotIn("Private Lead Name", str(disabled))
        self.assertNotIn("13800138000", str(disabled))

    def test_lead_outbox_requires_both_pool_and_offline_flags_before_payload_parsing_or_log_write(self):
        for lead_pool, lead_offline in ((False, True), (True, False)):
            with self.subTest(lead_pool=lead_pool, lead_offline=lead_offline):
                with (
                    patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_pool", lead_pool),
                    patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_offline", lead_offline),
                    patch("app.api.routes.mobile_round4.CrmLeadFollowupCreate.model_validate") as validate_payload,
                ):
                    with self.assertRaises(HTTPException) as error:
                        _process_operation(self._operation(), request=self.request, db=self.db, current_user=self.user)

                self.assertEqual(error.exception.status_code, 404)
                validate_payload.assert_not_called()
                self.assertEqual(self.db.scalar(select(func.count(MobileOperationLog.id))), 0)
                self.assertEqual(self.db.scalar(select(func.count(CrmLeadFollowup.id))), 0)

    def test_processing_lead_followup_recovers_after_final_commit_crash_without_duplicate_business_record(self):
        original_commit = self.db.commit
        commit_count = 0

        def crash_before_operation_result_commit():
            nonlocal commit_count
            commit_count += 1
            if commit_count == 3:
                raise SystemExit("simulated process crash")
            original_commit()

        operation = self._operation("lead-offline-operation-crash")
        with (
            patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_pool", True),
            patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_offline", True),
            patch.object(self.db, "commit", side_effect=crash_before_operation_result_commit),
        ):
            with self.assertRaises(SystemExit):
                _process_operation(operation, request=self.request, db=self.db, current_user=self.user)

        self.db.rollback()
        stranded = self.db.scalar(select(MobileOperationLog).where(MobileOperationLog.client_operation_id == operation.client_operation_id))
        self.assertEqual(stranded.status, "processing")
        self.assertEqual(self.db.scalar(select(func.count(CrmLeadFollowup.id))), 1)

        with (
            patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_pool", True),
            patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_offline", True),
        ):
            recovered = _process_operation(operation, request=self.request, db=self.db, current_user=self.user)
            repeated = _process_operation(operation, request=self.request, db=self.db, current_user=self.user)

        self.assertEqual(recovered.status, "applied")
        self.assertEqual(repeated.status, "applied")
        self.assertEqual(self.db.scalar(select(func.count(CrmLeadFollowup.id))), 1)

    def test_concurrent_and_repeated_lead_followup_operations_converge_to_one_business_record(self):
        with NamedTemporaryFile(suffix=".sqlite", delete=False) as database_file:
            database_path = Path(database_file.name)
        engine = create_engine(
            f"sqlite+pysqlite:///{database_path}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        try:
            Base.metadata.create_all(engine)
            seed_db = Session(engine)
            role = Role(role_code="salesperson", role_name="Sales")
            permission = Permission(
                permission_code="crm_lead.edit",
                permission_name="crm_lead.edit",
                resource_type="crm_lead",
                action_type="edit",
            )
            user = User(username="concurrent-sales", password_hash="hash", real_name="Sales", role="salesperson", status="active", is_active=True)
            seed_db.add_all([role, permission, user])
            seed_db.flush()
            seed_db.add(RolePermission(role_id=role.id, permission_id=permission.id))
            lead = CrmLead(
                lead_no="LEAD-CONCURRENT-001",
                lead_name="Concurrent Lead",
                normalized_name="Concurrent Lead",
                status="active",
                owner_user_id=user.id,
                assigned_user_id=user.id,
                created_by_user_id=user.id,
                updated_by_user_id=user.id,
            )
            seed_db.add(lead)
            seed_db.commit()
            operation = MobileSyncOperation(
                client_operation_id="lead-offline-operation-concurrent",
                device_id="concurrent-device",
                action_type="crm_lead_followup_create",
                resource_type="crm_lead",
                resource_id=str(lead.id),
                payload={"content": "One concurrent follow-up"},
            )
            barrier = Barrier(2)

            def submit_once():
                db = Session(engine)
                try:
                    concurrent_user = db.scalar(select(User).where(User.username == "concurrent-sales"))
                    barrier.wait(timeout=5)
                    return _process_operation(operation, request=self.request, db=db, current_user=concurrent_user).status
                finally:
                    db.close()

            with (
                patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_pool", True),
                patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_offline", True),
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    statuses = list(executor.map(lambda _unused: submit_once(), range(2)))

                verify_db = Session(engine)
                try:
                    verify_user = verify_db.scalar(select(User).where(User.username == "concurrent-sales"))
                    repeated = _process_operation(operation, request=self.request, db=verify_db, current_user=verify_user)
                    self.assertTrue(set(statuses).issubset({"applied", "retryable_error"}))
                    self.assertEqual(repeated.status, "applied")
                    self.assertEqual(verify_db.scalar(select(func.count(CrmLeadFollowup.id))), 1)
                    self.assertEqual(verify_db.scalar(select(func.count(MobileOperationLog.id))), 1)
                finally:
                    verify_db.close()
                    seed_db.close()
        finally:
            engine.dispose()
            database_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
