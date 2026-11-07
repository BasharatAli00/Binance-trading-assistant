# Robinhood Chain System: Architecture (Phase 1: data foundation)

## Data flow
```
Robinhood Chain RPC ──eth_getLogs (12 DEX topics)──► rhc_indexer
                                                        │ decode (rhc_decoders)
                                                        │ resolve pools/tokens (rhc_registry ⇄ rhc_pool/rhc_token)
                                                        │ normalise swaps → trades, USD via ref pool (rhc_market)
                                                        │ 1m/5m candles + flow (rhc_candles)
                                                        ▼
                                          rhc_store ──► dedicated Supabase DB (rhc_* tables)
DexScreener / GeckoTerminal ──► rhc_sources.SourceHub ──► snapshots + cross-checks + health
DefiLlama / Relay           ──► chain context + health
rhc_storage.StorageGuard    ──► retention, 5m→15m roll-up, write pause at 90% of budget
rhc_api (/api/rhc/*)        ◄── read-only views for the frontend (Phase 5)
```

## Modules (backend/)
| Module | Responsibility | I/O |
|---|---|---|
| `rhc_config` | Every threshold and flag (env-overridable) | none |
| `rhc_util` | Token bucket, TTL cache, time helpers | none |
| `rhc_decoders` | Raw logs → typed events (v2/v3/v4 pools, swaps, syncs, liquidity) | pure |
| `rhc_market` | Pool classification (base/quote), USD quoting, swap → trade | pure |
| `rhc_candles` | Candle book, rolling activity, tracking policy | pure |
| `rhc_rpc` | JSON-RPC: retries, failover, rate limit, batching, adaptive `getLogs` splitting | network |
| `rhc_registry` | Pool/token cache with batched on-chain resolution | network + DB |
| `rhc_indexer` | Polling loop, checkpoints, reorg handling, gaps, backfill | network + DB |
| `rhc_sources` | DexScreener, GeckoTerminal, DefiLlama, Relay adapters + `SourceHub` | network |
| `rhc_storage` | Storage guard (pure `decide()` + actions) | DB |
| `rhc_models` / `rhc_db` / `rhc_store` | Own `RhcBase`, lazy engine on `RHC_DATABASE_URL`, idempotent upserts | DB |
| `rhc_service` | Lifecycle: supervisor thread, writer lock, `status()` | threads |
| `rhc_api` | `/api/rhc/health`, `/pools/tracked`, `/candles`, `/snapshots`, `/gaps`, `/watchlist`, `/screens`, `/reasons` | DB read |
| `rhc_screener` (Phase 2) | Discovery → watchlist → screening pipeline; own thread and own, smaller RPC budget | network + DB |
| `rhc_sim` + `contracts/RhcSimulator.sol` | Buy→sell round trip via `eth_call` state overrides (v2/v3/v4) | network |
| `rhc_contract_scan` / `rhc_holders` / `rhc_flow` / `rhc_lp` | Permission scan, holder concentration, flow quality, LP history (pure analysis + fetch) | network |
| `rhc_reasons` / `rhc_watchlist` | Reason-code catalog; pure watchlist transitions and discovery scoring | none |

Screening is documented in [SCREENING.md](SCREENING.md).

## Key design decisions
- **Isolation from production:**
  - separate database (`RHC_DATABASE_URL`, no fallback);
  - separate declarative base, so tables are never created through the production `Base`;
  - guarded import and startup in `main.py`;
  - all work on daemon threads.
- **The chain is the archive.**
  - Raw swaps aren't stored; the RPC retains all logs.
  - Only derived candles for *tracked* pools are persisted.
  - The pool registry records every pool seen, so later analysis isn't skewed toward pools that survived.
- **Tracking:** the ETH/USD reference pool plus the top `RHC_MAX_TRACKED_POOLS` pools by 1-hour USD volume, subject to minimum volume and swap counts, with hysteresis and an idle timeout. Closed candles of pools that become tracked are back-filled from an in-memory ring (up to 60 min).
- **USD prices:**
  - USDG is taken as $1, cross-checked against the sources.
  - ETH/USD comes point-in-time from the Uniswap v3 WETH/USDG 0.01% pool's own swaps, so historical candles use the ETH price *at that time*.
