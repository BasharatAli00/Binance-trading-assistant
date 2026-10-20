"""Provider abstraction for fetching DEX candle data and pool metadata.

Supports GeckoTerminal API v2 with rate limit backoff, caching (15-30s TTL),
and pagination via `before_timestamp`.
Configurable via environment variables (TOKEN_ADDRESS, POOL_ADDRESS, NETWORK).
"""
import os
import time
import requests
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple

# Defaults configurable via env
DEFAULT_TOKEN_ADDRESS = os.getenv("TOKEN_ADDRESS", "0x56fa3670e19396c4ee8f7775b49ceaede04a84ef").strip().lower()
DEFAULT_POOL_ADDRESS = os.getenv("POOL_ADDRESS", "").strip().lower()
DEFAULT_NETWORK = os.getenv("NETWORK", "robinhood").strip().lower()

GECKOTERMINAL_BASE_URL = os.getenv("GECKOTERMINAL_BASE_URL", "https://api.geckoterminal.com/api/v2")
CACHE_TTL_SECONDS = int(os.getenv("LIQUIDITY_CACHE_TTL", "20"))


class CandleProvider(ABC):
    """Abstract provider interface so candle sources can be swapped seamlessly."""

    @abstractmethod
    def resolve_top_pool(self, network: str, token_address: str) -> Optional[Dict[str, Any]]:
        """Resolve the pool with the highest liquidity for a given token address."""
        pass

    @abstractmethod
    def get_pool_info(self, network: str, pool_address: str) -> Dict[str, Any]:
        """Fetch real-time pool info: pair address, liquidity_usd, volume_24h, price_usd."""
        pass

    @abstractmethod
    def get_candles(self, network: str, pool_address: str, timeframe: str = "5m", limit: int = 1000) -> List[Dict[str, Any]]:
        """Fetch closed OHLCV candles for the pool."""
        pass


