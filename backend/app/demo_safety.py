"""New demo adapter: refuse production targets before engine creation."""
from pathlib import Path
from sqlalchemy.engine import make_url


def ensure_demo_database(url, expected_name, root):
    parsed = make_url(url)
    if parsed.drivername.startswith("sqlite"):
        target = Path(parsed.database or "").resolve()
        allowed = (Path(root) / "runtime").resolve()
        if target.name != "demo.sqlite3" or allowed not in target.parents:
            raise ValueError("SQLite demo database must be runtime/demo.sqlite3 inside this candidate")
        target.parent.mkdir(parents=True, exist_ok=True)
    elif parsed.drivername == "postgresql+psycopg":
        if (parsed.host not in {"127.0.0.1", "localhost", "postgres"}
            or parsed.database != expected_name or parsed.username != "portfolio_demo"
            or parsed.port not in {5432, 25432, 25433}):
            raise ValueError("Database must point to the dedicated local portfolio demo service")
        if any(key in parsed.query for key in ("host", "hostaddr", "service", "servicefile", "port", "dbname")):
            raise ValueError("Database query target overrides are forbidden")
    else:
        raise ValueError("Only dedicated PostgreSQL or runtime SQLite demo targets are supported")
