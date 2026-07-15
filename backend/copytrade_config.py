"""Config & feature flags for Strategy #4 — Smart-Money Copy Trade.

Watches the wallets that qualified in the Top-Gainer finder (pump_top_gainer)
via Helius, and when 2+ of them buy the SAME token within a short window, opens
a simulated position and manages the exit itself. Fully isolated: own wallet,
own tables (all prefixed `copy_`), own loop. Sim-only until LIVE is wired.

Pure configuration, mirroring sniper_config.py.
"""
import os


def _flag(name, default="true"):
    return os.getenv(name, default).lower() in ("1", "true", "yes")


# ---- Master switch -------------------------------------------------------
# Off => the loop/thread is never started and the app is byte-for-byte
# unaffected. Also effectively idle if no Helius key is configured.
COPYTRADE_ENABLED = _flag("COPYTRADE_ENABLED", "true")

# ---- LIVE trading (Part B) — OFF by default. REAL MONEY when enabled. --------
# Master kill switch. While false, NOTHING can trade for real — every fill is
# simulated regardless of a portfolio's mode. This is the single flag that gates
# all real execution.
LIVE_TRADING_ENABLED = _flag("COPYTRADE_LIVE", "false")

# Wallet secret — store ONLY in Azure (env var or Key Vault), NEVER in git/DB.
# Accepts a Phantom base58 export OR a JSON byte array. Loaded lazily and only
# when LIVE_TRADING_ENABLED is true.
SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY", "")
# The public address we EXPECT that key to produce — a safety cross-check so a
# wrong/rotated key can't silently trade from an unexpected wallet.
LIVE_TRADING_WALLET = os.getenv("LIVE_TRADING_WALLET",
                                "Xob9L3jNCgGiNXZWj6USNsoor1QW1rWkCG5zmv7zyt9")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

# DRY-RUN: when live is enabled we STILL don't send by default — we build the
# real Jupiter quote (to measure real slippage) but skip the final send. Real
# money moves ONLY when COPYTRADE_LIVE=true AND COPYTRADE_LIVE_DRYRUN=false.
# Two deliberate switches stand between "deployed" and "spending".
LIVE_DRYRUN = _flag("COPYTRADE_LIVE_DRYRUN", "true")

# Live wallet (real money) — tiny by design for the first live phase.
LIVE_START_USD = float(os.getenv("CT_LIVE_START_USD", "34"))     # nominal baseline for %P&L
LIVE_POSITION_USD = float(os.getenv("CT_LIVE_POSITION_USD", "1"))   # $ per live trade
LIVE_ADD_USD = float(os.getenv("CT_LIVE_ADD_USD", "1"))            # $ per live add
LIVE_MAX_OPEN = int(os.getenv("CT_LIVE_MAX_OPEN", "2"))            # max live positions

# Live 2 wallet
LIVE2_START_USD = float(os.getenv("CT_LIVE2_START_USD", "100"))
LIVE2_POSITION_USD = float(os.getenv("CT_LIVE2_POSITION_USD", "14"))
LIVE2_MAX_OPEN = int(os.getenv("CT_LIVE2_MAX_OPEN", "6"))

# Live safety rails (all enforced before any real order):
LIVE_MAX_TRADE_USD = float(os.getenv("CT_LIVE_MAX_TRADE_USD", "50"))     # hard cap per trade
LIVE_MAX_TRADES_PER_DAY = int(os.getenv("CT_LIVE_MAX_TRADES_DAY", "100"))
LIVE_MIN_SOL_BALANCE = float(os.getenv("CT_LIVE_MIN_SOL", "0.015"))     # SOL-floor auto-pause
LIVE_SLIPPAGE_BPS = int(os.getenv("CT_LIVE_SLIPPAGE_BPS", "300"))       # 3% max slippage on the swap
LIVE_MAX_PRICE_IMPACT_PCT = float(os.getenv("CT_LIVE_MAX_IMPACT", "10"))  # skip if quote impact > this
LIVE_MIN_LIQUIDITY_USD = float(os.getenv("CT_LIVE_MIN_LIQ", "20000"))   # stricter liq floor for live
LIVE_MAX_LIQUIDITY_USD = float(os.getenv("CT_LIVE_MAX_LIQ", "0"))
LIVE_PRIORITY_FEE_LAMPORTS = int(os.getenv("CT_LIVE_PRIORITY_FEE", "200000"))
LIVE_EXIT_PRIORITY_FEE_LAMPORTS = int(os.getenv("CT_LIVE_EXIT_PRIORITY_FEE", "600000"))
LIVE_CONFIRM_TIMEOUT_SEC = int(os.getenv("CT_LIVE_CONFIRM_TIMEOUT", "45"))

