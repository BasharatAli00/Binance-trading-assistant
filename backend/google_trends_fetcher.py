"""Google Trends search-interest for "Bitcoin" (via pytrends).

Fetches weekly search interest for the past 3 months, takes the latest week
and compares it to the previous week to get a week-over-week % change.

Google Trends is unofficial and rate-limits aggressively, so this:
  * caches for 24h (skips the network if the last stored row is < 24h old),
  * retries with exponential backoff on rate-limit / transient errors,
  * never raises into the rest of the system.

Runs in a background thread (scheduled daily + once at startup). Every fetch
attempt is logged with a timestamp + status, matching the other fetchers.
"""
import time
from datetime import datetime, timedelta

from pytrends.request import TrendReq

from database import SessionLocal, engine
from models import GoogleTrend

_KEYWORD = "Bitcoin"
_TIMEFRAME = "today 3-m"   # ~3 months, weekly granularity
_CACHE_HOURS = 24
_MAX_RETRIES = 3
_BACKOFF_BASE = 2          # seconds: 2, 4, 8 ...


def _log(msg):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[GoogleTrends][{now}] {msg}")


def _fetch_interest():
    """One pytrends fetch -> the weekly interest Series for the keyword."""
    pytrends = TrendReq(hl="en-US", tz=0)
    pytrends.build_payload([_KEYWORD], timeframe=_TIMEFRAME)
    df = pytrends.interest_over_time()
    if df is None or df.empty or _KEYWORD not in df.columns:
        raise ValueError("Empty interest_over_time response")
    series = df[_KEYWORD]
    # Drop the trailing partial week if Google flags it as not-yet-complete.
    if "isPartial" in df.columns and bool(df["isPartial"].iloc[-1]):
        series = series.iloc[:-1]
    if len(series) < 2:
        raise ValueError("Not enough weekly data points")
    return series


def fetch_and_store_trends():
    """Fetch Google Trends interest for "Bitcoin", compute WoW change, store it.

    No-ops (without raising) if a fresh row already exists within the 24h cache
    window, or if every retry fails, so the system is unaffected by failures.
    """
    GoogleTrend.__table__.create(bind=engine, checkfirst=True)

    db = SessionLocal()
    try:
        # 24h cache guard.
        latest = db.query(GoogleTrend).filter(
            GoogleTrend.keyword == _KEYWORD
        ).order_by(GoogleTrend.timestamp.desc()).first()
        if latest and latest.timestamp > datetime.utcnow() - timedelta(hours=_CACHE_HOURS):
            _log("Cached value < 24h old - skipping network fetch.")
            return

        series = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                _log(f"fetch attempt {attempt}/{_MAX_RETRIES} for '{_KEYWORD}'...")
                series = _fetch_interest()
                break
            except Exception as e:
                wait = _BACKOFF_BASE ** attempt
                _log(f"attempt {attempt} failed: {e}")
                if attempt < _MAX_RETRIES:
                    _log(f"backing off {wait}s before retry...")
                    time.sleep(wait)

        if series is None:
            _log("all attempts failed - keeping previous value.")
            return

        current = float(series.iloc[-1])
        prev = float(series.iloc[-2])
        wow = ((current - prev) / prev * 100.0) if prev > 0 else 0.0

        row = GoogleTrend(
            keyword=_KEYWORD,
            timestamp=datetime.utcnow(),
            trend_score=current,
            prev_score=prev,
            wow_change_pct=wow,
        )
        db.add(row)
        db.commit()
        _log(f"Stored: score={current:.0f}, prev={prev:.0f}, WoW={wow:+.1f}%")
    except Exception as e:
        _log(f"unexpected error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    fetch_and_store_trends()
