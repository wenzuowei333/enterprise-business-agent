import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.api.mobile_errors import install_mobile_error_contract
from app.api.routes.external_api import (
    ExternalApiKeyRotate,
    _key_public,
    external_api_catalog,
    rotate_external_api_key,
)
from app.api.routes.external_api_v2 import router as external_v2_router
from app.api.routes.external_api_v2_governance import router as governance_router
from app.core.database import Base, get_db
from app.models import (
    AuditLog,
    CrmProject,
    CrmProjectCustomerTask,
    CustomerMaster,
    ExternalApiKey,
    ExternalApiUsageLog,
    User,
)
from app.services.external_api_service import hash_external_token


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ExternalApiStage4Test(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.token = "pb-ext-stage4-governed"
        self.low_token = "pb-ext-stage4-low-quota"
        self.other_token = "pb-ext-stage4-other"
        self._seed_data()

        app = FastAPI()
        install_mobile_error_contract(app)
        app.include_router(external_v2_router)
        app.include_router(governance_router)

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()

    def _seed_data(self):
        east = CustomerMaster(customer_code="C-EAST", customer_name="East customer", region="East")
        west = CustomerMaster(customer_code="C-WEST", customer_name="West customer", region="West")
        self.db.add_all([east, west])
        self.db.flush()
        visible_project = CrmProject(
            project_code="P-VISIBLE",
            project_name="Visible project",
            status="active",
            approval_status="approved",
        )
        hidden_project = CrmProject(
            project_code="P-HIDDEN",
            project_name="Hidden project",
            status="active",
            approval_status="approved",
        )
        self.db.add_all([visible_project, hidden_project])
        self.db.flush()
        self.visible_project_id = visible_project.id
        self.hidden_project_id = hidden_project.id
        self.db.add_all(
            [
                CrmProjectCustomerTask(
                    project_id=visible_project.id,
                    task_code="T-VISIBLE",
                    customer_code=east.customer_code,
                    customer_name_snapshot=east.customer_name,
                ),
                CrmProjectCustomerTask(
                    project_id=hidden_project.id,
                    task_code="T-HIDDEN",
                    customer_code=west.customer_code,
                    customer_name_snapshot=west.customer_name,
                ),
            ]
        )
        self.db.add_all(
            [
                AuditLog(
                    action_type="crm_project_update",
                    resource_type="crm_project",
                    resource_id=str(visible_project.id),
                    before_data={"status": "submitted", "password_hash": "OLD SECRET"},
                    after_data={"project_id": visible_project.id, "status": "active", "secret_note": "NEW SECRET"},
                ),
                AuditLog(
                    action_type="crm_project_update",
                    resource_type="crm_project",
                    resource_id=str(hidden_project.id),
                    after_data={"project_id": hidden_project.id, "status": "active"},
                ),
                AuditLog(
                    action_type="crm_task_update",
                    resource_type="crm_task",
                    resource_id="1",
                    after_data={"project_id": visible_project.id, "customer_code": east.customer_code, "status": "closed"},
                ),
                AuditLog(
                    action_type="product_update",
                    resource_type="product_master",
                    resource_id="PR-SECRET",
                    after_data={"product_code": "PR-SECRET", "reference_cost": "99.99"},
                ),
            ]
        )
        governed = ExternalApiKey(
            key_id="ext_stage4_governed",
            name="Governed agent",
            key_prefix=self.token[:16],
            key_hash=hash_external_token(self.token),
            scope_region="East",
            scope_project_ids=[visible_project.id],
            allowed_customer_fields=["customer_code", "customer_name"],
            can_read_projects=False,
            can_read_tasks=False,
            can_read_audit_summary=False,
            can_read_changes=False,
            permission_scopes=["projects.read", "tasks.read", "changes.read", "usage.read"],
            rate_limit_per_minute=20,
            daily_request_limit=100,
        )
        low_quota = ExternalApiKey(
            key_id="ext_stage4_low",
            name="Low quota agent",
            key_prefix=self.low_token[:16],
            key_hash=hash_external_token(self.low_token),
            allowed_customer_fields=["customer_code", "customer_name"],
            permission_scopes=["projects.read"],
            rate_limit_per_minute=2,
            daily_request_limit=10,
        )
        other = ExternalApiKey(
            key_id="ext_stage4_other",
            name="Other agent",
            key_prefix=self.other_token[:16],
            key_hash=hash_external_token(self.other_token),
            allowed_customer_fields=["customer_code", "customer_name"],
            permission_scopes=["usage.read"],
            rate_limit_per_minute=20,
            daily_request_limit=100,
        )
        admin = User(
            username="stage4-admin",
            password_hash="hash",
            real_name="Stage 4 admin",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add_all([governed, low_quota, other, admin])
        self.db.commit()
        self.admin = admin

    def _headers(self, token=None):
        return {"Authorization": f"Bearer {token or self.token}"}

    def _request(self, path: str) -> Request:
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": [],
                "client": ("127.0.0.1", 50000),
                "scheme": "http",
                "server": ("testserver", 80),
                "query_string": b"",
            }
        )

    def test_capability_scopes_override_legacy_boolean_flags(self):
        capabilities = self.client.get("/api/external/v2/capabilities", headers=self._headers())
        identity = self.client.get("/api/external/v2/me", headers=self._headers())

        self.assertEqual(capabilities.status_code, 200)
        values = {item["code"]: item["enabled"] for item in capabilities.json()["data"]["capabilities"]}
        self.assertTrue(values["projects.read"])
        self.assertTrue(values["changes.read"])
        self.assertFalse(values["products.read"])
        key = identity.json()["data"]["key"]
        self.assertEqual(key["permission_scopes"], ["projects.read", "tasks.read", "usage.read", "changes.read"])
        self.assertEqual(key["rate_limit_per_minute"], 20)
        self.assertEqual(key["daily_request_limit"], 100)

    def test_usage_logs_capture_status_duration_and_are_key_isolated(self):
        first = self.client.get("/api/external/v2/me", headers=self._headers())
        other = self.client.get("/api/external/v2/me", headers=self._headers(self.other_token))
        usage = self.client.get("/api/external/v2/usage", headers=self._headers())

        self.assertEqual(first.status_code, 200)
        self.assertEqual(other.status_code, 200)
        self.assertEqual(usage.status_code, 200)
        self.db.expire_all()
        governed_rows = list(
            self.db.scalars(
                select(ExternalApiUsageLog).where(ExternalApiUsageLog.key_id == "ext_stage4_governed")
            ).all()
        )
        self.assertGreaterEqual(len(governed_rows), 2)
        self.assertTrue(all(row.status_code == 200 for row in governed_rows))
        self.assertTrue(all(row.duration_ms is not None and row.duration_ms >= 0 for row in governed_rows))
        self.assertNotIn("ext_stage4_other", usage.text)
        self.assertTrue(all(item["endpoint"].startswith("/api/external/v2/") for item in usage.json()["data"]["recent"]))

    def test_minute_quota_returns_429_with_retry_after(self):
        fixed_now = datetime.now(timezone.utc)
        with patch("app.services.external_api_service.external_now", return_value=fixed_now):
            first = self.client.get("/api/external/v2/me", headers=self._headers(self.low_token))
            second = self.client.get("/api/external/v2/me", headers=self._headers(self.low_token))
            limited = self.client.get("/api/external/v2/me", headers=self._headers(self.low_token))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["retry-after"], "60")
        self.assertEqual(limited.json()["error"]["code"], "http_429")

    def test_daily_quota_returns_429_with_remaining_day_retry(self):
        key = self.db.scalar(select(ExternalApiKey).where(ExternalApiKey.key_id == "ext_stage4_low"))
        key.rate_limit_per_minute = 10
        key.daily_request_limit = 1
        self.db.commit()

        first = self.client.get("/api/external/v2/me", headers=self._headers(self.low_token))
        limited = self.client.get("/api/external/v2/me", headers=self._headers(self.low_token))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(limited.status_code, 429)
        self.assertGreater(int(limited.headers["retry-after"]), 0)
        self.assertIn("daily quota", limited.json()["error"]["message"])

    def test_change_feed_is_scoped_permission_aware_sanitized_and_cursor_stable(self):
        first = self.client.get("/api/external/v2/changes", headers=self._headers(), params={"limit": 1})
        cursor = first.json()["meta"]["next_cursor"]
        second = self.client.get(
            "/api/external/v2/changes", headers=self._headers(), params={"limit": 1, "cursor": cursor}
        )

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["meta"]["has_more"])
        self.assertIsNotNone(cursor)
        first_item = first.json()["data"]["items"][0]
        second_item = second.json()["data"]["items"][0]
        self.assertNotEqual(first_item["change_id"], second_item["change_id"])
        combined = first.text + second.text
        self.assertNotIn("P-HIDDEN", combined)
        self.assertNotIn(str(self.hidden_project_id), [str(item.get("project_id")) for item in [first_item, second_item]])
        self.assertNotIn("PR-SECRET", combined)
        self.assertNotIn("OLD SECRET", combined)
        self.assertNotIn("NEW SECRET", combined)
        self.assertNotIn("password_hash", combined)
        self.assertNotIn("secret_note", combined)

    def test_rotation_supports_bounded_old_key_grace_without_exposing_hashes(self):
        result = rotate_external_api_key(
            "ext_stage4_governed",
            ExternalApiKeyRotate(grace_minutes=15),
            self._request("/api/v1/external-api/keys/ext_stage4_governed/rotate"),
            db=self.db,
            current_user=self.admin,
        )
        new_token = result["api_key"]
        public_key = result["key"]

        self.assertNotEqual(new_token, self.token)
        self.assertEqual(public_key["rotation_count"], 1)
        self.assertIsNotNone(public_key["previous_key_expires_at"])
        self.assertNotIn("key_hash", public_key)
        self.assertNotIn("previous_key_hash", public_key)
        self.assertEqual(self.client.get("/api/external/v2/me", headers=self._headers(self.token)).status_code, 200)
        self.assertEqual(self.client.get("/api/external/v2/me", headers=self._headers(new_token)).status_code, 200)

        key = self.db.scalar(select(ExternalApiKey).where(ExternalApiKey.key_id == "ext_stage4_governed"))
        key.previous_key_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.db.commit()
        self.assertEqual(self.client.get("/api/external/v2/me", headers=self._headers(self.token)).status_code, 401)
        self.assertEqual(self.client.get("/api/external/v2/me", headers=self._headers(new_token)).status_code, 200)

    def test_management_catalog_and_public_key_include_governance_without_secrets(self):
        key = self.db.scalar(select(ExternalApiKey).where(ExternalApiKey.key_id == "ext_stage4_governed"))
        public = _key_public(key)
        catalog = external_api_catalog()

        self.assertEqual(catalog["base_url"], "/api/external/v2")
        self.assertEqual(catalog["schema_version"], "2.0")
        self.assertGreaterEqual(len(catalog["endpoints"]), 27)
        self.assertEqual(public["rate_limit_per_minute"], 20)
        self.assertEqual(public["daily_request_limit"], 100)
        self.assertNotIn("key_hash", public)
        self.assertNotIn("previous_key_hash", public)

    def test_governance_migration_upgrades_and_downgrades_real_database(self):
        backend_dir = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "governance.db"
            migration_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with migration_engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE external_api_keys (id INTEGER PRIMARY KEY, key_id VARCHAR(120) NOT NULL UNIQUE)"
                )
                connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
                connection.exec_driver_sql("INSERT INTO alembic_version (version_num) VALUES ('20260721_0100')")
            environment = os.environ.copy()
            environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"

            upgrade = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=backend_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(upgrade.returncode, 0, upgrade.stderr)
            tables = set(inspect(migration_engine).get_table_names())
            columns = {column["name"] for column in inspect(migration_engine).get_columns("external_api_keys")}
            self.assertIn("external_api_usage_log", tables)
            self.assertIn("permission_scopes", columns)
            self.assertIn("previous_key_hash", columns)
            self.assertIn("can_read_changes", columns)

            downgrade = subprocess.run(
                [sys.executable, "-m", "alembic", "downgrade", "20260721_0100"],
                cwd=backend_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(downgrade.returncode, 0, downgrade.stderr)
            self.assertNotIn("external_api_usage_log", inspect(migration_engine).get_table_names())
            downgraded = {column["name"] for column in inspect(migration_engine).get_columns("external_api_keys")}
            self.assertNotIn("permission_scopes", downgraded)
            migration_engine.dispose()


if __name__ == "__main__":
    unittest.main()
