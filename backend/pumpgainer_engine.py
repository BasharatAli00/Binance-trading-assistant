"""Orchestration for the Top-Gainer finder.

One run, per window (24h == 1d, 7d):
  1. Fetch the top-trader leaderboard from Solana Tracker (eligibility floors
     applied server-side via query params).
  2. Apply local filters (net-positive, creator/bot exclusion) + our composite
     ranking score.
  3. Replace that window's leaderboard, append the audit stats, log the run.

Exposes fetch_and_store_top_gainers() for the scheduler (mirrors the other
fetch_and_store_* collectors), plus read helpers for the API.
"""
from datetime import datetime

import pumpgainer_config as cfg
import pumpgainer_client as client
import pumpgainer_score as scorer
from database import SessionLocal
from models import PumpWalletStats, PumpTopGainer, PumpRunHistory


# --------------------------------------------------------------------------
# Public entry point (scheduler + manual/API trigger)
# --------------------------------------------------------------------------
def fetch_and_store_top_gainers():
    """Run one refresh cycle across all windows. Never raises — provider
    failures are logged to run_history and swallowed so the scheduler keeps
    ticking; the next run retries normally."""
    if not cfg.SOLANATRACKER_API_KEY:
        print("[pump-gainer] SOLANATRACKER_API_KEY not set — skipping run")
        return

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        for window, days in cfg.WINDOWS.items():
            _run_window(db, window, days, now)
    finally:
        db.close()


def _run_window(db, window, days, now):
    try:
        records = client.fetch_leaderboard(days)
    except Exception as e:
        db.rollback()
        print(f"[pump-gainer] window {window} fetch failed: {e}")
        _log_run(db, window, now, 0, 0, 0, "failed", str(e))
        return

    try:
        all_rows, eligible = scorer.evaluate(records)
        _persist_wallet_stats(db, window, now, all_rows)
        _persist_leaderboard(db, window, now, eligible)
        _log_run(db, window, now, len(records), len(all_rows),
                 len(eligible), "success", None)
    except Exception as e:
        db.rollback()
        print(f"[pump-gainer] window {window} store failed: {e}")
        _log_run(db, window, now, len(records), 0, 0, "failed", str(e))


def _persist_wallet_stats(db, window, now, all_rows):
    for r in all_rows:
        db.add(PumpWalletStats(
            wallet_address=r["wallet_address"], window=window, run_timestamp=now,
            realized_pnl=r.get("realized_pnl"), roi_pct=r.get("roi_pct"),
            volume=r.get("volume"), round_trip_count=r.get("trades"),
            distinct_tokens=r.get("tokens_traded"), win_rate=r.get("win_rate"),
            passed_eligibility=r["passed_eligibility"],
            exclusion_reason=r["exclusion_reason"],
        ))
    db.commit()


def _persist_leaderboard(db, window, now, eligible):
    # Current-run only: replace the window's leaderboard atomically.
    db.query(PumpTopGainer).filter(PumpTopGainer.window == window).delete()
    for r in eligible:
        db.add(PumpTopGainer(
            window=window, rank=r["rank"], wallet_address=r["wallet_address"],
            score=r["score"], realized_pnl=r.get("realized_pnl"),
            roi_pct=r.get("roi_pct"), win_rate=r.get("win_rate"),
            round_trip_count=r.get("trades"), distinct_tokens=r.get("tokens_traded"),
            volume=r.get("volume"), last_updated=now,
        ))
    db.commit()


def _log_run(db, window, now, fetched, evaluated, passed, status, err):
    db.add(PumpRunHistory(
        run_timestamp=now, window=window, wallets_fetched=fetched,
        wallets_evaluated=evaluated, wallets_passed_eligibility=passed,
        status=status, error_message=err,
    ))
    db.commit()


# --------------------------------------------------------------------------
# Read helpers (for the API)
# --------------------------------------------------------------------------
def get_leaderboard(window, limit=200):
    db = SessionLocal()
    try:
        rows = db.query(PumpTopGainer).filter(
            PumpTopGainer.window == window
        ).order_by(PumpTopGainer.rank.asc()).limit(limit).all()
        return [{
            "rank": r.rank, "wallet_address": r.wallet_address,
            "score": r.score, "realized_pnl": r.realized_pnl,
            "roi_pct": r.roi_pct, "win_rate": r.win_rate,
            "round_trip_count": r.round_trip_count,
            "distinct_tokens": r.distinct_tokens, "volume": r.volume,
            "last_updated": r.last_updated.isoformat() if r.last_updated else None,
        } for r in rows]
    finally:
        db.close()


def get_recent_runs(limit=20):
    db = SessionLocal()
    try:
        rows = db.query(PumpRunHistory).order_by(
            PumpRunHistory.run_timestamp.desc()
        ).limit(limit).all()
        return [{
            "run_id": str(r.run_id),
            "run_timestamp": r.run_timestamp.isoformat() if r.run_timestamp else None,
            "window": r.window, "wallets_fetched": r.wallets_fetched,
            "wallets_evaluated": r.wallets_evaluated,
            "wallets_passed_eligibility": r.wallets_passed_eligibility,
            "status": r.status, "error_message": r.error_message,
        } for r in rows]
    finally:
        db.close()
