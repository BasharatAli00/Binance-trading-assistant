"""Pure decision logic for the pivot-bracket strategy (strategy #2).

Idea: in a non-downtrend, buy when price has a favorable reward:risk to the
daily pivot levels — target the next resistance (R1), stop at the next support
(S1). No network, no DB (mirrors strategy.py's purity) so the same rules can be
unit-tested and reused.

A "pivots" snapshot is a plain dict: {pp, r1, s1, trend}.
"""

PIVOT_PARAMS = {
    "min_rr": 1.5,             # require reward:risk >= this to enter
    "fixed_trade_usdt": 1000,  # fixed notional per trade (caps concentration)
    "cooldown_passes": 5,      # loop passes to wait after an exit (avoid same-period chop)
    # Laddered exit:
    "watch_passes": 5,         # ~5 loop passes (~5 min) to confirm a break at each level
    "spike_pct": 0.02,         # >= level + 2% -> sell instantly (too far, too fast)
    "drop_pct": 0.005,         # while riding, a 0.5% pullback from the peak -> sell
}


def reward_risk(price, r1, s1):
    """Reward (room up to R1) divided by risk (room down to S1). 0 if invalid."""
    risk = price - s1
    if risk <= 0:
        return 0.0
    return (r1 - price) / risk


def should_enter(price, pp, r1, s1, trend, p=PIVOT_PARAMS):
    """Return (enter: bool, reason: str) for opening a long.

    Gates: not a downtrend, price genuinely between S1 and R1 (room both ways),
    and reward:risk to the bracket is at least `min_rr`.
    """
    if None in (price, pp, r1, s1) or trend is None:
        return False, "no pivot data"
    if trend == "Downtrend":
        return False, "skip: downtrend"
    if not (s1 < price < r1):
        return False, "skip: price outside S1..R1"
    rr = reward_risk(price, r1, s1)
    if rr < p["min_rr"]:
        return False, f"skip: R:R {rr:.2f} < {p['min_rr']}"
    return True, f"R:R {rr:.2f}, trend {trend}"


def ladder_decision(price, rung, peak, watch_count, r1, r2, r3, s1, p=PIVOT_PARAMS):
    """Laddered exit state machine. Pure — no DB/network.

    Returns (action, rung, peak, watch_count, reason) where action is "SELL" or
    "HOLD" and the other values are the UPDATED ladder state to persist.

    Rungs: 0 = target R1, 1 = R1 broken (riding to R2), 2 = R2 broken (riding to R3).
    At each resistance we wait `watch_passes` to confirm a break; a +2% overshoot
    sells instantly; once riding, a 0.5% pullback from the peak sells; R3 is final.
    """
    spike = 1 + p["spike_pct"]
    drop = 1 - p["drop_pct"]
    wp = p["watch_passes"]

    # Hard stop always wins.
    if price <= s1:
        return "SELL", rung, peak, 0, f"Stop-loss S1 ${s1:.0f}"

    peak = max(peak or price, price)

    if rung == 0:
        # Target R1 — confirm a break vs a rejection.
        if price >= r1 * spike:
            return "SELL", rung, peak, 0, "R1 +2% spike"
        if price >= r1:
            watch_count += 1
            if watch_count >= wp:
                return "HOLD", 1, peak, 0, "R1 broken -> target R2"
            return "HOLD", 0, peak, watch_count, f"At R1, confirming ({watch_count}/{wp})"
        if watch_count > 0:
            return "SELL", rung, peak, 0, "Rejected at R1"
        return "HOLD", 0, peak, 0, "Holding toward R1"

    if rung == 1:
        # Riding R1 -> R2 with a 0.5% trailing exit; confirm a break of R2.
        if price <= peak * drop:
            return "SELL", rung, peak, 0, "0.5% pullback (pre-R2)"
        if price >= r2 * spike:
            return "SELL", rung, peak, 0, "R2 +2% spike"
        if price >= r2:
            watch_count += 1
            if watch_count >= wp:
                return "HOLD", 2, peak, 0, "R2 broken -> target R3"
            return "HOLD", 1, peak, watch_count, f"At R2, confirming ({watch_count}/{wp})"
        return "HOLD", 1, peak, 0, "Riding to R2"

    # rung >= 2: riding R2 -> R3; R3 is the final target (sell on touch).
    if price >= r3:
        return "SELL", rung, peak, 0, "R3 final target"
    if price <= peak * drop:
        return "SELL", rung, peak, 0, "0.5% pullback (pre-R3)"
    return "HOLD", 2, peak, 0, "Riding to R3"