- **Restart safety:**
  - candles are flushed only once closed;
  - the durable checkpoint sits before the oldest open 5m bucket;
  - on restart, trades before `resume_from_ts` are skipped and everything after is rebuilt from complete data, giving identical upserts (tested).
- **Reorgs:** the hash of the last processed block is re-checked every poll. On a mismatch, the indexer rewinds to the durable checkpoint.
- **Failure handling:** any failed step, and any loss of the writer lease mid-chunk, forces a rewind to the durable checkpoint. In-memory state that was only partly updated is never re-used, so a retry can't double-count trades (tested).
- **Single writer:**
  - a lease row (`rhc_lease`, database time, 120 s time-to-live, renewed every 20 s on its own thread);
  - a write gate stops all candle and checkpoint writes while the lease isn't held;
  - advisory locks were rejected because they outlive the client behind Supavisor.
- **v4 pool resolution:**
  - first `PositionManager.poolKeys(bytes25)`, verified by recomputing `keccak(abi.encode(key)) == poolId`;
  - then single-ID `Initialize` log scans, because OR-lists in a topic position are limited to 100k-block spans.
- **Gaps:** downtime up to `RHC_MAX_CATCHUP_BLOCKS` (~1 day) is caught up automatically. Longer downtime is recorded in `rhc_gap` and can be filled with `python rhc_indexer.py backfill-gap <id>`.
- **Spoofed events:**
  - v4 events are accepted only from the known PoolManager;
  - v2/v3 pools only count when their factory is allow-listed;
  - anything else is recorded as `factory_unrecognized` and surfaced in `/api/rhc/health` for review.

## RPC facts this design depends on (measured 2026-11-07)
| Fact | Value | Handling |
|---|---|---|
| Block time | ~0.104 s | 20-block confirmation lag ≈ 2 s |
| WebSocket | Not available | HTTP polling every 2 s |
| Historical state | ~1,000 blocks | No historical `eth_call`; prices come from events |
| Log history | ≥108 days | Full backfill possible |
| `getLogs`, topic-only filter | ≤30,000 blocks per call | `RHC_GETLOGS_TOPIC_SPAN=29000` |
| `getLogs`, address filter | ≤10,000,000 blocks per call | v4 id resolution uses 10M windows |
| `getLogs` result cap | 10,000 logs | Adaptive range splitting |
| `log.blockTimestamp` | Field present but always `0x0` | Batched block headers; sampled + interpolated for large ranges |
| JSON-RPC batching | Works (50 calls ≈ 0.8 s); **a batch of 80 → HTTP 429**, 40 → OK | Batches capped at 40 (`RHC_RPC_BATCH_SIZE`); 20 calls/s counted inside batches (`RHC_RPC_MAX_ITEMS_PER_S`); on a 429 the batch is halved and retried |

## Database tables (dedicated DB)
- **Raw data:**
  - `rhc_swap` exists but is written only for pools flagged in Phase 4 (open paper positions).
- **Registry:**
  - `rhc_pool`: every pool seen, with its classification and tracking state.
  - `rhc_token`: decimals and symbol.
- **Market data:**
  - `rhc_candle`: `(pool_pk, tf, bucket)` with OHLC in quote units, close in USD, volume, buys/sells, buy/sell USD, unique traders (`traders_exact` flag), large trades, liquidity.
  - `rhc_liquidity_event`: liquidity adds/removes for tracked pools.
- **Sources:**
  - `rhc_source_snapshot`: DexScreener/GeckoTerminal price, liquidity and volume, with our price and the deviation %.
  - `rhc_source_health`: per-source success/error counts and latency.
- **Operations:**
  - `rhc_checkpoint`: indexer progress.
  - `rhc_gap`: recorded coverage gaps.
  - `rhc_kv`: service state (for example the storage guard's last result).
