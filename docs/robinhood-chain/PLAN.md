# Robinhood Chain Discovery & Paper-Trading System — Phase 0 Plan

**Status:** Phase 0 (research, audit, plan). No feature code has been written. Awaiting approval before Phase 1.
**Branch:** `new-feature` · **Probe date:** 2026-11-07 (UTC) · **Chain head at probe:** block ~108,450,000

Conventions in this document:
- **[VERIFIED]** means measured by a probe on 2026-11-07. The scripts are in [`probes/`](probes/) and can be re-run.
- **[NEEDS VERIFICATION]** means not confirmed: an assumption, a vendor's documentation, or something that couldn't be probed.
- Nothing here claims any strategy is profitable. Phase 0 makes no performance claims at all.

---

## Summary: what the probes changed versus the brief

| Brief assumption | What the probe found | Consequence |
|---|---|---|
| "WebSocket subscriptions where supported" | Public RPC has **no WebSocket** (`eth_subscribe` → "notifications not supported"; `wss://` endpoints fail) [VERIFIED] | Indexer uses HTTP `eth_getLogs` polling. With ~0.1 s blocks, a 1–2 s poll interval is fine for 1m/5m strategies. |
| "Archive vs. pruned state" | **Pruned.** Historical state is available only about 1,000 blocks (≈100 s) back. 10,000 blocks back fails [VERIFIED] | `eth_call` at past blocks is impossible, so backtests **cannot** re-quote historical pools. Historical prices and liquidity must come from event data (Swap/Sync/ModifyLiquidity). |
| Logs history | **Logs are retained** at least 108 days back, across the whole active life of the chain [VERIFIED] | Full event backfill from the RPC is possible, which is the main reason this plan is viable on free data. |
| `eth_getLogs` range limits | No block-range limit was hit. The cap is **10,000 logs per response** [VERIFIED] | Adaptive chunking by log count, not by a fixed block range. |
| Blockscout API as a source | **HTTP 403 (Cloudflare challenge)** for scripted access [VERIFIED] | Not usable as an automated source. Manual verification only, unless Blockscout issues API access. |
| Algebra pools | **No Algebra `Pool` creation events** in the last 24 h [VERIFIED for that signature] | Algebra decoder deprioritized. Other concentrated-liquidity forks (Ramses, Aero Slipstream, Pancake v3) are present and need checking. |
| Launchpads: Pons, Flap, hood.fun, Bankr, Openfair, noxa | GeckoTerminal lists **52 DEX/launchpad venues** on chain `robinhood`, including Pons V1/V2, Bankr, Clanker, Virtuals, Flap (DexScreener `flapsh`), Hoodit, Frontier.fun, o1 Launchpad and others [VERIFIED list] | Coverage must be prioritized by measured volume. A decoder for every venue isn't realistic. hood.fun, Openfair and noxa were **not** seen by name [NEEDS VERIFICATION]. |

---

## A. Repo audit

### A.1 Structure
- **Backend:** flat Python modules in `backend/` (no packages), FastAPI 0.115, SQLAlchemy 2.0, Python 3.11 in CI.
- **Frontend:** Next.js 16 App Router in `frontend/app/`, Tailwind v4, `lightweight-charts` v5, `lucide-react`.
- **Deployment:**
  - Backend: GitHub Actions → Azure App Service `Bushutrading` on push to `main` (`.github/workflows/main_bushutrading.yml`).
  - Frontend: Azure Static Web Apps, also on push to `main`.
  - Database: Supabase Postgres (`DATABASE_URL`, pooler host `aws-1-ap-south-1.pooler.supabase.com`).
- **No startup command is in the repo** (no `startup.sh` or Procfile). It's set in the Azure portal [NEEDS VERIFICATION: command and worker count].

### A.2 Database and migrations
- `backend/database.py`:
  - Single `engine = create_engine(DATABASE_URL)` with default pool settings (no `pool_pre_ping`).
  - Shared `SessionLocal` and a single shared `Base`.
  - The import fails if `DATABASE_URL` is unset.
- All models are in `backend/models.py`. Primary keys are Postgres `UUID(as_uuid=True)`, timestamps are naive UTC (`datetime.utcnow()`), and there are no foreign keys.
- **No Alembic.**
  - Each module has an `ensure_initialized()` that runs `Base.metadata.create_all(checkfirst=True)` plus raw `ALTER TABLE … ADD COLUMN IF NOT EXISTS`.
  - Because `Base` is shared, the **first** `create_all` (from `paper_engine`, which has **no try/except**) creates every table.

> **Design consequence:** a broken new model on the shared `Base` could abort `paper_engine.ensure_initialized()`, and with it the whole production startup. **New tables will use a separate declarative base (`RhcBase`) with their own guarded `create_all`**, so they can never break existing startup.

### A.3 Background jobs and scheduler
- `main.py` lifespan starts:
  - `ensure_initialized()` calls, most of them unguarded;
  - the Robinhood desk monitor thread (`robinhood_manual.monitor()` every 6 s while `trader.config.is_running`);
  - the trader thread, the copytrade thread (guarded) and the liquidity thread;
  - an APScheduler `AsyncIOScheduler` (data collector hourly, pivots on cron).
- Loop pattern (`copytrade_loop.py`): module-level `_running` flag, `stop()`, try/except around each tick, sleep in 1 s steps.
- **Every module is imported at the top of `main.py`.** An import-time error in any new module stops the backend from booting.
- Multiple Uvicorn/Gunicorn workers would duplicate every thread [NEEDS VERIFICATION: worker count on Azure].

