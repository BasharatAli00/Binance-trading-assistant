# Intelligent Sniper — Integration Plan (into the existing binance-trader system)

> **Scope of this document:** *how* to fold the "Intelligent Sniper" meme-coin bot
> (see `INTELLIGENT_SNIPER_IMPLEMENTATION.md`) into our **existing** FastAPI +
> SQLAlchemy + Next.js app **without touching the two strategies that already
> work**. This is a plan only — no code is written or changed yet.
>
> The reference doc's code is treated as a **specification, not literal source** —
> we re-implement it in our house style (sync SQLAlchemy, daemon-thread loop) so it
> matches the rest of the backend instead of bolting on a second, foreign stack.

---

## 0. Hard constraints (non-negotiable)

1. **Do not touch Strategy #1** (trend-following BTC, `strategy.py` + `paper_engine.py` + `_manage_btc` in `trader.py`).
2. **Do not touch Strategy #2** (pivot-bracket, `pivot_strategy.py` + `pivot_engine.py` + `_manage_pivot` in `trader.py`).
3. The existing **trader thread**, **APScheduler collectors**, **DB tables**, and **API routes** keep working unchanged.
4. The sniper is a **third, fully isolated strategy**: its own tables, its own wallet, its own loop thread, its own API prefix, its own frontend page. A crash anywhere in the sniper must never reach the other two — same isolation pattern already used to wrap `_manage_pivot` in `try/except`.

If a step in this plan would require editing `strategy.py`, `pivot_strategy.py`, `paper_engine.py`, `pivot_engine.py`, `signals.py`, or the `_manage_btc` / `_manage_pivot` functions — **it's the wrong step.** The only existing files we touch are *additively*: `models.py`, `main.py`, `requirements.txt`, and the frontend nav.

---

## 1. How the current system is built (anchor)

