"""Config & feature flags for the Top-Gainer Wallet Finder.

Data source: Solana Tracker Data API (https://docs.solanatracker.io) — its
`/v2/pnl/leaderboard/top` endpoint is purpose-built for exactly this job: it
ranks Solana trading wallets by recent realized PnL over 1/7/30/90-day windows,
with most of our eligibility criteria available as native server-side filters.

Pure configuration (no logic), mirroring sniper_config.py.

SCOPE NOTE: this leaderboard ranks top *Solana memecoin* traders globally, not
pump.fun-exclusively (the endpoint has no single-program filter). We keep the
`pump_*` naming for continuity; treat the output as "best Solana meme traders."
"""
import os


def _flag(name, default="true"):
    return os.getenv(name, default).lower() in ("1", "true", "yes")


# ---- Master switch -------------------------------------------------------
# Off => the scheduler job is never registered and startup is byte-for-byte
# unaffected. Also auto-disabled at runtime if no API key is present, so a
# missing key degrades gracefully instead of crashing the app.
PUMP_GAINER_ENABLED = _flag("PUMP_GAINER_ENABLED", "true")

# ---- Solana Tracker Data API --------------------------------------------
SOLANATRACKER_BASE = os.getenv("SOLANATRACKER_BASE", "https://data.solanatracker.io")
SOLANATRACKER_API_KEY = os.getenv("SOLANATRACKER_API_KEY", "")   # x-api-key; never commit
HTTP_TIMEOUT = 30

# ---- Schedule ------------------------------------------------------------
INTERVAL_MINUTES = int(os.getenv("PUMP_GAINER_INTERVAL_MIN", "30"))

# ---- Windows -------------------------------------------------------------
# Our label -> the provider's `days` param. 24h == the 1-day window.
WINDOWS = {
    "24h": 1,
    "7d": 7,
}

# ---- Eligibility ---------------------------------------------------------
# Most of these are pushed to the provider as query params (server-side); the
# creator/bot exclusion and the net-positive check are applied locally after
# fetch (see pumpgainer_score). Kept as one dict so a reviewer tunes them here.
ELIGIBILITY = {
    "min_round_trips":        int(os.getenv("PG_MIN_ROUND_TRIPS", "5")),     # -> minTrades
    "min_distinct_tokens":    int(os.getenv("PG_MIN_DISTINCT_TOKENS", "3")), # -> minClosedTokens
    "min_total_volume":       float(os.getenv("PG_MIN_VOLUME", "5")),        # -> minInvested
    "min_win_rate":           float(os.getenv("PG_MIN_WIN_RATE", "0.35")),   # 0..1 -> minWinRate (as %)
    "min_days_active":        int(os.getenv("PG_MIN_DAYS", "3")),            # -> minDays (clamped to window)
    "max_token_pnl_share":    float(os.getenv("PG_MAX_TOKEN_SHARE", "0.60")),# 0..1 -> maxSingleTokenPct (as %)
    "exclude_token_creators": _flag("PG_EXCLUDE_CREATORS", "true"),          # local: identity.developer
    "exclude_bots":           _flag("PG_EXCLUDE_BOTS", "true"),              # local: identity.bot/exchange/hacker
    # Anti-HFT/market-maker guard (local). The provider's identity flags are
    # often null, so obvious bots (100k+ trades / thousands of tokens a day)
    # slip through. A human "top gainer" to watch never trades at that rate.
    # 0 disables the cap.
    "max_round_trips":        int(os.getenv("PG_MAX_ROUND_TRIPS", "3000")),
    "max_distinct_tokens":    int(os.getenv("PG_MAX_DISTINCT_TOKENS", "300")),
}

# Provider PnL accounting mode: strict | adjusted | raw. `strict` discards
# unverifiable PnL (fees/transfers/airdrops), the closest match to our
# "net, auditable" intent — this is what CORRECTION #3 was manually doing.
PNL_MODE = os.getenv("PG_PNL_MODE", "strict")
EXCLUDE_ARBITRAGE = _flag("PG_EXCLUDE_ARBITRAGE", "true")

# Over-fetch factor: we pull more rows than the leaderboard cap so that after
# local creator/bot/net-positive filtering we still have a full board.
FETCH_LIMIT = int(os.getenv("PG_FETCH_LIMIT", "500"))

# ---- Scoring weights (starting point — tune once real data is observed) ---
# Applied to the provider's realized-PnL / ROI / win-rate to produce our own
# composite ranking (rather than trusting a single sort key).
SCORING = {
    "weight_pnl":      float(os.getenv("PG_W_PNL", "0.5")),
    "weight_roi":      float(os.getenv("PG_W_ROI", "0.3")),
    "weight_win_rate": float(os.getenv("PG_W_WIN", "0.2")),
}

# ---- Output --------------------------------------------------------------
LEADERBOARD_MAX_SIZE = int(os.getenv("PG_LEADERBOARD_MAX", "200"))
