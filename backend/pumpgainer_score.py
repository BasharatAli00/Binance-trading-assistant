"""Local eligibility gate + composite ranking score.

The Solana Tracker leaderboard already enforces most hard floors server-side
(min trades / tokens / invested / win-rate / days, single-token concentration,
arbitrage exclusion, strict PnL). This module applies the checks the provider
can't express as a single query param, then computes our own composite score:

  * net-positive realized PnL (CORRECTION #4) — a "top gainer" must be in profit.
  * creator / bot / exchange / hacker exclusion (CORRECTION #4 + wash defense),
    from the provider's `identity` flags.
  * composite score (§3.2) with winsorized + log-scaled normalization
    (CORRECTION #5) so one whale can't flatten the field.
"""
import math

import pumpgainer_config as cfg


def evaluate(records):
    """records (from pumpgainer_client) -> (all_rows, eligible_rows).

    all_rows: every fetched wallet with passed_eligibility + exclusion_reason.
    eligible_rows: survivors, each with `score` and `rank` set, capped.
    """
    elig = cfg.ELIGIBILITY
    all_rows = []
    eligible = []

    for rec in records:
        reason = _first_failing_filter(rec, elig)
        row = dict(rec)
        row["passed_eligibility"] = reason is None
        row["exclusion_reason"] = reason
        all_rows.append(row)
        if reason is None:
            eligible.append(row)

    _apply_scores(eligible)
    eligible.sort(key=lambda r: r["score"], reverse=True)
    for i, row in enumerate(eligible, start=1):
        row["rank"] = i

    return all_rows, eligible[: cfg.LEADERBOARD_MAX_SIZE]


def _first_failing_filter(rec, elig):
    # Net-positive is the main floor the leaderboard query can't express.
    if (rec.get("realized_pnl") or 0.0) <= 0.0:
        return "not_net_positive"
    if elig["exclude_token_creators"] and rec.get("is_developer"):
        return "token_creator"
    if elig["exclude_bots"] and (rec.get("is_bot") or rec.get("is_exchange")
                                 or rec.get("is_hacker")):
        return "bot_or_exchange"
    # Activity ceiling — catches HFT/MM bots the provider left unlabeled.
    if elig["max_round_trips"] and rec.get("trades", 0) > elig["max_round_trips"]:
        return "likely_bot_activity"
    if elig["max_distinct_tokens"] and rec.get("tokens_traded", 0) > elig["max_distinct_tokens"]:
        return "likely_bot_activity"
    # Defensive re-check of the server-side floors (in case a param is ignored).
    if rec.get("trades", 0) < elig["min_round_trips"]:
        return "min_round_trips"
    if rec.get("tokens_traded", 0) < elig["min_distinct_tokens"]:
        return "min_distinct_tokens"
    if (rec.get("win_rate") or 0.0) < elig["min_win_rate"]:
        return "min_win_rate"
    return None


def _apply_scores(eligible):
    if not eligible:
        return
    w = cfg.SCORING
    pnl_norm = _winsorized_minmax([r["realized_pnl"] for r in eligible], log=True)
    roi_norm = _winsorized_minmax([(r.get("roi_pct") or 0.0) for r in eligible], log=True)
    for r, pn, rn in zip(eligible, pnl_norm, roi_norm):
        r["score"] = (pn * w["weight_pnl"]
                      + rn * w["weight_roi"]
                      + (r.get("win_rate") or 0.0) * w["weight_win_rate"])


def _winsorized_minmax(values, log=False, lo_q=0.05, hi_q=0.95):
    """Robust [0,1] scaling: clamp to the 5th/95th percentiles (kills outlier
    dominance), optionally log-compress, then min-max. Degenerate inputs
    (one value, or all-equal) map to a neutral 0.5 instead of dividing by zero."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]

    v = list(values)
    if log:
        # eligible PnL/ROI are > 0; guard anything non-positive that slips in.
        v = [math.log(x) if x > 0 else 0.0 for x in v]

    lo = _percentile(v, lo_q)
    hi = _percentile(v, hi_q)
    if hi <= lo:
        return [0.5] * n
    out = []
    for x in v:
        c = min(max(x, lo), hi)
        out.append((c - lo) / (hi - lo))
    return out


def _percentile(values, q):
    """Linear-interpolated percentile (q in [0,1]); no numpy dependency."""
    s = sorted(values)
    if not s:
        return 0.0
    if len(s) == 1:
        return s[0]
    idx = q * (len(s) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return s[lo]
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac
