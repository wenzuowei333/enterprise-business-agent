from __future__ import annotations

from app.core.database import SessionLocal
from app.services.ai_remediation_service import cleanup_expired_attachments


def main() -> int:
    with SessionLocal() as db:
        removed = cleanup_expired_attachments(db)
        db.commit()
    print(f"expired remediation attachments removed: {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
