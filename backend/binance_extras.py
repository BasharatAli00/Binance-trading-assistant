"""Supplementary Binance public market-data fetchers.

These extend the existing Binance integration (klines in signals.py, the 24h
ticker in data_collector.py) with extra public endpoints that need no API key:

  * order book depth   (top bids/asks)
  * aggregate trades   (recent executed trades)
  * real-time avg price

Each fetcher is isolated, has its own short-lived cache (these change fast, so
we only cache a few seconds to avoid hammering the endpoint while many UI
clients poll), a network timeout, and never raises into the caller: on failure
it returns the last good snapshot (or an empty one) so the rest of the system
keeps working. Every call is logged with a timestamp and status, matching the
style of fear_greed.py.
"""
import time
from datetime import datetime

from binance.client import Client

# One shared public client (no keys needed for these endpoints), mirroring the
# ui_client used in main.py. requests_params sets a timeout on every call.
_client = Client(requests_params={"timeout": 10})

# Per-key cache: {cache_key: {"data": ..., "fetched_at": float, "refresh_at": float}}
_cache = {}

# How long each kind of data stays fresh (seconds). Order book / trades move
# fast but the UI polls often, so a few seconds is plenty to cut request volume.
_TTL = {
    "orderbook": 5.0,
    "aggtrades": 5.0,
    "avgprice": 5.0,
}


def _log(tag, symbol, status):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[BinanceExtras][{now}] {tag} {symbol} -> {status}")


def _get_cached(kind, symbol, fetch_fn, empty):
    """Generic cache wrapper: return fresh data or refetch via fetch_fn().

    On error keep the last good value (or `empty` if we never succeeded) and
    back off briefly before retrying.
    """
    key = f"{kind}:{symbol}"
    now = time.time()
    entry = _cache.get(key)
    if entry and now < entry["refresh_at"]:
        return entry["data"]

    try:
        data = fetch_fn()
        _cache[key] = {
            "data": data,
            "fetched_at": now,
            "refresh_at": now + _TTL.get(kind, 5.0),
        }
        _log(kind, symbol, "ok")
        return data
    except Exception as e:
        _log(kind, symbol, f"failed: {e}")
        if entry:
            entry["refresh_at"] = now + 3.0  # keep stale value, retry soon
            return entry["data"]
        # Cache the empty result briefly so a hard outage doesn't spin.
        _cache[key] = {"data": empty, "fetched_at": now, "refresh_at": now + 3.0}
        return empty


def get_order_book(symbol="BTCUSDT", limit=10):
    """Top `limit` bids and asks. Normalized to lists of {price, qty} floats."""
    def fetch():
        raw = _client.get_order_book(symbol=symbol, limit=limit)
        bids = [{"price": float(p), "qty": float(q)} for p, q in raw.get("bids", [])]
        asks = [{"price": float(p), "qty": float(q)} for p, q in raw.get("asks", [])]
        return {
            "symbol": symbol,
            "bids": bids,
            "asks": asks,
            "fetched_at": time.time(),
        }

    return _get_cached("orderbook", symbol,
                       fetch, {"symbol": symbol, "bids": [], "asks": [], "fetched_at": 0.0})


def get_agg_trades(symbol="BTCUSDT", limit=50):
    """Last `limit` aggregate trades, newest first."""
    def fetch():
        raw = _client.get_aggregate_trades(symbol=symbol, limit=limit)
        trades = [{
            "price": float(t["p"]),
            "qty": float(t["q"]),
            "time": int(t["T"]),
            "is_buyer_maker": bool(t["m"]),  # True => sell-side aggressor
        } for t in raw]
        trades.reverse()  # newest first for the UI
        return {"symbol": symbol, "trades": trades, "fetched_at": time.time()}

    return _get_cached("aggtrades", symbol,
                       fetch, {"symbol": symbol, "trades": [], "fetched_at": 0.0})


def get_avg_price(symbol="BTCUSDT"):
    """Binance real-time average price (rolling window)."""
    def fetch():
        raw = _client.get_avg_price(symbol=symbol)
        return {
            "symbol": symbol,
            "mins": int(raw.get("mins", 0)),
            "price": float(raw.get("price", 0.0)),
            "fetched_at": time.time(),
        }

    return _get_cached("avgprice", symbol,
                       fetch, {"symbol": symbol, "mins": 0, "price": 0.0, "fetched_at": 0.0})


def get_market_depth(symbol="BTCUSDT"):
    """Combined snapshot the frontend can fetch in one call."""
    return {
        "symbol": symbol,
        "order_book": get_order_book(symbol),
        "agg_trades": get_agg_trades(symbol),
        "avg_price": get_avg_price(symbol),
    }
