"""Taapi.io technical indicators (supplementary source).

This fetches RSI / MACD / EMA20 for BTC/USDT (1h) from the Taapi.io free tier
and stores them in their own `taapi_indicators` table. It is purely additive:
the project's own locally-computed indicators (data_collector.py / signals.py)
are never replaced.

Free-tier constraints handled here:
  * Rate limit: 1 request / 15 seconds -> we sleep 15s between each indicator.
  * Caching: skip the network entirely if our last stored row is < 15 min old.

The fetcher runs in a background thread (scheduled hourly + once at startup),
so the inter-request sleeps don't block the API event loop. Every call is
logged with a timestamp and status, matching news_fetcher.py / fear_greed.py.
"""
import os
import time
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

from database import SessionLocal, engine
from models import TaapiIndicator

load_dotenv()

_BASE_URL = "https://api.taapi.io"
_SYMBOL = "BTC/USDT"
_EXCHANGE = "binance"
_INTERVAL = "1h"

# Free tier: 1 request every 15 seconds. Keep a small safety margin.
_RATE_LIMIT_SECONDS = 16
# Don't refetch if we already have a row newer than this.
_CACHE_MINUTES = 15


def _log(msg):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Taapi][{now}] {msg}")


def _get(endpoint, api_key, extra=None):
    """Single Taapi GET with timeout. Returns parsed JSON or raises."""
    params = {
        "secret": api_key,
        "exchange": _EXCHANGE,
        "symbol": _SYMBOL,
        "interval": _INTERVAL,
    }
    if extra:
        params.update(extra)
    resp = requests.get(f"{_BASE_URL}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_and_store_taapi():
    """Fetch RSI/MACD/EMA20 from Taapi.io and store one combined row.

    No-ops (without raising) if the key is missing or if a fresh row already
    exists within the cache window, so the scheduler and the rest of the system
    are unaffected by any failure here.
    """
    api_key = os.getenv("TAAPI_API_KEY")
    if not api_key or api_key == "your_taapi_api_key_here":
        _log("TAAPI_API_KEY not configured properly - skipping.")
        return

    # Make sure our table exists even if init_db hasn't been re-run.
    TaapiIndicator.__table__.create(bind=engine, checkfirst=True)

    db = SessionLocal()
    try:
        # Cache guard: respect the 15-minute minimum between real fetches.
        latest = db.query(TaapiIndicator).filter(
            TaapiIndicator.symbol == "BTCUSDT"
        ).order_by(TaapiIndicator.timestamp.desc()).first()
        if latest and latest.timestamp > datetime.utcnow() - timedelta(minutes=_CACHE_MINUTES):
            _log("Cached value < 15 min old — skipping network fetch.")
            return

        # --- RSI ---
        rsi_data = _get("rsi", api_key)
        _log(f"RSI ok -> {rsi_data.get('value')}")
        rsi = float(rsi_data.get("value")) if rsi_data.get("value") is not None else None

        time.sleep(_RATE_LIMIT_SECONDS)

        # --- MACD ---
        macd_data = _get("macd", api_key)
        _log(f"MACD ok -> {macd_data.get('valueMACD')}")
        macd = _maybe_float(macd_data.get("valueMACD"))
        macd_signal = _maybe_float(macd_data.get("valueMACDSignal"))
        macd_hist = _maybe_float(macd_data.get("valueMACDHist"))

        time.sleep(_RATE_LIMIT_SECONDS)

        # --- EMA 20 ---
        ema_data = _get("ema", api_key, extra={"period": 20})
        _log(f"EMA20 ok -> {ema_data.get('value')}")
        ema20 = _maybe_float(ema_data.get("value"))

        row = TaapiIndicator(
            symbol="BTCUSDT",
            timestamp=datetime.utcnow(),
            rsi=rsi,
            macd=macd,
            macd_signal=macd_signal,
            macd_hist=macd_hist,
            ema20=ema20,
        )
        db.add(row)
        db.commit()
        _log("Stored new Taapi indicator row.")
    except Exception as e:
        _log(f"fetch failed: {e}")
    finally:
        db.close()


def _maybe_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    fetch_and_store_taapi()