# ---- Live-only entry safety ("Bouncer" + "Seatbelt") --------------------
# These gates apply ONLY to live portfolios. The Sim wallet is intentionally
# left on the OLD criteria (liquidity floor + no-chase) so it stays a clean
# control to compare against. Motivation: the live book was profitable EXCEPT
# for rug-pulls that blew straight through the -20% price stop; these refuse the
# risky entry up front instead.
LIVE_SAFETY_ENABLED = _flag("CT_LIVE_SAFETY", "true")

# Bouncer — on-chain rug vectors (verified via SOLANA_RPC_URL before any buy):
#   * mint authority must be revoked (else the dev can print unlimited supply)
#   * freeze authority must be revoked (else your tokens can be frozen = honeypot)
LIVE_REQUIRE_MINT_REVOKED = _flag("CT_LIVE_REQ_MINT_REVOKED", "true")
LIVE_REQUIRE_FREEZE_REVOKED = _flag("CT_LIVE_REQ_FREEZE_REVOKED", "true")
# Top-holder concentration check. OFF by default: for brand-new pump.fun tokens
# the largest "holder" is usually the liquidity pool / bonding curve, so this
# false-positives easily. Enable once you've watched the logs.
LIVE_CHECK_TOP_HOLDER = _flag("CT_LIVE_CHECK_TOP_HOLDER", "false")
LIVE_MAX_TOP_HOLDER_PCT = float(os.getenv("CT_LIVE_MAX_TOP_HOLDER", "40"))
# If the RPC can't verify the token at all, fail SAFE (skip) rather than risk it.
LIVE_SKIP_IF_UNVERIFIED = _flag("CT_LIVE_SKIP_UNVERIFIED", "true")

# Seatbelt — exposure & re-entry limits (local, no network):
#   * never put more than this % of equity into one coin (the -97% rug was 30%)
#   * don't re-buy a coin we already traded in the last N hours (that rug was a
#     re-entry of a coin we'd just exited)
LIVE_MAX_POSITION_PCT = float(os.getenv("CT_LIVE_MAX_POS_PCT", "15"))
LIVE_REENTRY_BLOCK_HOURS = float(os.getenv("CT_LIVE_REENTRY_BLOCK_H", "6"))
# Minimum token/pair age before a live buy — brand-new pairs rug the most.
# Disabled by default (0); set CT_LIVE_MIN_AGE_H to e.g. 4 to require 4h.
LIVE_MIN_TOKEN_AGE_HOURS = float(os.getenv("CT_LIVE_MIN_AGE_H", "0"))

# ---- Ported rug-risk score (from the pump-bot system) — live-only ---------
# A 0-100 weighted score from holder concentration + liquidity drain + socials +
# graduation + age + sell pressure + liq/mcap + mint/freeze authority. A score
# at/above the veto threshold blocks the live entry. Fed from DexScreener + RPC.
# ENABLED = compute + log the score (safe). VETO = actually block on a high score.
# Veto is OFF by default: testing showed the score flags winners and rugs alike on
# pump.fun tokens (pool-inflated concentration), so blocking would kill winners too.
# Turn the veto on only if dry-run data reveals a threshold that truly separates them.
LIVE_RUG_SCORE_ENABLED = _flag("CT_LIVE_RUG_SCORE", "true")
LIVE_RUG_SCORE_VETO = _flag("CT_LIVE_RUG_VETO_ON", "false")
LIVE_RUG_VETO_THRESHOLD = float(os.getenv("CT_LIVE_RUG_VETO", "45"))
# Rug blacklist: skip a coin that CLOSED below this % (rugged) in the last N hours.
LIVE_RUG_BLACKLIST_HOURS = float(os.getenv("CT_LIVE_RUG_BLACKLIST_H", "24"))
LIVE_RUG_BLACKLIST_PCT = float(os.getenv("CT_LIVE_RUG_BLACKLIST_PCT", "-50"))

