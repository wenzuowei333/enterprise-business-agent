import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import CrmLead, CrmLeadAssignmentEvent, CrmLeadFollowup, CrmLeadProductIntent, DataScopeRule, User
from app.models.crm import CRM_APPROVAL_TYPES, CRM_LEAD_STATUSES
from app.schemas.crm import CrmLeadCreate, CrmLeadFollowupCreate, CrmLeadUpdate
from app.services.crm_access_service import crm_lead_scope_filter
from app.services.seed_stage1 import PERMISSION_SEEDS


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CrmLeadDomainTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.owner = User(
            username="lead-owner",
            password_hash="hash",
            real_name="Lead Owner",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.assignee = User(
            username="lead-assignee",
            password_hash="hash",
            real_name="Lead Assignee",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.db.add_all([self.owner, self.assignee])
        self.db.flush()

    def tearDown(self):
        self.db.close()

    def test_lead_models_expose_statuses_and_linked_records(self):
        self.assertEqual(
            CRM_LEAD_STATUSES,
            ("draft", "active", "qualified", "conversion_pending", "converted", "closed", "rejected"),
        )
        self.assertIn("crm_lead_convert", CRM_APPROVAL_TYPES)

        lead = CrmLead(
            lead_no="LEAD-001",
            lead_name="Suzhou Prospect",
            normalized_name="suzhou prospect",
            contact_phone="13800138000",
            normalized_phone="13800138000",
            owner_user_id=self.owner.id,
            assigned_user_id=self.assignee.id,
            created_by_user_id=self.owner.id,
        )
        self.db.add(lead)
        self.db.flush()
        self.db.add_all(
            [
                CrmLeadFollowup(lead_id=lead.id, followup_no="LF-001", content="Initial call", created_by_user_id=self.owner.id),
                CrmLeadAssignmentEvent(
                    lead_id=lead.id,
                    from_assignee_user_id=self.owner.id,
                    to_assignee_user_id=self.assignee.id,
                    assigned_by_user_id=self.owner.id,
                ),
                CrmLeadProductIntent(lead_id=lead.id, product_name="Custom bag", sort_order=1),
            ]
        )
        self.db.commit()

        self.assertEqual(lead.status, "draft")
        self.assertEqual(self.db.scalar(select(CrmLeadFollowup).where(CrmLeadFollowup.lead_id == lead.id)).followup_no, "LF-001")
        self.assertEqual(self.db.scalar(select(CrmLeadAssignmentEvent).where(CrmLeadAssignmentEvent.lead_id == lead.id)).to_assignee_user_id, self.assignee.id)
        self.assertEqual(self.db.scalar(select(CrmLeadProductIntent).where(CrmLeadProductIntent.lead_id == lead.id)).product_name, "Custom bag")

    def test_lead_contracts_accept_create_and_followup_payloads(self):
        lead = CrmLeadCreate(lead_name="Suzhou Prospect", contact_phone="13800138000")
        followup = CrmLeadFollowupCreate(content="Initial call")

        self.assertEqual(lead.status, "draft")
        self.assertEqual(followup.content, "Initial call")

    def test_lead_contracts_reject_invalid_and_conversion_creation_statuses(self):
        for status in ("conversion_pending", "converted", "invalid"):
            with self.subTest(status=status):
                with self.assertRaises(ValidationError):
                    CrmLeadCreate(lead_name="Suzhou Prospect", status=status)

        with self.assertRaises(ValidationError):
            CrmLeadUpdate(status="invalid")

        self.assertEqual(CrmLeadUpdate(status="converted").status, "converted")

    def test_lead_model_and_database_reject_invalid_statuses(self):
        with self.assertRaises(ValueError):
            CrmLead(
                lead_no="LEAD-INVALID-MODEL",
                lead_name="Invalid model status",
                normalized_name="invalid model status",
                status="invalid",
            )

        with self.assertRaises(IntegrityError):
            self.db.execute(
                CrmLead.__table__.insert().values(
                    lead_no="LEAD-INVALID-DB",
                    lead_name="Invalid database status",
                    normalized_name="invalid database status",
                    status="invalid",
                )
            )
            self.db.commit()
        self.db.rollback()

    def test_lead_storage_allows_duplicate_normalized_identity_for_review(self):
        self.db.add_all(
            [
                CrmLead(
                    lead_no="LEAD-DUPLICATE-1",
                    lead_name="Duplicate prospect",
                    normalized_name="duplicate prospect",
                    contact_phone="13800138000",
                    normalized_phone="13800138000",
                ),
                CrmLead(
                    lead_no="LEAD-DUPLICATE-2",
                    lead_name="Duplicate prospect",
                    normalized_name="duplicate prospect",
                    contact_phone="13800138000",
                    normalized_phone="13800138000",
                ),
            ]
        )
        self.db.commit()

        rows = self.db.scalars(select(CrmLead).where(CrmLead.normalized_phone == "13800138000")).all()
        self.assertEqual([row.lead_no for row in rows], ["LEAD-DUPLICATE-1", "LEAD-DUPLICATE-2"])

    def test_lead_scope_limits_own_and_assigned_records(self):
        own = CrmLead(
            lead_no="LEAD-OWN",
            lead_name="Own lead",
            normalized_name="own lead",
            owner_user_id=self.owner.id,
            created_by_user_id=self.owner.id,
        )
        assigned = CrmLead(
            lead_no="LEAD-ASSIGNED",
            lead_name="Assigned lead",
            normalized_name="assigned lead",
            assigned_user_id=self.owner.id,
            created_by_user_id=self.assignee.id,
        )
        other = CrmLead(
            lead_no="LEAD-OTHER",
            lead_name="Other lead",
            normalized_name="other lead",
            owner_user_id=self.assignee.id,
            created_by_user_id=self.assignee.id,
        )
        self.db.add_all([own, assigned, other])
        self.db.add(DataScopeRule(subject_type="role", subject_id="salesperson", resource_type="crm_lead", scope_mode="own", scope_value=None))
        self.db.commit()

        own_rows = self.db.scalars(crm_lead_scope_filter(select(CrmLead).order_by(CrmLead.lead_no), self.db, self.owner)).all()
        self.assertEqual([row.lead_no for row in own_rows], ["LEAD-ASSIGNED", "LEAD-OWN"])

        self.db.add(DataScopeRule(subject_type="user", subject_id=str(self.owner.id), resource_type="crm_lead", scope_mode="assigned", scope_value=None))
        self.db.commit()
        assigned_rows = self.db.scalars(crm_lead_scope_filter(select(CrmLead), self.db, self.owner)).all()
        self.assertEqual([row.lead_no for row in assigned_rows], ["LEAD-ASSIGNED"])

    def test_lead_scope_limits_custom_lead_ids_and_owner_user_ids(self):
        explicit = CrmLead(
            lead_no="LEAD-CUSTOM-ID",
            lead_name="Explicit custom lead",
            normalized_name="explicit custom lead",
            owner_user_id=self.owner.id,
            created_by_user_id=self.owner.id,
        )
        owner_match = CrmLead(
            lead_no="LEAD-CUSTOM-OWNER",
            lead_name="Owner custom lead",
            normalized_name="owner custom lead",
            owner_user_id=self.assignee.id,
            created_by_user_id=self.assignee.id,
        )
        excluded = CrmLead(
            lead_no="LEAD-CUSTOM-EXCLUDED",
            lead_name="Excluded custom lead",
            normalized_name="excluded custom lead",
            created_by_user_id=self.owner.id,
        )
        self.db.add_all([explicit, owner_match, excluded])
        self.db.flush()
        self.db.add(
            DataScopeRule(
                subject_type="user",
                subject_id=str(self.owner.id),
                resource_type="crm_lead",
                scope_mode="custom",
                scope_value={"lead_ids": [explicit.id], "owner_user_ids": [self.assignee.id]},
            )
        )
        self.db.commit()

        rows = self.db.scalars(
            crm_lead_scope_filter(select(CrmLead).order_by(CrmLead.lead_no), self.db, self.owner)
        ).all()
        self.assertEqual([row.lead_no for row in rows], ["LEAD-CUSTOM-ID", "LEAD-CUSTOM-OWNER"])

    def test_lead_permissions_are_seeded(self):
        permission_codes = {code for code, _, _, _ in PERMISSION_SEEDS}
        self.assertTrue(
            {
                "crm_lead.view",
                "crm_lead.create",
                "crm_lead.edit",
                "crm_lead.assign",
                "crm_lead.convert",
                "crm_lead.approve",
            }.issubset(permission_codes)
        )


if __name__ == "__main__":
    unittest.main()
