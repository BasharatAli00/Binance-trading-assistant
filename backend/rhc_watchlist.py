"""Pure watchlist logic: discovery scoring and state transitions.

States
  candidate -> (screen) -> watch | rejected
  watch     -> re-screened every RHC_RESCREEN_WATCH_MIN (taxes, owners and liquidity change)
  rejected  -> re-screened after a cooldown: short for transient reasons, long for permanent ones
  *         -> expired when the pool shows no activity for RHC_WATCH_EXPIRE_H
"""
import math

from rhc_reasons import is_permanent


def discovery_reasons(stats_1h, surge, created_ts, now_ts, rank, cfg):
    """Pure. stats_1h=(usd, swaps, last_ts); surge=(usd_15m, usd_prior_45m); rank = 0-based by 1h volume."""
    usd, n, _ = stats_1h
    if usd < cfg.RHC_DISCOVER_MIN_VOL_1H or n < cfg.RHC_DISCOVER_MIN_SWAPS_1H:
        return []
    reasons = []
    if created_ts and now_ts - created_ts <= cfg.RHC_DISCOVER_NEW_POOL_H * 3600:
        reasons.append("new_pool")
    u15, prior45 = surge
    pace = prior45 / 3.0
    if u15 >= 1_000 and (pace <= 0 or u15 >= cfg.RHC_DISCOVER_SURGE_X * pace):
        reasons.append("volume_surge")
    if rank < cfg.RHC_DISCOVER_TOP_N:
        reasons.append("top_volume")
    return reasons


def score(stats_1h, reasons):
    usd = max(stats_1h[0], 1.0)
    s = math.log10(usd)
    s += 1.0 if "new_pool" in reasons else 0.0
    s += 1.5 if "volume_surge" in reasons else 0.0
    s += 0.5 if "liquidity_add" in reasons else 0.0
    return round(s, 3)


def after_screen(verdict, reject_codes, now_ts, cfg):
    """Pure: (state, next_screen_ts) after a screening."""
    if verdict == "pass":
        return "watch", now_ts + cfg.RHC_RESCREEN_WATCH_MIN * 60
    if any(is_permanent(c) for c in reject_codes):
        return "rejected", now_ts + cfg.RHC_RESCREEN_PERMANENT_H * 3600
    return "rejected", now_ts + cfg.RHC_RESCREEN_TRANSIENT_MIN * 60


def should_expire(state, last_activity_ts, now_ts, cfg):
    if state == "expired" or not last_activity_ts:
        return False
    return now_ts - last_activity_ts > cfg.RHC_WATCH_EXPIRE_H * 3600


def due(rows, now_ts, limit):
    """Pure: pick entries to screen now, best score first. rows: dicts with state/next_screen_ts/score."""
    ready = [r for r in rows if r["state"] in ("candidate", "watch", "rejected")
             and (r.get("next_screen_ts") or 0) <= now_ts]
    ready.sort(key=lambda r: (r["state"] != "candidate", -(r.get("score") or 0.0)))
    return ready[:limit]
