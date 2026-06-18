"""Backtest harness for the long-only pullback strategy (strategy.py).

Fetches ~2 years of BTCUSDT 1h candles from Binance (cached to a local CSV so
re-runs are instant), computes the same indicators the live system uses, then
replays the strategy bar-by-bar with realistic fees + slippage and reports the
metrics that actually matter: return, win rate, profit factor, max drawdown,
expectancy (avg R), and a buy & hold benchmark.

Run:  python backtest.py            # default params
      python backtest.py --grid     # small parameter sweep for calibration
"""
import os
import sys

import pandas as pd
import ta
from binance.client import Client

import strategy

CACHE_FILE = os.path.join(os.path.dirname(__file__), "_btc_1h_cache.csv")
START = "2 years ago UTC"
FEE = 0.001        # 0.1% per side
SLIPPAGE = 0.0005  # 0.05% adverse fill
START_EQUITY = 5000.0


def load_data(refresh=False):
    """Load candles from cache, or fetch from Binance and cache them."""
    if os.path.exists(CACHE_FILE) and not refresh:
        df = pd.read_csv(CACHE_FILE, parse_dates=["timestamp"])
        print(f"Loaded {len(df)} candles from cache ({df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]})")
        return df

    print(f"Fetching BTCUSDT 1h klines from Binance ({START})... this takes a moment")
    client = Client(requests_params={"timeout": 30})
    klines = client.get_historical_klines("BTCUSDT", Client.KLINE_INTERVAL_1HOUR, START)
    df = pd.DataFrame(klines, columns=[
        "Open time", "Open", "High", "Low", "Close", "Volume", "Close time",
        "qav", "trades", "tbbav", "tbqav", "ignore"])
    df["timestamp"] = pd.to_datetime(df["Open time"], unit="ms")
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        df[c] = pd.to_numeric(df[c])
    df = df[["timestamp", "Open", "High", "Low", "Close", "Volume"]]
    df.to_csv(CACHE_FILE, index=False)
    print(f"Fetched and cached {len(df)} candles ({df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]})")
    return df


