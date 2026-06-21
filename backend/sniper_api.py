"""FastAPI routes for Strategy #3 (Intelligent Sniper), mounted at /api/sniper.

Additive router — included from main.py with a single app.include_router() call.
Read-only views for the dashboard plus config/reset mutations. Nothing here
touches Strategy #1 / #2 routes.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from database import SessionLocal
from models import SniperToken, SniperModelScore
import sniper_engine
import sniper_loop

router = APIRouter(prefix="/api/sniper", tags=["sniper"])


@router.get("/status")
def sniper_status():
    """All portfolios' summaries + loop heartbeat (drives the header + tabs)."""
    portfolios = sniper_engine.get_portfolios()
    summaries = [sniper_engine.portfolio_summary(p["id"]) for p in portfolios]
    return {"portfolios": [s for s in summaries if s], "loop": sniper_loop.status}


@router.get("/portfolio/{portfolio_id}")
def sniper_portfolio(portfolio_id: int):
    return sniper_engine.portfolio_summary(portfolio_id) or {}


@router.get("/positions")
def sniper_positions(portfolio_id: int, status: str = "open", limit: int = 200):
    return sniper_engine.get_positions(portfolio_id, status=status, limit=limit)


@router.get("/trades")
def sniper_trades(portfolio_id: int, limit: int = 100):
    return sniper_engine.get_trades(portfolio_id, limit=limit)


@router.get("/chart-pnl")
def sniper_chart_pnl(portfolio_id: int):
    return sniper_engine.chart_pnl(portfolio_id)


@router.get("/watchlist")
def sniper_watchlist(limit: int = 100):
    """Active tokens joined with their latest conviction/rug scores."""
    db = SessionLocal()
    try:
        tokens = db.query(SniperToken).filter(SniperToken.is_active == True).all()
        scores = {s.token_address: s for s in db.query(SniperModelScore).all()}
        rows = []
        for t in tokens:
            s = scores.get(t.token_address)
            rows.append({
                "token_address": t.token_address,
                "symbol": t.symbol,
                "name": t.name,
                "logo_url": t.logo_url,
                "dex_id": t.dex_id,
                "liquidity_usd": t.liquidity_usd,
                "volume_h1": t.volume_h1,
                "price_usd": t.price_usd,
                "market_cap": t.market_cap,
                "discovery_source": t.discovery_source,
                "has_socials": t.has_socials,
                "boost_count": t.boost_count,
                "rank_score": t.rank_score,
                "conviction_score": s.conviction_score if s else None,
                "rug_risk_score": s.rug_risk_score if s else None,
                "prob_win": s.prob_win if s else None,
            })
        rows.sort(key=lambda r: (r["conviction_score"] is not None, r["conviction_score"] or 0),
                  reverse=True)
        return rows[:limit]
    finally:
        db.close()


class ConfigUpdate(BaseModel):
    is_active: Optional[bool] = None
    position_size: Optional[float] = None
    max_open_positions: Optional[int] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    time_exit_minutes: Optional[int] = None
    trail_start_pct: Optional[float] = None
    trail_start_distance: Optional[float] = None
    trail_end_pct: Optional[float] = None
    trail_end_distance: Optional[float] = None
    conviction_floor: Optional[int] = None
    min_buy_pressure: Optional[float] = None
    rug_veto_threshold: Optional[int] = None
    cb_enabled: Optional[bool] = None
    cb_max_drawdown: Optional[float] = None


@router.put("/config/{portfolio_id}")
def sniper_update_config(portfolio_id: int, body: ConfigUpdate):
    fields = {k: v for k, v in body.dict().items() if v is not None}
    updated = sniper_engine.update_config(portfolio_id, fields)
    return {"ok": updated is not None, "config": updated}


@router.post("/toggle/{portfolio_id}")
def sniper_toggle(portfolio_id: int):
    """Pause/resume trading for a portfolio (the Overview button)."""
    summary = sniper_engine.portfolio_summary(portfolio_id)
    if not summary:
        return {"ok": False}
    new_state = not summary["is_active"]
    sniper_engine.update_config(portfolio_id, {"is_active": new_state})
    return {"ok": True, "is_active": new_state}


@router.post("/reset/{portfolio_id}")
def sniper_reset(portfolio_id: int):
    return sniper_engine.reset_portfolio(portfolio_id) or {"ok": False}
