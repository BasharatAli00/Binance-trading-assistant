# Intelligent Sniper Bot — Implementation Guide (Free Sources Only)
> For Claude Code: Implement this autonomous Solana meme-coin trading bot step by step.
> All paid sources (CoinGecko Pro, Helius, twitterapi.io) are replaced with free alternatives.

---

## 0. Overview

Build a long-running Python bot that:
1. Discovers hot pump.fun Solana tokens every 5 min (DexScreener only — free)
2. Snapshots each token every 60 seconds into PostgreSQL
3. Computes ~35 features per token from rolling snapshot history
4. Scores tokens with a rule-based conviction system (ML model optional later)
5. Buys small fixed-size positions when all gates pass
6. Manages exits: stop-loss / trailing-stop / take-profit / time-exit
7. Runs dual-mode: **sim** (paper) and **live** (Jupiter swaps)
8. Exposes a Next.js dashboard at `/pump-bot`

**Free data sources only:**
| Provider | Purpose | Cost |
|----------|---------|------|
| DexScreener API | Discovery, snapshots, prices | Free, no key |
| Jupiter API | Live swap execution, SOL price | Free, no key |
| alternative.me | Fear & Greed index | Free, no key |
| Solana public RPC | On-chain safety checks | Free (use `api.mainnet-beta.solana.com`) |

**Removed (paid):** CoinGecko Pro, Helius RPC, twitterapi.io

---

## 1. Project Structure

```
pump_bot/
├── __init__.py
├── bot.py                  # Main loop — entry point
├── config.py               # All constants & defaults
├── watchlist.py            # Token discovery (DexScreener)
├── collector.py            # Snapshot fetcher (DexScreener)
├── features.py             # Feature engineering from snapshots
├── conviction.py           # Rule-based conviction scorer (0–100)
├── rug_risk.py             # On-chain safety score (public RPC)
├── trader.py               # Entry gate + exit logic
├── live_executor.py        # Jupiter swap execution
├── circuit_breaker.py      # Drawdown protection
├── db.py                   # PostgreSQL helpers
└── macro.py                # Fear & Greed + SOL price (free)

api/
└── pump_bot_router.py      # FastAPI router for dashboard

frontend/
└── app/pump-bot/page.tsx   # Next.js dashboard
```

---

## 2. Database Schema

Create these tables first. All prefixed `pump_`.

```sql
-- Active/tracked tokens
CREATE TABLE pump_watchlist (
    id SERIAL PRIMARY KEY,
    token_address TEXT UNIQUE NOT NULL,
    symbol TEXT,
    name TEXT,
    pair_address TEXT,
    dex_id TEXT,
    liquidity_usd FLOAT,
    volume_h1 FLOAT,
    price_usd FLOAT,
    market_cap FLOAT,
    discovery_source TEXT,
    rank_score FLOAT,
    is_active BOOLEAN DEFAULT TRUE,
    logo_url TEXT,
    has_socials BOOLEAN DEFAULT FALSE,
    boost_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 1-minute time-series snapshots
CREATE TABLE pump_token_snapshots (
    id SERIAL PRIMARY KEY,
    token_address TEXT NOT NULL,
    snapshot_time TIMESTAMPTZ NOT NULL,
    price_usd FLOAT,
    price_native FLOAT,
    volume_m5 FLOAT,
    volume_h1 FLOAT,
    volume_h6 FLOAT,
    volume_h24 FLOAT,
    buys_m5 INT,
    sells_m5 INT,
    buys_h1 INT,
    sells_h1 INT,
    buys_h6 INT,
    sells_h6 INT,
    buys_h24 INT,
    sells_h24 INT,
    price_change_m5 FLOAT,
    price_change_h1 FLOAT,
    price_change_h6 FLOAT,
    price_change_h24 FLOAT,
    liquidity_usd FLOAT,
    liquidity_base FLOAT,
    liquidity_quote FLOAT,
    market_cap FLOAT,
    fdv FLOAT,
    pair_created_at TIMESTAMPTZ,
    has_socials BOOLEAN,
    pool_count INT,
    boost_count INT,
    dex_id TEXT,
    pair_address TEXT,
    UNIQUE(token_address, snapshot_time)
);
CREATE INDEX idx_snapshots_token_time ON pump_token_snapshots(token_address, snapshot_time DESC);

-- Open & closed positions
CREATE TABLE pump_positions (
    id SERIAL PRIMARY KEY,
    portfolio_id INT REFERENCES pump_bot_portfolio(id),
    token_address TEXT NOT NULL,
    symbol TEXT,
    entry_price FLOAT NOT NULL,
    entry_time TIMESTAMPTZ DEFAULT NOW(),
    exit_price FLOAT,
    exit_time TIMESTAMPTZ,
    qty FLOAT NOT NULL,
    position_usd FLOAT NOT NULL,
    peak_price FLOAT,
    exit_reason TEXT,
    realized_pnl FLOAT,
    return_pct FLOAT,
    hold_minutes FLOAT,
    conviction_score FLOAT,
    rug_risk_score FLOAT,
    entry_dex_id TEXT,
    entry_pair_address TEXT,
    discovery_source TEXT,
    tx_hash_buy TEXT,
    tx_hash_sell TEXT,
    status TEXT DEFAULT 'open'   -- open | closed
);
CREATE INDEX idx_positions_portfolio_status ON pump_positions(portfolio_id, status);

-- Immutable trade log
CREATE TABLE pump_trades (
    id SERIAL PRIMARY KEY,
    position_id INT REFERENCES pump_positions(id),
    portfolio_id INT,
    token_address TEXT,
    symbol TEXT,
    side TEXT,           -- buy | sell
    price FLOAT,
    qty FLOAT,
    usd_value FLOAT,
    tx_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Per-portfolio strategy config (tunable from UI)
CREATE TABLE pump_bot_portfolio (
    id SERIAL PRIMARY KEY,
    name TEXT,
    mode TEXT DEFAULT 'sim',          -- sim | live
    is_active BOOLEAN DEFAULT TRUE,
    cash_balance FLOAT DEFAULT 1000,
    initial_balance FLOAT DEFAULT 1000,
    position_size FLOAT DEFAULT 50,
    max_open_positions INT DEFAULT 5,
    stop_loss_pct FLOAT DEFAULT -20,
    take_profit_pct FLOAT DEFAULT 1000,
    time_exit_minutes INT DEFAULT 120,
    trail_start_pct FLOAT DEFAULT 15,
    trail_start_distance FLOAT DEFAULT 5,
    trail_end_pct FLOAT DEFAULT 30,
    trail_end_distance FLOAT DEFAULT 2,
    model_threshold FLOAT DEFAULT 0.40,
    model_gate_enabled BOOLEAN DEFAULT FALSE,  -- off until training data accumulates
    conviction_floor INT DEFAULT 20,
    min_buy_pressure FLOAT DEFAULT 0.5,
    min_vol_accel FLOAT DEFAULT 0,
    cb_enabled BOOLEAN DEFAULT TRUE,
    cb_max_drawdown FLOAT DEFAULT 20,
    cb_action TEXT DEFAULT 'pause',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Cooldowns after exits
CREATE TABLE pump_cooldowns (
    token_address TEXT PRIMARY KEY,
    cooldown_until TIMESTAMPTZ NOT NULL
);

-- ML scores per token (updated each tick)
CREATE TABLE pump_model_scores (
    token_address TEXT PRIMARY KEY,
    prob_win FLOAT,
    conviction_score FLOAT,
    rug_risk_score FLOAT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 3. config.py — All Constants

```python
# pump_bot/config.py

# Timing
POLL_INTERVAL_SEC     = 60
WATCHLIST_REFRESH_MIN = 5
WATCHLIST_MAX_TOKENS  = 50
SNAPSHOT_RETENTION_DAYS = 45

# Discovery filters
MIN_LIQUIDITY         = 10_000     # USD
MIN_VOLUME_H1         = 1_000      # USD
MIN_TOKEN_AGE_MIN     = 30
MAX_TOKEN_AGE_DAYS    = 7
MIN_PRICE_MOVE_M5     = 2.0        # % absolute
MIN_PRICE_MOVE_H1     = 5.0        # %

