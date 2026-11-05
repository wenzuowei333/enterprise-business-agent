import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CrmFollowupBusinessProfileFlagSourceTest(unittest.TestCase):
    def test_model_schema_and_audit_snapshot_expose_business_profile_update_flag(self):
        model_source = (ROOT / "app" / "models" / "crm.py").read_text(encoding="utf-8")
        schema_source = (ROOT / "app" / "schemas" / "crm.py").read_text(encoding="utf-8")
        service_source = (ROOT / "app" / "services" / "crm_project_service.py").read_text(encoding="utf-8")

        self.assertIn("business_profile_updated", model_source)
        self.assertIn("business_profile_updated: bool", schema_source)
        self.assertIn('"business_profile_updated": followup.business_profile_updated', service_source)
