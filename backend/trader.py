import time
from datetime import datetime

from binance.client import Client
from binance.exceptions import BinanceAPIException

import paper_engine
import strategy
import pivot_engine
import pivot_strategy
from signals import (
    get_signal, compute_indicator_df, latest_closed,
    get_fear_greed, get_news_sentiment_score,
)

# Prices/signals are computed for all of these (for the dashboard tabs)...
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']
# ...but the strategy only trades these symbols.
TRADE_SYMBOLS = ['BTCUSDT']

TRADE_INTERVAL = 60  # seconds between loop passes (stops are checked every pass)
MIN_TRADE_AMOUNT = 10.0  # USDT


# Global Configuration State
class TraderConfig:
    is_running = True
    auto_trade = True
    risk_per_trade = strategy.PARAMS["risk_per_trade"]  # fraction of equity risked
    # Legacy fields kept for the settings API; the strategy now sets stops/size
    # itself (ATR stop + risk-based sizing), so these are informational.
    position_size_pct = 0.20
    stop_loss_pct = 0.02
    take_profit_pct = 0.05
    min_trade_amount = MIN_TRADE_AMOUNT

config = TraderConfig()


def _coin_state():
    return {
        "price": 0.0, "rsi": 0.0, "macd": 0.0, "macd_signal": 0.0,
        "ema20": 0.0, "ema50": 0.0, "ema200": 0.0, "adx": 0.0, "atr": 0.0,
        "signal": "HOLD", "reason": "", "message": "Initializing...",
        # strategy/position view (BTC)
        "in_position": False, "entry_price": 0.0, "stop_price": 0.0,
        "unrealized_r": 0.0,
    }


# Global State for Dashboard
dashboard_state = {
    "balances": {"USDT": 0.0, "BTC": 0.0, "ETH": 0.0, "SOL": 0.0, "BNB": 0.0},
    "portfolio": {},
    "global_message": "Initializing...",
    "fear_greed": {"value": None, "classification": None, "fetched_at": 0.0},
    "coins": {sym: _coin_state() for sym in SYMBOLS},
}

# Per-symbol strategy bookkeeping across loop passes
_last_closed_ts = {}     # symbol -> Open time of last processed closed candle
_cooldown = {}           # symbol -> remaining cooldown in candles

# ---- Strategy #2 (pivot-bracket) state — fully isolated from strategy #1 ----
def _pivot_state():
    return {
        "signal": "HOLD", "message": "Initializing...", "in_position": False,
        "entry_price": 0.0, "take_profit": 0.0, "stop_price": 0.0,
        "pp": 0.0, "r1": 0.0, "s1": 0.0, "trend": "",
    }

pivot_dashboard = {sym: _pivot_state() for sym in TRADE_SYMBOLS}
_pivot_cooldown = {}     # symbol -> remaining cooldown in loop passes


def _refresh_portfolio():
    """Recompute the wallet snapshot from current dashboard prices."""
    prices = {sym.replace("USDT", ""): dashboard_state["coins"][sym]["price"] for sym in SYMBOLS}
    summary = paper_engine.portfolio_summary(prices)
    dashboard_state["portfolio"] = summary
    for asset in dashboard_state["balances"]:
        dashboard_state["balances"][asset] = summary["balances"].get(asset, 0.0)
    return summary


def _entry_filters_ok(state):
    """Alt-data vetoes on NEW entries only (never blocks an exit).

    Don't buy into euphoria (Extreme Greed) or a strongly negative news tape.
    These are conservative gates layered on top of the technical entry; they can
    only stop a trade, never force one, and never affect exits.
    """
    fng = get_fear_greed().get("value")
    if fng is not None and fng >= 80:
        return False, f"vetoed: Extreme Greed ({fng})"
    if get_news_sentiment_score() < 0:
        return False, "vetoed: negative news tape"
    return True, ""


def _manage_btc(symbol, df, ind, prev, live_price, new_candle):
    """Strategy-driven entry/exit/trailing for a trade symbol."""
    state = dashboard_state["coins"][symbol]
    position = paper_engine.get_position(symbol)
    atr = ind["atr"]

    if position:
        state["in_position"] = True
        state["entry_price"] = position["avg_entry_price"]
        entry = position["avg_entry_price"]
        init_stop = position["init_stop"] or strategy.initial_stop(entry, atr)
        # Ratchet the high-water mark and chandelier trailing stop (never down).
        high = max(position["highest_price"] or entry, live_price)
        trail = strategy.trail_stop(high, atr)
        stop = max(position["stop_price"] or init_stop, trail)
        paper_engine.update_position_risk(symbol, stop_price=stop, highest_price=high)
        state["stop_price"] = stop
        risk_unit = entry - init_stop
        state["unrealized_r"] = ((live_price - entry) / risk_unit) if risk_unit > 0 else 0.0

        # Exit 1: stop / trailing stop (checked every pass against live price).
        if live_price <= stop:
            res = paper_engine.execute_sell(symbol, position["quantity"], live_price, "Stop/Trail hit")
            if res:
                print(f"[{symbol}] PAPER SELL (stop) {res['qty']:.6f} @ ${live_price:.2f} | P&L ${res['realized_pnl']:.2f}")
                state["message"] = f"Stopped out (P&L ${res['realized_pnl']:.2f})"
                state["in_position"] = False
                state["signal"] = "SELL"
                _cooldown[symbol] = strategy.PARAMS["cooldown_bars"]
            return

        # Exit 2: trend-break (momentum) exit — only re-evaluated on a closed candle.
        if new_candle:
            ex, why = strategy.momentum_exit(ind, prev)
            if ex:
                res = paper_engine.execute_sell(symbol, position["quantity"], live_price, why)
                if res:
                    print(f"[{symbol}] PAPER SELL ({why}) {res['qty']:.6f} @ ${live_price:.2f} | P&L ${res['realized_pnl']:.2f}")
                    state["message"] = f"Exited: {why} (P&L ${res['realized_pnl']:.2f})"
                    state["in_position"] = False
                    state["signal"] = "SELL"
                    _cooldown[symbol] = strategy.PARAMS["cooldown_bars"]
                return

        state["signal"] = "HOLD"
        state["message"] = f"Long @ ${entry:.0f}, stop ${stop:.0f} ({state['unrealized_r']:+.1f}R)"
        return

    # ---- Flat: look for an entry, once per closed candle, after cooldown ----
    state["in_position"] = False
    state["entry_price"] = 0.0
    state["stop_price"] = 0.0
    state["unrealized_r"] = 0.0

    if not new_candle:
        return
    if _cooldown.get(symbol, 0) > 0:
        _cooldown[symbol] -= 1
        state["signal"] = "HOLD"
        state["message"] = f"Cooldown ({_cooldown[symbol]} bars)"
        return

    enter, reason = strategy.entry_signal(ind, prev)
    if not enter:
        state["signal"] = "HOLD"
        state["message"] = "Waiting for trend setup"
        return

    ok, veto = _entry_filters_ok(state)
    if not ok:
        state["signal"] = "HOLD"
        state["message"] = f"Setup found but {veto}"
        return

    if not config.auto_trade:
        state["signal"] = "BUY"
        state["message"] = "Setup ready (auto-trade paused)"
        return

    entry = live_price
    stop = strategy.initial_stop(entry, atr)
    summary = _refresh_portfolio()
    equity = summary["total_equity"]
    qty = strategy.position_size(equity, entry, stop, {**strategy.PARAMS, "risk_per_trade": config.risk_per_trade})
    notional = min(qty * entry, summary["cash"] * 0.99)
    if notional < config.min_trade_amount:
        state["signal"] = "HOLD"
        state["message"] = "Setup ready but insufficient cash"
        return

    res = paper_engine.execute_buy(symbol, notional, entry, reason, stop=stop)
    if res:
        print(f"[{symbol}] PAPER BUY {res['qty']:.6f} @ ${entry:.2f} (${notional:.2f}) stop ${stop:.2f} | {reason}")
        state["signal"] = "BUY"
        state["in_position"] = True
        state["entry_price"] = entry
        state["stop_price"] = stop
        state["message"] = f"Entered long: {reason}"


def _get_latest_pivots(symbol):
    """Latest stored daily pivots for a symbol, or None if not collected yet."""
    from database import SessionLocal
    from models import PivotLevels
    db = SessionLocal()
    try:
        row = db.query(PivotLevels).filter(
            PivotLevels.symbol == symbol
        ).order_by(PivotLevels.timestamp.desc()).first()
        if not row:
            return None
        return {
            "pp": row.pp, "r1": row.r1, "s1": row.s1, "trend": row.trend,
            "day": row.timestamp.strftime("%Y-%m-%d"),
        }
    finally:
        db.close()


def _manage_pivot(symbol, live_price):
    """Strategy #2: pivot-bracket entry/exit on its OWN isolated wallet.

    Buy when reward:risk to R1/S1 is favorable in a non-downtrend; take profit
    at R1, stop at S1, and flatten at the daily pivot rollover (end of day).
    Reads daily pivots already stored by pivots.py.
    """
    st = pivot_dashboard[symbol]
    piv = _get_latest_pivots(symbol)
    if not piv:
        st["message"] = "No pivot data yet"
        return
    st["pp"], st["r1"], st["s1"], st["trend"] = piv["pp"], piv["r1"], piv["s1"], piv["trend"]

    position = pivot_engine.get_position(symbol)

    if position:
        st["in_position"] = True
        st["entry_price"] = position["avg_entry_price"]
        tp = position["take_profit"]
        sl = position["stop_price"]
        st["take_profit"], st["stop_price"] = tp or 0.0, sl or 0.0

        # End-of-day flatten: a newer pivot day exists -> never hold overnight.
        if piv["day"] != position["pivot_day"]:
            res = pivot_engine.execute_sell(symbol, position["quantity"], live_price, "End-of-day flatten")
            if res:
                print(f"[pivot {symbol}] EoD flatten {res['qty']:.6f} @ ${live_price:.2f} | P&L ${res['realized_pnl']:.2f}")
                st["signal"] = "SELL"; st["in_position"] = False
                st["message"] = f"EoD flatten (P&L ${res['realized_pnl']:.2f})"
                _pivot_cooldown[symbol] = pivot_strategy.PIVOT_PARAMS["cooldown_passes"]
            return

        # Take-profit at R1.
        if tp and live_price >= tp:
            res = pivot_engine.execute_sell(symbol, position["quantity"], live_price, f"Take-profit R1 ${tp:.0f}")
            if res:
                print(f"[pivot {symbol}] TP {res['qty']:.6f} @ ${live_price:.2f} | P&L ${res['realized_pnl']:.2f}")
                st["signal"] = "SELL"; st["in_position"] = False
                st["message"] = f"Hit R1 target (P&L ${res['realized_pnl']:.2f})"
            return

        # Stop-loss at S1.
        if sl and live_price <= sl:
            res = pivot_engine.execute_sell(symbol, position["quantity"], live_price, f"Stop-loss S1 ${sl:.0f}")
            if res:
                print(f"[pivot {symbol}] SL {res['qty']:.6f} @ ${live_price:.2f} | P&L ${res['realized_pnl']:.2f}")
                st["signal"] = "SELL"; st["in_position"] = False
                st["message"] = f"Stopped at S1 (P&L ${res['realized_pnl']:.2f})"
                _pivot_cooldown[symbol] = pivot_strategy.PIVOT_PARAMS["cooldown_passes"]
            return

        st["signal"] = "HOLD"
        st["message"] = f"Long @ ${position['avg_entry_price']:.0f} | TP ${tp:.0f} / SL ${sl:.0f}"
        return

    # ---- Flat: look for an entry ----
    st["in_position"] = False
    st["entry_price"] = st["take_profit"] = st["stop_price"] = 0.0

    if _pivot_cooldown.get(symbol, 0) > 0:
        _pivot_cooldown[symbol] -= 1
        st["signal"] = "HOLD"; st["message"] = f"Cooldown ({_pivot_cooldown[symbol]})"
        return

    enter, reason = pivot_strategy.should_enter(live_price, piv["pp"], piv["r1"], piv["s1"], piv["trend"])
    if not enter:
        st["signal"] = "HOLD"; st["message"] = reason
        return

    summary = pivot_engine.portfolio_summary({symbol.replace("USDT", ""): live_price})
    equity = summary["total_equity"]
    qty = pivot_strategy.position_size(equity, live_price, piv["s1"])
    notional = min(qty * live_price, summary["cash"] * 0.99)
    if notional < config.min_trade_amount:
        st["signal"] = "HOLD"; st["message"] = "Setup ready but insufficient cash"
        return

    res = pivot_engine.execute_buy(symbol, notional, live_price, reason,
                                   take_profit=piv["r1"], stop=piv["s1"], pivot_day=piv["day"])
    if res:
        print(f"[pivot {symbol}] BUY {res['qty']:.6f} @ ${live_price:.2f} (${notional:.2f}) "
              f"TP ${piv['r1']:.0f} SL ${piv['s1']:.0f} | {reason}")
        st["signal"] = "BUY"; st["in_position"] = True
        st["entry_price"] = live_price
        st["take_profit"], st["stop_price"] = piv["r1"], piv["s1"]
        st["message"] = f"Entered: {reason}"