class GeckoTerminalProvider(CandleProvider):
    """GeckoTerminal API v2 implementation with TTL cache and exponential backoff."""

    def __init__(self, base_url: str = GECKOTERMINAL_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json;version=20230302",
            "User-Agent": "BinanceTraderPro/1.0",
        })
        # Simple in-memory cache: {cache_key: (timestamp, data)}
        self._cache: Dict[str, Tuple[float, Any]] = {}

    def _get_with_backoff(self, url: str, params: Optional[Dict[str, Any]] = None, max_retries: int = 3) -> Optional[requests.Response]:
        """Execute GET request with exponential backoff for 429 rate limits."""
        delay = 1.0
        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=12)
                if resp.status_code == 429:
                    # Rate limited: wait with backoff
                    retry_after = resp.headers.get("Retry-After")
                    sleep_time = float(retry_after) if retry_after else delay
                    time.sleep(sleep_time)
                    delay *= 2.0
                    continue
                return resp
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"[GeckoTerminalProvider] GET error on {url}: {e}")
                    return None
                time.sleep(delay)
                delay *= 2.0
        return None

    def _get_cached(self, key: str) -> Optional[Any]:
        if key in self._cache:
            ts, val = self._cache[key]
            if (time.time() - ts) < CACHE_TTL_SECONDS:
                return val
            del self._cache[key]
        return None

    def _set_cached(self, key: str, val: Any):
        self._cache[key] = (time.time(), val)

    def resolve_top_pool(self, network: str, token_address: str) -> Optional[Dict[str, Any]]:
        """Look up all pools for token address and pick the one with highest liquidity reserve."""
        token_clean = token_address.lower().strip()
        cache_key = f"top_pool_{network}_{token_clean}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        url = f"{self.base_url}/networks/{network}/tokens/{token_clean}/pools"
        resp = self._get_with_backoff(url)
        if not resp or not resp.ok:
            return None

        try:
            data = resp.json()
            pools = data.get("data", [])
            if not pools:
                return None

            # Sort pools by reserve_in_usd descending
            sorted_pools = sorted(
                pools,
                key=lambda p: float(p.get("attributes", {}).get("reserve_in_usd") or 0.0),
                reverse=True,
            )
            top = sorted_pools[0]
            attr = top.get("attributes", {})
            pool_info = {
                "address": attr.get("address", top.get("id")),
                "name": attr.get("name", "Unknown Pool"),
                "liquidity_usd": float(attr.get("reserve_in_usd") or 0.0),
                "volume_24h": float((attr.get("volume_usd") or {}).get("h24") or 0.0),
                "price_usd": float(attr.get("base_token_price_usd") or 0.0),
            }
            self._set_cached(cache_key, pool_info)
            return pool_info
        except Exception as e:
            print(f"[GeckoTerminalProvider] resolve_top_pool error: {e}")
            return None

    def get_pool_info(self, network: str, pool_address: str) -> Dict[str, Any]:
        """Fetch details of a specific pool."""
        pool_clean = pool_address.lower().strip()
        cache_key = f"pool_info_{network}_{pool_clean}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        url = f"{self.base_url}/networks/{network}/pools/{pool_clean}"
        resp = self._get_with_backoff(url)
        if not resp or not resp.ok:
            return {
                "address": pool_clean,
                "name": "Pool",
                "liquidity_usd": 0.0,
                "volume_24h": 0.0,
                "price_usd": 0.0,
            }

        try:
            attr = resp.json().get("data", {}).get("attributes", {})
            info = {
                "address": attr.get("address", pool_clean),
                "name": attr.get("name", "Unknown Pool"),
                "liquidity_usd": float(attr.get("reserve_in_usd") or 0.0),
                "volume_24h": float((attr.get("volume_usd") or {}).get("h24") or 0.0),
                "price_usd": float(attr.get("base_token_price_usd") or 0.0),
            }
            self._set_cached(cache_key, info)
            return info
        except Exception as e:
            print(f"[GeckoTerminalProvider] get_pool_info error: {e}")
            return {
                "address": pool_clean,
                "name": "Pool",
                "liquidity_usd": 0.0,
                "volume_24h": 0.0,
                "price_usd": 0.0,
            }

    def get_candles(self, network: str, pool_address: str, timeframe: str = "5m", limit: int = 1000) -> List[Dict[str, Any]]:
        """Fetch 5m OHLCV candles with limit and pagination support."""
        pool_clean = pool_address.lower().strip()
        cache_key = f"candles_{network}_{pool_clean}_{timeframe}_{limit}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        # GeckoTerminal uses aggregate=5 for 5m candles
        aggregate = 5 if timeframe == "5m" else 1
        url = f"{self.base_url}/networks/{network}/pools/{pool_clean}/ohlcv/minute"
        
        all_ohlcv: List[List[Any]] = []
        fetch_limit = min(limit, 1000)
        params = {"aggregate": aggregate, "limit": fetch_limit}

        resp = self._get_with_backoff(url, params=params)
        if resp and resp.ok:
            data = resp.json().get("data", {}).get("attributes", {})
            ohlcv_list = data.get("ohlcv_list", [])
            all_ohlcv.extend(ohlcv_list)

            # If the user asked for > 1000 candles and we received a full page, paginate
            if limit > 1000 and len(ohlcv_list) >= 1000:
                oldest_ts = ohlcv_list[-1][0]
                remaining = limit - len(all_ohlcv)
                params_pag = {
                    "aggregate": aggregate,
                    "limit": min(remaining, 1000),
                    "before_timestamp": oldest_ts,
                }
                resp_pag = self._get_with_backoff(url, params=params_pag)
                if resp_pag and resp_pag.ok:
                    data_pag = resp_pag.json().get("data", {}).get("attributes", {})
                    all_ohlcv.extend(data_pag.get("ohlcv_list", []))

        # Format and sort chronologically (oldest -> newest)
        # GeckoTerminal returns: [timestamp, open, high, low, close, volume] (newest first)
        formatted: List[Dict[str, Any]] = []
        for c in reversed(all_ohlcv):
            if len(c) >= 6:
                formatted.append({
                    "time": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                })

        # Drop the still-forming last candle if its 5m interval is not yet closed
        now = time.time()
        if formatted and (formatted[-1]["time"] + 300 > now):
            formatted.pop()

        self._set_cached(cache_key, formatted)
        return formatted
