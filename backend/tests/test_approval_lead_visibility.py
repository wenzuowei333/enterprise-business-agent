import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.approvals import router as approvals_router
from app.api.routes.crm_reports import router as crm_reports_router
from app.api.routes.mobile import router as mobile_router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import ApprovalEvent, ApprovalInstance, CrmLead, DataScopeRule, Permission, Role, RolePermission, User
from app.services.approval_service import create_approval_instance


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ApprovalLeadVisibilityTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed_identity()
        self.lead = self._lead()
        self.lead_approval = self._lead_conversion_approval()
        self.generic_approval = create_approval_instance(
            self.db,
            approval_type="crm_project_extension",
            resource_type="crm_project",
            resource_id="project-1",
            title="Generic approval",
            description=None,
            applicant=self.applicant,
            current_handler_user_id=self.approval_only.id,
            priority="normal",
            payload_json={"project_name": "Visible generic approval"},
            submit=True,
        )
        self.db.commit()

        app = FastAPI()
        app.include_router(approvals_router, prefix="/api/v1")
        app.include_router(crm_reports_router, prefix="/api/v1")
        app.include_router(mobile_router, prefix="/api/v1")

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()

    def _seed_identity(self):
        permission_codes = (
            "approval.view",
            "approval.approve",
            "crm_lead.view",
            "crm_lead.approve",
            "customer_tag.review",
        )
        permissions = {
            code: Permission(permission_code=code, permission_name=code, resource_type="approval", action_type="view")
            for code in permission_codes
        }
        roles = {
            code: Role(role_code=code, role_name=code)
            for code in (
                "applicant",
                "handler_only",
                "outsider",
                "approval_only",
                "generic_approver",
                "lead_viewer",
                "lead_scope_viewer",
                "lead_approver",
                "tag_reviewer",
            )
        }
        self.applicant = User(username="applicant", password_hash="hash", real_name="Applicant", role="applicant", status="active", is_active=True)
        self.handler_only = User(username="handler-only", password_hash="hash", real_name="Handler only", role="handler_only", status="active", is_active=True)
        self.outsider = User(username="outsider", password_hash="hash", real_name="Outsider", role="outsider", status="active", is_active=True)
        self.approval_only = User(username="approval-only", password_hash="hash", real_name="Approval only", role="approval_only", status="active", is_active=True)
        self.generic_approver = User(username="generic-approver", password_hash="hash", real_name="Generic approver", role="generic_approver", status="active", is_active=True)
        self.lead_viewer = User(username="lead-viewer", password_hash="hash", real_name="Lead viewer", role="lead_viewer", status="active", is_active=True)
        self.lead_scope_viewer = User(username="lead-scope-viewer", password_hash="hash", real_name="Lead scope viewer", role="lead_scope_viewer", status="active", is_active=True)
        self.lead_approver = User(username="lead-approver", password_hash="hash", real_name="Lead approver", role="lead_approver", status="active", is_active=True)
        self.tag_reviewer = User(username="tag-reviewer", password_hash="hash", real_name="Tag reviewer", role="tag_reviewer", status="active", is_active=True)
        self.db.add_all([
            *roles.values(),
            *permissions.values(),
            self.applicant,
            self.handler_only,
            self.outsider,
            self.approval_only,
            self.generic_approver,
            self.lead_viewer,
            self.lead_scope_viewer,
            self.lead_approver,
            self.tag_reviewer,
        ])
        self.db.flush()
        self.db.add_all([
            RolePermission(role_id=roles["approval_only"].id, permission_id=permissions["approval.view"].id),
            RolePermission(role_id=roles["generic_approver"].id, permission_id=permissions["approval.approve"].id),
            RolePermission(role_id=roles["lead_viewer"].id, permission_id=permissions["approval.view"].id),
            RolePermission(role_id=roles["lead_viewer"].id, permission_id=permissions["approval.approve"].id),
            RolePermission(role_id=roles["lead_viewer"].id, permission_id=permissions["crm_lead.view"].id),
            RolePermission(role_id=roles["lead_scope_viewer"].id, permission_id=permissions["crm_lead.view"].id),
            RolePermission(role_id=roles["lead_approver"].id, permission_id=permissions["crm_lead.approve"].id),
            RolePermission(role_id=roles["tag_reviewer"].id, permission_id=permissions["customer_tag.review"].id),
            DataScopeRule(subject_type="role", subject_id="lead_viewer", resource_type="crm_lead", scope_mode="custom", scope_value={"lead_ids": []}),
        ])
        self.db.commit()

    def _lead(self) -> CrmLead:
        lead = CrmLead(
            lead_no="LEAD-PRIVATE-1",
            lead_name="Private lead",
            normalized_name="privatelead",
            company_name="Private company",
            contact_name="Jane Private",
            contact_phone="13800138000",
            normalized_phone="13800138000",
            status="conversion_pending",
            owner_user_id=self.applicant.id,
            assigned_user_id=self.applicant.id,
            created_by_user_id=self.applicant.id,
        )
        self.db.add(lead)
        self.db.flush()
        return lead

    def _lead_conversion_approval(self) -> ApprovalInstance:
        approval = create_approval_instance(
            self.db,
            approval_type="crm_lead_convert",
            resource_type="crm_lead",
            resource_id=str(self.lead.id),
            title="Convert private lead",
            description=None,
            applicant=self.applicant,
            current_handler_user_id=self.lead_approver.id,
            priority="normal",
            payload_json={
                "lead_id": self.lead.id,
                "lead": {
                    "id": self.lead.id,
                    "lead_no": self.lead.lead_no,
                    "lead_name": self.lead.lead_name,
                    "company_name": self.lead.company_name,
                    "contact_name": self.lead.contact_name,
                    "contact_phone": self.lead.contact_phone,
                    "normalized_phone": self.lead.normalized_phone,
                    "internal_secret": "do-not-return",
                    "status": "qualified",
                },
                "before": {"normalized_phone": self.lead.normalized_phone, "internal_secret": "do-not-return", "status": "qualified"},
                "after": {"status": "converted", "internal_secret": "do-not-return"},
                "internal_secret": "do-not-return",
            },
            submit=True,
        )
        self.db.add(
            ApprovalEvent(
                approval_id=approval.id,
                event_type="submit",
                snapshot_json={"normalized_phone": self.lead.normalized_phone, "internal_secret": "do-not-return"},
            )
        )
        self.db.flush()
        return approval

    def _headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.username)}"}

    def _approval(
        self,
        *,
        approval_type: str,
        applicant: User,
        handler: User,
        title: str,
        status_value: str = "submitted",
    ) -> ApprovalInstance:
        approval = create_approval_instance(
            self.db,
            approval_type=approval_type,
            resource_type="crm_project",
            resource_id=f"resource-{title}",
            title=title,
            description=f"Description for {title}",
            applicant=applicant,
            current_handler_user_id=handler.id,
            priority="normal",
            payload_json={"title": title},
            status_value=status_value,
            submit=status_value == "submitted",
        )
        self.db.commit()
        return approval

    def test_approval_view_only_cannot_list_or_read_lead_conversion(self):
        page = self.client.get("/api/v1/approvals/page", headers=self._headers(self.approval_only))
        detail = self.client.get(f"/api/v1/approvals/{self.lead_approval.id}", headers=self._headers(self.approval_only))
        action = self.client.post(f"/api/v1/approvals/{self.lead_approval.id}/reject", headers=self._headers(self.approval_only))

        self.assertEqual(page.status_code, 200)
        self.assertEqual([item["id"] for item in page.json()["items"]], [self.generic_approval.id])
        self.assertEqual(detail.status_code, 404)
        self.assertEqual(action.status_code, 403)
        self.assertNotIn("13800138000", action.text)

    def test_out_of_scope_lead_viewer_cannot_list_or_read_conversion(self):
        page = self.client.get("/api/v1/approvals/page", headers=self._headers(self.lead_viewer))
        detail = self.client.get(f"/api/v1/approvals/{self.lead_approval.id}", headers=self._headers(self.lead_viewer))

        self.assertEqual(page.status_code, 200)
        self.assertEqual([item["id"] for item in page.json()["items"]], [self.generic_approval.id])
        self.assertEqual(detail.status_code, 404)

    def test_current_lead_approver_can_view_and_action_only_sanitized_detail(self):
        page = self.client.get("/api/v1/approvals/page", headers=self._headers(self.lead_approver))
        detail = self.client.get(f"/api/v1/approvals/{self.lead_approval.id}", headers=self._headers(self.lead_approver))
        action = self.client.post(f"/api/v1/approvals/{self.lead_approval.id}/reject", headers=self._headers(self.lead_approver))

        self.assertEqual(page.status_code, 200)
        self.assertEqual([item["id"] for item in page.json()["items"]], [self.lead_approval.id])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(action.status_code, 200)
        self.assertEqual(self.db.get(ApprovalInstance, self.lead_approval.id).status, "rejected")
        for response in (detail, action):
            response_text = response.text
            self.assertNotIn("13800138000", response_text)
            self.assertNotIn("normalized_phone", response_text)
            self.assertNotIn("internal_secret", response_text)
            self.assertIn("138****8000", response_text)
            self.assertNotIn("do-not-return", response_text)
        self.assertEqual(self.db.get(ApprovalInstance, self.lead_approval.id).payload_json["lead"]["normalized_phone"], "13800138000")

    def test_generic_approval_remains_visible_to_approval_view_user(self):
        detail = self.client.get(f"/api/v1/approvals/{self.generic_approval.id}", headers=self._headers(self.approval_only))

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["approval"]["payload_json"], {"project_name": "Visible generic approval"})

    def test_web_mobile_and_detail_share_the_same_role_matrix(self):
        handler_approval = self._approval(
            approval_type="crm_project_extension",
            applicant=self.applicant,
            handler=self.handler_only,
            title="handler-only",
        )
        generic_approver_approval = self._approval(
            approval_type="crm_project_extension",
            applicant=self.applicant,
            handler=self.generic_approver,
            title="generic-approver",
        )
        tag_approval = self._approval(
            approval_type="customer_tag_change",
            applicant=self.applicant,
            handler=self.tag_reviewer,
            title="tag-reviewer",
        )
        expected_by_user = {
            self.applicant.username: {
                self.generic_approval.id,
                handler_approval.id,
                generic_approver_approval.id,
                tag_approval.id,
            },
            self.handler_only.username: {handler_approval.id},
            self.generic_approver.username: {generic_approver_approval.id},
            self.lead_scope_viewer.username: {self.lead_approval.id},
            self.lead_approver.username: {self.lead_approval.id},
            self.tag_reviewer.username: {tag_approval.id},
            self.outsider.username: set(),
        }
        mobile_expected_by_user = {
            **expected_by_user,
            self.lead_scope_viewer.username: set(),
        }
        users = {
            user.username: user
            for user in (
                self.applicant,
                self.handler_only,
                self.generic_approver,
                self.lead_scope_viewer,
                self.lead_approver,
                self.tag_reviewer,
                self.outsider,
            )
        }
        all_approval_ids = {
            self.generic_approval.id,
            self.lead_approval.id,
            handler_approval.id,
            generic_approver_approval.id,
            tag_approval.id,
        }

        for username, expected_ids in expected_by_user.items():
            with self.subTest(username=username):
                headers = self._headers(users[username])
                web_page = self.client.get("/api/v1/approvals/page", headers=headers)
                mobile_page = self.client.get("/api/v1/mobile/approvals?scope=pending&mode=mine", headers=headers)
                self.assertEqual(web_page.status_code, 200)
                self.assertEqual(mobile_page.status_code, 200)
                self.assertEqual({item["id"] for item in web_page.json()["items"]}, expected_ids)
                self.assertEqual(
                    {item["id"] for item in mobile_page.json()["items"]},
                    mobile_expected_by_user[username],
                )
                for approval_id in all_approval_ids:
                    expected_status = 200 if approval_id in expected_ids else 404
                    web_detail = self.client.get(f"/api/v1/approvals/{approval_id}", headers=headers)
                    mobile_detail = self.client.get(f"/api/v1/mobile/approvals/{approval_id}", headers=headers)
                    self.assertEqual(web_detail.status_code, expected_status)
                    self.assertEqual(mobile_detail.status_code, expected_status)

    def test_notifications_and_exports_honor_special_approval_roles(self):
        supplement = self._approval(
            approval_type="crm_project_extension",
            applicant=self.applicant,
            handler=self.handler_only,
            title="supplement",
            status_value="need_supplement",
        )
        tag_supplement = self._approval(
            approval_type="customer_tag_change",
            applicant=self.applicant,
            handler=self.tag_reviewer,
            title="tag-supplement",
            status_value="need_supplement",
        )
        expected_supplements = {
            self.applicant.username: {supplement.id, tag_supplement.id},
            self.handler_only.username: {supplement.id},
            self.tag_reviewer.username: {tag_supplement.id},
            self.outsider.username: set(),
        }
        users = {
            user.username: user
            for user in (self.applicant, self.handler_only, self.tag_reviewer, self.outsider)
        }

        for username, expected_ids in expected_supplements.items():
            with self.subTest(username=username):
                response = self.client.get("/api/v1/crm/reports/notifications", headers=self._headers(users[username]))
                self.assertEqual(response.status_code, 200)
                actual_ids = {
                    int(item["source_id"])
                    for item in response.json()["items"]
                    if item["source_type"] == "approval"
                }
                self.assertEqual(actual_ids, expected_ids)

        for user in (self.generic_approver, self.lead_scope_viewer, self.lead_approver, self.tag_reviewer):
            with self.subTest(export_user=user.username):
                response = self.client.get("/api/v1/crm/reports/weekly.csv", headers=self._headers(user))
                self.assertEqual(response.status_code, 200)

    def test_mobile_customer_tag_reviewer_can_reject_assigned_approval(self):
        tag_approval = self._approval(
            approval_type="customer_tag_change",
            applicant=self.applicant,
            handler=self.tag_reviewer,
            title="tag-mobile-action",
        )

        response = self.client.post(
            f"/api/v1/mobile/approvals/{tag_approval.id}/actions?action=reject",
            headers=self._headers(self.tag_reviewer),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["approval"]["status"], "rejected")
        self.assertEqual(self.db.get(ApprovalInstance, tag_approval.id).status, "rejected")


if __name__ == "__main__":
    unittest.main()
