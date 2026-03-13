"""
Database engine and session factory for SQLAlchemy ORM.
PostgreSQL only. Set DATABASE_URL (e.g. postgresql://user:pass@localhost:5432/maildb).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from models import Base
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

# PostgreSQL required
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is required. Example: postgresql://user:pass@localhost:5432/maildb"
    )
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


def set_db_path(path: str | None) -> None:
    """No-op; kept for API compatibility. Use DATABASE_URL env."""
    pass


def _build_engine():
    return create_engine(
        DATABASE_URL,
        poolclass=NullPool,
        connect_args={},
        echo=os.environ.get("SQL_ECHO", "").lower() in ("1", "true", "yes"),
    )


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _build_engine()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def init_db() -> None:
    """Create all tables if they do not exist."""
    Base.metadata.create_all(bind=get_engine())


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager yielding a database session. Commits on success, rolls back on error."""
    session = get_session_local()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_local():
    """Return the SessionLocal factory (creates engine on first use)."""
    get_engine()
    return _SessionLocal


def get_session_connection() -> Session:
    """
    Return a new session. Caller must commit/rollback/close.
    For compatibility with existing code expecting connection-like object.
    """
    return get_session_local()()


class SessionConnection:
    """
    Wrapper that makes a SQLAlchemy Session look like a DB-API connection
    for backward compatibility. Provides execute(), cursor(), commit(), close().
    Handles both ? (positional) and :name (named) params.
    """

    def __init__(self, session: Session):
        self._session = session

    def execute(self, sql: str, params=None):
        import re

        if params is not None and isinstance(params, (tuple, list)):
            # Convert ? to :p0, :p1, ... for SQLAlchemy text()
            i = [0]

            def repl(_m):
                idx = i[0]
                i[0] += 1
                return f":p{idx}"

            new_sql = re.sub(r"\?", repl, sql)
            params_dict = {f"p{j}": v for j, v in enumerate(params)}
            return self._session.execute(text(new_sql), params_dict)
        if params is None:
            params = {}
        return self._session.execute(text(sql), params)

    def cursor(self):
        return self

    def commit(self):
        self._session.commit()

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
