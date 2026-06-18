"""Long-only trend-following pullback strategy for BTC/USDT (1h).

Pure decision logic — no network, no DB — so the *exact same* rules drive both
the backtest (backtest.py) and the live trader (trader.py). That parity is what
makes the backtested edge meaningful live.

Trading thesis (spot, long-only):
  1. Only buy when the market is in an uptrend (price above the slow EMA).
     Don't fight the trend — this removes most losing trades up front.
  2. Don't chase. Enter on a *pullback* (momentum reset toward the fast EMA)
     that is *turning back up* (MACD histogram rising / bullish cross).
  3. Risk first: every trade has a volatility-adaptive (ATR) stop, position
     size is set so a stop-out costs a fixed % of equity, winners are given
     room with a break-even move + ATR trail, and a momentum break exits early.

Each indicator snapshot ("ind") is a plain dict:
    close, ema20, ema50, ema200, rsi, macd, macd_signal, macd_hist, atr
"""

# Balanced profile: ~1% risk/trade, ~2.0 reward:risk. These are the knobs the
# backtest calibrates; defaults below are the starting point.
PARAMS = {
    # Trend / regime
    "ema_fast": 20,
    "ema_mid": 50,
    "ema_slow": 200,
    "require_alignment": True,   # require ema20 > ema50 > ema200 (true uptrend)
    "adx_min": 35,               # only trade when trend strength (ADX) is real
                                 # (calibrated: 32-38 is a robust profitable plateau)

    # Entry: trend continuation (buy strength inside a confirmed uptrend)
    "rsi_low": 45,        # avoid buying into weakness
    "rsi_high": 72,       # avoid buying blow-off tops
    "max_ext_atr": 1.5,   # don't buy if close is > ema20 + this*ATR (chasing)

    # Risk / exits — trend-following: cut losers fast, let winners run
    "atr_stop_mult": 2.0,      # initial stop = entry - 2.0*ATR
    "chandelier_mult": 5.0,    # trail stop = highest_high - 5.0*ATR (lets winners run)
    "exit_below_ema": "ema50", # also exit on a close below this EMA (trend break)
    "risk_per_trade": 0.01,    # risk 1% of equity per trade
    "cooldown_bars": 2,        # bars to wait after an exit before re-entering
}


def _regime_ok(ind, p):
    """Bullish, *trending* regime.

    Price above the slow EMA, EMAs stacked (20>50>200) so it's a real uptrend
    not chop, and ADX above the floor so the trend has actual strength. This
    gate is what keeps us flat during sideways markets (where the edge is gone).
    """
    if ind["ema200"] is None or ind["close"] is None:
        return False
    if ind["close"] <= ind["ema200"]:
        return False
    if p["require_alignment"]:
        if not (ind["ema20"] and ind["ema50"]
                and ind["ema20"] > ind["ema50"] > ind["ema200"]):
            return False
    if ind.get("adx") is not None and ind["adx"] < p["adx_min"]:
        return False
    return True


def entry_signal(ind, prev, p=PARAMS):
    """Return (enter: bool, reason: str) for opening a long.

    Trend-continuation entry: a confirmed, strong uptrend (regime gate) with
    positive MACD momentum and RSI showing strength but not a blow-off top, and
    price not overextended above the fast EMA (so we still enter on minor dips
    /consolidations within the trend rather than chasing a vertical spike).
    """
    if not prev or ind.get("atr") is None or ind.get("rsi") is None:
        return False, ""

    if not _regime_ok(ind, p):
        return False, ""

    if not (p["rsi_low"] <= ind["rsi"] <= p["rsi_high"]):
        return False, ""

    # Momentum confirmation: MACD above its signal (positive momentum).
    if not (ind["macd"] is not None and ind["macd_signal"] is not None
            and ind["macd"] > ind["macd_signal"]):
        return False, ""

    # Don't chase: price must be within reach of the fast EMA.
    if ind["ema20"] is not None and ind["close"] > ind["ema20"] + p["max_ext_atr"] * ind["atr"]:
        return False, ""

    return True, f"uptrend (ADX {ind.get('adx', 0):.0f}), RSI {ind['rsi']:.0f}, MACD+"


def momentum_exit(ind, prev, p=PARAMS):
    """Trend-break exit: a close back below the chosen EMA ends the trade."""
    key = p.get("exit_below_ema", "ema50")
    ema = ind.get(key)
    if ema is not None and ind["close"] < ema:
        return True, f"Close < {key.upper()} (trend break)"
    return False, ""


def initial_stop(entry_price, atr, p=PARAMS):
    """Volatility-adaptive initial (chandelier) stop below entry."""
    return entry_price - p["atr_stop_mult"] * atr


def trail_stop(highest_high, atr, p=PARAMS):
    """Chandelier trailing stop: highest high since entry minus a multiple of ATR."""
    return highest_high - p["chandelier_mult"] * atr


def position_size(equity, entry_price, stop, p=PARAMS):
    """Quantity such that a stop-out loses ~risk_per_trade of equity.

    Returns the base-asset quantity (0 if the stop is invalid).
    """
    risk_per_unit = entry_price - stop
    if risk_per_unit <= 0:
        return 0.0
    risk_budget = equity * p["risk_per_trade"]
    return risk_budget / risk_per_unit
