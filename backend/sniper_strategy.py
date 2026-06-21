"""Pure decision logic for the sniper (no DB / network here).

Entry: a stack of hard gates (momentum, buy pressure, reversal/bearish vetoes).
The rug-risk veto and conviction floor are applied in the loop (they need network
/ macro), but the price-action gates live here so they're unit-testable.

Exit: stop-loss / trailing-stop / take-profit / time-exit, evaluated against the
live mark. Mirrors the reference's exit ladder.
"""
import sniper_config as cfg


def passes_entry_gates(feats: dict, portfolio: dict):
    """Return (ok: bool, reason: str). Hard price-action gates only."""
    if not feats:
        return False, "no features"

    if feats.get("liquidity_usd", 0) < cfg.MIN_LIQUIDITY:
        return False, "liquidity too low"
    if (feats.get("buys_m5", 0) + feats.get("sells_m5", 0)) == 0:
        return False, "no recent trades"

    min_bp = portfolio.get("min_buy_pressure", cfg.MIN_BUY_PRESSURE)
    if feats.get("buy_pressure_10m", 0) < min_bp:
        return False, "weak buy pressure"

    # Reversal veto — actively selling for two windows
    if (feats.get("sells_m5", 0) > feats.get("buys_m5", 0) and
            feats.get("prev_sells_m5", 0) > feats.get("prev_buys_m5", 0)):
        return False, "reversing"

    # Momentum gate (never bypassed)
    pc_m5 = feats.get("price_change_m5", 0)
    if pc_m5 < cfg.MIN_PRICE_CHANGE_M5:
        return False, "no 5m momentum"

    # Bearish vetoes
    pc_15m = feats.get("price_change_15m", 0)
    if pc_m5 < -3 and pc_15m < -5:
        return False, "bearish"
    if pc_m5 < -5:
        return False, "dumping"
    if feats.get("liq_quote_change_10m", 0) < -10:
        return False, "liquidity draining"

    return True, "ok"


def exit_decision(position: dict, price: float, portfolio: dict):
    """Return an exit-reason string or None. `position` is a SniperPosition dict."""
    entry = position["entry_price"]
    if not entry or not price:
        return None
    peak = max(position.get("peak_price") or entry, price)
    hold_min = position.get("_hold_minutes", 0)

    cur_ret = (price - entry) / entry * 100
    peak_ret = (peak - entry) / entry * 100

    sl = portfolio.get("stop_loss_pct", -20.0)
    tp = portfolio.get("take_profit_pct", 1000.0)
    tex = portfolio.get("time_exit_minutes", 120)
    ts_start = portfolio.get("trail_start_pct", 15.0)
    ts_dist = portfolio.get("trail_start_distance", 5.0)
    te_pct = portfolio.get("trail_end_pct", 30.0)
    te_dist = portfolio.get("trail_end_distance", 2.0)

    # 1. Stop loss
    if cur_ret <= sl:
        return "stop_loss"

    # 2. Trailing stop (tightens linearly from ts_dist to te_dist)
    if peak_ret >= ts_start:
        if peak_ret <= te_pct and te_pct > ts_start:
            frac = (peak_ret - ts_start) / (te_pct - ts_start)
            trail_dist = ts_dist - frac * (ts_dist - te_dist)
        else:
            trail_dist = te_dist
        if cur_ret <= peak_ret - trail_dist:
            return "trailing_stop"

    # 3. Take profit
    if cur_ret >= tp:
        return "take_profit"

    # 4. Time exit
    if hold_min >= tex:
        return "time_exit"

    return None
