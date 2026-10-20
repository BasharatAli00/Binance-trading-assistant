"""Liquidity Pool and Sweep Detection Algorithm.

Pure mathematical/statistical functions for detecting:
1. Swing highs and lows (fractal n-bars)
2. ATR(14) calculation per timeframe
3. Liquidity pool clustering (equal highs / lows within ATR tolerance)
4. Pool lifecycle classification (untouched, swept, broken)
5. Forward-fill gap handling and UTC-aligned resampling

Strict No-Look-Ahead Guarantee:
Any signal or confirmation at time t uses ONLY candles that were closed at or before t.
"""
from typing import List, Dict, Any, Tuple, Optional
import uuid


def forward_fill_candles(candles: List[Dict[str, Any]], interval_seconds: int = 300) -> List[Dict[str, Any]]:
    """Ensure a continuous time grid by forward-filling missing DEX candles with previous close and zero volume.
    
    Expected candle dict format:
        {'time': int, 'open': float, 'high': float, 'low': float, 'close': float, 'volume': float}
    """
    if not candles:
        return []

    # Sort ascending by timestamp
    sorted_candles = sorted(candles, key=lambda c: c["time"])
    filled: List[Dict[str, Any]] = []

    for i, candle in enumerate(sorted_candles):
        if i == 0:
            filled.append(dict(candle))
            continue

        prev_time = filled[-1]["time"]
        prev_close = filled[-1]["close"]
        curr_time = candle["time"]

        # If there is a gap greater than the expected interval
        expected_next = prev_time + interval_seconds
        while expected_next < curr_time:
            filled.append({
                "time": expected_next,
                "open": prev_close,
                "high": prev_close,
                "low": prev_close,
                "close": prev_close,
                "volume": 0.0,
            })
            expected_next += interval_seconds

        filled.append(dict(candle))

    return filled


