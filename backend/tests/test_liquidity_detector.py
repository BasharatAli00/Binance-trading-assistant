"""Unit tests for the liquidity pool and sweep detection algorithm."""
import pytest
from liquidity_detector import (
    forward_fill_candles,
    resample_5m_to_1h,
    calculate_atr,
    detect_swings,
    cluster_liquidity_pools,
    evaluate_pool_states_and_sweeps,
    detect_pools_for_timeframe,
    run_full_liquidity_detection,
)


def make_candle(t, o, h, l, c, v=100.0):
    return {"time": t, "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)}


def test_forward_fill_gaps():
    """Verify that gaps between DEX candles are forward-filled with previous close and zero volume."""
    raw = [
        make_candle(1000, 10.0, 10.5, 9.8, 10.2, 50.0),
        # Gap of 900s (missing 1300 and 1600 for 300s interval)
        make_candle(1900, 10.3, 11.0, 10.1, 10.8, 80.0),
    ]
    filled = forward_fill_candles(raw, interval_seconds=300)
    assert len(filled) == 4
    assert [c["time"] for c in filled] == [1000, 1300, 1600, 1900]
    
    # Gap candles should have previous close and 0 volume
    assert filled[1]["close"] == 10.2
    assert filled[1]["open"] == 10.2
    assert filled[1]["volume"] == 0.0
    assert filled[2]["close"] == 10.2
    assert filled[2]["volume"] == 0.0
    
    # Final candle unchanged
    assert filled[3]["time"] == 1900
    assert filled[3]["close"] == 10.8


def test_resampling_5m_to_1h():
    """Verify 12 5m candles in a UTC hour are correctly resampled into a single 1h candle."""
    base_ts = 1700000000 - (1700000000 % 3600)  # Aligned to hour boundary
    candles_5m = []
    
    for i in range(12):
        t = base_ts + i * 300
        o = 100.0 + i
        h = 100.0 + i + 2.0
        l = 100.0 + i - 1.0
        c = 100.0 + i + 0.5
        candles_5m.append(make_candle(t, o, h, l, c, v=10.0))

    candles_1h = resample_5m_to_1h(candles_5m)
    assert len(candles_1h) == 1
    c1h = candles_1h[0]
    
    assert c1h["time"] == base_ts
    assert c1h["open"] == candles_5m[0]["open"]
    assert c1h["close"] == candles_5m[-1]["close"]
    assert c1h["high"] == max(c["high"] for c in candles_5m)
    assert c1h["low"] == min(c["low"] for c in candles_5m)
    assert c1h["volume"] == 120.0


def test_atr_calculation():
    """Verify ATR computes correctly with period 14."""
    # 20 flat candles
    candles = [make_candle(i * 300, 100, 105, 95, 100) for i in range(20)]
    atrs = calculate_atr(candles, period=14)
    assert len(atrs) == 20
    # For every candle, high - low = 10, close is constant 100 so TR is always 10
    assert pytest.approx(atrs[-1], 0.001) == 10.0


def test_swing_detection():
    """Verify fractal n=3 swing high/low detection and confirmation delay."""
    # Construct series with a clear peak at index 4 (time 1200) and trough at index 9 (time 2700)
    prices = [10, 11, 12, 14, 20, 13, 12, 11, 8, 4, 7, 8, 9, 10]
    candles = [make_candle(i * 300, p, p + 0.5, p - 0.5, p) for i, p in enumerate(prices)]

    swings = detect_swings(candles, swing_n=3)
    
    # Peak is at index 4 (highest high = 20.5)
    highs = swings["highs"]
    assert len(highs) == 1
    h = highs[0]
    assert h["index"] == 4
    assert h["price"] == 20.5
    # Confirmed strictly after 3 candles to right => index 7 (time = 7 * 300 = 2100)
    assert h["confirmed_index"] == 7
    assert h["confirmed_at"] == candles[7]["time"]

    # Trough is at index 9 (lowest low = 3.5)
    lows = swings["lows"]
    assert len(lows) == 1
    l = lows[0]
    assert l["index"] == 9
    assert l["price"] == 3.5
    # Confirmed at index 9 + 3 = 12
    assert l["confirmed_index"] == 12
    assert l["confirmed_at"] == candles[12]["time"]


def test_no_look_ahead():
    """Verify that at time t, no swings or pools have confirmed_at or created_at > t."""
    # Generate random-like price walk
    candles = []
    p = 100.0
    for i in range(50):
        step = 1.0 if (i % 5 == 2 or i % 7 == 3) else -0.8
        p += step
        candles.append(make_candle(i * 300, p, p + 1.0, p - 1.0, p))

    # Test at multiple cutoff points
    for cutoff_idx in [15, 25, 40]:
        cutoff_candles = candles[:cutoff_idx]
        cutoff_time = cutoff_candles[-1]["time"]

        swings = detect_swings(cutoff_candles, swing_n=3)
        for s in swings["highs"] + swings["lows"]:
            assert s["confirmed_at"] <= cutoff_time
            assert s["confirmed_index"] < cutoff_idx

        atrs = calculate_atr(cutoff_candles, period=14)
        pools = cluster_liquidity_pools(swings["highs"], atrs, side="buy", timeframe="5m")
        for pool in pools:
            assert pool["created_at"] <= cutoff_time
            assert pool["first_touch_time"] < pool["created_at"]


def test_clustering_with_atr_tolerance():
    """Verify that swings within tol_mult * ATR cluster, and those outside do not."""
    # Two swing highs at prices 100.0 and 100.1, with ATR = 1.0, tol_mult = 0.25 (tolerance = 0.25)
    swings = [
        {"side": "buy", "index": 5, "time": 1500, "price": 100.0, "confirmed_index": 8, "confirmed_at": 2400},
        {"side": "buy", "index": 12, "time": 3600, "price": 100.1, "confirmed_index": 15, "confirmed_at": 4500},
    ]
    atrs = [1.0] * 20
    
    # Inside tolerance (diff is 0.1 <= 0.25)
    pools = cluster_liquidity_pools(swings, atrs, side="buy", timeframe="5m", tol_mult=0.25)
    assert len(pools) == 1
    assert pools[0]["touches"] == 2
    assert pools[0]["level"] == 100.1  # Highest high of the cluster
    assert pools[0]["first_touch_time"] == 1500
    assert pools[0]["created_at"] == 4500  # Confirmed at 2nd swing

    # Outside tolerance: swing at 100.0 and 101.0 (diff 1.0 > 0.25)
    swings_far = [
        {"side": "buy", "index": 5, "time": 1500, "price": 100.0, "confirmed_index": 8, "confirmed_at": 2400},
        {"side": "buy", "index": 12, "time": 3600, "price": 101.0, "confirmed_index": 15, "confirmed_at": 4500},
    ]
    pools_far = cluster_liquidity_pools(swings_far, atrs, side="buy", timeframe="5m", tol_mult=0.25)
    assert len(pools_far) == 0  # No cluster with >= 2 touches formed


def test_sweep_vs_breakout_classification():
    """Verify classification of untouched, swept (wick fakeout), and broken (real breakout)."""
    # Create a baseline buy-side pool at level 100.0 with created_at = 1000
    pool = {
        "id": "test_pool_1",
        "timeframe": "5m",
        "side": "buy",
        "level": 100.0,
        "first_touch_time": 500,
        "created_at": 1000,
        "touches": 2,
    }

    # Case 1: Untouched (price stays below 100)
    candles_untouched = [
        make_candle(1000, 95, 96, 94, 95),
        make_candle(1300, 95, 97, 94, 96),
        make_candle(1600, 96, 98, 95, 97),
    ]
    eval_pools, sweeps = evaluate_pool_states_and_sweeps([pool], candles_untouched)
    assert eval_pools[0]["state"] == "untouched"
    assert len(sweeps) == 0

    # Case 2: Swept (candle wicks to 102.0 but closes at 99.0 < level 100.0)
    candles_swept = [
        make_candle(1000, 95, 96, 94, 95),
        make_candle(1300, 97, 102.0, 96, 99.0),  # High > 100, close < 100
        make_candle(1600, 98, 99, 97, 97),
    ]
    eval_pools_sw, sweeps_sw = evaluate_pool_states_and_sweeps([pool], candles_swept)
    assert eval_pools_sw[0]["state"] == "swept"
    assert eval_pools_sw[0]["sweep_price"] == 102.0
    assert eval_pools_sw[0]["sweep_time"] == 1300
    assert len(sweeps_sw) == 1
    assert sweeps_sw[0]["direction_hint"] == "bearish"
    assert sweeps_sw[0]["level"] == 100.0

    # Case 3: Broken (candle closes at 103.0 > 100.0 and subsequent candles stay above 100.0)
    candles_broken = [
        make_candle(1000, 95, 96, 94, 95),
        make_candle(1300, 98, 104.0, 97, 103.0),  # Closes above
        make_candle(1600, 103, 105.0, 102, 104.0), # Stays above
        make_candle(1900, 104, 106.0, 103, 105.0), # Stays above
    ]
    eval_pools_br, sweeps_br = evaluate_pool_states_and_sweeps([pool], candles_broken)
    assert eval_pools_br[0]["state"] == "broken"
    assert eval_pools_br[0]["broken_time"] == 1300
    assert len(sweeps_br) == 0


def test_sell_side_sweep():
    """Verify sell-side sweep (wick below support and closes inside => bullish reversal context)."""
    pool = {
        "id": "test_sell_pool",
        "timeframe": "5m",
        "side": "sell",
        "level": 50.0,
        "first_touch_time": 500,
        "created_at": 1000,
        "touches": 2,
    }
    candles = [
        make_candle(1000, 55, 56, 54, 55),
        make_candle(1300, 52, 53, 47.0, 51.0),  # Wick down to 47 (<50), closes at 51 (>50)
        make_candle(1600, 51, 54, 50, 53),
    ]
    eval_pools, sweeps = evaluate_pool_states_and_sweeps([pool], candles)
    assert eval_pools[0]["state"] == "swept"
    assert eval_pools[0]["sweep_price"] == 47.0
    assert len(sweeps) == 1
    assert sweeps[0]["direction_hint"] == "bullish"


def test_full_liquidity_detection_integration():
    """Test full pipeline end to end on synthetic multi-day data."""
    # Create 300 5m candles (25 hours) with periodic waves to ensure swings and pools form
    import math
    base_ts = 1700000000
    raw_5m = []
    for i in range(300):
        t = base_ts + i * 300
        # Sinusoidal price with two equal tops at ~110 and two equal bottoms at ~90
        val = 100.0 + 10.0 * math.sin(i * 0.1)
        raw_5m.append(make_candle(t, val, val + 0.5, val - 0.5, val, v=50.0))

    result = run_full_liquidity_detection(raw_5m, swing_n=3, tol_mult=0.5)
    assert len(result["candles_5m"]) == 300
    assert len(result["candles_1h"]) > 0
    assert "pools_1h" in result
    assert "pools_5m" in result
    assert "sweeps" in result
    assert result["meta"]["candle_count_5m"] == 300