### A.4 Config, auth, frontend-to-backend
- **Config:** per-feature `*_config.py` modules read env at import time (`_flag(name, default)` helper; two-switch live-money convention `*_LIVE` + `*_LIVE_DRYRUN`). There is no `.env.example` in the repo.
- **Auth:**
  - A global HTTP middleware in `main.py` requires `Authorization: Bearer <JWT>` for all `/api/*` paths.
  - Exempt paths: `/api/login`, two webhook paths, and **any path starting with `/api/liquidity`** (prefix match).
  - New routes will live under `/api/rhc/*`, which are protected automatically.
- **Frontend:**
  - `frontend/lib/config.ts` → `API_URL`.
  - `AuthProvider.tsx` monkey-patches `fetch` to add the bearer token.
  - Components call raw `fetch` and poll with `setInterval`.
  - Nav is the static `navItems` array in `frontend/app/components/Sidebar.tsx`.
  - Pages are thin wrappers that render a `"use client"` component from `app/components/`.

### A.5 Existing manual Robinhood Chain desk (must not change)

| Piece | File | Role |
|---|---|---|
| Config | `backend/robinhood_config.py` | `ROBINHOOD_ENABLED` (default true), `ROBINHOOD_LIVE_ENABLED` (false), `ROBINHOOD_LIVE_DRYRUN` (true), RPC URL, chain ID 4663, `ROBINHOOD_PRIVATE_KEY`, `ROBINHOOD_EXPECTED_WALLET`, limits |
| Wallet | `backend/robinhood_wallet.py` | Lazy `eth_account` key load; `_rpc()` over HTTP; balance/decimals/`balanceOf`; sign + `eth_sendRawTransaction`; receipt polling |
| Execution | `backend/robinhood_live.py` | `get_token_market_info()` (DexScreener); `execute_buy(token, usd)` / `execute_sell(token, qty)`; **routing via the Relay API** (`api.relay.link/quote`, verified to support chain 4663); gas = max(gasPrice, baseFee) × 1.4; `eth_estimateGas` × 1.25 |
| Desk logic | `backend/robinhood_manual.py` | `robinhood_position` table; market/limit buys; TP/SL monitor; tiered scale-in |
| API | `backend/robinhood_api.py` | `/api/robinhood/{buy,status,stats,token,positions,positions/{id}/sell,positions/{id}/targets}` |
| UI | `frontend/app/components/RobinhoodTradePanel.tsx` | Rendered inside `CopyTradeDashboard.tsx` via the "Robinhood Trade" toggle |

Observations that affect reuse. These are facts about the current code; this plan won't change it.
1. **There is no slippage protection in our code path.** `ROBINHOOD_MAX_SLIPPAGE_BPS` and `ROBINHOOD_MAX_PRICE_IMPACT_PCT` are defined but **never used**. Relay's quote defaults govern slippage.
2. **The desk's paper fills are optimistic.** Paper and dry-run fill at the DexScreener spot price, with zero fees, zero slippage and zero latency. The new system won't reuse that fill logic.
3. **The live switch is global.** `execute_buy` goes live whenever `ROBINHOOD_LIVE_ENABLED=true and ROBINHOOD_LIVE_DRYRUN=false`, using the **same** wallet as the manual desk.

**Reuse plan, with no behavior or interface change to any existing file:**
- **Read-only reuse:**
  - `robinhood_live.get_relay_swap_quote()` (a pure HTTP call) for executable quotes in forward paper trading;
  - `robinhood_live.get_eth_price_usd()`;
  - `robinhood_wallet._rpc`-style calls go through **our own** RPC client, so the desk's code path isn't touched.
- **LiveBroker (Phase 4):**
  - A wrapper class that *would* call `robinhood_live.execute_buy/execute_sell`. It's hard-disabled: it raises unless `RHC_LIVE_ENABLED=true` and further checks pass.
  - Because the existing functions use the desk's global switches and wallet, the brief's dedicated low-balance wallet can't be had without changing `robinhood_wallet`. **I will not do that in this task.** The LiveBroker stays a disabled adapter, and the dedicated-wallet wiring becomes a separate, explicitly approved change.
- **The only edits to existing files:**
  - `main.py`: one guarded, flag-gated import/start block and `include_router`;
  - `Sidebar.tsx`: one nav entry;
  - `requirements.txt`: only if a new dependency is truly needed (none are expected).

---

## B. Live data-source probe [VERIFIED 2026-11-07 unless marked]

### B.1 Robinhood Chain RPC (`https://rpc.mainnet.chain.robinhood.com`)

| Property | Result |
|---|---|
| Chain ID | 4663 |
| Client | Arbitrum Nitro v3.12.3-rc.4 |
| Block time | **0.104 s** average over the last 2,000 blocks (~830k blocks/day) |
| Genesis | Block 1 at 2026-04-30. The earliest DEX pools on GeckoTerminal date from about 2026-06-29. |
| Latency (from this machine, Pakistan) | p50 377 ms, max 490 ms. Azure Central India will differ [NEEDS VERIFICATION]. |
| Rate limit | 60 sequential calls in 22.8 s, all HTTP 200, no rate-limit headers. The real limit is unknown [NEEDS VERIFICATION under sustained load]. |
| `eth_getLogs` | Cap of 10,000 logs per response. 1,000 blocks unfiltered = 10,313 logs (over the cap). Filtered queries over 864k blocks (24 h) succeed. |
| Log history | Present at 6, 24, 60 and 108 days back |
| State history | **Pruned**, roughly 1,000 blocks (~100 s) |
| `eth_call` | Works at `latest`; **state override works** (needed for honeypot simulation) |
| `debug_*` / `trace_*` | Not available |
| WebSocket | Not available |

**Activity measured over 5,000 blocks (~8.7 min):**
- ~42 Transfer logs/s;
- ~9.5 Uniswap v4 Swaps/s, all from the PoolManager `0x8366a39cc670b4001a1121b8f6a443a643e40951`;
- ~3 v3-style Swaps/s across 215 pools.

Extrapolated, that's about **1.1 million swaps per day** — a major storage constraint (see D.4).

### B.2 Comparison table

