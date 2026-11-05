import unittest

from app.api.routes.process_data import _inventory_base_stmt


class ProcessDataContextCompatibilityTest(unittest.TestCase):
    def test_inventory_context_can_query_without_a_warehouse_filter(self):
        stmt = _inventory_base_stmt(
            q=None,
            date_from=None,
            date_to=None,
            product_code=None,
            default_supplier=None,
            inventory_status=None,
        )

        self.assertIsNotNone(stmt)


if __name__ == "__main__":
    unittest.main()
