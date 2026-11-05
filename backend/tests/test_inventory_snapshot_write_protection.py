import unittest

from fastapi import HTTPException

from app.api.routes.process_data import update_inventory_snapshot


class InventorySnapshotWriteProtectionTest(unittest.TestCase):
    def test_stock_quantity_cannot_be_overwritten(self):
        with self.assertRaises(HTTPException) as raised:
            update_inventory_snapshot(
                snapshot_id=17,
                payload={"stock_qty": "0"},
                db=None,  # Guard runs before database access.
                current_user=None,
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["error_code"], "inventory_snapshot_read_only")
        self.assertEqual(raised.exception.detail["resource_type"], "inventory_snapshot")
        self.assertEqual(raised.exception.detail["resource_id"], 17)
        self.assertIn("不能在管理中心直接修改", raised.exception.detail["message"])


if __name__ == "__main__":
    unittest.main()
