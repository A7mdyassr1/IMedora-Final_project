"""
PostgreSQL connection layer (SQLAlchemy 2.x).

Connects to the EXISTING database - nothing here creates or alters tables
(no Base.metadata.create_all; schema is owned by database/migrations).

Engine and session factory are created lazily so importing the app never
opens a connection, and tests can set DATABASE_URL before first use.
"""
import logging
from functools import lru_cache
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    return create_engine(
        s.database_url.get_secret_value(),
        pool_pre_ping=True,  # transparently replaces connections dropped by a DB restart
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_timeout=s.db_pool_timeout,
        connect_args={"connect_timeout": s.db_connect_timeout},
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request.

    It never commits on its own. Services decide transaction boundaries and
    call commit() explicitly; anything uncommitted is rolled back on error.
    """
    db = get_session_factory()()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database_connection() -> None:
    """Raises a SQLAlchemyError if PostgreSQL can't be reached."""
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))


def safe_database_url() -> str:
    """Connection URL with the password masked - the only form fit for logs."""
    return get_engine().url.render_as_string(hide_password=True)


def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
