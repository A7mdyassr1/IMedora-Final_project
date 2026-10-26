from typing import List, Tuple

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


def paginate(db: Session, stmt: Select, page: int, page_size: int) -> Tuple[List, int]:
    """Runs `stmt` for one page and returns (rows, total matching rows)."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(page_size).offset((page - 1) * page_size)).unique().all()
    return list(rows), total
