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
    c_usd = Column(Float)        # close, execution price in USD
    c_mid = Column(Float)        # close, marginal (post-swap pool) price in USD
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


class RhcWatch(RhcBase):
    """Dynamic watchlist: one row per pool with its state and why it is there."""
    __tablename__ = "rhc_watchlist"
    pool_pk = Column(Integer, primary_key=True)
    token = Column(String(42), nullable=False)
    state = Column(String(12), nullable=False)          # candidate | watch | rejected | expired
    discovery = Column(String(120))                       # comma-separated discovery reasons
    score = Column(Float)
    reject_codes = Column(String(400))
    warn_codes = Column(String(400))
    first_seen_ts = Column(BigInteger)
    last_screened_ts = Column(BigInteger)
    next_screen_ts = Column(BigInteger)
    last_activity_ts = Column(BigInteger)
    screens = Column(Integer, default=0)
    __table_args__ = (Index("ix_rhc_watch_state_next", "state", "next_screen_ts"),)


class RhcScreen(RhcBase):
    """Every screening, including rejections, with its evidence (auditable)."""
    __tablename__ = "rhc_screen"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    pool_pk = Column(Integer, nullable=False)
    token = Column(String(42), nullable=False)
    ts = Column(BigInteger, nullable=False)
    verdict = Column(String(8), nullable=False)           # pass | reject
    reject_codes = Column(String(400))
    warn_codes = Column(String(400))
    evidence = Column(String(6000))                       # compact JSON: per-check metrics
    duration_ms = Column(Integer)
    __table_args__ = (Index("ix_rhc_screen_pool_ts", "pool_pk", "ts"), Index("ix_rhc_screen_ts", "ts"))


class RhcWalletTrade(RhcBase):
    """Trades with resolved senders, for watch-listed pools only (storage budget)."""
    __tablename__ = "rhc_wallet_trade"
    tx_hash = Column(String(66), primary_key=True)
    log_index = Column(Integer, primary_key=True)
    pool_pk = Column(Integer, nullable=False)
    ts = Column(BigInteger, nullable=False)
    wallet = Column(String(42), nullable=False)
    side = Column(String(4), nullable=False)
    base_amt = Column(Float)
    usd = Column(Float)
    __table_args__ = (Index("ix_rhc_wtrade_pool_ts", "pool_pk", "ts"), Index("ix_rhc_wtrade_ts", "ts"))


class RhcWalletPosition(RhcBase):
    """Closed (wallet, pool) positions derived from rhc_wallet_trade; basis of wallet scores."""
    __tablename__ = "rhc_wallet_position"
    wallet = Column(String(42), primary_key=True)
    pool_pk = Column(Integer, primary_key=True)
    open_ts = Column(BigInteger, primary_key=True)
    close_ts = Column(BigInteger, nullable=False)
    cost_usd = Column(Float)
    proceeds_usd = Column(Float)
    __table_args__ = (Index("ix_rhc_wpos_close", "close_ts"),)


class RhcDecision(RhcBase):
    """Every signal and decision, including rejections, with its evidence."""
    __tablename__ = "rhc_decision"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ts = Column(BigInteger, nullable=False)              # wall-clock time recorded
    as_of = Column(BigInteger, nullable=False)           # chain time the decision was based on
    pool_pk = Column(Integer, nullable=False)
    token = Column(String(42))
    strategy = Column(String(24), nullable=False)
    action = Column(String(20), nullable=False)
    reasons = Column(String(300))
    size_usd = Column(Float)
    entry_ref = Column(Float)
    stop = Column(Float)
    targets = Column(String(120))
    mode = Column(String(8), default="paper")
    broker = Column(String(24))
    evidence = Column(String(6000))
    __table_args__ = (Index("ix_rhc_dec_ts", "ts"), Index("ix_rhc_dec_pool_ts", "pool_pk", "ts"))


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
                                          RhcSwap, RhcSourceSnapshot, RhcSourceHealth, RhcGap, RhcKv, RhcLease,
                                          RhcWatch, RhcScreen, RhcWalletTrade, RhcWalletPosition, RhcDecision)]
