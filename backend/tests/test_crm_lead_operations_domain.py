import importlib.util
import unittest
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import CrmLead, CrmLeadAssignmentEvent, CrmLeadCampaign, CrmLeadOperationPolicy, Permission, Role, RolePermission
from app.schemas.crm import CrmLeadCampaignCreate, CrmLeadOperationPolicyUpdate
from app.services.crm_lead_service import get_lead_operation_policy
from app.services.seed_stage1 import PERMISSION_SEEDS, seed_stage1


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CrmLeadOperationsDomainTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()

    def test_operations_models_default_to_private_lead_and_safe_policy(self):
        campaign = CrmLeadCampaign(campaign_code="CMP-001", campaign_name="夏季新客开发")
        policy = CrmLeadOperationPolicy(policy_key="default")
        self.db.add(campaign)
        self.db.flush()
        lead = CrmLead(
            lead_no="LEAD-OPS-001",
            lead_name="运营线索",
            normalized_name="运营线索",
            campaign_id=campaign.id,
        )
        self.db.add_all([policy, lead])
        self.db.commit()

        self.assertEqual(lead.pool_status, "private")
        self.assertEqual(lead.priority, "normal")
        self.assertEqual(lead.recycle_count, 0)
        self.assertEqual(policy.first_response_hours, 24)
        self.assertEqual(policy.next_followup_hours, 72)
        self.assertEqual(policy.assignment_hold_hours, 168)
        self.assertEqual(policy.daily_claim_limit, 10)
        self.assertEqual(lead.campaign_id, campaign.id)

    def test_missing_persisted_policy_uses_materialized_safe_defaults(self):
        policy = get_lead_operation_policy(self.db)

        self.assertEqual(policy.policy_key, "default")
        self.assertEqual(policy.first_response_hours, 24)
        self.assertEqual(policy.next_followup_hours, 72)
        self.assertEqual(policy.assignment_hold_hours, 168)
        self.assertEqual(policy.due_soon_hours, 4)
        self.assertEqual(policy.daily_claim_limit, 10)

    def test_operations_contracts_reject_invalid_policy_and_campaign_values(self):
        with self.assertRaises(ValidationError):
            CrmLeadOperationPolicyUpdate(first_response_hours=0)
        with self.assertRaises(ValidationError):
            CrmLeadOperationPolicyUpdate(daily_claim_limit=-1)
        with self.assertRaises(ValidationError):
            CrmLeadCampaignCreate(campaign_code="CMP-INVALID", campaign_name="无效活动", status="unknown")

        valid = CrmLeadOperationPolicyUpdate(first_response_hours=12, next_followup_hours=48)
        self.assertEqual(valid.first_response_hours, 12)
        self.assertEqual(valid.next_followup_hours, 48)

    def test_operations_storage_enforces_pool_and_event_contracts(self):
        with self.assertRaises(ValueError):
            CrmLead(
                lead_no="LEAD-OPS-INVALID",
                lead_name="非法公海状态",
                normalized_name="非法公海状态",
                pool_status="anything",
            )
        with self.assertRaises(ValueError):
            CrmLeadAssignmentEvent(lead_id=1, event_type="anything")

        with self.assertRaises(IntegrityError):
            self.db.execute(CrmLeadAssignmentEvent.__table__.insert().values(lead_id=1, event_type="anything"))
            self.db.commit()
        self.db.rollback()

    def test_operations_indexes_support_campaign_pool_and_sla_queries(self):
        inspector = inspect(self.engine)
        indexes = {index["name"] for index in inspector.get_indexes("crm_lead")}
        self.assertTrue(
            {
                "ix_crm_lead_campaign_status",
                "ix_crm_lead_pool_status_assigned",
                "ix_crm_lead_sla_first_response",
            }.issubset(indexes)
        )

    def test_operations_permissions_are_seeded_for_expected_roles(self):
        permission_codes = {code for code, _, _, _ in PERMISSION_SEEDS}
        self.assertTrue(
            {
                "crm_lead.claim",
                "crm_lead.recycle",
                "crm_lead.analytics",
                "crm_lead_campaign.view",
                "crm_lead_campaign.manage",
                "crm_lead_policy.manage",
            }.issubset(permission_codes)
        )

    def test_operations_role_grants_follow_the_least_privilege_matrix(self):
        seed_stage1(self.db)
        expected = {
            "admin": {
                "crm_lead.claim",
                "crm_lead.recycle",
                "crm_lead.analytics",
                "crm_lead_campaign.view",
                "crm_lead_campaign.manage",
                "crm_lead_policy.manage",
            },
            "boss": {"crm_lead.analytics", "crm_lead_campaign.view"},
            "business_middle_office": {
                "crm_lead.claim",
                "crm_lead.recycle",
                "crm_lead.analytics",
                "crm_lead_campaign.view",
            },
            "salesperson": {"crm_lead.claim"},
        }
        for role_code, permission_codes in expected.items():
            with self.subTest(role_code=role_code):
                granted = set(
                    self.db.scalars(
                        select(Permission.permission_code)
                        .join(RolePermission, RolePermission.permission_id == Permission.id)
                        .join(Role, Role.id == RolePermission.role_id)
                        .where(Role.role_code == role_code)
                    )
                )
                self.assertTrue(permission_codes.issubset(granted))

    def test_migration_declares_forward_and_backward_operations(self):
        path = Path(__file__).parents[1] / "alembic" / "versions" / "20260720_0100_crm_lead_operations.py"
        spec = importlib.util.spec_from_file_location("crm_lead_operations_migration", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertEqual(module.revision, "20260720_0100")
        self.assertEqual(module.down_revision, "20260713_0100")
        self.assertTrue(callable(module.upgrade))
        self.assertTrue(callable(module.downgrade))


if __name__ == "__main__":
    unittest.main()
