import os
from datetime import datetime
from dotenv import load_dotenv
from binance.client import Client

from database import SessionLocal
from models import PivotLevels
import pivot_config

load_dotenv(override=True)

# Hours -> Binance native kline interval. Only these are offered by Binance, and
# each divides 24h evenly so the periods align to UTC midnight.
_INTERVAL_MAP = {
    1: Client.KLINE_INTERVAL_1HOUR,
    2: Client.KLINE_INTERVAL_2HOUR,
    4: Client.KLINE_INTERVAL_4HOUR,
    6: Client.KLINE_INTERVAL_6HOUR,
    8: Client.KLINE_INTERVAL_8HOUR,
    12: Client.KLINE_INTERVAL_12HOUR,
}


def calculate_pivots(high, low, close):
    """Standard floor-trader pivot points from a period's High/Low/Close.

    Returns a dict with the central pivot (pp), three resistances (r1-r3)
    and three supports (s1-s3) — the same levels shown on most TA dashboards.
    """
    pp = (high + low + close) / 3.0
    r1 = (2 * pp) - low
    s1 = (2 * pp) - high
    r2 = pp + (high - low)
    s2 = pp - (high - low)
    r3 = high + 2 * (pp - low)
    s3 = low - 2 * (high - pp)
    return {
        "pp": pp,
        "r1": r1, "r2": r2, "r3": r3,
        "s1": s1, "s2": s2, "s3": s3,
    }


def _trend_label(price, pp):
    """Simple, self-contained daily bias: price relative to the pivot.

    A 0.1% neutral band avoids flip-flopping when price sits right on PP.
    """
    if pp <= 0:
        return "Neutral"
    band = pp * 0.001
    if price > pp + band:
        return "Uptrend"
    if price < pp - band:
        return "Downtrend"
    return "Neutral"


def fetch_and_store_pivots(symbol="BTCUSDT", interval_hours=None):
    """Compute pivot levels from the prior completed N-hour candle and store them.

    `interval_hours` (1/2/4/6/8/12) is the configurable recompute period for
    strategy #2 — it governs both how often this runs and which Binance candle
    the bracket is derived from. Falls back to the persisted config when not
    passed. No new API/key: reuses the Binance kline client we already depend on.
    """
    try:
        if interval_hours is None:
            interval_hours = pivot_config.get_interval_hours()
        kline_interval = _INTERVAL_MAP.get(interval_hours, Client.KLINE_INTERVAL_12HOUR)

        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_SECRET_KEY')
        client = Client(api_key, api_secret)

        # Two N-hour candles: [-1] is the current (still forming) period, [-2] is
        # the last fully-closed block — pivots are computed from that closed block.
        klines = client.get_klines(symbol=symbol, interval=kline_interval, limit=2)
        if len(klines) < 2:
            print(f"Not enough {interval_hours}h klines to compute pivots for {symbol}.")
            return

        prev_period = klines[-2]
        high = float(prev_period[2])
        low = float(prev_period[3])
        close = float(prev_period[4])
        current_price = float(klines[-1][4])  # current period's close-so-far for the trend bias

        levels = calculate_pivots(high, low, close)
        trend = _trend_label(current_price, levels["pp"])

        db = SessionLocal()
        try:
            row = PivotLevels(
                symbol=symbol,
                timestamp=datetime.utcnow(),
                pp=levels["pp"],
                r1=levels["r1"], r2=levels["r2"], r3=levels["r3"],
                s1=levels["s1"], s2=levels["s2"], s3=levels["s3"],
                trend=trend,
                interval_hours=interval_hours,
            )
            db.add(row)
            db.commit()
            print(f"[OK] Saved {interval_hours}h pivot levels for {symbol} (PP={levels['pp']:.2f}, trend={trend})")
        finally:
            db.close()

    except Exception as e:
        print(f"Failed to fetch or store pivot levels: {e}")


if __name__ == "__main__":
    fetch_and_store_pivots()
