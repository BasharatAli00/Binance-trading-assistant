"""Free macro context for the sniper: SOL price (Jupiter) + Fear & Greed.

Reuses the existing fear_greed.py cache (Strategy #1 already maintains it) and
adds a cached SOL/USD price from Jupiter's keyless price API. All free, no keys.
"""
import time
import requests

import sniper_config as cfg
from fear_greed import get_fear_greed

_cache = {
    "sol_price_usd": 150.0,    # safe fallback until first fetch
    "fear_greed_index": 50,
    "fear_greed_label": "Neutral",
    "fetched_at": 0.0,
}


def refresh_macro():
    """Refresh SOL price + Fear & Greed. Cheap; safe to call every ~15 min."""
    # SOL price via Jupiter lite price API v3 (free, no key).
    # Response shape: {"<mint>": {"usdPrice": <float>, ...}}
    try:
        r = requests.get(cfg.JUPITER_PRICE_URL,
                         params={"ids": cfg.WSOL_MINT}, timeout=10)
        r.raise_for_status()
        sol = r.json()[cfg.WSOL_MINT]
        _cache["sol_price_usd"] = float(sol["usdPrice"])
    except Exception as e:
        print(f"[sniper.macro] SOL price error: {e}")

    # Fear & Greed via the shared cache (refreshes ~once/day internally)
    try:
        fng = get_fear_greed()
        if fng.get("value") is not None:
            _cache["fear_greed_index"] = int(fng["value"])
            _cache["fear_greed_label"] = fng.get("classification") or "Neutral"
    except Exception as e:
        print(f"[sniper.macro] F&G error: {e}")

    _cache["fetched_at"] = time.time()
    return dict(_cache)


def get_macro():
    return dict(_cache)
