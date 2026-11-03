"""Synthetic fixtures only. Does not execute diagnosis jobs or contact a provider."""
import argparse
import hashlib
import json
import random
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from argon2 import PasswordHasher
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app import models as m
from app.core.config import settings
from app.core.database import Base
from app.demo_safety import ensure_demo_database
from app.services.inventory_agent_service import _anomaly_reasons, _case_fingerprint, _evidence_version

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261103
BASE_DATE = date(2026, 10, 1)
BASE_TIME = datetime(2026, 10, 1, tzinfo=timezone.utc)
PASSWORD = "LocalDemo-2026!"


def dataset():
    rng = random.Random(SEED)
    rows = []
    # Expected anomalies are independently specified in expected.json.
    for i in range(1, 13):
        stock = {2: "-8.0000", 5: "-3.0000", 8: "-2.0000"}.get(i, f"{rng.randint(20, 90)}.0000")
        rows.append({"id": i, "batch_id": 1, "row_number": i, "data_date": BASE_DATE.isoformat(),
                     "product_code": f"DEMO-SKU-{i:03}", "product_name": f"虚构收纳商品 {i:02}",
                     "warehouse_name": "演示东仓" if i <= 6 else "演示西仓", "warehouse_scope": "specific",
                     "stock_qty": None if i == 12 else stock,
                     "locked_base_qty": "4.0000" if i in (3, 5, 9) else "0.0000",
                     "stock_base_unit": "件", "unit_relation": "1件=1件", "inventory_status": "demo"})
    return {"synthetic": True, "seed": SEED, "base_date": BASE_DATE.isoformat(), "snapshots": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args()
    data = dataset()
    fixtures = ROOT / "demo/fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    (fixtures / "inventory.json").write_text(encoded)
    expected = {"synthetic": True, "snapshot_count": 12, "negative_stock_ids": [2, 5, 8],
                "locked_stock_ids": [3, 5, 9], "case_count": 6,
                "east_case_count": 4, "west_case_count": 2,
                "negative_stock_sum": "-13.0000", "locked_stock_sum": "12.0000",
                "missing_quantity_snapshot_ids": [12],
                "missing_quantity_note": "原规则将空数量按零处理；此样本不产生负库存案件，不代表数据完整。",
                "seed_does_not_create": ["diagnoses", "diagnosis_jobs", "provider_usage"],
                "accounts": [{"username": "demo_admin", "scope": "all", "diagnose": True},
                             {"username": "demo_east", "scope": "演示东仓", "diagnose": True},
                             {"username": "demo_viewer", "scope": "演示东仓", "diagnose": False}]}
    (fixtures / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n")
    if args.export_only:
        print(json.dumps({"exported": True, "snapshots": 12, "cases_expected": 6}))
        return
    ensure_demo_database(settings.database_url, "inventory_demo", ROOT)
    engine = create_engine(settings.database_url)
    hasher = PasswordHasher()
    with Session(engine) as db, db.begin():
        for i, code in enumerate(["demo_admin", "demo_analyst", "demo_viewer"], 1):
            upsert(db, m.Role, i, role_code=code, role_name=f"演示角色 {i}", is_system_role=True,
                   created_at=BASE_TIME, updated_at=BASE_TIME)
        for i, code in enumerate(["exception.view", "exception.diagnose", "exception.manage"], 1):
            upsert(db, m.Permission, i, permission_code=code, permission_name=code,
                   resource_type="exception_case", action_type=code.split('.')[-1],
                   created_at=BASE_TIME, updated_at=BASE_TIME)
        for i, (role, perm) in enumerate([(1,1),(1,2),(1,3),(2,1),(2,2),(3,1)], 1):
            upsert(db, m.RolePermission, i, role_id=role, permission_id=perm, created_at=BASE_TIME)
        for i, account in enumerate(expected["accounts"], 1):
            old = db.get(m.User, i)
            password_hash = old.password_hash if old else hasher.hash(PASSWORD)
            upsert(db, m.User, i, username=account["username"], password_hash=password_hash,
                   real_name=f"演示用户 {i}", role=["demo_admin","demo_analyst","demo_viewer"][i-1],
                   is_active=True, status="active", created_at=BASE_TIME, updated_at=BASE_TIME,
                   password_updated_at=BASE_TIME)
        for i, account in enumerate(expected["accounts"], 1):
            upsert(db, m.DataScopeRule, i, subject_type="user", subject_id=str(i),
                   resource_type="exception_case", scope_mode="all" if i == 1 else "warehouse",
                   scope_value={} if i == 1 else {"warehouse_names":["演示东仓"]}, is_active=True,
                   created_at=BASE_TIME, updated_at=BASE_TIME)
        upsert(db, m.ImportBatch, 1, batch_no="DEMO-IMPORT-001", file_name="synthetic-inventory.json",
               file_type="inventory_snapshot", data_date=BASE_DATE, status="committed", uploaded_by=1,
               total_rows=12, success_rows=12, error_rows=0, raw_file_path="demo/fixtures/inventory.json",
               content_sha256=hashlib.sha256(encoded.encode()).hexdigest(), uploaded_at=BASE_TIME,
               created_at=BASE_TIME, updated_at=BASE_TIME)
        counter = 0
        for row in data["snapshots"]:
            fields = {k:v for k,v in row.items() if k != "id"}
            fields["data_date"] = BASE_DATE
            fields["created_at"] = BASE_TIME
            for k in ("stock_qty", "locked_base_qty"):
                fields[k] = Decimal(fields[k]) if fields[k] is not None else None
            snapshot = upsert(db, m.InventorySnapshot, row["id"], **fields)
            for reason in _anomaly_reasons(snapshot):
                counter += 1
                fingerprint = _case_fingerprint(snapshot, reason)
                version = _evidence_version(snapshot, reason)
                upsert(db, m.InventoryAnomalyCase, counter, case_no=f"DEMO-INV-{counter:03}",
                       fingerprint=fingerprint, snapshot_id=snapshot.id, batch_id=1, data_date=BASE_DATE,
                       product_code=snapshot.product_code, product_name=snapshot.product_name,
                       warehouse_name=snapshot.warehouse_name, warehouse_scope="specific", reason_code=reason,
                       severity="high", status="open", stock_qty=snapshot.stock_qty,
                       locked_qty=snapshot.locked_base_qty, evidence_version=version,
                       detected_at=BASE_TIME, created_at=BASE_TIME, updated_at=BASE_TIME)
                upsert(db, m.ExceptionCase, counter, case_no=f"DEMO-CASE-{counter:03}", fingerprint=fingerprint,
                       domain="inventory", rule_code=reason, title="合成库存异常", severity="warning", status="open",
                       occurrence_type="new", occurrence_cycle=1, rule_version="demo-inventory-v1",
                       resource_type="inventory_snapshot", resource_id=str(snapshot.id), resource_code=snapshot.product_code,
                       resource_name=snapshot.product_name, source_type="inventory_snapshot", source_id=str(snapshot.id),
                       source_batch_kind="import", source_batch_id=1, inventory_anomaly_case_id=counter,
                       data_date=BASE_DATE, evidence_version=version, reason="合成数据命中确定性库存规则",
                       affected_rows=1, affected_quantity=snapshot.stock_qty, detected_at=BASE_TIME, last_seen_at=BASE_TIME,
                       metadata_json={"synthetic":True,"warehouse_name":snapshot.warehouse_name,"reason_code":reason},
                       created_at=BASE_TIME, updated_at=BASE_TIME)
                evidence = {"kind":"inventory_snapshot", "rule_code":reason, "reason_code":reason,
                            "snapshot_id":snapshot.id, "batch_id":1, "data_date":BASE_DATE.isoformat(),
                            "product":{"code":snapshot.product_code,"name":snapshot.product_name},
                            "warehouse":{"name":snapshot.warehouse_name,"scope":"specific"},
                            "observed":{"stock_qty":str(snapshot.stock_qty) if snapshot.stock_qty is not None else None,
                                        "locked_qty":str(snapshot.locked_base_qty)},
                            "allowed_root_cause_codes":["source_record_mismatch", "insufficient_evidence"]}
                upsert(db, m.ExceptionEvidence, counter, case_id=counter, evidence_version=version, data_json=evidence,
                       collected_at=BASE_TIME, created_at=BASE_TIME, updated_at=BASE_TIME)
                upsert(db, m.ExceptionEvent, counter, case_id=counter, event_type="demo_fixture_loaded",
                       actor_user_id=1, to_status="open", detail_json={"synthetic":True,"not_a_runtime_scan":True},
                       created_at=BASE_TIME)
        upsert(db, m.ExceptionPolicy, 1, policy_key="default", is_enabled=True, manual_ai_enabled=True,
               scheduled_ai_enabled=False, full_scan_enabled=False, digest_enabled=False, manual_ai_daily_limit=20,
               updated_by_user_id=1, settings_json={"synthetic":True,"provider":"mock"},
               created_at=BASE_TIME, updated_at=BASE_TIME)
        if engine.dialect.name == "postgresql":
            # Explicit fixture IDs must not leave serial sequences behind live inserts.
            for table in Base.metadata.sorted_tables:
                sequence = db.scalar(select(func.pg_get_serial_sequence(table.name, "id")))
                if sequence:
                    highest = db.scalar(select(func.max(table.c.id)))
                    db.execute(select(func.setval(sequence, highest or 1, highest is not None)))
    print(json.dumps({"synthetic":True,"snapshots":12,"cases":counter,"idempotent":True}))


def upsert(db, model, row_id, **fields):
    row = db.get(model, row_id)
    if row is None:
        row = model(id=row_id)
        db.add(row)
    for key, value in fields.items():
        setattr(row, key, value)
    db.flush()
    return row


if __name__ == "__main__":
    main()
