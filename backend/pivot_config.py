"""Persisted, tunable settings for strategy #2 (pivot-bracket).

Right now this is just the recompute interval — how often, and from which candle
period, the pivot Support/Resistance bracket is recomputed. Binance only serves
candles at fixed intervals, so the choice is restricted to natively-supported
periods (each of which also divides 24h evenly, keeping periods aligned to UTC
midnight). Stored in the DB so the setting survives restarts.
"""
from datetime import datetime

from sqlalchemy import text

from database import SessionLocal, engine, Base
from models import PivotConfig

# Only intervals Binance offers as native klines (and each divides 24h evenly).
ALLOWED_HOURS = [1, 2, 4, 6, 8, 12]
DEFAULT_HOURS = 12


def ensure_initialized():
    """Create the config table, self-heal pivot_levels, and seed one row."""
    Base.metadata.create_all(bind=engine, checkfirst=True)
    # Self-heal: older pivot_levels rows predate the interval column.
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE pivot_levels ADD COLUMN IF NOT EXISTS interval_hours INTEGER;"
        ))
        conn.commit()

    db = SessionLocal()
    try:
        if not db.query(PivotConfig).first():
            db.add(PivotConfig(interval_hours=DEFAULT_HOURS, updated_at=datetime.utcnow()))
            db.commit()
            print(f"[pivot] Initialized recompute interval at {DEFAULT_HOURS}h")
    finally:
        db.close()


def get_interval_hours():
    """Current recompute interval in hours (falls back to the default)."""
    db = SessionLocal()
    try:
        row = db.query(PivotConfig).first()
        if row and row.interval_hours in ALLOWED_HOURS:
            return row.interval_hours
        return DEFAULT_HOURS
    finally:
        db.close()


def set_interval_hours(hours):
    """Persist a new recompute interval. Raises ValueError if not allowed."""
    if hours not in ALLOWED_HOURS:
        raise ValueError(f"interval_hours must be one of {ALLOWED_HOURS}")
    db = SessionLocal()
    try:
        row = db.query(PivotConfig).first()
        if not row:
            row = PivotConfig(interval_hours=hours, updated_at=datetime.utcnow())
            db.add(row)
        else:
            row.interval_hours = hours
            row.updated_at = datetime.utcnow()
        db.commit()
        return hours
    finally:
        db.close()
