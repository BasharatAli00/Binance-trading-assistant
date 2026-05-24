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
SYMBOL = 'BTCUSDT'
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
LOG_FILE = 'trade_log.csv'

# Global State for Dashboard
dashboard_state = {
    "price": 0.0,
    "rsi": 0.0,
    "macd": 0.0,
    "macd_signal": 0.0,
    "ema20": 0.0,
    "ema50": 0.0,
    "signal": "HOLD",
    "usdt_balance": 0.0,
    "btc_balance": 0.0,
    "last_buy_price": None,
    "message": "Initializing..."
}

def log_trade(signal_type, price, amount, order_id):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(['Timestamp', 'Signal', 'Price', 'Amount', 'Order ID'])
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow([timestamp, signal_type, price, amount, order_id])

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
        dashboard_state["message"] = "Error: API keys not found"
        return

    print("Initializing Binance Client (TESTNET)...")
    try:
        client = Client(api_key, api_secret, testnet=True)
        client.ping()
        print("Connected to Binance Testnet successfully!")
        dashboard_state["message"] = "Connected to Testnet"
    except Exception as e:
        print(f"Connection Error: {e}")
        dashboard_state["message"] = f"Connection Error: {e}"
        return

    try:
        symbol_info = client.get_symbol_info(SYMBOL)
        lot_size_filter = next(f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE')
        step_size = float(lot_size_filter['stepSize'])
    except Exception as e:
        step_size = 0.00001

    print(f"\n--- Starting Auto Trading Engine on {SYMBOL} ---")

    while config.is_running:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{now}] Fetching signal...")
            dashboard_state["message"] = "Fetching signal..."

            # Update balances
            try:
                dashboard_state["usdt_balance"] = float(client.get_asset_balance(asset='USDT')['free'])
                dashboard_state["btc_balance"] = float(client.get_asset_balance(asset='BTC')['free'])
            except Exception:
                pass

            data = get_signal(client)
            if not data:
                print("Failed to get signal data.")
                dashboard_state["message"] = "Error fetching signal"
                time.sleep(TRADE_INTERVAL)
                continue

            current_price = data['price']
            signal = data['signal']
            
            # Update state for dashboard
            dashboard_state["price"] = current_price
            dashboard_state["rsi"] = data['rsi']
            dashboard_state["macd"] = data['macd']
            dashboard_state["macd_signal"] = data['macd_signal']
            dashboard_state["ema20"] = data['ema20']
            dashboard_state["ema50"] = data['ema50']
            dashboard_state["signal"] = signal

            print(f"Price: ${current_price:.2f} | RSI: {data['rsi']:.2f} | MACD: {data['macd']:.2f} | EMA20: ${data['ema20']:.2f} | Signal: {signal}")

            if not config.auto_trade:
                dashboard_state["message"] = "Auto-trading PAUSED"
                print("Auto-trading is PAUSED. Holding...")
                time.sleep(TRADE_INTERVAL)
                continue

            dashboard_state["message"] = "Bot Running..."

            if dashboard_state["last_buy_price"] is not None:
                stop_loss_price = dashboard_state["last_buy_price"] * (1 - config.stop_loss_pct)
                if current_price <= stop_loss_price:
                    print(f"!!! EMERGENCY STOP LOSS TRIGGERED !!! Price dropped below ${stop_loss_price:.2f}")
                    signal = "SELL"

            if signal == "BUY":
                usdt_balance = dashboard_state["usdt_balance"]
                if usdt_balance >= config.min_trade_amount:
                    trade_amount = min(usdt_balance, config.max_trade_amount)
                    trade_amount_str = f"{trade_amount:.2f}"
                    print(f"Placing MARKET BUY for ${trade_amount_str} USDT...")
                    order = client.create_order(
                        symbol=SYMBOL,
                        side=Client.SIDE_BUY,
                        type=Client.ORDER_TYPE_MARKET,
                        quoteOrderQty=trade_amount_str
                    )
                    log_trade("BUY", current_price, trade_amount, order['orderId'])
                    dashboard_state["last_buy_price"] = current_price
                    dashboard_state["message"] = f"Bought ${trade_amount_str} USDT"
                else:
                    print(f"Insufficient USDT (${usdt_balance:.2f}) to buy.")
            
            elif signal == "SELL":
                btc_balance = dashboard_state["btc_balance"]
                if btc_balance >= step_size:
                    sell_qty = truncate_quantity(btc_balance, step_size)
                    sell_qty_str = f"{sell_qty:.5f}"
                    print(f"Placing MARKET SELL for {sell_qty_str} BTC...")
                    order = client.create_order(
                        symbol=SYMBOL,
                        side=Client.SIDE_SELL,
                        type=Client.ORDER_TYPE_MARKET,
                        quantity=sell_qty_str
                    )
                    log_trade("SELL", current_price, sell_qty, order['orderId'])
                    dashboard_state["last_buy_price"] = None
                    dashboard_state["message"] = f"Sold {sell_qty_str} BTC"
                else:
                    print("No BTC to sell.")
                    dashboard_state["last_buy_price"] = None

        except BinanceAPIException as e:
            print(f"Binance API Error: {e}")
            dashboard_state["message"] = f"Binance Error: {e.message}"
        except Exception as e:
            print(f"Error during loop: {e}")
            dashboard_state["message"] = "Internal Error"

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
