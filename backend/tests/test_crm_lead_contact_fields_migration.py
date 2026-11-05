import importlib.util
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "alembic" / "versions" / "20260801_0100_crm_lead_contact_fields.py"


class CrmLeadContactFieldsMigrationTest(unittest.TestCase):
    def test_upgrade_and_downgrade_contact_fields(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        metadata = MetaData()
        Table("crm_lead", metadata, Column("id", Integer, primary_key=True))
        metadata.create_all(engine)

        spec = importlib.util.spec_from_file_location("crm_lead_contact_fields_migration", MIGRATION_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.revision, "20260801_0100")
        self.assertEqual(module.down_revision, "20260729_0500")

        with engine.begin() as connection:
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            upgraded_columns = {column["name"] for column in inspect(connection).get_columns("crm_lead")}
            self.assertIn("address", upgraded_columns)
            self.assertIn("customer_group_name", upgraded_columns)

            module.downgrade()
            downgraded_columns = {column["name"] for column in inspect(connection).get_columns("crm_lead")}
            self.assertNotIn("address", downgraded_columns)
            self.assertNotIn("customer_group_name", downgraded_columns)

        engine.dispose()


if __name__ == "__main__":
    unittest.main()
