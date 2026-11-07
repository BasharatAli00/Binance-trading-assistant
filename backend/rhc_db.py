"""Dedicated database access for RHC.

* The engine is created lazily from RHC_DATABASE_URL only. There is deliberately
  NO fallback to the production DATABASE_URL.
* Nothing here runs at import time, so importing RHC modules can never fail the
  backend's startup because of the database.
"""
import logging
import threading
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import rhc_config as cfg
from rhc_models import RHC_TABLES, RhcBase

log = logging.getLogger("rhc.db")

_engine = None
_Session = None
_lock = threading.Lock()



class RhcDbNotConfigured(RuntimeError):
    pass


def is_configured():
    return bool(cfg.RHC_DATABASE_URL)


def get_engine():
    global _engine, _Session
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is None:
            if not cfg.RHC_DATABASE_URL:
                raise RhcDbNotConfigured("RHC_DATABASE_URL is not set")
            _engine = create_engine(
                cfg.RHC_DATABASE_URL,
                pool_pre_ping=True,
                pool_size=cfg.RHC_DB_POOL_SIZE,
                max_overflow=2,
                pool_recycle=120,   # the pooler drops idle client connections
                connect_args={"connect_timeout": 15, "application_name": "rhc"},
            )
            _Session = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    return _engine


@contextmanager
def session_scope():
    get_engine()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


_MIGRATIONS = [
    # Phase 2: separate marginal close from execution-price close.
    "ALTER TABLE rhc_candle ADD COLUMN IF NOT EXISTS c_mid double precision",
]


def init_schema():
    """Create RHC tables (only RhcBase tables) if missing, then apply additive migrations."""
    RhcBase.metadata.create_all(bind=get_engine(), checkfirst=True)
    with get_engine().begin() as c:
        for stmt in _MIGRATIONS:
            c.execute(text(stmt))


def db_size_mb():
    with get_engine().connect() as c:
        return c.execute(text("select pg_database_size(current_database())")).scalar() / (1024 * 1024)


def table_sizes_mb():
    with get_engine().connect() as c:
        rows = c.execute(text(
            "select relname, pg_total_relation_size(c.oid) from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relkind = 'r' and relname = any(:names)"
        ), {"names": RHC_TABLES}).fetchall()
    return {r[0]: round(r[1] / (1024 * 1024), 3) for r in rows}


def vacuum_full(tables):
    """Reclaim disk space (only RHC tables, which live in the dedicated database)."""
    eng = get_engine()
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        for t in tables:
            if t in RHC_TABLES:
                c.execute(text(f'VACUUM FULL "{t}"'))


class LeaseLock:
    """Single-writer lease stored in rhc_lease, using database time.

    acquire() takes the lease if it is free, expired, or already ours, and renews it.
    Works through any connection pooler; a crashed owner's lease simply expires.
    """

    def __init__(self, name="writer", ttl_s=120):
        import os
        import socket
        import uuid
        self.name = name
        self.ttl_s = int(ttl_s)
        self.owner = f"{socket.gethostname()[:40]}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.held = False
        self.last_error = None
        self.taken_by_other = False   # set when another owner was seen holding the lease

    def acquire(self, _retry=True):
        try:
            with get_engine().begin() as c:
                c.execute(text(
                    "insert into rhc_lease (name, owner, expires_at) "
                    "values (:n, :o, now() + make_interval(secs => :ttl)) "
                    "on conflict (name) do update set owner = excluded.owner, expires_at = excluded.expires_at "
                    "where rhc_lease.expires_at < now() or rhc_lease.owner = excluded.owner"),
                    {"n": self.name, "o": self.owner, "ttl": self.ttl_s})
                cur = c.execute(text("select owner from rhc_lease where name = :n"), {"n": self.name}).scalar()
            self.held = cur == self.owner
            if cur is not None and cur != self.owner:
                self.taken_by_other = True
            self.last_error = None
        except Exception as e:
            if _retry:
                # The pooler drops connections now and then; one immediate retry on a fresh one.
                import time as _t
                _t.sleep(1)
                return self.acquire(_retry=False)
            # Unknown state: assume NOT held so nothing writes without a confirmed lease.
            self.held = False
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
        return self.held

    def release(self):
        try:
            with get_engine().begin() as c:
                c.execute(text("update rhc_lease set expires_at = now() where name = :n and owner = :o"),
                          {"n": self.name, "o": self.owner})
        except Exception:
            pass
        self.held = False
