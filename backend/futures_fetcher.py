import requests
from datetime import datetime

from database import SessionLocal
from models import FuturesStats

# Binance Futures public data endpoints — no API key / signing required.
LONG_SHORT_URL = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
PREMIUM_INDEX_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"


def _funding_direction(funding_rate):
    """Positive funding => longs pay shorts; negative => shorts pay longs."""
    if funding_rate > 0:
        return "Longs pay"
    if funding_rate < 0:
        return "Shorts pay"
    return "Neutral"


def fetch_and_store_futures_stats(symbol="BTCUSDT"):
    """Fetch perpetual-futures long/short ratio + funding rate and store a snapshot.

    Both calls hit Binance Futures *public* endpoints (keyless). On any error
    we log and return without writing, so the scheduler/app never breaks.
    """
    try:
        # --- Long/short account ratio (latest 5m bucket) ---
        ls_resp = requests.get(
            LONG_SHORT_URL,
            params={"symbol": symbol, "period": "5m", "limit": 1},
            timeout=10,
        )
        ls_resp.raise_for_status()
        ls_data = ls_resp.json()
        if not ls_data:
            print(f"No long/short data returned for {symbol}.")
            return
        latest_ls = ls_data[0]
        long_pct = float(latest_ls["longAccount"]) * 100.0
        short_pct = float(latest_ls["shortAccount"]) * 100.0
        long_short_ratio = float(latest_ls["longShortRatio"])

        # --- Funding rate (current premium index) ---
        fr_resp = requests.get(PREMIUM_INDEX_URL, params={"symbol": symbol}, timeout=10)
        fr_resp.raise_for_status()
        fr_data = fr_resp.json()
        funding_rate = float(fr_data.get("lastFundingRate", 0.0))
        next_funding_time = None
        nft = fr_data.get("nextFundingTime")
        if nft:
            next_funding_time = datetime.utcfromtimestamp(int(nft) / 1000.0)

        db = SessionLocal()
        try:
            row = FuturesStats(
                symbol=symbol,
                timestamp=datetime.utcnow(),
                long_pct=long_pct,
                short_pct=short_pct,
                long_short_ratio=long_short_ratio,
                funding_rate=funding_rate,
                funding_direction=_funding_direction(funding_rate),
                next_funding_time=next_funding_time,
            )
            db.add(row)
            db.commit()
            print(
                f"[OK] Saved futures stats for {symbol} "
                f"(L/S {long_pct:.1f}/{short_pct:.1f}, funding {funding_rate * 100:.4f}%)"
            )
        finally:
            db.close()

    except Exception as e:
        print(f"Failed to fetch or store futures stats: {e}")


if __name__ == "__main__":
    fetch_and_store_futures_stats()
