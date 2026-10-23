"""Declarative base for models that MIRROR the existing PostgreSQL tables.
The schema is owned by database/migrations; never call Base.metadata.create_all()."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
