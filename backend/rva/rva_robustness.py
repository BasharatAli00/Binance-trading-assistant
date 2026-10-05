"""Parameter-robustness sweep for RVA on daily BTC.

A real edge is a broad plateau: Sharpe/Calmar stay strong as you vary the knobs.
An overfit curve is a lonely spike that collapses one step away. This sweeps the
three economically meaningful knobs and shows the distribution of outcomes.
"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import rva_strategy as rva
import rva_backtest as bt
from rva_backtest_daily import load_daily

df = load_daily()
base = rva.add_indicators(df, rva.PARAMS)

rows = []
for trend in [60, 80, 100, 120, 150]:
    for tvol in [0.40, 0.50, 0.55, 0.65, 0.75]:
        for hyst in [0.02, 0.03, 0.05]:
            p = dict(rva.PARAMS, trend_ema=trend, target_vol=tvol, hysteresis=hyst)
            d = rva.add_indicators(df, p)
            _, _, s = bt.simulate(d, params=p, prepared=True)
            rows.append((trend, tvol, hyst, s["sharpe"], s["calmar"],
                         s["total_return"]*100, s["max_dd"]*100))

R = pd.DataFrame(rows, columns=["trend", "tvol", "hyst", "sharpe", "calmar", "ret%", "maxDD%"])
print(f"\nSwept {len(R)} parameter combos. Buy&hold: Sharpe 0.79, maxDD -83.2%, ret 1373%\n")
print("Distribution across ALL combos:")
print(f"  Sharpe  : min {R.sharpe.min():.2f}  median {R.sharpe.median():.2f}  max {R.sharpe.max():.2f}")
print(f"  Calmar  : min {R.calmar.min():.2f}  median {R.calmar.median():.2f}  max {R.calmar.max():.2f}")
print(f"  maxDD % : best {R['maxDD%'].max():.1f}  median {R['maxDD%'].median():.1f}  worst {R['maxDD%'].min():.1f}")
print(f"  return %: min {R['ret%'].min():.0f}  median {R['ret%'].median():.0f}  max {R['ret%'].max():.0f}")
beat = (R.sharpe > 0.79).mean() * 100
half = (R['maxDD%'] > -45).mean() * 100
print(f"\n  % of combos with Sharpe > buy&hold (0.79) : {beat:.0f}%")
print(f"  % of combos with maxDD better than -45%   : {half:.0f}%")
print("\nTop 8 by Calmar (return per unit of drawdown):")
print(R.sort_values("calmar", ascending=False).head(8).to_string(index=False))
