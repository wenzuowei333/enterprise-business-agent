from __future__ import annotations

from app.core.database import Base, engine
from app.models import MasterCategoryBinding, MasterCategoryNode  # noqa: F401


def main() -> None:
    Base.metadata.create_all(bind=engine, tables=[MasterCategoryNode.__table__, MasterCategoryBinding.__table__])
    print({"created_or_exists": ["master_category_node", "master_category_binding"]})


if __name__ == "__main__":
    main()
