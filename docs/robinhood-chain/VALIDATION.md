# Robinhood Chain System: Paper Trading & Validation (Phase 4)

**Nothing in this system trades real money.** `RHC_LIVE_ENABLED` is a constant `False` in code, the `LiveBroker` refuses every order, and tests verify both.

## Two kinds of evidence
| | Forward paper trading (`PaperBroker`) | Backtest (`rhc_backtest`) |
|---|---|---|
| Data | Live chain, in real time | Recorded candles |
| Fills | **Simulated through the pool's own contract at fill time** (`eth_call`) | Modelled from candles (historical state isn't available: the node keeps ~100 s) |
| Signals, risk, exits | Same `DecisionCore` and `manage()` | Same `DecisionCore` and `manage()` |
| Trust | Higher | Lower: use it for sanity and stability, not proof |

## Forward paper fill model (`rhc_paper.py`)
1. **Latency:** the order fills `RHC_PAPER_LATENCY_S` (2 s) after the decision, against the pool state **at that time**, so trades that land in between count against us. The decision itself is made on a closed candle, up to one decision cycle (30 s) old.
2. **Entry:** the simulator buys the intended USD size through the pool. Fees, hook fees, price impact and token taxes are all in the result.
3. **Exit:** the simulator sells exactly the tokens held.
   - The tokens are supplied by overriding the token's balance slot.
   - For non-standard tokens whose slot can't be found, a round trip of similar size is used instead, with half its cost deducted again (conservative), and the fill is flagged `approx`.
4. **Gas:** simulated gas × 1.6 (router overhead) × live gas price × ETH/USD, with a $0.01 floor. Measured on 2026-11-08: median real swap ≈ 190k gas, 0.02 gwei, **≈ $0.01**; p90 ≈ $0.05; no L1 data component on this chain.
5. **Safety haircut:** `RHC_PAPER_EXTRA_SLIP_BPS` (30 bps) on **every** fill.
6. **Failed transactions:** `RHC_PAPER_FAIL_PROB` (2%), deterministic per order. A failure pays gas and fills nothing.
7. **Stuck positions:** a position whose sell fails `RHC_PAPER_STUCK_AFTER` times becomes `STUCK` and is booked as a **100% loss**.
8. **Emergency exit:** if a held pool is re-screened and rejected with a permanent code (honeypot, rug, upgradeable, …).

**Measured on live state (2026-11-08):** an immediate $25 buy-then-stop on three watch-listed pools cost **0.72%, 1.47% and 1.54%** all-in.

## Exits (`manage()`, shared by both)
- **Stop:** checked against the candle **low**. A gap through the stop fills at the **open**.
- **Same-candle ambiguity:** if the stop and a target are both touched in one candle, the **stop is assumed first**.
- **TP1:** sell `RHC_TP1_FRACTION` (50%), move the stop to break-even, then trail the peak by the original stop distance.
- **TP2:** sell the rest. A **time stop** applies at `RHC_TIME_STOP_MIN`.
- **Backtest end:** positions still open when the data ends are closed at the last close with costs (`END_OF_DATA`), so open losers can't vanish.

## Backtest fill model
- **Entry:** the confirming close × (1 + side cost + haircut). **Exit:** the level (or the open on a gap) × (1 − side cost − haircut).
- **Side cost:** half the round-trip cost measured when the pool was screened (`RHC_BT_DEFAULT_COST_PCT` = 1% if unknown), plus `RHC_BT_LATENCY_ATR` (0.25) × ATR, plus gas per leg.
- **Walk-forward:** parameters are fixed (nothing is fitted), so trades are split into `RHC_BT_FOLDS` time folds to show stability. The last `RHC_BT_OOS_FRACTION` (20%) of time is reported separately as hold-out.

## Metrics (`rhc_metrics.py`)
- **Reported:** win rate (Wilson 95% CI), profit factor (bootstrap CI), net P&L, expectancy in USD and R (bootstrap CI), average win and loss, payoff ratio, max drawdown, trades per day, average hold time and exit reasons. Each is also broken down **by strategy and by regime**.
- **Bootstrap:** fixed seed, so the same trades always give the same numbers.
- **Sample gate:** fewer than **200 trades**, **30 tokens** or **21 days** gives the verdict *"insufficient sample - no conclusion"*, even if every trade won (tested).
- **Above the gate:** *"positive expectancy"* only when the expectancy CI lower bound is above 0; otherwise *"edge not demonstrated"*.

## Where paper results will overstate live results
- **Our fills are instant:** a real transaction can sit behind other transactions in the same block, and bots react to large buys. The re-simulation after latency captures *completed* trades in between, but not same-block ordering.
- **Simulator caller vs real router:** Relay or aggregator routing, approvals and permit flows add gas and can route worse.
- **Exact-price exits don't exist:** stops fill at the simulated post-latency price, and real exits in fast dumps can be worse still.
- **Partial fills and reverts:** a real swap can revert on slippage limits. We model a flat failure rate, not one that rises with volatility.
- **Owner actions after entry:** tax raises, blacklisting and liquidity pulls between checks. The 30-minute re-screen and emergency exit only partly cover these.
- **Approximate exits** (`approx=true`) for non-standard tokens.
- **Survivorship in the pool universe:** discovery starts from pools active enough to be noticed.
- **Small sample and a hype-phase market:** whatever works now may stop working.

**Treat any paper edge as an upper bound.** The go-live gate requires a margin for all of this.

## API
- `GET /api/rhc/paper/positions?status=open|closed|stuck`
- `GET /api/rhc/paper/fills?position_id=`
- `GET /api/rhc/performance`: forward paper metrics, by strategy and regime, with the sample gate.
- `GET /api/rhc/backtest?days=`: event-driven backtest + walk-forward on recorded data. Stored in `rhc_backtest_run`.
- `GET /api/rhc/go-live-gate`: the checklist below, evaluated live.
