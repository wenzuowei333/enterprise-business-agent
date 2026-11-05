from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.database import SessionLocal  # noqa: E402
from app.services.import_service import commit_batch, create_batch_from_upload, validate_batch  # noqa: E402


class LocalUploadFile:
    def __init__(self, path: Path):
        self.filename = path.name
        self.file = path.open("rb")

    def close(self) -> None:
        self.file.close()


class ScriptUser:
    id = None
    username = "import_dry_run"
    real_name = "导入干跑脚本"
    role = "admin"


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run a master-data customer import without leaving database rows.")
    parser.add_argument("file", type=Path, help="Customer master .xls/.xlsx/.csv file")
    parser.add_argument("--file-type", default="customer_master", help="Requested import file type; defaults to customer_master")
    parser.add_argument("--commit-check", action="store_true", help="Also run commit logic before rollback")
    parser.add_argument("--keep-data", action="store_true", help="Keep database changes; disabled by default")
    args = parser.parse_args()

    source = args.file.expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"File not found: {source}")

    upload = LocalUploadFile(source)
    batch_dir: Path | None = None
    with SessionLocal() as db:
        try:
            batch = create_batch_from_upload(
                db,
                file=upload,  # type: ignore[arg-type]
                file_type=args.file_type,
                data_date=None,
                user=ScriptUser(),  # type: ignore[arg-type]
            )
            batch_dir = Path(batch.raw_file_path).parent
            validate_batch(db, batch)
            if args.commit_check and batch.error_rows == 0:
                commit_batch(db, batch)
            print(f"batch_no={batch.batch_no}")
            print(f"requested_file_type={args.file_type}")
            print(f"resolved_file_type={batch.file_type}")
            print(f"status={batch.status}")
            print(f"total_rows={batch.total_rows}")
            print(f"success_rows={batch.success_rows}")
            print(f"error_rows={batch.error_rows}")
            print(f"mapping={batch.mapping_json}")
            if args.keep_data:
                db.commit()
                print("kept_data=true")
            else:
                db.rollback()
                print("kept_data=false")
        finally:
            upload.close()
            if not args.keep_data and batch_dir and batch_dir.exists():
                shutil.rmtree(batch_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
