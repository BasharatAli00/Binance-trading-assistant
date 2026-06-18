import os
import pandas as pd
import ta
from dotenv import load_dotenv
from binance.client import Client

from fear_greed import get_fear_greed

# Decision thresholds for the weighted score (range is roughly -7..+7)
# TEMPORARY (test mode): BUY lowered to -1 so the bot buys easily and you can
# watch a full buy -> hold -> sell/P&L cycle. Restore BUY_THRESHOLD = 2 for the
# real, more selective strategy.
BUY_THRESHOLD = -1
SELL_THRESHOLD = -2


def compute_signal(rsi, macd_hist, bullish_cross, bearish_cross, price, ema20, ema50, fng=None, news_score=0, volume_spike=False, hash_rate_drop=False, taapi_score=0, trends_score=0):
    """Weighted multi-indicator score -> (signal, score, reason).

    Each indicator nudges a score up (bullish) or down (bearish). The final
    score is compared against the BUY/SELL thresholds. Returns a short
    human-readable reason describing the strongest contributors.

    `fng` is the optional market-wide Fear & Greed value (0-100). It contributes
    a small contrarian nudge only at extremes: Extreme Fear leans bullish,
    Extreme Greed leans bearish. It never drives a decision on its own.
    
    `news_score` is based on the latest 10 news headlines.
    `volume_spike` adds a +1 BUY signal when on-chain volume surges.
    `hash_rate_drop` adds a warning to the reason string.
    """
    score = 0
    reasons = []

    # RSI momentum
    if rsi < 30:
        score += 2; reasons.append("RSI oversold")
    elif rsi < 45:
        score += 1; reasons.append("RSI below midline")
    elif rsi > 70:
        score -= 2; reasons.append("RSI overbought")
    elif rsi > 55:
        score -= 1; reasons.append("RSI above midline")

    # MACD histogram (momentum direction)
    if macd_hist > 0:
        score += 1; reasons.append("MACD positive")
    elif macd_hist < 0:
        score -= 1; reasons.append("MACD negative")

    # MACD crossover (stronger, fresh momentum shift)
    if bullish_cross:
        score += 1; reasons.append("MACD bullish cross")
    if bearish_cross:
        score -= 1; reasons.append("MACD bearish cross")

    # Trend regime (EMA20 vs EMA50)
    if ema20 > ema50:
        score += 1; reasons.append("Uptrend")
    elif ema20 < ema50:
        score -= 1; reasons.append("Downtrend")

    # Price relative to short EMA
    if price > ema20:
        score += 1
    elif price < ema20:
        score -= 1

    # Market-wide sentiment (small contrarian nudge at extremes only)
    if fng is not None:
        if fng <= 20:
            score += 1; reasons.append("Extreme Fear (contrarian buy)")
        elif fng >= 80:
            score -= 1; reasons.append("Extreme Greed (contrarian sell)")
            
    # News sentiment
    if news_score > 0:
        score += 1; reasons.append("Positive Crypto News")
    elif news_score < 0:
        score -= 1; reasons.append("Negative Crypto News")
        
    # On-Chain signals
    if volume_spike:
        score += 1; reasons.append("On-Chain Volume Spike")
    if hash_rate_drop:
        reasons.append("Warning: Hash Rate Drop")

    # Supplementary Taapi.io indicators (net bullish/bearish nudge)
    if taapi_score > 0:
        score += taapi_score; reasons.append("Taapi bullish")
    elif taapi_score < 0:
        score += taapi_score; reasons.append("Taapi bearish")

    # Google Trends search interest (rising = full BUY, falling = mild pressure)
    if trends_score > 0:
        score += 1; reasons.append("Search interest rising")
    elif trends_score < 0:
        score -= 1; reasons.append("Search interest falling (mild)")

    if score >= BUY_THRESHOLD:
        signal = "BUY"
    elif score <= SELL_THRESHOLD:
        signal = "SELL"
    else:
        signal = "HOLD"

    reason = ", ".join(reasons[:3]) if reasons else "Neutral"
    return signal, score, reason


def get_news_sentiment_score():
    try:
        from database import SessionLocal
        from models import NewsArticle
        db = SessionLocal()
        articles = db.query(NewsArticle).order_by(NewsArticle.timestamp.desc()).limit(10).all()
        db.close()
        
        pos = sum(1 for a in articles if a.sentiment == 'Positive')
        neg = sum(1 for a in articles if a.sentiment == 'Negative')
        
        if pos > 5:
            return 1
        if neg > 5:
            return -1
        return 0
    except Exception as e:
        print(f"Error getting news sentiment: {e}")
        return 0

