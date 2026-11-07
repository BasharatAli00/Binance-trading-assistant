"""SQLAlchemy models for RHC. Uses its OWN declarative base (RhcBase) so these
tables are never created on, and can never break, the production database's
shared Base.metadata.create_all(). Times are UTC epoch seconds (BigInteger).
"""
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, Column, DateTime, Float, Index, Integer, SmallInteger, String,
                        UniqueConstraint)
from sqlalchemy.orm import declarative_base

RhcBase = declarative_base()


class RhcCheckpoint(RhcBase):
    __tablename__ = "rhc_checkpoint"
    stream = Column(String(32), primary_key=True)
    block = Column(BigInteger, nullable=False)
    block_ts = Column(BigInteger)
    block_hash = Column(String(66))
    resume_from_ts = Column(BigInteger)      # trades before this ts were already flushed
    updated_at = Column(DateTime, default=datetime.utcnow)


class RhcToken(RhcBase):
    __tablename__ = "rhc_token"
    address = Column(String(42), primary_key=True)
    symbol = Column(String(64))
    decimals = Column(SmallInteger)
    first_seen_ts = Column(BigInteger)


class RhcPool(RhcBase):
    __tablename__ = "rhc_pool"
    id = Column(Integer, primary_key=True, autoincrement=True)
    pool_id = Column(String(66), nullable=False)
    kind = Column(String(4), nullable=False)
    venue = Column(String(42))
    hooks = Column(String(42))
    token0 = Column(String(42), nullable=False)
    token1 = Column(String(42), nullable=False)
    fee = Column(Integer)
    tick_spacing = Column(Integer)
    base_index = Column(SmallInteger)
    quote_token = Column(String(42))
    quote_class = Column(String(8))
    supported = Column(Boolean, default=False, nullable=False)
    reason = Column(String(32))
    created_block = Column(BigInteger)
    created_ts = Column(BigInteger)
    discovered_via = Column(String(12))      # creation | on_demand
    tracked = Column(Boolean, default=False, nullable=False)
    tracked_since = Column(BigInteger)
    last_swap_ts = Column(BigInteger)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("pool_id", name="uq_rhc_pool_pool_id"),
        Index("ix_rhc_pool_tracked", "tracked"),
        Index("ix_rhc_pool_last_swap", "last_swap_ts"),
    )


class RhcCandle(RhcBase):
    __tablename__ = "rhc_candle"
    pool_pk = Column(Integer, primary_key=True)
    tf = Column(SmallInteger, primary_key=True)
    bucket = Column(BigInteger, primary_key=True)
    o = Column(Float)
    h = Column(Float)
    l = Column(Float)
    c = Column(Float)
    c_usd = Column(Float)
    vol_usd = Column(Float)
    buys = Column(Integer)
    sells = Column(Integer)
    buy_usd = Column(Float)
    sell_usd = Column(Float)
    traders = Column(Integer)
    traders_exact = Column(Boolean)
    large = Column(Integer)
    liq = Column(Float)
    liq_usd = Column(Float)
    __table_args__ = (Index("ix_rhc_candle_tf_bucket", "tf", "bucket"),)


class RhcLiquidityEvent(RhcBase):
    __tablename__ = "rhc_liquidity_event"
    tx_hash = Column(String(66), primary_key=True)
    log_index = Column(Integer, primary_key=True)
    pool_pk = Column(Integer, nullable=False)
    block = Column(BigInteger)
    ts = Column(BigInteger)
    action = Column(String(8))
    amount0 = Column(Float)
    amount1 = Column(Float)
    liquidity_delta = Column(Float)
    usd = Column(Float)
    __table_args__ = (Index("ix_rhc_liq_pool_ts", "pool_pk", "ts"),)


class RhcSwap(RhcBase):
    """Raw swaps. Written ONLY for pools explicitly flagged (open paper positions, Phase 4)."""
    __tablename__ = "rhc_swap"
    tx_hash = Column(String(66), primary_key=True)
    log_index = Column(Integer, primary_key=True)
    pool_pk = Column(Integer, nullable=False)
    block = Column(BigInteger)
    ts = Column(BigInteger)
    side = Column(String(4))
    base_amt = Column(Float)
    quote_amt = Column(Float)
    price_usd = Column(Float)
    usd = Column(Float)
    trader = Column(String(42))
    __table_args__ = (Index("ix_rhc_swap_pool_ts", "pool_pk", "ts"),)


class RhcSourceSnapshot(RhcBase):
    __tablename__ = "rhc_source_snapshot"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source = Column(String(16), nullable=False)
    pool_pk = Column(Integer, nullable=False)
    ts = Column(BigInteger, nullable=False)
    price_usd = Column(Float)
    liquidity_usd = Column(Float)
    volume_24h = Column(Float)
    our_price_usd = Column(Float)
    dev_pct = Column(Float)
    __table_args__ = (Index("ix_rhc_snap_pool_ts", "pool_pk", "ts"),)


class RhcSourceHealth(RhcBase):
    __tablename__ = "rhc_source_health"
    source = Column(String(16), primary_key=True)
    ok_count = Column(BigInteger, default=0)
    err_count = Column(BigInteger, default=0)
    last_ok_ts = Column(BigInteger)
    last_err_ts = Column(BigInteger)
    last_err = Column(String(300))
    last_latency_ms = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow)


class RhcGap(RhcBase):
    __tablename__ = "rhc_gap"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stream = Column(String(32), nullable=False)
    start_block = Column(BigInteger, nullable=False)
    end_block = Column(BigInteger, nullable=False)
    reason = Column(String(64))
    detected_at = Column(DateTime, default=datetime.utcnow)
    filled_at = Column(DateTime)


class RhcLease(RhcBase):
    """Single-writer lease. Expires on its own, so a dead process can never block a new one
    (session advisory locks proved unreliable behind the Supabase pooler)."""
    __tablename__ = "rhc_lease"
    name = Column(String(32), primary_key=True)
    owner = Column(String(96), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class RhcKv(RhcBase):
    """Small key/value store for service state (e.g. storage guard status)."""
    __tablename__ = "rhc_kv"
    key = Column(String(64), primary_key=True)
    value = Column(String(2000))
    updated_at = Column(DateTime, default=datetime.utcnow)


RHC_TABLES = [m.__table__.name for m in (RhcCheckpoint, RhcToken, RhcPool, RhcCandle, RhcLiquidityEvent,
                                          RhcSwap, RhcSourceSnapshot, RhcSourceHealth, RhcGap, RhcKv, RhcLease)]
