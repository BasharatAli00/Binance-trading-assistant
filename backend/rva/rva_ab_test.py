"""A/B test: RVA WITHOUT the momentum tilt vs WITH it.

Judged the honest way: full period, then in-sample vs out-of-sample. The tilt
is only kept if it improves the UNSEEN (out-of-sample) result without wrecking
the drawdown protection.
"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import rva_strategy as rva
import rva_backtest as bt
from rva_backtest_daily import load_daily

df = load_daily()

OFF = dict(rva.PARAMS, momentum_tilt=False)
ON  = dict(rva.PARAMS, momentum_tilt=True)


def run(params, a, b):
    d = rva.add_indicators(df.iloc[a:b].reset_index(drop=True), params)
    _, _, s = bt.simulate(d, params=params, prepared=True)
    return s


def line(tag, s):
    print(f"  {tag:26} ret {s['total_return']*100:8.1f}%  Sharpe {s['sharpe']:.2f}  "
          f"maxDD {s['max_dd']*100:6.1f}%  Calmar {s['calmar']:.2f}  avgHold {s['avg_weight']*100:.0f}%")


N = len(df)
cut = int(N * 0.60)
segments = [("FULL 2017-2026", 0, N),
            ("IN-SAMPLE 2017-2022", 0, cut),
            ("OUT-OF-SAMPLE 2023-2026 (unseen)", cut, N)]

for name, a, b in segments:
    s_off = run(OFF, a, b)
    s_on  = run(ON, a, b)
    print(f"\n=== {name} ===   (buy&hold: ret {s_off['bh_total_return']*100:.0f}%  "
          f"Sharpe {s_off['bh_sharpe']:.2f}  maxDD {s_off['bh_max_dd']*100:.0f}%)")
    line("OLD (no tilt)", s_off)
    line("NEW (momentum tilt)", s_on)
