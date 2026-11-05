#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.database import engine  # noqa: E402
from app.services.global_ai_backfill_service import (  # noqa: E402
    backfill_legacy_global_ai_data,
    global_ai_backfill_status,
)


def main() -> int:
    with engine.begin() as connection:
        inserted = backfill_legacy_global_ai_data(connection)
        status = global_ai_backfill_status(connection)
    print(json.dumps({"inserted": inserted, "status": status}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