# Fire Alarm — real-time rug guard on OPEN live positions. A rug drains the pool
# faster than the -20% price stop can react, so we watch the POOL liquidity and
# bail the instant it collapses from its peak (before the normal exit rules run).
# Live-only. It only ever SELLS, so a false trigger just exits early — cheap
# insurance against a -97% wipeout. Raise the drop % if it fires spuriously.
LIVE_LIQ_ALARM_ENABLED = _flag("CT_LIVE_LIQ_ALARM", "true")
LIVE_LIQ_ALARM_DROP_PCT = float(os.getenv("CT_LIVE_LIQ_ALARM_DROP", "40"))   # sell if pool down this % from peak
LIVE_LIQ_ALARM_MIN_USD = float(os.getenv("CT_LIVE_LIQ_ALARM_MIN", "3000"))   # only arm once peak pool exceeded this (ignore dust/noise)

# Jupiter free/keyless tier (same as the sniper uses). No API key required.
JUPITER_QUOTE_URL = os.getenv("JUPITER_QUOTE_URL", "https://api.jup.ag/swap/v2/order")
JUPITER_SWAP_URL = os.getenv("JUPITER_SWAP_URL", "https://api.jup.ag/swap/v2/execute")
JUPITER_PRICE_URL = os.getenv("JUPITER_PRICE_URL", "https://lite-api.jup.ag/price/v3")

# ---- Helius (real-time wallet watching) ---------------------------------
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
# Public URL Helius POSTs events to — our receiver route. Must be reachable
# from the internet (the backend is deployed). e.g. https://<host>/api/copytrade/helius
HELIUS_WEBHOOK_URL = os.getenv("HELIUS_WEBHOOK_URL", "")
# Shared secret we set as the webhook's authHeader and verify on each POST.
HELIUS_WEBHOOK_SECRET = os.getenv("HELIUS_WEBHOOK_SECRET", "")
HELIUS_API_BASE = os.getenv("HELIUS_API_BASE", "https://api.helius.xyz")
HTTP_TIMEOUT = 20

# Pump.fun / PumpSwap programs — we only care about swaps on these.
PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL_MINT = "So11111111111111111111111111111111111111112"

# ---- QuickNode Feed Integration -----------------------------------------
ENABLE_QUICKNODE_FEED = _flag("ENABLE_QUICKNODE_FEED", "false")
QUICKNODE_WEBHOOK_URL = os.getenv("QUICKNODE_WEBHOOK_URL", "")
QUICKNODE_API_KEY = os.getenv("QUICKNODE_API_KEY", "")

# Stage 1: Shadow mode (parse + dedup + log only, discard before signal table)
QUICKNODE_SHADOW_ONLY = _flag("QUICKNODE_SHADOW_ONLY", "true")

# Stage 3: Live trading allowed (QuickNode events can influence Live portfolio)
QUICKNODE_LIVE_ENABLED = _flag("QUICKNODE_LIVE_ENABLED", "false")

SOURCE_SILENT_THRESHOLD_SECONDS = int(os.getenv("SOURCE_SILENT_THRESHOLD_SEC", "600"))
DEDUP_CACHE_TTL_SECONDS = int(os.getenv("DEDUP_CACHE_TTL_SEC", "600"))

# ---- Watched wallet set --------------------------------------------------
# Taken from the qualified leaderboard. Union of both windows, capped.
WATCH_FROM_WINDOWS = ["7d", "24h"]
MAX_WATCHED_WALLETS = int(os.getenv("CT_MAX_WATCHED", "40"))
WALLET_SYNC_MINUTES = int(os.getenv("CT_WALLET_SYNC_MIN", "30"))  # re-sync list + webhook

