"""Backtest for the RVA allocator (rva_strategy.py) on BTC/USDT 1h.

Simulates a fractional long-only spot allocation with realistic fees +
slippage and a rebalance band (so we don't pay fees churning tiny weight
changes). Reports the metrics that decide whether a strategy is worth real
money: annualised Sharpe & Sortino, max drawdown, Calmar, CAGR, % time in
market, and a head-to-head vs buy & hold and vs a naive trend filter.

No lookahead: the target weight decided at the close of bar t is applied to
the return earned from bar t -> t+1 (weights are shifted by 1).

Run:
    python rva_backtest.py                 # full-period + out-of-sample split
    python rva_backtest.py --refresh       # re-fetch candles from Binance first
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import rva_strategy as rva

# Reuse the existing 2yr hourly cache the repo already maintains.
CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "_btc_1h_cache.csv")
FEE = 0.001         # 0.10% taker per side (Binance spot)
SLIPPAGE = 0.0005   # 0.05% adverse fill
START_EQUITY = 5000.0
BPY = rva.BARS_PER_YEAR


def load_data(refresh=False):
    if os.path.exists(CACHE_FILE) and not refresh:
        df = pd.read_csv(CACHE_FILE, parse_dates=["timestamp"])
    else:
        from binance.client import Client
        print("Fetching BTCUSDT 1h from Binance (2 years)...")
        client = Client(requests_params={"timeout": 30})
        kl = client.get_historical_klines("BTCUSDT", Client.KLINE_INTERVAL_1HOUR, "2 years ago UTC")
        df = pd.DataFrame(kl, columns=["Open time", "Open", "High", "Low", "Close", "Volume",
                                       "Close time", "qav", "trades", "tbbav", "tbqav", "ignore"])
        df["timestamp"] = pd.to_datetime(df["Open time"], unit="ms")
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            df[c] = pd.to_numeric(df[c])
        df = df[["timestamp", "Open", "High", "Low", "Close", "Volume"]]
        df.to_csv(CACHE_FILE, index=False)
    print(f"Loaded {len(df)} 1h candles: {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}")
    return df


def simulate(df, params=None, prepared=False):
    """Run the allocation sim. Returns (equity_series, weight_applied, stats)."""
    p = dict(rva.PARAMS)
    if params:
        p.update(params)

    if not prepared:
        df = rva.add_indicators(df, p)
    w_target = rva.target_weights(df, p)

    price = df["Close"].to_numpy()
    wt = w_target.to_numpy()
    n = len(df)

    cash = START_EQUITY
    units = 0.0            # BTC held
    w_actual = 0.0         # current fraction of equity in BTC
    equity = np.empty(n)
    applied = np.empty(n)
    n_rebal = 0
    fee_paid = 0.0

    # Warmup: skip until indicators are valid.
    warmup = max(p["trend_ema"], p["vol_win"], p["slope_win"]) + 2

    for i in range(n):
        v = cash + units * price[i]
        if i < warmup or np.isnan(wt[i]):
            equity[i] = v
            applied[i] = w_actual
            continue

        target = wt[i]
        # Rebalance only if the target has drifted beyond the band.
        if abs(target - w_actual) > p["rebalance_band"] or (target == 0.0 and w_actual > 0):
            desired_btc_val = target * v
            delta_val = desired_btc_val - units * price[i]     # +buy / -sell
            cost = abs(delta_val) * (FEE + SLIPPAGE)
            # execute
            units = desired_btc_val / price[i]
            cash = v - desired_btc_val - cost
            fee_paid += cost
            w_actual = target
            n_rebal += 1

        v = cash + units * price[i]
        equity[i] = v
        applied[i] = w_actual

    eq = pd.Series(equity, index=df.index)
    stats = _metrics(df, eq, applied, n_rebal, fee_paid, warmup, p.get("bars_per_year", BPY))
    return eq, pd.Series(applied, index=df.index), stats


def _metrics(df, eq, applied, n_rebal, fee_paid, warmup, bpy=BPY):
    r = eq.pct_change().dropna()
    bh_r = df["Close"].pct_change().dropna()

    def sharpe(x):
        s = x.std()
        return (x.mean() / s * np.sqrt(bpy)) if s > 0 else 0.0

    def sortino(x):
        d = x[x < 0].std()
        return (x.mean() / d * np.sqrt(bpy)) if d > 0 else 0.0

    def maxdd(series):
        peak = series.cummax()
        return ((series - peak) / peak).min()

    yrs = len(df) / bpy
    tot = eq.iloc[-1] / eq.iloc[warmup] - 1 if warmup < len(eq) else eq.iloc[-1] / START_EQUITY - 1
    cagr = (eq.iloc[-1] / START_EQUITY) ** (1 / yrs) - 1 if yrs > 0 else 0.0
    dd = maxdd(eq)
    bh_dd = maxdd(df["Close"])
    bh_tot = df["Close"].iloc[-1] / df["Close"].iloc[0] - 1

    return {
        "years": yrs,
        "total_return": tot,
        "cagr": cagr,
        "sharpe": sharpe(r),
        "sortino": sortino(r),
        "max_dd": dd,
        "calmar": (cagr / abs(dd)) if dd < 0 else float("inf"),
        "time_in_market": float(np.mean(np.array(applied) > 0.01)),
        "avg_weight": float(np.mean(applied)),
        "rebalances": n_rebal,
        "fees_paid": fee_paid,
        "final_equity": eq.iloc[-1],
        # benchmarks
        "bh_total_return": bh_tot,
        "bh_cagr": (df["Close"].iloc[-1] / df["Close"].iloc[0]) ** (1 / yrs) - 1,
        "bh_sharpe": sharpe(bh_r),
        "bh_sortino": sortino(bh_r),
        "bh_max_dd": bh_dd,
        "bh_calmar": ((df["Close"].iloc[-1] / df["Close"].iloc[0]) ** (1 / yrs) - 1) / abs(bh_dd),
    }


def _print_block(title, s):
    print(f"\n=== {title} ===")
    print(f"  Period            : {s['years']:.2f} years")
    print(f"  {'':18}{'STRATEGY':>12}{'BUY & HOLD':>14}")
    print(f"  Total return      {s['total_return']*100:>11.1f}%{s['bh_total_return']*100:>13.1f}%")
    print(f"  CAGR              {s['cagr']*100:>11.1f}%{s['bh_cagr']*100:>13.1f}%")
    print(f"  Sharpe (ann.)     {s['sharpe']:>12.2f}{s['bh_sharpe']:>14.2f}")
    print(f"  Sortino (ann.)    {s['sortino']:>12.2f}{s['bh_sortino']:>14.2f}")
    print(f"  Max drawdown      {s['max_dd']*100:>11.1f}%{s['bh_max_dd']*100:>13.1f}%")
    print(f"  Calmar            {s['calmar']:>12.2f}{s['bh_calmar']:>14.2f}")
    print(f"  Time in market    {s['time_in_market']*100:>11.1f}%")
    print(f"  Avg allocation    {s['avg_weight']*100:>11.1f}%")
    print(f"  Rebalances/fees   {s['rebalances']:>8}   ${s['fees_paid']:,.0f}")
    print(f"  Final equity      ${s['final_equity']:>11,.0f}")


def naive_trend_benchmark(df):
    """Fully-in or fully-out on a simple EMA200 filter (no vol targeting, no
    hysteresis) — the 'obvious' version, so we can see what RVA's extra
    machinery actually buys us."""
    d = df.copy()
    ema = d["Close"].ewm(span=200, adjust=False).mean()
    w = (d["Close"] > ema).astype(float)
    # apply next bar, flat fee model on switches
    ret = d["Close"].pct_change().fillna(0).to_numpy()
    ws = w.shift(1).fillna(0).to_numpy()
    switches = np.abs(np.diff(ws, prepend=0))
    eq = START_EQUITY
    curve = []
    for i in range(len(d)):
        eq *= (1 + ws[i] * ret[i])
        eq -= eq * switches[i] * (FEE + SLIPPAGE)
        curve.append(eq)
    curve = pd.Series(curve, index=d.index)
    peak = curve.cummax()
    dd = ((curve - peak) / peak).min()
    yrs = len(d) / BPY
    r = curve.pct_change().dropna()
    sh = (r.mean() / r.std() * np.sqrt(BPY)) if r.std() > 0 else 0
    return {"total": curve.iloc[-1] / START_EQUITY - 1, "cagr": (curve.iloc[-1]/START_EQUITY)**(1/yrs)-1,
            "sharpe": sh, "max_dd": dd}


if __name__ == "__main__":
    refresh = "--refresh" in sys.argv
    df = load_data(refresh=refresh)
    df = rva.add_indicators(df)

    # ---- Full period ----
    eq, w, stats = simulate(df, prepared=True)
    _print_block("FULL PERIOD", stats)

    nb = naive_trend_benchmark(df)
    print(f"\n  [ref] Naive EMA200 in/out : ret {nb['total']*100:+.1f}%  CAGR {nb['cagr']*100:+.1f}%  "
          f"Sharpe {nb['sharpe']:.2f}  maxDD {nb['max_dd']*100:.1f}%")

    # ---- Out-of-sample split (first 60% = "seen", last 40% = untouched) ----
    cut = int(len(df) * 0.60)
    is_df = df.iloc[:cut].reset_index(drop=True)
    oos_df = df.iloc[cut:].reset_index(drop=True)
    _, _, is_stats = simulate(is_df, prepared=True)
    _, _, oos_stats = simulate(oos_df, prepared=True)
    _print_block("IN-SAMPLE (first 60%)", is_stats)
    _print_block("OUT-OF-SAMPLE (last 40%, unseen)", oos_stats)

    print("\nInterpretation:")
    print("  - Value = higher Sharpe/Sortino & shallower drawdown than buy&hold.")
    print("  - If OOS Sharpe stays clearly > 1 and maxDD << buy&hold, the edge is real.")
