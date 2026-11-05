from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.mobile import router as mobile_router
from app.api.routes.mobile_round4 import router as mobile_round4_router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import ApprovalInstance, CrmLead, MobileOperationLog, Permission, Role, RolePermission, User
from app.services.approval_service import create_approval_instance


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class MobileLegacyLeadWrapperContainmentTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed_identity()
        self.lead_approval = self._lead_approval("private", self.lead_handler)
        self.approve_approval = self._lead_approval("approve", self.lead_handler)
        self.reject_approval = self._lead_approval("reject", self.lead_handler)
        self.supplement_approval = self._lead_approval("supplement", self.lead_handler)
        self.out_of_scope_lead_approval = self._lead_approval("other-handler", self.generic_approver)
        self.generic_approval = create_approval_instance(
            self.db,
            approval_type="crm_project_extension",
            resource_type="crm_project",
            resource_id="project-1",
            title="Generic approval",
            description=None,
            applicant=self.no_lead_user,
            current_handler_user_id=self.generic_approver.id,
            priority="normal",
            payload_json={"project_name": "Generic approval"},
            submit=True,
        )
        self.db.add_all([
            MobileOperationLog(
                user_id=self.no_lead_user.id,
                device_id="device-1",
                client_operation_id="stored-lead-operation",
                action_type="crm_lead_followup_create",
                payload_hash="a" * 64,
                status="applied",
                resource_type="crm_lead_followup",
                resource_id="9",
                request_json={"content": "private lead follow-up"},
                result_json={"contact_phone": "13800138000", "content": "private lead follow-up"},
            ),
            MobileOperationLog(
                user_id=self.no_lead_user.id,
                device_id="device-1",
                client_operation_id="stored-generic-operation",
                action_type="followup.create",
                payload_hash="b" * 64,
                status="applied",
                resource_type="approval_instance",
                resource_id="10",
                result_json={"approval_id": 10},
            ),
        ])
        self.db.commit()

        app = FastAPI()
        app.include_router(mobile_router, prefix="/api/v1")
        app.include_router(mobile_round4_router, prefix="/api/v1")

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()

    def _seed_identity(self):
        codes = ("approval.view", "approval.approve", "crm_lead.approve")
        permissions = {
            code: Permission(permission_code=code, permission_name=code, resource_type="approval", action_type="view")
            for code in codes
        }
        roles = {code: Role(role_code=code, role_name=code) for code in ("no_lead", "lead_handler", "generic_approver")}
        self.no_lead_user = User(username="no-lead", password_hash="hash", real_name="No lead", role="no_lead", status="active", is_active=True)
        self.lead_handler = User(username="lead-handler", password_hash="hash", real_name="Lead handler", role="lead_handler", status="active", is_active=True)
        self.generic_approver = User(username="generic-approver", password_hash="hash", real_name="Generic approver", role="generic_approver", status="active", is_active=True)
        self.db.add_all([*permissions.values(), *roles.values(), self.no_lead_user, self.lead_handler, self.generic_approver])
        self.db.flush()
        self.db.add_all([
            RolePermission(role_id=roles["no_lead"].id, permission_id=permissions["approval.view"].id),
            RolePermission(role_id=roles["lead_handler"].id, permission_id=permissions["crm_lead.approve"].id),
            RolePermission(role_id=roles["generic_approver"].id, permission_id=permissions["approval.approve"].id),
        ])
        self.db.commit()

    def _lead_approval(self, suffix: str, handler: User) -> ApprovalInstance:
        contact_phone = {
            "private": "13800138000",
            "approve": "13800138001",
            "reject": "13800138002",
            "supplement": "13800138003",
            "other-handler": "13800138004",
        }[suffix]
        lead = CrmLead(
            lead_no=f"LEAD-{suffix.upper()}",
            lead_name=f"Private lead {suffix}",
            normalized_name=f"private lead {suffix}",
            company_name="Private company",
            contact_name="Jane Private",
            contact_phone=contact_phone,
            normalized_phone=contact_phone,
            status="conversion_pending",
            owner_user_id=self.no_lead_user.id,
            assigned_user_id=self.no_lead_user.id,
            created_by_user_id=self.no_lead_user.id,
            updated_by_user_id=self.no_lead_user.id,
        )
        self.db.add(lead)
        self.db.flush()
        return create_approval_instance(
            self.db,
            approval_type="crm_lead_convert",
            resource_type="crm_lead",
            resource_id=str(lead.id),
            title="Convert private lead",
            description=None,
            applicant=self.no_lead_user,
            current_handler_user_id=handler.id,
            priority="normal",
            payload_json={
                "lead_id": lead.id,
                "lead": {"id": lead.id, "lead_no": lead.lead_no, "contact_phone": lead.contact_phone, "internal_secret": "do-not-return"},
                "before": {"id": lead.id, "status": "qualified", "normalized_phone": lead.normalized_phone, "internal_secret": "do-not-return"},
                "after": {"status": "converted", "internal_secret": "do-not-return"},
            },
            submit=True,
        )

    @staticmethod
    def _headers(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.username)}"}

    def test_no_lead_user_cannot_list_or_read_private_conversion(self):
        page = self.client.get("/api/v1/mobile/approvals?mode=mine", headers=self._headers(self.no_lead_user))
        detail = self.client.get(f"/api/v1/mobile/approvals/{self.lead_approval.id}", headers=self._headers(self.no_lead_user))

        self.assertEqual(page.status_code, 200)
        self.assertNotIn(self.lead_approval.id, [item["id"] for item in page.json()["items"]])
        self.assertNotIn("13800138000", page.text)
        self.assertEqual(detail.status_code, 404)
        self.assertNotIn("13800138000", detail.text)

    def test_lead_handler_gets_sanitized_visibility_and_shared_actions(self):
        page = self.client.get("/api/v1/mobile/approvals", headers=self._headers(self.lead_handler))
        detail = self.client.get(f"/api/v1/mobile/approvals/{self.lead_approval.id}", headers=self._headers(self.lead_handler))

        self.assertEqual(page.status_code, 200)
        self.assertIn(self.lead_approval.id, [item["id"] for item in page.json()["items"]])
        self.assertEqual(detail.status_code, 200)
        for response in (page, detail):
            self.assertIn("138****8000", response.text)
            self.assertNotIn("13800138000", response.text)
            self.assertNotIn("normalized_phone", response.text)
            self.assertNotIn("internal_secret", response.text)

        for action, approval, expected_status in (
            ("approve", self.approve_approval, "completed"),
            ("reject", self.reject_approval, "rejected"),
            ("supplement_request", self.supplement_approval, "need_supplement"),
        ):
            with self.subTest(action=action):
                response = self.client.post(
                    f"/api/v1/mobile/approvals/{approval.id}/actions?action={action}",
                    headers=self._headers(self.lead_handler),
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.db.get(ApprovalInstance, approval.id).status, expected_status)
                self.assertNotIn("13800138000", response.text)
                self.assertNotIn("internal_secret", response.text)

    def test_lead_only_action_scope_hides_existing_and_missing_ids_for_every_action(self):
        for action in ("approve", "reject", "supplement_request"):
            with self.subTest(action=action):
                existing = self.client.post(
                    f"/api/v1/mobile/approvals/{self.out_of_scope_lead_approval.id}/actions?action={action}",
                    headers=self._headers(self.lead_handler),
                )
                missing = self.client.post(
                    f"/api/v1/mobile/approvals/999999/actions?action={action}",
                    headers=self._headers(self.lead_handler),
                )
                self.assertEqual(existing.status_code, 403)
                self.assertEqual(missing.status_code, 403)
                self.assertEqual(existing.json(), missing.json())

    def test_generic_approver_retains_generic_actions_but_not_private_lead_access(self):
        pending_page = self.client.get(
            "/api/v1/mobile/approvals?mode=to_handle",
            headers=self._headers(self.generic_approver),
        )
        lead_detail = self.client.get(
            f"/api/v1/mobile/approvals/{self.lead_approval.id}",
            headers=self._headers(self.generic_approver),
        )
        lead_action = self.client.post(
            f"/api/v1/mobile/approvals/{self.lead_approval.id}/actions?action=reject",
            headers=self._headers(self.generic_approver),
        )
        generic_action = self.client.post(
            f"/api/v1/mobile/approvals/{self.generic_approval.id}/actions?action=reject",
            headers=self._headers(self.generic_approver),
        )

        self.assertEqual(pending_page.status_code, 200)
        self.assertIn(self.generic_approval.id, [item["id"] for item in pending_page.json()["items"]])
        self.assertNotIn(self.lead_approval.id, [item["id"] for item in pending_page.json()["items"]])
        self.assertEqual(lead_detail.status_code, 404)
        self.assertEqual(lead_action.status_code, 403)
        self.assertEqual(generic_action.status_code, 200)
        self.assertEqual(self.db.get(ApprovalInstance, self.generic_approval.id).status, "rejected")

    def test_pre_disable_lead_operations_are_omitted_or_not_found_without_pii(self):
        for lead_pool, lead_offline in ((False, True), (True, False)):
            with self.subTest(lead_pool=lead_pool, lead_offline=lead_offline):
                with (
                    patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_pool", lead_pool),
                    patch("app.api.routes.mobile_round4.settings.mobile_feature_lead_offline", lead_offline),
                ):
                    status = self.client.get("/api/v1/mobile/sync/status", headers=self._headers(self.no_lead_user))
                    summary = self.client.get("/api/v1/mobile/operations/summary", headers=self._headers(self.no_lead_user))
                    hidden = self.client.get("/api/v1/mobile/operations/stored-lead-operation", headers=self._headers(self.no_lead_user))
                    generic = self.client.get("/api/v1/mobile/operations/stored-generic-operation", headers=self._headers(self.no_lead_user))

                self.assertEqual(status.status_code, 200)
                self.assertEqual(summary.status_code, 200)
                self.assertEqual(hidden.status_code, 404)
                self.assertEqual(generic.status_code, 200)
                self.assertEqual(len(status.json()["latest"]), 1)
                self.assertEqual(status.json()["counts"], {"applied": 1})
                self.assertEqual(summary.json()["counts"], {"applied": 1})
                self.assertNotIn("private lead follow-up", status.text)
                self.assertNotIn("13800138000", status.text)
                self.assertNotIn("private lead follow-up", hidden.text)
                self.assertNotIn("13800138000", hidden.text)


if __name__ == "__main__":
    unittest.main()
