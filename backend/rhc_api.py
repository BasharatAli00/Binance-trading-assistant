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


@router.get("/paper/positions")
def paper_positions(status: Optional[str] = None, limit: int = Query(200, ge=1, le=1000)):
    """Paper positions (open | closed | stuck). Simulated fills on live chain state; no real funds."""
    if status is not None and status not in ("open", "closed", "stuck"):
        return JSONResponse(status_code=400, content={"error": "invalid status"})
    st, err = _store_or_503()
    return err or _safe(lambda: st.paper_positions(status, limit))


@router.get("/paper/fills")
def paper_fills(position_id: Optional[int] = None, limit: int = Query(200, ge=1, le=1000)):
    st, err = _store_or_503()
    return err or _safe(lambda: st.paper_fills(position_id, limit))


@router.get("/performance")
def performance():
    """Forward paper-trading metrics with CIs, by strategy and regime. Reports 'insufficient sample'
    until the gate (trades / tokens / days) is met; never labels a strategy profitable below it."""
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        from rhc_metrics import breakdown, compute
        trades = st.closed_paper_trades()
        eq = cfg.RHC_PAPER_EQUITY_USD
        return {"mode": "paper", "overall": compute(trades, eq, cfg),
                "by_strategy": breakdown(trades, "strategy", eq, cfg), "by_regime": breakdown(trades, "regime", eq, cfg)}
    return _safe(_q)


def _backtest_inputs(st, days):
    import time as _t
    from sqlalchemy import text as _text
    import rhc_db
    now = int(_t.time())
    start = now - int(days * 86400)
    with rhc_db.get_engine().connect() as c:
        pools = dict(c.execute(_text(
            "select w.pool_pk, w.token from rhc_watchlist w join rhc_pool p on p.id = w.pool_pk "
            "where w.screens > 0 and w.token not in :majors"), {"majors": tuple(cfg.RHC_ETH_QUOTES + cfg.RHC_STABLE_QUOTES)}
        ).fetchall())
        rows = c.execute(_text(
            "select pool_pk, bucket, o, h, l, c, c_usd, vol_usd, buys, sells, buy_usd, sell_usd, traders, large, liq, "
            "liq_usd from rhc_candle where tf = 60 and bucket >= :b and pool_pk = any(:pks) order by pool_pk, bucket"),
            {"b": start - 7200, "pks": list(pools)}).mappings().all()
        ref_pk = c.execute(_text("select id from rhc_pool where pool_id = :p"), {"p": cfg.RHC_ETH_USD_REF_POOL}).scalar()
    by_pool = {}
    for r in rows:
        by_pool.setdefault(r["pool_pk"], []).append(dict(r))
    costs = {}
    for pk in pools:
        for scr in st.screens(pk, None, 5):
            sim = (scr.get("evidence") or {}).get("simulation") or {}
            if sim.get("round_trip_cost") is not None:
                costs[pk] = {"round_trip_cost": sim.get("round_trip_cost"), "impact": sim.get("impact")}
                break
    mv = st.market_volume_5m(start - 30 * 3600)
    eth = st.pool_closes(ref_pk, 300, start - 4 * 3600) if ref_pk else []
    # The window starts where the data starts (+1 h feature warm-up), so "days" reflects real coverage.
    first = min((cs[0]["bucket"] for cs in by_pool.values() if cs), default=now)
    start = max(start, first + 3600)
    return pools, by_pool, mv, eth, costs, start, now


@router.get("/backtest")
def backtest(days: float = Query(1.0, gt=0, le=30)):
    """Event-driven backtest + walk-forward over recorded candles of screened pools (candle-based fills;
    historical pool state is not available). Results are stored in rhc_backtest_run."""
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        import rhc_backtest
        pools, by_pool, mv, eth, costs, start, now = _backtest_inputs(st, min(days, cfg.RHC_BT_MAX_DAYS))
        pools = {pk: tok for pk, tok in pools.items() if len(by_pool.get(pk, [])) >= 30}
        trades, decisions = rhc_backtest.run(pools, by_pool, mv, eth, start, now, cfg, costs)
        summary = rhc_backtest.summarize(trades, decisions, start, now, cfg)
        summary["pools"] = len(pools)
        summary["run_id"] = st.insert_backtest_run(now, start, now, summary["config_hash"], summary)
        return summary
    return _safe(_q)


