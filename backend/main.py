import os
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

import paper_engine
import pivot_config
from trader import config, dashboard_state, run_trader
from database import SessionLocal
from models import Candle, Indicator, MarketStats

# Strategy #3 (Intelligent Sniper) — fully isolated, gated by SNIPER_ENABLED.
import sniper_config
import sniper_engine
import sniper_loop
from sniper_api import router as sniper_router

# Public client for fetching UI chart data (live market prices, no keys needed)
load_dotenv()
ui_client = Client()

trader_thread = None
sniper_thread = None

scheduler = AsyncIOScheduler()


def _pivot_cron_hours(interval_hours):
    """Cron 'hour' expression that fires on every N-hour boundary from midnight."""
    return ",".join(str(h) for h in range(0, 24, interval_hours))


async def run_data_collector():
    try:
        print("Running data collector...")
        from data_collector import backfill_data
        await asyncio.to_thread(backfill_data)
        print("Data collector completed successfully!")
    except Exception as e:
        print(f"Data collector error: {e}")

async def run_news_collector():
    try:
        print("Running news collector...")
        from news_fetcher import fetch_and_store_news
        await asyncio.to_thread(fetch_and_store_news)
        print("News collector completed successfully!")
    except Exception as e:
        print(f"News collector error: {e}")

async def run_onchain_collector():
    try:
        print("Running on-chain collector...")
        from blockchain_fetcher import fetch_and_store_onchain_stats
        await asyncio.to_thread(fetch_and_store_onchain_stats)
        print("On-chain collector completed successfully!")
    except Exception as e:
        print(f"On-chain collector error: {e}")

async def run_taapi_collector():
    try:
        print("Running Taapi indicators collector...")
        from taapi_fetcher import fetch_and_store_taapi
        await asyncio.to_thread(fetch_and_store_taapi)
        print("Taapi collector completed successfully!")
    except Exception as e:
        print(f"Taapi collector error: {e}")

async def run_trends_collector():
    try:
        print("Running Google Trends collector...")
        from google_trends_fetcher import fetch_and_store_trends
        await asyncio.to_thread(fetch_and_store_trends)
        print("Google Trends collector completed successfully!")
    except Exception as e:
        print(f"Google Trends collector error: {e}")

async def run_pivots_collector():
    try:
        print("Running pivot-levels collector...")
        from pivots import fetch_and_store_pivots
        await asyncio.to_thread(fetch_and_store_pivots)
        print("Pivot-levels collector completed successfully!")
    except Exception as e:
        print(f"Pivot-levels collector error: {e}")