| Source | Chain 4663? | Provides | Limits (measured / documented) | History | Gaps |
|---|---|---|---|---|---|
| **Own RPC indexer** | Yes | Every decoded event: pools, swaps (price + liquidity in v3/v4), liquidity changes, transfers | See B.1 | Full logs since genesis; state ~100 s | No historical `eth_call`; single public endpoint is a single point of failure |
| **DexScreener** | Yes (`robinhood`) | Pair price/liquidity/volume, `dexId` labels, token profiles and boosts | 40 rapid calls, all HTTP 200. Documented ~300/min for pair endpoints [NEEDS VERIFICATION] | Current snapshot only; no OHLCV API | Many fresh pools are missing (≈50% of sampled new pools returned "not found") |
| **GeckoTerminal** | Yes (`robinhood`) | 52 venues, new pools, top pools, OHLCV (1m/5m/…), last 300 trades | **HTTP 429 after ~15 rapid calls**; ~1 call/2.5 s worked. Documented free ~30/min [NEEDS VERIFICATION] | 1,000 candles per call (1m ≈ 17 h, 5m ≈ 3.5 days). Deeper paging (`before_timestamp`) untested because of the 429. | Only indexed pools; tight rate limit |
| **Blockscout** | Unknown (blocked) | Would give verified source, holders, token list | **HTTP 403 Cloudflare challenge** to scripted requests | — | Not usable automatically |
| **DefiLlama** | Yes ("Robinhood Chain", 4663) | Chain TVL (~$1.09 B), chain DEX volume (24 h ~$715 M), per-protocol volume | No issues at low volume | Daily granularity | Too coarse for trading. Useful only for the regime context. |
| **Relay** | Yes (chain 4663) | Executable swap quotes (already used by the desk) | Unknown [NEEDS VERIFICATION] | Live only | Quote-only for us; rate limits unknown |
| **Bitquery** | Untested | Reportedly trades, holders, reserves | HTTP 401 without a key | — | Needs an API key from you |
| **StalkChain** | Untested | — | — | — | Needs a key or docs |

### B.3 Recommended source hierarchy
1. **Primary: our own RPC indexer**, for pool discovery, swaps, candles, flow, liquidity events, holders (replayed from Transfer logs per token) and wallet behaviour. It's the only source that is complete, free of survivorship bias and has no third-party rate limit.
2. **Enrichment and cross-check: DexScreener**, for venue labels, USD liquidity sanity checks and metadata, with a cache of at least 60 s.
3. **Backfill and second opinion: GeckoTerminal**, for OHLCV around the time our indexer started and for price cross-checks, strictly paced (≤ 20 calls/min, token-bucket).
4. **Execution-realism quotes: Relay** quotes, plus `eth_call` against on-chain quoters at `latest`, for forward paper fills only.
5. **Regime context: DefiLlama**, polled daily.
6. **Optional, if you supply keys:**
   - a second RPC provider (strongly recommended for failover) [NEEDS VERIFICATION: which providers support chain 4663];
   - Bitquery;
   - a CoinGecko Demo/Pro key.

---

## C. Chain protocol map [VERIFIED by event counts unless marked]

### C.1 Quote assets
| Asset | Address | Evidence |
|---|---|---|
| Native ETH (v4 `currency0 = 0x0`) | — | 2,051 of 3,972 v4 pools created in the last 24 h |
| WETH | `0x0bd7d308f8e1639fab988df18a8011f41eacad73` | Top quote in v2 (1,708/1,723 pairs) and v3 (217/237) |
| USDG | `0x5fc5360d0400a0fd4f2af552add042d716f1d168` | 385 v4 pools/24 h; the main stable quote asset |
| Others seen as `currency0` | SPCX, AMC, TTWO, GOO, VIRTUAL, DAI, HOOD | Tokenized-equity and ecosystem tokens; treat as non-standard quote assets |

USD reference price: the WETH/USDG pools (Uniswap v3 0.01% `0x52e65b17…`, ~$10 M liquidity; Aero Slipstream `0x76159260…`).

### C.2 Pool creation by venue (last 24 h)
| Venue | Contract | Type | Pools/24 h | Identification |
|---|---|---|---|---|
| Uniswap v4 PoolManager | `0x8366a39cc670b4001a1121b8f6a443a643e40951` | Singleton v4, `Initialize` / `Swap` / `ModifyLiquidity` | 3,972 | VERIFIED (all v4 events come from this contract) |
| — no hook | hooks = `0x0` | Plain v4 | ~1,860/24 h (621 per 8 h) | DexScreener `uniswap v4` |
| — hook `0x4e3468951d49f2eea976ed0d6e75ffcb44a9a544` | | **Launchpad-style hook**; 497 pools per 8 h, **none on DexScreener** | ~1,500/24 h | **Unidentified [NEEDS VERIFICATION]**. Likely a launchpad bonding-curve hook (candidates: Pons V2, Bankr, Clanker). |
| — hook `0x2c668601…2acc`, `0x15e5e720…a8cc`, `0x0af57f62…28ec`, `0x4eb19769…e0cc` | | Smaller hook families | 5–61 per 8 h | DexScreener labels them `uniswap v4`; the hook owner is unknown |
| Uniswap v2-style factory | `0x8bceaa40b9acdfaedf85adf4ff01f5ad6517937f` | v2 | 990 | DexScreener `uniswap v2` |
| Flap (v2-style) | `0x0d1ebb179cdbca88d74c923c4255cb2b17474afd` | v2 graduation target | 711 | DexScreener `flapsh` (1 of 3 samples); 2 samples not indexed |
| PancakeSwap v2 | `0x02a84c1b3bbd7401a5f7fa98a384ebc70bb5749e` | v2 | 6 | DexScreener `pancakeswap v2` |
| Uniswap v3 factory | `0x1f7d7550b1b028f7571e69a784071f0205fd2efa` | v3 | 222 | DexScreener `uniswap v3` |
| Goo Exchange | `0x221a6239e40709792b0d4bdc140fa36158cd41c7` | v3-style | 9 | DexScreener `goo-exchange` |
| Aero Slipstream | e.g. pool `0x4857db57…`, symbol `AERO-CL` | CL (v3-style events) | — | Partially verified |
| Algebra | — | — | 0 `Pool` events | Not found |

