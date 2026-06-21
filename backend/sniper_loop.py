"""Strategy #3 main loop — `run_sniper()` runs in its own daemon thread.

Structurally identical to run_trader() (Strategy #1/#2): a 60-second tick that
discovers tokens, snapshots them, manages exits, and opens new positions per
portfolio. Fully isolated — every tick is wrapped so a fault can never reach the
other two strategies, and it shares no mutable state with them.
"""
import time
from datetime import datetime

import sniper_config as cfg
import sniper_data
import sniper_engine
import sniper_macro
from sniper_features import compute_features
from sniper_conviction import compute_conviction
from sniper_rug import compute_rug_risk
from sniper_strategy import passes_entry_gates, exit_decision

# Lightweight status for the UI header ("scanning every 60s").
status = {
    "running": False,
    "last_tick": None,
    "last_tick_seconds": 0.0,
    "tracked_tokens": 0,
    "candidates": 0,
}

_running = False
_last_watchlist = 0.0
_last_macro = 0.0


def stop():
    global _running
    _running = False


def _default_gate_portfolio():
    # Global gate defaults for candidate building (per-portfolio floors applied later).
    return {"min_buy_pressure": cfg.MIN_BUY_PRESSURE}


def _check_exits(portfolio, snapshots):
    for pos in sniper_engine.get_open_positions(portfolio["id"]):
        addr = pos["token_address"]
        snap = snapshots.get(addr)
        price = (snap or {}).get("price_usd") or sniper_data.latest_price(
            pos.get("entry_pair_address") or addr)
        if not price:
            continue
        sniper_engine.update_position_mark(pos["id"], price)
        entry_time = pos.get("entry_time")
        pos["_hold_minutes"] = ((datetime.utcnow() - entry_time).total_seconds() / 60
                                if entry_time else 0.0)
        # peak after marking
        pos["peak_price"] = max(pos.get("peak_price") or pos["entry_price"], price)
        reason = exit_decision(pos, price, portfolio)
        if reason:
            res = sniper_engine.execute_sell(pos, price, reason)
            if res:
                print(f"[sniper] EXIT {pos['symbol'] or addr[:8]} {reason} "
                      f"ret={res['return_pct']:.1f}% pnl=${res['realized_pnl']:.2f}")


def _build_candidates(features_map):
    """Tokens passing the hard gates, scored with conviction + rug risk."""
    gate_pf = _default_gate_portfolio()
    out = []
    for addr, feats in features_map.items():
        if not feats:
            continue
        ok, _ = passes_entry_gates(feats, gate_pf)
        if not ok:
            continue
        conviction = compute_conviction(feats)
        rug = compute_rug_risk(addr, feats)
        out.append((addr, feats, conviction, rug))
    out.sort(key=lambda x: (x[2], x[1].get("vol_acceleration_15m", 0)), reverse=True)
    return out


def _execute_entries(portfolio, candidates, snapshots, sym_map):
    pid = portfolio["id"]
    open_now = sniper_engine.get_open_positions(pid)
    slots = portfolio["max_open_positions"] - len(open_now)
    if slots <= 0:
        return
    floor = portfolio.get("conviction_floor", 20)
    rug_thresh = portfolio.get("rug_veto_threshold", cfg.RUG_RISK_VETO_THRESHOLD)
    executed = 0

    for addr, feats, conviction, rug in candidates:
        if executed >= slots:
            break
        if conviction < floor:
            continue
        if rug >= rug_thresh:
            continue
        if sniper_engine.is_holding(pid, addr):
            continue
        if sniper_engine.in_cooldown(addr):
            continue
        snap = snapshots.get(addr, {})
        price = snap.get("price_usd") or feats.get("price_usd") or 0
        if not price:
            continue
        res = sniper_engine.execute_buy(
            portfolio, addr, sym_map.get(addr) or (addr[:6] + "…"),
            price, conviction=conviction, rug=rug,
            dex_id=snap.get("dex_id", ""), pair_address=snap.get("pair_address", ""),
            source=feats.get("discovery_source", "watchlist"))
        if res:
            print(f"[sniper] ENTRY pf={portfolio['name']} {sym_map.get(addr) or addr[:8]} "
                  f"@ ${price:.8f} conv={conviction:.0f} rug={rug}")
            executed += 1


