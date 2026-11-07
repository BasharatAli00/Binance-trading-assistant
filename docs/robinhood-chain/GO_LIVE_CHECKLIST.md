# Go-Live Checklist (gate before real execution may even be *considered*)

**Passing this checklist does not enable anything.** Live trading is hard-disabled in code. Turning it on needs a **separate, explicitly approved change**.

`GET /api/rhc/go-live-gate` evaluates items 1–6 automatically. Items 7–9 are manual, stored in `rhc_kv` under the key `go_live_manual`. Item 10 is a code change.

| # | Condition | How it's checked |
|---|---|---|
| 1 | Forward paper sample is sufficient: ≥ 200 closed trades, ≥ 30 tokens, ≥ 21 days | `rhc_metrics.sample_gate` |
| 2 | Forward paper expectancy **95% CI lower bound > 0** after all modelled costs | bootstrap CI |
| 3 | Profit factor CI lower bound ≥ `RHC_GATE_MIN_PF_LO` (1.0) | bootstrap CI |
| 4 | Max drawdown ≤ `RHC_GATE_MAX_DD_PCT` (15%) **on a sufficient sample** | equity curve |
| 5 | Backtest hold-out (last 20% of time) expectancy CI lower bound > 0 | walk-forward hold-out |
| 6 | Forward paper expectancy lies inside the backtest hold-out CI (no overfit signal) | consistency check |
| 7 | A **dedicated low-balance wallet** is configured and approved. The existing manual desk's key and global switches must **not** be reused. | manual |
| 8 | Hard per-trade and daily caps plus the kill switch tested end to end | manual |
| 9 | A small-size live pilot is approved by the owner (e.g. ≤ $5 per trade, ≤ $25 per day, for 1–2 weeks) | manual |
| 10 | `LiveBroker` wired and `RHC_LIVE_ENABLED` changed from a constant to a guarded flag, in a reviewed change | code review |

**Current status (2026-11-08):** not ready. There are no closed forward paper trades yet, and the backtest has 2 trades. Every automatic check except the code item is waiting on data, and the code item is intentionally disabled.

## What the dedicated-wallet change must include (when approved)
- Its own key variable (for example `RHC_LIVE_PRIVATE_KEY`) and an expected-address check, separate from `ROBINHOOD_PRIVATE_KEY`.
- Hard caps enforced **inside** the LiveBroker, independent of the risk engine: maximum USD per trade, per day and open at once.
- A slippage limit on every swap. Note that the existing desk's `ROBINHOOD_MAX_SLIPPAGE_BPS` is defined but never applied.
- A kill switch checked immediately before signing.
- Live fills reconciled against the paper model, so the overstatement can be measured.