def get_onchain_signal_flags():
    try:
        from database import SessionLocal
        from models import OnChainStats
        from datetime import datetime, timedelta
        db = SessionLocal()
        latest = db.query(OnChainStats).order_by(OnChainStats.timestamp.desc()).first()
        if not latest:
            db.close()
            return False, False
            
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        past_week = db.query(OnChainStats).filter(OnChainStats.timestamp >= seven_days_ago).all()
        
        avg_volume = sum(s.estimated_transaction_volume_usd for s in past_week) / len(past_week) if past_week else 0
        volume_spike = False
        if avg_volume > 0 and latest.estimated_transaction_volume_usd > (avg_volume * 1.3):
            volume_spike = True
            
        prev = db.query(OnChainStats).order_by(OnChainStats.timestamp.desc()).offset(1).first()
        hash_rate_drop = False
        if prev and prev.hash_rate > 0 and latest.hash_rate < (prev.hash_rate * 0.9):
            hash_rate_drop = True
            
        db.close()
        return volume_spike, hash_rate_drop
    except Exception as e:
        print(f"Error getting onchain signals: {e}")
        return False, False

def get_taapi_signal_score(symbol="BTCUSDT"):
    """Net BUY/SELL nudge from the supplementary Taapi.io indicators.

    +1 RSI < 30, -1 RSI > 70; +1 MACD line crossing above its signal line,
    -1 crossing below (detected against the previously stored Taapi row).
    Returns 0 if no Taapi data is available, so it never blocks a decision.
    """
    try:
        from database import SessionLocal
        from models import TaapiIndicator
        db = SessionLocal()
        rows = db.query(TaapiIndicator).filter(
            TaapiIndicator.symbol == symbol
        ).order_by(TaapiIndicator.timestamp.desc()).limit(2).all()
        db.close()

        if not rows:
            return 0
        latest = rows[0]
        prev = rows[1] if len(rows) > 1 else None

        score = 0
        if latest.rsi is not None:
            if latest.rsi < 30:
                score += 1
            elif latest.rsi > 70:
                score -= 1

        # MACD crossover vs the previous stored reading
        if (latest.macd is not None and latest.macd_signal is not None
                and prev is not None and prev.macd is not None and prev.macd_signal is not None):
            if prev.macd <= prev.macd_signal and latest.macd > latest.macd_signal:
                score += 1
            elif prev.macd >= prev.macd_signal and latest.macd < latest.macd_signal:
                score -= 1

        return score
    except Exception as e:
        print(f"Error getting Taapi signal: {e}")
        return 0

def get_trends_signal_score():
    """Nudge from Google Trends week-over-week search interest for "Bitcoin".

    +1 if interest is rising more than 10% WoW, -1 if falling more than 10%
    WoW (mild sell pressure). Returns 0 otherwise or if no data is available.
    """
    try:
        from database import SessionLocal
        from models import GoogleTrend
        db = SessionLocal()
        latest = db.query(GoogleTrend).order_by(GoogleTrend.timestamp.desc()).first()
        db.close()

        if not latest or latest.wow_change_pct is None:
            return 0
        if latest.wow_change_pct > 10:
            return 1
        if latest.wow_change_pct < -10:
            return -1
        return 0
    except Exception as e:
        print(f"Error getting Google Trends signal: {e}")
        return 0

