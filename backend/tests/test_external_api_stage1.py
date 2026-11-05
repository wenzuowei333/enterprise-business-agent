import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.mobile_errors import install_mobile_error_contract
from app.api.routes.external_api import external_router
from app.api.routes.external_api_v2 import router as external_v2_router
from app.core.database import Base, get_db
from app.models import ApprovalInstance, AuditLog, CrmProject, CrmProjectCustomerTask, CustomerMaster, CustomerPortraitSnapshot, ExternalApiKey
from app.services.external_api_service import hash_external_token, ip_allowed


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ExternalApiStage1Test(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.token = "pb-ext-stage1-test-token"
        self._seed_data()

        app = FastAPI()
        install_mobile_error_contract(app)
        app.include_router(external_router)
        app.include_router(external_v2_router)

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()

    def _seed_data(self):
        east_customer = CustomerMaster(customer_code="C-EAST", customer_name="East customer", region="East", contact_phone="13800138000")
        west_customer = CustomerMaster(customer_code="C-WEST", customer_name="West customer", region="West", contact_phone="13900139000")
        east_project = CrmProject(project_code="P-EAST", project_name="East project", status="active", approval_status="approved")
        west_project = CrmProject(project_code="P-WEST", project_name="West project", status="active", approval_status="approved")
        self.db.add_all([east_customer, west_customer, east_project, west_project])
        self.db.flush()
        self.east_project_id = east_project.id
        self.west_project_id = west_project.id

        self.db.add_all(
            [
                CrmProjectCustomerTask(
                    project_id=east_project.id,
                    task_code="T-EAST",
                    customer_code=east_customer.customer_code,
                    customer_name_snapshot=east_customer.customer_name,
                    status="in_progress",
                ),
                CrmProjectCustomerTask(
                    project_id=west_project.id,
                    task_code="T-WEST",
                    customer_code=west_customer.customer_code,
                    customer_name_snapshot=west_customer.customer_name,
                    status="in_progress",
                ),
                CrmProjectCustomerTask(
                    project_id=east_project.id,
                    task_code="T-EAST-WEST-CUSTOMER",
                    customer_code=west_customer.customer_code,
                    customer_name_snapshot=west_customer.customer_name,
                    status="closed",
                    is_closed=True,
                ),
                CustomerPortraitSnapshot(customer_code="C-EAST", customer_name="East customer", rule_version="v1", summary_json={"risk": "low"}),
                CustomerPortraitSnapshot(customer_code="C-WEST", customer_name="West customer", rule_version="v1", summary_json={"risk": "secret"}),
            ]
        )
        self.db.flush()

        self.db.add_all(
            [
                ApprovalInstance(
                    approval_no="A-EAST",
                    approval_type="crm_followup_submit",
                    resource_type="crm_followup",
                    resource_id="1",
                    title="East approval",
                    status="under_review",
                    payload_json={"task": {"project_id": east_project.id, "customer_code": "C-EAST"}, "secret": "east-secret"},
                    result_json={"internal": "east-result"},
                ),
                ApprovalInstance(
                    approval_no="A-WEST",
                    approval_type="crm_followup_submit",
                    resource_type="crm_followup",
                    resource_id="2",
                    title="West approval",
                    status="under_review",
                    payload_json={"task": {"project_id": west_project.id, "customer_code": "C-WEST"}, "secret": "west-secret"},
                    result_json={"internal": "west-result"},
                ),
            ]
        )
        key = ExternalApiKey(
            key_id="ext_stage1",
            name="Stage 1 agent",
            owner_name="Integration test",
            key_prefix=self.token[:16],
            key_hash=hash_external_token(self.token),
            scope_region="East",
            scope_project_ids=[east_project.id],
            allowed_customer_fields=["customer_code", "customer_name"],
            can_read_projects=True,
            can_read_customers=True,
            can_read_followups=True,
            can_read_judgements=True,
            can_read_tasks=True,
            can_read_approvals=True,
            can_read_audit_summary=True,
        )
        self.db.add(key)
        self.db.flush()
        self.db.add_all(
            [
                AuditLog(action_type="external_api_read", resource_type="external_api", resource_id=key.key_id, after_data={"endpoint": "/seed"}),
                AuditLog(action_type="user_update", resource_type="user", resource_id="999", after_data={"password_hash": "must-not-leak"}),
            ]
        )
        self.db.commit()

    def _headers(self, request_id: str | None = None):
        headers = {"Authorization": f"Bearer {self.token}"}
        if request_id:
            headers["X-Request-ID"] = request_id
        return headers

    def test_v2_me_uses_stable_envelope_and_safe_key_identity(self):
        response = self.client.get("/api/external/v2/me", headers=self._headers("req-stage1"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "req-stage1")
        payload = response.json()
        self.assertEqual(payload["meta"]["request_id"], "req-stage1")
        self.assertEqual(payload["meta"]["schema_version"], "2.0")
        self.assertEqual(payload["data"]["key"]["data_scope"]["project_ids"], [self.east_project_id])
        self.assertTrue(payload["data"]["key"]["readonly"])
        self.assertNotIn("key_hash", response.text)
        self.assertNotIn("last_used_ip", response.text)
        self.assertNotIn("created_by_user_id", response.text)

    def test_v2_capabilities_and_dictionaries_are_machine_readable(self):
        capabilities = self.client.get("/api/external/v2/capabilities", headers=self._headers())
        dictionaries = self.client.get("/api/external/v2/dictionaries", headers=self._headers())

        self.assertEqual(capabilities.status_code, 200)
        codes = {item["code"] for item in capabilities.json()["data"]["capabilities"]}
        self.assertIn("projects.read", codes)
        self.assertIn("approvals.read", codes)
        self.assertEqual(dictionaries.status_code, 200)
        project_statuses = {item["code"]: item["label"] for item in dictionaries.json()["data"]["project_statuses"]}
        self.assertEqual(project_statuses["active"], "进行中")

    def test_v2_auth_errors_follow_external_contract(self):
        response = self.client.get("/api/external/v2/me", headers={"X-Request-ID": "req-denied"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["X-Request-ID"], "req-denied")
        self.assertEqual(
            response.json(),
            {
                "error": {
                    "code": "http_401",
                    "message": "Missing external API key",
                    "details": [],
                    "request_id": "req-denied",
                }
            },
        )

    def test_v1_overview_applies_project_and_region_scope(self):
        response = self.client.get("/api/external/v1/overview", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        stats = response.json()["stats"]
        self.assertEqual(stats["projects"], 1)
        self.assertEqual(stats["customers"], 1)
        self.assertEqual(stats["tasks"], 1)
        self.assertEqual(stats["approvals"], 1)
        self.assertEqual(stats["judgements"], 1)

    def test_v1_lists_do_not_cross_scope_or_expose_approval_snapshots(self):
        tasks = self.client.get("/api/external/v1/tasks", headers=self._headers())
        judgements = self.client.get("/api/external/v1/judgements", headers=self._headers())
        approvals = self.client.get("/api/external/v1/approvals", headers=self._headers())

        self.assertEqual([item["task_code"] for item in tasks.json()["tasks"]], ["T-EAST"])
        self.assertEqual([item["customer_code"] for item in judgements.json()["judgements"]], ["C-EAST"])
        self.assertEqual([item["approval_no"] for item in approvals.json()["approvals"]], ["A-EAST"])
        self.assertNotIn("payload_json", approvals.text)
        self.assertNotIn("result_json", approvals.text)
        self.assertNotIn("west-secret", approvals.text)

    def test_v1_project_detail_aggregates_only_visible_customers(self):
        response = self.client.get(f"/api/external/v1/projects/{self.east_project_id}", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(payload["summary"]["closed"], 0)
        self.assertEqual(payload["project"]["task_total"], 1)
        self.assertEqual([item["customer_code"] for item in payload["customers"]], ["C-EAST"])

    def test_v1_audit_summary_only_returns_current_key_usage(self):
        response = self.client.get("/api/external/v1/audit-summary", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("must-not-leak", response.text)
        self.assertTrue(all(set(item) == {"id", "action_type", "endpoint", "created_at"} for item in response.json()["recent"]))
        self.assertTrue(all(item["action_type"] == "external_api_read" for item in response.json()["recent"]))

    def test_ip_allowlist_supports_exact_addresses_and_cidr(self):
        self.assertTrue(ip_allowed("10.10.1.25", ["10.10.1.0/24"]))
        self.assertFalse(ip_allowed("10.10.2.25", ["10.10.1.0/24"]))
        self.assertTrue(ip_allowed("testclient", ["testclient"]))
        self.assertFalse(ip_allowed(None, ["10.10.1.0/24"]))


if __name__ == "__main__":
    unittest.main()