# Entry gates
MIN_PRICE_CHANGE_M5   = 3.0        # % — momentum gate, never bypassed
MIN_BUY_PRESSURE      = 0.5
RUG_RISK_VETO_THRESHOLD = 45

# Exit defaults (overridden per-portfolio in DB)
STOP_LOSS_PCT         = -20.0
TAKE_PROFIT_PCT       = 1000.0
TIME_EXIT_MINUTES     = 120
TRAIL_START_PCT       = 15.0
TRAIL_START_DIST      = 5.0
TRAIL_END_PCT         = 30.0
TRAIL_END_DIST        = 2.0

# Cooldown minutes by exit reason
COOLDOWN_MINUTES = {
    "stop_loss":      10,
    "time_exit":       5,
    "trailing_stop":   3,
    "take_profit":     2,
    "default":         5,
}

# Free API endpoints
DEXSCREENER_BASE      = "https://api.dexscreener.com"
JUPITER_PRICE_URL     = "https://api.jup.ag/price/v2"
JUPITER_QUOTE_URL     = "https://api.jup.ag/swap/v2/order"   # quote
JUPITER_SWAP_URL      = "https://api.jup.ag/swap/v2/execute"
FEAR_GREED_URL        = "https://api.alternative.me/fng/?limit=1"
SOLANA_RPC_URL        = "https://api.mainnet-beta.solana.com"

# Security
WALLET_ENCRYPTION_KEY = ""   # set in env: WALLET_ENCRYPTION_KEY (Fernet)
DATABASE_URL          = ""   # set in env: DATABASE_URL
```

---

## 4. watchlist.py — Token Discovery (DexScreener only)

```python
"""
pump_bot/watchlist.py
Discovers top 50 pump.fun tokens using only free DexScreener endpoints.
Runs every WATCHLIST_REFRESH_MIN minutes.
"""
import time, asyncio, httpx
from datetime import datetime, timezone
from pump_bot.config import *

DISCOVERY_ENDPOINTS = [
    # (url, tag, max_results)
    (f"{DEXSCREENER_BASE}/token-boosts/top/v1",      "boost_top",    30),
    (f"{DEXSCREENER_BASE}/token-boosts/latest/v1",   "boost_latest", 30),
    (f"{DEXSCREENER_BASE}/token-profiles/latest/v1", "profile",      20),
]

async def refresh_watchlist(conn):
    """Main entry point. Returns list of enriched token dicts."""
    candidates = {}   # addr -> {source, ...}

    async with httpx.AsyncClient(timeout=15) as client:
        # 1. Collect addresses from discovery endpoints
        for url, tag, limit in DISCOVERY_ENDPOINTS:
            try:
                r = await client.get(url)
                r.raise_for_status()
                items = r.json() if isinstance(r.json(), list) else r.json().get("pairs", [])
                for item in items[:limit]:
                    addr = item.get("tokenAddress") or item.get("address", "")
                    if addr.endswith("pump"):
                        candidates.setdefault(addr, {"source": tag})
            except Exception as e:
                print(f"[watchlist] {tag} error: {e}")
            await asyncio.sleep(0.5)

        # 2. Batch enrich with pair data (30 at a time)
        addrs = list(candidates.keys())
        enriched = []
        for i in range(0, len(addrs), 30):
            batch = addrs[i:i+30]
            try:
                r = await client.get(f"{DEXSCREENER_BASE}/latest/dex/tokens/{','.join(batch)}")
                r.raise_for_status()
                pairs = r.json().get("pairs", []) or []
                for pair in pairs:
                    token = _best_pair(pair, pairs)
                    if token and _passes_filters(token):
                        addr = token["baseToken"]["address"]
                        token["_source"] = candidates.get(addr, {}).get("source", "unknown")
                        enriched.append(token)
            except Exception as e:
                print(f"[watchlist] enrich batch error: {e}")
            await asyncio.sleep(1.0)

    # 3. Deduplicate by address, keep best pair
    seen = {}
    for t in enriched:
        addr = t["baseToken"]["address"]
        score = _rank_score(t)
        if addr not in seen or score > seen[addr]["_rank"]:
            t["_rank"] = score
            seen[addr] = t

    ranked = sorted(seen.values(), key=lambda x: x["_rank"], reverse=True)[:WATCHLIST_MAX_TOKENS]

    # 4. Upsert to DB
    await _upsert_watchlist(conn, ranked)
    return ranked


def _best_pair(pair, all_pairs):
    """For a token address, prefer pumpswap pair, else highest liquidity."""
    addr = pair.get("baseToken", {}).get("address", "")
    matches = [p for p in all_pairs if p.get("baseToken", {}).get("address") == addr]
    pump = [p for p in matches if p.get("dexId") == "pumpswap"]
    if pump:
        return max(pump, key=lambda p: p.get("liquidity", {}).get("usd", 0))
    if matches:
        return max(matches, key=lambda p: p.get("liquidity", {}).get("usd", 0))
    return pair


def _passes_filters(pair: dict) -> bool:
    addr    = pair.get("baseToken", {}).get("address", "")
    chain   = pair.get("chainId", "")
    liq     = pair.get("liquidity", {}).get("usd", 0) or 0
    vol_h1  = pair.get("volume", {}).get("h1", 0) or 0
    created = pair.get("pairCreatedAt")            # epoch ms
    txns_m5 = (pair.get("txns", {}).get("m5", {}).get("buys", 0) or 0) + \
              (pair.get("txns", {}).get("m5", {}).get("sells", 0) or 0)
    pc_m5   = abs(pair.get("priceChange", {}).get("m5", 0) or 0)
    pc_h1   = abs(pair.get("priceChange", {}).get("h1", 0) or 0)

    if not addr.endswith("pump"):          return False
    if chain != "solana":                  return False
    if liq < MIN_LIQUIDITY:                return False
    if vol_h1 < MIN_VOLUME_H1:            return False
    if txns_m5 == 0:                      return False
    if pc_m5 < MIN_PRICE_MOVE_M5 and pc_h1 < MIN_PRICE_MOVE_H1:
        return False

    if created:
        age_min = (time.time() * 1000 - created) / 60_000
        if age_min < MIN_TOKEN_AGE_MIN or age_min > MAX_TOKEN_AGE_DAYS * 1440:
            return False
    return True


def _rank_score(pair: dict) -> float:
    liq      = pair.get("liquidity", {}).get("usd", 1) or 1
    vol_h1   = pair.get("volume", {}).get("h1", 0) or 0
    buys_m5  = pair.get("txns", {}).get("m5", {}).get("buys", 0) or 0
    sells_m5 = pair.get("txns", {}).get("m5", {}).get("sells", 0) or 0
    pc_m5    = abs(pair.get("priceChange", {}).get("m5", 0) or 0)
    pc_h1    = abs(pair.get("priceChange", {}).get("h1", 0) or 0)
    source   = pair.get("_source", "")

    vol_liq      = vol_h1 / liq
    buy_pressure = buys_m5 / (sells_m5 + 1)
    momentum     = pc_m5 + pc_h1 / 2
    score        = vol_liq * (1 + buy_pressure) * (1 + momentum / 10)
    return score