Other relevant contracts seen: Permit2 `0x000000000022d473030f116ddee9f6b43ac78ba3`, ERC-4337 EntryPoint v0.7 `0x0000000071727de22e5e9d8baf0edac6f37da032` (smart-wallet traffic), price-feed contracts emitting `FeedUpdated` and `PriceRead`, and an intent/solver contract emitting `SolverCallExecuted`.

### C.3 Event signatures for the decoders
All hashes were recomputed with keccak256 from the canonical signatures [VERIFIED]. The v3/v4 Swap and ModifyLiquidity hashes also match the topics observed live.

| Event | topic0 |
|---|---|
| v2 `PairCreated` | `0x0d3648bd…28d0e9` |
| v2 `Swap` / `Sync` / `Mint` / `Burn` | `0xd78ad95f…59d822` / `0x1c411e9a…bbad1` / `0x4c209b5f…` / `0xdccd412f…` |
| v3 `PoolCreated` | `0x783cca1c…6b7118` |
| v3 `Swap` (sqrtPrice, liquidity, tick) | `0xc42079f9…fbcca67` |
| v3 `Mint` / `Burn` / `Collect` | `0x7a53080b…` / `0x0c396cd9…98982c` / `0x70935338…6ca9c0` |
| v4 `Initialize` (id, currency0/1, fee, tickSpacing, hooks) | `0xdd466e67…6d438` |
| v4 `Swap` (id, sender, amount0/1, sqrtPrice, liquidity, tick, fee) | `0x40e9cecb…d7112f` |
| v4 `ModifyLiquidity` | `0xf208f491…11d5ec` |
| ERC-20 `Transfer` | `0xddf252ad…3b3ef` |

### C.4 Launchpads and graduation
- **Confirmed by name** (GeckoTerminal venue list): Pons V1, Pons V2 and Pons V2 Dex, Bankr, Clanker, Virtuals, Hoodit, EasyA Kickstart, Mint Club, Frontier.fun, o1 Launchpad, Clank.trade, Long.xyz, Goo Exchange. Flap is confirmed through DexScreener (`flapsh`).
- **Graduation mechanics, factory addresses and bonding-curve contracts:** [NEEDS VERIFICATION per launchpad].
  - Blockscout (the normal way to read verified contracts) is blocked for scripts.
  - Phase 1 will identify these from on-chain patterns: which contract deploys tokens, what call precedes `Initialize`/`PairCreated`, and the hook address.
  - I'll confirm each one manually on the explorer in a browser.
- **Coverage priority** (by measured pool creation): v4 (plain + hook `0x4e34…`) → Uniswap v2 → Flap → Uniswap v3 → everything else. **The v4 + v2 + v3 decoders cover more than 95% of pool creations.** Pre-graduation bonding-curve trades on launchpad contracts are **out of scope for Phase 1**: each needs a bespoke decoder, and they are also the riskiest phase to trade.

---

## D. Architecture

### D.1 Module layout (new files only, prefix `rhc_`)

The repo uses flat modules, so we follow that rather than adding a package.

```
backend/
  rhc_config.py        # all thresholds/flags (env, defaults, documented)
  rhc_models.py        # RhcBase (separate declarative base) + tables
  rhc_db.py            # guarded ensure_initialized(); optional separate engine via RHC_DATABASE_URL
  rhc_rpc.py           # RPC client: retries, timeouts, health, failover list, adaptive log chunking
  rhc_decoders.py      # pure functions: v2/v3/v4/ERC20 log -> typed events (unit-tested)
  rhc_indexer.py       # poll loop, checkpoints, reorg check, backfill, gap detection
  rhc_candles.py       # pure: events -> 1m/5m OHLCV + flow features (idempotent upserts)
  rhc_sources.py       # DexScreener / GeckoTerminal / DefiLlama / Relay adapters, one interface, rate limits, cache, health
  rhc_registry.py      # token/pool registry, quote-asset normalisation to USD
  rhc_safety.py        # honeypot sim (eth_call + state override), bytecode/permission scan, holder concentration
  rhc_features.py      # point-in-time feature computation (strict as-of timestamps)
  rhc_strategies.py    # pluggable strategies -> Setup(entry, stop, targets, evidence)
  rhc_risk.py          # sizing, exposure caps, daily loss, cooldowns, kill switch
  rhc_broker.py        # Broker interface; PaperBroker (fill model); LiveBroker (disabled stub)
  rhc_fills.py         # pure fill/slippage/fee/latency model (unit-tested)
  rhc_engine.py        # decision loop: discover -> screen -> rank -> setup -> confirm -> size -> execute -> monitor -> exit -> record
  rhc_backtest.py      # event-replay backtester + walk-forward
  rhc_metrics.py       # metrics + bootstrap CIs, "insufficient sample" gating
  rhc_api.py           # APIRouter(prefix="/api/rhc")
  tests/test_rhc_*.py  # pure-logic tests, no DB/network (fixtures recorded from real logs)
frontend/app/robinhood-chain/page.tsx (+ layout.tsx for metadata)
frontend/app/components/rhc/*.tsx
docs/robinhood-chain/{PLAN,SETUP,ARCHITECTURE,OPERATIONS,GO_LIVE_CHECKLIST}.md
```

