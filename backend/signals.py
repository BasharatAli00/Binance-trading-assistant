import os
import pandas as pd
import ta
from dotenv import load_dotenv
from binance.client import Client

# Decision thresholds for the weighted score (range is roughly -6..+6)
BUY_THRESHOLD = 2
SELL_THRESHOLD = -2


def compute_signal(rsi, macd_hist, bullish_cross, bearish_cross, price, ema20, ema50):
    """Weighted multi-indicator score -> (signal, score, reason).

    Each indicator nudges a score up (bullish) or down (bearish). The final
    score is compared against the BUY/SELL thresholds. Returns a short
    human-readable reason describing the strongest contributors.
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

    if score >= BUY_THRESHOLD:
        signal = "BUY"
    elif score <= SELL_THRESHOLD:
        signal = "SELL"
    else:
        signal = "HOLD"

    reason = ", ".join(reasons[:3]) if reasons else "Neutral"
    return signal, score, reason


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

    signal, score, reason = compute_signal(
        rsi_val, macd_hist, bullish_cross, bearish_cross, current_price, ema20, ema50
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
        'reason': reason
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