async def _upsert_watchlist(conn, tokens: list):
    now = datetime.now(timezone.utc)
    # Mark all inactive first
    await conn.execute("UPDATE pump_watchlist SET is_active = FALSE WHERE is_active = TRUE")
    for t in tokens:
        addr    = t["baseToken"]["address"]
        symbol  = t["baseToken"].get("symbol", "")
        name    = t["baseToken"].get("name", "")
        pair    = t.get("pairAddress", "")
        dex     = t.get("dexId", "")
        liq     = t.get("liquidity", {}).get("usd", 0)
        vol_h1  = t.get("volume", {}).get("h1", 0)
        price   = float(t.get("priceUsd", 0) or 0)
        mcap    = t.get("marketCap", 0)
        source  = t.get("_source", "unknown")
        rank    = t.get("_rank", 0)
        socials = bool(t.get("info", {}).get("socials"))
        boosts  = t.get("boosts", {}).get("active", 0) or 0
        logo    = t.get("info", {}).get("imageUrl", "")

        await conn.execute("""
            INSERT INTO pump_watchlist
                (token_address, symbol, name, pair_address, dex_id, liquidity_usd,
                 volume_h1, price_usd, market_cap, discovery_source, rank_score,
                 is_active, has_socials, boost_count, logo_url, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,TRUE,$12,$13,$14,$15)
            ON CONFLICT (token_address) DO UPDATE SET
                pair_address=EXCLUDED.pair_address, dex_id=EXCLUDED.dex_id,
                liquidity_usd=EXCLUDED.liquidity_usd, volume_h1=EXCLUDED.volume_h1,
                price_usd=EXCLUDED.price_usd, market_cap=EXCLUDED.market_cap,
                discovery_source=EXCLUDED.discovery_source, rank_score=EXCLUDED.rank_score,
                is_active=TRUE, has_socials=EXCLUDED.has_socials,
                boost_count=EXCLUDED.boost_count, logo_url=EXCLUDED.logo_url,
                updated_at=EXCLUDED.updated_at
        """, addr, symbol, name, pair, dex, liq, vol_h1, price, mcap,
             source, rank, socials, boosts, logo, now)
```

---

## 5. collector.py — Snapshot Fetcher

```python
"""
pump_bot/collector.py
Fetches DexScreener snapshots every tick for watchlist + open positions.
"""
import asyncio, httpx
from datetime import datetime, timezone
from pump_bot.config import DEXSCREENER_BASE


async def fetch_snapshots(conn, addresses: list[str]) -> dict:
    """
    Fetch and store 1-min snapshots for all given addresses.
    Returns dict: addr -> snapshot_dict
    """
    results = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for i in range(0, len(addresses), 30):
            batch = addresses[i:i+30]
            try:
                r = await client.get(
                    f"{DEXSCREENER_BASE}/latest/dex/tokens/{','.join(batch)}"
                )
                r.raise_for_status()
                pairs = r.json().get("pairs") or []
                # Group by token address, pick best pair
                by_addr = {}
                for p in pairs:
                    addr = p.get("baseToken", {}).get("address", "")
                    if not addr:
                        continue
                    liq = p.get("liquidity", {}).get("usd", 0) or 0
                    is_pump = p.get("dexId") == "pumpswap"
                    existing = by_addr.get(addr)
                    if not existing or is_pump or liq > (existing.get("liquidity", {}).get("usd", 0) or 0):
                        by_addr[addr] = p

                now = datetime.now(timezone.utc)
                for addr, p in by_addr.items():
                    snap = _extract_snapshot(addr, p, now)
                    results[addr] = snap
                    await _store_snapshot(conn, snap)

            except Exception as e:
                print(f"[collector] batch error: {e}")
            await asyncio.sleep(1.0)

    return results


def _extract_snapshot(addr: str, pair: dict, now: datetime) -> dict:
    vol  = pair.get("volume", {})
    txns = pair.get("txns", {})
    pc   = pair.get("priceChange", {})
    liq  = pair.get("liquidity", {})

    return {
        "token_address":   addr,
        "snapshot_time":   now,
        "price_usd":       float(pair.get("priceUsd", 0) or 0),
        "price_native":    float(pair.get("priceNative", 0) or 0),
        "volume_m5":       vol.get("m5", 0),
        "volume_h1":       vol.get("h1", 0),
        "volume_h6":       vol.get("h6", 0),
        "volume_h24":      vol.get("h24", 0),
        "buys_m5":         txns.get("m5", {}).get("buys", 0),
        "sells_m5":        txns.get("m5", {}).get("sells", 0),
        "buys_h1":         txns.get("h1", {}).get("buys", 0),
        "sells_h1":        txns.get("h1", {}).get("sells", 0),
        "buys_h6":         txns.get("h6", {}).get("buys", 0),
        "sells_h6":        txns.get("h6", {}).get("sells", 0),
        "buys_h24":        txns.get("h24", {}).get("buys", 0),
        "sells_h24":       txns.get("h24", {}).get("sells", 0),
        "price_change_m5": pc.get("m5", 0),
        "price_change_h1": pc.get("h1", 0),
        "price_change_h6": pc.get("h6", 0),
        "price_change_h24":pc.get("h24", 0),
        "liquidity_usd":   liq.get("usd", 0),
        "liquidity_base":  liq.get("base", 0),
        "liquidity_quote": liq.get("quote", 0),
        "market_cap":      pair.get("marketCap", 0),
        "fdv":             pair.get("fdv", 0),
        "pair_created_at": pair.get("pairCreatedAt"),
        "has_socials":     bool(pair.get("info", {}).get("socials")),
        "pool_count":      pair.get("info", {}).get("pairCount", 1),
        "boost_count":     pair.get("boosts", {}).get("active", 0) or 0,
        "dex_id":          pair.get("dexId", ""),
        "pair_address":    pair.get("pairAddress", ""),
    }


async def _store_snapshot(conn, snap: dict):
    await conn.execute("""
        INSERT INTO pump_token_snapshots
            (token_address, snapshot_time, price_usd, price_native,
             volume_m5, volume_h1, volume_h6, volume_h24,
             buys_m5, sells_m5, buys_h1, sells_h1, buys_h6, sells_h6, buys_h24, sells_h24,
             price_change_m5, price_change_h1, price_change_h6, price_change_h24,
             liquidity_usd, liquidity_base, liquidity_quote,
             market_cap, fdv, pair_created_at, has_socials, pool_count, boost_count,
             dex_id, pair_address)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                $17,$18,$19,$20,$21,$22,$23,$24,$25,to_timestamp($26/1000.0),$27,$28,$29,$30,$31)
        ON CONFLICT (token_address, snapshot_time) DO NOTHING
    """,
    snap["token_address"], snap["snapshot_time"], snap["price_usd"], snap["price_native"],
    snap["volume_m5"], snap["volume_h1"], snap["volume_h6"], snap["volume_h24"],
    snap["buys_m5"], snap["sells_m5"], snap["buys_h1"], snap["sells_h1"],
    snap["buys_h6"], snap["sells_h6"], snap["buys_h24"], snap["sells_h24"],
    snap["price_change_m5"], snap["price_change_h1"], snap["price_change_h6"], snap["price_change_h24"],
    snap["liquidity_usd"], snap["liquidity_base"], snap["liquidity_quote"],
    snap["market_cap"], snap["fdv"], snap["pair_created_at"],
    snap["has_socials"], snap["pool_count"], snap["boost_count"],
    snap["dex_id"], snap["pair_address"])
```

---

## 6. features.py — Feature Engineering

```python
"""
pump_bot/features.py
Computes ~35 features per token from the last 20 minutes of snapshots.
Returns None if < 3 snapshots exist.
"""
import statistics
from datetime import datetime, timezone, timedelta