### D.2 Production-safety design (backend on Azure, DB on Supabase)
1. **Master flag `RHC_ENABLED`, default `false`.** Merging and deploying changes nothing in production until you set it in Azure App Settings.
2. **Separate sub-flags:** `RHC_INDEXER_ENABLED`, `RHC_ENGINE_ENABLED`, `RHC_LIVE_ENABLED` (default false; also hard-blocked in code during this project).
3. **Guarded wiring in `main.py`.** A single `try: import rhc_api … except Exception: log` block, plus a guarded start function in the lifespan. Any failure in RHC code logs and continues; it can never stop startup or existing threads.
4. **Isolated schema.** `RhcBase` is a separate declarative base with its own guarded `create_all`, all tables prefixed `rhc_`, and no ALTERs to existing tables.
5. **Separate database (DECIDED 2026-11-07).** All Robinhood Chain data goes to a **new, dedicated free database** set by `RHC_DATABASE_URL`, with its own engine (`pool_pre_ping=True`, small pool).
   - The existing production database (`DATABASE_URL`) keeps running unchanged, and RHC code **never writes to it**.
   - If `RHC_DATABASE_URL` is unset, RHC stays disabled. There is **no fallback** to the production database.
6. **Isolated HTTP sessions and timeouts.** No shared module-level state with the existing desk.
7. **CI and tests.** RHC tests are pure (no DB, no network) and run with `python -m pytest backend/tests`. I'll run them, plus an import smoke test (`python -c "import main"` with a dummy `DATABASE_URL`), on Python 3.11 compatibility before every commit.

### D.3 Process model
- **Option A (default, no new Azure resources):** RHC runs as daemon threads in the existing App Service process.
  - Threads: an indexer poll thread, a source-enrichment thread and an engine thread.
  - Each follows the `copytrade_loop` pattern: a `_running` flag, try/except per tick, and a `stop()` called at shutdown.
  - Risks: CPU/GIL contention with the API and other bots, a memory ceiling, and App Service restarts causing gaps. Gaps are backfilled automatically from the checkpoint, since logs are retained.
- **Option B (recommended once the indexer runs continuously):** run the indexer as a separate process: an Azure WebJob, a second App Service or a Container App, using the same code and `python -m rhc_indexer`. The API then only reads.
  - It needs your decision and Azure access (Q2).
- **Single-writer guarantee:**
  - The indexer takes a Postgres advisory lock (`pg_try_advisory_lock`). If Azure runs more than one worker, or a deploy overlaps an old instance, only one indexer writes.
  - The engine uses the same mechanism.

### D.4 Data model (core tables; all writes idempotent via natural keys)

| Table | Key | Contents |
|---|---|---|
| `rhc_checkpoint` | `stream` | last block, last block hash, updated_at |
| `rhc_pool` | `pool_id` (v2/v3 address or v4 bytes32 id) | venue, factory/hook, token0/1, quote asset, fee, tickSpacing, created_block/ts, first-seen source |
| `rhc_token` | `address` | symbol, decimals, deployer, first_seen, bytecode hash, safety status |
| `rhc_swap` | `(tx_hash, log_index)` | pool, block, ts, sender/recipient, amounts, sqrtPrice/reserves, liquidity, price_quote, price_usd, usd_size, side |
| `rhc_liquidity_event` | `(tx_hash, log_index)` | pool, type (add/remove/sync), amounts, liquidity delta |
| `rhc_candle` | `(pool_id, tf, bucket_ts)` | OHLC (quote and USD), volume, buys/sells counts and USD, unique traders, large-trade count, liquidity close |
| `rhc_source_snapshot` | `(source, pool_id, ts)` | price/liquidity from DexScreener/GT, for cross-checks |
| `rhc_source_health` | `source` | success rate, latency, last error, last OK |
| `rhc_watchlist` | `token` | state (new / screening / watch / rejected / tradable / expired), reasons, scores, timestamps |
| `rhc_screen_result` | `(token, ts)` | each check's result and reason codes (auditable rejections) |
| `rhc_signal` | `id` | strategy, token/pool, as_of_ts, entry/stop/targets, features snapshot (JSON), evidence |
| `rhc_decision` | `id` | every decision, including rejections, with reason codes and evidence |
| `rhc_paper_position` / `rhc_paper_fill` | `id` | fills with modelled fee/gas/slippage/latency, exits, PnL |
| `rhc_backtest_run` / `rhc_metric` | `id` | config hash, data window, split, metrics with CIs, sample-size flag |

**Storage budget** (the biggest practical constraint). All-chain swaps run ~1.1 M/day, about 250–350 MB/day raw in Postgres. The dedicated database is a **free tier (500 MB)**, so raw history can't be stored. Instead, **the chain is the archive**: the RPC keeps logs since genesis, so raw swaps are re-fetched when needed rather than stored. Policy, all values configurable:

