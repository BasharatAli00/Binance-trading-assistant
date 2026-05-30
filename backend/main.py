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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio

from trader import config, dashboard_state, run_trader, LOG_FILE
from database import SessionLocal
from models import Candle, Indicator, MarketStats

# Global testnet client for fetching UI data
load_dotenv()
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_SECRET_KEY')
ui_client = Client(api_key, api_secret, testnet=True)

trader_thread = None

scheduler = AsyncIOScheduler()

async def run_data_collector():
    try:
        print("Running data collector...")
        from data_collector import backfill_data
        await asyncio.to_thread(backfill_data)
        print("Data collector completed successfully!")
    except Exception as e:
        print(f"Data collector error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global trader_thread
    print("Starting trader thread...")
    config.is_running = True
    trader_thread = threading.Thread(target=run_trader, daemon=True)
    trader_thread.start()
    
    scheduler.add_job(
        run_data_collector,
        'interval',
        hours=1,
        id='data_collector_job'
    )
    scheduler.start()
    print("Scheduler started - data collector will run every hour")
    
    await run_data_collector()
    
    yield
    
    # Shutdown
    print("Shutting down trader thread...")
    config.is_running = False
    if trader_thread:
        trader_thread.join(timeout=5.0)
        
    scheduler.shutdown()
    print("Scheduler stopped")

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

@app.get("/api/dashboard")
def get_dashboard_data(symbol: str = "BTCUSDT"):
    db = SessionLocal()
    try:
        candle = db.query(Candle).filter(Candle.symbol == symbol).order_by(Candle.timestamp.desc()).first()
        indicators_first = db.query(Indicator).filter(Indicator.symbol == symbol).order_by(Indicator.timestamp.desc()).first()
        stats = db.query(MarketStats).filter(MarketStats.symbol == symbol).order_by(MarketStats.timestamp.desc()).first()
        
        if not candle or not indicators_first or not stats:
            return JSONResponse(status_code=404, content={"error": "Data not found for symbol"})
            
        latest_time = indicators_first.timestamp
        all_inds = db.query(Indicator).filter(Indicator.symbol == symbol, Indicator.timestamp == latest_time).all()
        
        ind_dict = {}
        for ind in all_inds:
            ind_dict[ind.name] = ind.value
            
        last_24_candles = db.query(Candle).filter(Candle.symbol == symbol).order_by(Candle.timestamp.desc()).limit(24).all()
        timeline = [c.price_change_1h for c in last_24_candles if c.price_change_1h is not None]
        timeline.reverse()
        
        rsi_val = ind_dict.get('RSI', 0)
        rsi_zone = "OVERSOLD" if rsi_val < 30 else "OVERBOUGHT" if rsi_val > 70 else "NEUTRAL"
        macd_hist = indicators_first.macd_histogram or 0
        macd_trend = "BULLISH" if macd_hist > 0 else "BEARISH"
        
        signal_val = ind_dict.get('Signal', 0)
        sig_str = "BUY" if signal_val == 1.0 else "SELL" if signal_val == -1.0 else "HOLD"
        
        return {
            "price": candle.close,
            "price_change_1h": candle.price_change_1h,
            "price_change_4h": candle.price_change_4h,
            "price_change_24h": candle.price_change_24h,
            "high_24h": candle.high_24h,
            "low_24h": candle.low_24h,
            "volume_24h": stats.volume_24h,
            "volatility": candle.volatility,
            "rsi": rsi_val,
            "rsi_change": indicators_first.rsi_change,
            "rsi_zone": rsi_zone,
            "macd": ind_dict.get('MACD', 0),
            "macd_histogram": macd_hist,
            "macd_trend": macd_trend,
            "ema20": ind_dict.get('EMA20', 0),
            "ema50": ind_dict.get('EMA50', 0),
            "price_vs_ema20": indicators_first.price_vs_ema20,
            "price_vs_ema50": indicators_first.price_vs_ema50,
            "signal": sig_str,
            "signal_strength": indicators_first.signal_strength,
            "weighted_avg_price": stats.weighted_avg_price,
            "trade_count_24h": stats.trade_count_24h,
            "timeline": timeline
        }
    finally:
        db.close()

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