async def compute_features(conn, token_address: str, latest_snap: dict) -> dict | None:
    # Fetch last 20 minutes of snapshots
    rows = await conn.fetch("""
        SELECT * FROM pump_token_snapshots
        WHERE token_address = $1
          AND snapshot_time >= NOW() - INTERVAL '20 minutes'
        ORDER BY snapshot_time ASC
    """, token_address)

    if len(rows) < 3:
        return None

    snaps = [dict(r) for r in rows]
    latest = snaps[-1]
    prev   = snaps[-2] if len(snaps) >= 2 else latest

    f = {}

    # --- 5m momentum (from DexScreener directly) ---
    f["price_change_m5"]  = latest.get("price_change_m5", 0) or 0
    f["volume_m5"]        = latest.get("volume_m5", 0) or 0
    f["buys_m5"]          = latest.get("buys_m5", 0) or 0
    f["sells_m5"]         = latest.get("sells_m5", 0) or 0

    # --- 15m computed from own snapshots ---
    prices   = [s["price_usd"] for s in snaps if s.get("price_usd")]
    vols     = [s["volume_m5"] for s in snaps if s.get("volume_m5")]
    buys_arr = [s["buys_m5"]   for s in snaps if s.get("buys_m5") is not None]
    sell_arr = [s["sells_m5"]  for s in snaps if s.get("sells_m5") is not None]

    if len(prices) >= 2:
        p_now  = prices[-1]
        p_3m   = prices[-3]  if len(prices) >= 3  else prices[0]
        p_10m  = prices[-10] if len(prices) >= 10 else prices[0]
        p_15m  = prices[-15] if len(prices) >= 15 else prices[0]
        f["price_change_3m"]  = (p_now - p_3m)  / p_3m  * 100 if p_3m  else 0
        f["price_change_10m"] = (p_now - p_10m) / p_10m * 100 if p_10m else 0
        f["price_change_15m"] = (p_now - p_15m) / p_15m * 100 if p_15m else 0

        # Volatility (std of 1-min returns)
        returns = [(prices[i] - prices[i-1]) / prices[i-1] * 100
                   for i in range(1, len(prices)) if prices[i-1]]
        f["price_volatility_15m"] = statistics.stdev(returns) if len(returns) >= 2 else 0

        # Trend (linear slope normalized)
        n = len(prices)
        mean_x = (n - 1) / 2
        mean_y = sum(prices) / n
        num = sum((i - mean_x) * (prices[i] - mean_y) for i in range(n))
        den = sum((i - mean_x) ** 2 for i in range(n))
        f["price_trend_15m"] = (num / den) if den else 0

        # Session high
        session_high = max(prices)
        f["price_vs_session_high"] = (p_now / session_high - 1) * 100 if session_high else 0

        # Consecutive green candles
        green = 0
        for i in range(len(prices) - 1, 0, -1):
            if prices[i] > prices[i-1]:
                green += 1
            else:
                break
        f["consecutive_green_candles"] = green
    else:
        f.update({k: 0 for k in ["price_change_3m","price_change_10m","price_change_15m",
                                   "price_volatility_15m","price_trend_15m",
                                   "price_vs_session_high","consecutive_green_candles"]})

    # Volume 15m sum & trend
    f["volume_sum_15m"]  = sum(vols[-15:]) if vols else 0
    f["buys_sum_15m"]    = sum(buys_arr[-15:]) if buys_arr else 0
    f["sells_sum_15m"]   = sum(sell_arr[-15:]) if sell_arr else 0
    total_bs = f["buys_sum_15m"] + f["sells_sum_15m"]
    f["buy_sell_ratio_15m"] = f["buys_sum_15m"] / total_bs if total_bs else 0.5

    if len(vols) >= 6:
        recent_vol  = sum(vols[-3:]) / 3
        earlier_vol = sum(vols[-6:-3]) / 3
        va = recent_vol / earlier_vol if earlier_vol else 1
        f["vol_acceleration_15m"] = min(va / 5, 1.0)
    else:
        f["vol_acceleration_15m"] = 0

    liq = latest.get("liquidity_usd", 0) or 1
    f["vol_to_liquidity_15m"] = f["volume_sum_15m"] / liq

    trade_count = total_bs
    f["avg_trade_size_15m"] = (f["volume_sum_15m"] / trade_count) if trade_count else 0

    if len(vols) >= 2:
        v_n  = len(vols)
        mean_vx = (v_n - 1) / 2
        mean_vy = sum(vols) / v_n
        vnum = sum((i - mean_vx) * (vols[i] - mean_vy) for i in range(v_n))
        vden = sum((i - mean_vx) ** 2 for i in range(v_n))
        f["volume_trend_15m"] = (vnum / vden) if vden else 0
    else:
        f["volume_trend_15m"] = 0

    # --- 1h context (from DexScreener) ---
    f["price_change_h1"]       = latest.get("price_change_h1", 0) or 0
    f["volume_h1"]             = latest.get("volume_h1", 0) or 0
    f["buys_h1"]               = latest.get("buys_h1", 0) or 0
    f["sells_h1"]              = latest.get("sells_h1", 0) or 0
    total_h1 = f["buys_h1"] + f["sells_h1"]
    f["buyer_seller_ratio_h1"] = f["buys_h1"] / total_h1 if total_h1 else 0.5

    # --- Broader context ---
    f["price_change_h6"]  = latest.get("price_change_h6", 0) or 0
    f["price_change_h24"] = latest.get("price_change_h24", 0) or 0
    f["volume_h6"]        = latest.get("volume_h6", 0) or 0
    f["volume_h24"]       = latest.get("volume_h24", 0) or 0

    # Momentum acceleration (3m vs 15m)
    f["momentum_accel"] = f["price_change_3m"] - f.get("price_change_15m", 0)

    # Buy pressure 10m
    buys_10 = sum(buys_arr[-10:]) if len(buys_arr) >= 10 else sum(buys_arr)
    sells_10 = sum(sell_arr[-10:]) if len(sell_arr) >= 10 else sum(sell_arr)
    f["buy_pressure_10m"] = buys_10 / (sells_10 + 1)

    # --- Token profile ---
    created_ms = latest.get("pair_created_at")
    if created_ms:
        import time
        age_h = (time.time() - (created_ms / 1000 if created_ms > 1e10 else created_ms)) / 3600
    else:
        age_h = 0
    f["token_age_hours"]   = age_h
    f["liquidity_usd"]     = latest.get("liquidity_usd", 0) or 0
    f["market_cap"]        = latest.get("market_cap", 0) or 0
    f["liq_to_mcap_ratio"] = f["liquidity_usd"] / f["market_cap"] if f["market_cap"] else 0
    f["pool_count"]        = latest.get("pool_count", 1) or 1
    f["has_socials"]       = 1 if latest.get("has_socials") else 0
    f["boost_count"]       = latest.get("boost_count", 0) or 0
    f["fdv"]               = latest.get("fdv", 0) or 0
    f["fdv_mcap_ratio"]    = f["fdv"] / f["market_cap"] if f["market_cap"] else 1

    # Liquidity drain detection (rug signal)
    liq_10m_ago = snaps[-10]["liquidity_quote"] if len(snaps) >= 10 else None
    liq_now_q   = latest.get("liquidity_quote", 0) or 0
    if liq_10m_ago and liq_10m_ago > 0:
        f["liq_quote_change_10m"] = (liq_now_q - liq_10m_ago) / liq_10m_ago * 100
    else:
        f["liq_quote_change_10m"] = 0

    # Prev snapshot for reversal detection
    f["prev_buys_m5"]  = prev.get("buys_m5", 0) or 0
    f["prev_sells_m5"] = prev.get("sells_m5", 0) or 0

    # Is graduated (on Raydium/Orca/Meteora = not just pumpswap)
    f["is_graduated"] = 0 if latest.get("dex_id") == "pumpswap" else 1

    # Buyer dominance 24h
    total_24h = (latest.get("buys_h24", 0) or 0) + (latest.get("sells_h24", 0) or 0)
    f["buyer_seller_ratio_h24"] = (latest.get("buys_h24", 0) or 0) / total_24h if total_24h else 0.5

    return f
```

---

## 7. macro.py — Free Macro Data

```python
"""
pump_bot/macro.py
Fetches Fear & Greed + SOL price from free sources only.
"""
import httpx
from pump_bot.config import FEAR_GREED_URL, JUPITER_PRICE_URL

_macro_cache = {}

async def refresh_macro() -> dict:
    global _macro_cache
    data = {}

    async with httpx.AsyncClient(timeout=10) as client:
        # Fear & Greed (alternative.me — completely free)
        try:
            r = await client.get(FEAR_GREED_URL)
            r.raise_for_status()
            fng = r.json()["data"][0]
            data["fear_greed_index"]  = int(fng["value"])
            data["fear_greed_label"]  = fng["value_classification"]
        except Exception as e:
            print(f"[macro] F&G error: {e}")
            data["fear_greed_index"] = 50
            data["fear_greed_label"] = "Neutral"

        # SOL price via Jupiter (free, no key)
        try:
            r = await client.get(
                JUPITER_PRICE_URL,
                params={"ids": "So11111111111111111111111111111111111111112"}
            )
            r.raise_for_status()
            sol = r.json()["data"]["So11111111111111111111111111111111111111112"]
            data["sol_price_usd"] = float(sol["price"])
        except Exception as e:
            print(f"[macro] SOL price error: {e}")
            data["sol_price_usd"] = 150.0  # fallback

    _macro_cache = data
    return data

