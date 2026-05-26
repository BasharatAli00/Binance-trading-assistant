from database import engine, Base
from models import Candle, Indicator, Trade, Prediction, MarketStats
from sqlalchemy import text

print("Creating tables...")
Base.metadata.create_all(bind=engine, checkfirst=True)

print("Adding new columns to candles and indicators (if they don't exist)...")
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE candles ADD COLUMN IF NOT EXISTS price_change_1h FLOAT;"))
    conn.execute(text("ALTER TABLE candles ADD COLUMN IF NOT EXISTS price_change_4h FLOAT;"))
    conn.execute(text("ALTER TABLE candles ADD COLUMN IF NOT EXISTS price_change_24h FLOAT;"))
    conn.execute(text("ALTER TABLE candles ADD COLUMN IF NOT EXISTS high_24h FLOAT;"))
    conn.execute(text("ALTER TABLE candles ADD COLUMN IF NOT EXISTS low_24h FLOAT;"))
    conn.execute(text("ALTER TABLE candles ADD COLUMN IF NOT EXISTS volume_change_24h FLOAT;"))
    conn.execute(text("ALTER TABLE candles ADD COLUMN IF NOT EXISTS volatility FLOAT;"))
    conn.execute(text("ALTER TABLE candles ADD COLUMN IF NOT EXISTS candle_body FLOAT;"))
    conn.execute(text("ALTER TABLE candles ADD COLUMN IF NOT EXISTS is_bullish BOOLEAN;"))
    
    conn.execute(text("ALTER TABLE indicators ADD COLUMN IF NOT EXISTS rsi_change FLOAT;"))
    conn.execute(text("ALTER TABLE indicators ADD COLUMN IF NOT EXISTS price_vs_ema20 FLOAT;"))
    conn.execute(text("ALTER TABLE indicators ADD COLUMN IF NOT EXISTS price_vs_ema50 FLOAT;"))
    conn.execute(text("ALTER TABLE indicators ADD COLUMN IF NOT EXISTS ema20_vs_ema50 FLOAT;"))
    conn.execute(text("ALTER TABLE indicators ADD COLUMN IF NOT EXISTS macd_histogram FLOAT;"))
    conn.execute(text("ALTER TABLE indicators ADD COLUMN IF NOT EXISTS signal_strength INTEGER;"))
    conn.commit()

print("✅ Table created/updated: candles")
print("✅ Table created/updated: indicators")
print("✅ Table created: trades")
print("✅ Table created: predictions")
print("✅ Table created: market_stats")
print("✅ Database initialized successfully!")
