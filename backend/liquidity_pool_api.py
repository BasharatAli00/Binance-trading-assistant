"""FastAPI Router for Liquidity Pool and Sweep Visualization (/api/liquidity).

Exposes 5m candles, resampled 1h candles, 1h liquidity pools, 5m liquidity pools,
and liquidity sweep markers for Commander VRAX on Robinhood Chain (or any configured token/pool).
"""
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from liquidity_provider import (
    GeckoTerminalProvider,
    DEFAULT_TOKEN_ADDRESS,
    DEFAULT_POOL_ADDRESS,
    DEFAULT_NETWORK,
)
from liquidity_detector import run_full_liquidity_detection

router = APIRouter(prefix="/api/liquidity", tags=["liquidity"])
provider = GeckoTerminalProvider()


@router.get("")
def get_liquidity_data(
    token_address: Optional[str] = Query(None, description="Token contract address (defaults to env TOKEN_ADDRESS)"),
    pool_address: Optional[str] = Query(None, description="Uniswap v4 Pool address (defaults to highest liquidity pool)"),
    network: Optional[str] = Query(None, description="Network / chain ID (defaults to 'robinhood')"),
    timeframe: str = Query("5m", description="Primary candle timeframe"),
    limit: int = Query(1000, ge=50, le=2000, description="Number of candles to fetch"),
    swing_n: int = Query(3, ge=1, le=10, description="Fractal swing bar count n"),
    tol_mult: float = Query(0.25, ge=0.01, le=2.0, description="Equal-level ATR tolerance multiplier"),
    max_pools: int = Query(30, ge=1, le=100, description="Max liquidity pools to return per timeframe"),
):
    """Fetch 5m candles, calculate 1h resampled candles, and detect liquidity pools and sweeps."""
    net = (network.strip().lower() if isinstance(network, str) and network.strip() else DEFAULT_NETWORK)
    tok_addr = (token_address.strip().lower() if isinstance(token_address, str) and token_address.strip() else DEFAULT_TOKEN_ADDRESS)
    p_addr = (pool_address.strip().lower() if isinstance(pool_address, str) and pool_address.strip() else DEFAULT_POOL_ADDRESS)
    tf = timeframe if isinstance(timeframe, str) else "5m"
    lim = limit if isinstance(limit, int) else 1000
    sn = swing_n if isinstance(swing_n, int) else 3
    tm = float(tol_mult) if isinstance(tol_mult, (int, float)) else 0.25
    mp = max_pools if isinstance(max_pools, int) else 30

    # If pool address is not specified, auto-resolve top liquidity pool for token
    pool_info = None
    if p_addr:
        pool_info = provider.get_pool_info(net, p_addr)
    else:
        pool_info = provider.resolve_top_pool(net, tok_addr)
        if pool_info and pool_info.get("address"):
            p_addr = pool_info["address"].lower()

    if not p_addr:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"No pool found for token {tok_addr} on network {net}.",
                "token_address": tok_addr,
                "network": net,
            },
        )

    # If pool_info was not fetched yet
    if not pool_info:
        pool_info = provider.get_pool_info(net, p_addr)

    # Fetch 5m candles from provider
    raw_candles = provider.get_candles(net, p_addr, timeframe=tf, limit=lim)

    if not raw_candles:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"No candle history found for pool {p_addr}.",
                "token_address": tok_addr,
                "pool_address": p_addr,
                "network": net,
            },
        )

    # Run detection pure functions
    detection_result = run_full_liquidity_detection(
        raw_candles,
        swing_n=sn,
        tol_mult=tm,
        max_pools=mp,
    )

    history_start = detection_result["meta"]["history_start"]
    history_end = detection_result["meta"]["history_end"]
    history_hours = round((history_end - history_start) / 3600.0, 1) if (history_start and history_end) else 0.0
    history_days = round(history_hours / 24.0, 1)

    response_payload = {
        "token": {
            "address": tok_addr,
            "symbol": "VRAX",
            "name": "Commander VRAX",
        },
        "pool": {
            "address": p_addr,
            "name": pool_info.get("name", "VRAX Pool"),
            "liquidity_usd": pool_info.get("liquidity_usd", 0.0),
            "volume_24h": pool_info.get("volume_24h", 0.0),
            "price_usd": pool_info.get("price_usd", 0.0),
            "network": net,
        },
        "candles": detection_result["candles_5m"],
        "candles_1h": detection_result["candles_1h"],
        "pools_1h": detection_result["pools_1h"],
        "pools_5m": detection_result["pools_5m"],
        "sweeps": detection_result["sweeps"],
        "meta": {
            "history_start": history_start,
            "history_end": history_end,
            "history_hours": history_hours,
            "history_days": history_days,
            "history_summary": f"{history_days}d ({history_hours}h)" if history_days >= 1.0 else f"{history_hours} hours",
            "candle_count": detection_result["meta"]["candle_count_5m"],
            "candle_count_1h": detection_result["meta"]["candle_count_1h"],
            "params": {
                "swing_n": sn,
                "tol_mult": tm,
                "max_pools": mp,
                "timeframe": tf,
                "limit": lim,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    return response_payload