def get_macro() -> dict:
    return _macro_cache
```

---

## 8. rug_risk.py — Safety Score (Public RPC, Free)

```python
"""
pump_bot/rug_risk.py
Computes rug risk 0–100 using only public Solana RPC (free).
Veto threshold: >= 45.
IMPORTANT: Rate-limit these calls — max once per token per 5 min.
"""
import httpx, asyncio
from pump_bot.config import SOLANA_RPC_URL

_cache = {}   # addr -> (score, timestamp)

async def compute_rug_risk(token_address: str, features: dict) -> int:
    import time
    cached = _cache.get(token_address)
    if cached and time.time() - cached[1] < 300:
        return cached[0]

    score = 0

    # Feature-derived components (no RPC needed)
    liq_mcap   = features.get("liq_to_mcap_ratio", 0)
    liq_drain  = features.get("liq_quote_change_10m", 0)
    has_socials = features.get("has_socials", 0)
    age_hours  = features.get("token_age_hours", 0)
    sells_m5   = features.get("sells_m5", 0)
    buys_m5    = features.get("buys_m5", 0)
    is_grad    = features.get("is_graduated", 0)

    if liq_drain < -10:          score += 15   # liquidity draining
    if not has_socials:          score += 10   # no socials
    if not is_grad:              score += 10   # not graduated
    if age_hours < 1:            score += 10   # very new
    if liq_mcap < 0.05:         score += 5    # thin liquidity vs mcap
    sp = sells_m5 / (buys_m5 + 1)
    if sp > 2:                   score += 10   # heavy sell pressure

    # On-chain components via public RPC
    try:
        mint_ok, freeze_ok, top_holder_pct = await _check_onchain(token_address)
        if not mint_ok:   score += 20   # mint authority not revoked (#1 rug vector)
        if not freeze_ok: score += 10   # freeze authority active
        if top_holder_pct > 50: score += 15   # extreme concentration
        elif top_holder_pct > 30: score += 8
    except Exception as e:
        print(f"[rug_risk] RPC error for {token_address}: {e}")
        score += 10   # penalize if we can't check

    score = min(score, 100)
    _cache[token_address] = (score, __import__("time").time())
    return score