def _update_display(symbol, ind, live_price):
    """Populate the dashboard display fields from the latest closed-candle indicators."""
    state = dashboard_state["coins"][symbol]
    state["price"] = live_price
    state["rsi"] = ind["rsi"]
    state["macd"] = ind["macd"]
    state["macd_signal"] = ind["macd_signal"]
    state["ema20"] = ind["ema20"]
    state["ema50"] = ind["ema50"]
    state["ema200"] = ind["ema200"]
    state["adx"] = ind["adx"]
    state["atr"] = ind["atr"]


def run_trader():
    print("Initializing Binance public market-data client...")
    try:
        client = Client()
        client.ping()
        print("Connected to Binance market data successfully!")
    except Exception as e:
        print(f"Connection Error: {e}")
        dashboard_state["global_message"] = f"Connection Error: {e}"
        return

    paper_engine.ensure_initialized()
    pivot_engine.ensure_initialized()  # strategy #2's isolated wallet
    dashboard_state["global_message"] = "Strategy active"
    print(f"\n--- Trend-following PAPER engine (trading: {', '.join(TRADE_SYMBOLS)}) ---")

    while config.is_running:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{now}] Evaluating...")

            for symbol in SYMBOLS:
                if not config.is_running:
                    break

                if symbol in TRADE_SYMBOLS:
                    df = compute_indicator_df(client, symbol, limit=300)
                    ind, prev, live_price = latest_closed(df)
                    if ind is None:
                        dashboard_state["coins"][symbol]["message"] = "Warming up indicators..."
                        if live_price:
                            dashboard_state["coins"][symbol]["price"] = live_price
                        continue

                    closed_ts = int(df.iloc[-2]['Open time'])
                    new_candle = _last_closed_ts.get(symbol) != closed_ts
                    _last_closed_ts[symbol] = closed_ts

                    _update_display(symbol, ind, live_price)
                    _manage_btc(symbol, df, ind, prev, live_price, new_candle)
                    # Strategy #2 runs on its own wallet; isolate it so a fault
                    # here can never disrupt strategy #1's management above.
                    try:
                        _manage_pivot(symbol, live_price)
                    except Exception as e:
                        print(f"[pivot {symbol}] error: {e}")
                    s = dashboard_state["coins"][symbol]
                    print(f"[{symbol}] ${live_price:.2f} | ADX {ind['adx']:.0f} RSI {ind['rsi']:.0f} "
                          f"| {s['signal']} | {s['message']}")
                else:
                    # Display-only symbols: lightweight legacy signal for the tabs.
                    data = get_signal(client, symbol)
                    if not data:
                        dashboard_state["coins"][symbol]["message"] = "Error fetching signal"
                        continue
                    st = dashboard_state["coins"][symbol]
                    st["price"] = data['price']
                    st["rsi"] = data['rsi']
                    st["macd"] = data['macd']
                    st["macd_signal"] = data['macd_signal']
                    st["ema20"] = data['ema20']
                    st["ema50"] = data['ema50']
                    st["signal"] = data['signal']
                    st["reason"] = data.get('reason', '')
                    if data.get("fng") is not None:
                        dashboard_state["fear_greed"] = {
                            "value": data["fng"], "classification": data.get("fng_class"),
                            "fetched_at": dashboard_state["fear_greed"].get("fetched_at", 0.0),
                        }

            _refresh_portfolio()
            dashboard_state["global_message"] = "Strategy active" if config.auto_trade else "Auto-trading PAUSED"

        except BinanceAPIException as e:
            print(f"Binance API Error: {e}")
            dashboard_state["global_message"] = f"Binance Error: {e.message}"
        except Exception as e:
            print(f"Error during loop: {e}")
            dashboard_state["global_message"] = "Internal Error"

        for _ in range(TRADE_INTERVAL):
            if not config.is_running:
                break
            time.sleep(1)


def main():
    run_trader()


if __name__ == '__main__':
    main()