| Data | Retention | Est. size |
|---|---|---|
| Pool and token registry (every pool, including dead ones, so backtests aren't skewed toward survivors) | Forever | ~1 MB/day |
| 5m candles + flow, tracked pools only (~100–200) | Forever (rolled up to 15m after 60 days) | ~4–8 MB/day |
| 1m candles | Rolling 7 days | ~15–30 MB total |
| Raw swaps | Open paper positions only, 48 h | a few MB |
| Signals / decisions / rejections / paper trades | Forever | <1 MB/day |
| Transfers | Not stored; replayed per token on demand | 0 |

- **Hard cap (`RHC_DB_BUDGET_MB`, default 400).** An hourly size check prunes oldest-first at 70% and **stops all RHC writes at 90%**, raising an alert on the page.
- **Backtest cache.** Logs re-fetched for backtests go to compressed local files, not the database.
- I'll measure actual row sizes in the first 24 h of Phase 1 and report them before widening the tracked set.

### D.5 Failure and restart behaviour
- **Checkpoint advance.** The indexer advances its checkpoint only after a batch commits. On restart it resumes from the checkpoint. A gap detector compares candle continuity against block coverage and schedules backfill.
- **Reorgs.** The indexer processes up to `head − RHC_CONFIRMATIONS` (default 20 blocks ≈ 2 s) and stores block hashes. If the parent hash mismatches, it rolls back to the last matching block and re-indexes.
  - Arbitrum sequencer soft-finality makes reorgs rare, but they're handled anyway.
- **RPC failure.** Exponential backoff plus failover to `RHC_RPC_URLS` (comma-separated). After N failures the engine enters a **no-trade state** (stale data blocks new entries).
- **Third-party source failure.** It degrades health status but never blocks indexing.
- **Engine restart.** Paper positions are re-loaded from the DB. Stops are re-evaluated against the latest data before any new entry.

---

## E. Methodology (proposal to validate, not assumptions)

### E.1 Universe and hard filters (deterministic, run in order, each with a reason code)
1. **Quote asset** ∈ {ETH, WETH, USDG} (`QUOTE_UNSUPPORTED`).
2. **Pool type decodable** by our decoders (`VENUE_UNSUPPORTED`).
3. **Age** ≥ `RHC_MIN_POOL_AGE_MIN` (default 15 min). This avoids the launch block, where sniping bots and latency dominate (`TOO_NEW`).
4. **Liquidity** ≥ `RHC_MIN_LIQ_USD` (default $25k) **and** modelled round-trip cost for the intended size ≤ `RHC_MAX_ROUNDTRIP_COST_PCT` (default 3%) (`ILLIQUID`, `COST_TOO_HIGH`).
5. **Honeypot simulation passes:**
   - `eth_call` with state override: an injected helper contract buys, then sells, through the pool's router or PoolManager at `latest`;
   - measures buy and sell tax and checks for transfer restrictions;
   - reason codes `SELL_BLOCKED`, `TAX_HIGH`.
6. **Contract permissions:**
   - bytecode selector scan for mint, blacklist, pause, set-fee, set-max-tx and owner-only trading toggles;
   - EIP-1967 proxy slots read at `latest`;
   - owner renounced or not;
   - reason codes `MINTABLE`, `BLACKLIST_FN`, `PAUSABLE`, `UPGRADEABLE`, `OWNER_ACTIVE`. Some of these are warnings rather than hard rejects, set in config.
7. **Liquidity control:** who can remove the LP (v2 LP-token holder; v4 position NFT owner or hook-locked) (`LP_UNLOCKED`) [NEEDS VERIFICATION per launchpad].
8. **Holder concentration:** from the replayed Transfer logs, top-10 non-pool holders below X%, deployer below Y%, and funding-source clustering of early buyers (`CONCENTRATED`, `INSIDER_CLUSTER`).
9. **Volume quality:** unique-trader ratio, self-trade/round-trip heuristics and median trade size versus outliers (`WASH_SUSPECT`).

### E.2 Candidate features (all computed as-of `t` using only data with block timestamp ≤ `t`)
- **Price and momentum:** returns over 1/5/15/60 min; distance from VWAP; breakout versus rolling high; candle range expansion (ATR ratio).
- **Volume and flow:** volume versus its own rolling baseline; buy/sell USD imbalance; unique buyers per minute and its acceleration; share of new wallets; large-trade count; repeat-buyer share.
- **Liquidity:** liquidity level and its 15/60 min change; recent liquidity removals (a rug precursor); price impact at the trade size.
- **Wallet intelligence:** buys by wallets with good *past* realized outcomes. Scores are computed **only from trades closed before `t`**, with a minimum history per wallet; this is the main leakage risk.
- **Context:** chain-wide volume and new-pool rate (risk-on / risk-off), the ETH trend, the token's age bucket, and time of day.

### E.3 Candidate strategies (each a pluggable class with an identical interface)
1. **Volume breakout:** price above its N-minute high, volume ≥ k× baseline, buy-imbalance confirmation.
2. **Momentum continuation:** positive 5m/15m returns with rising unique buyers and stable or rising liquidity.
3. **Liquidity-growth:** sustained liquidity additions with organic flow (not single-wallet).
4. **Smart-money flow:** cluster of buys from historically good wallets within a window (only once the wallet scores pass a predictive test).
5. **Volatility expansion:** a range-compression → expansion trigger.
6. **Multi-signal:** a combination learned in E.6, not hand-weighted.

**Shared execution rules:**
- **Entry confirmation:** the signal must persist for at least one more candle, and the price must not have moved more than X% beyond the trigger (anti-chase).
- **Exits:**
  - an initial stop from ATR or structure, capped at a maximum percentage;
  - take-profit as an R-multiple, with optional partial take-profit;
  - a trailing stop after +1R;
  - a time stop at 4 h, matching the brief's hold horizon;
  - an emergency exit on a liquidity-removal event or a failed re-run of the sell simulation.

### E.4 Regime and no-trade conditions
- No new entries if any of these hold:
  - data is stale (indexer lag over N s, or source health red);
  - chain-wide volume or new-pool rate is in its bottom decile;
  - ETH drops more than X% within 1 h;
  - the daily loss limit is hit;
  - the kill switch is on.
- Regime labels (e.g. `hot`, `normal`, `cold`) come from chain-wide flow percentiles **computed on trailing data only**. Results are reported per regime.

### E.5 Position sizing
- Fixed-fractional risk: risk per trade = `RHC_RISK_PCT` of paper equity, with size = risk ÷ stop distance.
- Size is then capped by the liquidity-impact limit (max X% price impact), a per-token cap, max open positions and max total exposure.
- Paper equity and limits are config-driven (Q4).

### E.6 How weights get learned (not hand-set)
1. **Stage 1 (no model).** Hard filters plus rule-based strategies with a few config parameters. Collect labeled setups. The label is the triple-barrier outcome: TP hit / SL hit / time-out, computed from **future** data and stored separately from features.
2. **Stage 2 (only after ≥ `RHC_MIN_LABELED_SETUPS`, default 500, spanning ≥ 3 weeks).** An L1/L2-regularized logistic regression on standardized features: interpretable, with coefficient stability checked across folds.
3. **Stage 3 (only if Stage 2 shows out-of-sample lift).** Gradient boosting (LightGBM is already in requirements) with monotonic constraints where they make sense, plus calibration.
4. **Throughout:** feature importances and coefficients are published on the page. LLMs are used **only** for human-readable summaries of already-computed evidence, never in the decision path.

---

## F. Validation design

### F.1 Bias controls
- **Look-ahead:**
  - every feature function takes `as_of_ts` and is unit-tested with "future rows present" fixtures to prove they're ignored;
  - candles use block timestamps;
  - signals are evaluated on **closed** candles only;
  - entries fill at the *next* event after `as_of_ts + latency`.
- **Survivorship:**
  - the universe comes from on-chain pool-creation events (every pool ever created), not from DexScreener or GeckoTerminal lists, which only show survivors;
  - dead and rugged tokens stay in the dataset, and their losses count.
- **Leakage:**
  - wallet scores and regime thresholds are computed from data before the training-fold boundary;
  - **purging plus an embargo** of at least 4 h between train and test (equal to the max hold) so overlapping trades don't leak.
- **Selection bias (multiple testing):**
  - every strategy/parameter combination tried is recorded;
  - results are reported alongside the number of trials;
  - the final test window is touched once per strategy version.

### F.2 Splits
- **Walk-forward:** rolling train (e.g. 14 days) → embargo (4 h) → test (e.g. 3 days), advancing by the test length.
- **Out-of-sample hold-out:** the most recent 20% of data, never used for tuning.
- **Live forward paper trading** is the final out-of-sample test.
- With only about 4 months of chain history, and only the history we index ourselves at full fidelity, **early conclusions will be weak by construction**.

### F.3 Minimum samples (configurable; the UI shows "insufficient sample" below them)
- **Per strategy:** ≥ 200 closed trades **and** ≥ 30 distinct tokens **and** ≥ 3 calendar weeks before *any* performance statement. At a ~50% win rate, n = 200 gives a 95% CI of about ±7 percentage points.
- **Per regime bucket:** ≥ 50 trades.
- **Model training:** ≥ 500 labeled setups.

### F.4 Metrics (each with a 95% CI: Wilson for win rate, bootstrap by trade for the others)
- Win rate, profit factor, net PnL, expectancy per trade (R and USD), average win and average loss, realized R/R, max drawdown and its duration, trade frequency, exposure time.
- Breakdowns by strategy × regime × venue × token-age bucket.
- Cost attribution: fees vs. gas vs. slippage vs. latency drift.

### F.5 Paper-fill realism model (`rhc_fills.py`, pure and unit-tested)
- **Price impact:**
  - v2: exact constant-product math from current reserves (Sync events).
  - v3/v4: constant-L approximation within the current tick from the Swap event's `liquidity`. This **underestimates impact for trades that cross ticks**, so a conservative multiplier is applied and calibrated against live quotes.
  - **Forward paper:** fills use an actual quote at decision time (Relay quote and/or an on-chain quoter via `eth_call` at `latest`). The modelled value is stored next to it so the backtest model can be calibrated.
- **Fees:** the pool fee tier, plus dynamic or hook fees where detectable (the v4 `Swap` event carries the fee). Plus the router/aggregator fee if Relay is used [NEEDS VERIFICATION: Relay fee].
- **Gas:** measured `gasPrice × gasUsed` from recent comparable swaps, including the L1 data component on Orbit.
- **Latency:**
  - decision → submit → inclusion modelled as `RHC_LATENCY_MS` (default 1,500 ms, about 15 blocks);
  - the fill uses the pool state **after** the swaps in that window;
  - failed-transaction probability rises with volatility (configurable), and a failed transaction pays gas.
- **Adverse selection:** an extra slippage penalty proportional to same-block and next-block flow in the same direction (proxy for bots and sequencer ordering), calibrated later from live pilot data.
- **Exit liquidity:** stops fill at the post-latency price, *not* the stop price. A gap through the stop is honoured.

**Where paper results will likely overstate live results:**
- Tick-crossing impact on v3/v4.
- Bot competition and ordering.
- Honeypots that change behaviour after our simulation (fee or blacklist toggles).
- Liquidity pulls between decision and fill.
- Relay or aggregator routing differences.
- Partial fills and transaction failures.
- Our own market impact if size grows.

Expect live results to be **worse** than paper. The go-live gate (Phase 4) requires a margin for this.

---

## G. Risks and limitations
1. **Short, non-stationary history.** Roughly 4 months, in a hype phase. Edges found now may vanish, so regime breakdowns and continual forward testing are mandatory.
2. **Single public RPC with an unknown rate limit.** This is the biggest operational risk. Mitigations: a failover URL list and a paid provider if you can supply one (Q3).
3. **No historical state.** Backtests rely on event-derived prices and liquidity. v3/v4 depth beyond the current tick is approximated.
4. **Blockscout is not automatable**, so verified-source analysis is unavailable. Permission analysis falls back to bytecode heuristics, which are weaker: obfuscated or custom contracts can evade them. When a check can't be completed, the safe default is reject.
5. **Launchpad coverage.** The largest hook family (`0x4e34…`, ~1,500 pools/day) is unidentified and absent from DexScreener. Pre-graduation bonding-curve trading is out of scope.
6. **Free-tier storage (500 MB) in the dedicated database** (D.4). Only derived data is kept, under a hard cap. Detailed history for pools that weren't tracked at the time needs a slower re-fetch from the chain. Public-RPC log retention isn't guaranteed [NEEDS VERIFICATION]. Free-tier egress limits apply [NEEDS VERIFICATION].
7. **Azure single process.** Indexing in-process competes with the API and other bots. App Service restarts cause gaps (backfill covers them).
8. **Latency.** Azure Central India → RPC host latency is unknown, and 0.1 s blocks mean dozens of blocks can pass per decision. Strategies must target 1m/5m moves, not block-level races.
9. **Existing desk issues (reported, not changed):**
   - unused slippage and price-impact caps;
   - optimistic paper fills;
   - global live switch shared with the manual desk's wallet.
10. **Security observation (outside this task's scope).** `Binance-trading-assistant.env` is tracked in git and appears to contain live API keys, a Solana private key and the production DB URL. Treat these as exposed and rotate them. **Also:** your local `backend/.env` currently has `COPYTRADE_LIVE=true`, `COPYTRADE_LIVE_DRYRUN=false`.
11. **Unverified items carried forward:**
    - DexScreener and GeckoTerminal documented limits;
    - GeckoTerminal deep OHLCV paging;
    - Relay limits and fees;
    - launchpad identities, factory addresses and graduation mechanics;
    - hood.fun, Openfair and noxa existence on this chain;
    - Bitquery and StalkChain coverage;
    - the Azure worker count and startup command;
    - which commercial RPC providers support chain 4663.

---

## H. Phased roadmap

Every phase ends with tests run, a summary of verified versus assumed, and a stop for your approval. Every commit stays on `new-feature`; nothing deploys until you merge to `main`.

**Phase 1: Data foundation**
- **Build:**
  - `rhc_config`, `rhc_models`/`rhc_db` (separate base, guarded);
  - `rhc_rpc` (retries, failover, adaptive chunking);
  - `rhc_decoders` (v2/v3/v4/ERC-20);
  - `rhc_indexer` (polling, checkpoints, reorg handling, gap backfill, advisory lock);
  - `rhc_candles` (1m/5m + flow);
  - `rhc_sources` (DexScreener, GeckoTerminal, DefiLlama, Relay behind one interface with token-bucket limits, caching and health);
  - `/api/rhc/health`;
  - `.env.example` additions.
- **Accept when:**
  - decoder unit tests pass on real recorded logs;
  - candle builder tests prove idempotency and correct bucketing;
  - a 24 h local indexing run (against the RPC, writing to a non-production DB) shows no unexplained gaps;
  - our prices on 5 reference pools match GeckoTerminal OHLCV within a stated tolerance;
  - the measured storage per day is reported;
  - `import main` with `RHC_ENABLED=false` behaves identically to today;
  - the app boots with an RHC import deliberately broken.

**Phase 2: Discovery and screening**
- **Build:** watchlist state machine; safety engine (honeypot sim via state override, bytecode permission scan, proxy detection, LP control, holder concentration and insider clustering, wash heuristics); reason codes.
- **Accept when:**
  - tests on fixture tokens (known-good and synthetic honeypot cases) pass;
  - every rejection is visible with its reason codes;
  - false-reject and false-pass rates are spot-checked manually on 30 real tokens and reported.

**Phase 3: Intelligence, signals and decision engine**
- **Build:** point-in-time features; wallet scoring; pluggable strategies; decision engine with a full evidence log; risk engine (sizing, caps, daily loss, cooldowns, kill switch, no-trade rules).
- **Accept when:**
  - no-look-ahead tests pass;
  - risk-rule unit tests pass;
  - a deterministic replay of a recorded day yields identical decisions twice.

**Phase 4: Paper trading and validation**
- **Build:** `Broker` interface; `PaperBroker` with the F.5 fill model; `LiveBroker` (disabled stub that wraps the existing execution functions and raises unless gated); backtester with walk-forward; metrics with CIs; `GO_LIVE_CHECKLIST.md`.
- **Accept when:**
  - fill-model tests pass;
  - the backtest reproduces the paper engine's decisions on the same data;
  - "insufficient sample" gating is enforced in the API and UI;
  - the LiveBroker provably refuses to execute (tested).

**Phase 5: Frontend page `/robinhood-chain`**
- **Build:**
  - sidebar entry;
  - watchlist, ranked opportunities, token intelligence report, regime panel, active signals, paper positions, history including rejections, performance dashboard (by strategy and regime, with CIs and sample flags), risk monitor, and system and source health;
  - a "PAPER MODE · live trading disabled" banner on every view.
- **Accept when:**
  - `npm run build` and `npm run lint` pass;
  - the page works against a local backend;
  - the Copy Trade page's Robinhood panel is unchanged (manual regression check of buy, sell and targets in paper mode).

**Go-live gate (Phase 4 document; not executed in this project):**
- every metric above its minimum sample;
- positive out-of-sample expectancy with its CI lower bound above 0 **after** costs and a safety haircut;
- max drawdown within limit;
- the dedicated wallet change approved separately;
- a small-size live pilot with hard caps and the kill switch tested.

### Questions I need answered (I can't determine these from the repo or by probing)
1. **Database. ANSWERED:** free Supabase. A new dedicated free database will be created for Robinhood Chain data via `RHC_DATABASE_URL`, and the existing production database stays as-is.
2. **Azure.**
   - What App Service tier is it? Is "Always On" enabled? How many workers or instances run, and what is the startup command?
   - Can we later run the indexer as a separate WebJob or Container App (D.3 Option B)?
3. **Keys and budget.** Do you have, or want, a paid RPC for chain 4663, a CoinGecko/GeckoTerminal API key, a Bitquery key or Blockscout API access? Without them, everything runs on the public endpoints described above.
4. **Paper parameters.** Starting paper equity, per-trade size range and risk per trade. Defaults if you don't specify: $1,000 equity, $10–$50 per trade, 1% risk, max 5 open positions, 3% max daily loss.
5. **Deployment workflow.** OK to keep all work on `new-feature`, with you merging to `main` (which triggers the Azure deploys) after each approved phase?
