"""Wallet intelligence from our own indexed trades (no third-party labels).

* Positions: per (wallet, pool), average-cost accounting over the wallet's observed trades.
  A position closes when the wallet has sold >= 95% of what it bought. Wallets whose first
  observed trade is a sell (they bought before we started watching) are ignored for that pool.
* Score (as of t): only positions CLOSED before t count -> no leakage from the future.
  score = (wins + 1) / (n + 2) (Beta(1,1) shrinkage); "smart" needs n >= RHC_SMART_MIN_CLOSED,
  score >= RHC_SMART_MIN_SCORE and a positive median return.
* Smart flow (as of t): buys by smart-as-of-t wallets in the window before t.
* evaluate(): does smart flow predict forward returns? Time-ordered split, reported with sample
  sizes; below RHC_SMART_EVAL_MIN_SAMPLES it says "insufficient sample" and draws no conclusion.
"""
from collections import defaultdict
from dataclasses import dataclass
from statistics import median


@dataclass
class ClosedPosition:
    wallet: str
    pool_pk: int
    open_ts: int
    close_ts: int
    cost_usd: float
    proceeds_usd: float

    @property
    def ret(self):
        return self.proceeds_usd / self.cost_usd - 1.0 if self.cost_usd > 0 else 0.0


def positions(trades, close_frac=0.95):
    """Pure: trades = [{wallet, pool_pk, ts, side, base_amt, usd}] -> list[ClosedPosition]."""
    out = []
    book = {}
    for t in sorted(trades, key=lambda x: (x["ts"], x.get("log_index", 0))):
        key = (t["wallet"], t["pool_pk"])
        p = book.get(key)
        if t["side"] == "buy":
            if p is None:
                p = book[key] = {"open_ts": t["ts"], "bought": 0.0, "sold": 0.0, "cost": 0.0, "proceeds": 0.0}
            p["bought"] += t["base_amt"] or 0.0
            p["cost"] += t["usd"] or 0.0
        else:
            if p is None:
                continue                                       # entry not observed: ignore
            p["sold"] += t["base_amt"] or 0.0
            p["proceeds"] += t["usd"] or 0.0
            if p["bought"] > 0 and p["sold"] >= close_frac * p["bought"]:
                out.append(ClosedPosition(t["wallet"], t["pool_pk"], p["open_ts"], t["ts"], p["cost"], p["proceeds"]))
                del book[key]
    return out


def scores(closed, as_of_ts, cfg):
    """Pure: {wallet: dict(n, wins, score, median_ret, smart)} from positions closed before as_of."""
    by = defaultdict(list)
    for p in closed:
        if p.close_ts < as_of_ts:
            by[p.wallet].append(p.ret)
    out = {}
    for w, rets in by.items():
        n, wins = len(rets), sum(1 for r in rets if r > 0)
        s = (wins + 1) / (n + 2)
        med = median(rets)
        out[w] = {"n": n, "wins": wins, "score": s, "median_ret": med,
                  "smart": n >= cfg.RHC_SMART_MIN_CLOSED and s >= cfg.RHC_SMART_MIN_SCORE and med > 0}
    return out


def smart_flow(trades, wallet_scores, pool_pk, as_of_ts, window_s=900):
    """Pure: (smart_buy_usd, smart_buyers) for one pool in [as_of - window, as_of)."""
    usd, who = 0.0, set()
    for t in trades:
        if (t["pool_pk"] == pool_pk and t["side"] == "buy" and as_of_ts - window_s <= t["ts"] < as_of_ts
                and wallet_scores.get(t["wallet"], {}).get("smart")):
            usd += t["usd"] or 0.0
            who.add(t["wallet"])
    return usd, len(who)


def evaluate(samples, cfg):
    """samples: [(ts, smart_buy_usd, forward_return)] time-ordered. Compares forward returns when
    smart flow is present vs absent, in the later (out-of-sample) half only."""
    samples = sorted(samples)
    n = len(samples)
    res = {"samples": n, "min_required": cfg.RHC_SMART_EVAL_MIN_SAMPLES, "conclusion": "insufficient sample"}
    if n < cfg.RHC_SMART_EVAL_MIN_SAMPLES:
        return res
    test = samples[n // 2:]
    with_flow = [r for _, s, r in test if s > 0]
    without = [r for _, s, r in test if s <= 0]
    res.update(test_samples=len(test), with_flow=len(with_flow), without_flow=len(without))
    if len(with_flow) < 30 or len(without) < 30:
        res["conclusion"] = "insufficient sample (too few cases in one group)"
        return res
    mw, mo = sum(with_flow) / len(with_flow), sum(without) / len(without)
    res.update(mean_fwd_ret_with=mw, mean_fwd_ret_without=mo, lift=mw - mo,
               conclusion="positive lift (not yet significance-tested)" if mw > mo else "no lift")
    return res
