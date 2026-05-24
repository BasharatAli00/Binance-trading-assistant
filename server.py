import os
import csv
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from binance.client import Client

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

# Mount the static dashboard folder
# We will create this directory shortly
os.makedirs("dashboard", exist_ok=True)
app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")

@app.get("/")
def read_root():
    return {"message": "Server running. Go to /dashboard"}

@app.get("/api/price")
def get_price_data():
    return {
        "price": dashboard_state.get("price", 0),
        "rsi": dashboard_state.get("rsi", 0),
        "macd": dashboard_state.get("macd", 0),
        "macd_signal": dashboard_state.get("macd_signal", 0),
        "ema20": dashboard_state.get("ema20", 0),
        "ema50": dashboard_state.get("ema50", 0),
        "message": dashboard_state.get("message", "")
    }

@app.get("/api/balance")
def get_balance():
    return {
        "usdt": dashboard_state.get("usdt_balance", 0),
        "btc": dashboard_state.get("btc_balance", 0)
    }

@app.get("/api/signal")
def get_current_signal():
    return {"signal": dashboard_state.get("signal", "HOLD")}

@app.get("/api/candles")
def get_candles():
    try:
        # Fetch last 50 candles (1h timeframe)
        klines = ui_client.get_klines(symbol='BTCUSDT', interval=Client.KLINE_INTERVAL_1HOUR, limit=50)
        formatted_data = []
        for k in klines:
            # klines format: [open_time, open, high, low, close, volume, ...]
            formatted_data.append({
                "time": int(k[0] / 1000), # Unix timestamp in seconds for lightweight-charts
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "value": float(k[5]) # volume
            })
        return formatted_data
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/trades")
def get_trades():
    trades = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, mode='r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                trades.append(row)
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
