"""Solana Tracker Data API client for the Top-Gainer finder.

Single responsibility: call GET /v2/pnl/leaderboard/top for a given window and
return normalized wallet records. Most eligibility floors are pushed here as
query params (server-side filtering); the creator/bot exclusion and the
net-positive check are done locally afterwards in pumpgainer_score.

Docs: https://docs.solanatracker.io/data-api/pnl-v2/leaderboard/
Auth: `x-api-key` header. Base: https://api.solanatracker.io
"""
import requests

import pumpgainer_config as cfg

_LEADERBOARD_PATH = "/v2/pnl/leaderboard/top"


def _params_for(days):
    """Map our ELIGIBILITY config onto the leaderboard's native query params."""
    e = cfg.ELIGIBILITY
    # minDays can't exceed the window: the endpoint defaults minDays=3, so a
    # 1-day (24h) window with minDays=3 is unsatisfiable and returns 0 rows.
    min_days = min(e["min_days_active"], days)
    params = {
        "sort": "realized",
        "direction": "desc",
        "limit": cfg.FETCH_LIMIT,
        "days": days,
        "pnlMode": cfg.PNL_MODE,
        "excludeArbitrage": "true" if cfg.EXCLUDE_ARBITRAGE else "false",
        "minTrades": e["min_round_trips"],
        "minClosedTokens": e["min_distinct_tokens"],
        "minInvested": e["min_total_volume"],
        "minDays": min_days,
        # provider expects percentages (0..100); our config stores 0..1 fractions
        "minWinRate": e["min_win_rate"] * 100.0,
        "maxSingleTokenPct": e["max_token_pnl_share"] * 100.0,
    }
    return params


def fetch_leaderboard(days):
    """Fetch and normalize the top-trader leaderboard for a `days` window."""
    if not cfg.SOLANATRACKER_API_KEY:
        raise RuntimeError("SOLANATRACKER_API_KEY is not set")

    resp = requests.get(
        cfg.SOLANATRACKER_BASE + _LEADERBOARD_PATH,
        params=_params_for(days),
        headers={"x-api-key": cfg.SOLANATRACKER_API_KEY},
        timeout=cfg.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()

    # The endpoint returns a list under `traders` (or a bare list, defensively).
    rows = payload.get("traders") if isinstance(payload, dict) else payload
    rows = rows or []
    out = []
    for row in rows:
        rec = _normalize(row)
        if rec is not None:
            out.append(rec)
    return out


def _normalize(row):
    """One leaderboard entry -> flat record used by scoring/storage.

    Field paths follow the documented response shape. Kept isolated so any
    provider-side shape change is a one-spot fix.
    """
    wallet = row.get("wallet")
    if not wallet:
        return None

    period = row.get("period") or {}
    pdays = period.get("days") or {}
    counts = row.get("counts") or {}
    tokens = row.get("tokens") or {}
    identity = row.get("identity") or {}

    realized = _num(period.get("realized"))
    roi = _num(period.get("roi"))
    # winRate may be top-level or under period.days; normalize to a 0..1 fraction.
    win_rate = _num(row.get("winRate"))
    if win_rate is None:
        win_rate = _num(pdays.get("winRate"))
    if win_rate is not None and win_rate > 1.0:
        win_rate = win_rate / 100.0

    return {
        "wallet_address": wallet,
        "realized_pnl": realized,
        "roi_pct": roi,
        "win_rate": win_rate if win_rate is not None else 0.0,
        "volume": _num(period.get("volume")) or 0.0,
        "trades": int(counts.get("trades") or 0),
        "tokens_traded": int(counts.get("tokensTraded") or 0),
        "tokens_closed": int(tokens.get("closed") or 0),
        # single-token concentration is enforced server-side via maxSingleTokenPct
        # --- identity flags used by local exclusion (creator/bot/etc.) ---
        "is_developer": bool((identity.get("developer") or {}).get("token")),
        "is_bot": bool((identity.get("bot") or {}).get("name")),
        "is_exchange": bool((identity.get("exchange") or {}).get("name")),
        "is_hacker": bool((identity.get("hacker") or {}).get("label")),
        "identity_name": identity.get("name"),
    }


def _num(v):
    """Coerce a possibly-null numeric field to float or None."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
