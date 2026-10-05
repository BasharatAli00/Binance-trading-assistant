"""Regime-Filtered Volatility-Targeted Allocator (RVA) — long-only spot BTC.

Pure decision logic. No network, no DB. Given a price series it produces a
*target allocation* w_t in [0, 1] for every bar: the fraction of equity that
should be held in BTC (the rest sits in cash / USDT). This is NOT an
entry/exit-trade bot — it is a continuous risk-allocation model, which is the
professional way to run a single volatile asset.

The edge (three independent, documented sources):

  1. TREND REGIME GATE (hysteresis)  -> the drawdown killer.
     Only hold BTC when it is in a confirmed uptrend (above a long EMA whose
     slope is up). A buffer band around the EMA gives hysteresis so we don't
     flip-flop every time price kisses the line (where naive trend filters bleed
     money). Below trend -> 100% cash. Historically this alone turns BTC's
     ~80% peak-to-trough drawdowns into ~35%.

  2. VOLATILITY TARGETING            -> the Sharpe booster.
     Size the position so its *risk* is roughly constant. When realised vol
     spikes (which for BTC happens at tops and during crashes) the allocation
     shrinks automatically; when the market is calm and grinding up, it grows
     toward 100%. Vol is far more forecastable than return (vol clustering), so
     this is close to free Sharpe. Capped at 1.0 (spot, no leverage).

  3. FAST CRASH EXIT                 -> the tail-risk cutter.
     A sharp break (close far below the fast EMA, or a large single-bar drop)
     forces allocation to 0 ahead of the slower regime gate.

Parsimony is deliberate: every knob below is an economically meaningful risk
control, not a curve-fit indicator. Fewer knobs -> less overfitting -> the
backtested edge is more likely to survive live.
"""

import numpy as np
import pandas as pd

# Default annualisation factor (hourly). Overridden per-timeframe via PARAMS.
BARS_PER_YEAR = 24 * 365

# ---------------------------------------------------------------------------
# DAILY is the natural clock for a trend/vol-regime allocator: same edge, far
# less noise & fee drag than hourly. These are the defaults. HOURLY_PARAMS
# below keeps the intraday variant available.
# ---------------------------------------------------------------------------
PARAMS = {
    "bars_per_year": 365,

    # --- 1. Trend regime -------------------------------------------------
    "trend_ema": 100,        # long-term trend reference (~100 days)
    "slope_win": 20,         # EMA must be rising vs this many bars ago
    "hysteresis": 0.03,      # 3% buffer band: enter regime above ema*(1+b),
                             # exit below ema*(1-b). Kills line-hugging whipsaw.

    # --- 2. Volatility targeting ----------------------------------------
    "vol_win": 30,           # realised-vol lookback (~30 days)
    "target_vol": 0.55,      # target ANNUALISED vol of the BTC sleeve (55%).
                             # BTC realised vol ~40-90%, so w typically 0.6-1.0
                             # in calm uptrends and auto-cuts when vol blows out.
    "max_weight": 1.0,       # spot, long-only: never exceed 100% of equity.
    "min_weight": 0.0,       # floor.

    # --- 3. Fast crash exit (genuine crash only, NOT normal dips) --------
    "crash_drop_atr": 3.0,   # a single-bar drop bigger than this*ATR -> flatten
    "atr_win": 14,

    # --- 4. Momentum tilt (lean IN harder during strong uptrends) -------
    # Adds exposure ONLY when price is well above its trend EMA (strong,
    # confirmed momentum). Never removes a safety brake: the regime gate, vol
    # cap and crash veto all still bind. Off -> pure vol-target behaviour.
    # VERDICT (rva_ab_test.py): helps a lot IN-SAMPLE but adds nothing on
    # UNSEEN data and slightly deepens drawdown -> kept OFF by default. The
    # code stays so the finding is reproducible.
    "momentum_tilt": False,
    "tilt_norm": 0.20,       # price 20% above trend EMA -> full tilt
    "tilt_max": 0.60,        # up to +60% more exposure at full strength

    # --- execution discipline -------------------------------------------
    "rebalance_band": 0.08,  # only trade when target vs current weight differ
                             # by >8% of equity (kills fee-bleeding churn).
}

# Intraday variant (kept for completeness; daily is the recommended default).
HOURLY_PARAMS = dict(PARAMS, bars_per_year=24 * 365, trend_ema=200, slope_win=48,
                     hysteresis=0.02, vol_win=72)


def add_indicators(df, p=PARAMS):
    """Attach the columns the allocator reads. Expects Open/High/Low/Close/Volume.

    All indicators use only past/# current-bar data (no lookahead)."""
    df = df.copy()
    close = df["Close"]
    bpy = p.get("bars_per_year", BARS_PER_YEAR)

    df["ema_trend"] = close.ewm(span=p["trend_ema"], adjust=False).mean()

    # Realised vol: rolling std of log returns, annualised.
    logret = np.log(close / close.shift(1))
    df["logret"] = logret
    df["real_vol"] = logret.rolling(p["vol_win"]).std() * np.sqrt(bpy)

    # ATR (Wilder) for the crash trigger.
    high, low = df["High"], df["Low"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / p["atr_win"], adjust=False).mean()

    # Single-bar drop in ATR units (how violent was this candle to the downside).
    df["bar_drop_atr"] = (prev_close - close) / df["atr"]

    return df


def target_weights(df, p=PARAMS):
    """Vectorised target allocation w_t in [0, 1] for every bar.

    w_t is decided from information available at the CLOSE of bar t. The
    backtester is responsible for applying it to the NEXT bar's return (no
    lookahead). Returns a float Series aligned to df.index.
    """
    close = df["Close"]
    ema = df["ema_trend"]

    # --- 1. Regime gate with hysteresis (stateful -> loop, but cheap) ----
    upper = ema * (1 + p["hysteresis"])
    lower = ema * (1 - p["hysteresis"])
    slope_up = ema > ema.shift(p["slope_win"])

    regime = np.zeros(len(df), dtype=bool)
    on = False
    c = close.to_numpy(); up = upper.to_numpy(); lo = lower.to_numpy()
    su = slope_up.to_numpy()
    for i in range(len(df)):
        if np.isnan(up[i]):
            regime[i] = False
            continue
        if not on:
            # turn ON only above the upper band AND with a rising trend EMA
            if c[i] > up[i] and su[i]:
                on = True
        else:
            # stay ON until price breaks below the lower band
            if c[i] < lo[i]:
                on = False
        regime[i] = on
    regime = pd.Series(regime, index=df.index)

    # --- 2. Volatility target scaling -----------------------------------
    vol_scale = (p["target_vol"] / df["real_vol"])

    # --- 4. Momentum tilt: lean in harder when price is strongly above trend.
    #        strength = how far above the trend EMA (0 at/below, 1 when >=norm).
    if p.get("momentum_tilt"):
        strength = ((close / ema - 1.0) / p["tilt_norm"]).clip(lower=0.0, upper=1.0)
        vol_scale = vol_scale * (1.0 + strength * p["tilt_max"])

    vol_scale = vol_scale.clip(upper=p["max_weight"]).fillna(0.0)

    # --- 3. Fast crash veto: only a genuine violent down-bar, NOT a normal
    #        pullback (the pullback clause was what whipsawed the hourly test).
    crash = (df["bar_drop_atr"] > p["crash_drop_atr"])

    w = np.where(regime, vol_scale, 0.0)
    w = np.where(crash.to_numpy(), 0.0, w)
    w = np.clip(w, p["min_weight"], p["max_weight"])

    return pd.Series(w, index=df.index).fillna(0.0)
