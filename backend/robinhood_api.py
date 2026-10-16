"""FastAPI router for the isolated Robinhood Chain Trading Desk (/api/robinhood).

Completely isolated from /api/manual (Solana) and /api/copytrade.
Now supports direct price targets (buy_price, tp_price, sl_price) with backward
compatibility for market-cap targets.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

import robinhood_manual as manual

router = APIRouter(prefix="/api/robinhood", tags=["robinhood"])


class RobinhoodBuyRequest(BaseModel):
    token_address: str
    amount_usd: float
    buy_price: Optional[float] = None
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    buy_mcap: Optional[float] = None
    tp_mcap: Optional[float] = None
    sl_mcap: Optional[float] = None
    auto_sell: bool = True
    scale_in_enabled: bool = False
    tier1_pct: Optional[float] = 5.0
    tier1_add_usd: Optional[float] = 0.5
    tier2_pct: Optional[float] = 10.0
    tier2_add_usd: Optional[float] = 1.0


@router.post("/buy")
def buy(body: RobinhoodBuyRequest):
    """Open a Robinhood Chain position (Market Now or Limit Buy)."""
    res = manual.create_position(
        token_address=body.token_address,
        amount_usd=body.amount_usd,
        buy_price=body.buy_price,
        tp_price=body.tp_price,
        sl_price=body.sl_price,
        buy_mcap=body.buy_mcap,
        tp_mcap=body.tp_mcap,
        sl_mcap=body.sl_mcap,
        auto_sell=body.auto_sell,
        scale_in_enabled=body.scale_in_enabled,
        tier1_pct=body.tier1_pct,
        tier1_add_usd=body.tier1_add_usd,
        tier2_pct=body.tier2_pct,
        tier2_add_usd=body.tier2_add_usd,
    )
    if res.get("error"):
        return JSONResponse(status_code=400, content={"success": False, "error": res["error"]})
    return res


@router.get("/status")
def status():
    """Returns active position count, max positions limit, mode, and desk stats."""
    return manual.status()


@router.get("/stats")
def stats():
    """Returns aggregate performance stats: total trades, win rate, total P&L."""
    return manual.get_desk_stats()


@router.get("/token")
def token(address: str):
    """Fetches live symbol, price, and market cap for a given EVM token address."""
    return manual.token_info(address)


@router.get("/positions")
def positions(status: str = "active", limit: int = 100):
    """Returns positions filtered by status ('active', 'open', 'closed')."""
    return manual.get_positions(status_filter=status, limit=limit)


@router.post("/positions/{position_id}/sell")
def sell(position_id: str):
    """Closes an open position at market price or cancels a pending limit order."""
    res = manual.manual_sell(position_id)
    if not res.get("ok"):
        return JSONResponse(status_code=400, content=res)
    return res


class TargetUpdateRequest(BaseModel):
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_mcap: Optional[float] = None
    sl_mcap: Optional[float] = None


@router.post("/positions/{position_id}/targets")
def edit_targets(position_id: str, body: TargetUpdateRequest):
    """Edits TP/SL targets for an open position."""
    res = manual.update_targets(
        position_id,
        tp_price=body.tp_price,
        sl_price=body.sl_price,
        tp_mcap=body.tp_mcap,
        sl_mcap=body.sl_mcap,
    )
    if not res.get("ok"):
        return JSONResponse(status_code=400, content=res)
    return res
