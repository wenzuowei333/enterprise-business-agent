import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.mobile import router as mobile_router
from app.core.database import get_db
from app.core.security import hash_password
from app.models import MobileSession, User


class MobileAuthApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        User.__table__.create(self.engine)
        MobileSession.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.db.add(
            User(
                username="admin",
                password_hash=hash_password("556677"),
                real_name="施总",
                role="admin",
                status="active",
                is_active=True,
            )
        )
        self.db.commit()

        app = FastAPI()
        app.include_router(mobile_router)

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

    def test_login_refresh_and_logout(self):
        with patch("app.api.routes.mobile.write_audit_log", create=True):
            login = self.client.post(
                "/mobile/auth/login",
                json={
                    "username": "admin",
                    "password": "556677",
                    "device_id": "device-001",
                    "device_name": "Pixel Test",
                },
            )
        self.assertEqual(login.status_code, 200)
        login_payload = login.json()
        self.assertTrue(login_payload["access_token"])
        self.assertTrue(login_payload["refresh_token"])

        with patch("app.api.routes.mobile.write_audit_log", create=True):
            refreshed = self.client.post(
                "/mobile/auth/refresh",
                json={"refresh_token": login_payload["refresh_token"], "device_id": "device-001"},
            )
        self.assertEqual(refreshed.status_code, 200)
        refreshed_payload = refreshed.json()
        self.assertNotEqual(refreshed_payload["refresh_token"], login_payload["refresh_token"])

        with patch("app.api.routes.mobile.write_audit_log", create=True):
            logout = self.client.post(
                "/mobile/auth/logout",
                json={"refresh_token": refreshed_payload["refresh_token"], "device_id": "device-001"},
            )
        self.assertEqual(logout.status_code, 200)

        with patch("app.api.routes.mobile.write_audit_log", create=True):
            rejected = self.client.post(
                "/mobile/auth/refresh",
                json={"refresh_token": refreshed_payload["refresh_token"], "device_id": "device-001"},
            )
        self.assertEqual(rejected.status_code, 401)


if __name__ == "__main__":
    unittest.main()
