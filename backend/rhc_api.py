"""Read-only API for the Robinhood Chain system: /api/rhc/*

Protected by the app's global JWT middleware (path does not start with
/api/liquidity). Every endpoint works when RHC is disabled and reports why.
"""
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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


@router.get("/watchlist")
def watchlist(state: Optional[str] = None, limit: int = Query(200, ge=1, le=1000)):
    """Discovered pools with state (candidate | watch | rejected | expired), discovery reasons and codes."""
    if state is not None and state not in ("candidate", "watch", "rejected", "expired"):
        return JSONResponse(status_code=400, content={"error": "invalid state"})
    st, err = _store_or_503()
    return err or _safe(lambda: st.watchlist(state, limit))


@router.get("/screens")
def screens(pool_id: Optional[str] = None, verdict: Optional[str] = None, limit: int = Query(50, ge=1, le=500)):
    """Screening history with full evidence. verdict = pass | reject."""
    if verdict is not None and verdict not in ("pass", "reject"):
        return JSONResponse(status_code=400, content={"error": "verdict must be pass or reject"})
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        pk = None
        if pool_id:
            pk = st.pool_pk(pool_id)
            if pk is None:
                return JSONResponse(status_code=404, content={"error": "unknown pool"})
        return st.screens(pk, verdict, limit)
    return _safe(_q)


@router.get("/reasons")
def reasons():
    """Catalog of every screening reason code (category, default severity, description)."""
    from rhc_reasons import REASONS, severity
    return [{"code": r.code, "category": r.category, "severity": severity(r.code, cfg.RHC_SEVERITY_OVERRIDES),
             "permanent": r.permanent, "description": r.description} for r in REASONS.values()]


@router.get("/decisions")
def decisions(pool_id: Optional[str] = None, action: Optional[str] = None, limit: int = Query(100, ge=1, le=1000)):
    """Signals and decisions with evidence. action: SETUP_DETECTED | NOT_CONFIRMED | EXPIRED |
    REJECTED_RISK | ENTER_INTENT. Phase 3 records intents only; nothing is executed."""
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        pk = st.pool_pk(pool_id) if pool_id else None
        if pool_id and pk is None:
            return JSONResponse(status_code=404, content={"error": "unknown pool"})
        return st.decisions(pk, action, limit)
    return _safe(_q)


@router.get("/features")
def pool_features(pool_id: str):
    """Point-in-time features for a pool, computed now from stored closed candles."""
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        import time as _t
        from rhc_features import features
        pk = st.pool_pk(pool_id)
        if pk is None:
            return JSONResponse(status_code=404, content={"error": "unknown pool"})
        as_of = ((int(_t.time()) - cfg.RHC_CANDLE_GRACE_S) // 60) * 60
        return {"pool_id": pool_id.lower(), "features": features(st.candles(pk, 60, limit=cfg.RHC_FEATURE_LOOKBACK_MIN),
                                                                 as_of)}
    return _safe(_q)


@router.get("/regime")
def current_regime():
    """Market regime and active no-trade conditions (as last computed by the decision engine)."""
    out = rhc_service.status()
    return {"regime": out.get("regime"), "decisions": out.get("decisions")}


@router.get("/wallets/top")
def top_wallets(limit: int = Query(50, ge=1, le=500)):
    """Wallets ranked by realized outcomes on watch-listed pools (positions closed before now)."""
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        import time as _t
        from rhc_wallets import scores
        now = int(_t.time())
        sc = scores(st.wallet_positions_since(now - cfg.RHC_RETAIN_WALLET_POS_DAYS * 86400), now, cfg)
        ranked = sorted(sc.items(), key=lambda kv: (kv[1]["smart"], kv[1]["score"], kv[1]["n"]), reverse=True)
        return [{"wallet": w, **v} for w, v in ranked[:limit]]
    return _safe(_q)


@router.get("/research/smart-money")
def smart_money_research():
    """Does buying by 'smart' wallets predict the next hour's return? Time-split, out-of-sample half
    only; says 'insufficient sample' until enough data exists. No conclusions are drawn early."""
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        import time as _t
        from rhc_wallets import evaluate, scores, smart_flow
        now = int(_t.time())
        closed = st.wallet_positions_since(now - cfg.RHC_RETAIN_WALLET_POS_DAYS * 86400)
        trades = st.wallet_trades_since(now - cfg.RHC_RETAIN_WALLET_TRADE_DAYS * 86400)
        samples = []
        for pk in sorted({t["pool_pk"] for t in trades}):
            closes = dict(st.pool_closes(pk, 60, now - cfg.RHC_RETAIN_WALLET_TRADE_DAYS * 86400))
            pool_trades = [t for t in trades if t["pool_pk"] == pk]
            for t0 in range((min(closes) // 900 + 1) * 900 if closes else now, now - 3600, 900):
                p0 = closes.get(t0 - 60)
                p1 = closes.get(t0 + 3540)
                if not p0 or not p1:
                    continue
                usd, _ = smart_flow(pool_trades, scores(closed, t0, cfg), pk, t0)
                samples.append((t0, usd, p1 / p0 - 1.0))
        return evaluate(samples, cfg)
    return _safe(_q)


@router.get("/kill-switch")
def kill_switch_status():
    st, err = _store_or_503()
    if err:
        return err
    return _safe(lambda: {"db": st.kv_get("kill_switch") or {"enabled": False}, "env": cfg.RHC_KILL_SWITCH})


class KillSwitchBody(BaseModel):
    enabled: bool
    reason: Optional[str] = None


@router.post("/kill-switch")
def set_kill_switch(body: KillSwitchBody):
    """Global kill switch: when enabled, the decision engine blocks every new entry."""
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        import time as _t
        val = {"enabled": bool(body.enabled), "reason": (body.reason or "")[:200], "ts": int(_t.time())}
        st.kv_set("kill_switch", val)
        return val
    return _safe(_q)


@router.get("/gaps")
def gaps(limit: int = Query(100, ge=1, le=1000)):
    st, err = _store_or_503()
    return err or _safe(lambda: st.list_gaps(limit))
