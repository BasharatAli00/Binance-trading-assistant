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

    # Over-extension veto — don't chase a token that already blew off on the hour.
    # Late entries into a parabola are where the worst -90% bags came from.
    if feats.get("price_change_h1", 0) > cfg.MAX_PRICE_CHANGE_H1_ENTRY:
        return False, "over-extended"

    return True, "ok"


def exit_decision(position: dict, price: float, portfolio: dict):
    """Decide what to do with an open position at the current mark.

    Returns None (hold) or a dict {"action", "reason", "fraction"}:
      - action="partial" : sell `fraction` of the remaining qty, keep position open
      - action="sell"    : close the whole remaining position

    Design (fixes the inverted-payoff problem found in the trade history):
      * Bank a tranche at `scale_out_pct` to lock the high-probability base gain.
      * AFTER scaling, switch the remaining "runner" to a WIDE give-back trail so
        the occasional 5-50x can actually be captured (the old tight 2-5% trail
        amputated every winner at ~+17%).
      * BEFORE scaling, keep the original tightening trail so trades that pop to
        15-30% and fade still book a gain.
      * A no-progress cull kills the dead-zone trades that just bleed fees/time.
    """
    entry = position["entry_price"]
    if not entry or not price:
        return None
    peak = max(position.get("peak_price") or entry, price)
    hold_min = position.get("_hold_minutes", 0)
    scaled = bool(position.get("scaled_out"))

    cur_ret = (price - entry) / entry * 100
    peak_ret = (peak - entry) / entry * 100

    sl = portfolio.get("stop_loss_pct", -15.0)
    tp = portfolio.get("take_profit_pct", 1000.0)
    tex = portfolio.get("time_exit_minutes", 120)
    so_pct = portfolio.get("scale_out_pct", 25.0)
    so_frac = portfolio.get("scale_out_fraction", 0.5)
    runner_trail = portfolio.get("runner_trail_pct", 35.0)
    np_min = portfolio.get("no_progress_minutes", 25)
    np_pct = portfolio.get("no_progress_pct", 8.0)
    ts_start = portfolio.get("trail_start_pct", 15.0)
    ts_dist = portfolio.get("trail_start_distance", 5.0)
    te_pct = portfolio.get("trail_end_pct", 30.0)
    te_dist = portfolio.get("trail_end_distance", 2.0)

    # 1. Stop loss (full)
    if cur_ret <= sl:
        return {"action": "sell", "reason": "stop_loss", "fraction": 1.0}

    # 2. Hard take-profit cap (full) — usually unreachable; a safety ceiling.
    if cur_ret >= tp:
        return {"action": "sell", "reason": "take_profit", "fraction": 1.0}

    # 3. Scale-out: bank the first tranche once, lock the base gain.
    if not scaled and 0 < so_frac < 1 and cur_ret >= so_pct:
        return {"action": "partial", "reason": "scale_out", "fraction": so_frac}

    # 4. Trailing stop — wide for an established runner, tight before scaling.
    if scaled:
        if cur_ret <= peak_ret - runner_trail:
            return {"action": "sell", "reason": "trailing_stop", "fraction": 1.0}
    else:
        if peak_ret >= ts_start:
            if peak_ret <= te_pct and te_pct > ts_start:
                frac = (peak_ret - ts_start) / (te_pct - ts_start)
                trail_dist = ts_dist - frac * (ts_dist - te_dist)
            else:
                trail_dist = te_dist
            if cur_ret <= peak_ret - trail_dist:
                return {"action": "sell", "reason": "trailing_stop", "fraction": 1.0}

    # 5. No-progress cull (only pre-scale; a scaled runner has earned room).
    if not scaled and hold_min >= np_min and peak_ret < np_pct:
        return {"action": "sell", "reason": "no_progress", "fraction": 1.0}

    # 6. Time exit
    if hold_min >= tex:
        return {"action": "sell", "reason": "time_exit", "fraction": 1.0}

    return None
