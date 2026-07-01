# Pump.fun Top-Gainer Wallet Finder — Standalone Service Spec

**Status:** Ready for implementation
**Scope:** Milestone 1 only — discover, score, and store the wallet addresses of the top-performing Pump.fun traders. Does **not** include buy/sell tracking of those wallets (that's Milestone 2, out of scope here) and does **not** integrate with any other existing system — this is fully standalone with its own storage, config, and process.

---

## 1. Objective

Build a scheduled service that:
1. Pulls Pump.fun trade data from Bitquery
2. Aggregates it per wallet address
3. Scores and ranks wallets by trading performance
4. Persists a ranked "top gainers" table that other systems (future milestone) can read from

Output of this milestone is a **database table + a simple read API/CLI**, not a trading bot.

---

## 2. Data Source

**Primary and only source for this milestone: Bitquery GraphQL API** (`streaming.bitquery.io`)

Rationale: Bitquery is the only reviewed provider with both (a) a purpose-built Pump.fun schema and (b) wallet-level trade aggregation (`Trade.Account.Owner`) needed to compute per-wallet PnL, in a single GraphQL schema. Single-vendor by design for v1 simplicity — do not add secondary sources in this milestone.

- Docs: https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/
- Auth: API access token generated from the Bitquery IDE (`ide.bitquery.io`)
- Pump.fun bonding-curve program address: `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`
- PumpSwap (post-graduation) program address: `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`
- Delivery method for this milestone: **polling via GraphQL query on a schedule** (not subscriptions/streaming — not needed until Milestone 2's live tracking). Simpler, cheaper, and sufficient for a leaderboard that refreshes every 15–60 minutes.

---

## 3. Top-Gainer Criteria (finalized)

This is the core design decision of the service. Ranking purely by "biggest profit" is unreliable on Pump.fun because of wash trading, token-creator self-dealing, and one-off lucky snipes. The criteria below are designed to filter those out before ranking.

### 3.1 Eligibility filters (hard floors — a wallet must pass ALL of these to be scored at all)

| Filter | Threshold | Why |
|---|---|---|
| Minimum closed round-trips | ≥ 5 buy→sell pairs in the lookback window | Excludes one-off lucky snipers; a real "top gainer" trades repeatedly, not once |
| Minimum distinct tokens traded | ≥ 3 different mints | Excludes wash-trading pairs and wallets gaming a single token they control |
| Minimum total volume | ≥ 5 SOL total buy+sell volume in window | Excludes dust/noise wallets whose "100% gain" is $4 |
| Not a detected token-creator wallet | Wallet address ≠ creator address of any token it trades | Creator wallets show inflated "profit" from their own bonding-curve seed — not trading skill |
| Win rate floor | ≥ 35% of round-trips profitable | Excludes wallets whose entire ranking rests on one outsized win masking many losses |

Wallets failing any filter are excluded from the leaderboard entirely (not scored, not shown), and should be logged for later inspection since the filters themselves may need tuning over time.

### 3.2 Ranking score (applied only to wallets that pass eligibility)

Use a **composite score**, not raw PnL alone — raw PnL over-weights whales; ROI alone over-weights tiny wallets with one good trade. The composite balances both:

```
score = (realized_pnl_sol_normalized * 0.5)
       + (roi_pct_normalized * 0.3)
       + (win_rate * 0.2)
```

Where:
- **realized_pnl_sol** = total SOL received from sells − total SOL spent on buys, for closed round-trips only, in the lookback window
- **roi_pct** = realized_pnl_sol / total_sol_spent_on_buys × 100
- **win_rate** = profitable_round_trips / total_round_trips
- Normalization: min-max scale `realized_pnl_sol` and `roi_pct` across the current eligible wallet set before combining (so the score is relative to today's field, not an arbitrary fixed scale)

This weighting (50% absolute profit, 30% efficiency, 20% consistency) favors wallets that are both making real money and doing it skillfully — not just wallets with the biggest bankroll. **This weighting is a starting point and should be configurable**, not hardcoded — expose it in config (see §6) so it can be tuned once real data is observed.

### 3.3 Two parallel windows

Maintain **both** a 24h and a 7d leaderboard, computed independently:
- **24h** — catches wallets on a current hot streak (more useful for near-term signal)
- **7d** — smooths out noise, more statistically reliable, less prone to one lucky day

Store both; let the consumer (Milestone 2 or a human) decide which to use. Do not collapse them into one number.

### 3.4 Explicit non-goals for this milestone

- No unrealized/mark-to-market PnL on open positions — only closed round-trips count. Open-position tracking is more complex (needs live pricing) and belongs in Milestone 2.
- No social/off-chain reputation signals (Twitter, etc.) — on-chain data only.
- No automatic wash-trading graph analysis (e.g., detecting circular trading rings across multiple wallets) — flag this as a known limitation, not something to build now. The eligibility filters above are a first-pass defense, not a complete one.

---

## 4. System Architecture

```
┌─────────────────────────┐
│  Scheduler (cron/interval)│  runs every 15–60 min (configurable)
└────────────┬─────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  Bitquery Client                     │
│  - fetch Pump.fun trades in window   │
│  - paginate as needed                │
└────────────┬──────────────────────────┘
             │ raw trades
             ▼
┌─────────────────────────────────────┐
│  Aggregation Engine                  │
│  - group by wallet (Trade.Account.Owner)│
│  - reconstruct buy/sell round-trips  │
│  - compute PnL, ROI, win rate, volume│
└────────────┬──────────────────────────┘
             │ per-wallet stats
             ▼
┌─────────────────────────────────────┐
│  Eligibility Filter + Scorer         │
│  - apply §3.1 hard floors            │
│  - compute §3.2 composite score      │
└────────────┬──────────────────────────┘
             │ ranked wallets
             ▼
┌─────────────────────────────────────┐
│  Storage (SQLite/Postgres)           │
│  - top_gainers_24h                   │
│  - top_gainers_7d                    │
│  - run_history (audit log)           │
└────────────┬──────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  Read API (local REST or CLI)        │
│  - GET /top-gainers?window=24h       │
│  - GET /top-gainers?window=7d        │
└───────────────────────────────────────┘
```

This is a **self-contained service** — its own repo/folder, own database file, own config, own scheduler. No imports from or dependencies on any other existing system. It exposes a simple read interface so a *future* milestone can consume it, but it does not call out to anything else.

---

## 5. Data Model

### `wallet_stats` (raw computed stats per run, before filtering — kept for audit/debugging)

| Column | Type | Notes |
|---|---|---|
| wallet_address | text | Solana wallet/owner address |
| window | text | `24h` or `7d` |
| run_timestamp | timestamptz | when this row was computed |
| total_buys_sol | numeric | sum of SOL spent buying |
| total_sells_sol | numeric | sum of SOL received selling |
| realized_pnl_sol | numeric | total_sells_sol − total_buys_sol |
| roi_pct | numeric | realized_pnl_sol / total_buys_sol × 100 |
| round_trip_count | int | number of closed buy→sell cycles |
| distinct_tokens | int | number of distinct mints traded |
| profitable_round_trips | int | |
| win_rate | numeric | profitable_round_trips / round_trip_count |
| passed_eligibility | boolean | result of §3.1 filters |
| exclusion_reason | text nullable | which filter failed, if any |

### `top_gainers_24h` / `top_gainers_7d` (final ranked output — what consumers read)

| Column | Type | Notes |
|---|---|---|
| rank | int | 1 = best |
| wallet_address | text | |
| score | numeric | composite score from §3.2 |
| realized_pnl_sol | numeric | |
| roi_pct | numeric | |
| win_rate | numeric | |
| round_trip_count | int | |
| distinct_tokens | int | |
| last_updated | timestamptz | |

### `run_history` (audit log)

| Column | Type | Notes |
|---|---|---|
| run_id | uuid | |
| run_timestamp | timestamptz | |
| window | text | |
| trades_fetched | int | |
| wallets_evaluated | int | |
| wallets_passed_eligibility | int | |
| status | text | success / partial / failed |
| error_message | text nullable | |

---

## 6. Configuration (externalize all of this — do not hardcode)

```yaml
bitquery:
  api_token: ${BITQUERY_API_TOKEN}   # from env var, never committed
  endpoint: https://streaming.bitquery.io/graphql
  pump_fun_program_address: "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

schedule:
  interval_minutes: 30

eligibility:
  min_round_trips: 5
  min_distinct_tokens: 3
  min_total_volume_sol: 5
  min_win_rate: 0.35
  exclude_token_creators: true

scoring:
  weight_pnl: 0.5
  weight_roi: 0.3
  weight_win_rate: 0.2

windows:
  - 24h
  - 7d

storage:
  type: sqlite   # or postgres
  path: ./data/top_gainers.db

leaderboard:
  max_size: 200   # store top 200, not just top 10 — gives room for future filtering
```

---

## 7. Bitquery Query Approach

Use Bitquery's `DEXTradeByTokens` (or `DEXTrades`) query filtered to the Pump.fun program address, over the target time window, returning per-trade: wallet (`Trade.Account.Owner`), token mint, side (buy/sell), amount, price in USD/SOL, and block time. Bitquery's own docs include a directly analogous pre-built pattern for top-trader aggregation by wallet (bought/sold/volume grouped by owner) — adapt that pattern rather than building the aggregation query from scratch. Since Bitquery's free/IDE tier realtime dataset covers roughly the trailing 30 days, both the 24h and 7d windows are comfortably within reach without needing the paid archive tier.

Implementation note for Claude Code: fetch raw trades (not pre-aggregated) so the round-trip reconstruction and eligibility logic in §3 can run in your own code — this keeps the scoring logic auditable and independent of whatever aggregation Bitquery's query layer does internally.

---

## 8. Round-Trip Reconstruction Logic (for the Aggregation Engine)

For each wallet, per token mint, within the window:
1. Sort that wallet's trades on that mint chronologically
2. Use **FIFO matching**: each sell closes against the oldest still-open buy(s) for that mint
3. A "round-trip" = one buy matched against one sell (partial fills should be handled as partial round-trips, weighted by size)
4. `realized_pnl_sol` for a round-trip = sell_value_sol − matched_buy_value_sol
5. Ignore any buy that has no matching sell yet within the window (that's an open position — excluded per §3.4)

This FIFO approach is standard, auditable, and avoids the complexity of LIFO/average-cost methods that are harder to explain when debugging a wallet's score.

---

## 9. Acceptance Criteria

- [ ] Service runs on schedule without manual intervention, logs each run to `run_history`
- [ ] `top_gainers_24h` and `top_gainers_7d` tables are populated and update on every run
- [ ] All eligibility filters from §3.1 are enforced and excluded wallets are logged with a reason
- [ ] Composite score weights are read from config, not hardcoded
- [ ] Manual spot-check: top 5 wallets on each leaderboard are verified by hand against a Solana explorer (e.g., Solscan) to confirm they are not token-creator wallets and that PnL math is directionally correct
- [ ] Read API/CLI returns the current leaderboard in under 1 second (reading from storage, not re-querying Bitquery live)
- [ ] Bitquery API failures (rate limit, timeout, auth error) are caught, logged to `run_history` with `status = failed`, and do not crash the scheduler — next run should retry normally
- [ ] No dependency on, or import from, any other existing codebase — this service starts, runs, and stores data entirely on its own

---

## 10. Known Limitations (document these in the repo README, don't silently hide them)

1. Wash trading between two or more colluding wallets can still pass the eligibility filters if each wallet individually meets the round-trip/token/volume floors — this is a first-pass defense, not a guarantee.
2. FIFO round-trip matching is an approximation; it will occasionally misattribute PnL when a wallet has complex overlapping positions in the same token.
3. Bitquery is a third-party indexer, not Pump.fun-official — if Bitquery's indexing lags or has a bug, the leaderboard inherits that error. No cross-validation source is included in this milestone (deliberately, to keep v1 simple) — consider adding one in a later milestone if data quality issues surface.
4. Token-creator exclusion (§3.1) depends on correctly identifying the creator address from Pump.fun's `create`/`create_v2` instruction data — verify this mapping is reliable during implementation, it's the filter most likely to need adjustment.
