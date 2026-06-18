import uuid
from sqlalchemy import Column, String, Float, DateTime, Boolean, JSON, Integer
from sqlalchemy.dialects.postgresql import UUID
from database import Base

class Candle(Base):
    __tablename__ = "candles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    price_change_1h = Column(Float)
    price_change_4h = Column(Float)
    price_change_24h = Column(Float)
    high_24h = Column(Float)
    low_24h = Column(Float)
    volume_change_24h = Column(Float)
    volatility = Column(Float)
    candle_body = Column(Float)
    is_bullish = Column(Boolean)

class Indicator(Base):
    __tablename__ = "indicators"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    name = Column(String, index=True)
    value = Column(Float)
    rsi_change = Column(Float)
    price_vs_ema20 = Column(Float)
    price_vs_ema50 = Column(Float)
    ema20_vs_ema50 = Column(Float)
    macd_histogram = Column(Float)
    signal_strength = Column(Integer)

class Trade(Base):
    __tablename__ = "trades"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    side = Column(String)
    price = Column(Float)
    quantity = Column(Float)
    quote_amount = Column(Float)      # USDT value of the trade (qty * price)
    fee = Column(Float)               # simulated trading fee in USDT
    realized_pnl = Column(Float)      # profit/loss locked in on SELL (0 for BUY)
    balance_after = Column(Float)     # USDT cash balance right after this trade
    reason = Column(String)           # human-readable why the bot traded
    status = Column(String)


class PaperAccount(Base):
    """Single-row virtual wallet for simulated (paper) trading."""
    __tablename__ = "paper_account"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    usdt_balance = Column(Float)       # free cash
    starting_balance = Column(Float)   # baseline used for total P&L %
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class Position(Base):
    """Current open holding per symbol in the paper wallet."""
    __tablename__ = "positions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    quantity = Column(Float)
    avg_entry_price = Column(Float)
    updated_at = Column(DateTime)
    # Strategy risk state (trend-following stop management)
    stop_price = Column(Float)        # current (trailing) stop
    init_stop = Column(Float)         # initial stop at entry (for R math)
    highest_price = Column(Float)     # high-water mark since entry (chandelier)

class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    predicted_price = Column(Float)
    confidence = Column(Float)

class MarketStats(Base):
    __tablename__ = "market_stats"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    price_change_24h_pct = Column(Float)
    high_24h = Column(Float)
    low_24h = Column(Float)
    volume_24h = Column(Float)
    quote_volume_24h = Column(Float)
    trade_count_24h = Column(Integer)
    weighted_avg_price = Column(Float)

class NewsArticle(Base):
    __tablename__ = "news_articles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    timestamp = Column(DateTime, index=True)
    title = Column(String)
    url = Column(String)
    sentiment = Column(String)
    source = Column(String)

class OnChainStats(Base):
    __tablename__ = "onchain_stats"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    timestamp = Column(DateTime, index=True)
    n_tx = Column(Integer)
    total_fees_btc = Column(Float)
    hash_rate = Column(Float)
    difficulty = Column(Float)
    estimated_transaction_volume_usd = Column(Float)

class TaapiIndicator(Base):
    """Supplementary technical indicators fetched from the Taapi.io API.

    Stored separately from the locally-computed `Indicator` rows so the
    external source never overwrites our own calculations.
    """
    __tablename__ = "taapi_indicators"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    rsi = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    macd_hist = Column(Float)
    ema20 = Column(Float)

class GoogleTrend(Base):
    """Google Trends search-interest for a keyword (e.g. "Bitcoin")."""
    __tablename__ = "google_trends"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    keyword = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    trend_score = Column(Float)        # latest week's search interest (0-100)
    prev_score = Column(Float)         # previous week's value
    wow_change_pct = Column(Float)     # week-over-week % change

