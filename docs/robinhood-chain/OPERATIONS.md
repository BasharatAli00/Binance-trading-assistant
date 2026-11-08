# Robinhood Chain System: Operations

## Health checklist (`GET /api/rhc/health`)
| Field | Healthy | If not |
|---|---|---|
| `service.status` | `running` | `disabled`: flag off · `disabled_no_database`: set `RHC_DATABASE_URL` · `db_unavailable`: check the Supabase project isn't paused and the password is right · `standby_other_writer`: another worker or process holds the writer **lease** (expected with more than one worker) · `standby_lease_lost`: the lease renewal failed (usually a network blip); it retries every 30 s |
| `indexer.mode` | `live` | `catchup` after a restart is normal · `paused_storage`: see the storage section below |
| `indexer.lag_blocks` | < 100 (≈10 s) | Rising lag means RPC problems; check `rpc.per_url` |
| `indexer.last_error` | `null` | Transient RPC errors are retried with backoff |
| `storage.pct` | < 70 | See the storage section below |
| `sources.*.err_count` | Small relative to `ok_count` | GeckoTerminal 429s are expected occasionally (free tier) |
| `cross_check.flagged` | Empty | Pools where our price differs from a source by more than `RHC_XCHECK_MAX_DEV_PCT`; review them |
| `registry.unrecognized_factories` | Few | New DEX factories seen; verify on the explorer, then add them to `RHC_V2_FACTORIES` / `RHC_V3_FACTORIES` |

## Storage (free tier, 500 MB)
- **Budget:** `RHC_DB_BUDGET_MB` (default 400). The guard runs hourly:
  - **always:** retention (1m candles 72 h, liquidity events 7 days, snapshots 7 days), and 5m candles older than 30 days roll up to 15m;
  - **≥ 70%:** halved retention windows;
  - **≥ 90%:** **all RHC writes pause**, `VACUUM FULL` runs on the RHC tables, and writes resume below 80%. A pause shows up as `indexer.mode = paused_storage`.
- **To create more room:** lower `RHC_MAX_TRACKED_POOLS`, lower `RHC_RETAIN_1M_HOURS`, or raise `RHC_TRACK_MIN_VOL_USD_1H`.
- **Liquidity events:** removals are always stored, because they're the rug-pull signal. Adds are stored only when priced and at least `RHC_LIQ_ADD_MIN_USD`. Some hook-driven v4 pools reposition liquidity hundreds of times a minute; storing every add was measured at roughly 40 MB/day in one test run.

## Restarts and gaps
- **Restart:** automatic catch-up from the durable checkpoint. Candles are rebuilt identically.
- **Downtime over ~1 day** (`RHC_MAX_CATCHUP_BLOCKS`): a row is recorded in `GET /api/rhc/gaps` and indexing restarts near the chain head.
- **Filling a gap:** `cd backend && python rhc_indexer.py backfill-gap <id>`. It rebuilds candles for the currently tracked pools; buckets at the range edges that can't be complete are skipped.

## Emergency off
Set `RHC_ENABLED=false` and restart the App Service. The existing app is unaffected either way.

## Known limitations (Phase 1)
- **Pool history before tracking:** candles start when a pool becomes tracked, plus up to 60 minutes from memory. Older history for such a pool needs a manual `backfill-range`.
- **Unique traders:** counted only in live mode for tracked pools (`traders_exact=true`). During catch-up, distinct transactions are counted instead (`traders_exact=false`).
- **v3/v4 liquidity:** stored as raw in-range liquidity (`liq`). USD liquidity for these pools comes from source snapshots. v2 pools get `liq_usd` from reserves.
- **Unsupported venues:** pre-graduation bonding-curve launchpads, PancakeSwap v3 (different Swap signature), Algebra and DLMM venues aren't decoded yet.
- **USDG is assumed to be $1.** The cross-checks will show any de-peg.
