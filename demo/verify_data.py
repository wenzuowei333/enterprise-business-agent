"""Phase-2 data/schema checks, not phase-3 workflow/concurrency acceptance."""
import hashlib
import json
from decimal import Decimal
from argon2 import PasswordHasher
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, configure_mappers
from alembic.migration import MigrationContext
from alembic.autogenerate import compare_metadata
from app import models as m
from app.core.config import settings
from app.core.database import Base
from demo.provider import diagnose
from app.services.evidence_contract import HermesResponseError


def main():
    engine = create_engine(settings.database_url)
    configure_mappers()
    with engine.connect() as conn:
        drift = compare_metadata(MigrationContext.configure(conn, opts={"compare_type":True}), Base.metadata)
        assert not drift, repr(drift)
        for table in Base.metadata.tables.values():
            for fk in table.foreign_keys:
                assert fk.column.table.name in Base.metadata.tables
    with Session(engine) as db:
        snapshots = db.scalars(select(m.InventorySnapshot).order_by(m.InventorySnapshot.id)).all()
        cases = db.scalars(select(m.ExceptionCase).order_by(m.ExceptionCase.id)).all()
        assert len(snapshots) == 12 and len(cases) == 6
        assert [s.id for s in snapshots if s.stock_qty is not None and s.stock_qty < 0] == [2,5,8]
        assert [s.id for s in snapshots if (s.locked_base_qty or 0) > 0] == [3,5,9]
        assert sum(s.stock_qty for s in snapshots if s.stock_qty is not None and s.stock_qty < 0) == Decimal('-13')
        assert sum(s.locked_base_qty or 0 for s in snapshots) == Decimal('12')
        assert sum(c.metadata_json['warehouse_name'] == '演示东仓' for c in cases) == 4
        assert sum(c.metadata_json['warehouse_name'] == '演示西仓' for c in cases) == 2
        assert db.scalar(select(func.count()).select_from(m.User)) == 3
        for user in db.scalars(select(m.User)):
            assert PasswordHasher().verify(user.password_hash, 'LocalDemo-2026!')
        evidence = db.scalar(select(m.ExceptionEvidence).order_by(m.ExceptionEvidence.id)).data_json
        good = diagnose(evidence)
        assert good['mock'] and good['diagnosis']['evidence_refs']
        try:
            diagnose(evidence, invalid_reference=True)
        except HermesResponseError:
            pass
        else:
            raise AssertionError('Unknown citation was accepted')
        if engine.dialect.name == 'postgresql':
            for table in Base.metadata.tables.values():
                sequence = db.scalar(select(func.pg_get_serial_sequence(table.name, 'id')))
                if sequence:
                    maximum = db.scalar(select(func.max(table.c.id))) or 0
                    # Sequence names come from PostgreSQL, quoted by its identifier preparer.
                    quoted = '.'.join(engine.dialect.identifier_preparer.quote(x) for x in sequence.split('.'))
                    last, called = db.connection().exec_driver_sql(f'SELECT last_value, is_called FROM {quoted}').one()
                    assert last >= maximum
        normalized = {}
        for table in Base.metadata.sorted_tables:
            rows = [dict(r) for r in db.execute(select(table).order_by(table.c.id)).mappings()]
            for row in rows:
                row.pop('password_hash', None)  # random salt is intentionally not a fixture constant
            normalized[table.name] = rows
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
    print(json.dumps({'status':'passed','scope':'synthetic_fixture_and_schema_check','tables':19,
                      'snapshots':12,'cases':6,'mock_contract_rejects_unknown_reference':True,
                      'normalized_data_sha256':digest}))


if __name__ == '__main__':
    main()
