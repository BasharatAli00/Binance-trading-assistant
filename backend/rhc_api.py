"""Read-only API for the Robinhood Chain system: /api/rhc/*

Protected by the app's global JWT middleware (path does not start with
/api/liquidity). Every endpoint works when RHC is disabled and reports why.
"""
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

import rhc_config as cfg
import rhc_service

router = APIRouter(prefix="/api/rhc", tags=["robinhood-chain"])


def _store_or_503():
    if not cfg.RHC_DATABASE_URL:
        return None, JSONResponse(status_code=503, content={"error": "RHC database not configured",
                                                            "mode": cfg.RHC_MODE, "live_trading": "disabled"})
    st = rhc_service.store()
    if st is None:
        from rhc_store import Store
        st = Store()
    return st, None


def _safe(fn):
    try:
        return fn()
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": f"{type(e).__name__}: {str(e)[:200]}"})


@router.get("/health")
def health():
    """Service, indexer, RPC, data-source and storage health. PAPER mode; live trading disabled."""
    out = rhc_service.status()
    st, _ = _store_or_503()
    if st is not None and out["service"].get("status") == "running":
        try:
            out["counts"] = st.counts()
        except Exception as e:
            out["counts_error"] = str(e)[:200]
    return out


@router.get("/pools/tracked")
def tracked_pools(limit: int = Query(100, ge=1, le=500)):
    st, err = _store_or_503()
    return err or _safe(lambda: st.tracked_pools(limit))


@router.get("/candles")
def candles(pool_id: str, tf: int = Query(60), limit: int = Query(500, ge=1, le=2000),
            before: Optional[int] = None):
    if tf not in (60, 300, 900):
        return JSONResponse(status_code=400, content={"error": "tf must be 60, 300 or 900"})
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        pk = st.pool_pk(pool_id)
        if pk is None:
            return JSONResponse(status_code=404, content={"error": "unknown pool"})
        return {"pool_id": pool_id.lower(), "pool_pk": pk, "tf": tf, "candles": st.candles(pk, tf, limit, before)}
    return _safe(_q)


@router.get("/snapshots")
def snapshots(pool_id: str, limit: int = Query(100, ge=1, le=1000)):
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        pk = st.pool_pk(pool_id)
        if pk is None:
            return JSONResponse(status_code=404, content={"error": "unknown pool"})
        return st.snapshots(pk, limit)
    return _safe(_q)


@router.get("/gaps")
def gaps(limit: int = Query(100, ge=1, le=1000)):
    st, err = _store_or_503()
    return err or _safe(lambda: st.list_gaps(limit))
