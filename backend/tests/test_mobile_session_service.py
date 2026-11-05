import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import MobileSession, User
from app.services.mobile_session_service import (
    MobileSessionError,
    issue_mobile_session,
    refresh_mobile_session,
    revoke_mobile_session,
)


class MobileSessionServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        User.__table__.create(self.engine)
        MobileSession.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.user = User(
            username="admin",
            password_hash="hash",
            real_name="施总",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_refresh_rotates_token_and_invalidates_previous_token(self):
        first_token, session = issue_mobile_session(
            self.db,
            user=self.user,
            device_id="device-001",
            device_name="Pixel Test",
        )
        self.db.commit()

        second_token, refreshed = refresh_mobile_session(
            self.db,
            refresh_token=first_token,
            device_id="device-001",
        )
        self.db.commit()

        self.assertNotEqual(first_token, second_token)
        self.assertEqual(refreshed.id, session.id)
        with self.assertRaises(MobileSessionError):
            refresh_mobile_session(self.db, refresh_token=first_token, device_id="device-001")

    def test_logout_revokes_refresh_token(self):
        refresh_token, _ = issue_mobile_session(
            self.db,
            user=self.user,
            device_id="device-002",
            device_name="Android Test",
        )
        self.db.commit()

        revoke_mobile_session(self.db, refresh_token=refresh_token, device_id="device-002")
        self.db.commit()

        with self.assertRaises(MobileSessionError):
            refresh_mobile_session(self.db, refresh_token=refresh_token, device_id="device-002")


if __name__ == "__main__":
    unittest.main()