def resample_5m_to_1h(candles_5m: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Resample 5m candles into 1h candles aligned to UTC hour boundaries (ts // 3600 * 3600).
    
    12 5m candles per 1h bucket.
    """
    if not candles_5m:
        return []

    # Group candles by hour boundary
    hour_buckets: Dict[int, List[Dict[str, Any]]] = {}
    for c in candles_5m:
        bucket_ts = (c["time"] // 3600) * 3600
        if bucket_ts not in hour_buckets:
            hour_buckets[bucket_ts] = []
        hour_buckets[bucket_ts].append(c)

    resampled_1h: List[Dict[str, Any]] = []
    # Sort hour timestamps ascending
    for hour_ts in sorted(hour_buckets.keys()):
        bucket = hour_buckets[hour_ts]
        bucket_sorted = sorted(bucket, key=lambda c: c["time"])
        
        open_val = bucket_sorted[0]["open"]
        close_val = bucket_sorted[-1]["close"]
        high_val = max(c["high"] for c in bucket_sorted)
        low_val = min(c["low"] for c in bucket_sorted)
        vol_val = sum(c.get("volume", 0.0) for c in bucket_sorted)

        resampled_1h.append({
            "time": hour_ts,
            "open": open_val,
            "high": high_val,
            "low": low_val,
            "close": close_val,
            "volume": vol_val,
        })

    return resampled_1h


def calculate_atr(candles: List[Dict[str, Any]], period: int = 14) -> List[float]:
    """Calculate Average True Range (ATR) with standard period (default 14).
    
    TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)
    Uses Wilder's smoothing after initial simple average.
    """
    n = len(candles)
    if n == 0:
        return []

    true_ranges: List[float] = []
    for i in range(n):
        c = candles[i]
        h = c["high"]
        l = c["low"]
        if i == 0:
            tr = h - l
        else:
            prev_c = candles[i - 1]["close"]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        true_ranges.append(tr)

    atrs: List[float] = [0.0] * n
    if n < period:
        # If fewer than period candles, use cumulative mean
        cum = 0.0
        for i in range(n):
            cum += true_ranges[i]
            atrs[i] = cum / (i + 1)
        return atrs

    # First ATR is simple average of first `period` TRs
    initial_atr = sum(true_ranges[:period]) / period
    atrs[period - 1] = initial_atr

    # Fill leading entries with running average
    cum = 0.0
    for i in range(period - 1):
        cum += true_ranges[i]
        atrs[i] = cum / (i + 1)

    # Wilder's smoothing for subsequent entries
    for i in range(period, n):
        atrs[i] = (atrs[i - 1] * (period - 1) + true_ranges[i]) / period

    return atrs


def detect_swings(candles: List[Dict[str, Any]], swing_n: int = 3) -> Dict[str, List[Dict[str, Any]]]:
    """Detect fractal swing highs and lows with parameter n.
    
    A candle at index i is a swing high if high[i] > high[j] for all j in [i-n, i+n] (j != i).
    A candle at index i is a swing low if low[i] < low[j] for all j in [i-n, i+n] (j != i).
    
    CONFIRMATION:
    The swing at index i is ONLY confirmed at index i + n (after n closed candles to the right).
    confirmed_at = candles[i + n]['time'].
    
    Returns dict: {"highs": [...], "lows": [...]}
    """
    total = len(candles)
    highs: List[Dict[str, Any]] = []
    lows: List[Dict[str, Any]] = []

    if total < (2 * swing_n + 1):
        return {"highs": highs, "lows": lows}

    for i in range(swing_n, total - swing_n):
        curr_h = candles[i]["high"]
        curr_l = candles[i]["low"]

        # Check Swing High
        is_high = True
        for k in range(1, swing_n + 1):
            if candles[i - k]["high"] >= curr_h or candles[i + k]["high"] >= curr_h:
                is_high = False
                break
        if is_high:
            confirmed_idx = i + swing_n
            highs.append({
                "side": "buy",
                "index": i,
                "time": candles[i]["time"],
                "price": curr_h,
                "confirmed_index": confirmed_idx,
                "confirmed_at": candles[confirmed_idx]["time"],
            })

        # Check Swing Low
        is_low = True
        for k in range(1, swing_n + 1):
            if candles[i - k]["low"] <= curr_l or candles[i + k]["low"] <= curr_l:
                is_low = False
                break
        if is_low:
            confirmed_idx = i + swing_n
            lows.append({
                "side": "sell",
                "index": i,
                "time": candles[i]["time"],
                "price": curr_l,
                "confirmed_index": confirmed_idx,
                "confirmed_at": candles[confirmed_idx]["time"],
            })

    return {"highs": highs, "lows": lows}


def cluster_liquidity_pools(
    swings: List[Dict[str, Any]],
    atrs: List[float],
    side: str,
    timeframe: str,
    tol_mult: float = 0.25,
) -> List[Dict[str, Any]]:
    """Cluster >= 2 swing points within equal-level tolerance (tol_mult * ATR).
    
    Buy-side pool = cluster of swing highs (above price). Level = highest high of cluster.
    Sell-side pool = cluster of swing lows (below price). Level = lowest low of cluster.
    
    created_at is the confirmed_at time of the swing that formed the cluster (2nd touch).
    """
    if len(swings) < 2:
        return []

    # Sort swings chronologically by confirmation time
    sorted_swings = sorted(swings, key=lambda s: (s["confirmed_at"], s["time"]))
    
    # We maintain active clusters
    # Each cluster: {"swings": [...], "representative_price": float}
    raw_clusters: List[List[Dict[str, Any]]] = []

    for s in sorted_swings:
        conf_idx = s["confirmed_index"]
        atr = atrs[conf_idx] if conf_idx < len(atrs) else (atrs[-1] if atrs else 0.0)
        tol = tol_mult * atr if atr > 0 else (s["price"] * 0.005)

        placed = False
        for cluster in raw_clusters:
            # Check if swing price is within tolerance of cluster's representative level
            cluster_prices = [item["price"] for item in cluster]
            avg_price = sum(cluster_prices) / len(cluster_prices)
            if abs(s["price"] - avg_price) <= tol:
                cluster.append(s)
                placed = True
                break

        if not placed:
            raw_clusters.append([s])

    pools: List[Dict[str, Any]] = []
    for cluster in raw_clusters:
        if len(cluster) >= 2:
            # Level: highest high for buy-side, lowest low for sell-side
            prices = [c["price"] for c in cluster]
            level = max(prices) if side == "buy" else min(prices)
            
            # Sort cluster swings by touch time
            cluster_by_time = sorted(cluster, key=lambda c: c["time"])
            first_touch_time = cluster_by_time[0]["time"]
            
            # The cluster officially becomes a liquidity pool upon confirmation of the 2nd swing
            # Sorted by confirmation time to find when >= 2 touches were confirmed
            cluster_by_conf = sorted(cluster, key=lambda c: c["confirmed_at"])
            created_at = cluster_by_conf[1]["confirmed_at"]

            pool_id = f"pool_{timeframe}_{side}_{created_at}_{uuid.uuid4().hex[:6]}"
            pools.append({
                "id": pool_id,
                "timeframe": timeframe,
                "side": side,
                "level": level,
                "first_touch_time": first_touch_time,
                "created_at": created_at,
                "touches": len(cluster),
                "touch_times": [c["time"] for c in cluster_by_time],
                "prices": prices,
            })

    return pools


def evaluate_pool_states_and_sweeps(
    pools: List[Dict[str, Any]],
    candles: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Evaluate pool state on closed candles strictly after pool.created_at.
    
    States:
      * untouched: price never traded beyond the level
      * swept: a candle's wick goes beyond the level but it CLOSES back inside
        (buy-side: high > level and close < level; sell-side: low < level and close > level).
        Or a candle closed beyond but closed back inside within 2 candles.
      * broken: a candle CLOSES beyond the level and does not close back inside within next 2 candles.
    
    Returns (evaluated_pools, sweeps)
    """
    if not candles or not pools:
        for p in pools:
            p["state"] = "untouched"
            p["end_time"] = candles[-1]["time"] if candles else p["created_at"]
        return pools, []

    evaluated_pools: List[Dict[str, Any]] = []
    sweeps: List[Dict[str, Any]] = []
    
    # Map timestamp to candle index for fast lookup
    time_to_idx = {c["time"]: i for i, c in enumerate(candles)}
    total_candles = len(candles)

    for p in pools:
        pool = dict(p)
        created_at = pool["created_at"]
        level = pool["level"]
        side = pool["side"]

        # Find starting candle index (first candle strictly after created_at)
        start_idx = None
        for i, c in enumerate(candles):
            if c["time"] > created_at:
                start_idx = i
                break

        if start_idx is None:
            # All candles are at or before created_at
            pool["state"] = "untouched"
            pool["end_time"] = candles[-1]["time"]
            evaluated_pools.append(pool)
            continue

        state = "untouched"
        sweep_time: Optional[int] = None
        sweep_price: Optional[float] = None
        broken_time: Optional[int] = None
        end_time = candles[-1]["time"]

        i = start_idx
        while i < total_candles:
            c = candles[i]
            
            if side == "buy":
                # Check for Close beyond level
                if c["close"] > level:
                    # Check next 2 candles to see if it closes back inside (<= level)
                    closed_back = False
                    for look in range(1, 3):
                        if (i + look) < total_candles:
                            if candles[i + look]["close"] <= level:
                                closed_back = True
                                break
                    if closed_back:
                        # False breakout closing back inside => Swept!
                        state = "swept"
                        sweep_time = c["time"]
                        sweep_price = c["high"]
                        end_time = c["time"]
                        sweeps.append({
                            "pool_id": pool["id"],
                            "timeframe": pool["timeframe"],
                            "side": side,
                            "level": level,
                            "time": c["time"],
                            "sweep_price": c["high"],
                            "candle_index": i,
                            "direction_hint": "bearish",
                        })
                        break
                    else:
                        # Real breakout => Broken!
                        state = "broken"
                        broken_time = c["time"]
                        end_time = c["time"]
                        break

                # Check for Wick beyond level with close inside
                elif c["high"] > level and c["close"] <= level:
                    state = "swept"
                    sweep_time = c["time"]
                    sweep_price = c["high"]
                    end_time = c["time"]
                    sweeps.append({
                        "pool_id": pool["id"],
                        "timeframe": pool["timeframe"],
                        "side": side,
                        "level": level,
                        "time": c["time"],
                        "sweep_price": c["high"],
                        "candle_index": i,
                        "direction_hint": "bearish",
                    })
                    break

            else:  # sell-side
                # Check for Close beyond level (below support)
                if c["close"] < level:
                    closed_back = False
                    for look in range(1, 3):
                        if (i + look) < total_candles:
                            if candles[i + look]["close"] >= level:
                                closed_back = True
                                break
                    if closed_back:
                        # False breakdown closing back inside => Swept!
                        state = "swept"
                        sweep_time = c["time"]
                        sweep_price = c["low"]
                        end_time = c["time"]
                        sweeps.append({
                            "pool_id": pool["id"],
                            "timeframe": pool["timeframe"],
                            "side": side,
                            "level": level,
                            "time": c["time"],
                            "sweep_price": c["low"],
                            "candle_index": i,
                            "direction_hint": "bullish",
                        })
                        break
                    else:
                        # Real breakout => Broken!
                        state = "broken"
                        broken_time = c["time"]
                        end_time = c["time"]
                        break

                # Check for Wick beyond level with close inside
                elif c["low"] < level and c["close"] >= level:
                    state = "swept"
                    sweep_time = c["time"]
                    sweep_price = c["low"]
                    end_time = c["time"]
                    sweeps.append({
                        "pool_id": pool["id"],
                        "timeframe": pool["timeframe"],
                        "side": side,
                        "level": level,
                        "time": c["time"],
                        "sweep_price": c["low"],
                        "candle_index": i,
                        "direction_hint": "bullish",
                    })
                    break

            i += 1

        pool["state"] = state
        pool["end_time"] = end_time
        if sweep_time is not None:
            pool["sweep_time"] = sweep_time
            pool["sweep_price"] = sweep_price
        if broken_time is not None:
            pool["broken_time"] = broken_time

        evaluated_pools.append(pool)

    return evaluated_pools, sweeps


def detect_pools_for_timeframe(
    candles: List[Dict[str, Any]],
    timeframe: str,
    swing_n: int = 3,
    tol_mult: float = 0.25,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Run detection pipeline on a single timeframe's closed candles.
    
    Returns (evaluated_pools, sweeps)
    """
    if len(candles) < (2 * swing_n + 1):
        return [], []

    atrs = calculate_atr(candles, period=14)
    swings = detect_swings(candles, swing_n=swing_n)

    buy_pools = cluster_liquidity_pools(
        swings["highs"], atrs, side="buy", timeframe=timeframe, tol_mult=tol_mult
    )
    sell_pools = cluster_liquidity_pools(
        swings["lows"], atrs, side="sell", timeframe=timeframe, tol_mult=tol_mult
    )
    all_raw_pools = buy_pools + sell_pools

    evaluated_pools, sweeps = evaluate_pool_states_and_sweeps(all_raw_pools, candles)
    return evaluated_pools, sweeps


def run_full_liquidity_detection(
    raw_5m_candles: List[Dict[str, Any]],
    swing_n: int = 3,
    tol_mult: float = 0.25,
    max_pools: int = 50,
) -> Dict[str, Any]:
    """Complete liquidity detection pipeline for both 5m and 1h timeframes.
    
    1. Forward-fills DEX candle gaps.
    2. Drops forming candle if incomplete.
    3. Resamples 5m to 1h candles.
    4. Runs identical detection algorithm on both 5m and 1h closed candles.
    5. Returns unified result payload.
    """
    if not raw_5m_candles:
        return {
            "candles_5m": [],
            "candles_1h": [],
            "pools_1h": [],
            "pools_5m": [],
            "sweeps": [],
            "meta": {"history_start": None, "history_end": None, "candle_count": 0},
        }

    # 1. Forward-fill gaps at 5-minute (300s) resolution
    candles_5m = forward_fill_candles(raw_5m_candles, interval_seconds=300)

    # 2. Resample continuous 5m candles to 1h
    candles_1h = resample_5m_to_1h(candles_5m)

    # 3. Detect 5m pools and sweeps
    pools_5m, sweeps_5m = detect_pools_for_timeframe(
        candles_5m, timeframe="5m", swing_n=swing_n, tol_mult=tol_mult
    )

    # 4. Detect 1h pools and sweeps
    pools_1h, sweeps_1h = detect_pools_for_timeframe(
        candles_1h, timeframe="1h", swing_n=swing_n, tol_mult=tol_mult
    )

    # Combine and sort sweeps newest first
    all_sweeps = sorted(sweeps_1h + sweeps_5m, key=lambda s: s["time"], reverse=True)

    # Optional: limit number of returned pools if max_pools specified
    if max_pools and max_pools > 0:
        pools_5m = sorted(pools_5m, key=lambda p: p["created_at"], reverse=True)[:max_pools]
        pools_1h = sorted(pools_1h, key=lambda p: p["created_at"], reverse=True)[:max_pools]

    history_start = candles_5m[0]["time"] if candles_5m else None
    history_end = candles_5m[-1]["time"] if candles_5m else None

    return {
        "candles_5m": candles_5m,
        "candles_1h": candles_1h,
        "pools_1h": pools_1h,
        "pools_5m": pools_5m,
        "sweeps": all_sweeps,
        "meta": {
            "history_start": history_start,
            "history_end": history_end,
            "candle_count_5m": len(candles_5m),
            "candle_count_1h": len(candles_1h),
            "params": {
                "swing_n": swing_n,
                "tol_mult": tol_mult,
                "max_pools": max_pools,
            },
        },
    }
