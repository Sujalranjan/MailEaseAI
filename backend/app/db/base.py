from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base. All ORM models inherit from this so that
    a single `Base.metadata` describes the whole schema — used by both
    Alembic (autogenerate) and tests (create_all on an isolated engine).
    """
