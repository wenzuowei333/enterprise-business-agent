import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CrmCustomerPanoramaStage2SourceTest(unittest.TestCase):
    def test_followup_response_exposes_customer_name_and_pending_review_scope(self):
        schema_source = (ROOT / "app" / "schemas" / "crm.py").read_text(encoding="utf-8")
        route_source = (ROOT / "app" / "api" / "routes" / "crm_projects.py").read_text(encoding="utf-8")

        self.assertIn("customer_name: str | None = None", schema_source)
        self.assertIn("review_scope: str | None = None", route_source)
        self.assertIn('review_scope == "pending"', route_source)
        self.assertIn('CrmFollowup.review_status.in_(["pending", "need_supplement"])', route_source)

    def test_linked_customer_scope_supports_panorama_metric_filters(self):
        route_source = (ROOT / "app" / "api" / "routes" / "crm_projects.py").read_text(encoding="utf-8")

        self.assertIn('scope == "profile_incomplete"', route_source)
        self.assertIn('scope == "pending_action"', route_source)


if __name__ == "__main__":
    unittest.main()
