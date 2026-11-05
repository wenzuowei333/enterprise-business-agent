import unittest
from unittest.mock import patch

from app.api.routes.mobile import mobile_bootstrap
from app.models import User


class MobileApiTest(unittest.TestCase):
    def test_bootstrap_exposes_version_and_feature_flags(self):
        user = User(
            id=1,
            username="admin",
            password_hash="hash",
            real_name="施总",
            role="admin",
            status="active",
            is_active=True,
        )

        with (
            patch("app.api.routes.mobile.get_final_permission_codes", return_value=["dashboard.view"]),
            patch("app.api.routes.mobile._visible_nav", return_value=[{"key": "home", "label": "工作台"}]),
            patch("app.api.routes.mobile._mobile_scope_revision", return_value="scope-test"),
        ):
            payload = mobile_bootstrap(db=object(), current_user=user)

        app_config = payload["app"]
        self.assertEqual(app_config["latest_version"], "1.6.0")
        self.assertEqual(app_config["latest_version_code"], 7)
        self.assertEqual(app_config["minimum_supported_version"], "1.0.0")
        self.assertEqual(app_config["page_size"], 20)
        self.assertEqual(app_config["ui_theme_version"], "liquid_v1")
        self.assertTrue(app_config["mobile_feature_liquid_ui"])
        self.assertTrue(app_config["mobile_feature_liquid_full_effect"])
        self.assertTrue(app_config["mobile_feature_dark_theme"])
        self.assertFalse(app_config["force_reduced_glass"])
        self.assertEqual(
            app_config["feature_flags"],
            {
                "project_application": False,
                "crm_customers": False,
                "crm_tasks": False,
                "crm_followups": False,
                "crm_approvals": True,
                "data_query": False,
                "checks": False,
                "notifications": False,
                "scanner": False,
                "manager_dashboard": False,
                "ai": False,
                "offline_read": False,
                "offline_outbox": False,
                "sync_conflict": False,
                "in_app_update": False,
                "device_management": False,
                "operations_console": False,
                "onboarding": False,
                "in_app_feedback": False,
                "voice_input": False,
                "contact_ocr": False,
                "ai_drafts": False,
                "smart_reminders": False,
                "adoption_dashboard": False,
                "exception_center": False,
                "customer_tags": False,
                "fulfillment": False,
                "lead_pool": False,
                "lead_ocr": False,
                "lead_offline": False,
                "lead_conversion": False,
                "lead_product_intent": False,
                "lead_analytics": False,
                "liquid_ui": True,
                "liquid_full_effect": True,
                "dark_theme": True,
                "lead_sla": False,
                "lead_public_pool": False,
                "lead_campaign": False,
                "lead_team_dashboard": False,
                "lead_bulk_assignment": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
