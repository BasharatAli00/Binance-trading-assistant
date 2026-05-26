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
    timestamp = Column(DateTime)
    side = Column(String)
    price = Column(Float)
    quantity = Column(Float)
    status = Column(String)

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
