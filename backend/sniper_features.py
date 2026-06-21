"""Feature engineering for the sniper.

Computes ~35 features per token from the last 20 minutes of its own snapshots
(plus the DexScreener-provided multi-window aggregates on the latest snapshot).
Returns None if fewer than 3 snapshots exist yet.
"""
import time
import statistics
from datetime import datetime, timedelta

from sqlalchemy import asc
from database import SessionLocal
from models import SniperSnapshot


def _row_dict(r):
    return {c.name: getattr(r, c.name) for c in r.__table__.columns}


def compute_features(token_address: str) -> dict | None:
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=20)
        rows = db.query(SniperSnapshot).filter(
            SniperSnapshot.token_address == token_address,
            SniperSnapshot.snapshot_time >= cutoff,
        ).order_by(asc(SniperSnapshot.snapshot_time)).all()
    finally:
        db.close()

    if len(rows) < 3:
        return None

    snaps = [_row_dict(r) for r in rows]
    latest = snaps[-1]
    prev = snaps[-2] if len(snaps) >= 2 else latest

    f = {}

    # --- 5m momentum (straight from DexScreener) ---
    f["price_change_m5"] = latest.get("price_change_m5") or 0
    f["volume_m5"] = latest.get("volume_m5") or 0
    f["buys_m5"] = latest.get("buys_m5") or 0
    f["sells_m5"] = latest.get("sells_m5") or 0

    prices = [s["price_usd"] for s in snaps if s.get("price_usd")]
    vols = [s["volume_m5"] for s in snaps if s.get("volume_m5")]
    buys_arr = [s["buys_m5"] for s in snaps if s.get("buys_m5") is not None]
    sell_arr = [s["sells_m5"] for s in snaps if s.get("sells_m5") is not None]

    if len(prices) >= 2:
        p_now = prices[-1]
        p_3m = prices[-3] if len(prices) >= 3 else prices[0]
        p_10m = prices[-10] if len(prices) >= 10 else prices[0]
        p_15m = prices[-15] if len(prices) >= 15 else prices[0]
        f["price_change_3m"] = (p_now - p_3m) / p_3m * 100 if p_3m else 0
        f["price_change_10m"] = (p_now - p_10m) / p_10m * 100 if p_10m else 0
        f["price_change_15m"] = (p_now - p_15m) / p_15m * 100 if p_15m else 0

        returns = [(prices[i] - prices[i-1]) / prices[i-1] * 100
                   for i in range(1, len(prices)) if prices[i-1]]
        f["price_volatility_15m"] = statistics.stdev(returns) if len(returns) >= 2 else 0

        n = len(prices)
        mean_x = (n - 1) / 2
        mean_y = sum(prices) / n
        num = sum((i - mean_x) * (prices[i] - mean_y) for i in range(n))
        den = sum((i - mean_x) ** 2 for i in range(n))
        f["price_trend_15m"] = (num / den) if den else 0

        session_high = max(prices)
        f["price_vs_session_high"] = (p_now / session_high - 1) * 100 if session_high else 0

        green = 0
        for i in range(len(prices) - 1, 0, -1):
            if prices[i] > prices[i-1]:
                green += 1
            else:
                break
        f["consecutive_green_candles"] = green
    else:
        for k in ["price_change_3m", "price_change_10m", "price_change_15m",
                  "price_volatility_15m", "price_trend_15m",
                  "price_vs_session_high", "consecutive_green_candles"]:
            f[k] = 0

    f["volume_sum_15m"] = sum(vols[-15:]) if vols else 0
    f["buys_sum_15m"] = sum(buys_arr[-15:]) if buys_arr else 0
    f["sells_sum_15m"] = sum(sell_arr[-15:]) if sell_arr else 0
    total_bs = f["buys_sum_15m"] + f["sells_sum_15m"]
    f["buy_sell_ratio_15m"] = f["buys_sum_15m"] / total_bs if total_bs else 0.5

    if len(vols) >= 6:
        recent_vol = sum(vols[-3:]) / 3
        earlier_vol = sum(vols[-6:-3]) / 3
        va = recent_vol / earlier_vol if earlier_vol else 1
        f["vol_acceleration_15m"] = min(va / 5, 1.0)
    else:
        f["vol_acceleration_15m"] = 0

    liq = latest.get("liquidity_usd") or 1
    f["vol_to_liquidity_15m"] = f["volume_sum_15m"] / liq
    f["avg_trade_size_15m"] = (f["volume_sum_15m"] / total_bs) if total_bs else 0

    if len(vols) >= 2:
        v_n = len(vols)
        mean_vx = (v_n - 1) / 2
        mean_vy = sum(vols) / v_n
        vnum = sum((i - mean_vx) * (vols[i] - mean_vy) for i in range(v_n))
        vden = sum((i - mean_vx) ** 2 for i in range(v_n))
        f["volume_trend_15m"] = (vnum / vden) if vden else 0
    else:
        f["volume_trend_15m"] = 0

    # --- 1h context ---
    f["price_change_h1"] = latest.get("price_change_h1") or 0
    f["volume_h1"] = latest.get("volume_h1") or 0
    f["buys_h1"] = latest.get("buys_h1") or 0
    f["sells_h1"] = latest.get("sells_h1") or 0
    total_h1 = f["buys_h1"] + f["sells_h1"]
    f["buyer_seller_ratio_h1"] = f["buys_h1"] / total_h1 if total_h1 else 0.5

    # --- Broader context ---
    f["price_change_h6"] = latest.get("price_change_h6") or 0
    f["price_change_h24"] = latest.get("price_change_h24") or 0
    f["volume_h6"] = latest.get("volume_h6") or 0
    f["volume_h24"] = latest.get("volume_h24") or 0

    f["momentum_accel"] = f["price_change_3m"] - f.get("price_change_15m", 0)

    buys_10 = sum(buys_arr[-10:]) if len(buys_arr) >= 10 else sum(buys_arr)
    sells_10 = sum(sell_arr[-10:]) if len(sell_arr) >= 10 else sum(sell_arr)
    f["buy_pressure_10m"] = buys_10 / (sells_10 + 1)

    # --- Token profile ---
    created = latest.get("pair_created_at")
    if isinstance(created, datetime):
        age_h = (datetime.utcnow() - created).total_seconds() / 3600
    else:
        age_h = 0
    f["token_age_hours"] = age_h
    f["liquidity_usd"] = latest.get("liquidity_usd") or 0
    f["market_cap"] = latest.get("market_cap") or 0
    f["liq_to_mcap_ratio"] = f["liquidity_usd"] / f["market_cap"] if f["market_cap"] else 0
    f["pool_count"] = latest.get("pool_count") or 1
    f["has_socials"] = 1 if latest.get("has_socials") else 0
    f["boost_count"] = latest.get("boost_count") or 0
    f["fdv"] = latest.get("fdv") or 0
    f["fdv_mcap_ratio"] = f["fdv"] / f["market_cap"] if f["market_cap"] else 1

    # Liquidity drain (rug signal)
    liq_10m_ago = snaps[-10]["liquidity_quote"] if len(snaps) >= 10 else None
    liq_now_q = latest.get("liquidity_quote") or 0
    if liq_10m_ago and liq_10m_ago > 0:
        f["liq_quote_change_10m"] = (liq_now_q - liq_10m_ago) / liq_10m_ago * 100
    else:
        f["liq_quote_change_10m"] = 0

    f["prev_buys_m5"] = prev.get("buys_m5") or 0
    f["prev_sells_m5"] = prev.get("sells_m5") or 0
    f["is_graduated"] = 0 if latest.get("dex_id") == "pumpswap" else 1

    total_24h = (latest.get("buys_h24") or 0) + (latest.get("sells_h24") or 0)
    f["buyer_seller_ratio_h24"] = (latest.get("buys_h24") or 0) / total_24h if total_24h else 0.5

    # carry useful display fields
    f["price_usd"] = latest.get("price_usd") or 0
    f["symbol"] = None  # filled by caller from watchlist if available
    f["dex_id"] = latest.get("dex_id") or ""
    f["pair_address"] = latest.get("pair_address") or ""
    return f
