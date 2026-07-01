"""FastAPI routes for the Pump.fun Top-Gainer finder, mounted at /api/pump-gainers.

Additive router — included from main.py with a single app.include_router().
Read-only leaderboard views + a manual refresh trigger. Reads come straight
from storage (sub-second), never re-querying the provider live (acceptance §9).
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

import pumpgainer_config as cfg
import pumpgainer_engine as engine

router = APIRouter(prefix="/api/pump-gainers", tags=["pump-gainers"])


@router.get("")
def top_gainers(window: str = "24h", limit: int = 50):
    """Current ranked leaderboard for a window ('24h' or '7d')."""
    if window not in cfg.WINDOWS:
        return JSONResponse(status_code=400,
                            content={"error": f"window must be one of {list(cfg.WINDOWS)}"})
    limit = max(1, min(limit, cfg.LEADERBOARD_MAX_SIZE))
    return {"window": window, "wallets": engine.get_leaderboard(window, limit=limit)}


@router.get("/runs")
def runs(limit: int = 20):
    """Recent run-history audit rows (newest first)."""
    return engine.get_recent_runs(limit=limit)


@router.get("/config")
def config_view():
    """Effective eligibility/scoring config (so the UI can show the knobs)."""
    return {
        "enabled": cfg.PUMP_GAINER_ENABLED,
        "has_key": bool(cfg.SOLANATRACKER_API_KEY),
        "provider": "solana-tracker",
        "interval_minutes": cfg.INTERVAL_MINUTES,
        "windows": list(cfg.WINDOWS),
        "eligibility": cfg.ELIGIBILITY,
        "scoring": cfg.SCORING,
        "pnl_mode": cfg.PNL_MODE,
    }


@router.post("/refresh")
def refresh():
    """Manually trigger a refresh cycle (same work the scheduler does)."""
    if not cfg.SOLANATRACKER_API_KEY:
        return JSONResponse(status_code=400,
                            content={"error": "SOLANATRACKER_API_KEY is not configured"})
    engine.fetch_and_store_top_gainers()
    return {"status": "ok"}
