"""Pure entry/exit rules for Strategy #4. No DB, no I/O — easy to unit test.

Entry gate: the token must be safe/liquid and not already run away from the
smart-money entry (don't chase the top). Exit: our own stop / take-profit /
trailing / time limit, PLUS a mirror-sell when the wallets that triggered our
entry start selling.
"""
import copytrade_config as cfg


def passes_entry_gates(mark, price_move_since_signal_pct=None):
    """mark = {'price', 'liquidity_usd'}. Returns (ok, reason)."""
    if not mark or not mark.get("price"):
        return False, "no_price"
    if (mark.get("liquidity_usd") or 0) < cfg.MIN_LIQUIDITY_USD:
        return False, "low_liquidity"
    # Don't chase: if it already ran past the cap since the first smart buy, skip.
    if (price_move_since_signal_pct is not None
            and price_move_since_signal_pct > cfg.MAX_PRICE_MOVE_SINCE_SIGNAL_PCT):
        return False, "already_pumped"
    return True, "ok"


def exit_decision(pos, price, smart_money_exiting=False):
    """Decide what to do with an open position at `price`.

    Returns None (hold) or {'action': 'full'|'partial', 'fraction'?, 'reason'}.
    Order matters: safety first (stop), then smart-money mirror, then time,
    then profit-taking / trailing.
    """
    entry = pos["entry_price"]
    if not entry or price <= 0:
        return None
    gain_pct = (price / entry - 1.0) * 100.0
    peak = max(pos.get("peak_price") or entry, price)
    peak_gain = (peak / entry - 1.0) * 100.0
    hold_min = pos.get("_hold_minutes", 0.0)
    scaled = pos.get("scaled_out", False)

    # 1. Hard stop-loss — always first.
    if gain_pct <= cfg.STOP_LOSS_PCT:
        return {"action": "full", "reason": "stop_loss"}

    # 2. Smart money is leaving — follow them out.
    if smart_money_exiting:
        return {"action": "full", "reason": "smart_money_exit"}

    # 3. Time limit.
    if cfg.TIME_EXIT_MINUTES and hold_min >= cfg.TIME_EXIT_MINUTES:
        return {"action": "full", "reason": "time_exit"}

    # 4. First profit target — bank half, let the rest run.
    if not scaled and gain_pct >= cfg.TAKE_PROFIT_PCT:
        return {"action": "partial", "fraction": cfg.SCALE_OUT_FRACTION,
                "reason": "take_profit"}

    # 5. Runner trail (after we've scaled out) — wide give-back from peak.
    if scaled and (peak_gain - gain_pct) >= cfg.RUNNER_TRAIL_PCT:
        return {"action": "full", "reason": "trailing_stop"}

    # 6. Pre-scale trail — once up enough, protect against a sharp pullback.
    if (not scaled and gain_pct >= cfg.TRAIL_START_PCT
            and (peak_gain - gain_pct) >= cfg.TRAIL_DISTANCE_PCT):
        return {"action": "full", "reason": "trailing_stop"}

    return None
