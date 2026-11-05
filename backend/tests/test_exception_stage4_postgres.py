from __future__ import annotations

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes.exceptions import router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import AuditLog, ExceptionPolicy, Permission, Role, RolePermission, User


STAGE4_TEST_DATABASE_URL = os.getenv("STAGE4_TEST_DATABASE_URL", "").strip()


@unittest.skipUnless(STAGE4_TEST_DATABASE_URL, "STAGE4_TEST_DATABASE_URL is not configured")
class ExceptionStage4PostgresConcurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        database_url = make_url(STAGE4_TEST_DATABASE_URL)
        if database_url.get_backend_name() != "postgresql":
            raise unittest.SkipTest("STAGE4_TEST_DATABASE_URL must use PostgreSQL")

        cls.schema_name = f"stage4_baseline_{uuid4().hex}"
        cls.admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
        with cls.admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{cls.schema_name}"')

        cls.engine = create_engine(
            database_url,
            connect_args={"options": f"-csearch_path={cls.schema_name},public"},
            pool_pre_ping=True,
            pool_size=12,
            max_overflow=4,
        )
        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine, autoflush=False, expire_on_commit=False)

        with cls.SessionLocal() as db:
            role = Role(role_code="stage4_policy_admin", role_name="Stage 4 policy admin")
            db.add(role)
            db.flush()
            user = User(
                username="stage4-postgres-policy-admin",
                password_hash="hash",
                real_name="Stage 4 PostgreSQL Policy Admin",
                role=role.role_code,
                status="active",
                is_active=True,
            )
            db.add(user)
            db.flush()
            for code in (
                "exception_center.policy_manage",
                "crm_task.view",
                "crm_followup.view",
            ):
                permission = Permission(
                    permission_code=code,
                    permission_name=code,
                    resource_type=code.split(".", 1)[0],
                    action_type=code.rsplit(".", 1)[-1],
                )
                db.add(permission)
                db.flush()
                db.add(RolePermission(role_id=role.id, permission_id=permission.id))
            policy = ExceptionPolicy(
                policy_key="default",
                is_enabled=True,
                manual_ai_enabled=False,
                scheduled_ai_enabled=False,
                full_scan_enabled=False,
                digest_enabled=False,
                manual_ai_daily_limit=0,
                scheduled_ai_daily_limit=0,
                scheduled_ai_batch_limit=20,
                ai_concurrency=1,
                stale_diagnosis_hours=24,
                settings_json={
                    "domain_modes": {"crm": "shadow", "approval": "off"},
                    "domain_rollout": {
                        "crm": {
                            "mode": "shadow",
                            "shadow_cycle": 1,
                            "shadow_started_at": "2026-07-29T00:00:00+00:00",
                            "shadow_started_by_user_id": user.id,
                        }
                    },
                },
                updated_by_user_id=user.id,
            )
            db.add(policy)
            db.commit()
            db.refresh(policy)
            cls.expected_updated_at = policy.updated_at.isoformat()
            cls.token = create_access_token(user.username)

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        def override_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        cls.app = app

    @classmethod
    def tearDownClass(cls) -> None:
        cls.app.dependency_overrides.clear()
        cls.engine.dispose()
        with cls.admin_engine.connect() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{cls.schema_name}" CASCADE')
        cls.admin_engine.dispose()

    def test_ten_concurrent_baseline_requests_create_one_audited_cycle(self) -> None:
        concurrency = 10
        barrier = Barrier(concurrency)

        def run_request(_: int) -> tuple[int, str | None]:
            with TestClient(self.app) as client:
                barrier.wait(timeout=30)
                response = client.post(
                    "/api/v1/exceptions/baseline-scan",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={
                        "domain": "crm",
                        "expected_policy_updated_at": self.expected_updated_at,
                    },
                )
                payload = response.json()
                error_code = (
                    payload.get("detail", {}).get("error_code")
                    if isinstance(payload.get("detail"), dict)
                    else None
                )
                return response.status_code, error_code

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            ThreadPoolExecutor(max_workers=concurrency) as executor,
        ):
            results = list(executor.map(run_request, range(concurrency)))

        self.assertEqual([status for status, _ in results].count(200), 1, results)
        self.assertEqual([status for status, _ in results].count(409), concurrency - 1, results)
        self.assertTrue(
            all(
                error_code in {"exception_policy_version_conflict", "exception_baseline_already_completed"}
                for status, error_code in results
                if status == 409
            ),
            results,
        )
        with self.SessionLocal() as db:
            audit_count = int(
                db.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.action_type == "run_exception_baseline_scan")
                )
                or 0
            )
            policy = db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
            self.assertIsNotNone(policy)
            rollout = policy.settings_json["domain_rollout"]["crm"]
            self.assertEqual(audit_count, 1)
            self.assertEqual(rollout["shadow_cycle"], 1)
            self.assertTrue(rollout["baseline_completed_at"])
            self.assertTrue(rollout["baseline_audit_id"])


if __name__ == "__main__":
    unittest.main()
