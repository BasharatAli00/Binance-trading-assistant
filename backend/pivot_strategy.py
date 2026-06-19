"""Pure decision logic for the pivot-bracket strategy (strategy #2).

Idea: in a non-downtrend, buy when price has a favorable reward:risk to the
daily pivot levels — target the next resistance (R1), stop at the next support
(S1). No network, no DB (mirrors strategy.py's purity) so the same rules can be
unit-tested and reused.

A "pivots" snapshot is a plain dict: {pp, r1, s1, trend}.
"""

PIVOT_PARAMS = {
    "min_rr": 1.5,            # require reward:risk >= this to enter
    "risk_per_trade": 0.015,  # size so a stop-out (price -> S1) loses ~1.5% of equity
    "cooldown_passes": 5,     # loop passes to wait after a stop-out (avoid same-day chop)
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


def position_size(equity, price, s1, p=PIVOT_PARAMS):
    """Quantity such that a drop to S1 loses ~risk_per_trade of equity.

    Returns the base-asset quantity (0 if the stop is invalid).
    """
    risk_per_unit = price - s1
    if risk_per_unit <= 0:
        return 0.0
    risk_budget = equity * p["risk_per_trade"]
    return risk_budget / risk_per_unit
