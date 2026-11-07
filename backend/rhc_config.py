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