@router.get("/go-live-gate")
def go_live_gate():
    """Checklist required before real execution may even be considered. Live trading stays
    hard-disabled in code regardless of the result."""
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        import rhc_backtest
        from rhc_gate import evaluate
        from rhc_metrics import compute
        paper = compute(st.closed_paper_trades(), cfg.RHC_PAPER_EQUITY_USD, cfg)
        pools, by_pool, mv, eth, costs, start, now = _backtest_inputs(st, cfg.RHC_BT_MAX_DAYS)
        pools = {pk: tok for pk, tok in pools.items() if len(by_pool.get(pk, [])) >= 30}
        trades, _ = rhc_backtest.run(pools, by_pool, mv, eth, start, now, cfg, costs)
        holdout = rhc_backtest.walk_forward(trades, start, now, cfg)["holdout"]
        return dict(evaluate(paper, holdout, cfg, st.kv_get("go_live_manual") or {}), live_trading="disabled")
    return _safe(_q)


@router.get("/risk")
def risk_monitor():
    """Paper-account risk state: exposure, today's P&L vs the daily loss limit, open positions vs cap,
    kill switch and active no-trade conditions."""
    st, err = _store_or_503()
    if err:
        return err

    def _q():
        import time as _t
        now = int(_t.time())
        open_pos = st.paper_positions("open", 500)
        exposure, unreal = 0.0, 0.0
        for p in open_pos:
            held_cost = (p["cost_usd"] or 0.0) - (p["proceeds_usd"] or 0.0)
            exposure += held_cost
            last = st.last_close_usd(p["pool_pk"])
            if last and p.get("tokens"):
                unreal += p["tokens"] * last - held_cost
        realized_today = st.paper_realized_since(now - now % 86400)
        equity = cfg.RHC_PAPER_EQUITY_USD + st.paper_realized_since(0)
        kill = st.kv_get("kill_switch") or {"enabled": False}
        reg = (rhc_service.status().get("regime") or {})
        return {
            "mode": cfg.RHC_MODE, "live_trading": "disabled", "equity_usd": equity,
            "open_positions": len(open_pos), "max_open": cfg.RHC_MAX_OPEN,
            "exposure_usd": exposure, "max_exposure_usd": cfg.RHC_MAX_EXPOSURE_PCT * equity,
            "realized_today_usd": realized_today, "unrealized_usd": unreal,
            "daily_pnl_usd": realized_today + unreal, "daily_loss_limit_usd": -cfg.RHC_MAX_DAILY_LOSS_PCT * equity,
            "daily_limit_hit": (realized_today + unreal) <= -cfg.RHC_MAX_DAILY_LOSS_PCT * equity,
            "kill_switch": {"db": kill, "env": cfg.RHC_KILL_SWITCH},
            "no_trade": reg.get("no_trade", []), "regime": reg.get("label"),
        }
    return _safe(_q)


@router.get("/settings")
def effective_settings():
    """Effective non-secret thresholds (screening, strategies, risk, paper fill model)."""
    keys = ["RHC_SCREEN_TRADE_USD", "RHC_MIN_LIQ_USD", "RHC_MAX_BUY_TAX", "RHC_MAX_SELL_TAX", "RHC_MAX_ROUNDTRIP_COST",
            "RHC_MAX_IMPACT", "RHC_MAX_TOP10_PCT", "RHC_MIN_POOL_AGE_MIN", "RHC_PAPER_EQUITY_USD", "RHC_RISK_PCT",
            "RHC_MIN_POSITION_USD", "RHC_MAX_POSITION_USD", "RHC_MAX_OPEN", "RHC_MAX_EXPOSURE_PCT",
            "RHC_MAX_PER_TOKEN_USD", "RHC_MAX_DAILY_LOSS_PCT", "RHC_TOKEN_COOLDOWN_MIN", "RHC_STOP_MIN_PCT",
            "RHC_STOP_MAX_PCT", "RHC_TARGET_R", "RHC_TIME_STOP_MIN", "RHC_MAX_CHASE", "RHC_PAPER_LATENCY_S",
            "RHC_PAPER_EXTRA_SLIP_BPS", "RHC_PAPER_FAIL_PROB", "RHC_MIN_TRADES_FOR_STATS", "RHC_MIN_TOKENS_FOR_STATS",
            "RHC_MIN_DAYS_FOR_STATS", "RHC_STRAT_BREAKOUT_ENABLED", "RHC_STRAT_MOMENTUM_ENABLED",
            "RHC_STRAT_VOLEXP_ENABLED", "RHC_STRAT_LIQ_ENABLED", "RHC_STRAT_SMART_ENABLED"]
    return {k: getattr(cfg, k) for k in keys} | {"mode": cfg.RHC_MODE, "live_trading": "disabled"}


@router.get("/gaps")
def gaps(limit: int = Query(100, ge=1, le=1000)):
    st, err = _store_or_503()
    return err or _safe(lambda: st.list_gaps(limit))
