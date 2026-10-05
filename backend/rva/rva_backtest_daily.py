"""Backtest the RVA allocator on 9 years of DAILY BTC/USDT (2017-2026).

Same engine and honest metrics as the hourly test, but on the timeframe the
strategy was actually designed for and across real bull AND bear cycles. This
is the test that decides whether the edge is real.

Run:
    python rva_backtest_daily.py
    python rva_backtest_daily.py --refresh   # re-fetch daily candles first
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import rva_strategy as rva
import rva_backtest as bt   # reuse simulate() / _metrics() / _print_block()

CACHE = os.path.join(os.path.dirname(__file__), "_btc_1d_cache.csv")


def load_daily(refresh=False):
    if refresh or not os.path.exists(CACHE):
        import fetch_daily
        return fetch_daily.fetch()
    df = pd.read_csv(CACHE, parse_dates=["timestamp"])
    print(f"Loaded {len(df)} daily candles: {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}")
    return df


def per_year_breakdown(df, eq, w):
    """Yearly strategy vs buy&hold return + who was in the market."""
    d = pd.DataFrame({"ts": df["timestamp"].values, "eq": eq.values,
                      "w": w.values, "close": df["Close"].values})
    d["year"] = pd.DatetimeIndex(d["ts"]).year
    print(f"\n  {'Year':>6}{'Strat %':>10}{'B&H %':>10}{'AvgAlloc':>10}")
    for y, g in d.groupby("year"):
        s = g["eq"].iloc[-1] / g["eq"].iloc[0] - 1
        b = g["close"].iloc[-1] / g["close"].iloc[0] - 1
        print(f"  {y:>6}{s*100:>9.1f}{b*100:>10.1f}{g['w'].mean()*100:>9.1f}%")


if __name__ == "__main__":
    refresh = "--refresh" in sys.argv
    df = load_daily(refresh=refresh)

    # Daily costs: keep fee+slippage identical so comparison is apples-to-apples.
    df = rva.add_indicators(df, rva.PARAMS)

    eq, w, stats = bt.simulate(df, params=rva.PARAMS, prepared=True)
    # Fix annualisation for daily inside the printed stats:
    bt._print_block("FULL PERIOD  (2017-2026, daily)", stats)

    nb = bt.naive_trend_benchmark  # note: naive uses hourly BPY internally; skip for daily

    per_year_breakdown(df, eq, w)

    # Out-of-sample: train-era (2017-2022) vs unseen (2023-2026)
    cut = int(len(df) * 0.60)
    is_df = df.iloc[:cut].reset_index(drop=True)
    oos_df = df.iloc[cut:].reset_index(drop=True)
    _, _, is_stats = bt.simulate(is_df, params=rva.PARAMS, prepared=True)
    _, _, oos_stats = bt.simulate(oos_df, params=rva.PARAMS, prepared=True)
    bt._print_block("IN-SAMPLE (first 60%: ~2017-2022)", is_stats)
    bt._print_block("OUT-OF-SAMPLE (last 40%: ~2023-2026, unseen)", oos_stats)

    print("\nVerdict test:")
    print("  Worth it IF  ->  Sharpe > buy&hold  AND  maxDD roughly half of buy&hold,")
    print("               across BOTH in-sample and out-of-sample.")
