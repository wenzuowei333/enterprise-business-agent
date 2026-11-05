import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.master_data import create_customer, update_customer
from app.core.database import Base
from app.models import CustomerMaster, User
from app.schemas.master_data import CustomerMasterCreate, CustomerMasterUpdate
from app.services.import_service import upsert_customer
from app.services.customer_identity_service import acquire_customer_identity_locks, customer_identity_lock_keys


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CustomerMasterIdentityTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(
            username="customer-editor",
            password_hash="hash",
            real_name="客户维护员",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _existing_customer(self) -> CustomerMaster:
        customer = CustomerMaster(
            customer_code="C001",
            customer_name="苏州恒力纺织有限公司",
            contact_phone="13800138000",
            status="active",
        )
        self.db.add(customer)
        self.db.commit()
        return customer

    def _other_customer(self) -> CustomerMaster:
        customer = CustomerMaster(
            customer_code="C002",
            customer_name="无锡新客户",
            contact_phone="13900000002",
            status="active",
        )
        self.db.add(customer)
        self.db.commit()
        return customer

    def test_manual_creation_rejects_an_exact_normalized_customer_identity(self):
        self._existing_customer()

        with self.assertRaises(HTTPException) as error:
            create_customer(
                CustomerMasterCreate(
                    customer_code="C002",
                    customer_name="苏州 恒力 纺织 有限公司",
                    contact_phone="+86 138 0013 8000",
                ),
                request=None,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(list(self.db.scalars(select(CustomerMaster)))), 1)

    def test_import_new_record_allows_an_exact_normalized_customer_identity(self):
        self._existing_customer()

        upsert_customer(
            self.db,
            {
                "customer_code": "C002",
                "customer_name": "苏州 恒力 纺织 有限公司",
                "contact_phone": "+86 138 0013 8000",
            },
        )
        self.db.flush()

        self.assertEqual(len(list(self.db.scalars(select(CustomerMaster)))), 2)

    def test_manual_identity_update_rejects_another_customers_normalized_identity(self):
        self._existing_customer()
        other = self._other_customer()

        with self.assertRaises(HTTPException) as error:
            update_customer(
                other.customer_code,
                CustomerMasterUpdate(customer_name="苏州 恒力 纺织 有限公司"),
                request=None,
                db=self.db,
                current_user=self.user,
        )

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(
            self.db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == other.customer_code)).customer_name,
            "无锡新客户",
        )

    def test_import_existing_code_identity_update_allows_another_customers_normalized_identity(self):
        self._existing_customer()
        other = self._other_customer()

        upsert_customer(
            self.db,
            {
                "customer_code": other.customer_code,
                "customer_name": "无锡 新 客户",
                "contact_phone": "+86 138 0013 8000",
            },
        )
        self.db.flush()

        self.assertEqual(
            self.db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == other.customer_code)).contact_phone,
            "+86 138 0013 8000",
        )

    def test_manual_non_identity_update_remains_available(self):
        customer = self._existing_customer()

        updated = update_customer(
            customer.customer_code,
            CustomerMasterUpdate(address="苏州市工业园区"),
            request=None,
            db=self.db,
            current_user=self.user,
        )

        self.assertEqual(updated["address"], "苏州市工业园区")

    def test_identity_advisory_locks_are_deterministic_and_postgres_only(self):
        expected = customer_identity_lock_keys(
            customer_name="苏州 恒力纺织有限公司",
            contact_phone="+86 138 0013 8000",
        )
        self.assertEqual(
            expected,
            customer_identity_lock_keys(
                customer_name="苏州恒力纺织有限公司",
                contact_phone="13800138000",
            ),
        )

        postgres_db = Mock()
        postgres_db.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        acquire_customer_identity_locks(
            postgres_db,
            customer_name="苏州 恒力纺织有限公司",
            contact_phone="+86 138 0013 8000",
        )
        self.assertEqual(postgres_db.execute.call_count, len(expected))

        sqlite_db = Mock()
        sqlite_db.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
        acquire_customer_identity_locks(sqlite_db, customer_name="苏州恒力纺织有限公司", contact_phone="13800138000")
        sqlite_db.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
