import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.crm_leads import router as crm_leads_router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import (
    AuditLog,
    CrmLead,
    CrmLeadAssignmentEvent,
    CrmLeadFollowup,
    DataScopeRule,
    FieldPermissionRule,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.services.crm_lead_service import acquire_lead_duplicate_locks, lead_duplicate_lock_keys


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CrmLeadApiTest(unittest.TestCase):
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
            for code in ("salesperson", "team", "admin", "blocked", "create_only", "assign_only", "analytics")
        }
        self.permissions = {
            code: Permission(
                permission_code=code,
                permission_name=code,
                resource_type="crm_lead",
                action_type=code.rsplit(".", 1)[-1],
            )
            for code in ("crm_lead.view", "crm_lead.create", "crm_lead.edit", "crm_lead.assign", "crm_lead.analytics")
        }
        self.owner = User(username="owner", password_hash="hash", real_name="Owner", role="salesperson", status="active", is_active=True)
        self.teammate = User(username="teammate", password_hash="hash", real_name="Teammate", role="team", status="active", is_active=True)
        self.admin = User(username="admin", password_hash="hash", real_name="Admin", role="admin", status="active", is_active=True)
        self.blocked = User(username="blocked", password_hash="hash", real_name="Blocked", role="blocked", status="active", is_active=True)
        self.creator = User(username="creator", password_hash="hash", real_name="Creator", role="create_only", status="active", is_active=True)
        self.assigner = User(username="assigner", password_hash="secret-hash", real_name="Assign Only", role="assign_only", status="active", is_active=True)
        self.analytics_user = User(username="analytics", password_hash="hash", real_name="Analytics", role="analytics", status="active", is_active=True)
        self.inactive_assignee = User(username="inactive-assignee", password_hash="private-hash", real_name="Inactive", role="team", status="disabled", is_active=False)
        self.db.add_all([*self.roles.values(), *self.permissions.values(), self.owner, self.teammate, self.admin, self.blocked, self.creator, self.assigner, self.analytics_user, self.inactive_assignee])
        self.db.flush()
        for role_code, grants in {
            "salesperson": ("crm_lead.view", "crm_lead.create", "crm_lead.edit"),
            "team": ("crm_lead.view",),
            "admin": tuple(self.permissions),
            "create_only": ("crm_lead.create",),
            "assign_only": ("crm_lead.assign",),
            "analytics": ("crm_lead.view", "crm_lead.create", "crm_lead.analytics"),
        }.items():
            for permission_code in grants:
                self.db.add(RolePermission(role_id=self.roles[role_code].id, permission_id=self.permissions[permission_code].id))
        self.db.add_all(
            [
                DataScopeRule(subject_type="role", subject_id="salesperson", resource_type="crm_lead", scope_mode="own", scope_value=None),
                DataScopeRule(subject_type="role", subject_id="team", resource_type="crm_lead", scope_mode="assigned", scope_value=None),
                DataScopeRule(subject_type="role", subject_id="admin", resource_type="crm_lead", scope_mode="all", scope_value=None),
                DataScopeRule(subject_type="role", subject_id="analytics", resource_type="crm_lead", scope_mode="own", scope_value=None),
                FieldPermissionRule(subject_type="role", subject_id="team", resource_type="crm_lead", field_name="contact_phone", permission_type="masked", mask_rule="phone"),
            ]
        )
        self.db.commit()

    def test_assignee_options_allow_assign_only_and_return_safe_active_labels(self):
        response = self.client.get("/api/v1/crm/leads/assignee-options", headers=self._headers(self.assigner))

        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertGreater(len(items), 0)
        self.assertTrue(all(set(item) == {"id", "name", "username", "label"} for item in items))
        self.assertIn(self.assigner.id, {item["id"] for item in items})
        self.assertNotIn(self.inactive_assignee.id, {item["id"] for item in items})
        self.assertNotIn("secret-hash", response.text)
        self.assertNotIn("private-hash", response.text)

    def test_assignee_options_reject_users_without_assign_permission(self):
        response = self.client.get("/api/v1/crm/leads/assignee-options", headers=self._headers(self.teammate))

        self.assertEqual(response.status_code, 403)

    def test_list_followup_pending_group_filters_all_matching_statuses_with_scope_and_pagination(self):
        self.db.add_all(
            [
                CrmLead(
                    lead_no="LEAD-FOLLOWUP-DRAFT",
                    lead_name="Followup draft",
                    normalized_name="followupdraft",
                    status="draft",
                    owner_user_id=self.owner.id,
                    created_by_user_id=self.owner.id,
                ),
                CrmLead(
                    lead_no="LEAD-FOLLOWUP-ACTIVE",
                    lead_name="Followup active",
                    normalized_name="followupactive",
                    status="active",
                    owner_user_id=self.owner.id,
                    created_by_user_id=self.owner.id,
                ),
                CrmLead(
                    lead_no="LEAD-NOT-FOLLOWUP",
                    lead_name="Qualified lead",
                    normalized_name="qualifiedlead",
                    status="qualified",
                    owner_user_id=self.owner.id,
                    created_by_user_id=self.owner.id,
                ),
                CrmLead(
                    lead_no="LEAD-HIDDEN-FOLLOWUP",
                    lead_name="Hidden followup",
                    normalized_name="hiddenfollowup",
                    status="active",
                    owner_user_id=self.admin.id,
                    created_by_user_id=self.admin.id,
                ),
            ]
        )
        self.db.commit()

        first_page = self.client.get(
            "/api/v1/crm/leads",
            headers=self._headers(self.owner),
            params={"status_group": "followup_pending", "limit": 1, "offset": 0},
        )
        second_page = self.client.get(
            "/api/v1/crm/leads",
            headers=self._headers(self.owner),
            params={"status_group": "followup_pending", "limit": 1, "offset": 1},
        )

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(first_page.json()["total"], 2)
        self.assertEqual(second_page.json()["total"], 2)
        self.assertEqual(first_page.json()["summary"]["total"], 3)
        self.assertEqual(
            first_page.json()["summary"]["by_status"],
            {"draft": 1, "active": 1, "qualified": 1},
        )
        self.assertEqual(second_page.json()["summary"], first_page.json()["summary"])
        rows = first_page.json()["items"] + second_page.json()["items"]
        self.assertEqual({row["lead_no"] for row in rows}, {"LEAD-FOLLOWUP-DRAFT", "LEAD-FOLLOWUP-ACTIVE"})
        self.assertEqual({row["status"] for row in rows}, {"draft", "active"})
        self.assertNotIn("LEAD-HIDDEN-FOLLOWUP", first_page.text + second_page.text)

        invalid_group = self.client.get(
            "/api/v1/crm/leads",
            headers=self._headers(self.owner),
            params={"status_group": "unknown"},
        )
        self.assertEqual(invalid_group.status_code, 422)

    def _headers(self, user):
        return {"Authorization": f"Bearer {create_access_token(user.username)}"}

    def _create(self, headers, **overrides):
        payload = {"lead_name": "Suzhou Textile", "contact_phone": "138 0013 8000", "source": "expo", "address": "No. 8 Industry Road", "customer_group_name": "Suzhou customer group", "product_intents": [{"product_name": "Canvas bag", "sort_order": 1}]}
        payload.update(overrides)
        return self.client.post("/api/v1/crm/leads", headers=headers, json=payload)

    def test_create_update_replaces_intents_and_audits(self):
        created = self._create(self._headers(self.owner))
        self.assertEqual(created.status_code, 201)
        lead = created.json()
        self.assertNotIn("normalized_phone", lead)
        self.assertNotIn("normalized_name", lead)
        self.assertEqual(lead["owner_user_id"], self.owner.id)
        self.assertEqual(lead["address"], "No. 8 Industry Road")
        self.assertEqual(lead["customer_group_name"], "Suzhou customer group")
        self.assertEqual([item["product_name"] for item in lead["product_intents"]], ["Canvas bag"])

        updated = self.client.patch(
            f"/api/v1/crm/leads/{lead['id']}",
            headers=self._headers(self.owner),
            json={"lead_name": "Suzhou Textile Co., Ltd.", "address": "No. 18 Updated Road", "customer_group_name": "Updated customer group", "status": "active", "product_intents": [{"product_name": "Drawstring bag", "sort_order": 4}]},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertNotIn("normalized_name", updated.json())
        self.assertNotIn("normalized_phone", updated.json())
        self.assertEqual(updated.json()["address"], "No. 18 Updated Road")
        self.assertEqual(updated.json()["customer_group_name"], "Updated customer group")
        self.assertEqual([item["product_name"] for item in updated.json()["product_intents"]], ["Drawstring bag"])
        self.assertEqual(len(list(self.db.scalars(select(AuditLog).where(AuditLog.resource_id == str(lead["id"]))))), 2)

    def test_invalid_state_transition_is_rejected(self):
        lead_id = self._create(self._headers(self.owner)).json()["id"]
        response = self.client.patch(
            f"/api/v1/crm/leads/{lead_id}",
            headers=self._headers(self.owner),
            json={"status": "converted"},
        )
        self.assertEqual(response.status_code, 400)

    def test_manual_stage_transitions_allow_direct_qualification_and_reactivation(self):
        created = self._create(self._headers(self.owner)).json()

        qualified = self.client.patch(
            f"/api/v1/crm/leads/{created['id']}",
            headers=self._headers(self.owner),
            json={"status": "qualified"},
        )
        self.assertEqual(qualified.status_code, 200)
        self.assertEqual(qualified.json()["status"], "qualified")

        for terminal_status in ("closed", "rejected"):
            with self.subTest(terminal_status=terminal_status):
                terminal = self.client.patch(
                    f"/api/v1/crm/leads/{created['id']}",
                    headers=self._headers(self.owner),
                    json={"status": terminal_status},
                )
                self.assertEqual(terminal.status_code, 200)

                reactivated = self.client.patch(
                    f"/api/v1/crm/leads/{created['id']}",
                    headers=self._headers(self.owner),
                    json={"status": "active"},
                )
                self.assertEqual(reactivated.status_code, 200)
                self.assertEqual(reactivated.json()["status"], "active")
                self.assertEqual(self.db.get(CrmLead, created["id"]).status, "active")

    def test_conversion_states_remain_locked_against_manual_reactivation(self):
        leads = [
            CrmLead(
                lead_no=f"LEAD-{lead_status.upper()}",
                lead_name=f"Locked {lead_status}",
                normalized_name=f"locked{lead_status}",
                status=lead_status,
                owner_user_id=self.owner.id,
                created_by_user_id=self.owner.id,
            )
            for lead_status in ("conversion_pending", "converted")
        ]
        self.db.add_all(leads)
        self.db.commit()

        for lead in leads:
            with self.subTest(current_status=lead.status):
                response = self.client.patch(
                    f"/api/v1/crm/leads/{lead.id}",
                    headers=self._headers(self.owner),
                    json={"status": "active"},
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json()["detail"],
                    f"Invalid CRM lead status transition: {lead.status} -> active",
                )
                self.assertEqual(self.db.get(CrmLead, lead.id).status, lead.status)

    def test_patch_rejects_explicit_null_lead_name_but_allows_omission(self):
        lead_id = self._create(self._headers(self.owner)).json()["id"]

        omitted = self.client.patch(f"/api/v1/crm/leads/{lead_id}", headers=self._headers(self.owner), json={})
        explicit_null = self.client.patch(
            f"/api/v1/crm/leads/{lead_id}",
            headers=self._headers(self.owner),
            json={"lead_name": None},
        )

        self.assertEqual(omitted.status_code, 200)
        self.assertEqual(explicit_null.status_code, 422)

    def test_patch_rejects_explicit_null_status_but_allows_omission(self):
        lead_id = self._create(self._headers(self.owner)).json()["id"]

        omitted = self.client.patch(f"/api/v1/crm/leads/{lead_id}", headers=self._headers(self.owner), json={})
        explicit_null = self.client.patch(
            f"/api/v1/crm/leads/{lead_id}",
            headers=self._headers(self.owner),
            json={"status": None},
        )

        self.assertEqual(omitted.status_code, 200)
        self.assertEqual(explicit_null.status_code, 422)

    def test_delete_closes_lead_preserves_history_and_audits(self):
        created = self._create(self._headers(self.owner)).json()
        followup = self.client.post(
            f"/api/v1/crm/leads/{created['id']}/followups",
            headers=self._headers(self.owner),
            json={"content": "Keep this history", "method": "phone"},
        )
        self.assertEqual(followup.status_code, 201)

        closed = self.client.delete(f"/api/v1/crm/leads/{created['id']}", headers=self._headers(self.owner))

        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.json()["message"], "CRM lead closed")
        self.assertEqual(closed.json()["lead"]["status"], "closed")
        self.assertIsNotNone(self.db.get(CrmLead, created["id"]))
        detail = self.client.get(f"/api/v1/crm/leads/{created['id']}", headers=self._headers(self.owner))
        self.assertEqual(len(detail.json()["product_intents"]), 1)
        self.assertEqual(len(detail.json()["followups"]), 1)
        audit = self.db.scalar(
            select(AuditLog)
            .where(AuditLog.resource_id == str(created["id"]), AuditLog.action_type == "close_crm_lead")
            .order_by(AuditLog.id.desc())
        )
        self.assertEqual(audit.before_data["status"], "draft")
        self.assertEqual(audit.after_data["status"], "closed")

    def test_delete_flushes_current_updated_at_into_audit_snapshot(self):
        created = self._create(self._headers(self.owner)).json()
        stale_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.db.execute(update(CrmLead).where(CrmLead.id == created["id"]).values(updated_at=stale_at))
        self.db.commit()

        closed = self.client.delete(f"/api/v1/crm/leads/{created['id']}", headers=self._headers(self.owner))

        self.assertEqual(closed.status_code, 200)
        audit = self.db.scalar(
            select(AuditLog)
            .where(AuditLog.resource_id == str(created["id"]), AuditLog.action_type == "close_crm_lead")
            .order_by(AuditLog.id.desc())
        )
        self.assertGreater(
            datetime.fromisoformat(audit.after_data["updated_at"]),
            datetime.fromisoformat(audit.before_data["updated_at"]),
        )

    def test_patch_flushes_current_updated_at_into_audit_snapshot(self):
        created = self._create(self._headers(self.owner)).json()
        stale_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.db.execute(update(CrmLead).where(CrmLead.id == created["id"]).values(updated_at=stale_at))
        self.db.commit()

        self.db.autoflush = False
        try:
            updated = self.client.patch(
                f"/api/v1/crm/leads/{created['id']}",
                headers=self._headers(self.owner),
                json={"status": "active"},
            )
        finally:
            self.db.autoflush = True

        self.assertEqual(updated.status_code, 200)
        audit = self.db.scalar(
            select(AuditLog)
            .where(AuditLog.resource_id == str(created["id"]), AuditLog.action_type == "update_crm_lead")
            .order_by(AuditLog.id.desc())
        )
        self.assertGreater(
            datetime.fromisoformat(audit.after_data["updated_at"]),
            datetime.fromisoformat(audit.before_data["updated_at"]),
        )

    def test_assign_flushes_current_updated_at_into_audit_snapshot(self):
        created = self._create(self._headers(self.owner)).json()
        stale_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.db.execute(update(CrmLead).where(CrmLead.id == created["id"]).values(updated_at=stale_at))
        self.db.commit()

        self.db.autoflush = False
        try:
            assigned = self.client.post(
                f"/api/v1/crm/leads/{created['id']}/assign",
                headers=self._headers(self.admin),
                json={"assigned_user_id": self.teammate.id, "note": "Flush audit state"},
            )
        finally:
            self.db.autoflush = True

        self.assertEqual(assigned.status_code, 200)
        audit = self.db.scalar(
            select(AuditLog)
            .where(AuditLog.resource_id == str(created["id"]), AuditLog.action_type == "assign_crm_lead")
            .order_by(AuditLog.id.desc())
        )
        self.assertGreater(
            datetime.fromisoformat(audit.after_data["updated_at"]),
            datetime.fromisoformat(audit.before_data["updated_at"]),
        )

    def test_delete_requires_edit_permission_and_scoped_visibility(self):
        lead_id = self._create(self._headers(self.owner)).json()["id"]
        self.client.post(
            f"/api/v1/crm/leads/{lead_id}/assign",
            headers=self._headers(self.admin),
            json={"assigned_user_id": self.teammate.id},
        )

        self.assertEqual(self.client.delete(f"/api/v1/crm/leads/{lead_id}", headers=self._headers(self.teammate)).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/v1/crm/leads/{lead_id}", headers=self._headers(self.blocked)).status_code, 403)

        hidden = CrmLead(
            lead_no="LEAD-HIDDEN-CLOSE",
            lead_name="Hidden close lead",
            normalized_name="hiddencloselead",
            owner_user_id=self.admin.id,
            created_by_user_id=self.admin.id,
        )
        self.db.add(hidden)
        self.db.commit()
        self.assertEqual(self.client.delete(f"/api/v1/crm/leads/{hidden.id}", headers=self._headers(self.owner)).status_code, 404)

    def test_delete_rejects_conversion_pending_and_converted_leads(self):
        for lead_no, lead_status in (("LEAD-PENDING-CLOSE", "conversion_pending"), ("LEAD-CONVERTED-CLOSE", "converted")):
            lead = CrmLead(
                lead_no=lead_no,
                lead_name=lead_no,
                normalized_name=lead_no.lower().replace("-", ""),
                status=lead_status,
                owner_user_id=self.owner.id,
                created_by_user_id=self.owner.id,
            )
            self.db.add(lead)
        self.db.commit()

        for lead in self.db.scalars(select(CrmLead).where(CrmLead.lead_no.in_(["LEAD-PENDING-CLOSE", "LEAD-CONVERTED-CLOSE"]))).all():
            response = self.client.delete(f"/api/v1/crm/leads/{lead.id}", headers=self._headers(self.owner))
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], f"Invalid CRM lead status transition: {lead.status} -> closed")
            self.assertEqual(self.db.get(CrmLead, lead.id).status, lead.status)

    def test_delete_rejects_rejected_to_closed_transition(self):
        lead = CrmLead(
            lead_no="LEAD-REJECTED-CLOSE",
            lead_name="Rejected close lead",
            normalized_name="rejectedcloselead",
            status="rejected",
            owner_user_id=self.owner.id,
            created_by_user_id=self.owner.id,
        )
        self.db.add(lead)
        self.db.commit()

        response = self.client.delete(f"/api/v1/crm/leads/{lead.id}", headers=self._headers(self.owner))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid CRM lead status transition: rejected -> closed")
        self.assertEqual(self.db.get(CrmLead, lead.id).status, "rejected")

    def test_assignment_and_followup_keep_history_and_summary_fields(self):
        lead_id = self._create(self._headers(self.owner)).json()["id"]
        assigned = self.client.post(
            f"/api/v1/crm/leads/{lead_id}/assign",
            headers=self._headers(self.admin),
            json={"assigned_user_id": self.teammate.id, "note": "North territory"},
        )
        self.assertEqual(assigned.status_code, 200)
        followup = self.client.post(
            f"/api/v1/crm/leads/{lead_id}/followups",
            headers=self._headers(self.owner),
            json={"content": "Called procurement", "method": "phone", "next_action": "Send samples", "next_followup_at": "2026-07-12T09:00:00Z"},
        )
        self.assertEqual(followup.status_code, 201)
        detail = self.client.get(f"/api/v1/crm/leads/{lead_id}", headers=self._headers(self.owner))
        self.assertEqual(len(detail.json()["assignments"]), 1)
        self.assertEqual(len(detail.json()["followups"]), 1)
        self.assertEqual(len(list(self.db.scalars(select(CrmLeadAssignmentEvent).where(CrmLeadAssignmentEvent.lead_id == lead_id)))), 1)
        self.assertEqual(len(list(self.db.scalars(select(CrmLeadFollowup).where(CrmLeadFollowup.lead_id == lead_id)))), 1)
        self.assertEqual(detail.json()["next_followup_at"], "2026-07-12T09:00:00")

    def test_exact_duplicates_are_blocking_and_fuzzy_candidates_are_advisory(self):
        first = self._create(self._headers(self.owner), lead_name="Suzhou Textile", contact_phone="13800138000")
        self.assertEqual(first.status_code, 201)
        duplicate = self._create(self._headers(self.owner), lead_name="Suzhou Textile", contact_phone="138-0013-8000")
        self.assertEqual(duplicate.status_code, 409)
        duplicate_check = self.client.get(
            "/api/v1/crm/leads/duplicate-check",
            headers=self._headers(self.owner),
            params={"lead_name": "Suzhou Textile", "contact_phone": "13800138000"},
        )
        self.assertEqual(duplicate_check.status_code, 200)
        self.assertTrue(duplicate_check.json()["has_blocking_duplicates"])
        self.assertIn("exact_phone", duplicate_check.json()["items"][0]["reasons"])
        fuzzy = self.client.get(
            "/api/v1/crm/leads/duplicate-check",
            headers=self._headers(self.owner),
            params={"lead_name": "Suzhou Textiles", "contact_phone": "13900000000"},
        )
        self.assertEqual(fuzzy.status_code, 200)
        self.assertFalse(fuzzy.json()["has_blocking_duplicates"])
        self.assertTrue(fuzzy.json()["requires_acknowledgement"])
        self.assertTrue(any("similar_name" in item["reasons"] for item in fuzzy.json()["items"]))

    def test_same_name_with_different_phone_requires_server_acknowledgement_and_is_audited(self):
        first = self._create(
            self._headers(self.owner),
            lead_name="Shared Trading Name",
            contact_phone="13800138000",
        )
        self.assertEqual(first.status_code, 201)

        check = self.client.get(
            "/api/v1/crm/leads/duplicate-check",
            headers=self._headers(self.owner),
            params={"lead_name": "Shared Trading Name", "contact_phone": "13900139000"},
        )
        self.assertEqual(check.status_code, 200)
        self.assertFalse(check.json()["has_blocking_duplicates"])
        self.assertTrue(check.json()["requires_acknowledgement"])

        unacknowledged = self._create(
            self._headers(self.owner),
            lead_name="Shared Trading Name",
            contact_phone="13900139000",
        )
        self.assertEqual(unacknowledged.status_code, 409)
        self.assertEqual(
            unacknowledged.json()["detail"]["message"],
            "CRM lead duplicate acknowledgement required",
        )

        acknowledged = self._create(
            self._headers(self.owner),
            lead_name="Shared Trading Name",
            contact_phone="13900139000",
            duplicate_acknowledged=True,
        )
        self.assertEqual(acknowledged.status_code, 201)
        audit = self.db.scalar(
            select(AuditLog)
            .where(
                AuditLog.action_type == "create_crm_lead",
                AuditLog.resource_id == str(acknowledged.json()["id"]),
            )
            .order_by(AuditLog.id.desc())
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.after_data["duplicate_override"]["acknowledged"], True)
        self.assertIn("exact_normalized_name", audit.after_data["duplicate_override"]["reasons"])

    def test_hidden_same_name_candidate_requires_acknowledgement_without_exposing_identity(self):
        restricted = CrmLead(
            lead_no="LEAD-HIDDEN-SAME-NAME",
            lead_name="Hidden Shared Name",
            normalized_name="hiddensharedname",
            contact_phone="13800138881",
            normalized_phone="13800138881",
            owner_user_id=self.admin.id,
            created_by_user_id=self.admin.id,
        )
        self.db.add(restricted)
        self.db.commit()

        response = self.client.get(
            "/api/v1/crm/leads/duplicate-check",
            headers=self._headers(self.owner),
            params={"lead_name": "Hidden Shared Name", "contact_phone": "13900139991"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["has_blocking_duplicates"])
        self.assertTrue(payload["requires_acknowledgement"])
        self.assertTrue(payload["has_hidden_duplicates"])
        self.assertEqual(payload["items"], [])
        self.assertNotIn("LEAD-HIDDEN-SAME-NAME", response.text)
        self.assertNotIn("13800138881", response.text)
        self.assertNotIn("Hidden Shared Name", response.text)

    def test_create_only_user_can_precheck_duplicates_without_viewing_candidate_details(self):
        self._create(self._headers(self.owner), lead_name="Private duplicate", contact_phone="13800138888")

        response = self.client.get(
            "/api/v1/crm/leads/duplicate-check",
            headers=self._headers(self.creator),
            params={"lead_name": "Private duplicate", "contact_phone": "13800138888"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["has_blocking_duplicates"])
        self.assertTrue(response.json()["has_hidden_duplicates"])
        self.assertEqual(response.json()["items"], [])

    def test_duplicate_conflict_does_not_expose_out_of_scope_lead_identity(self):
        restricted = CrmLead(
            lead_no="LEAD-RESTRICTED",
            lead_name="Restricted Counterparty",
            normalized_name="restrictedcounterparty",
            contact_phone="13912345678",
            normalized_phone="13912345678",
            owner_user_id=self.admin.id,
            created_by_user_id=self.admin.id,
        )
        self.db.add(restricted)
        self.db.commit()

        response = self._create(
            self._headers(self.owner),
            lead_name="Restricted Counterparty",
            contact_phone="13912345678",
        )

        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertEqual(detail["message"], "Blocking CRM lead duplicate")
        self.assertEqual(detail["blocking_duplicate_count"], 1)
        self.assertNotIn("duplicate_ids", detail)
        self.assertNotIn("lead_id", detail)
        self.assertNotIn("lead_no", detail)
        self.assertNotIn("Restricted Counterparty", str(detail))

    def test_create_and_patch_assignment_targets_require_assign_permission_and_active_users(self):
        forbidden_owner = self._create(self._headers(self.owner), owner_user_id=self.teammate.id)
        self.assertEqual(forbidden_owner.status_code, 403)
        forbidden_assignee = self._create(
            self._headers(self.owner),
            lead_name="Assigned by salesperson",
            contact_phone="13800138101",
            assigned_user_id=self.teammate.id,
        )
        self.assertEqual(forbidden_assignee.status_code, 403)
        own_assignment = self._create(
            self._headers(self.owner),
            lead_name="Self assigned lead",
            contact_phone="13800138102",
            owner_user_id=self.owner.id,
            assigned_user_id=self.owner.id,
        )
        self.assertEqual(own_assignment.status_code, 201)

        lead_id = self._create(
            self._headers(self.owner),
            lead_name="Patch assignment lead",
            contact_phone="13800138103",
        ).json()["id"]
        owner_patch = self.client.patch(
            f"/api/v1/crm/leads/{lead_id}",
            headers=self._headers(self.owner),
            json={"owner_user_id": self.teammate.id},
        )
        assignee_patch = self.client.patch(
            f"/api/v1/crm/leads/{lead_id}",
            headers=self._headers(self.owner),
            json={"assigned_user_id": self.teammate.id},
        )
        self.assertEqual(owner_patch.status_code, 403)
        self.assertEqual(assignee_patch.status_code, 403)

        self.teammate.is_active = False
        self.db.commit()
        inactive_owner = self.client.patch(
            f"/api/v1/crm/leads/{lead_id}",
            headers=self._headers(self.admin),
            json={"owner_user_id": self.teammate.id},
        )
        inactive_assignee = self.client.patch(
            f"/api/v1/crm/leads/{lead_id}",
            headers=self._headers(self.admin),
            json={"assigned_user_id": self.teammate.id},
        )
        self.assertEqual(inactive_owner.status_code, 400)
        self.assertEqual(inactive_assignee.status_code, 400)

    def test_audit_snapshots_capture_mutable_fields_intents_and_full_followup_content(self):
        created = self._create(
            self._headers(self.owner),
            company_name="Original company",
            contact_name="Original contact",
            intent_summary="Original intent",
            qualification_note="Original qualification",
            region="East",
            address="Original address",
            customer_group_name="Original group",
            business_line="Bags",
        ).json()
        updated = self.client.patch(
            f"/api/v1/crm/leads/{created['id']}",
            headers=self._headers(self.owner),
            json={
                "lead_name": "Updated lead",
                "company_name": "Updated company",
                "contact_name": "Updated contact",
                "contact_phone": "13900138000",
                "source": "referral",
                "region": "West",
                "address": "Updated address",
                "customer_group_name": "Updated group",
                "business_line": "Accessories",
                "intent_summary": "Updated intent",
                "qualification_note": "Updated qualification",
                "status": "active",
                "next_followup_at": "2026-07-13T09:00:00Z",
                "product_intents": [
                    {
                        "product_code": "BAG-001",
                        "product_name": "Updated bag",
                        "quantity_note": "500 units",
                        "interest_level": "high",
                        "note": "Need samples",
                        "sort_order": 3,
                    }
                ],
            },
        )
        self.assertEqual(updated.status_code, 200)
        lead_audits = list(
            self.db.scalars(
                select(AuditLog)
                .where(AuditLog.resource_id == str(created["id"]))
                .order_by(AuditLog.id)
            )
        )
        update_audit = lead_audits[-1]
        self.assertEqual(update_audit.before_data["company_name"], "Original company")
        self.assertEqual(update_audit.after_data["company_name"], "Updated company")
        self.assertEqual(update_audit.before_data["address"], "Original address")
        self.assertEqual(update_audit.after_data["address"], "Updated address")
        self.assertEqual(update_audit.before_data["customer_group_name"], "Original group")
        self.assertEqual(update_audit.after_data["customer_group_name"], "Updated group")
        self.assertEqual(update_audit.before_data["product_intents"][0]["product_name"], "Canvas bag")
        self.assertEqual(update_audit.after_data["product_intents"][0]["product_code"], "BAG-001")
        self.assertEqual(update_audit.after_data["product_intents"][0]["note"], "Need samples")
        self.assertEqual(update_audit.after_data["next_followup_at"], "2026-07-13T09:00:00+00:00")

        followup = self.client.post(
            f"/api/v1/crm/leads/{created['id']}/followups",
            headers=self._headers(self.owner),
            json={
                "content": "Discussed the full sample plan",
                "method": "video",
                "outcome": "Positive",
                "next_action": "Ship samples",
                "next_followup_at": "2026-07-14T09:00:00Z",
            },
        )
        self.assertEqual(followup.status_code, 201)
        followup_audit = self.db.scalar(
            select(AuditLog)
            .where(AuditLog.resource_type == "crm_lead_followup")
            .order_by(AuditLog.id.desc())
        )
        self.assertIsNone(followup_audit.before_data["followup"])
        self.assertEqual(followup_audit.after_data["followup"]["content"], "Discussed the full sample plan")
        self.assertEqual(followup_audit.after_data["followup"]["method"], "video")
        self.assertEqual(followup_audit.after_data["followup"]["outcome"], "Positive")
        self.assertEqual(followup_audit.after_data["followup"]["next_action"], "Ship samples")

    def test_fuzzy_duplicate_check_considers_old_candidates_beyond_former_500_row_window(self):
        historic = CrmLead(
            lead_no="LEAD-HISTORIC",
            lead_name="Historic Textile",
            normalized_name="historictextile",
            owner_user_id=self.owner.id,
            created_by_user_id=self.owner.id,
        )
        self.db.add(historic)
        self.db.flush()
        for index in range(501):
            self.db.add(
                CrmLead(
                    lead_no=f"LEAD-BACKGROUND-{index}",
                    lead_name=f"Background prospect {index}",
                    normalized_name=f"backgroundprospect{index}",
                    owner_user_id=self.owner.id,
                    created_by_user_id=self.owner.id,
                )
            )
        self.db.commit()

        response = self.client.get(
            "/api/v1/crm/leads/duplicate-check",
            headers=self._headers(self.owner),
            params={"lead_name": "Historic Textiles"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(item["lead_id"] == historic.id and "similar_name" in item["reasons"] for item in response.json()["items"]))

    def test_duplicate_advisory_locks_are_deterministic_for_postgres_and_noop_for_sqlite(self):
        lock_keys = lead_duplicate_lock_keys(lead_name="Suzhou Textile", contact_phone="138 0013 8000")
        self.assertEqual(lock_keys, lead_duplicate_lock_keys(lead_name="Suzhou Textile", contact_phone="13800138000"))
        self.assertEqual(lock_keys, sorted(lock_keys, key=lambda item: item[0]))

        postgres_db = Mock()
        postgres_db.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        acquire_lead_duplicate_locks(postgres_db, lead_name="Suzhou Textile", contact_phone="13800138000")
        self.assertEqual(postgres_db.execute.call_count, len(lock_keys))
        for call, (_, expected_lock_key) in zip(postgres_db.execute.call_args_list, lock_keys, strict=True):
            self.assertIn(expected_lock_key, call.args[0].compile().params.values())

        sqlite_db = Mock()
        sqlite_db.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
        acquire_lead_duplicate_locks(sqlite_db, lead_name="Suzhou Textile", contact_phone="13800138000")
        sqlite_db.execute.assert_not_called()

    def test_own_team_all_scope_and_field_masking_are_enforced(self):
        owned_id = self._create(self._headers(self.owner), lead_name="Owned lead").json()["id"]
        self.db.add(CrmLead(lead_no="LEAD-OTHER", lead_name="Other lead", normalized_name="otherlead", contact_phone="13900000000", normalized_phone="13900000000", owner_user_id=self.admin.id, created_by_user_id=self.admin.id))
        self.db.commit()
        own_page = self.client.get("/api/v1/crm/leads", headers=self._headers(self.owner))
        self.assertEqual([item["id"] for item in own_page.json()["items"]], [owned_id])

        self.client.post(f"/api/v1/crm/leads/{owned_id}/assign", headers=self._headers(self.admin), json={"assigned_user_id": self.teammate.id})
        team_page = self.client.get("/api/v1/crm/leads", headers=self._headers(self.teammate))
        self.assertEqual([item["id"] for item in team_page.json()["items"]], [owned_id])
        self.assertEqual(team_page.json()["items"][0]["contact_phone"], "138****8000")
        all_page = self.client.get("/api/v1/crm/leads", headers=self._headers(self.admin))
        self.assertEqual(all_page.json()["total"], 2)
        self.assertEqual(self.client.get("/api/v1/crm/leads", headers=self._headers(self.blocked)).status_code, 403)

    def test_masked_user_cannot_recover_phone_from_internal_normalization_fields(self):
        lead_id = self._create(self._headers(self.owner), lead_name="Masked lead", contact_phone="13800138000").json()["id"]
        assigned = self.client.post(
            f"/api/v1/crm/leads/{lead_id}/assign",
            headers=self._headers(self.admin),
            json={"assigned_user_id": self.teammate.id},
        )
        self.assertEqual(assigned.status_code, 200)

        responses = [
            self.client.get("/api/v1/crm/leads", headers=self._headers(self.teammate)),
            self.client.get(f"/api/v1/crm/leads/{lead_id}", headers=self._headers(self.teammate)),
            self.client.get(
                "/api/v1/crm/leads/duplicate-check",
                headers=self._headers(self.teammate),
                params={"lead_name": "Masked lead", "contact_phone": "13800138000"},
            ),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("13800138000", json.dumps(response.json()))

        self.assertEqual(responses[0].json()["items"][0]["contact_phone"], "138****8000")
        self.assertEqual(responses[1].json()["contact_phone"], "138****8000")
        self.assertEqual(responses[2].json()["items"][0]["contact_phone"], "138****8000")
        for lead_payload in (
            responses[0].json()["items"][0],
            responses[1].json(),
            responses[2].json()["items"][0],
        ):
            self.assertNotIn("normalized_name", lead_payload)
            self.assertNotIn("normalized_phone", lead_payload)

    def test_pagination_and_analytics_use_visible_rows(self):
        self._create(self._headers(self.analytics_user), lead_name="Lead one", contact_phone="13800138001", status="active")
        self._create(self._headers(self.analytics_user), lead_name="Lead two", contact_phone="13800138002", status="qualified")
        self._create(self._headers(self.analytics_user), lead_name="Lead three", contact_phone="13800138003", status="draft")
        page = self.client.get("/api/v1/crm/leads", headers=self._headers(self.analytics_user), params={"limit": 2, "offset": 1})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json()["total"], 3)
        self.assertEqual(len(page.json()["items"]), 2)
        analytics = self.client.get("/api/v1/crm/leads/analytics", headers=self._headers(self.analytics_user))
        self.assertEqual(analytics.status_code, 200)
        self.assertEqual(analytics.json()["summary"]["total"], 3)
        self.assertEqual(analytics.json()["summary"]["by_status"]["active"], 1)


if __name__ == "__main__":
    unittest.main()
