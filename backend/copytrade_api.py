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
import copytrade_quicknode as quicknode
import copytrade_event_merge as merge
import copytrade_loop

router = APIRouter(prefix="/api/copytrade", tags=["copytrade"])


@router.get("/status")
def status():
    portfolios = [s for s in (engine.portfolio_summary(p["id"]) for p in engine.get_portfolios()) if s]
    return {
        "portfolios": portfolios,
        "loop": copytrade_loop.status,
        "config": {
            "enabled": cfg.COPYTRADE_ENABLED,
            "has_helius_key": bool(cfg.HELIUS_API_KEY),
            "webhook_configured": bool(cfg.HELIUS_WEBHOOK_URL),
            "min_wallets": cfg.MIN_WALLETS,
            "consensus_window_min": cfg.CONSENSUS_WINDOW_MIN,
            "tier1_usd": cfg.TIER1_USD, "add_usd": cfg.ADD_USD, "max_adds": cfg.MAX_WALLET_ADDS,
            "live_tier1_usd": cfg.LIVE_POSITION_USD, "live_add_usd": cfg.LIVE_ADD_USD,
            "live_enabled": cfg.LIVE_TRADING_ENABLED, "live_dry_run": cfg.LIVE_DRYRUN,
            "expected_wallet": cfg.LIVE_TRADING_WALLET,
            "live_max_trade_usd": cfg.LIVE_MAX_TRADE_USD,
            "live_max_impact_pct": cfg.LIVE_MAX_PRICE_IMPACT_PCT,
        },
    }


@router.get("/live/status")
def live_status():
    """Read-only live-trading health check — wallet address, SOL balance,
    runway, dry-run/master state. NEVER trades."""
    import copytrade_live
    return copytrade_live.preflight()


@router.get("/positions")
def positions(portfolio_id: int, status: str = "open", limit: int = 200):
    return engine.get_positions(portfolio_id, status=status, limit=limit)


@router.post("/positions/{position_id}/sell")
def sell_position(position_id: str):
    """Manually close one open position at market (user clicked Sell)."""
    res = engine.manual_sell(position_id)
    if not res.get("ok"):
        return JSONResponse(status_code=400, content=res)
    return res


@router.get("/trades")
def trades(portfolio_id: int, limit: int = 100):
    return engine.get_trades(portfolio_id, limit=limit)


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
    portfolio_id: int
    is_active: Optional[bool] = None
    position_size: Optional[float] = None
    max_open_positions: Optional[int] = None
    initial_balance: Optional[float] = None


@router.put("/config")
def update_config(body: ConfigUpdate):
    fields = {k: v for k, v in body.dict().items() if v is not None and k != "portfolio_id"}
    updated = engine.update_config(body.portfolio_id, fields)
    return updated or JSONResponse(status_code=404, content={"error": "no portfolio"})


@router.post("/reset")
def reset(portfolio_id: int):
    return engine.reset(portfolio_id) or JSONResponse(status_code=404, content={"error": "no portfolio"})


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

    # Safely log the raw webhook payload
    try:
        from database import SessionLocal
        from models import CopyWebhookRaw
        import json
        from datetime import datetime
        
        # Helius payloads are usually lists of transactions
        event_type = "UNKNOWN"
        if isinstance(payload, list) and len(payload) > 0:
            event_type = payload[0].get("type", "UNKNOWN")
        elif isinstance(payload, dict):
            event_type = payload.get("type", "UNKNOWN")
            
        db = SessionLocal()
        try:
            db.add(CopyWebhookRaw(
                received_at=datetime.utcnow(),
                event_type=event_type,
                payload=json.dumps(payload)
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[copytrade] Failed to log raw webhook: {e}")

    watched = set(helius.get_watched_wallets())
    events = helius.parse_webhook_payload(payload, watched)
    inserted = 0
    if events:
        for e in events:
            inserted += merge.process_event("helius", e)
    return {"received": True, "events": inserted}


@router.post("/quicknode")
async def quicknode_webhook(request: Request):
    """Receiver for QuickNode Stream events."""
    if not cfg.ENABLE_QUICKNODE_FEED:
        return JSONResponse(status_code=403, content={"error": "quicknode disabled"})

    # Optional auth validation if QuickNode provides signature headers
    # (To be implemented when API is known)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid json"})

    # Safely log the raw webhook payload
    try:
        from database import SessionLocal
        from models import CopyWebhookRaw
        import json
        from datetime import datetime
        
        db = SessionLocal()
        try:
            db.add(CopyWebhookRaw(
                received_at=datetime.utcnow(),
                event_type="quicknode_stream",
                payload=json.dumps(payload)
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[copytrade] Failed to log raw quicknode webhook: {e}")

    watched = set(helius.get_watched_wallets())
    events = quicknode.parse_webhook_payload(payload, watched)
    inserted = 0
    if events:
        for e in events:
            inserted += merge.process_event("quicknode", e)
    return {"received": True, "events": inserted}