def compute_indicator_df(client, symbol, limit=300):
    """Full indicator frame for the trend-following strategy (matches backtest).

    Fetches enough 1h candles to warm up EMA200/ADX and returns a DataFrame with
    EMA20/50/200, RSI, MACD(+hist), ATR and ADX. Returns None on fetch error.
    """
    try:
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=limit)
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

    df = pd.DataFrame(klines, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume',
                                       'Close time', 'qav', 'trades', 'tbbav', 'tbqav', 'ignore'])
    for c in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df[c] = pd.to_numeric(df[c])
    df['ema20'] = ta.trend.EMAIndicator(df['Close'], window=20).ema_indicator()
    df['ema50'] = ta.trend.EMAIndicator(df['Close'], window=50).ema_indicator()
    df['ema200'] = ta.trend.EMAIndicator(df['Close'], window=200).ema_indicator()
    df['rsi'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
    macd = ta.trend.MACD(df['Close'], window_slow=26, window_fast=12, window_sign=9)
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    df['atr'] = ta.volatility.AverageTrueRange(df['High'], df['Low'], df['Close'], window=14).average_true_range()
    df['adx'] = ta.trend.ADXIndicator(df['High'], df['Low'], df['Close'], window=14).adx()
    return df


def _row_to_ind(r):
    """Map a DataFrame row to the dict shape strategy.py expects."""
    return {
        "close": float(r['Close']), "ema20": float(r['ema20']), "ema50": float(r['ema50']),
        "ema200": float(r['ema200']), "rsi": float(r['rsi']), "macd": float(r['macd']),
        "macd_signal": float(r['macd_signal']), "macd_hist": float(r['macd_hist']),
        "atr": float(r['atr']), "adx": float(r['adx']),
    }


def latest_closed(df):
    """Return (ind, prev, live_price) using the last CLOSED candle.

    The final row is the still-forming candle; we decide on the last *closed*
    candle (iloc[-2]) so signals don't repaint, but use the forming candle's
    close as the live price for stop checks and fills.
    """
    if df is None or len(df) < 3:
        return None, None, None
    closed = df.iloc[-2]
    prev = df.iloc[-3]
    live_price = float(df.iloc[-1]['Close'])
    if pd.isna(closed['ema200']) or pd.isna(closed['adx']) or pd.isna(closed['atr']):
        return None, None, live_price
    return _row_to_ind(closed), _row_to_ind(prev), live_price


def get_signal(client, symbol):
    try:
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=100)
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

    # Klines format: [Open time, Open, High, Low, Close, Volume, Close time, Quote asset volume, Number of trades, Taker buy base asset volume, Taker buy quote asset volume, Ignore]
    df = pd.DataFrame(klines, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time', 'Quote asset volume', 'Number of trades', 'Taker buy base asset volume', 'Taker buy quote asset volume', 'Ignore'])
    df['Close'] = pd.to_numeric(df['Close'])
    
    # Calculate indicators
    df['RSI'] = ta.momentum.RSIIndicator(close=df['Close'], window=14).rsi()
    
    macd = ta.trend.MACD(close=df['Close'], window_slow=26, window_fast=12, window_sign=9)
    df['MACD'] = macd.macd()
    df['MACD_Signal'] = macd.macd_signal()
    
    df['EMA20'] = ta.trend.EMAIndicator(close=df['Close'], window=20).ema_indicator()
    df['EMA50'] = ta.trend.EMAIndicator(close=df['Close'], window=50).ema_indicator()
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    current_price = latest['Close']
    rsi_val = latest['RSI']
    macd_val = latest['MACD']
    macd_signal = latest['MACD_Signal']
    ema20 = latest['EMA20']
    ema50 = latest['EMA50']
    macd_hist = macd_val - macd_signal

    bullish_cross = prev['MACD'] <= prev['MACD_Signal'] and latest['MACD'] > latest['MACD_Signal']
    bearish_cross = prev['MACD'] >= prev['MACD_Signal'] and latest['MACD'] < latest['MACD_Signal']

    # Market-wide sentiment (cached, fetches at most once per day)
    fng_snapshot = get_fear_greed()
    fng_value = fng_snapshot["value"]
    
    news_score = get_news_sentiment_score()
    volume_spike, hash_rate_drop = get_onchain_signal_flags()
    taapi_score = get_taapi_signal_score(symbol)
    trends_score = get_trends_signal_score()

    signal, score, reason = compute_signal(
        rsi_val, macd_hist, bullish_cross, bearish_cross, current_price, ema20, ema50, fng_value, news_score, volume_spike, hash_rate_drop, taapi_score, trends_score
    )

    return {
        'price': current_price,
        'rsi': rsi_val,
        'macd': macd_val,
        'macd_signal': macd_signal,
        'ema20': ema20,
        'ema50': ema50,
        'signal': signal,
        'score': score,
        'reason': reason,
        'fng': fng_value,
        'fng_class': fng_snapshot["classification"]
    }

def main():
    load_dotenv()
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_SECRET_KEY')

    if not api_key or not api_secret:
        print("Error: API keys not found in .env")
        return

    client = Client(api_key, api_secret)
    
    print("Fetching last 100 candles of BTCUSDT (1h timeframe)...")
    data = get_signal(client, 'BTCUSDT')
    if data:
        print("\n--- Market Data (BTCUSDT) ---")
        print(f"Current Price : ${data['price']:.2f}")
        print(f"RSI (14)      : {data['rsi']:.2f}")
        print(f"MACD          : {data['macd']:.2f} (Signal: {data['macd_signal']:.2f})")
        print(f"EMA20         : ${data['ema20']:.2f}")
        print(f"EMA50         : ${data['ema50']:.2f}")
        print("-----------------------------")
        print(f"Final Signal  : {data['signal']}")
        print("-----------------------------")

if __name__ == '__main__':
    main()
