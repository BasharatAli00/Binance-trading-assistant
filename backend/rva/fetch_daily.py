"""Fetch long-history BTC/USDT DAILY candles (since 2017) and cache them.

Daily is the natural timeframe for a regime/trend allocator: it captures the
same trend edge with far less noise and fee drag than 1h, and going back to
2017 lets us test across real bull AND bear cycles (2018, 2021, 2022, 2023-25).
"""
import os
import sys
import pandas as pd

CACHE = os.path.join(os.path.dirname(__file__), "_btc_1d_cache.csv")


def fetch():
    from binance.client import Client
    client = Client(requests_params={"timeout": 60})
    print("Fetching BTCUSDT 1d klines since 2017-08-01 ...")
    kl = client.get_historical_klines("BTCUSDT", Client.KLINE_INTERVAL_1DAY, "1 Aug, 2017")
    df = pd.DataFrame(kl, columns=["Open time", "Open", "High", "Low", "Close", "Volume",
                                   "Close time", "qav", "trades", "tbbav", "tbqav", "ignore"])
    df["timestamp"] = pd.to_datetime(df["Open time"], unit="ms")
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        df[c] = pd.to_numeric(df[c])
    df = df[["timestamp", "Open", "High", "Low", "Close", "Volume"]]
    df.to_csv(CACHE, index=False)
    print(f"Cached {len(df)} daily candles: {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}")
    return df


if __name__ == "__main__":
    fetch()