def add_indicators(df):
    """Compute the indicators the strategy reads (matches live calculations)."""
    df = df.copy()
    df["ema20"] = ta.trend.EMAIndicator(df["Close"], window=20).ema_indicator()
    df["ema50"] = ta.trend.EMAIndicator(df["Close"], window=50).ema_indicator()
    df["ema200"] = ta.trend.EMAIndicator(df["Close"], window=200).ema_indicator()
    df["rsi"] = ta.momentum.RSIIndicator(df["Close"], window=14).rsi()
    macd = ta.trend.MACD(df["Close"], window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    df["atr"] = ta.volatility.AverageTrueRange(df["High"], df["Low"], df["Close"], window=14).average_true_range()
    df["adx"] = ta.trend.ADXIndicator(df["High"], df["Low"], df["Close"], window=14).adx()
    return df


def _row_ind(r):
    return {
        "close": r["Close"], "ema20": r["ema20"], "ema50": r["ema50"], "ema200": r["ema200"],
        "rsi": r["rsi"], "macd": r["macd"], "macd_signal": r["macd_signal"],
        "macd_hist": r["macd_hist"], "atr": r["atr"], "adx": r["adx"],
    }


def run_backtest(df, params=None, verbose=False, prepared=False):
    """Replay the strategy over df. Returns a metrics dict.

    Pass prepared=True if df already has indicator columns (avoids recomputing
    the expensive ADX/ATR each run during a grid search).
    """
    p = dict(strategy.PARAMS)
    if params:
        p.update(params)

    if not prepared:
        df = add_indicators(df).dropna().reset_index(drop=True)

    cash = START_EQUITY
    pos = None            # {"entry","stop","target","qty","high"}
    cooldown = 0
    trades = []
    equity_curve = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        ind = _row_ind(row)
        prev_ind = _row_ind(prev)
        price = row["Close"]

        # ---- Manage an open position FIRST (exits use this bar's range) ----
        if pos:
            exit_price = None
            reason = None
            # Chandelier stop can be hit intrabar (use the bar low).
            if row["Low"] <= pos["stop"]:
                exit_price = pos["stop"] * (1 - SLIPPAGE)
                reason = "Stop/Trail"
            else:
                me, mr = strategy.momentum_exit(ind, prev_ind, p)
                if me:
                    exit_price = price * (1 - SLIPPAGE)
                    reason = mr

            if exit_price is not None:
                proceeds = pos["qty"] * exit_price * (1 - FEE)
                cost_basis = pos["qty"] * pos["entry"]
                pnl = proceeds - cost_basis
                r_mult = pnl / (pos["qty"] * (pos["entry"] - pos["stop_init"])) if (pos["entry"] - pos["stop_init"]) > 0 else 0
                cash += proceeds
                trades.append({"pnl": pnl, "r": r_mult, "reason": reason,
                               "entry": pos["entry"], "exit": exit_price})
                pos = None
                cooldown = p["cooldown_bars"]
            else:
                # Ratchet the chandelier trailing stop up (never down).
                pos["high"] = max(pos["high"], row["High"])
                trail = strategy.trail_stop(pos["high"], ind["atr"], p)
                pos["stop"] = max(pos["stop"], trail)

        # ---- Look for an entry when flat ----
        if not pos:
            if cooldown > 0:
                cooldown -= 1
            else:
                enter, ereason = strategy.entry_signal(ind, prev_ind, p)
                if enter:
                    entry = price * (1 + SLIPPAGE)
                    stop = strategy.initial_stop(entry, ind["atr"], p)
                    equity = cash  # flat, so equity == cash
                    qty = strategy.position_size(equity, entry, stop, p)
                    notional = qty * entry
                    if notional > cash:           # no leverage: cap to available cash
                        qty = cash / entry
                        notional = qty * entry
                    if qty > 0 and notional >= 10:
                        cash -= notional * (1 + FEE)
                        pos = {"entry": entry, "stop": stop, "stop_init": stop,
                               "qty": qty, "high": entry}

        # mark-to-market equity
        equity_curve.append(cash + (pos["qty"] * price if pos else 0.0))

    # Close any open position at the last price
    if pos:
        last = df.iloc[-1]["Close"]
        cash += pos["qty"] * last * (1 - FEE)
        pnl = pos["qty"] * last * (1 - FEE) - pos["qty"] * pos["entry"]
        r_mult = pnl / (pos["qty"] * (pos["entry"] - pos["stop_init"])) if (pos["entry"] - pos["stop_init"]) > 0 else 0
        trades.append({"pnl": pnl, "r": r_mult, "reason": "EOD", "entry": pos["entry"], "exit": last})

    return _metrics(df, trades, equity_curve, cash, p, verbose)


def _metrics(df, trades, equity_curve, final_cash, p, verbose):
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    n = len(trades)

    # Max drawdown on the equity curve
    peak = -1e18
    max_dd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)

    ret_pct = (final_cash - START_EQUITY) / START_EQUITY * 100
    bh = (df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[0] * 100

    m = {
        "trades": n,
        "win_rate": (len(wins) / n * 100) if n else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "avg_R": (sum(t["r"] for t in trades) / n) if n else 0.0,
        "return_pct": ret_pct,
        "buy_hold_pct": bh,
        "max_drawdown_pct": max_dd * 100,
        "final_equity": final_cash,
    }
    if verbose:
        print("\n=== Backtest Result ===")
        print(f"Period bars       : {len(df)}")
        print(f"Trades            : {m['trades']}")
        print(f"Win rate          : {m['win_rate']:.1f}%")
        print(f"Profit factor     : {m['profit_factor']:.2f}")
        print(f"Avg R / expectancy: {m['avg_R']:+.2f}")
        print(f"Strategy return   : {m['return_pct']:+.1f}%   (final ${m['final_equity']:,.0f})")
        print(f"Buy & hold return : {m['buy_hold_pct']:+.1f}%")
        print(f"Max drawdown      : {m['max_drawdown_pct']:.1f}%")
        # exit breakdown
        from collections import Counter
        c = Counter(t["reason"] for t in trades)
        print(f"Exits             : {dict(c)}")
    return m


def grid_search(df):
    """Small sweep over the highest-leverage parameters for calibration."""
    print("\n=== Grid search (calibration) ===")
    prepared = add_indicators(df).dropna().reset_index(drop=True)
    results = []
    for adx_min in [32, 34, 35, 36, 38]:
        for atr_stop in [2.0]:
            for chand in [4.5, 5.0, 5.5]:
                for exit_ema in ["ema50"]:
                    params = {"adx_min": adx_min, "atr_stop_mult": atr_stop,
                              "chandelier_mult": chand, "exit_below_ema": exit_ema}
                    m = run_backtest(prepared, params, prepared=True)
                    results.append((params, m))
                    print(f"  adx{adx_min} sl{atr_stop} ch{chand} {exit_ema}: "
                          f"ret{m['return_pct']:+.0f}% pf{m['profit_factor']:.2f} "
                          f"n{m['trades']} dd{m['max_drawdown_pct']:.0f}%", flush=True)
    results.sort(key=lambda x: x[1]["return_pct"], reverse=True)
    print(f"\n--- TOP RESULTS ---")
    print(f"{'adx':>4} {'atrSL':>6} {'chand':>6} {'exitEMA':>8} | {'trades':>6} {'win%':>6} {'PF':>5} {'avgR':>6} {'ret%':>8} {'DD%':>6}")
    for params, m in results[:15]:
        print(f"{params['adx_min']:>4} {params['atr_stop_mult']:>6} {params['chandelier_mult']:>6} {params['exit_below_ema']:>8} | "
              f"{m['trades']:>6} {m['win_rate']:>5.1f} {m['profit_factor']:>5.2f} {m['avg_R']:>+6.2f} "
              f"{m['return_pct']:>+8.1f} {m['max_drawdown_pct']:>6.1f}")
    return results


if __name__ == "__main__":
    refresh = "--refresh" in sys.argv
    df = load_data(refresh=refresh)
    if "--grid" in sys.argv:
        grid_search(df)
    else:
        run_backtest(df, verbose=True)
