import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.crm_leads import operations_router, router as crm_leads_router
from app.api.routes.mobile_round6 import router as mobile_leads_router
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import (
    AuditLog,
    CrmLead,
    CrmLeadAssignmentEvent,
    CrmLeadOperationPolicy,
    DataScopeRule,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.services.crm_lead_service import lead_sla_snapshot


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CrmLeadOperationsApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed_identity()
        self.policy = CrmLeadOperationPolicy(policy_key="default", daily_claim_limit=1)
        self.db.add(self.policy)
        self.db.commit()

        app = FastAPI()
        app.include_router(crm_leads_router, prefix="/api/v1")
        app.include_router(operations_router, prefix="/api/v1")
        app.include_router(mobile_leads_router, prefix="/api/v1/mobile")

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
        self.roles = {code: Role(role_code=code, role_name=code) for code in ("salesperson", "manager", "admin", "blocked")}
        permission_codes = (
            "crm_lead.view",
            "crm_lead.create",
            "crm_lead.edit",
            "crm_lead.assign",
            "crm_lead.claim",
            "crm_lead.recycle",
            "crm_lead.analytics",
            "crm_lead_campaign.view",
            "crm_lead_campaign.manage",
            "crm_lead_policy.manage",
        )
        self.permissions = {
            code: Permission(permission_code=code, permission_name=code, resource_type=code.rsplit(".", 1)[0], action_type=code.rsplit(".", 1)[-1])
            for code in permission_codes
        }
        self.sales = User(username="sales", password_hash="hash", real_name="Sales", role="salesperson", status="active", is_active=True)
        self.other_sales = User(username="other-sales", password_hash="hash", real_name="Other Sales", role="salesperson", status="active", is_active=True)
        self.manager = User(username="manager", password_hash="hash", real_name="Manager", role="manager", status="active", is_active=True)
        self.admin = User(username="admin", password_hash="hash", real_name="Admin", role="admin", status="active", is_active=True)
        self.blocked = User(username="blocked", password_hash="hash", real_name="Blocked", role="blocked", status="active", is_active=True)
        self.db.add_all([*self.roles.values(), *self.permissions.values(), self.sales, self.other_sales, self.manager, self.admin, self.blocked])
        self.db.flush()
        grants = {
            "salesperson": ("crm_lead.view", "crm_lead.create", "crm_lead.edit", "crm_lead.claim"),
            "manager": (
                "crm_lead.view",
                "crm_lead.edit",
                "crm_lead.assign",
                "crm_lead.recycle",
                "crm_lead.analytics",
                "crm_lead_campaign.view",
                "crm_lead_campaign.manage",
            ),
            "admin": permission_codes,
        }
        for role_code, codes in grants.items():
            for code in codes:
                self.db.add(RolePermission(role_id=self.roles[role_code].id, permission_id=self.permissions[code].id))
        self.db.add_all(
            [
                DataScopeRule(subject_type="role", subject_id="salesperson", resource_type="crm_lead", scope_mode="own", scope_value=None),
                DataScopeRule(subject_type="role", subject_id="manager", resource_type="crm_lead", scope_mode="all", scope_value=None),
                DataScopeRule(subject_type="role", subject_id="admin", resource_type="crm_lead", scope_mode="all", scope_value=None),
            ]
        )
        self.db.commit()

    def _headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.username)}"}

    def _public_lead(self, suffix: str) -> CrmLead:
        lead = CrmLead(
            lead_no=f"LEAD-POOL-{suffix}",
            lead_name=f"Public lead {suffix}",
            normalized_name=f"publiclead{suffix}",
            company_name="星河演示潜客有限公司",
            contact_name="不应暴露的联系人",
            contact_phone="13800138000",
            normalized_phone="13800138000",
            source="展会",
            region="苏州",
            status="active",
            pool_status="public",
        )
        self.db.add(lead)
        self.db.commit()
        return lead

    def _flag_values(self, **overrides):
        values = {
            "lead_sla": True,
            "lead_public_pool": True,
            "lead_campaign": True,
            "lead_team_dashboard": True,
            "lead_bulk_assignment": False,
            "mobile_feature_lead_pool": True,
        }
        values.update(overrides)
        return [patch.object(settings, field_name, value) for field_name, value in values.items()]

    def test_sla_uses_first_response_then_next_followup_deadline(self):
        now = datetime(2026, 7, 13, 9, tzinfo=timezone.utc)
        lead = CrmLead(
            lead_no="LEAD-SLA-1",
            lead_name="SLA lead",
            normalized_name="slalead",
            assigned_user_id=self.sales.id,
            first_response_due_at=now + timedelta(hours=2),
        )
        first_response = lead_sla_snapshot(lead, self.policy, now)
        self.assertEqual(first_response["state"], "due_soon")
        self.assertEqual(first_response["phase"], "first_response")

        lead.first_responded_at = now - timedelta(hours=1)
        lead.last_activity_at = now - timedelta(hours=73)
        lead.next_followup_at = now - timedelta(minutes=1)
        next_followup = lead_sla_snapshot(lead, self.policy, now)
        self.assertEqual(next_followup["state"], "overdue")
        self.assertEqual(next_followup["phase"], "next_followup")

    def test_public_pool_is_flagged_and_never_returns_pii(self):
        self._public_lead("MASKED")
        with patch.object(settings, "lead_public_pool", False):
            disabled = self.client.get("/api/v1/crm/leads/public-pool", headers=self._headers(self.sales))
        self.assertEqual(disabled.status_code, 404)

        with self._flag_context():
            response = self.client.get("/api/v1/crm/leads/public-pool", headers=self._headers(self.sales))
        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertNotIn("contact_name", item)
        self.assertNotIn("contact_phone", item)
        self.assertNotIn("13800138000", response.text)
        self.assertEqual(item["pool_status"], "public")

    def test_claim_is_atomic_and_respects_daily_limit(self):
        first = self._public_lead("CLAIM-1")
        second = self._public_lead("CLAIM-2")
        with self._flag_context():
            claimed = self.client.post(f"/api/v1/crm/leads/{first.id}/claim", headers=self._headers(self.sales))
            lost_race = self.client.post(f"/api/v1/crm/leads/{first.id}/claim", headers=self._headers(self.other_sales))
            over_limit = self.client.post(f"/api/v1/crm/leads/{second.id}/claim", headers=self._headers(self.sales))
        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(lost_race.status_code, 409)
        self.assertEqual(over_limit.status_code, 429)
        refreshed = self.db.get(CrmLead, first.id)
        self.assertEqual(refreshed.pool_status, "private")
        self.assertEqual(refreshed.assigned_user_id, self.sales.id)
        event = self.db.scalar(select(CrmLeadAssignmentEvent).where(CrmLeadAssignmentEvent.lead_id == first.id))
        self.assertEqual(event.event_type, "claimed")

    def test_recycle_returns_eligible_lead_to_pool_and_audits(self):
        lead = CrmLead(
            lead_no="LEAD-RECYCLE",
            lead_name="Recycle lead",
            normalized_name="recyclelead",
            assigned_user_id=self.sales.id,
            owner_user_id=self.sales.id,
            status="active",
        )
        self.db.add(lead)
        self.db.commit()
        with self._flag_context():
            response = self.client.post(
                f"/api/v1/crm/leads/{lead.id}/recycle",
                headers=self._headers(self.manager),
                json={"note": "超过跟进时限"},
            )
        self.assertEqual(response.status_code, 200)
        refreshed = self.db.get(CrmLead, lead.id)
        self.assertEqual(refreshed.pool_status, "public")
        self.assertIsNone(refreshed.assigned_user_id)
        self.assertIsNone(refreshed.owner_user_id)
        self.assertEqual(refreshed.recycle_count, 1)
        self.assertEqual(
            self.db.scalar(select(CrmLeadAssignmentEvent.event_type).where(CrmLeadAssignmentEvent.lead_id == lead.id)),
            "recycled",
        )
        self.assertIsNotNone(
            self.db.scalar(select(AuditLog).where(AuditLog.resource_id == str(lead.id), AuditLog.action_type == "recycle_crm_lead"))
        )

    def test_sla_exceptions_are_flagged_and_limited_to_visible_leads(self):
        now = datetime.now(timezone.utc)
        own = CrmLead(
            lead_no="LEAD-SLA-OWN",
            lead_name="Own overdue",
            normalized_name="ownoverdue",
            owner_user_id=self.sales.id,
            assigned_user_id=self.sales.id,
            status="active",
            first_response_due_at=now - timedelta(hours=1),
        )
        other = CrmLead(
            lead_no="LEAD-SLA-OTHER",
            lead_name="Other overdue",
            normalized_name="otheroverdue",
            owner_user_id=self.other_sales.id,
            assigned_user_id=self.other_sales.id,
            status="active",
            first_response_due_at=now - timedelta(hours=1),
        )
        self.db.add_all([own, other])
        self.db.commit()

        with patch.object(settings, "lead_sla", False):
            disabled = self.client.get("/api/v1/crm/leads/sla-exceptions", headers=self._headers(self.sales))
        with self._flag_context():
            enabled = self.client.get("/api/v1/crm/leads/sla-exceptions", headers=self._headers(self.sales))

        self.assertEqual(disabled.status_code, 404)
        self.assertEqual(enabled.status_code, 200)
        self.assertEqual(enabled.json()["total"], 1)
        self.assertEqual(enabled.json()["items"][0]["lead"]["id"], own.id)
        self.assertEqual(enabled.json()["items"][0]["sla"]["state"], "overdue")

    def test_mobile_sla_exceptions_reuse_scope_and_respect_global_flag(self):
        now = datetime.now(timezone.utc)
        overdue = CrmLead(
            lead_no="LEAD-MOBILE-SLA",
            lead_name="Mobile SLA overdue",
            normalized_name="mobileslaoverdue",
            owner_user_id=self.sales.id,
            assigned_user_id=self.sales.id,
            status="active",
            first_response_due_at=now - timedelta(days=1),
        )
        due_today = CrmLead(
            lead_no="LEAD-MOBILE-SLA-TODAY",
            lead_name="Mobile SLA due today",
            normalized_name="mobilesladue",
            owner_user_id=self.sales.id,
            assigned_user_id=self.sales.id,
            status="active",
            first_response_due_at=now + timedelta(hours=1),
        )
        self.db.add_all([overdue, due_today])
        self.db.commit()

        with patch.object(settings, "lead_sla", False):
            disabled = self.client.get("/api/v1/mobile/leads/sla-exceptions", headers=self._headers(self.sales))
        with self._flag_context():
            enabled = self.client.get("/api/v1/mobile/leads/sla-exceptions", headers=self._headers(self.sales))

        self.assertEqual(disabled.status_code, 404)
        self.assertEqual(enabled.status_code, 200)
        self.assertEqual(enabled.json()["items"][0]["lead"]["id"], overdue.id)

        with self._flag_context():
            today = self.client.get("/api/v1/mobile/leads/sla-exceptions?today_only=true", headers=self._headers(self.sales))

        self.assertEqual(today.status_code, 200)
        self.assertEqual(today.json()["total"], 1)
        self.assertEqual(today.json()["items"][0]["lead"]["id"], due_today.id)

    def test_mobile_public_pool_requires_view_and_claim_permissions(self):
        lead = self._public_lead("CLAIM-ONLY")
        self.db.add(RolePermission(role_id=self.roles["blocked"].id, permission_id=self.permissions["crm_lead.claim"].id))
        self.db.commit()

        with self._flag_context():
            listed = self.client.get("/api/v1/mobile/leads/public-pool", headers=self._headers(self.blocked))
            claimed = self.client.post(f"/api/v1/mobile/leads/{lead.id}/claim", headers=self._headers(self.blocked))

        self.assertEqual(listed.status_code, 403)
        self.assertEqual(claimed.status_code, 403)

    def test_campaign_crud_is_role_gated_and_mobile_pool_reuses_masked_projection(self):
        self._public_lead("MOBILE")
        with self._flag_context():
            forbidden = self.client.post(
                "/api/v1/crm/lead-campaigns",
                headers=self._headers(self.sales),
                json={"campaign_code": "CMP-1", "campaign_name": "夏季展会"},
            )
            created = self.client.post(
                "/api/v1/crm/lead-campaigns",
                headers=self._headers(self.manager),
                json={"campaign_code": "CMP-1", "campaign_name": "夏季展会", "channel": "展会"},
            )
            listed = self.client.get("/api/v1/crm/lead-campaigns", headers=self._headers(self.manager))
            mobile_pool = self.client.get("/api/v1/mobile/leads/public-pool", headers=self._headers(self.sales))
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"][0]["campaign_code"], "CMP-1")
        self.assertEqual(mobile_pool.status_code, 200)
        self.assertNotIn("contact_phone", mobile_pool.json()["items"][0])

    def test_campaign_references_and_merged_campaign_dates_are_validated_before_write(self):
        lead = CrmLead(lead_no="LEAD-CAMPAIGN", lead_name="Campaign lead", normalized_name="campaignlead", owner_user_id=self.sales.id)
        self.db.add(lead)
        self.db.commit()
        with self._flag_context():
            invalid_reference = self.client.patch(
                f"/api/v1/crm/leads/{lead.id}",
                headers=self._headers(self.sales),
                json={"campaign_id": 999999},
            )
            created = self.client.post(
                "/api/v1/crm/lead-campaigns",
                headers=self._headers(self.manager),
                json={"campaign_code": "CMP-DATE", "campaign_name": "日期校验", "start_date": "2026-07-01", "end_date": "2026-07-02"},
            )
            invalid_date_patch = self.client.patch(
                f"/api/v1/crm/lead-campaigns/{created.json()['id']}",
                headers=self._headers(self.manager),
                json={"start_date": "2026-07-03"},
            )
        self.assertEqual(invalid_reference.status_code, 422)
        self.assertEqual(invalid_date_patch.status_code, 422)

    def test_analytics_requires_the_dedicated_permission(self):
        with self._flag_context():
            denied = self.client.get("/api/v1/crm/leads/analytics", headers=self._headers(self.sales))
            allowed = self.client.get("/api/v1/crm/leads/analytics", headers=self._headers(self.manager))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)

    class _FlagContext:
        def __init__(self, patches):
            self.patches = patches

        def __enter__(self):
            for patcher in self.patches:
                patcher.start()

        def __exit__(self, exc_type, exc, traceback):
            for patcher in reversed(self.patches):
                patcher.stop()

    def _flag_context(self, **overrides):
        return self._FlagContext(self._flag_values(**overrides))


if __name__ == "__main__":
    unittest.main()
