from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def init_engine(url: str) -> Engine:
    global _engine, _Session
    kw: dict[str, object] = {}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _fk(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    from aicad.memory import tables as _memory_tables  # noqa: F401  (projects + design memory, additive)
    from aicad.platform import models  # noqa: F401  (register tables)
    from aicad.platform.collab import tables  # noqa: F401  (collaboration tables, additive)

    Base.metadata.create_all(_engine)
    return _engine


def get_db() -> Iterator[Session]:
    assert _Session is not None, "init_engine() not called"
    db = _Session()
    try:
        yield db
    finally:
        db.close()


def session_factory() -> sessionmaker[Session]:
    assert _Session is not None
    return _Session
