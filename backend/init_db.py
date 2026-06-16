from database import engine, Base
from models import Candle, Indicator, Trade, Prediction, MarketStats, PaperAccount, Position
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

    # Paper-trading additions to the trades table
    conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS quote_amount FLOAT;"))
    conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS fee FLOAT;"))
    conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS realized_pnl FLOAT;"))
    conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS balance_after FLOAT;"))
    conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS reason VARCHAR;"))
    conn.commit()

# Seed the paper wallet (5,000 USDT) if it doesn't exist yet
from paper_engine import ensure_initialized
ensure_initialized()

print("✅ Table created/updated: candles")
print("✅ Table created/updated: indicators")
print("✅ Table created/updated: trades")
print("✅ Table created: predictions")
print("✅ Table created: market_stats")
print("✅ Table created: paper_account (seeded with 5000 USDT)")
print("✅ Table created: positions")
print("✅ Database initialized successfully!")
