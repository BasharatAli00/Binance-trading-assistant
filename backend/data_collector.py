import os
import pandas as pd
import ta
import requests
from datetime import datetime
from dotenv import load_dotenv
from binance.client import Client
from database import SessionLocal
from models import Candle, Indicator, MarketStats
from signals import compute_signal

load_dotenv(override=True)

def calculate_signal(row, prev_row):
    if pd.isna(row['RSI']) or pd.isna(row['MACD']) or pd.isna(row['MACD_Signal']):
        return "HOLD"

    bullish_cross = prev_row['MACD'] <= prev_row['MACD_Signal'] and row['MACD'] > row['MACD_Signal']
    bearish_cross = prev_row['MACD'] >= prev_row['MACD_Signal'] and row['MACD'] < row['MACD_Signal']
    macd_hist = row['macd_histogram'] if pd.notna(row['macd_histogram']) else 0.0
    ema50 = row['EMA50'] if pd.notna(row['EMA50']) else row['EMA20']

    signal, _score, _reason = compute_signal(
        row['RSI'], macd_hist, bullish_cross, bearish_cross, row['Close'], row['EMA20'], ema50, fng=None, news_score=0
    )
    return signal

def calculate_signal_strength(row):
    score = 5
    if pd.notna(row['RSI']):
        if row['RSI'] < 30:
            score += 2
        elif row['RSI'] > 70:
            score -= 2
        elif row['RSI'] < 35:
            score += 1
        elif row['RSI'] > 65:
            score -= 1
            
    if pd.notna(row['macd_histogram']):
        if row['macd_histogram'] > 0:
            score += 1
        elif row['macd_histogram'] < 0:
            score -= 1
            
    if pd.notna(row['Close']) and pd.notna(row['EMA20']):
        if row['Close'] > row['EMA20']:
            score += 1
        elif row['Close'] < row['EMA20']:
            score -= 1
            
    if pd.notna(row['price_change_24h']):
        if row['price_change_24h'] > 0:
            score += 1
        elif row['price_change_24h'] < 0:
            score -= 1
            
    return max(1, min(10, int(score)))

def fetch_market_stats(db):
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT"
        resp = requests.get(url).json()
        stats = MarketStats(
            symbol='BTCUSDT',
            timestamp=datetime.utcnow(),
            price_change_24h_pct=float(resp['priceChangePercent']),
            high_24h=float(resp['highPrice']),
            low_24h=float(resp['lowPrice']),
            volume_24h=float(resp['volume']),
            quote_volume_24h=float(resp['quoteVolume']),
            trade_count_24h=int(resp['count']),
            weighted_avg_price=float(resp['weightedAvgPrice'])
        )
        db.add(stats)
        db.commit()
        print("✅ Saved MarketStats from Binance 24h ticker")
    except Exception as e:
        print(f"Failed to fetch market stats: {e}")