async def _check_onchain(mint_address: str):
    """
    Returns (mint_revoked: bool, freeze_revoked: bool, top_holder_pct: float)
    Uses public Solana RPC — no key needed.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        # Check mint/freeze authority via getAccountInfo
        r = await client.post(SOLANA_RPC_URL, json={
            "jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
            "params": [mint_address, {"encoding": "jsonParsed"}]
        })
        info = r.json().get("result", {}).get("value", {})
        parsed = info.get("data", {}).get("parsed", {}).get("info", {})
        mint_auth   = parsed.get("mintAuthority")
        freeze_auth = parsed.get("freezeAuthority")
        mint_revoked   = mint_auth is None
        freeze_revoked = freeze_auth is None

        # Check top holder concentration via getTokenLargestAccounts
        await asyncio.sleep(0.3)
        r2 = await client.post(SOLANA_RPC_URL, json={
            "jsonrpc": "2.0", "id": 2,
            "method": "getTokenLargestAccounts",
            "params": [mint_address]
        })
        supply_r = await client.post(SOLANA_RPC_URL, json={
            "jsonrpc": "2.0", "id": 3,
            "method": "getTokenSupply",
            "params": [mint_address]
        })
        holders = r2.json().get("result", {}).get("value", [])
        total   = float(supply_r.json().get("result", {}).get("value", {}).get("uiAmount", 1) or 1)
        top_amt = float(holders[0]["uiAmount"]) if holders else 0
        top_pct = (top_amt / total * 100) if total else 0

    return mint_revoked, freeze_revoked, top_pct
```

---

## 9. conviction.py — Rule-Based Scorer (Replaces ML for v1)

```python
"""
pump_bot/conviction.py
Rule-based conviction score 0–100 (ML is additive later).
"""
from pump_bot.macro import get_macro


def compute_conviction(features: dict) -> float:
    score = 0.0

    # 1. Volume acceleration (max 18)
    va = features.get("vol_acceleration_15m", 0)
    score += min(va * 18, 18)

    # 2. Buy pressure 10m (max 15)
    bp = features.get("buy_pressure_10m", 0)
    if bp >= 3:    score += 15
    elif bp >= 2:  score += 10
    elif bp >= 1.5:score += 7
    elif bp >= 1:  score += 3

    # 3. Buy-ratio trend (max 10)
    bsr_15m = features.get("buy_sell_ratio_15m", 0.5)
    bsr_h1  = features.get("buyer_seller_ratio_h1", 0.5)
    if bsr_15m > bsr_h1: score += 10
    elif bsr_15m > 0.6:  score += 5

    # 4. Boost count (max 7, cap spam)
    bc = features.get("boost_count", 0)
    if 0 < bc <= 500:
        score += min(bc / 100 * 7, 7)

    # 5. Liquidity health (max 15)
    liq     = features.get("liquidity_usd", 0)
    lm_ratio = features.get("liq_to_mcap_ratio", 0)
    liq_drain = features.get("liq_quote_change_10m", 0)
    if liq >= 100_000:  score += 7
    elif liq >= 50_000: score += 5
    elif liq >= 10_000: score += 2
    if lm_ratio >= 0.1: score += 5
    elif lm_ratio >= 0.05: score += 3
    if liq_drain < -10: score -= 7   # rug penalty

    # 6. Macro sentiment (max 10)
    macro = get_macro()
    fg    = macro.get("fear_greed_index", 50)
    if fg >= 70:   score += 10
    elif fg >= 50: score += 5
    elif fg <= 25: score -= 5

    # 7. Momentum confirmation (max 10)
    pc_m5  = features.get("price_change_m5", 0)
    greens = features.get("consecutive_green_candles", 0)
    if pc_m5 >= 5:   score += 7
    elif pc_m5 >= 3: score += 4
    if greens >= 3:  score += 3
    elif greens >= 2:score += 1

    # 8. Buyer dominance (max 10)
    if bsr_15m >= 0.7:  score += 10
    elif bsr_15m >= 0.6:score += 6
    elif bsr_15m >= 0.55:score += 3

    # 9. Graduated (max 5)
    if features.get("is_graduated", 0):
        score += 5

    # 10. Has socials (max 5)
    if features.get("has_socials", 0):
        score += 5

    return round(min(score, 100), 2)
```

---

## 10. trader.py — Entry Gate + Exit Logic

```python
"""
pump_bot/trader.py
Full gate stack for entries + tick-based exit management.
"""
from datetime import datetime, timezone, timedelta
from pump_bot.config import *
from pump_bot.conviction import compute_conviction
from pump_bot.rug_risk import compute_rug_risk


async def filter_and_rank_entries(conn, snapshots: dict, features_map: dict) -> list:
    """
    Returns list of (token_address, features, conviction, rug_risk) passing all gates.
    """
    candidates = []

    # Count total open slots across all portfolios
    open_counts = await conn.fetch("""
        SELECT portfolio_id, COUNT(*) as cnt
        FROM pump_positions WHERE status = 'open'
        GROUP BY portfolio_id
    """)
    portfolios  = await conn.fetch("SELECT * FROM pump_bot_portfolio WHERE is_active = TRUE")

    total_slots = sum(
        p["max_open_positions"] - next((r["cnt"] for r in open_counts if r["portfolio_id"] == p["id"]), 0)
        for p in portfolios
    )
    if total_slots <= 0:
        return []

    for addr, feats in features_map.items():
        if not feats:
            continue

        # --- Dedup: already holding? ---
        holding = await conn.fetchval(
            "SELECT id FROM pump_positions WHERE token_address=$1 AND status='open' LIMIT 1", addr
        )
        if holding:
            continue

        # --- Cooldown ---
        cooldown = await conn.fetchval(
            "SELECT cooldown_until FROM pump_cooldowns WHERE token_address=$1", addr
        )
        if cooldown and cooldown > datetime.now(timezone.utc):
            continue

        # --- Quality gates ---
        if feats.get("liquidity_usd", 0) < MIN_LIQUIDITY:
            continue
        if (feats.get("buys_m5", 0) + feats.get("sells_m5", 0)) == 0:
            continue
        if feats.get("buy_pressure_10m", 0) < MIN_BUY_PRESSURE:
            continue

        # --- Reversal veto ---
        curr_buys  = feats.get("buys_m5", 0)
        curr_sells = feats.get("sells_m5", 0)
        prev_buys  = feats.get("prev_buys_m5", 0)
        prev_sells = feats.get("prev_sells_m5", 0)
        if curr_sells > curr_buys and prev_sells > prev_buys:
            continue   # actively reversing

        # --- Momentum gate (NEVER bypassed) ---
        if feats.get("price_change_m5", 0) < MIN_PRICE_CHANGE_M5:
            continue

        # --- Bearish vetoes (NEVER bypassed) ---
        pc_m5  = feats.get("price_change_m5", 0)
        pc_15m = feats.get("price_change_15m", 0)
        if pc_m5 < -3 and pc_15m < -5:
            continue
        if pc_m5 < -5:
            continue
        if feats.get("liq_quote_change_10m", 0) < -10:
            continue   # liquidity drain = rug

        # --- Rug risk veto (NEVER bypassed) ---
        rug_score = await compute_rug_risk(addr, feats)
        if rug_score >= RUG_RISK_VETO_THRESHOLD:
            continue

        # --- Conviction ---
        conviction = compute_conviction(feats)
        feats["_conviction"]  = conviction
        feats["_rug_risk"]    = rug_score

        candidates.append((addr, feats, conviction, rug_score))

    # Sort: conviction desc, vol_accel desc
    candidates.sort(key=lambda x: (x[2], x[1].get("vol_acceleration_15m", 0)), reverse=True)
    return candidates


async def check_exits(conn, portfolio: dict):
    """Run exit logic for all open positions of a portfolio."""
    positions = await conn.fetch(
        "SELECT * FROM pump_positions WHERE portfolio_id=$1 AND status='open'",
        portfolio["id"]
    )
    for pos in positions:
        pos = dict(pos)
        if pos.get("discovery_source") == "manual_buy":
            continue   # manual positions — skip auto-exit

        # Fetch fresh price
        current_price = await _fetch_current_price(pos["entry_pair_address"] or pos["token_address"])
        if not current_price:
            continue

        entry      = pos["entry_price"]
        peak       = pos.get("peak_price") or entry
        hold_min   = (datetime.now(timezone.utc) - pos["entry_time"]).total_seconds() / 60

        # Update peak
        if current_price > peak:
            peak = current_price
            await conn.execute("UPDATE pump_positions SET peak_price=$1 WHERE id=$2", peak, pos["id"])

        cur_ret  = (current_price - entry) / entry * 100
        peak_ret = (peak - entry) / entry * 100

        sl  = portfolio.get("stop_loss_pct", STOP_LOSS_PCT)
        tp  = portfolio.get("take_profit_pct", TAKE_PROFIT_PCT)
        tex = portfolio.get("time_exit_minutes", TIME_EXIT_MINUTES)
        ts_start = portfolio.get("trail_start_pct", TRAIL_START_PCT)
        ts_dist  = portfolio.get("trail_start_distance", TRAIL_START_DIST)
        te_pct   = portfolio.get("trail_end_pct", TRAIL_END_PCT)
        te_dist  = portfolio.get("trail_end_distance", TRAIL_END_DIST)

        exit_reason = None

        # 1. Stop loss
        if cur_ret <= sl:
            exit_reason = "stop_loss"

        # 2. Trailing stop
        elif peak_ret >= ts_start:
            if peak_ret <= te_pct:
                # Linear tighten ts_dist -> te_dist
                frac = (peak_ret - ts_start) / (te_pct - ts_start)
                trail_dist = ts_dist - frac * (ts_dist - te_dist)
            else:
                trail_dist = te_dist
            if cur_ret <= peak_ret - trail_dist:
                exit_reason = "trailing_stop"

        # 3. Take profit
        elif cur_ret >= tp:
            exit_reason = "take_profit"

        # 4. Time exit
        elif hold_min >= tex:
            exit_reason = "time_exit"

        if exit_reason:
            await execute_exit(conn, pos, portfolio, current_price, exit_reason)


async def execute_exit(conn, pos: dict, portfolio: dict, price: float, reason: str):
    now     = datetime.now(timezone.utc)
    pnl     = (price - pos["entry_price"]) * pos["qty"]
    ret_pct = (price - pos["entry_price"]) / pos["entry_price"] * 100
    hold_m  = (now - pos["entry_time"]).total_seconds() / 60

    if portfolio["mode"] == "live":
        # TODO: call live_executor.execute_sell()
        pass

    await conn.execute("""
        UPDATE pump_positions SET
            status='closed', exit_price=$1, exit_time=$2,
            realized_pnl=$3, return_pct=$4, hold_minutes=$5, exit_reason=$6
        WHERE id=$7
    """, price, now, pnl, ret_pct, hold_m, reason, pos["id"])

    await conn.execute("""
        UPDATE pump_bot_portfolio
        SET cash_balance = cash_balance + $1
        WHERE id = $2
    """, pos["position_usd"] + pnl, portfolio["id"])

    # Set cooldown
    cd_min = COOLDOWN_MINUTES.get(reason, COOLDOWN_MINUTES["default"])
    cd_until = now + timedelta(minutes=cd_min)
    await conn.execute("""
        INSERT INTO pump_cooldowns (token_address, cooldown_until)
        VALUES ($1, $2)
        ON CONFLICT (token_address) DO UPDATE SET cooldown_until = EXCLUDED.cooldown_until
    """, pos["token_address"], cd_until)

    print(f"[exit] {pos['token_address'][:8]} {reason} ret={ret_pct:.1f}% pnl=${pnl:.2f}")


async def _fetch_current_price(pair_or_addr: str) -> float | None:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                f"https://api.dexscreener.com/latest/dex/pairs/solana/{pair_or_addr}"
            )
            r.raise_for_status()
            pairs = r.json().get("pairs") or []
            if pairs:
                return float(pairs[0].get("priceUsd", 0) or 0)
    except:
        pass
    return None
```

---

## 11. bot.py — Main Loop

```python
"""
pump_bot/bot.py
Entry point: python -m pump_bot.bot
Long-running loop, 1 tick per 60 seconds.
"""
import asyncio, asyncpg, time, os, signal
from datetime import datetime, timezone

from pump_bot.config import (POLL_INTERVAL_SEC, WATCHLIST_REFRESH_MIN,
                              DATABASE_URL, WATCHLIST_MAX_TOKENS)
from pump_bot.watchlist  import refresh_watchlist
from pump_bot.collector  import fetch_snapshots
from pump_bot.features   import compute_features
from pump_bot.conviction import compute_conviction
from pump_bot.rug_risk   import compute_rug_risk
from pump_bot.trader     import filter_and_rank_entries, check_exits
from pump_bot.macro      import refresh_macro

_running = True

def _shutdown(sig, frame):
    global _running
    print("[bot] Shutting down...")
    _running = False

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)


async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    last_watchlist_refresh = 0
    last_macro_refresh     = 0

    while _running:
        tick_start = time.time()
        print(f"\n[tick] {datetime.now(timezone.utc).isoformat()}")

        try:
            # 1. Refresh watchlist every 5 min
            if time.time() - last_watchlist_refresh >= WATCHLIST_REFRESH_MIN * 60:
                print("[tick] Refreshing watchlist...")
                await refresh_watchlist(conn)
                last_watchlist_refresh = time.time()

            # 2. Get active watchlist addresses + open position addresses
            watchlist = await conn.fetch(
                "SELECT token_address, pair_address FROM pump_watchlist WHERE is_active = TRUE"
            )
            open_pos = await conn.fetch(
                "SELECT DISTINCT token_address, entry_pair_address FROM pump_positions WHERE status='open'"
            )
            all_addrs = list({r["token_address"] for r in watchlist} |
                             {r["token_address"] for r in open_pos})

            # 3. Fetch & store snapshots
            print(f"[tick] Snapshotting {len(all_addrs)} tokens...")
            snapshots = await fetch_snapshots(conn, all_addrs)

            # 4. Check exits on open positions
            portfolios = await conn.fetch(
                "SELECT * FROM pump_bot_portfolio WHERE is_active = TRUE"
            )
            for portfolio in portfolios:
                await check_exits(conn, dict(portfolio))

            # 5. Refresh macro (every 15 min is sufficient — free API)
            if time.time() - last_macro_refresh >= 900:
                await refresh_macro()
                last_macro_refresh = time.time()

            # 6. Compute features for all watchlist tokens
            features_map = {}
            for addr in [r["token_address"] for r in watchlist]:
                snap = snapshots.get(addr)
                if snap:
                    feats = await compute_features(conn, addr, snap)
                    features_map[addr] = feats

            # 7. Filter & rank entry candidates
            candidates = await filter_and_rank_entries(conn, snapshots, features_map)
            print(f"[tick] {len(candidates)} entry candidates")

            # 8. Execute entries per portfolio
            for portfolio in portfolios:
                p = dict(portfolio)
                await _execute_entries_for_portfolio(conn, candidates, p, snapshots)

            # 9. Update model scores table (for UI)
            for addr, feats in features_map.items():
                if feats:
                    conv = feats.get("_conviction", compute_conviction(feats))
                    rug  = feats.get("_rug_risk", 0)
                    await conn.execute("""
                        INSERT INTO pump_model_scores (token_address, prob_win, conviction_score, rug_risk_score, updated_at)
                        VALUES ($1, $2, $3, $4, NOW())
                        ON CONFLICT (token_address) DO UPDATE SET
                            prob_win=EXCLUDED.prob_win, conviction_score=EXCLUDED.conviction_score,
                            rug_risk_score=EXCLUDED.rug_risk_score, updated_at=NOW()
                    """, addr, conv / 100, conv, rug)

            # 10. Cleanup old snapshots
            await conn.execute(
                "DELETE FROM pump_token_snapshots WHERE snapshot_time < NOW() - INTERVAL '45 days'"
            )

        except Exception as e:
            print(f"[tick] ERROR: {e}")
            import traceback; traceback.print_exc()

        # Sleep remainder of 60s
        elapsed = time.time() - tick_start
        sleep_s = max(0, POLL_INTERVAL_SEC - elapsed)
        print(f"[tick] Done in {elapsed:.1f}s. Sleeping {sleep_s:.1f}s...")
        await asyncio.sleep(sleep_s)

    await conn.close()
    print("[bot] Stopped cleanly.")


async def _execute_entries_for_portfolio(conn, candidates, portfolio, snapshots):
    open_cnt = await conn.fetchval(
        "SELECT COUNT(*) FROM pump_positions WHERE portfolio_id=$1 AND status='open'",
        portfolio["id"]
    )
    slots = portfolio["max_open_positions"] - open_cnt
    if slots <= 0:
        return

    floor = portfolio.get("conviction_floor", 20)
    executed = 0

    for addr, feats, conviction, rug_score in candidates:
        if executed >= slots:
            break
        if conviction < floor:
            continue

        # Re-check cooldown per portfolio (already checked in filter, but safety)
        price = snapshots.get(addr, {}).get("price_usd", 0)
        if not price:
            continue

        position_usd = portfolio.get("position_size", 50)
        qty          = position_usd / price

        # Check cash
        cash = await conn.fetchval(
            "SELECT cash_balance FROM pump_bot_portfolio WHERE id=$1", portfolio["id"]
        )
        if (cash or 0) < position_usd:
            print(f"[entry] portfolio {portfolio['id']} — insufficient cash")
            break

        snap = snapshots.get(addr, {})
        await conn.execute("""
            INSERT INTO pump_positions
                (portfolio_id, token_address, symbol, entry_price, qty, position_usd,
                 peak_price, conviction_score, rug_risk_score,
                 entry_dex_id, entry_pair_address, discovery_source, status)
            VALUES ($1,$2,$3,$4,$5,$6,$6,$7,$8,$9,$10,$11,'open')
        """, portfolio["id"], addr,
             snap.get("symbol", addr[:8]),
             price, qty, position_usd,
             conviction, rug_score,
             snap.get("dex_id", ""), snap.get("pair_address", ""),
             snap.get("_source", "watchlist"))

        await conn.execute(
            "UPDATE pump_bot_portfolio SET cash_balance = cash_balance - $1 WHERE id = $2",
            position_usd, portfolio["id"]
        )

        print(f"[entry] portfolio={portfolio['id']} mode={portfolio['mode']} "
              f"addr={addr[:8]} price=${price:.6f} conviction={conviction:.0f}")
        executed += 1


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 12. live_executor.py — Jupiter Swap (Live Mode)

```python
"""
pump_bot/live_executor.py
Real on-chain swaps via Jupiter (free, no key).
Only called when portfolio.mode == 'live'.
"""
import httpx, base64, asyncio
from cryptography.fernet import Fernet
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from pump_bot.config import JUPITER_QUOTE_URL, JUPITER_SWAP_URL, SOLANA_RPC_URL

# SOL mint
WSOL_MINT = "So11111111111111111111111111111111111111112"


def _decrypt_key(encrypted_key: str, fernet_key: str) -> Keypair:
    f = Fernet(fernet_key.encode())
    pk_bytes = f.decrypt(encrypted_key.encode())
    return Keypair.from_bytes(pk_bytes)


async def execute_buy(wallet_enc_key: str, fernet_key: str,
                      token_mint: str, usd_amount: float, sol_price: float) -> dict:
    keypair = _decrypt_key(wallet_enc_key, fernet_key)
    lamports = int((usd_amount / sol_price) * 1e9)

    async with httpx.AsyncClient(timeout=20) as client:
        # 1. Get quote
        r = await client.get(JUPITER_QUOTE_URL, params={
            "inputMint":  WSOL_MINT,
            "outputMint": token_mint,
            "amount":     lamports,
            "slippageBps":500    # 5%
        })
        quote = r.json()
        if "error" in quote:
            raise ValueError(f"Jupiter quote error: {quote['error']}")

        # Check price impact
        impact = float(quote.get("priceImpactPct", 0))
        if impact > 5:
            raise ValueError(f"Price impact too high: {impact:.1f}%")

        # 2. Get swap transaction
        r2 = await client.post(JUPITER_SWAP_URL, json={
            "quoteResponse":    quote,
            "userPublicKey":    str(keypair.pubkey()),
            "wrapAndUnwrapSol": True,
        })
        swap_data = r2.json()
        tx_b64 = swap_data.get("swapTransaction")
        if not tx_b64:
            raise ValueError("No swapTransaction in response")

        # 3. Sign & send
        tx_bytes = base64.b64decode(tx_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        tx.sign([keypair])

        r3 = await client.post(SOLANA_RPC_URL, json={
            "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
            "params": [base64.b64encode(bytes(tx)).decode(), {"encoding": "base64"}]
        })
        sig = r3.json().get("result")
        if not sig:
            raise ValueError(f"Send failed: {r3.json()}")

        # 4. Poll for confirmation (30s max)
        for _ in range(30):
            await asyncio.sleep(1)
            conf = await client.post(SOLANA_RPC_URL, json={
                "jsonrpc": "2.0", "id": 1,
                "method": "getSignatureStatuses",
                "params": [[sig]]
            })
            statuses = conf.json().get("result", {}).get("value", [None])
            st = statuses[0] if statuses else None
            if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                return {"tx_hash": sig, "confirmed": True}

        return {"tx_hash": sig, "confirmed": False}
```

---

## 13. circuit_breaker.py

```python
"""
pump_bot/circuit_breaker.py
Trips when drawdown from peak PnL exceeds cb_max_drawdown %.
"""

async def check_circuit_breaker(conn, portfolio: dict) -> bool:
    """Returns True if trading should be HALTED."""
    if not portfolio.get("cb_enabled", True):
        return False

    result = await conn.fetchrow("""
        SELECT
            SUM(realized_pnl)                           as total_pnl,
            MAX(SUM(realized_pnl)) OVER ()              as peak_pnl
        FROM pump_positions
        WHERE portfolio_id = $1 AND status = 'closed'
    """, portfolio["id"])

    if not result or result["total_pnl"] is None:
        return False

    peak_pnl  = result.get("peak_pnl") or 0
    total_pnl = result["total_pnl"] or 0

    if peak_pnl > 0:
        drawdown = (peak_pnl - total_pnl) / peak_pnl * 100
        if drawdown >= portfolio.get("cb_max_drawdown", 20):
            print(f"[circuit_breaker] TRIPPED portfolio={portfolio['id']} drawdown={drawdown:.1f}%")
            await conn.execute(
                "UPDATE pump_bot_portfolio SET is_active=FALSE WHERE id=$1",
                portfolio["id"]
            )
            return True
    return False
```

---

## 14. FastAPI Router (Backend API)

```python
# api/pump_bot_router.py
from fastapi import APIRouter, Depends
import asyncpg

router = APIRouter(prefix="/pump-bot", tags=["pump-bot"])

# GET /pump-bot/status
@router.get("/status")
async def get_status(conn=Depends(get_db)):
    portfolios = await conn.fetch("SELECT * FROM pump_bot_portfolio")
    return {"portfolios": [dict(p) for p in portfolios]}

# GET /pump-bot/positions
@router.get("/positions")
async def get_positions(status: str = "open", limit: int = 100, conn=Depends(get_db)):
    rows = await conn.fetch(
        "SELECT * FROM pump_positions WHERE status=$1 ORDER BY entry_time DESC LIMIT $2",
        status, limit
    )
    return [dict(r) for r in rows]

# GET /pump-bot/watchlist
@router.get("/watchlist")
async def get_watchlist(conn=Depends(get_db)):
    rows = await conn.fetch("""
        SELECT w.*, m.prob_win, m.conviction_score, m.rug_risk_score
        FROM pump_watchlist w
        LEFT JOIN pump_model_scores m ON w.token_address = m.token_address
        WHERE w.is_active = TRUE
        ORDER BY m.conviction_score DESC NULLS LAST
    """)
    return [dict(r) for r in rows]

# GET /pump-bot/chart-pnl
@router.get("/chart-pnl")
async def get_chart_pnl(portfolio_id: int, conn=Depends(get_db)):
    rows = await conn.fetch("""
        SELECT exit_time as ts, SUM(realized_pnl) OVER (ORDER BY exit_time) as cum_pnl
        FROM pump_positions
        WHERE portfolio_id=$1 AND status='closed' AND exit_time IS NOT NULL
        ORDER BY exit_time
    """, portfolio_id)
    return [dict(r) for r in rows]

# PUT /pump-bot/portfolio/{id}
@router.put("/portfolio/{portfolio_id}")
async def update_portfolio(portfolio_id: int, body: dict, conn=Depends(get_db)):
    allowed = ["position_size","max_open_positions","stop_loss_pct","take_profit_pct",
               "time_exit_minutes","trail_start_pct","trail_start_distance",
               "trail_end_pct","trail_end_distance","conviction_floor",
               "min_buy_pressure","is_active","cb_enabled","cb_max_drawdown"]
    sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(k for k in body if k in allowed))
    vals = [body[k] for k in body if k in allowed]
    if sets:
        await conn.execute(f"UPDATE pump_bot_portfolio SET {sets}, updated_at=NOW() WHERE id=$1",
                           portfolio_id, *vals)
    return {"ok": True}

# POST /pump-bot/manual-buy
@router.post("/manual-buy")
async def manual_buy(body: dict, conn=Depends(get_db)):
    # calls same execute_entry logic from trader.py with discovery_source='manual_buy'
    pass

# POST /pump-bot/manual-sell
@router.post("/manual-sell")
async def manual_sell(body: dict, conn=Depends(get_db)):
    # calls execute_exit from trader.py
    pass
```

---

## 15. Docker Setup

```yaml
# docker-compose.yml (add to existing)
services:
  pump_bot:
    build: .
    command: ["python", "-m", "pump_bot.bot"]
    restart: unless-stopped
    stop_grace_period: 90s
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - WALLET_ENCRYPTION_KEY=${WALLET_ENCRYPTION_KEY}
    depends_on:
      - postgres
```

```dockerfile
# Add to existing Dockerfile or create pump_bot/Dockerfile
RUN pip install asyncpg httpx cryptography solders xgboost lightgbm scikit-learn
```

---

## 16. Dependencies

```txt
# requirements additions for pump_bot
asyncpg>=0.29
httpx>=0.27
cryptography>=42.0
solders>=0.21         # Solana keypair/transaction (live mode only)
```

---

## 17. Implementation Order for Claude Code

Implement in this exact order — each step is testable before the next:

1. **DB schema** — Run all CREATE TABLE statements. Seed one `pump_bot_portfolio` row (mode='sim', cash_balance=1000).
2. **config.py** — All constants, no logic.
3. **macro.py** — Test: `asyncio.run(refresh_macro())` should return fear_greed + sol_price.
4. **watchlist.py** — Test: run `refresh_watchlist(conn)`, verify rows in `pump_watchlist`.
5. **collector.py** — Test: call `fetch_snapshots(conn, addresses)`, verify rows in `pump_token_snapshots`.
6. **features.py** — Test: after a few snapshot ticks, `compute_features()` should return a dict.
7. **conviction.py** — Test: pass a sample features dict, verify score 0–100.
8. **rug_risk.py** — Test with a known pump address; confirm public RPC calls work.
9. **trader.py** — Test `filter_and_rank_entries` with mock features; test exit logic in sim.
10. **bot.py** — Run the full loop in sim mode for 10 minutes; verify positions open and close.
11. **api/pump_bot_router.py** — Wire up FastAPI endpoints; test via curl.
12. **live_executor.py** — Only after sim is stable; test with tiny amount first.
13. **Frontend** — Dashboard page last (reads from same DB the bot fills).

---

## 18. What Was Removed (Paid) & Free Replacements

| Original | Paid? | Replaced With |
|----------|-------|---------------|
| CoinGecko Pro trending pools | ✅ Paid | DexScreener boost endpoints (free) |
| CoinGecko Pro new pools | ✅ Paid | DexScreener profile endpoint (free) |
| CoinGecko macro (BTC price) | ❌ Free tier only | Dropped — Fear&Greed + SOL price sufficient |
| Helius RPC (whale detection) | ✅ Paid | Removed — conviction works without it |
| Helius mint/freeze check | ✅ Paid | Public Solana RPC `getAccountInfo` (free) |
| Helius holder concentration | ✅ Paid | Public RPC `getTokenLargestAccounts` (free) |
| twitterapi.io (tweets/KOL) | ✅ Paid | Removed — conviction still covers 8 signals |
| Helius enhanced txns (whale) | ✅ Paid | Removed in v1 — add later with free Solana RPC |

**Conviction score v1 (without whale/tweet signals): max ~75 pts (plenty for the 20-pt floor).**

---

## 19. Notes & Caveats

- **Public Solana RPC rate limits**: `api.mainnet-beta.solana.com` allows ~100 req/s but can be flaky. For production add a fallback: `https://solana-rpc.publicnode.com`.
- **DexScreener rate limits**: No official published limit. Add `await asyncio.sleep(0.5)` between batch calls. If you hit 429s, increase to 1s.
- **ML gate**: Set `model_gate_enabled = FALSE` until you have ≥2 weeks of snapshots. The system works with conviction-only scoring.
- **Live mode**: Only enable after running sim for ≥1 week and reviewing trade history. Start with `position_size = $5`.
- **Sim vs Live portfolios**: Insert two rows into `pump_bot_portfolio` — one `mode='sim'`, one `mode='live'`. The bot handles both in parallel.
- **Token address filter**: All pump.fun tokens end in `"pump"` — this is the cheapest possible filter and never misses valid targets.
