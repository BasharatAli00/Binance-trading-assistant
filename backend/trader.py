import time
from datetime import datetime
from binance.client import Client
from binance.exceptions import BinanceAPIException

import paper_engine
from signals import get_signal

# Configuration
# Prices/signals are computed for all of these (for the dashboard tabs)...
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']
# ...but paper trades are only placed for these symbols.
TRADE_SYMBOLS = ['BTCUSDT']

TRADE_INTERVAL = 60  # seconds
MIN_TRADE_AMOUNT = 10.0  # USDT


# Global Configuration State
class TraderConfig:
    is_running = True
    auto_trade = True
    position_size_pct = 0.20   # 20% of equity per BUY
    stop_loss_pct = 0.02       # 2% below average entry
    take_profit_pct = 0.05     # 5% above average entry
    min_trade_amount = MIN_TRADE_AMOUNT

config = TraderConfig()

# Global State for Dashboard
dashboard_state = {
    "balances": {
        "USDT": 0.0,
        "BTC": 0.0,
        "ETH": 0.0,
        "SOL": 0.0,
        "BNB": 0.0
    },
    "portfolio": {},          # full P&L snapshot from paper_engine
    "global_message": "Initializing...",
    "fear_greed": {           # market-wide sentiment (same for all coins)
        "value": None,
        "classification": None,
        "fetched_at": 0.0
    },
    "coins": {
        sym: {
            "price": 0.0,
            "rsi": 0.0,
            "macd": 0.0,
            "macd_signal": 0.0,
            "ema20": 0.0,
            "ema50": 0.0,
            "signal": "HOLD",
            "reason": "",
            "message": "Initializing..."
        } for sym in SYMBOLS
    }
}


def _refresh_portfolio():
    """Recompute the wallet snapshot from current dashboard prices."""
    prices = {sym.replace("USDT", ""): dashboard_state["coins"][sym]["price"] for sym in SYMBOLS}
    summary = paper_engine.portfolio_summary(prices)
    dashboard_state["portfolio"] = summary
    # Keep the simple per-asset balance map in sync (all 5 keys for the UI)
    for asset in dashboard_state["balances"]:
        dashboard_state["balances"][asset] = summary["balances"].get(asset, 0.0)
    return summary


def _handle_trade(symbol, price, signal, reason):
    """Apply position-aware BUY/SELL/stop-loss/take-profit on the paper wallet."""
    state = dashboard_state["coins"][symbol]
    position = paper_engine.get_position(symbol)
    holding = position is not None

    # Risk management overrides while holding
    if holding:
        avg = position["avg_entry_price"]
        if price <= avg * (1 - config.stop_loss_pct):
            signal = "SELL"
            reason = f"Stop-loss triggered (entry ${avg:.2f})"
        elif price >= avg * (1 + config.take_profit_pct):
            signal = "SELL"
            reason = f"Take-profit triggered (entry ${avg:.2f})"

    if signal == "BUY" and not holding:
        summary = _refresh_portfolio()
        quote = min(config.position_size_pct * summary["total_equity"], summary["cash"])
        if quote >= config.min_trade_amount:
            res = paper_engine.execute_buy(symbol, quote, price, reason)
            if res:
                print(f"[{symbol}] PAPER BUY {res['qty']:.6f} @ ${price:.2f} (${quote:.2f}) | {reason}")
                state["message"] = f"Bought ${quote:.2f} ({reason})"
        else:
            state["message"] = "Insufficient cash to buy"

    elif signal == "SELL" and holding:
        res = paper_engine.execute_sell(symbol, position["quantity"], price, reason)
        if res:
            pnl = res["realized_pnl"]
            print(f"[{symbol}] PAPER SELL {res['qty']:.6f} @ ${price:.2f} | P&L ${pnl:.2f} | {reason}")
            state["message"] = f"Sold (P&L ${pnl:.2f})"
    else:
        state["message"] = "Holding" if holding else "Waiting for entry"


def run_trader():
    # Public client: no API keys needed for market data, and we never place real orders.
    print("Initializing Binance public market-data client...")
    try:
        client = Client()
        client.ping()
        print("Connected to Binance market data successfully!")
    except Exception as e:
        print(f"Connection Error: {e}")
        dashboard_state["global_message"] = f"Connection Error: {e}"
        return

    # Make sure the paper wallet exists
    paper_engine.ensure_initialized()
    dashboard_state["global_message"] = "Paper trading active"

    print(f"\n--- Starting PAPER Trading Engine (trading: {', '.join(TRADE_SYMBOLS)}) ---")

    while config.is_running:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{now}] Fetching signals...")

            for symbol in SYMBOLS:
                if not config.is_running:
                    break

                data = get_signal(client, symbol)
                if not data:
                    dashboard_state["coins"][symbol]["message"] = "Error fetching signal"
                    continue

                price = data['price']
                signal = data['signal']
                reason = data.get('reason', '')

                state = dashboard_state["coins"][symbol]
                state["price"] = price
                state["rsi"] = data['rsi']
                state["macd"] = data['macd']
                state["macd_signal"] = data['macd_signal']
                state["ema20"] = data['ema20']
                state["ema50"] = data['ema50']
                state["signal"] = signal
                state["reason"] = reason

                # Market-wide sentiment is the same across symbols; cache it once on the state.
                if data.get("fng") is not None:
                    dashboard_state["fear_greed"] = {
                        "value": data["fng"],
                        "classification": data.get("fng_class"),
                        "fetched_at": dashboard_state["fear_greed"].get("fetched_at", 0.0)
                    }

                print(f"[{symbol}] ${price:.2f} | RSI {data['rsi']:.1f} | Signal {signal} | {reason}")

                if symbol not in TRADE_SYMBOLS:
                    continue
                if not config.auto_trade:
                    state["message"] = "Auto-trading PAUSED"
                    continue

                _handle_trade(symbol, price, signal, reason)

            # Refresh the wallet snapshot (equity + P&L) after this pass
            _refresh_portfolio()
            dashboard_state["global_message"] = "Paper trading active" if config.auto_trade else "Auto-trading PAUSED"

        except BinanceAPIException as e:
            print(f"Binance API Error: {e}")
            dashboard_state["global_message"] = f"Binance Error: {e.message}"
        except Exception as e:
            print(f"Error during loop: {e}")
            dashboard_state["global_message"] = "Internal Error"

        # Sleep in small increments to allow fast shutdown
        for _ in range(TRADE_INTERVAL):
            if not config.is_running:
                break
            time.sleep(1)


def main():
    run_trader()


if __name__ == '__main__':
    main()