def backfill_data():
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_SECRET_KEY')
    client = Client(api_key, api_secret)

    print("Fetching last 1000 candles of BTCUSDT (1h timeframe)...")
    klines = client.get_klines(symbol='BTCUSDT', interval=Client.KLINE_INTERVAL_1HOUR, limit=1000)
    
    df = pd.DataFrame(klines, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time', 'Quote asset volume', 'Number of trades', 'Taker buy base asset volume', 'Taker buy quote asset volume', 'Ignore'])
    df['timestamp'] = pd.to_datetime(df['Open time'], unit='ms')
    df['Open'] = pd.to_numeric(df['Open'])
    df['High'] = pd.to_numeric(df['High'])
    df['Low'] = pd.to_numeric(df['Low'])
    df['Close'] = pd.to_numeric(df['Close'])
    df['Volume'] = pd.to_numeric(df['Volume'])
    
    # Calculate enhanced metrics
    df['price_change_1h'] = df['Close'].pct_change(1) * 100
    df['price_change_4h'] = df['Close'].pct_change(4) * 100
    df['price_change_24h'] = df['Close'].pct_change(24) * 100
    df['high_24h'] = df['High'].rolling(24).max()
    df['low_24h'] = df['Low'].rolling(24).min()
    df['volume_change_24h'] = df['Volume'].pct_change(24) * 100
    df['volatility'] = (df['High'] - df['Low']) / df['Close'] * 100
    df['candle_body'] = abs(df['Close'] - df['Open']) / df['Open'] * 100
    df['is_bullish'] = df['Close'] > df['Open']
    
    # Calculate indicators
    df['RSI'] = ta.momentum.RSIIndicator(close=df['Close'], window=14).rsi()
    df['rsi_change'] = df['RSI'].diff()
    macd = ta.trend.MACD(close=df['Close'], window_slow=26, window_fast=12, window_sign=9)
    df['MACD'] = macd.macd()
    df['MACD_Signal'] = macd.macd_signal()
    df['macd_histogram'] = df['MACD'] - df['MACD_Signal']
    df['EMA20'] = ta.trend.EMAIndicator(close=df['Close'], window=20).ema_indicator()
    df['EMA50'] = ta.trend.EMAIndicator(close=df['Close'], window=50).ema_indicator()
    
    df['price_vs_ema20'] = (df['Close'] - df['EMA20']) / df['EMA20'] * 100
    df['price_vs_ema50'] = (df['Close'] - df['EMA50']) / df['EMA50'] * 100
    df['ema20_vs_ema50'] = (df['EMA20'] - df['EMA50']) / df['EMA50'] * 100
    
    df['signal_strength'] = df.apply(calculate_signal_strength, axis=1)

    db = SessionLocal()
    
    # Fetch market stats
    fetch_market_stats(db)
    
    candles_saved = 0
    updated_candles = 0
    indicators_saved = 0
    
    oldest_date = None
    newest_date = None
    
    def get_val(val, type_fn=float):
        return type_fn(val) if pd.notna(val) else None
    
    for i in range(len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else df.iloc[i]
        
        timestamp = row['timestamp'].to_pydatetime()
        
        if oldest_date is None or timestamp < oldest_date:
            oldest_date = timestamp
        if newest_date is None or timestamp > newest_date:
            newest_date = timestamp
            
        c_open = get_val(row['Open'])
        c_high = get_val(row['High'])
        c_low = get_val(row['Low'])
        c_close = get_val(row['Close'])
        c_vol = get_val(row['Volume'])
        
        pc_1h = get_val(row['price_change_1h'])
        pc_4h = get_val(row['price_change_4h'])
        pc_24h = get_val(row['price_change_24h'])
        h_24h = get_val(row['high_24h'])
        l_24h = get_val(row['low_24h'])
        vc_24h = get_val(row['volume_change_24h'])
        volat = get_val(row['volatility'])
        c_body = get_val(row['candle_body'])
        is_bull = bool(row['is_bullish'])

        existing_candle = db.query(Candle).filter(Candle.symbol == 'BTCUSDT', Candle.timestamp == timestamp).first()
        if existing_candle:
            existing_candle.price_change_1h = pc_1h
            existing_candle.price_change_4h = pc_4h
            existing_candle.price_change_24h = pc_24h
            existing_candle.high_24h = h_24h
            existing_candle.low_24h = l_24h
            existing_candle.volume_change_24h = vc_24h
            existing_candle.volatility = volat
            existing_candle.candle_body = c_body
            existing_candle.is_bullish = is_bull
            updated_candles += 1
        else:
            candle = Candle(
                symbol='BTCUSDT', timestamp=timestamp,
                open=c_open, high=c_high, low=c_low, close=c_close, volume=c_vol,
                price_change_1h=pc_1h, price_change_4h=pc_4h, price_change_24h=pc_24h,
                high_24h=h_24h, low_24h=l_24h, volume_change_24h=vc_24h,
                volatility=volat, candle_body=c_body, is_bullish=is_bull
            )
            db.add(candle)
            candles_saved += 1
            
        # Indicators
        rsi_c = get_val(row['rsi_change'])
        p_ema20 = get_val(row['price_vs_ema20'])
        p_ema50 = get_val(row['price_vs_ema50'])
        e20_50 = get_val(row['ema20_vs_ema50'])
        macd_h = get_val(row['macd_histogram'])
        sig_str = get_val(row['signal_strength'], int)
        
        existing_indicators = db.query(Indicator).filter(Indicator.symbol == 'BTCUSDT', Indicator.timestamp == timestamp).all()
        if existing_indicators:
            for ind in existing_indicators:
                ind.rsi_change = rsi_c
                ind.price_vs_ema20 = p_ema20
                ind.price_vs_ema50 = p_ema50
                ind.ema20_vs_ema50 = e20_50
                ind.macd_histogram = macd_h
                ind.signal_strength = sig_str
        else:
            signal = calculate_signal(row, prev_row)
            signal_val = 1.0 if signal == "BUY" else (-1.0 if signal == "SELL" else 0.0)
            inds_to_save = [
                ('RSI', row['RSI']), ('MACD', row['MACD']),
                ('EMA20', row['EMA20']), ('EMA50', row['EMA50']), ('Signal', signal_val)
            ]
            for name, val in inds_to_save:
                if not pd.isna(val):
                    indicator = Indicator(
                        symbol='BTCUSDT', timestamp=timestamp, name=name, value=float(val),
                        rsi_change=rsi_c, price_vs_ema20=p_ema20, price_vs_ema50=p_ema50,
                        ema20_vs_ema50=e20_50, macd_histogram=macd_h, signal_strength=sig_str
                    )
                    db.add(indicator)
                    indicators_saved += 1
            
        if (i + 1) % 100 == 0:
            print(f"✅ Updated/Saved {i + 1}/1000 candles...")
            db.commit()
            
    db.commit()
    db.close()
    
    print("================================")
    print("✅ Data Collection Complete!")
    print("================================")
    print(f"📊 Candles added    : {candles_saved}")
    print(f"📊 Candles updated  : {updated_candles}")
    print(f"📈 Indicators saved : {indicators_saved}")
    print(f"📅 From : {oldest_date}")
    print(f"📅 To   : {newest_date}")
    print("================================")

if __name__ == '__main__':
    backfill_data()
