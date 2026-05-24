import os
import pandas as pd
import ta
from dotenv import load_dotenv
from binance.client import Client

def get_signal(client):
    try:
        klines = client.get_klines(symbol='BTCUSDT', interval=Client.KLINE_INTERVAL_1HOUR, limit=100)
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
    
    macd_bullish_cross = prev['MACD'] <= prev['MACD_Signal'] and latest['MACD'] > latest['MACD_Signal']
    macd_bearish_cross = prev['MACD'] >= prev['MACD_Signal'] and latest['MACD'] < latest['MACD_Signal']
    
    signal = "HOLD"
    if rsi_val < 35 and macd_bullish_cross and current_price > ema20:
        signal = "BUY"
    elif rsi_val > 65 and macd_bearish_cross and current_price < ema20:
        signal = "SELL"
        
    return {
        'price': current_price,
        'rsi': rsi_val,
        'macd': macd_val,
        'macd_signal': macd_signal,
        'ema20': ema20,
        'ema50': ema50,
        'signal': signal
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
    data = get_signal(client)
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
