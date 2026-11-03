"""One mutation lock/order for recheck, enqueue, cancellation and owned writes."""
from sqlalchemy import select, func


def acquire_exception_case_mutation_lock(db):
    if db.get_bind().dialect.name != "postgresql":
        raise RuntimeError("The workflow requires PostgreSQL; SQLite is not a lease substitute")
    db.execute(select(func.pg_advisory_xact_lock(742028230003)))