| Concern | Existing implementation |
|---|---|
| Web framework | FastAPI, single app in `backend/main.py`, routes defined inline |
| DB layer | **SQLAlchemy 2.0 (sync)** + `psycopg2`, `Base` in `database.py`, models in `models.py` |
| Schema mgmt | `Base.metadata.create_all(checkfirst=True)` + self-healing `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` |
| Strategy loop | `run_trader()` (in `trader.py`) runs in a **daemon thread** started in `main.py` `lifespan`, loops every 60 s |
| Wallets | `paper_engine.py` (Strategy #1) and `pivot_engine.py` (Strategy #2) — **isolated wallets**, each with its own `*_account` / `*_positions` / `*_trades` tables and the same function surface (`ensure_initialized`, `get_position`, `execute_buy`, `execute_sell`, `portfolio_summary`, `get_recent_trades`, `reset_wallet`) |
| Scheduled fetchers | APScheduler cron jobs (data/news/onchain/taapi/trends/pivots/futures), hourly-ish |
| Frontend | Next.js (a **modified** build — see §10), pages under `frontend/app/*`, nav in `frontend/app/components/Sidebar.tsx`, API base in `frontend/lib/config.ts` |

**Key takeaway:** Strategy #2 is the template for adding an isolated strategy. We
copy its isolation pattern exactly.

---

## 2. The one big adaptation: asyncpg/async → SQLAlchemy/thread

The reference doc is written for **asyncpg + raw SQL + `asyncio.run`**. Our backend
is **sync SQLAlchemy in a daemon thread**. Mixing the two would mean a second DB
driver, a second connection model, raw SQL strings, and a foreign async runtime
living next to a sync one — more surface area, more ways to break.

**Decision: re-implement the reference logic in our house style (Option A).**

| Reference doc | This integration |
|---|---|
| `asyncpg.connect()` + raw SQL | SQLAlchemy ORM models + `SessionLocal`, `text()` only for the time-series aggregation query |
| `httpx.AsyncClient` | `requests` (already a dependency) — sequential, batched; at ~50 tokens/tick it fits comfortably in the 60 s budget. *(Optional: add `httpx` for sync client if we want connection pooling — not required for v1.)* |
| `asyncio.run(main())` long loop | `run_sniper()` in a **daemon thread**, mirroring `run_trader()` |
| `pump_bot_portfolio` multi-portfolio table | v1: a **single sim wallet** (`SniperAccount`) + one persisted **config row** (`SniperConfig`) the UI can tune. Multi-portfolio / live wallet is a Phase-2 extension. |

> *Alternative (Option B), not recommended:* keep the reference's `pump_bot/`
> async package verbatim and run it via `asyncio.run` in its own thread with its own
> `asyncpg` pool. Faithful to the doc, but adds a parallel DB stack and ORM. Only
> revisit if we later need high snapshot concurrency the sync path can't meet.

---

## 3. CoinGecko / GeckoTerminal decision

Verified against current docs (June 2026):

- **CoinGecko Demo (free coin API)** — free key, ~100 calls/min, **10,000 calls/month**.
  Brand-new pump.fun tokens are **not listed** as CoinGecko coins until much later,
  and its richer on-chain pool filters are **Pro-only**. The only free-tier value is
  macro/global sentiment, which we already cover with Fear & Greed + Jupiter SOL price.
  → **Exclude.** It does not help snipe fresh tokens.

- **GeckoTerminal API** (CoinGecko's on-chain DEX product) — **free, no API key,
  30 calls/min**, exposes `/networks/solana/new_pools`,
  `/networks/solana/trending_pools`, pool detail, and OHLCV. This *is* useful.
  → **Include as an optional SECONDARY discovery + cross-check source**, behind a
  config flag (`USE_GECKOTERMINAL = True`), with graceful fallback so DexScreener
  alone still works if GeckoTerminal is down or rate-limited.

**How GeckoTerminal slots in (additive, non-breaking):**
- Discovery: union GeckoTerminal `new_pools` + `trending_pools` (Solana) into the
  same candidate set the DexScreener boost/profile endpoints already build, then run
  the **same** `_passes_filters` / `_rank_score` gates. More candidates, same funnel.
- Cross-check (optional): use GeckoTerminal pool OHLCV as a sanity check on
  DexScreener price before an entry. Nice-to-have, not v1-critical.
- Rate budget: 30 calls/min is plenty for 2–3 discovery calls every 5 min. Keep a
  small client-side throttle and treat any non-200 as "skip GeckoTerminal this cycle".

---

## 4. New files (all live in `backend/`, all prefixed `sniper_`)

Mapping reference module → our file (one-to-one where sensible):

| Reference module | New file | Responsibility |
|---|---|---|
| `config.py` | `sniper_config.py` | All constants, endpoint URLs, gates, defaults, feature flags (`USE_GECKOTERMINAL`, `SNIPER_ENABLED`) |
| `watchlist.py` + `collector.py` | `sniper_data.py` | DexScreener (+ optional GeckoTerminal) discovery, batch snapshot fetch, persistence of watchlist + snapshots |
| `macro.py` | *reuse* `fear_greed.py` + small `sniper_macro.py` | Reuse existing Fear & Greed; add Jupiter SOL price helper |
| `features.py` | `sniper_features.py` | ~35 features from the last 20 min of snapshots (one `text()` query + pure-Python math) |
| `conviction.py` | `sniper_conviction.py` | Rule-based 0–100 conviction score (pure function) |
| `rug_risk.py` | `sniper_rug.py` | Safety score 0–100 via public Solana RPC, 5-min per-token cache |
| `trader.py` (gates+exits) | `sniper_strategy.py` | Pure decision logic: entry gate stack, exit decision (SL / trail / TP / time), circuit-breaker check |
| `bot.py` (main loop) | `sniper_loop.py` | `run_sniper()` daemon-thread loop, tick orchestration, `_manage_sniper_position()` (mirrors `_manage_pivot`) |
| (wallet, implicit in doc) | `sniper_engine.py` | Isolated sim wallet — **clone of `pivot_engine.py`** with `Sniper*` models |
| `live_executor.py` | `sniper_live.py` | **Phase 2 only** — Jupiter swaps; not built until sim is proven |
| `pump_bot_router.py` | `sniper_api.py` | FastAPI `APIRouter(prefix="/api/sniper")`, included via one additive line in `main.py` |

> **Naming:** we use the `sniper_` prefix (not `pump_`) in code, but the **DB tables**
> can keep the `sniper_` prefix too for consistency with `pivot_*`. Either is fine as
> long as nothing collides with existing tables.

---

## 5. Data model (append to `models.py` — additive only)

New ORM classes, all new `__tablename__`s, managed by the existing
`create_all(checkfirst=True)` (which only creates **missing** tables — existing data
untouched). Mirror the column style already in `models.py` (UUID PK, `Float`/`Integer`/`String`/`DateTime`).

1. **`SniperToken`** — active/tracked tokens (the watchlist). Cols: `token_address` (unique), `symbol`, `name`, `pair_address`, `dex_id`, `liquidity_usd`, `volume_h1`, `price_usd`, `market_cap`, `discovery_source`, `rank_score`, `is_active`, `logo_url`, `has_socials`, `boost_count`, `created_at`, `updated_at`.
2. **`SniperSnapshot`** — 60-s time-series. The ~30 fields from the reference `pump_token_snapshots` (price/volume/txns/liquidity/changes/meta). Index on `(token_address, snapshot_time DESC)`. **Retention: delete rows older than 45 days each tick** (same one-liner as the doc).
3. **`SniperPosition`** — open/closed positions for the sim wallet: `token_address`, `symbol`, `entry_price`, `entry_time`, `exit_price`, `exit_time`, `qty`, `position_usd`, `peak_price`, `exit_reason`, `realized_pnl`, `return_pct`, `hold_minutes`, `conviction_score`, `rug_risk_score`, `entry_dex_id`, `entry_pair_address`, `discovery_source`, `status`.
4. **`SniperTrade`** — immutable trade log (same shape as `PivotTrade`).
5. **`SniperAccount`** — single-row sim wallet (clone of `PivotAccount`): `usdt_balance`, `starting_balance`, `created_at`, `updated_at`. Seed once (e.g. `STARTING_BALANCE = 1000`).
6. **`SniperConfig`** — single-row tunable strategy params the UI can edit (position_size, max_open_positions, stop_loss_pct, take_profit_pct, time_exit_minutes, trail_*, conviction_floor, min_buy_pressure, rug_veto_threshold, cb_enabled, cb_max_drawdown, is_active/auto_trade). Replaces the reference `pump_bot_portfolio`. Seed defaults once.
7. **`SniperCooldown`** — `token_address` (PK), `cooldown_until`.
8. **`SniperModelScore`** — per-token latest scores for the UI: `token_address` (PK), `prob_win`, `conviction_score`, `rug_risk_score`, `updated_at`.

Also add these to the import list in `init_db.py` (additive line) so a fresh
`init_db` run creates them — but `create_all` in `ensure_initialized()` will also
create them at startup, so this is belt-and-suspenders.

---

## 6. The loop and how isolation is guaranteed

`sniper_loop.run_sniper()` — a daemon thread, 60-s tick, structurally identical to
`run_trader()`. Each tick (all wrapped in a top-level `try/except` that only logs):

1. Every 5 min: refresh watchlist (DexScreener boosts/profiles [+ GeckoTerminal if enabled]) → upsert `SniperToken`.
2. Snapshot all active watchlist + open-position tokens (batched 30/call) → insert `SniperSnapshot`.
3. Check exits on open `SniperPosition`s (SL / trailing / TP / time) → `sniper_engine.execute_sell` + cooldown.
4. Every 15 min: refresh macro (Fear & Greed via existing `fear_greed.py`, SOL price via Jupiter).
5. Compute features per watchlist token (`sniper_features`).
6. Entry funnel (`sniper_strategy`): dedup/cooldown/quality/momentum/bearish/rug-veto gates → conviction → rank.
7. Circuit-breaker check; if tripped, set config inactive and skip entries.
8. Execute entries against `SniperAccount` up to `max_open_positions` and cash.
9. Upsert `SniperModelScore` for the UI.
10. Delete snapshots older than 45 days.

**Isolation mechanics:**
- **Separate thread.** Started in `main.py` `lifespan` *after* the existing trader thread, e.g.:
  ```
  sniper_engine.ensure_initialized()           # seed sniper wallet/config
  sniper_thread = threading.Thread(target=run_sniper, daemon=True)
  sniper_thread.start()
  ```
  and join it on shutdown. This is the **only** change to `lifespan`, and it mirrors
  the existing `pivot_engine.ensure_initialized()` addition exactly.
- **Guard flag.** `SNIPER_ENABLED` (config/env). If false, the thread isn't started — the rest of the app is byte-for-byte unaffected. Lets us ship dark and flip on.
- **Top-level try/except** inside the tick so a sniper exception logs and continues; it shares no mutable state with `dashboard_state`, `paper_engine`, or `pivot_engine`.
- **No scheduler coupling.** The sniper runs its own loop, *not* an APScheduler job, so it can't interfere with the existing cron collectors.
- **No shared tables / wallets / prices.** It reads its own snapshots, writes its own tables, holds its own cash.

---

## 7. Wallet engine (`sniper_engine.py`)

Clone `pivot_engine.py` 1:1, swap `Pivot*` models for `Sniper*`. Same function surface:
`ensure_initialized()`, `get_position()`, `execute_buy()`, `execute_sell()`,
`portfolio_summary(prices)`, `get_recent_trades()`, `reset_wallet()`, plus a small
`update_position_risk(peak_price=...)` for the trailing-stop high-water mark.

Because meme-coin positions are keyed by `token_address` (not a fixed symbol set),
`get_position`/`execute_*` take `token_address`; otherwise the logic (fees, avg
entry, realized P&L, cash accounting) is the same as the paper/pivot engines. Fee
model: keep a simulated fee (and in live mode, model Jupiter slippage/price-impact).

---

## 8. API surface (`sniper_api.py`, additive)

New `APIRouter(prefix="/api/sniper")`, included in `main.py` with a single
`app.include_router(sniper_router)` line. Endpoints (read-only + a couple of mutations):

- `GET /api/sniper/status` — config row + wallet summary + active flag.
- `GET /api/sniper/positions?status=open|closed&limit=` — positions.
- `GET /api/sniper/watchlist` — `SniperToken` joined with `SniperModelScore`, ranked by conviction.
- `GET /api/sniper/trades?limit=` — recent trades (newest first).
- `GET /api/sniper/chart-pnl` — cumulative realized P&L over time (for the equity curve).
- `PUT /api/sniper/config` — update whitelisted tunable params (allow-list, same pattern as the reference `update_portfolio`).
- `POST /api/sniper/reset` — reset the sim wallet (mirrors `/api/pivot-reset`).
- *(Phase 2)* `POST /api/sniper/manual-buy` / `manual-sell`.

Prefix `/api/sniper/*` cannot collide with existing `/api/*` routes.

CORS already allows the frontend origins — no change needed.

---

## 9. Frontend (additive page + nav item)

> ⚠️ **`frontend/AGENTS.md` warns this is a *modified* Next.js build.** Before writing
> any frontend code, read the relevant guide under
> `frontend/node_modules/next/dist/docs/`. Do not assume stock Next.js APIs.

- New route: `frontend/app/sniper/page.tsx` (+ a `layout.tsx` if the sibling pages use one — `analysis`, `news`, `signals`, `watchlist` each have a `layout.tsx`).
- New nav entry in `Sidebar.tsx` `navItems` (e.g. `{ name: "Sniper", href: "/sniper", icon: Crosshair }`) — one array element, additive.
- New components under `frontend/app/components/` mirroring the existing strategy cards (`PivotPortfolio.tsx`, `PivotStrategyCard.tsx`, `PivotTradeHistory.tsx`): a sniper portfolio card, a watchlist/conviction table, a positions table, a P&L chart, and a settings panel hitting `PUT /api/sniper/config`.
- All fetches use the existing `API_URL` from `frontend/lib/config.ts` (no change to config).

Existing pages/components are untouched.

---

## 10. Dependencies & env

**v1 (sim) — backend deps:** none new. Uses `requests` (present) + `sqlalchemy`
(present). *(Optional `httpx` if we prefer a pooled sync client — not required.)*

**Phase 2 (live) — add only when building live mode:** `solders`, `cryptography`
(for Jupiter swap signing + Fernet-encrypted wallet key). Keep these out of
`requirements.txt` until Phase 2 so the sim build stays lean.

**Env vars:**
- `DATABASE_URL` — already set; reused.
- `SNIPER_ENABLED` — gate the thread (default off until we flip it on).
- `SOLANA_RPC_URL` — default `https://api.mainnet-beta.solana.com`, with `https://solana-rpc.publicnode.com` as fallback.
- `USE_GECKOTERMINAL` — default on (free, no key).
- *(Phase 2)* `WALLET_ENCRYPTION_KEY` (Fernet) for live mode only.

No secrets needed for v1 sim (all data sources are keyless).

---

## 11. Implementation order (each step testable, nothing breaks if we stop early)

1. **Models** — append `Sniper*` classes to `models.py`; add to `init_db.py` import list. Run `init_db` (or rely on startup `create_all`); confirm new tables exist and **existing tables/data are untouched**.
2. **`sniper_config.py`** — constants + flags only.
3. **`sniper_engine.py`** — clone pivot engine; unit-test buy/sell/summary against the new sim wallet.
4. **`sniper_macro.py`** — Jupiter SOL price; reuse `fear_greed.py`. Smoke-test.
5. **`sniper_data.py`** — DexScreener discovery + snapshots; verify `SniperToken`/`SniperSnapshot` fill. Then add GeckoTerminal union behind `USE_GECKOTERMINAL` and confirm graceful fallback when forced off/erroring.
6. **`sniper_features.py`** — after a few snapshot ticks, confirm a features dict comes back (needs ≥3 snapshots).
7. **`sniper_conviction.py`** — pure function, score 0–100 on sample features.
8. **`sniper_rug.py`** — public-RPC mint/freeze/holder checks with 5-min cache; test on a known `*pump` mint.
9. **`sniper_strategy.py`** — entry gate stack + exit decision + circuit breaker (pure logic, unit-testable with mock features).
10. **`sniper_loop.py`** — wire `run_sniper()`; run standalone (not yet threaded into the app) for ~10 min in sim; verify positions open/close on the sim wallet.
11. **`main.py` lifespan** — add the guarded `sniper_engine.ensure_initialized()` + thread start/stop (behind `SNIPER_ENABLED`). Confirm the **existing trader thread and all `/api/*` routes still behave identically** with the sniper both off and on.
12. **`sniper_api.py`** — add router + one `include_router` line; curl every endpoint.
13. **Frontend** — read the modified-Next docs first, then add the `/sniper` page, nav item, and components.
14. **Phase 2 — `sniper_live.py`** — only after sim runs clean for ≥1 week; start with a tiny position size and a separate live wallet/config.

---

## 12. "Old pipeline still works" verification checklist

After step 11 (the only step that edits a shared runtime file), explicitly confirm:

- [ ] `run_trader()` thread still starts; BTC Strategy #1 still enters/exits on the paper wallet.
- [ ] Strategy #2 (`_manage_pivot`) still trades on the pivot wallet; `/api/pivot-*` endpoints unchanged.
- [ ] All existing APScheduler collectors still fire (data/news/onchain/taapi/trends/pivots/futures).
- [ ] Every existing `/api/*` route returns the same shape as before.
- [ ] With `SNIPER_ENABLED=false`, the app is functionally identical to today (thread never starts).
- [ ] `create_all` created only the new `Sniper*` tables; no existing table altered/dropped; existing rows intact.
- [ ] A forced exception inside a sniper tick logs and continues — it does not kill the sniper thread or affect the trader thread.

---

## 13. Summary of files touched

**New (additive):** `backend/sniper_config.py`, `sniper_data.py`, `sniper_macro.py`,
`sniper_features.py`, `sniper_conviction.py`, `sniper_rug.py`, `sniper_strategy.py`,
`sniper_engine.py`, `sniper_loop.py`, `sniper_api.py`, (Phase 2) `sniper_live.py`;
`frontend/app/sniper/page.tsx` (+ layout) and new sniper components.

**Existing, edited additively only:**
- `backend/models.py` — append `Sniper*` model classes.
- `backend/init_db.py` — add `Sniper*` to the import list.
- `backend/main.py` — `lifespan`: guarded init + thread start/stop; one `include_router` line.
- `backend/requirements.txt` — nothing for v1; `solders`/`cryptography` only at Phase 2.
- `frontend/app/components/Sidebar.tsx` — one nav item.

**Never touched:** `strategy.py`, `pivot_strategy.py`, `paper_engine.py`,
`pivot_engine.py`, `signals.py`, `trader.py` (the `_manage_btc` / `_manage_pivot`
logic), and every existing model/table/route belonging to Strategies #1 and #2.
