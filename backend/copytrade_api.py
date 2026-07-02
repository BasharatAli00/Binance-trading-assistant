"""FastAPI routes for Strategy #4 (Smart-Money Copy Trade), at /api/copytrade.

Additive router — included from main.py. Read-only dashboard views + config/
reset controls + the Helius webhook receiver that ingests live wallet events.
Nothing here touches the other strategies.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from database import SessionLocal
from models import CopyWatchedWallet
import copytrade_config as cfg
import copytrade_engine as engine
import copytrade_signal as signal
import copytrade_helius as helius
import copytrade_loop

router = APIRouter(prefix="/api/copytrade", tags=["copytrade"])


@router.get("/status")
def status():
    return {
        "portfolio": engine.portfolio_summary() or {},
        "loop": copytrade_loop.status,
        "config": {
            "enabled": cfg.COPYTRADE_ENABLED,
            "has_helius_key": bool(cfg.HELIUS_API_KEY),
            "webhook_configured": bool(cfg.HELIUS_WEBHOOK_URL),
            "min_wallets": cfg.MIN_WALLETS,
            "consensus_window_min": cfg.CONSENSUS_WINDOW_MIN,
            "position_size": cfg.POSITION_SIZE_USD,
            "tier1_usd": cfg.TIER1_USD,
            "add_usd": cfg.ADD_USD,
            "max_adds": cfg.MAX_WALLET_ADDS,
            "live_enabled": cfg.LIVE_TRADING_ENABLED,
            "expected_wallet": cfg.LIVE_TRADING_WALLET,
            "live_max_trade_usd": cfg.LIVE_MAX_TRADE_USD,
        },
    }


@router.get("/live/status")
def live_status():
    """Read-only live-trading health check — wallet address, SOL balance,
    whether the master switch is on. NEVER trades."""
    import copytrade_live
    return copytrade_live.preflight()


@router.get("/positions")
def positions(status: str = "open", limit: int = 200):
    return engine.get_positions(status=status, limit=limit)


@router.get("/trades")
def trades(limit: int = 100):
    return engine.get_trades(limit=limit)


@router.get("/signals")
def signals(limit: int = 50):
    return engine.get_signals(limit=limit)


@router.get("/watched")
def watched():
    db = SessionLocal()
    try:
        rows = db.query(CopyWatchedWallet).order_by(CopyWatchedWallet.score.desc()).all()
        return [{"wallet": r.wallet, "window": r.source_window, "rank": r.rank,
                 "score": r.score} for r in rows]
    finally:
        db.close()


class ConfigUpdate(BaseModel):
    is_active: Optional[bool] = None
    position_size: Optional[float] = None
    max_open_positions: Optional[int] = None
    initial_balance: Optional[float] = None
    mode: Optional[str] = None          # 'sim' | 'live' (still needs the master switch)


@router.put("/config")
def update_config(body: ConfigUpdate):
    updated = engine.update_config({k: v for k, v in body.dict().items() if v is not None})
    return updated or JSONResponse(status_code=404, content={"error": "no portfolio"})


@router.post("/reset")
def reset():
    return engine.reset() or JSONResponse(status_code=404, content={"error": "no portfolio"})


@router.post("/sync")
def sync():
    """Manually re-sync the watched wallet list + Helius webhook."""
    wallets = helius.sync_watched_wallets()
    wid = helius.ensure_webhook(wallets)
    return {"watched": len(wallets), "webhook_id": wid}


@router.post("/helius")
async def helius_webhook(request: Request):
    """Receiver for Helius enhanced-transaction events.

    Verifies the shared secret (sent by Helius as the Authorization header),
    parses swaps by watched wallets into buy/sell events, and stores them for
    the consensus detector. Returns fast — the loop does the trading work.
    """
    if cfg.HELIUS_WEBHOOK_SECRET:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth != cfg.HELIUS_WEBHOOK_SECRET:
            return JSONResponse(status_code=401, content={"error": "bad auth"})
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid json"})

    watched = set(helius.get_watched_wallets())
    events = helius.parse_webhook_payload(payload, watched)
    inserted = signal.record_events(events) if events else 0
    return {"received": True, "events": inserted}
