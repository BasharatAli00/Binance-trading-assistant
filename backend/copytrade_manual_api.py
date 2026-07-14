"""FastAPI routes for the Strategy #4 Manual Trade desk, at /api/manual.

Additive router — included from main.py. Opens hand-placed Solana positions
(market or a pending MCap limit) with optional TP/SL, and reports the active
count for the "X/5 active" badge + the server-side 5-position cap. All swap
execution is delegated to copytrade_manual -> copytrade_live (Jupiter).

Note: these `/api/manual/*` paths are distinct from the older BTC manual desk's
`/api/manual-*` routes in main.py — different feature, no collision.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

import copytrade_manual as manual

router = APIRouter(prefix="/api/manual", tags=["manual"])


class ManualBuy(BaseModel):
    token_mint: str
    amount_usd: float
    buy_mcap: Optional[float] = None   # None = market buy "now"
    tp_mcap: Optional[float] = None    # None = no take-profit
    sl_mcap: Optional[float] = None    # None = no stop-loss
    auto_sell: bool = True


@router.post("/buy")
def buy(body: ManualBuy):
    """Open a manual position (market now, or a pending MCap limit buy)."""
    res = manual.create_manual_position(
        token_mint=body.token_mint,
        amount_usd=body.amount_usd,
        buy_mcap=body.buy_mcap,
        tp_mcap=body.tp_mcap,
        sl_mcap=body.sl_mcap,
        auto_sell=body.auto_sell,
    )
    if res.get("error"):
        return JSONResponse(status_code=400, content={"success": False, "error": res["error"]})
    return res


@router.get("/status")
def status():
    """Active manual-position count + cap (single source of truth for the badge)."""
    return manual.status()


@router.get("/token")
def token(mint: str):
    """Live symbol + price + market cap for a mint (for the form's live MCap + TP/SL checks)."""
    return manual.token_info(mint)


@router.get("/positions")
def positions(status: str = "active", limit: int = 100):
    """Manual positions: status = 'active' (pending+open), 'open', 'closed', or ''."""
    return manual.get_positions(status_filter=status, limit=limit)


@router.post("/positions/{position_id}/sell")
def sell(position_id: str):
    """Close one manual position at market (sell if open, cancel if still pending)."""
    res = manual.manual_sell(position_id)
    if not res.get("ok"):
        return JSONResponse(status_code=400, content=res)
    return res


class TargetUpdate(BaseModel):
    tp_mcap: Optional[float] = None   # None = clear take-profit
    sl_mcap: Optional[float] = None   # None = clear stop-loss


@router.post("/positions/{position_id}/targets")
def edit_targets(position_id: str, body: TargetUpdate):
    """Edit TP/SL (in MCap) of an open manual position. None clears a target."""
    res = manual.update_targets(position_id, tp_mcap=body.tp_mcap, sl_mcap=body.sl_mcap)
    if not res.get("ok"):
        return JSONResponse(status_code=400, content=res)
    return res