def _tick():
    global _last_watchlist, _last_macro
    now = time.time()

    # 1. Refresh watchlist every 5 min
    if now - _last_watchlist >= cfg.WATCHLIST_REFRESH_MIN * 60:
        print("[sniper] refreshing watchlist…")
        sniper_data.refresh_watchlist()
        _last_watchlist = now

    # 2. Active + held addresses
    active = sniper_data.get_active_addresses()
    sym_map = {a: s for a, s in active}
    active_addrs = [a for a, _ in active]
    held = set()
    portfolios = sniper_engine.get_portfolios()
    for pf in portfolios:
        for pos in sniper_engine.get_open_positions(pf["id"]):
            held.add(pos["token_address"])
    all_addrs = list(set(active_addrs) | held)
    status["tracked_tokens"] = len(all_addrs)

    # 3. Snapshots
    snapshots = sniper_data.fetch_snapshots(all_addrs) if all_addrs else {}

    # 4. Exits first (frees slots)
    for pf in portfolios:
        _check_exits(pf, snapshots)

    # 5. Macro every 15 min
    if now - _last_macro >= cfg.MACRO_REFRESH_SEC:
        sniper_macro.refresh_macro()
        _last_macro = now

    # 6. Features for active tokens
    features_map = {}
    for addr in active_addrs:
        if addr in snapshots:
            f = compute_features(addr)
            if f:
                f["symbol"] = sym_map.get(addr)
                features_map[addr] = f

    # 7. Candidates
    candidates = _build_candidates(features_map)
    status["candidates"] = len(candidates)

    # 8. Persist model scores for the UI
    sniper_engine_update_scores(candidates, features_map)

    # 9. Entries per active portfolio (respecting circuit breaker)
    for pf in portfolios:
        if not pf["is_active"]:
            continue
        cb = sniper_engine.circuit_breaker_state(pf["id"])
        if cb.get("tripped"):
            print(f"[sniper] circuit breaker tripped pf={pf['name']} — pausing")
            sniper_engine.update_config(pf["id"], {"is_active": False})
            continue
        _execute_entries(pf, candidates, snapshots, sym_map)

    # 10. Retention
    sniper_data.cleanup_old_snapshots()


def sniper_engine_update_scores(candidates, features_map):
    """Upsert per-token scores (conviction/rug/prob) for the watchlist UI."""
    from database import SessionLocal
    from models import SniperModelScore
    scored = {addr: (conv, rug) for addr, _f, conv, rug in candidates}
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        for addr, feats in features_map.items():
            conv, rug = scored.get(addr, (compute_conviction(feats), 0))
            row = db.query(SniperModelScore).filter(
                SniperModelScore.token_address == addr).first()
            if row:
                row.conviction_score = conv
                row.rug_risk_score = rug
                row.prob_win = conv / 100.0
                row.updated_at = now
            else:
                db.add(SniperModelScore(token_address=addr, conviction_score=conv,
                                        rug_risk_score=rug, prob_win=conv / 100.0,
                                        updated_at=now))
        db.commit()
    except Exception as e:
        print(f"[sniper] score upsert error: {e}")
    finally:
        db.close()


def run_sniper():
    global _running
    sniper_engine.ensure_initialized()
    sniper_macro.refresh_macro()
    _running = True
    status["running"] = True
    print("[sniper] Strategy #3 (Intelligent Sniper) loop started — simulated trading")

    while _running:
        t0 = time.time()
        try:
            _tick()
        except Exception as e:
            import traceback
            print(f"[sniper] tick error: {e}")
            traceback.print_exc()
        elapsed = time.time() - t0
        status["last_tick"] = datetime.utcnow().isoformat()
        status["last_tick_seconds"] = round(elapsed, 1)
        # Sleep the rest of the interval, 1s at a time so shutdown is responsive.
        remaining = max(0, cfg.POLL_INTERVAL_SEC - elapsed)
        end = time.time() + remaining
        while _running and time.time() < end:
            time.sleep(1)

    status["running"] = False
    print("[sniper] loop stopped cleanly")
