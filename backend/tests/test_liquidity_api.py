"""Unit tests for the liquidity pool API router and provider."""
import pytest
from unittest.mock import MagicMock, patch
from liquidity_pool_api import get_liquidity_data
from liquidity_provider import GeckoTerminalProvider


def test_provider_cache():
    """Verify that provider caches get_candles and doesn't re-query if within TTL."""
    provider = GeckoTerminalProvider()
    mock_candles = [{"time": 1000, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 10.0}]
    
    with patch.object(provider, "_get_with_backoff") as mock_get:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {"attributes": {"ohlcv_list": [[1000, 1.0, 1.1, 0.9, 1.0, 10.0]]}}
        }
        mock_get.return_value = mock_resp

        # First call fetches from API
        c1 = provider.get_candles("robinhood", "0xtestpool")
        assert len(c1) == 1
        assert mock_get.call_count == 1

        # Second call returns from cache without calling API
        c2 = provider.get_candles("robinhood", "0xtestpool")
        assert len(c2) == 1
        assert mock_get.call_count == 1


def test_api_endpoint_structure():
    """Verify get_liquidity_data returns the complete expected schema."""
    sample_candles = [
        {"time": 1700000000 + i * 300, "open": 1.0 + (i % 3) * 0.1, "high": 1.2 + (i % 3) * 0.1, "low": 0.9, "close": 1.0, "volume": 100.0}
        for i in range(100)
    ]
    
    with patch("liquidity_pool_api.provider") as mock_p:
        mock_p.get_pool_info.return_value = {
            "address": "0xpool123",
            "name": "VRAX / USDG",
            "liquidity_usd": 150000.0,
            "volume_24h": 350000.0,
            "price_usd": 0.0035,
        }
        mock_p.get_candles.return_value = sample_candles

        res = get_liquidity_data(pool_address="0xpool123", limit=100)
        assert isinstance(res, dict)
        assert "token" in res
        assert "pool" in res
        assert "candles" in res
        assert "pools_1h" in res
        assert "pools_5m" in res
        assert "sweeps" in res
        assert "meta" in res

        # Verify pool metadata
        assert res["pool"]["address"] == "0xpool123"
        assert res["pool"]["liquidity_usd"] == 150000.0
        assert res["pool"]["volume_24h"] == 350000.0

        # Verify meta
        assert "history_summary" in res["meta"]
        assert "params" in res["meta"]
        assert res["meta"]["candle_count"] == 100
