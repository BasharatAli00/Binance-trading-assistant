"""Constants & feature flags for Strategy #3 — the Intelligent Sniper.

Pure configuration, no logic. Per-portfolio knobs (position size, stops, etc.)
live in the SniperPortfolio DB row and are editable from the UI; the values here
are global defaults and the things that don't change per wallet.
"""
import os

# ---- Master switch -------------------------------------------------------
# When false, the sniper thread is never started — the rest of the app
# (Strategy #1 + #2) is byte-for-byte unaffected. Ship dark, flip on later.
SNIPER_ENABLED = os.getenv("SNIPER_ENABLED", "true").lower() in ("1", "true", "yes")

# Use GeckoTerminal (CoinGecko's free, keyless on-chain DEX API) as a SECONDARY
# discovery source alongside DexScreener. Free, no key, 30 req/min. Falls back
# to DexScreener-only automatically if it errors or is rate-limited.
USE_GECKOTERMINAL = os.getenv("USE_GECKOTERMINAL", "true").lower() in ("1", "true", "yes")

# Live trading is stubbed (sniper_live.py). Even a portfolio with mode='live'
# is SIMULATED until this is true AND sniper_live is fully implemented.
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() in ("1", "true", "yes")

# ---- Timing --------------------------------------------------------------
POLL_INTERVAL_SEC       = 60      # full discovery/entry tick cadence
FAST_POLL_SEC           = 10      # exit-only poll on OPEN positions (cuts stop slippage)
WATCHLIST_REFRESH_MIN   = 5       # rediscover tokens every 5 min

# ---- ML brain auto-retrain ----------------------------------------------
# Retrain the LightGBM model on a schedule from the growing snapshot history.
# Runs in a background thread so it never blocks trading; falls back silently if
# there isn't enough data yet. Manual retrain (UI button / POST /train) still works.
AUTO_RETRAIN_ENABLED    = os.getenv("SNIPER_AUTO_RETRAIN", "true").lower() in ("1", "true", "yes")
RETRAIN_INTERVAL_HOURS  = 24
MACRO_REFRESH_SEC       = 900     # refresh SOL price / F&G every 15 min
WATCHLIST_MAX_TOKENS    = 50
SNAPSHOT_RETENTION_DAYS = 45

# ---- Discovery filters ---------------------------------------------------
MIN_LIQUIDITY      = 10_000       # USD
MIN_VOLUME_H1      = 1_000        # USD
MIN_TOKEN_AGE_MIN  = 30
MAX_TOKEN_AGE_DAYS = 7
MIN_PRICE_MOVE_M5  = 2.0          # % absolute
MIN_PRICE_MOVE_H1  = 5.0          # %

# ---- Entry gates (never bypassed) ---------------------------------------
MIN_PRICE_CHANGE_M5     = 3.0     # % momentum gate
MIN_BUY_PRESSURE        = 0.5
RUG_RISK_VETO_THRESHOLD = 45      # default; per-portfolio override exists
MAX_PRICE_CHANGE_H1_ENTRY = 120.0 # % — don't chase blow-off tops (late = bag-holder)

# ---- Open-position safety -----------------------------------------------
# Hard liquidity floor: if a held token's pool collapses below this, force-exit
# immediately on the fast pass rather than waiting for the % stop (which fills
# catastrophically late in a rug). Entry requires MIN_LIQUIDITY (10k), so a drop
# to a few k means the pool is being pulled.
LIQ_HARD_FLOOR          = 3_000   # USD

# ---- Cooldown minutes by exit reason ------------------------------------
COOLDOWN_MINUTES = {
    "stop_loss":     10,
    "time_exit":      5,
    "trailing_stop":  3,
    "take_profit":    2,
    "no_progress":    5,
    "liq_drain":     30,   # rugged once — stay away
    "circuit_breaker": 0,
    "manual":         0,
    "default":        5,
}

# ---- Simulated execution -------------------------------------------------
FEE_RATE = 0.01        # 1% round-trip-ish friction proxy for meme-coin swaps
                       # (Jupiter fee + spread + slippage). Conservative on purpose.

# ---- Free API endpoints (all keyless) -----------------------------------
# Jupiter split its API in 2025: api.jup.ag now needs a key, the free tier
# lives on lite-api.jup.ag. Price API is v3 (shape: {mint: {usdPrice: ...}}).
DEXSCREENER_BASE   = "https://api.dexscreener.com"
GECKOTERMINAL_BASE = "https://api.geckoterminal.com/api/v2"
JUPITER_PRICE_URL  = "https://lite-api.jup.ag/price/v3"
JUPITER_QUOTE_URL  = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_SWAP_URL   = "https://lite-api.jup.ag/swap/v1/swap"
FEAR_GREED_URL     = "https://api.alternative.me/fng/?limit=1"
SOLANA_RPC_URL     = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
SOLANA_RPC_FALLBACK = "https://solana-rpc.publicnode.com"

WSOL_MINT = "So11111111111111111111111111111111111111112"
HTTP_TIMEOUT = 15

# ---- Seed wallets (created once) ----------------------------------------
# Both simulate for now. The 'live' one carries mode='live' so the UI shows the
# Live/Sim toggle and so it routes through sniper_live once that's enabled.
SEED_PORTFOLIOS = [
    {"name": "Live", "mode": "live", "cash_balance": 80.0,   "initial_balance": 80.0,
     "position_size": 10.0, "max_open_positions": 10},
    {"name": "Sim",  "mode": "sim",  "cash_balance": 1000.0, "initial_balance": 1000.0,
     "position_size": 50.0, "max_open_positions": 5},
]
