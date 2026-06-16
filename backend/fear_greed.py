"""Crypto Fear & Greed Index (alternative.me).

Market-wide sentiment score 0-100, updated once per day (~00:00 UTC). We cache
the value and only hit the network when the API's own `time_until_update` says a
fresh value is due, so the hourly trader loop can call get_fear_greed() freely
without spamming the endpoint.
"""
import time
import requests

_API_URL = "https://api.alternative.me/fng/?limit=1"

# Cached snapshot shared across the trader loop.
_cache = {
    "value": None,            # int 0-100, or None until first successful fetch
    "classification": None,   # "Extreme Fear" .. "Extreme Greed"
    "fetched_at": 0.0,        # epoch seconds of last successful fetch
    "refresh_at": 0.0,        # epoch seconds when we're allowed to fetch again
}


def _snapshot():
    return {
        "value": _cache["value"],
        "classification": _cache["classification"],
        "fetched_at": _cache["fetched_at"],
    }


def get_fear_greed(force=False):
    """Return the cached Fear & Greed snapshot, refreshing at most once a day.

    Returns a dict: {"value": int|None, "classification": str|None, "fetched_at": float}.
    On a fetch error the last known value is kept (value stays None if we've never
    succeeded) and we back off for an hour before retrying.
    """
    now = time.time()
    if not force and _cache["value"] is not None and now < _cache["refresh_at"]:
        return _snapshot()

    try:
        resp = requests.get(_API_URL, timeout=10)
        resp.raise_for_status()
        d = resp.json()["data"][0]
        _cache["value"] = int(d["value"])
        _cache["classification"] = d.get("value_classification", "")
        _cache["fetched_at"] = now
        # Trust the API's countdown, but clamp to [1h, 24h] as a safety net.
        ttl = int(d.get("time_until_update") or 3600)
        _cache["refresh_at"] = now + max(3600, min(ttl, 86400))
        print(f"[FearGreed] {_cache['value']} ({_cache['classification']})")
    except Exception as e:
        print(f"[FearGreed] fetch failed: {e}")
        _cache["refresh_at"] = now + 3600  # retry in an hour, keep stale value

    return _snapshot()