# Wallet-discovery source:
#   "smart"       -> smart_wallet_finder: top traders of KNOWN-RELIABLE tokens
#                    (follows skilled money into real/community tokens, not rugs)
#   "leaderboard" -> the original PnL leaderboard (pump_top_gainer)
# When "smart", disable the PnL-leaderboard job (PUMP_GAINER_ENABLED=false) to
# stay within the Solana Tracker free-tier call budget.
WALLET_SOURCE = os.getenv("CT_WALLET_SOURCE", "leaderboard")
SMART_MIN_SEEDS = int(os.getenv("CT_SMART_MIN_SEEDS", "2"))       # must rank on >= this many reliable tokens
# 48h keeps the Solana Tracker spend inside the free tier: (21 seeds + 60
# profiles) x ~15 refreshes/month ~= 1,200 calls. Wallet behaviour is stable over
# days, so refreshing faster buys nothing.
SMART_REFRESH_HOURS = float(os.getenv("CT_SMART_REFRESH_H", "48"))
# How many candidates to behaviour-profile (1 API call each, and it blocks the
# loop while it runs). ~10% pass, so 60 profiles ~= 6 quality wallets.
SMART_MAX_PROFILE = int(os.getenv("CT_SMART_MAX_PROFILE", "60"))

# Behaviour filter — the important one. Ranking wallets on PAST PnL surfaced
# traders whose CURRENT activity is $5k micro-cap junk (that's what lost money in
# the dry-run: median traded liquidity was $5.4k, and 96% of their buys were under
# $30k). This keeps only wallets that actually trade real tokens NOW and are still
# active. Costs 1 API call per candidate, so it only runs on the refresh cadence.
SMART_BEHAVIOR_FILTER = _flag("CT_SMART_BEHAVIOR", "true")
SMART_MIN_MEDIAN_MCAP = float(os.getenv("CT_SMART_MIN_MCAP", "500000"))
SMART_MAX_IDLE_DAYS = float(os.getenv("CT_SMART_MAX_IDLE_D", "7"))

# ---- Tiered entry (the edge) --------------------------------------------
# Analysis showed top-gainer wallets rarely buy the SAME coin, so a strict
# "2+ agree" gate almost never fires. Instead: enter small on ONE qualified
# wallet's buy, then ADD a little more each time ANOTHER distinct qualified
# wallet buys the same coin (rewarding agreement).
MIN_WALLETS = int(os.getenv("CT_MIN_WALLETS", "1"))            # wallets needed to ENTER
CONSENSUS_WINDOW_MIN = int(os.getenv("CT_WINDOW_MIN", "10"))   # buy-grouping window (minutes)
SIGNAL_COOLDOWN_MIN = int(os.getenv("CT_SIGNAL_COOLDOWN_MIN", "120"))  # re-entry cooldown per mint
EVENT_RETENTION_HOURS = int(os.getenv("CT_EVENT_RETENTION_H", "24"))   # prune wallet events

# Tier sizing (USD): first wallet buys TIER1; each additional distinct wallet
# on the same held coin adds ADD_USD ("a little more"), up to MAX_WALLET_ADDS.
TIER1_USD = float(os.getenv("CT_TIER1_USD", "25"))
ADD_USD = float(os.getenv("CT_ADD_USD", "35"))
MAX_WALLET_ADDS = int(os.getenv("CT_MAX_ADDS", "2"))

# ---- Entry gates ---------------------------------------------------------
MIN_LIQUIDITY_USD = float(os.getenv("CT_MIN_LIQ", "8000"))
MAX_LIQUIDITY_USD = float(os.getenv("CT_MAX_LIQ", "0"))
# Don't chase: if price already ran past this since the FIRST triggering buy we
# can detect, skip — we missed the entry and would be buying the top.
MAX_PRICE_MOVE_SINCE_SIGNAL_PCT = float(os.getenv("CT_MAX_CHASE_PCT", "40"))

# ---- Simulated wallet + risk --------------------------------------------
INITIAL_BALANCE = float(os.getenv("CT_INITIAL_BALANCE", "1000"))
POSITION_SIZE_USD = float(os.getenv("CT_POSITION_SIZE", "50"))
MAX_OPEN_POSITIONS = int(os.getenv("CT_MAX_OPEN", "8"))
DAILY_MAX_LOSS_PCT = float(os.getenv("CT_DAILY_MAX_LOSS", "20"))   # circuit breaker

