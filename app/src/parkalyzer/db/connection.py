from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


def make_engine(dsn: str, **kwargs: object) -> Engine:
    """Create a SQLAlchemy engine.

    The DSN must use the psycopg3 driver prefix:
        postgresql+psycopg://user:password@host/dbname
    """
    return create_engine(dsn, pool_pre_ping=True, **kwargs)


@contextmanager
def make_session(dsn: str) -> Generator[Session, None, None]:
    """Context manager yielding a SQLAlchemy Session.

    Creates and disposes the engine on each call — appropriate for
    short-lived CLI commands. Commits on clean exit, rolls back on exception.
    """
    engine = make_engine(dsn)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def ensure_schema_exists(dsn: str, schema_name: str) -> None:
    """Create schema if it does not exist. Idempotent."""
    engine = make_engine(dsn)
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        conn.commit()
    engine.dispose()
