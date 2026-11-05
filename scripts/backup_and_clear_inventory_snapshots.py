#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import delete, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import ImportBatch, ImportError, InventorySnapshot  # noqa: E402
from app.services.inventory_flow_service import rebuild_inventory_flow  # noqa: E402


def jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def row_to_dict(row) -> dict:
    return {column.name: jsonable(getattr(row, column.name)) for column in row.__table__.columns}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup and optionally clear legacy inventory_snapshot import data.")
    parser.add_argument("--execute", action="store_true", help="Delete data after backup. Without this flag the script only reports and writes backups.")
    parser.add_argument("--out-dir", default=str(ROOT / "backups" / "inventory_snapshot_cleanup"), help="Backup output directory.")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir).resolve() / timestamp

    with SessionLocal() as db:
        batches = list(db.scalars(select(ImportBatch).where(ImportBatch.file_type == "inventory_snapshot").order_by(ImportBatch.id)).all())
        batch_ids = [batch.id for batch in batches]
        snapshots = list(db.scalars(select(InventorySnapshot).where(InventorySnapshot.batch_id.in_(batch_ids)).order_by(InventorySnapshot.batch_id, InventorySnapshot.row_number)).all()) if batch_ids else []
        errors = list(db.scalars(select(ImportError).where(ImportError.batch_id.in_(batch_ids)).order_by(ImportError.batch_id, ImportError.row_number)).all()) if batch_ids else []

        write_jsonl(out_dir / "import_batch.inventory_snapshot.jsonl", [row_to_dict(row) for row in batches])
        write_jsonl(out_dir / "inventory_snapshot.jsonl", [row_to_dict(row) for row in snapshots])
        write_jsonl(out_dir / "import_error.inventory_snapshot.jsonl", [row_to_dict(row) for row in errors])

        print(json.dumps({
            "backup_dir": str(out_dir),
            "execute": args.execute,
            "inventory_snapshot_batches": len(batches),
            "inventory_snapshot_rows": len(snapshots),
            "import_error_rows": len(errors),
        }, ensure_ascii=False, indent=2))

        if not args.execute:
            print("Dry run only. Re-run with --execute to delete after backup.")
            return 0

        if batch_ids:
            db.execute(delete(InventorySnapshot).where(InventorySnapshot.batch_id.in_(batch_ids)))
            db.execute(delete(ImportError).where(ImportError.batch_id.in_(batch_ids)))
            db.execute(delete(ImportBatch).where(ImportBatch.id.in_(batch_ids)))
            rebuild_inventory_flow(db)
        db.commit()
        print("Inventory snapshot import data cleared and inventory flow rebuilt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
