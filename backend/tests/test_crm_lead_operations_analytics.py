import unittest
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.approvals import approve_approval, router as approvals_router
from app.api.routes.crm_leads import create_lead_conversion_approval_draft, router as crm_leads_router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import (
    ApprovalInstance,
    AuditLog,
    CrmLead,
    CrmLeadAssignmentEvent,
    CrmLeadCampaign,
    CustomerMaster,
    DataScopeRule,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.schemas.crm import CrmLeadConversionApprovalDraftCreate


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CrmLeadOperationsAnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed_identity()

        app = FastAPI()
        app.include_router(crm_leads_router, prefix="/api/v1")
        app.include_router(approvals_router, prefix="/api/v1")

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()

    def _seed_identity(self):
        self.roles = {
            code: Role(role_code=code, role_name=code)
            for code in ("salesperson", "analyst", "admin")
        }
        permission_codes = (
            "crm_lead.view",
            "crm_lead.convert",
            "crm_lead.analytics",
            "approval.approve",
        )
        self.permissions = {
            code: Permission(
                permission_code=code,
                permission_name=code,
                resource_type=code.rsplit(".", 1)[0],
                action_type=code.rsplit(".", 1)[-1],
            )
            for code in permission_codes
        }
        self.sales = User(username="sales", password_hash="hash", real_name="销售员", role="salesperson", status="active", is_active=True)
        self.analyst = User(username="analyst", password_hash="hash", real_name="分析员", role="analyst", status="active", is_active=True)
        self.admin = User(username="admin", password_hash="hash", real_name="施总", role="admin", status="active", is_active=True)
        self.db.add_all([*self.roles.values(), *self.permissions.values(), self.sales, self.analyst, self.admin])
        self.db.flush()
        grants = {
            "salesperson": ("crm_lead.view", "crm_lead.convert"),
            "analyst": ("crm_lead.view", "crm_lead.analytics"),
            "admin": ("crm_lead.view", "approval.approve"),
        }
        for role_code, codes in grants.items():
            for code in codes:
                self.db.add(RolePermission(role_id=self.roles[role_code].id, permission_id=self.permissions[code].id))
        self.db.add_all(
            [
                DataScopeRule(subject_type="role", subject_id="salesperson", resource_type="crm_lead", scope_mode="own", scope_value=None),
                DataScopeRule(subject_type="role", subject_id="analyst", resource_type="crm_lead", scope_mode="own", scope_value=None),
                DataScopeRule(subject_type="role", subject_id="admin", resource_type="crm_lead", scope_mode="all", scope_value=None),
            ]
        )
        self.db.commit()

    def _headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.username)}"}

    def _lead(self, suffix: str, *, owner: User, status: str = "qualified", **values) -> CrmLead:
        data = {
            "lead_no": f"LEAD-OPS-{suffix}",
            "lead_name": f"线索 {suffix}",
            "normalized_name": f"leadops{suffix}",
            "company_name": f"公司 {suffix}",
            "contact_name": "王经理",
            "contact_phone": f"13800138{suffix[-3:]}",
            "normalized_phone": f"13800138{suffix[-3:]}",
            "source": "展会",
            "region": "苏州",
            "business_line": "包装",
            "status": status,
            "owner_user_id": owner.id,
            "assigned_user_id": owner.id,
            "created_by_user_id": owner.id,
            "updated_by_user_id": owner.id,
        }
        data.update(values)
        lead = CrmLead(**data)
        self.db.add(lead)
        self.db.commit()
        return lead

    def test_conversion_result_keeps_campaign_source_owner_attribution_and_project_prefill(self):
        campaign = CrmLeadCampaign(campaign_code="CMP-SUMMER", campaign_name="夏季客户开发", source="展会", status="active")
        self.db.add(campaign)
        self.db.flush()
        lead = self._lead("101", owner=self.sales, campaign_id=campaign.id, source="夏季展会")

        approval = create_lead_conversion_approval_draft(
            lead.id,
            CrmLeadConversionApprovalDraftCreate(submit=True, note="客户确认合作意向"),
            request=None,
            db=self.db,
            current_user=self.sales,
        )
        detail = approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)
        result = detail.approval.result_json

        self.assertEqual(result["attribution"]["source"], "夏季展会")
        self.assertEqual(result["attribution"]["campaign"]["campaign_code"], "CMP-SUMMER")
        self.assertEqual(result["attribution"]["owner_label"], "销售员")
        self.assertEqual(result["project_prefill"]["campaign"]["campaign_name"], "夏季客户开发")
        self.assertEqual(result["project_prefill"]["source"], "夏季展会")
        stored_result = self.db.get(ApprovalInstance, approval.id).result_json
        self.assertEqual(stored_result["attribution"]["owner_user_id"], self.sales.id)
        audit = self.db.scalar(select(AuditLog).where(AuditLog.action_type == "approve_crm_lead_convert"))
        self.assertEqual(audit.after_data["attribution"]["campaign"]["campaign_code"], "CMP-SUMMER")

    def test_conversion_rejects_an_approval_when_the_lead_changed_after_submission(self):
        lead = self._lead("102", owner=self.sales)
        approval = create_lead_conversion_approval_draft(
            lead.id,
            CrmLeadConversionApprovalDraftCreate(submit=True),
            request=None,
            db=self.db,
            current_user=self.sales,
        )
        lead.source = "后续补录来源"
        self.db.commit()

        with self.assertRaises(HTTPException) as error:
            approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("线索资料在审批期间发生变化", str(error.exception.detail))
        self.assertIsNone(self.db.scalar(select(CustomerMaster)))
        self.assertEqual(self.db.get(ApprovalInstance, approval.id).status, "submitted")

    def test_historical_conversion_without_a_guard_remains_approvable(self):
        lead = self._lead("103", owner=self.sales)
        approval = create_lead_conversion_approval_draft(
            lead.id,
            CrmLeadConversionApprovalDraftCreate(submit=True),
            request=None,
            db=self.db,
            current_user=self.sales,
        )
        legacy_payload = dict(approval.payload_json)
        legacy_payload.pop("conversion_guard", None)
        approval.payload_json = legacy_payload
        lead.source = "历史审批继续按原口径处理"
        self.db.commit()

        detail = approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(detail.approval.status, "completed")
        self.assertEqual(self.db.get(CrmLead, lead.id).status, "converted")

    def test_operations_analytics_matches_the_visible_lead_list_and_excludes_other_scopes(self):
        now = datetime.now(timezone.utc)
        overdue = self._lead("201", owner=self.analyst, status="active", first_response_due_at=now - timedelta(hours=1), recycle_count=1)
        self.db.add(
            CrmLeadAssignmentEvent(
                lead_id=overdue.id,
                event_type="recycled",
                from_assignee_user_id=self.analyst.id,
                assigned_by_user_id=self.analyst.id,
            )
        )
        self._lead("202", owner=self.analyst, status="qualified", source="转介绍", first_response_due_at=now + timedelta(hours=1))
        self._lead("203", owner=self.analyst, status="converted", source="展会")
        self._lead("999", owner=self.sales, status="converted", source="不应暴露")
        self.db.commit()

        page = self.client.get("/api/v1/crm/leads", headers=self._headers(self.analyst))
        analytics = self.client.get("/api/v1/crm/leads/analytics", headers=self._headers(self.analyst))

        self.assertEqual(page.status_code, 200)
        self.assertEqual(analytics.status_code, 200)
        body = analytics.json()
        self.assertEqual(body["summary"]["total"], page.json()["total"])
        self.assertEqual(body["summary"]["total"], 3)
        self.assertEqual(sum(item["total"] for item in body["operations"]["source_funnel"]), 3)
        self.assertNotIn("不应暴露", {item["source"] for item in body["operations"]["source_funnel"]})
        self.assertEqual(body["operations"]["sla_exceptions"]["overdue"], 1)
        self.assertEqual(body["operations"]["sla_exceptions"]["due_soon"], 1)
        self.assertEqual(body["operations"]["recycle_metrics"]["recycled_leads"], 1)
        self.assertEqual(body["operations"]["recycle_metrics"]["recycle_events"], 1)


if __name__ == "__main__":
    unittest.main()
