import os
import time
import math
import csv
from datetime import datetime
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException
from signals import get_signal

# Configuration
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']
TRADE_INTERVAL = 60  # seconds
MAX_TRADE_AMOUNT = 20.0  # USDT
MIN_TRADE_AMOUNT = 10.0  # USDT
STOP_LOSS_PCT = 0.02  # 2%
LOG_FILE = 'trade_log.csv'

# Global Configuration State
class TraderConfig:
    is_running = True
    auto_trade = True
    max_trade_amount = MAX_TRADE_AMOUNT
    min_trade_amount = MIN_TRADE_AMOUNT
    stop_loss_pct = STOP_LOSS_PCT

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
    "global_message": "Initializing...",
    "coins": {
        sym: {
            "price": 0.0,
            "rsi": 0.0,
            "macd": 0.0,
            "macd_signal": 0.0,
            "ema20": 0.0,
            "ema50": 0.0,
            "signal": "HOLD",
            "last_buy_price": None,
            "message": "Initializing..."
        } for sym in SYMBOLS
    }
}

def log_trade(symbol, signal_type, price, amount, order_id):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(['Timestamp', 'Symbol', 'Signal', 'Price', 'Amount', 'Order ID'])
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow([timestamp, symbol, signal_type, price, amount, order_id])

def truncate_quantity(quantity, step_size):
    precision = int(round(-math.log(step_size, 10), 0))
    factor = 10 ** precision
    return math.floor(quantity * factor) / factor

def run_trader():
    load_dotenv()
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_SECRET_KEY')

    if not api_key or not api_secret:
        print("Error: API keys not found in .env")
        dashboard_state["global_message"] = "Error: API keys not found"
        return

    print("Initializing Binance Client (TESTNET)...")
    try:
        client = Client(api_key, api_secret, testnet=True)
        client.ping()
        print("Connected to Binance Testnet successfully!")
        dashboard_state["global_message"] = "Connected to Testnet"
    except Exception as e:
        print(f"Connection Error: {e}")
        dashboard_state["global_message"] = f"Connection Error: {e}"
        return

    # Cache step sizes for each symbol
    step_sizes = {}
    for sym in SYMBOLS:
        try:
            symbol_info = client.get_symbol_info(sym)
            lot_size_filter = next(f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE')
            step_sizes[sym] = float(lot_size_filter['stepSize'])
        except Exception as e:
            step_sizes[sym] = 0.00001

    print(f"\n--- Starting Auto Trading Engine on {', '.join(SYMBOLS)} ---")

    while config.is_running:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{now}] Fetching signals...")
            dashboard_state["global_message"] = "Fetching signals..."

            # Update balances
            try:
                dashboard_state["balances"]["USDT"] = float(client.get_asset_balance(asset='USDT')['free'])
                dashboard_state["balances"]["BTC"] = float(client.get_asset_balance(asset='BTC')['free'])
                dashboard_state["balances"]["ETH"] = float(client.get_asset_balance(asset='ETH')['free'])
                dashboard_state["balances"]["SOL"] = float(client.get_asset_balance(asset='SOL')['free'])
                dashboard_state["balances"]["BNB"] = float(client.get_asset_balance(asset='BNB')['free'])
            except Exception as e:
                print(f"Error fetching balances: {e}")
                pass

            for symbol in SYMBOLS:
                if not config.is_running:
                    break
                    
                data = get_signal(client, symbol)
                if not data:
                    print(f"Failed to get signal data for {symbol}.")
                    dashboard_state["coins"][symbol]["message"] = "Error fetching signal"
                    continue

                current_price = data['price']
                signal = data['signal']
                
                # Update state for dashboard
                state = dashboard_state["coins"][symbol]
                state["price"] = current_price
                state["rsi"] = data['rsi']
                state["macd"] = data['macd']
                state["macd_signal"] = data['macd_signal']
                state["ema20"] = data['ema20']
                state["ema50"] = data['ema50']
                state["signal"] = signal

                print(f"[{symbol}] Price: ${current_price:.2f} | RSI: {data['rsi']:.2f} | MACD: {data['macd']:.2f} | EMA20: ${data['ema20']:.2f} | Signal: {signal}")

                if not config.auto_trade:
                    state["message"] = "Auto-trading PAUSED"
                    continue

                state["message"] = "Bot Running..."

                if state["last_buy_price"] is not None:
                    stop_loss_price = state["last_buy_price"] * (1 - config.stop_loss_pct)
                    if current_price <= stop_loss_price:
                        print(f"[{symbol}] !!! EMERGENCY STOP LOSS TRIGGERED !!! Price dropped below ${stop_loss_price:.2f}")
                        signal = "SELL"

                if signal == "BUY":
                    usdt_balance = dashboard_state["balances"]["USDT"]
                    if usdt_balance >= config.min_trade_amount:
                        trade_amount = min(usdt_balance, config.max_trade_amount)
                        trade_amount_str = f"{trade_amount:.2f}"
                        print(f"[{symbol}] Placing MARKET BUY for ${trade_amount_str} USDT...")
                        try:
                            order = client.create_order(
                                symbol=symbol,
                                side=Client.SIDE_BUY,
                                type=Client.ORDER_TYPE_MARKET,
                                quoteOrderQty=trade_amount_str
                            )
                            log_trade(symbol, "BUY", current_price, trade_amount, order['orderId'])
                            state["last_buy_price"] = current_price
                            state["message"] = f"Bought ${trade_amount_str} USDT"
                            # Deduct USDT balance immediately to avoid double spend in same loop
                            dashboard_state["balances"]["USDT"] -= trade_amount
                        except BinanceAPIException as e:
                            print(f"[{symbol}] Buy Order Error: {e}")
                            state["message"] = f"Buy Error: {e.message}"
                    else:
                        print(f"[{symbol}] Insufficient USDT (${usdt_balance:.2f}) to buy.")
                
                elif signal == "SELL":
                    base_asset = symbol.replace("USDT", "")
                    asset_balance = dashboard_state["balances"][base_asset]
                    step_size = step_sizes[symbol]
                    if asset_balance >= step_size:
                        sell_qty = truncate_quantity(asset_balance, step_size)
                        sell_qty_str = f"{sell_qty:.5f}"
                        # Check min notional rule if needed (skip for brevity, let API handle it)
                        print(f"[{symbol}] Placing MARKET SELL for {sell_qty_str} {base_asset}...")
                        try:
                            order = client.create_order(
                                symbol=symbol,
                                side=Client.SIDE_SELL,
                                type=Client.ORDER_TYPE_MARKET,
                                quantity=sell_qty_str
                            )
                            log_trade(symbol, "SELL", current_price, sell_qty, order['orderId'])
                            state["last_buy_price"] = None
                            state["message"] = f"Sold {sell_qty_str} {base_asset}"
                            dashboard_state["balances"][base_asset] -= sell_qty
                        except BinanceAPIException as e:
                            print(f"[{symbol}] Sell Order Error: {e}")
                            state["message"] = f"Sell Error: {e.message}"
                    else:
                        print(f"[{symbol}] No {base_asset} to sell.")
                        state["last_buy_price"] = None

            if not config.auto_trade:
                print("Auto-trading is PAUSED. Holding...")

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
    # If run standalone, execute directly
    run_trader()

if __name__ == '__main__':
    main()
