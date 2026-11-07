"""Configuration for the Robinhood Chain discovery & paper-trading system (RHC).

Every threshold lives here and is overridable via environment variables. The
whole system is OFF unless RHC_ENABLED=true AND RHC_DATABASE_URL is set.
RHC never writes to the production DATABASE_URL.

See docs/robinhood-chain/SETUP.md and backend/.env.example for documentation.
"""
import os


def _flag(name, default="false"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _float(name, default):
    try:
        return float(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _list(name, default):
    raw = os.getenv(name, "")
    items = [x.strip().lower() for x in raw.split(",") if x.strip()]
    return items or [x.lower() for x in default]


# ── Master switches ───────────────────────────────────────────────────────────
RHC_ENABLED = _flag("RHC_ENABLED", "false")
RHC_INDEXER_ENABLED = _flag("RHC_INDEXER_ENABLED", "true")
RHC_SOURCES_ENABLED = _flag("RHC_SOURCES_ENABLED", "true")
# Live execution is hard-disabled in code for this project. The env var is
# intentionally NOT read; enabling live trading requires a separate approved change.
RHC_LIVE_ENABLED = False
RHC_MODE = "paper"

# Dedicated database. No fallback to DATABASE_URL by design.
RHC_DATABASE_URL = os.getenv("RHC_DATABASE_URL", "").strip()
RHC_DB_POOL_SIZE = _int("RHC_DB_POOL_SIZE", 3)
# Single-writer lease (a row in rhc_lease, database time). Expires if the owner dies.
RHC_LEASE_TTL_S = _int("RHC_LEASE_TTL_S", 120)
RHC_LEASE_RENEW_S = _int("RHC_LEASE_RENEW_S", 20)

# ── Chain / RPC ───────────────────────────────────────────────────────────────
CHAIN_ID = 4663
_default_rpc = os.getenv("ROBINHOOD_RPC_URL", "https://rpc.mainnet.chain.robinhood.com")
RHC_RPC_URLS = _list("RHC_RPC_URLS", [_default_rpc])
RHC_RPC_TIMEOUT_S = _float("RHC_RPC_TIMEOUT_S", 20.0)
RHC_RPC_MAX_RPS = _float("RHC_RPC_MAX_RPS", 8.0)
RHC_RPC_MAX_RETRIES = _int("RHC_RPC_MAX_RETRIES", 4)
RHC_RPC_BATCH_SIZE = _int("RHC_RPC_BATCH_SIZE", 40)              # node returns 429 for 80-call batches
RHC_RPC_MAX_ITEMS_PER_S = _float("RHC_RPC_MAX_ITEMS_PER_S", 20.0)  # calls/s counted inside batches
# Measured limits of the public node (2026-11-07):
#   * topic-only eth_getLogs may span at most 30,000 blocks
#   * address-filtered eth_getLogs may span at most 10,000,000 blocks
#   * at most 10,000 logs per response (handled by adaptive splitting)
RHC_GETLOGS_TOPIC_SPAN = _int("RHC_GETLOGS_TOPIC_SPAN", 29_000)
RHC_GETLOGS_ADDRESS_SPAN = _int("RHC_GETLOGS_ADDRESS_SPAN", 9_900_000)

# ── Indexer ───────────────────────────────────────────────────────────────────
RHC_CONFIRMATIONS = _int("RHC_CONFIRMATIONS", 20)            # ~2 s at 0.1 s blocks
RHC_POLL_INTERVAL_S = _float("RHC_POLL_INTERVAL_S", 2.0)
RHC_LIVE_CHUNK_BLOCKS = _int("RHC_LIVE_CHUNK_BLOCKS", 600)
RHC_CATCHUP_CHUNK_BLOCKS = _int("RHC_CATCHUP_CHUNK_BLOCKS", 3_000)
RHC_START_LOOKBACK_BLOCKS = _int("RHC_START_LOOKBACK_BLOCKS", 6_000)    # ~10 min on first start
RHC_MAX_CATCHUP_BLOCKS = _int("RHC_MAX_CATCHUP_BLOCKS", 830_000)        # ~1 day; beyond -> record gap
RHC_EXACT_TS_MAX_BLOCKS = _int("RHC_EXACT_TS_MAX_BLOCKS", 300)          # above -> sampled timestamps
RHC_TS_SAMPLE_STEP = _int("RHC_TS_SAMPLE_STEP", 50)
RHC_CANDLE_GRACE_S = _int("RHC_CANDLE_GRACE_S", 5)
RHC_RESOLVE_TRADERS = _flag("RHC_RESOLVE_TRADERS", "true")
RHC_LARGE_TRADE_USD = _float("RHC_LARGE_TRADE_USD", 1_000.0)
# Liquidity events (tracked pools): removals are always stored (rug signal); adds only if
# priced and >= RHC_LIQ_ADD_MIN_USD. Hook-driven pools can emit ~200 small adds/min.
RHC_LIQ_STORE_ALL_ADDS = _flag("RHC_LIQ_STORE_ALL_ADDS", "false")
RHC_LIQ_ADD_MIN_USD = _float("RHC_LIQ_ADD_MIN_USD", 1_000.0)
RHC_MAX_TRADE_USD_SANITY = _float("RHC_MAX_TRADE_USD_SANITY", 20_000_000.0)

# ── Tracking (which pools get candles persisted) ──────────────────────────────
RHC_MAX_TRACKED_POOLS = _int("RHC_MAX_TRACKED_POOLS", 100)
RHC_TRACK_MIN_VOL_USD_1H = _float("RHC_TRACK_MIN_VOL_USD_1H", 5_000.0)
RHC_TRACK_MIN_SWAPS_1H = _int("RHC_TRACK_MIN_SWAPS_1H", 20)
RHC_TRACK_REVIEW_S = _int("RHC_TRACK_REVIEW_S", 60)
RHC_UNTRACK_IDLE_MIN = _int("RHC_UNTRACK_IDLE_MIN", 120)
RHC_RING_CANDLES = _int("RHC_RING_CANDLES", 60)          # closed 1m candles kept in memory per pool
RHC_RING_MIN_VOL_USD_1H = _float("RHC_RING_MIN_VOL_USD_1H", 500.0)

# ── Addresses (verified on-chain 2026-11-07) ──────────────────────────────────
NATIVE_ETH = "0x0000000000000000000000000000000000000000"
WETH = os.getenv("RHC_WETH", "0x0bd7d308f8e1639fab988df18a8011f41eacad73").lower()
USDG = os.getenv("RHC_USDG", "0x5fc5360d0400a0fd4f2af552add042d716f1d168").lower()
RHC_STABLE_QUOTES = _list("RHC_STABLE_QUOTES", [USDG])
RHC_ETH_QUOTES = _list("RHC_ETH_QUOTES", [NATIVE_ETH, WETH])
RHC_V4_POOL_MANAGERS = _list("RHC_V4_POOL_MANAGERS", ["0x8366a39cc670b4001a1121b8f6a443a643e40951"])
# v4 PositionManager(s): poolKeys(bytes25) resolves pool id -> key in one eth_call
# (verified: 38/40 active pools resolved on 2026-11-07; results are re-hashed and checked).
RHC_V4_POSITION_MANAGERS = _list("RHC_V4_POSITION_MANAGERS", ["0x58daec3116aae6d93017baaea7749052e8a04fa7"])
# Fallback for ids unknown to the PositionManager: single-id Initialize log scans (10M-block windows).
RHC_V4_SCAN_MAX_IDS = _int("RHC_V4_SCAN_MAX_IDS", 10)          # per resolve() call
RHC_V4_SCAN_MAX_WINDOWS = _int("RHC_V4_SCAN_MAX_WINDOWS", 12)   # 12 x 9.9M blocks covers all history
RHC_UNRESOLVABLE_RETRY_S = _int("RHC_UNRESOLVABLE_RETRY_S", 6 * 3600)
# Factories whose pools are trusted to emit genuine events (others are recorded
# but marked unsupported until reviewed). Identified via DexScreener labels.
RHC_V2_FACTORIES = _list("RHC_V2_FACTORIES", [
    "0x8bceaa40b9acdfaedf85adf4ff01f5ad6517937f",  # Uniswap v2
    "0x0d1ebb179cdbca88d74c923c4255cb2b17474afd",  # Flap
    "0x02a84c1b3bbd7401a5f7fa98a384ebc70bb5749e",  # PancakeSwap v2
])
RHC_V3_FACTORIES = _list("RHC_V3_FACTORIES", [
    "0x1f7d7550b1b028f7571e69a784071f0205fd2efa",  # Uniswap v3
    "0x221a6239e40709792b0d4bdc140fa36158cd41c7",  # Goo Exchange
])
# USD reference for ETH: Uniswap v3 WETH/USDG 0.01% (deepest pool at probe time).
RHC_ETH_USD_REF_POOL = os.getenv("RHC_ETH_USD_REF_POOL", "0x52e65b17fb6e5ba00ed806f37afcd2daa50271ca").lower()
RHC_STABLE_USD = _float("RHC_STABLE_USD", 1.0)   # USDG assumed at peg; cross-checked via sources

# ── Round-trip simulation (honeypot / tax detection) ──────────────────────────
RHC_SIM_GAS_LIMIT = _int("RHC_SIM_GAS_LIMIT", 30_000_000)
# v2 swap fee per factory, in bps. Unknown factories use the conservative default.
RHC_V2_FEE_BPS = {
    "0x8bceaa40b9acdfaedf85adf4ff01f5ad6517937f": _int("RHC_V2_FEE_BPS_UNISWAP", 30),
    "0x02a84c1b3bbd7401a5f7fa98a384ebc70bb5749e": _int("RHC_V2_FEE_BPS_PANCAKE", 25),
}
RHC_V2_FEE_BPS_DEFAULT = _int("RHC_V2_FEE_BPS_DEFAULT", 100)

# ── Discovery & screening (Phase 2) ───────────────────────────────────────────
RHC_SCREENER_ENABLED = _flag("RHC_SCREENER_ENABLED", "true")
RHC_SCREEN_CYCLE_S = _int("RHC_SCREEN_CYCLE_S", 30)
RHC_SCREEN_PER_CYCLE = _int("RHC_SCREEN_PER_CYCLE", 3)          # screenings per cycle (RPC budget)
RHC_SCREEN_RPC_MAX_RPS = _float("RHC_SCREEN_RPC_MAX_RPS", 3.0)
RHC_SCREEN_RPC_MAX_ITEMS_PER_S = _float("RHC_SCREEN_RPC_MAX_ITEMS_PER_S", 8.0)
RHC_SCREEN_TRADE_USD = _float("RHC_SCREEN_TRADE_USD", 25.0)      # intended trade size for simulation
RHC_SCREEN_PROBE_USD = _float("RHC_SCREEN_PROBE_USD", 1.0)       # tiny probe to measure price impact
RHC_DISCOVER_MIN_VOL_1H = _float("RHC_DISCOVER_MIN_VOL_1H", 2_000.0)
RHC_DISCOVER_MIN_SWAPS_1H = _int("RHC_DISCOVER_MIN_SWAPS_1H", 10)
RHC_DISCOVER_NEW_POOL_H = _float("RHC_DISCOVER_NEW_POOL_H", 6.0)
RHC_DISCOVER_SURGE_X = _float("RHC_DISCOVER_SURGE_X", 3.0)       # last-15m volume vs prior-45m pace
RHC_DISCOVER_TOP_N = _int("RHC_DISCOVER_TOP_N", 30)
RHC_WATCH_MAX = _int("RHC_WATCH_MAX", 60)                        # watch-state pools are kept tracked
RHC_RESCREEN_WATCH_MIN = _int("RHC_RESCREEN_WATCH_MIN", 30)      # taxes/owners can change: re-check
RHC_RESCREEN_TRANSIENT_MIN = _int("RHC_RESCREEN_TRANSIENT_MIN", 20)
RHC_RESCREEN_PERMANENT_H = _int("RHC_RESCREEN_PERMANENT_H", 24)
RHC_WATCH_EXPIRE_H = _float("RHC_WATCH_EXPIRE_H", 6.0)           # no activity -> expired
RHC_RETAIN_SCREEN_DAYS = _int("RHC_RETAIN_SCREEN_DAYS", 14)
# Hard limits (reject above/below)
RHC_MIN_POOL_AGE_MIN = _float("RHC_MIN_POOL_AGE_MIN", 15.0)
RHC_MIN_LIQ_USD = _float("RHC_MIN_LIQ_USD", 25_000.0)
RHC_MIN_TRADES_1H = _int("RHC_MIN_TRADES_1H", 30)
RHC_MIN_TRADERS_1H = _int("RHC_MIN_TRADERS_1H", 15)
RHC_MAX_BUY_TAX = _float("RHC_MAX_BUY_TAX", 0.05)
RHC_MAX_SELL_TAX = _float("RHC_MAX_SELL_TAX", 0.05)
RHC_MAX_ROUNDTRIP_COST = _float("RHC_MAX_ROUNDTRIP_COST", 0.04)
RHC_MAX_IMPACT = _float("RHC_MAX_IMPACT", 0.02)
RHC_MAX_TOP1_PCT = _float("RHC_MAX_TOP1_PCT", 20.0)
RHC_MAX_TOP10_PCT = _float("RHC_MAX_TOP10_PCT", 50.0)
RHC_MAX_INSIDER_PCT = _float("RHC_MAX_INSIDER_PCT", 30.0)
RHC_HOLDER_MAX_LOGS = _int("RHC_HOLDER_MAX_LOGS", 60_000)
RHC_HOLDER_LOOKBACK_BLOCKS = _int("RHC_HOLDER_LOOKBACK_BLOCKS", 25_000_000)   # ~30 days if creation unknown
RHC_FLOW_WINDOW_BLOCKS = _int("RHC_FLOW_WINDOW_BLOCKS", 36_000)               # ~1 hour
RHC_FLOW_MAX_RESOLVE = _int("RHC_FLOW_MAX_RESOLVE", 150)
RHC_FLOW_MAX_NONCES = _int("RHC_FLOW_MAX_NONCES", 60)          # wallet-age checks for the biggest traders
RHC_MIN_HOLDERS = _int("RHC_MIN_HOLDERS", 50)
RHC_LP_HISTORY_BLOCKS = _int("RHC_LP_HISTORY_BLOCKS", 72_000)  # ~2 hours of liquidity add/remove history
RHC_RUG_REMOVED_FRAC = _float("RHC_RUG_REMOVED_FRAC", 0.9)
RHC_LP_REMOVAL_WARN_FRAC = _float("RHC_LP_REMOVAL_WARN_FRAC", 0.3)
RHC_FRESH_NONCE = _int("RHC_FRESH_NONCE", 5)
RHC_WASH_TOP3_SHARE = _float("RHC_WASH_TOP3_SHARE", 0.6)
RHC_WASH_ROUNDTRIP_SHARE = _float("RHC_WASH_ROUNDTRIP_SHARE", 0.5)
RHC_FRESH_VOLUME_WARN = _float("RHC_FRESH_VOLUME_WARN", 0.6)
RHC_BUNDLED_BLOCKS_WARN = _int("RHC_BUNDLED_BLOCKS_WARN", 3)
RHC_LP_MIN_BURNED_PCT = _float("RHC_LP_MIN_BURNED_PCT", 90.0)
RHC_TOKEN_CHECK_TTL_S = _int("RHC_TOKEN_CHECK_TTL_S", 1_800)    # cache for contract/holder checks
# Severity overrides, e.g. RHC_SEVERITY_OVERRIDES="WASH_SUSPECT=warn,LP_NOT_BURNED=reject"
RHC_SEVERITY_OVERRIDES = {
    kv.split("=")[0].strip().upper(): kv.split("=")[1].strip().lower()
    for kv in os.getenv("RHC_SEVERITY_OVERRIDES", "").split(",") if "=" in kv
}
# Registry trimming: pools that never traded (or are unsupported) and were never tracked.
RHC_PRUNE_DEAD_POOLS_DAYS = _int("RHC_PRUNE_DEAD_POOLS_DAYS", 3)

# ── Intelligence, signals & decisions (Phase 3) ───────────────────────────────
# All strategy thresholds below are UNVALIDATED starting points, not claims of an edge.
RHC_DECISIONS_ENABLED = _flag("RHC_DECISIONS_ENABLED", "true")
RHC_DECISION_CYCLE_S = _int("RHC_DECISION_CYCLE_S", 30)
RHC_FEATURE_LOOKBACK_MIN = _int("RHC_FEATURE_LOOKBACK_MIN", 120)
RHC_MIN_COVERAGE_60M = _float("RHC_MIN_COVERAGE_60M", 0.5)    # >= 30 of the last 60 minutes traded
RHC_STOP_ATR_MULT = _float("RHC_STOP_ATR_MULT", 3.0)
RHC_STOP_MIN_PCT = _float("RHC_STOP_MIN_PCT", 0.04)
RHC_STOP_MAX_PCT = _float("RHC_STOP_MAX_PCT", 0.12)
RHC_TARGET_R = [float(x) for x in os.getenv("RHC_TARGET_R", "1.5,3").split(",") if x.strip()]
RHC_TIME_STOP_MIN = _int("RHC_TIME_STOP_MIN", 240)
RHC_MAX_CHASE = _float("RHC_MAX_CHASE", 0.03)
RHC_CONFIRM_MAX_DIP = _float("RHC_CONFIRM_MAX_DIP", 0.01)
RHC_CONFIRM_MIN_IMBALANCE = _float("RHC_CONFIRM_MIN_IMBALANCE", 0.5)
RHC_CONFIRM_TIMEOUT_MIN = _int("RHC_CONFIRM_TIMEOUT_MIN", 3)
RHC_SIGNAL_COOLDOWN_MIN = _int("RHC_SIGNAL_COOLDOWN_MIN", 60)
RHC_STRAT_BREAKOUT_ENABLED = _flag("RHC_STRAT_BREAKOUT_ENABLED", "true")
RHC_BRK_VOL_RATIO = _float("RHC_BRK_VOL_RATIO", 3.0)
RHC_BRK_IMBALANCE = _float("RHC_BRK_IMBALANCE", 0.6)
RHC_BRK_MIN_TRADERS = _int("RHC_BRK_MIN_TRADERS", 8)
RHC_STRAT_MOMENTUM_ENABLED = _flag("RHC_STRAT_MOMENTUM_ENABLED", "true")
RHC_MOM_RET_15M = _float("RHC_MOM_RET_15M", 0.05)
RHC_MOM_RET_60M = _float("RHC_MOM_RET_60M", 0.10)
RHC_MOM_TRADER_GROWTH = _float("RHC_MOM_TRADER_GROWTH", 1.3)
RHC_MOM_IMBALANCE = _float("RHC_MOM_IMBALANCE", 0.55)
RHC_MOM_MAX_VWAP_DIST = _float("RHC_MOM_MAX_VWAP_DIST", 0.25)
RHC_MOM_MAX_LIQ_DROP = _float("RHC_MOM_MAX_LIQ_DROP", 0.10)
RHC_STRAT_VOLEXP_ENABLED = _flag("RHC_STRAT_VOLEXP_ENABLED", "true")
RHC_VEX_MAX_ATR_RATIO = _float("RHC_VEX_MAX_ATR_RATIO", 0.6)
RHC_VEX_MIN_EXPANSION = _float("RHC_VEX_MIN_EXPANSION", 2.5)
RHC_VEX_MIN_CLOSE_POS = _float("RHC_VEX_MIN_CLOSE_POS", 0.75)
RHC_VEX_IMBALANCE = _float("RHC_VEX_IMBALANCE", 0.6)
RHC_STRAT_LIQ_ENABLED = _flag("RHC_STRAT_LIQ_ENABLED", "true")
RHC_LIQ_MIN_GROWTH_60M = _float("RHC_LIQ_MIN_GROWTH_60M", 0.30)
RHC_LIQ_IMBALANCE = _float("RHC_LIQ_IMBALANCE", 0.55)
RHC_LIQ_MIN_TRADERS = _int("RHC_LIQ_MIN_TRADERS", 10)
RHC_STRAT_SMART_ENABLED = _flag("RHC_STRAT_SMART_ENABLED", "false")   # off until validated
RHC_SMART_MIN_BUY_USD = _float("RHC_SMART_MIN_BUY_USD", 500.0)
RHC_SMART_MIN_BUYERS = _int("RHC_SMART_MIN_BUYERS", 2)
RHC_SMART_MIN_CLOSED = _int("RHC_SMART_MIN_CLOSED", 5)
RHC_SMART_MIN_SCORE = _float("RHC_SMART_MIN_SCORE", 0.6)
RHC_SMART_EVAL_MIN_SAMPLES = _int("RHC_SMART_EVAL_MIN_SAMPLES", 200)
RHC_WALLET_REBUILD_S = _int("RHC_WALLET_REBUILD_S", 600)
RHC_RETAIN_WALLET_TRADE_DAYS = _int("RHC_RETAIN_WALLET_TRADE_DAYS", 3)
RHC_RETAIN_WALLET_POS_DAYS = _int("RHC_RETAIN_WALLET_POS_DAYS", 30)
RHC_RETAIN_DECISION_DAYS = _int("RHC_RETAIN_DECISION_DAYS", 30)
# Regime / no-trade rules
RHC_REGIME_LOOKBACK_5M = _int("RHC_REGIME_LOOKBACK_5M", 288)          # 24 h of 5m buckets
RHC_REGIME_MIN_HISTORY_5M = _int("RHC_REGIME_MIN_HISTORY_5M", 24)     # 2 h before a label is given
RHC_REGIME_HOT_PCT = _float("RHC_REGIME_HOT_PCT", 0.8)
RHC_REGIME_COLD_PCT = _float("RHC_REGIME_COLD_PCT", 0.2)
RHC_NO_TRADE_COLD = _flag("RHC_NO_TRADE_COLD", "true")
RHC_NO_TRADE_UNKNOWN_REGIME = _flag("RHC_NO_TRADE_UNKNOWN_REGIME", "false")
RHC_NO_TRADE_ETH_DROP = _float("RHC_NO_TRADE_ETH_DROP", 0.03)
RHC_NO_TRADE_MAX_LAG_S = _int("RHC_NO_TRADE_MAX_LAG_S", 90)
# Risk (paper account)
RHC_PAPER_EQUITY_USD = _float("RHC_PAPER_EQUITY_USD", 1_000.0)
RHC_RISK_PCT = _float("RHC_RISK_PCT", 0.01)
RHC_MIN_POSITION_USD = _float("RHC_MIN_POSITION_USD", 10.0)
RHC_MAX_POSITION_USD = _float("RHC_MAX_POSITION_USD", 50.0)
RHC_MAX_OPEN = _int("RHC_MAX_OPEN", 5)
RHC_MAX_EXPOSURE_PCT = _float("RHC_MAX_EXPOSURE_PCT", 0.25)
RHC_MAX_PER_TOKEN_USD = _float("RHC_MAX_PER_TOKEN_USD", 50.0)
RHC_MAX_DAILY_LOSS_PCT = _float("RHC_MAX_DAILY_LOSS_PCT", 0.03)
RHC_TOKEN_COOLDOWN_MIN = _int("RHC_TOKEN_COOLDOWN_MIN", 60)
RHC_KILL_SWITCH = _flag("RHC_KILL_SWITCH", "false")      # env-level kill switch (DB switch also exists)

# ── Storage guard (free-tier database) ────────────────────────────────────────
RHC_DB_BUDGET_MB = _float("RHC_DB_BUDGET_MB", 400.0)
RHC_PRUNE_AT_PCT = _float("RHC_PRUNE_AT_PCT", 70.0)
RHC_PAUSE_AT_PCT = _float("RHC_PAUSE_AT_PCT", 90.0)
RHC_RESUME_BELOW_PCT = _float("RHC_RESUME_BELOW_PCT", 80.0)
RHC_STORAGE_CHECK_S = _int("RHC_STORAGE_CHECK_S", 3_600)
RHC_RETAIN_1M_HOURS = _int("RHC_RETAIN_1M_HOURS", 72)
RHC_RETAIN_5M_DAYS = _int("RHC_RETAIN_5M_DAYS", 30)          # older 5m candles roll up to 15m
RHC_RETAIN_LIQ_DAYS = _int("RHC_RETAIN_LIQ_DAYS", 7)
RHC_RETAIN_SNAPSHOT_DAYS = _int("RHC_RETAIN_SNAPSHOT_DAYS", 7)
RHC_RETAIN_SWAP_HOURS = _int("RHC_RETAIN_SWAP_HOURS", 48)

# ── External data sources ─────────────────────────────────────────────────────
RHC_HTTP_TIMEOUT_S = _float("RHC_HTTP_TIMEOUT_S", 15.0)
RHC_DEXSCREENER_BASE = os.getenv("RHC_DEXSCREENER_BASE", "https://api.dexscreener.com").rstrip("/")
RHC_GECKOTERMINAL_BASE = os.getenv("RHC_GECKOTERMINAL_BASE", "https://api.geckoterminal.com/api/v2").rstrip("/")
RHC_GT_NETWORK = os.getenv("RHC_GT_NETWORK", "robinhood")
RHC_DS_CHAIN = os.getenv("RHC_DS_CHAIN", "robinhood")
RHC_DEFILLAMA_BASE = os.getenv("RHC_DEFILLAMA_BASE", "https://api.llama.fi").rstrip("/")
RHC_RELAY_BASE = os.getenv("RHC_RELAY_BASE", "https://api.relay.link").rstrip("/")
RHC_DS_MAX_PER_MIN = _float("RHC_DS_MAX_PER_MIN", 120.0)
RHC_GT_MAX_PER_MIN = _float("RHC_GT_MAX_PER_MIN", 20.0)     # 429 observed after ~15 rapid calls
RHC_LLAMA_MAX_PER_MIN = _float("RHC_LLAMA_MAX_PER_MIN", 10.0)
RHC_RELAY_MAX_PER_MIN = _float("RHC_RELAY_MAX_PER_MIN", 30.0)
RHC_SOURCE_CACHE_TTL_S = _int("RHC_SOURCE_CACHE_TTL_S", 60)
RHC_SNAPSHOT_INTERVAL_S = _int("RHC_SNAPSHOT_INTERVAL_S", 300)
RHC_SNAPSHOT_TOP_N = _int("RHC_SNAPSHOT_TOP_N", 20)
RHC_GT_XCHECK_PER_CYCLE = _int("RHC_GT_XCHECK_PER_CYCLE", 10)
RHC_XCHECK_MAX_DEV_PCT = _float("RHC_XCHECK_MAX_DEV_PCT", 5.0)
RHC_CONTEXT_REFRESH_S = _int("RHC_CONTEXT_REFRESH_S", 3_600)
