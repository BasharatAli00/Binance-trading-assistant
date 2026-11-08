"""Performance metrics with confidence intervals and a hard sample-size gate.

A strategy is never described as profitable below the gate (RHC_MIN_TRADES_FOR_STATS trades,
RHC_MIN_TOKENS_FOR_STATS distinct tokens, RHC_MIN_DAYS_FOR_STATS days). Above it, "positive
expectancy" is only stated when the 95% bootstrap CI lower bound of expectancy is above zero.
Bootstraps use a fixed seed so the same trades always give the same numbers.
"""
import math
import random
from collections import defaultdict

Z95 = 1.959964


def wilson(k, n, z=Z95):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _pf(pnls):
    gains = sum(x for x in pnls if x > 0)
    losses = -sum(x for x in pnls if x < 0)
    if losses == 0:
        return float("inf") if gains > 0 else None
    return gains / losses


def bootstrap_ci(values, stat, n_boot=1000, seed=4663, alpha=0.05):
    if len(values) < 2:
        return (None, None)
    rng = random.Random(seed)
    n = len(values)
    stats = []
    for _ in range(n_boot):
        s = stat([values[rng.randrange(n)] for _ in range(n)])
        if s is not None and not (isinstance(s, float) and math.isinf(s)):
            stats.append(s)
    if not stats:
        return (None, None)
    stats.sort()
    lo = stats[int(alpha / 2 * len(stats))]
    hi = stats[min(len(stats) - 1, int((1 - alpha / 2) * len(stats)))]
    return (lo, hi)


def max_drawdown(pnls, equity0):
    eq, peak, mdd = equity0, equity0, 0.0
    for x in pnls:
        eq += x
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak if peak > 0 else 0.0)
    return mdd


def compute(trades, equity0, cfg, start_ts=None, end_ts=None):
    """trades: [{pnl_usd, cost_usd, risk_usd, strategy, regime, token, entry_ts, exit_ts, exit_reason}],
    ordered by exit time. Returns a metrics dict including the sample gate."""
    trades = sorted(trades, key=lambda t: t["exit_ts"])
    n = len(trades)
    pnls = [t["pnl_usd"] for t in trades]
    rs = [t["pnl_usd"] / t["risk_usd"] for t in trades if t.get("risk_usd")]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    tokens = {t["token"] for t in trades}
    span_s = ((end_ts or (trades[-1]["exit_ts"] if trades else 0)) -
              (start_ts or (trades[0]["entry_ts"] if trades else 0)))
    days = max(span_s / 86400.0, 0.0)
    m = {
        "trades": n, "tokens": len(tokens), "days": round(days, 2),
        "net_pnl_usd": round(sum(pnls), 4),
        "win_rate": (len(wins) / n) if n else None, "win_rate_ci95": wilson(len(wins), n),
        "avg_win_usd": (sum(wins) / len(wins)) if wins else None,
        "avg_loss_usd": (sum(losses) / len(losses)) if losses else None,
        "payoff_ratio": ((sum(wins) / len(wins)) / abs(sum(losses) / len(losses))) if wins and losses else None,
        "profit_factor": _pf(pnls), "profit_factor_ci95": bootstrap_ci(pnls, _pf),
        "expectancy_usd": (sum(pnls) / n) if n else None,
        "expectancy_usd_ci95": bootstrap_ci(pnls, lambda v: sum(v) / len(v)),
        "expectancy_r": (sum(rs) / len(rs)) if rs else None,
        "expectancy_r_ci95": bootstrap_ci(rs, lambda v: sum(v) / len(v)),
        "max_drawdown_pct": round(100.0 * max_drawdown(pnls, equity0), 3),
        "trades_per_day": (n / days) if days > 0 else None,
        "avg_hold_min": (sum(t["exit_ts"] - t["entry_ts"] for t in trades) / n / 60.0) if n else None,
        "exit_reasons": dict(sorted(_count(trades, "exit_reason").items())),
    }
    m["gate"] = sample_gate(n, len(tokens), days, cfg)
    lo = (m["expectancy_usd_ci95"] or (None, None))[0]
    if not m["gate"]["sufficient"]:
        m["verdict"] = "insufficient sample - no conclusion"
    elif lo is not None and lo > 0:
        m["verdict"] = "positive expectancy (95% CI lower bound > 0)"
    else:
        m["verdict"] = "edge not demonstrated"
    return m


def _count(trades, key):
    c = defaultdict(int)
    for t in trades:
        c[t.get(key) or "unknown"] += 1
    return c


def sample_gate(n, tokens, days, cfg):
    reasons = []
    if n < cfg.RHC_MIN_TRADES_FOR_STATS:
        reasons.append(f"trades {n} < {cfg.RHC_MIN_TRADES_FOR_STATS}")
    if tokens < cfg.RHC_MIN_TOKENS_FOR_STATS:
        reasons.append(f"tokens {tokens} < {cfg.RHC_MIN_TOKENS_FOR_STATS}")
    if days < cfg.RHC_MIN_DAYS_FOR_STATS:
        reasons.append(f"days {days:.1f} < {cfg.RHC_MIN_DAYS_FOR_STATS}")
    return {"sufficient": not reasons, "missing": reasons}


def breakdown(trades, key, equity0, cfg):
    groups = defaultdict(list)
    for t in trades:
        groups[t.get(key) or "unknown"].append(t)
    return {g: compute(ts, equity0, cfg) for g, ts in sorted(groups.items())}
