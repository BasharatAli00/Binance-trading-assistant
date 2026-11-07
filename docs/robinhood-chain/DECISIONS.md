# Robinhood Chain System: Intelligence, Signals & Decisions (Phase 3)

Paper mode. In Phase 3 the broker is **IntentOnlyBroker**: it records entry intents and executes nothing. Phase 4 replaces it with the PaperBroker (realistic fill model); the live broker stays disabled.

## Flow (every `RHC_DECISION_CYCLE_S`, for watch-listed pools only)
```
closed 1m candles (rhc_candle) ──► features (as of the last closed minute)
wallet trades + closed wallet positions ──► smart-money flow (as of the same minute)
market volume + ETH reference candles ──► regime + no-trade codes
                                      │
strategies ──► SETUP_DETECTED ──(next closed candle)──► confirm? ──no──► NOT_CONFIRMED / EXPIRED
                                                           │yes
                                     risk engine (kill switch, regime, caps, daily loss, cooldown, sizing)
                                         │blocked                         │allowed
                                    REJECTED_RISK                    ENTER_INTENT ──► broker
```
Every row goes to `rhc_decision` with its evidence: the features used, each strategy condition (value, threshold, pass or fail), the regime, and the risk state with every sizing cap. `GET /api/rhc/decisions` returns them.

## No look-ahead (enforced and tested)
- **Features:** `rhc_features.features(candles, as_of)` only uses candles whose bucket ended at or before `as_of`. Future rows passed in by mistake are ignored; a test passes future candles and requires identical output.
- **Wallet scores:** only positions **closed before** `as_of` count, and smart flow only uses trades strictly before `as_of`.
- **Regime:** only 5-minute buckets closed before `as_of`.
- **Entries:** decisions are made on closed candles, and an entry needs a **later** candle to confirm. The entry reference moves to the confirming candle's close.
- **Replay:** `rhc_decision.replay()` runs the same `DecisionCore` over stored data. Two runs over all recorded candles (19 pools, 2026-11-08) produced identical decisions.

## Features (per pool, 1-minute candles)
- **Price and returns:** 1/5/15/60-minute returns; distance from the 60-minute VWAP; 30-minute breakout and distance to the prior high.
- **Volatility:** ATR(14) as a fraction of price, ATR ratio (compression), 1-minute range and close position.
- **Volume and flow:** 5-minute volume against the median 5-minute volume of the previous hour; buy/sell USD imbalance over 5 and 15 minutes; traders over 15 minutes versus the previous 15; large trades.
- **Liquidity:** 15- and 60-minute change. v2 pools use USD depth; v3/v4 use in-range liquidity.
- **Data quality:** coverage (minutes with trades out of the last 60) and minutes since the last trade.
- **Smart money:** 15-minute buy USD and buyer count from "smart" wallets, as of the decision time.

## Strategies (`rhc_strategies.py`; all thresholds are **unvalidated defaults**)
| Strategy | Fires when | Default |
|---|---|---|
| `volume_breakout` | close > prior 30-minute high, 5-minute volume ≥ 3× baseline, buy share ≥ 60%, ≥ 8 traders, ≤ 3% above the breakout | on |
| `momentum` | +5% over 15 minutes and +10% over 60, traders up ≥ 30%, buy share ≥ 55%, ≤ 25% above VWAP, liquidity not down > 10% | on |
| `vol_expansion` | ATR compressed (ratio ≤ 0.6), expansion candle ≥ 2.5 × ATR closing in its top 25%, buy share ≥ 60% | on |
| `liquidity_growth` | liquidity +30% in 60 minutes, price not falling, buy share ≥ 55%, ≥ 10 traders | on |
| `smart_money` | ≥ $500 of buys from ≥ 2 smart wallets in 15 minutes | **off** until validated |

All strategies also require coverage ≥ 50% and a trade within the last 3 minutes.
- **Stop:** 3 × ATR, clamped to 4–12%.
- **Targets:** 1.5R and 3R.
- **Time stop:** 240 minutes.

## Confirmation
The next closed candle must not be ≥ 1% below the entry reference (`CONFIRM_FAILED_DIP`), must not be ≥ 3% above it (`CONFIRM_FAILED_CHASE`), and must have a 5-minute buy share ≥ 50% (`CONFIRM_FAILED_FLOW`). With no candle within 3 minutes the setup `EXPIRED`s; this is time-based, so it works even if the pool stops trading. After a confirmation, the same pool and strategy is quiet for `RHC_SIGNAL_COOLDOWN_MIN`.

## Regime & no-trade rules
- **Regime label:** the percentile of the last hour's market-wide volume within the trailing 24 hours: hot ≥ 80th, cold ≤ 20th, unknown with under 2 hours of history.
- **No new entries when:**
  - the regime is `REGIME_COLD`;
  - ETH fell ≥ 3% in an hour (`ETH_DUMP`);
  - the indexer lags more than 90 s (`DATA_LAG`);
  - optionally `REGIME_UNKNOWN` (off by default).
- **Caveat:** market volume is the sum over *tracked* pools, so changes in the tracked set shift the series.

## Risk engine (`rhc_risk.py`)
- **Size:** paper equity ($1,000) × risk per trade (1%) ÷ stop distance, clamped by:
  - the maximum position ($50);
  - the remaining total-exposure headroom (25% of equity);
  - the remaining per-token headroom ($50);
  - a **liquidity cap**: screening size × max impact ÷ simulated impact.
- **Too small:** below $10 → `SIZE_BELOW_MIN`.
- **Blocks:** `KILL_SWITCH`, `NO_TRADE_*`, `MAX_OPEN_POSITIONS` (5), `DAILY_LOSS_LIMIT` (3% of equity, realized + unrealized), `TOKEN_COOLDOWN` (60 minutes after an exit), `INVALID_STOP`.
- **Kill switch:** `POST /api/rhc/kill-switch {"enabled": true, "reason": "..."}`, or `RHC_KILL_SWITCH=true` in the environment.

## Wallet intelligence (`rhc_wallets.py`)
- **Inputs:** trades with resolved senders (`tx.from`) are stored for **watch-listed pools only** (`rhc_wallet_trade`, kept 3 days). Closed positions are derived every 10 minutes using average cost and kept 30 days.
- **Score:** (wins + 1) / (n + 2). A wallet counts as "smart" with ≥ 5 closed positions, a score ≥ 0.6 and a positive median return.
- **Predictive value:** `GET /api/rhc/research/smart-money` tests whether smart flow predicts the next hour's return, on the later half of the data only. It reports **"insufficient sample"** below 200 samples and draws no conclusion before then.
- **Limits:**
  - wallets that bought before a pool was watch-listed are ignored for that pool;
  - one person running many wallets looks like many traders;
  - gas costs and transfers between a wallet's own addresses are not modelled.

## API
- `GET /api/rhc/decisions?pool_id=&action=`
- `GET /api/rhc/features?pool_id=`
- `GET /api/rhc/regime`
- `GET /api/rhc/wallets/top`
- `GET /api/rhc/research/smart-money`
- `GET/POST /api/rhc/kill-switch`
