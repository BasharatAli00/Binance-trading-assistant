"""Point-in-time features from CLOSED 1-minute candles.

No look-ahead by construction: `features(candles, as_of_ts)` only uses candles whose bucket
ended at or before as_of_ts (bucket + 60 <= as_of_ts); anything later is ignored even if the
caller passes it. Every feature is reproducible from stored candles, so live decisions and
replays see exactly the same numbers.

Candle dicts use the rhc_candle columns: bucket, o, h, l, c, c_usd, vol_usd, buys, sells,
buy_usd, sell_usd, traders, large, liq, liq_usd.
"""
from statistics import median

TF = 60


def closed_until(candles, as_of_ts):
    """Pure: only candles fully closed at as_of_ts, sorted by bucket (de-duplicated)."""
    seen = {}
    for c in candles:
        if c["bucket"] + TF <= as_of_ts:
            seen[c["bucket"]] = c
    return [seen[b] for b in sorted(seen)]


def _window(cs, end_bucket, minutes):
    start = end_bucket - (minutes - 1) * TF
    return [c for c in cs if start <= c["bucket"] <= end_bucket]


def _price(c):
    return c.get("c_usd") or c.get("c")


def _ret(cs, last, minutes):
    """Return over `minutes` using the last close at or before last_bucket - minutes."""
    target = last["bucket"] - minutes * TF
    prior = [c for c in cs if c["bucket"] <= target]
    if not prior or not _price(prior[-1]) or not _price(last):
        return None
    return _price(last) / _price(prior[-1]) - 1.0


def _sum(cs, key):
    return sum((c.get(key) or 0) for c in cs)


def _atr(cs, n):
    """Mean true range (as a fraction of close) over the last n candles."""
    sel = cs[-n:]
    if len(sel) < 2:
        return None
    trs = []
    prev_close = None
    for c in sel:
        hi, lo, cl = c.get("h"), c.get("l"), c.get("c")
        if not hi or not lo or not cl:
            continue
        tr = hi - lo if prev_close is None else max(hi, prev_close) - min(lo, prev_close)
        trs.append(tr / cl)
        prev_close = cl
    return sum(trs) / len(trs) if trs else None


def features(candles, as_of_ts):
    """Pure: dict of features at as_of_ts (None where not computable)."""
    cs = closed_until(candles, as_of_ts)
    if not cs:
        return {"n_candles": 0}
    last = cs[-1]
    lb = last["bucket"]
    w5, w15, w60 = _window(cs, lb, 5), _window(cs, lb, 15), _window(cs, lb, 60)
    prev15 = _window(cs, lb - 15 * TF, 15)
    prior60_excl5 = [c for c in w60 if c["bucket"] <= lb - 5 * TF]

    def imbalance(ws):
        b, s = _sum(ws, "buy_usd"), _sum(ws, "sell_usd")
        return b / (b + s) if (b + s) > 0 else None

    # 5m volume buckets over the prior 55 minutes, for a robust (median) baseline
    vol5_hist = []
    for k in range(1, 12):
        seg = [c for c in cs if lb - (5 * k + 4) * TF <= c["bucket"] <= lb - 5 * k * TF]
        vol5_hist.append(_sum(seg, "vol_usd"))
    base5 = median(vol5_hist) if vol5_hist else 0.0
    vol5 = _sum(w5, "vol_usd")

    prior_high = max((c["h"] for c in cs[-31:-1] if c.get("h")), default=None)
    vwap_num = sum((c.get("vol_usd") or 0) * (c.get("c") or 0) for c in w60)
    vwap_den = _sum(w60, "vol_usd")
    vwap = vwap_num / vwap_den if vwap_den > 0 else None

    def liq_of(c):
        return c.get("liq_usd") if c.get("liq_usd") is not None else c.get("liq")

    def liq_change(minutes):
        prior = [c for c in cs if c["bucket"] <= lb - minutes * TF and liq_of(c)]
        if not prior or not liq_of(last):
            return None
        return liq_of(last) / liq_of(prior[-1]) - 1.0

    atr14 = _atr(cs, 14)
    atr60 = _atr(cs[:-14], 60) if len(cs) > 30 else None
    rng = (last["h"] - last["l"]) / last["c"] if last.get("h") and last.get("l") and last.get("c") else None
    close_pos = ((last["c"] - last["l"]) / (last["h"] - last["l"])
                 if last.get("h") and last.get("l") and last["h"] > last["l"] else None)

    return {
        "as_of": as_of_ts,
        "last_bucket": lb,
        "n_candles": len(cs),
        "coverage_60m": len(w60) / 60.0,                 # data quality: minutes with trades
        "price_usd": _price(last),
        "close_q": last.get("c"),
        "ret_1m": _ret(cs, last, 1),
        "ret_5m": _ret(cs, last, 5),
        "ret_15m": _ret(cs, last, 15),
        "ret_60m": _ret(cs, last, 60),
        "vol_usd_5m": vol5,
        "vol_usd_60m": _sum(w60, "vol_usd"),
        "vol_ratio_5m": (vol5 / base5) if base5 > 0 else None,
        "imbalance_5m": imbalance(w5),
        "imbalance_15m": imbalance(w15),
        "traders_5m": _sum(w5, "traders"),
        "traders_15m": _sum(w15, "traders"),
        "traders_prev15m": _sum(prev15, "traders"),
        "large_15m": _sum(w15, "large"),
        "breakout_30m": (last["c"] > prior_high) if prior_high and last.get("c") else None,
        "dist_prior_high": (last["c"] / prior_high - 1.0) if prior_high and last.get("c") else None,
        "dist_vwap_60m": (last["c"] / vwap - 1.0) if vwap and last.get("c") else None,
        "atr14": atr14,
        "atr_ratio": (atr14 / atr60) if atr14 and atr60 else None,
        "range_1m": rng,
        "close_pos_1m": close_pos,
        "liq_change_15m": liq_change(15),
        "liq_change_60m": liq_change(60),
        "minutes_since_last_trade": (as_of_ts - (lb + TF)) / 60.0,
        "prior60_candles": len(prior60_excl5),
    }
