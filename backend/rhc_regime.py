"""Market regime and no-trade conditions (pure).

Regime uses only trailing data: the percentile of the last hour's market-wide volume (sum of
tracked pools' 5m candle volume) within the trailing window, plus the ETH move from the
reference pool. With too little history the regime is "unknown" and that is reported.
"""
from bisect import bisect_left


def percentile_rank(value, history):
    if not history:
        return None
    s = sorted(history)
    return bisect_left(s, value) / len(s)


def regime(market_vol_5m, eth_closes_5m, as_of_ts, cfg):
    """market_vol_5m / eth_closes_5m: [(bucket, value)] with bucket + 300 <= as_of_ts only.
    Returns dict(label, pct, eth_ret_1h, no_trade: [codes])."""
    mv = [(b, v) for b, v in market_vol_5m if b + 300 <= as_of_ts]
    ec = [(b, v) for b, v in eth_closes_5m if b + 300 <= as_of_ts and v]
    out = {"label": "unknown", "pct": None, "eth_ret_1h": None, "market_vol_1h": None, "no_trade": []}
    if len(mv) >= 12:
        hourly = [sum(v for _, v in mv[i - 11:i + 1]) for i in range(11, len(mv))]
        out["market_vol_1h"] = hourly[-1]
        hist = hourly[:-1][-cfg.RHC_REGIME_LOOKBACK_5M:]
        if len(hist) >= cfg.RHC_REGIME_MIN_HISTORY_5M:
            p = percentile_rank(hourly[-1], hist)
            out["pct"] = p
            out["label"] = "hot" if p >= cfg.RHC_REGIME_HOT_PCT else "cold" if p <= cfg.RHC_REGIME_COLD_PCT else "normal"
    if len(ec) >= 13:
        out["eth_ret_1h"] = ec[-1][1] / ec[-13][1] - 1.0
    if out["label"] == "cold" and cfg.RHC_NO_TRADE_COLD:
        out["no_trade"].append("REGIME_COLD")
    if out["eth_ret_1h"] is not None and out["eth_ret_1h"] <= -cfg.RHC_NO_TRADE_ETH_DROP:
        out["no_trade"].append("ETH_DUMP")
    if out["label"] == "unknown" and cfg.RHC_NO_TRADE_UNKNOWN_REGIME:
        out["no_trade"].append("REGIME_UNKNOWN")
    return out
