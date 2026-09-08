import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base


@pytest.fixture()
def db_session():
    """An isolated, fully in-memory SQLite database per test.

    StaticPool keeps the same in-memory connection alive for the whole
    test (plain in-memory SQLite otherwise gets a fresh, empty DB per
    connection, which breaks anything using more than one connection).
    Tables are created directly from the ORM metadata rather than via
    Alembic — appropriate for ephemeral test databases; the real
    dev/prod database is still migration-managed (see alembic/).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