async def run_futures_collector():
    try:
        print("Running futures-stats collector...")
        from futures_fetcher import fetch_and_store_futures_stats
        await asyncio.to_thread(fetch_and_store_futures_stats)
        print("Futures-stats collector completed successfully!")
    except Exception as e:
        print(f"Futures-stats collector error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global trader_thread
    print("Initializing paper wallet...")
    paper_engine.ensure_initialized()
    import pivot_engine
    pivot_engine.ensure_initialized()  # strategy #2's isolated wallet
    pivot_config.ensure_initialized()  # strategy #2's recompute-interval setting
    print("Starting trader thread...")
    config.is_running = True
    trader_thread = threading.Thread(target=run_trader, daemon=True)
    trader_thread.start()

    # Strategy #3 — start its own isolated loop (only if enabled). A failure to
    # start it must never block the rest of the app, so it's guarded.
    global sniper_thread
    if sniper_config.SNIPER_ENABLED:
        try:
            print("Starting Intelligent Sniper (Strategy #3) thread...")
            sniper_engine.ensure_initialized()
            sniper_thread = threading.Thread(target=sniper_loop.run_sniper, daemon=True)
            sniper_thread.start()
        except Exception as e:
            print(f"[sniper] failed to start (continuing without it): {e}")
    else:
        print("Intelligent Sniper disabled (SNIPER_ENABLED=false)")


    scheduler.add_job(
        run_data_collector,
        'cron',
        minute=0,
        id='data_collector_job'
    )
    scheduler.add_job(
        run_news_collector,
        'cron',
        minute=5,  # Run 5 minutes after the hour to stagger API calls
        id='news_collector_job'
    )
    scheduler.add_job(
        run_onchain_collector,
        'cron',
        minute=10,  # Run 10 minutes after the hour
        id='onchain_collector_job'
    )
    scheduler.add_job(
        run_taapi_collector,
        'cron',
        minute=15,  # Run 15 minutes after the hour to stagger API calls
        id='taapi_collector_job'
    )
    scheduler.add_job(
        run_trends_collector,
        'cron',
        hour=0, minute=20,  # Once a day (Google Trends is heavily rate-limited)
        id='trends_collector_job'
    )
    scheduler.add_job(
        run_pivots_collector,
        'cron',
        # Recompute the pivot bracket on every configured N-hour boundary.
        hour=_pivot_cron_hours(pivot_config.get_interval_hours()), minute=25,
        id='pivots_collector_job'
    )
    scheduler.add_job(
        run_futures_collector,
        'cron',
        minute=30,  # Hourly, staggered after the other fetchers
        id='futures_collector_job'
    )
    scheduler.start()
    print("Scheduler started - data collector will run every hour")

    await run_data_collector()
    await run_news_collector()
    await run_onchain_collector()
    await run_pivots_collector()
    await run_futures_collector()
    # Taapi's free-tier rate limit forces ~30s of inter-request sleeps, so kick
    # it off in the background instead of blocking startup on it.
    asyncio.create_task(run_taapi_collector())
    # Google Trends may retry with backoff; run it in the background too.
    asyncio.create_task(run_trends_collector())
    
    yield
    
    # Shutdown
    print("Shutting down trader thread...")
    config.is_running = False
    if trader_thread:
        trader_thread.join(timeout=5.0)

    sniper_loop.stop()
    if sniper_thread:
        sniper_thread.join(timeout=5.0)

    scheduler.shutdown()
    print("Scheduler stopped")

app = FastAPI(lifespan=lifespan)
app.include_router(sniper_router)

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

def _portfolio_payload():
    """Build the wallet snapshot using the latest dashboard prices."""
    prices = {sym.replace("USDT", ""): data.get("price", 0.0)
              for sym, data in dashboard_state["coins"].items()}
    summary = paper_engine.portfolio_summary(prices)
    btc = next((h for h in summary["holdings"] if h["base"] == "BTC"), None)
    payload = dict(summary["balances"])  # USDT, BTC, ...
    for asset in ["USDT", "BTC", "ETH", "SOL", "BNB"]:
        payload.setdefault(asset, 0.0)
    payload.update({
        "cash": summary["cash"],
        "positions_value": summary["positions_value"],
        "total_equity": summary["total_equity"],
        "unrealized_pnl": summary["unrealized_pnl"],
        "realized_pnl": summary["realized_pnl"],
        "total_pnl": summary["total_pnl"],
        "total_pnl_pct": summary["total_pnl_pct"],
        "starting_balance": summary["starting_balance"],
        "btc_avg_entry": btc["avg_entry_price"] if btc else 0.0,
        "btc_value": btc["value"] if btc else 0.0,
        "holdings": summary["holdings"],
    })
    return payload

@app.get("/api/balance")
def get_balance():
    return _portfolio_payload()

@app.get("/api/portfolio")
def get_portfolio():
    return _portfolio_payload()

@app.post("/api/reset")
def reset_wallet():
    result = paper_engine.reset_wallet(clear_trades=True)
    # Clear cached signal-driven messages and strategy position flags so the UI
    # reflects the flat wallet immediately (rather than after the next cycle).
    for sym in dashboard_state["coins"]:
        c = dashboard_state["coins"][sym]
        c["message"] = "Wallet reset"
        c["in_position"] = False
        c["entry_price"] = 0.0
        c["stop_price"] = 0.0
        c["unrealized_r"] = 0.0
    return result

@app.get("/api/signal")
def get_current_signal(symbol: str = "BTCUSDT"):
    return {"signal": dashboard_state["coins"].get(symbol, {}).get("signal", "HOLD")}

@app.get("/api/strategy")
def get_strategy_state(symbol: str = "BTCUSDT"):
    """Live trend-following strategy state for a traded symbol."""
    c = dashboard_state["coins"].get(symbol, {})
    return {
        "symbol": symbol,
        "price": c.get("price", 0.0),
        "signal": c.get("signal", "HOLD"),
        "message": c.get("message", ""),
        "in_position": c.get("in_position", False),
        "entry_price": c.get("entry_price", 0.0),
        "stop_price": c.get("stop_price", 0.0),
        "unrealized_r": c.get("unrealized_r", 0.0),
        "adx": c.get("adx", 0.0),
        "atr": c.get("atr", 0.0),
        "rsi": c.get("rsi", 0.0),
        "ema200": c.get("ema200", 0.0),
    }

@app.get("/api/feargreed")
def get_fear_greed_index():
    """Market-wide crypto Fear & Greed Index (cached, refreshes ~once a day)."""
    from fear_greed import get_fear_greed
    return get_fear_greed()

@app.get("/api/orderbook")
def get_order_book_data(symbol: str = "BTCUSDT"):
    """Top 10 bids/asks from the Binance public order book (cached briefly)."""
    from binance_extras import get_order_book
    return get_order_book(symbol)

@app.get("/api/aggtrades")
def get_agg_trades_data(symbol: str = "BTCUSDT"):
    """Last 50 aggregate trades from Binance, newest first (cached briefly)."""
    from binance_extras import get_agg_trades
    return get_agg_trades(symbol)

@app.get("/api/avgprice")
def get_avg_price_data(symbol: str = "BTCUSDT"):
    """Binance real-time average price (cached briefly)."""
    from binance_extras import get_avg_price
    return get_avg_price(symbol)

@app.get("/api/marketdepth")
def get_market_depth_data(symbol: str = "BTCUSDT"):
    """Combined order book + aggregate trades + avg price snapshot."""
    from binance_extras import get_market_depth
    return get_market_depth(symbol)

@app.get("/api/news")
def get_news_data():
    """Get the latest 3 BTC news articles from the database."""
    from models import NewsArticle
    db = SessionLocal()
    try:
        articles = db.query(NewsArticle).order_by(NewsArticle.timestamp.desc()).limit(3).all()
        return [
            {
                "id": str(a.id),
                "timestamp": a.timestamp.isoformat(),
                "title": a.title,
                "url": a.url,
                "sentiment": a.sentiment,
                "source": a.source
            }
            for a in articles
        ]
    finally:
        db.close()

@app.get("/api/onchain")
def get_onchain_data():
    """Get the latest Bitcoin on-chain stats and 7-day volume average."""
    from models import OnChainStats
    from datetime import datetime, timedelta
    db = SessionLocal()
    try:
        latest = db.query(OnChainStats).order_by(OnChainStats.timestamp.desc()).first()
        if not latest:
            return JSONResponse(status_code=404, content={"error": "On-chain data not found"})
            
        # Calculate 7-day average volume
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        past_week = db.query(OnChainStats).filter(OnChainStats.timestamp >= seven_days_ago).all()
        
        avg_volume = 0
        if past_week:
            avg_volume = sum(s.estimated_transaction_volume_usd for s in past_week) / len(past_week)
            
        is_spike = False
        if avg_volume > 0 and latest.estimated_transaction_volume_usd > (avg_volume * 1.3):
            is_spike = True
            
        # Check hash rate drop compared to previous entry
        prev = db.query(OnChainStats).order_by(OnChainStats.timestamp.desc()).offset(1).first()
        hash_drop = False
        if prev and prev.hash_rate > 0:
            if latest.hash_rate < (prev.hash_rate * 0.9):
                hash_drop = True

        return {
            "n_tx": latest.n_tx,
            "total_fees_btc": latest.total_fees_btc,
            "hash_rate": latest.hash_rate,
            "difficulty": latest.difficulty,
            "estimated_transaction_volume_usd": latest.estimated_transaction_volume_usd,
            "volume_7d_avg": avg_volume,
            "is_volume_spike": is_spike,
            "is_hash_rate_drop": hash_drop,
            "timestamp": latest.timestamp.isoformat()
        }
    finally:
        db.close()

@app.get("/api/taapi")
def get_taapi_data(symbol: str = "BTCUSDT"):
    """Latest supplementary Taapi.io indicators (RSI/MACD/EMA20) from storage."""
    from models import TaapiIndicator
    db = SessionLocal()
    try:
        latest = db.query(TaapiIndicator).filter(
            TaapiIndicator.symbol == symbol
        ).order_by(TaapiIndicator.timestamp.desc()).first()
        if not latest:
            return JSONResponse(status_code=404, content={"error": "Taapi data not found"})
        return {
            "symbol": latest.symbol,
            "rsi": latest.rsi,
            "macd": latest.macd,
            "macd_signal": latest.macd_signal,
            "macd_hist": latest.macd_hist,
            "ema20": latest.ema20,
            "timestamp": latest.timestamp.isoformat(),
        }
    finally:
        db.close()

@app.get("/api/trends")
def get_trends_data():
    """Latest Google Trends search-interest for "Bitcoin" + week-over-week change."""
    from models import GoogleTrend
    db = SessionLocal()
    try:
        latest = db.query(GoogleTrend).order_by(GoogleTrend.timestamp.desc()).first()
        if not latest:
            return JSONResponse(status_code=404, content={"error": "Trends data not found"})
        return {
            "keyword": latest.keyword,
            "trend_score": latest.trend_score,
            "prev_score": latest.prev_score,
            "wow_change_pct": latest.wow_change_pct,
            "timestamp": latest.timestamp.isoformat(),
        }
    finally:
        db.close()

@app.get("/api/pivots")
def get_pivots_data(symbol: str = "BTCUSDT"):
    """Latest daily pivot levels (PP, R1-R3, S1-S3) + trend bias from storage."""
    from models import PivotLevels
    db = SessionLocal()
    try:
        latest = db.query(PivotLevels).filter(
            PivotLevels.symbol == symbol
        ).order_by(PivotLevels.timestamp.desc()).first()
        if not latest:
            return JSONResponse(status_code=404, content={"error": "Pivot data not found"})
        return {
            "symbol": latest.symbol,
            "pp": latest.pp,
            "r1": latest.r1, "r2": latest.r2, "r3": latest.r3,
            "s1": latest.s1, "s2": latest.s2, "s3": latest.s3,
            "trend": latest.trend,
            "timestamp": latest.timestamp.isoformat(),
        }
    finally:
        db.close()

@app.get("/api/futures")
def get_futures_data(symbol: str = "BTCUSDT"):
    """Latest perpetual-futures long/short ratio + funding rate from storage."""
    from models import FuturesStats
    db = SessionLocal()
    try:
        latest = db.query(FuturesStats).filter(
            FuturesStats.symbol == symbol
        ).order_by(FuturesStats.timestamp.desc()).first()
        if not latest:
            return JSONResponse(status_code=404, content={"error": "Futures data not found"})
        return {
            "symbol": latest.symbol,
            "long_pct": latest.long_pct,
            "short_pct": latest.short_pct,
            "long_short_ratio": latest.long_short_ratio,
            "funding_rate": latest.funding_rate,
            "funding_direction": latest.funding_direction,
            "next_funding_time": latest.next_funding_time.isoformat() if latest.next_funding_time else None,
            "timestamp": latest.timestamp.isoformat(),
        }
    finally:
        db.close()

@app.get("/api/pivot-portfolio")
def get_pivot_portfolio():
    """Strategy #2 (pivot-bracket) wallet snapshot — its own isolated balance/P&L."""
    import pivot_engine
    prices = {sym.replace("USDT", ""): dashboard_state["coins"].get(sym, {}).get("price", 0.0)
              for sym in dashboard_state["coins"]}
    return pivot_engine.portfolio_summary(prices)

@app.get("/api/pivot-trades")
def get_pivot_trades(symbol: str = None):
    """Recent trades from the pivot-bracket strategy (newest first)."""
    import pivot_engine
    return pivot_engine.get_recent_trades(symbol=symbol, limit=20)

@app.get("/api/pivot-strategy")
def get_pivot_strategy_state(symbol: str = "BTCUSDT"):
    """Live pivot-bracket strategy state (signal, bracket levels, position)."""
    from trader import pivot_dashboard
    return pivot_dashboard.get(symbol, {})

@app.post("/api/pivot-reset")
def reset_pivot_wallet():
    """Reset the pivot-bracket strategy wallet back to its starting balance."""
    import pivot_engine
    result = pivot_engine.reset_wallet(clear_trades=True)
    from trader import pivot_dashboard
    for sym in pivot_dashboard:
        pivot_dashboard[sym].update({
            "signal": "HOLD", "message": "Wallet reset", "in_position": False,
            "entry_price": 0.0, "take_profit": 0.0, "stop_price": 0.0,
        })
    return result

@app.get("/api/pivot-interval")
def get_pivot_interval():
    """Strategy #2's current recompute interval (hours) + the selectable options."""
    return {
        "interval_hours": pivot_config.get_interval_hours(),
        "allowed": pivot_config.ALLOWED_HOURS,
    }


class PivotIntervalUpdate(BaseModel):
    interval_hours: int


@app.post("/api/pivot-interval")
async def set_pivot_interval(update: PivotIntervalUpdate):
    """Set how often strategy #2 recomputes S/R (and the candle period it uses).

    Changing the interval resets strategy #2's wallet so each interval can be
    evaluated from a clean 5000 USDT baseline. The recompute job is rescheduled to
    the new period and a fresh bracket is computed immediately.
    """
    import pivot_engine
    try:
        hours = pivot_config.set_interval_hours(update.interval_hours)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    # Reschedule the recompute job to fire on the new N-hour boundaries.
    try:
        scheduler.reschedule_job(
            'pivots_collector_job', trigger='cron',
            hour=_pivot_cron_hours(hours), minute=25,
        )
    except Exception as e:
        print(f"Could not reschedule pivots job: {e}")

    # Reset strategy #2's wallet for a clean comparison at the new interval.
    pivot_engine.reset_wallet(clear_trades=True)
    from trader import pivot_dashboard, _pivot_cooldown
    _pivot_cooldown.clear()
    for sym in pivot_dashboard:
        pivot_dashboard[sym].update({
            "signal": "HOLD", "message": f"Interval set to {hours}h — wallet reset",
            "in_position": False, "entry_price": 0.0, "take_profit": 0.0, "stop_price": 0.0,
        })

    # Compute a fresh bracket right away so the new setting takes effect now.
    await run_pivots_collector()
    return {"interval_hours": hours, "status": "updated"}


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
    # Newest first, from the paper-trading DB
    return paper_engine.get_recent_trades(symbol=symbol, limit=20)

class SettingsUpdate(BaseModel):
    auto_trade: bool
    position_size_pct: float   # as a percentage, e.g. 20 for 20%
    stop_loss: float           # as a percentage, e.g. 2 for 2%
    take_profit: float         # as a percentage, e.g. 5 for 5%

@app.post("/api/settings")
def update_settings(settings: SettingsUpdate):
    config.auto_trade = settings.auto_trade
    config.position_size_pct = settings.position_size_pct / 100.0
    config.stop_loss_pct = settings.stop_loss / 100.0
    config.take_profit_pct = settings.take_profit / 100.0
    return {"status": "success", "config": get_settings()}

@app.get("/api/settings")
def get_settings():
    return {
        "auto_trade": config.auto_trade,
        "position_size_pct": config.position_size_pct,
        "stop_loss_pct": config.stop_loss_pct,
        "take_profit_pct": config.take_profit_pct
    }