# ---- Exits ---------------------------------------------------------------
STOP_LOSS_PCT = float(os.getenv("CT_STOP_LOSS", "-20"))       # hard stop
TAKE_PROFIT_PCT = float(os.getenv("CT_TAKE_PROFIT", "35"))    # scale-out trigger (lowered from 60 for safety)
SCALE_OUT_FRACTION = float(os.getenv("CT_SCALE_OUT_FRAC", "0.5"))  # sell half at TP, run the rest
RUNNER_TRAIL_PCT_LOOSE = float(os.getenv("CT_RUNNER_TRAIL_LOOSE", "15"))   # give-back trail when up < 50%
RUNNER_TRAIL_PCT_MEDIUM = float(os.getenv("CT_RUNNER_TRAIL_MEDIUM", "10")) # give-back trail when up 50% - 100%
RUNNER_TRAIL_PCT_TIGHT = float(os.getenv("CT_RUNNER_TRAIL_TIGHT", "5"))    # give-back trail when up > 100%
TRAIL_START_PCT = float(os.getenv("CT_TRAIL_START", "15"))    # start trailing once up this much (lowered from 25)
TRAIL_DISTANCE_PCT = float(os.getenv("CT_TRAIL_DIST", "10"))  # trail distance before scale-out (lowered from 12)
TIME_EXIT_MINUTES = int(os.getenv("CT_TIME_EXIT_MIN", "180"))
# Mirror the smart money: exit when this fraction of the wallets that triggered
# our entry have SOLD the token. 0.5 = exit once half of them are out.
SMART_EXIT_SELL_FRACTION = float(os.getenv("CT_SMART_EXIT_FRAC", "0.5"))

# ---- Fees / loop ---------------------------------------------------------
FEE_RATE = float(os.getenv("CT_FEE_RATE", "0.01"))   # same friction proxy as the sniper
FAST_POLL_SEC = int(os.getenv("CT_FAST_POLL_SEC", "10"))   # exit + signal processing cadence

# Cooldown (minutes) after an exit before we'll re-enter the same token.
COOLDOWN_MINUTES = {
    "stop_loss": 30, "trailing_stop": 10, "take_profit": 5,
    "time_exit": 10, "smart_money_exit": 15, "manual": 0, "default": 10,
}

# ---- Seeded wallets (Sim + Live) ----------------------------------------
# Two isolated portfolios watching the SAME signals. Sim = paper. Live = real
# money (tiny), only ever active behind LIVE_TRADING_ENABLED. Both are created
# once on startup.
SIM_SEED = {
    "name": "CopyTrade Sim", "mode": "sim",
    "cash_balance": INITIAL_BALANCE, "initial_balance": INITIAL_BALANCE,
    "position_size": POSITION_SIZE_USD, "max_open_positions": MAX_OPEN_POSITIONS,
}
LIVE_SEED = {
    "name": "CopyTrade Live", "mode": "live",
    "cash_balance": LIVE_START_USD, "initial_balance": LIVE_START_USD,
    "position_size": LIVE_POSITION_USD, "max_open_positions": LIVE_MAX_OPEN,
}
LIVE2_SEED = {
    "name": "CopyTrade Live 2", "mode": "live",
    "cash_balance": LIVE2_START_USD, "initial_balance": LIVE2_START_USD,
    "position_size": LIVE2_POSITION_USD, "max_open_positions": LIVE2_MAX_OPEN,
}
SEED_PORTFOLIOS = [SIM_SEED, LIVE_SEED, LIVE2_SEED]


def tier_sizes(pf):
    """(first-buy USD, per-add USD) for a portfolio."""
    # Respect the database/UI setting first
    pos_size = pf.get("position_size")
    if pos_size is not None and float(pos_size) > 0:
        return float(pos_size), float(pos_size)
        
    # Fallback overrides if no UI setting exists
    mode = pf.get("mode", "sim")
    name = pf.get("name", "")
    if mode == "live":
        if "2" in name:
            return 14.0, 14.0
        return 1.0, 1.0
    return TIER1_USD, ADD_USD
