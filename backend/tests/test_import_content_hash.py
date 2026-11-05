import hashlib
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from app.api.routes.imports import upload_import_file
from app.services.import_service import create_batch_from_upload


class ImportContentHashTest(unittest.TestCase):
    def test_upload_persists_sha256_of_exact_file_bytes(self):
        payload = b"customer_code,customer_name\nC001,Example\n"
        upload = SimpleNamespace(filename="customers.csv", file=BytesIO(payload))
        db = MagicMock()
        user = SimpleNamespace(id=7)
        raw = pd.DataFrame([{"customer_code": "C001", "customer_name": "Example"}])

        with (
            tempfile.TemporaryDirectory() as upload_root,
            patch("app.services.import_service.settings.upload_root", upload_root),
            patch("app.services.import_service.read_raw_upload_table", return_value=raw),
            patch("app.services.import_service.resolve_file_type", return_value="customer_master"),
            patch("app.services.import_service.infer_data_date_from_upload", return_value=(None, None)),
            patch("app.services.import_service.table_from_raw", return_value=raw),
            patch("app.services.import_service.write_audit_log"),
        ):
            batch = create_batch_from_upload(
                db,
                file=upload,
                file_type="customer_master",
                data_date=None,
                user=user,
            )

            self.assertEqual(batch.content_sha256, hashlib.sha256(payload).hexdigest())
            self.assertEqual(Path(batch.raw_file_path).read_bytes(), payload)

    def test_successful_upload_queues_non_blocking_import_scan(self):
        batch = SimpleNamespace(id=42, file_type="sales_detail")
        db = MagicMock()
        with (
            patch("app.api.routes.imports.create_batch_from_upload", return_value=batch),
            patch("app.api.routes.imports.ensure_file_type_import_permission"),
            patch("app.services.exception_center_service.enqueue_incremental_exception_scan_safely", return_value=False) as enqueue,
        ):
            result = upload_import_file(
                file_type="sales_detail",
                data_date=None,
                file=SimpleNamespace(),
                db=db,
                current_user=SimpleNamespace(id=7),
            )

        self.assertIs(result, batch)
        enqueue.assert_called_once_with(
            db,
            domains=["import"],
            source_batch_kind="import",
            source_batch_id=42,
        )
        db.commit.assert_called_once_with()
        db.refresh.assert_called_once_with(batch)


if __name__ == "__main__":
    unittest.main()
