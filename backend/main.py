import os
import csv
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from binance.client import Client
from fastapi.middleware.cors import CORSMiddleware


from trader import config, dashboard_state, run_trader, LOG_FILE

# Global testnet client for fetching UI data
load_dotenv()
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_SECRET_KEY')
ui_client = Client(api_key, api_secret, testnet=True)

trader_thread = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global trader_thread
    print("Starting trader thread...")
    config.is_running = True
    trader_thread = threading.Thread(target=run_trader, daemon=True)
    trader_thread.start()
    
    yield
    
    # Shutdown
    print("Shutting down trader thread...")
    config.is_running = False
    if trader_thread:
        trader_thread.join(timeout=5.0)

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000",
                   "https://lemon-river-036346300.7.azurestaticapps.net"
                  ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/price")
def get_price_data(symbol: str = "BTCUSDT"):
    coin_data = dashboard_state["coins"].get(symbol, {})
    return {
        "price": coin_data.get("price", 0),
        "rsi": coin_data.get("rsi", 0),
        "macd": coin_data.get("macd", 0),
        "macd_signal": coin_data.get("macd_signal", 0),
        "ema20": coin_data.get("ema20", 0),
        "ema50": coin_data.get("ema50", 0),
        "message": coin_data.get("message", dashboard_state["global_message"])
    }

@app.get("/api/balance")
def get_balance():
    return dashboard_state["balances"]

@app.get("/api/signal")
def get_current_signal(symbol: str = "BTCUSDT"):
    return {"signal": dashboard_state["coins"].get(symbol, {}).get("signal", "HOLD")}

@app.get("/api/allcoins")
def get_all_coins():
    summary = []
    for sym, data in dashboard_state["coins"].items():
        summary.append({
            "symbol": sym,
            "price": data.get("price", 0),
            "rsi": data.get("rsi", 0),
            "signal": data.get("signal", "HOLD")
        })
    return summary

@app.get("/api/candles")
def get_candles(symbol: str = "BTCUSDT"):
    try:
        # Fetch last 50 candles (1h timeframe)
        klines = ui_client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=50)
        formatted_data = []
        for k in klines:
            # klines format: [open_time, open, high, low, close, volume, ...]
            formatted_data.append({
                "time": int(k[0] / 1000), # Unix timestamp in seconds for lightweight-charts
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]) # volume
            })
        return formatted_data
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/trades")
def get_trades(symbol: str = None):
    trades = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, mode='r') as file:
            reader = csv.reader(file)
            headers = next(reader, None)
            if not headers:
                return []
            
            has_symbol = 'Symbol' in headers
            
            for row in reader:
                if not row: continue
                
                if has_symbol:
                    if len(row) < 6: continue
                    row_sym = row[1]
                    if symbol and row_sym != symbol:
                        continue
                    trades.append({
                        "Timestamp": row[0],
                        "Symbol": row[1],
                        "Signal": row[2],
                        "Price": row[3],
                        "Amount": row[4],
                        "Order ID": row[5]
                    })
                else:
                    if len(row) < 5: continue
                    # Old format, assume BTCUSDT
                    row_sym = 'BTCUSDT'
                    if symbol and row_sym != symbol:
                        continue
                    trades.append({
                        "Timestamp": row[0],
                        "Symbol": row_sym,
                        "Signal": row[1],
                        "Price": row[2],
                        "Amount": row[3],
                        "Order ID": row[4]
                    })
    # Return last 10 trades reversed (newest first)
    return trades[-10:][::-1]

class SettingsUpdate(BaseModel):
    auto_trade: bool
    max_amount: float
    stop_loss: float

@app.post("/api/settings")
def update_settings(settings: SettingsUpdate):
    config.auto_trade = settings.auto_trade
    config.max_trade_amount = settings.max_amount
    config.stop_loss_pct = settings.stop_loss
    return {"status": "success", "config": {
        "auto_trade": config.auto_trade,
        "max_trade_amount": config.max_trade_amount,
        "stop_loss_pct": config.stop_loss_pct
    }}

@app.get("/api/settings")
def get_settings():
    return {
        "auto_trade": config.auto_trade,
        "max_trade_amount": config.max_trade_amount,
        "stop_loss_pct": config.stop_loss_pct
    }
