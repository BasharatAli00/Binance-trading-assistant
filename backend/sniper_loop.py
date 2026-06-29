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
import sniper_ml
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
_last_full_tick = 0.0
_last_retrain = 0.0
_retraining = False


def stop():
    global _running
    _running = False


def _maybe_retrain():
    """Kick off a background model retrain on schedule (non-blocking).

    Retrains every RETRAIN_INTERVAL_HOURS in its own thread so the trading loop
    keeps polling exits/entries while LightGBM fits. Skips if one is already
    running. The first retrain is seeded one interval out from startup so we
    don't train on boot.
    """
    global _last_retrain, _retraining
    if not cfg.AUTO_RETRAIN_ENABLED or _retraining:
        return
    now = time.time()
    if _last_retrain == 0.0:
        _last_retrain = now            # seed: first retrain one interval from now
        return
    if now - _last_retrain < cfg.RETRAIN_INTERVAL_HOURS * 3600:
        return
    _last_retrain = now

    def _run():
        global _retraining
        _retraining = True
        try:
            print("[sniper] scheduled retrain starting…")
            import sniper_ml_train
            meta = sniper_ml_train.train()   # saves + reloads the model on success
            if meta:
                print(f"[sniper] scheduled retrain done — val AUC={meta.get('val_auc'):.3f}, "
                      f"{meta.get('n_samples')} samples")
            else:
                print("[sniper] scheduled retrain skipped — not enough data")
        except Exception as e:
            print(f"[sniper] scheduled retrain error: {e}")
        finally:
            _retraining = False

    import threading
    threading.Thread(target=_run, daemon=True).start()


def _default_gate_portfolio():
    # Global gate defaults for candidate building (per-portfolio floors applied later).
    return {"min_buy_pressure": cfg.MIN_BUY_PRESSURE}


def _evaluate_exit(portfolio, pos, price, liquidity=None):
    """Mark a position and act on the exit decision (shared by fast + full pass).

    Handles the liquidity-drain hard guard, partial scale-outs, and full closes.
    """
    addr = pos["token_address"]
    sniper_engine.update_position_mark(pos["id"], price)
    entry_time = pos.get("entry_time")
    pos["_hold_minutes"] = ((datetime.utcnow() - entry_time).total_seconds() / 60
                            if entry_time else 0.0)
    pos["peak_price"] = max(pos.get("peak_price") or pos["entry_price"], price)

    # Hard liquidity-drain guard: pool being pulled -> exit NOW, don't wait for
    # the % stop (which fills catastrophically late in a rug).
    if liquidity is not None and liquidity < cfg.LIQ_HARD_FLOOR:
        res = sniper_engine.execute_sell(pos, price, "liq_drain")
        if res:
            print(f"[sniper] RUG-EXIT {pos['symbol'] or addr[:8]} liq=${liquidity:.0f} "
                  f"ret={res['return_pct']:.1f}% pnl=${res['realized_pnl']:.2f}")
        return

    decision = exit_decision(pos, price, portfolio)
    if not decision:
        return

    if decision["action"] == "partial":
        res = sniper_engine.execute_partial_sell(
            pos, price, decision["fraction"], decision["reason"])
        if res:
            print(f"[sniper] SCALE-OUT {pos['symbol'] or addr[:8]} "
                  f"sold {decision['fraction']*100:.0f}% pnl=${res['realized_pnl']:.2f} "
                  f"(runner left)")
    else:
        res = sniper_engine.execute_sell(pos, price, decision["reason"])
        if res:
            print(f"[sniper] EXIT {pos['symbol'] or addr[:8]} {decision['reason']} "
                  f"ret={res['return_pct']:.1f}% pnl=${res['realized_pnl']:.2f}")


def _check_exits(portfolio, snapshots):
    for pos in sniper_engine.get_open_positions(portfolio["id"]):
        addr = pos["token_address"]
        snap = snapshots.get(addr)
        price = (snap or {}).get("price_usd") or sniper_data.latest_price(
            pos.get("entry_pair_address") or addr)
        if not price:
            continue
        _evaluate_exit(portfolio, pos, price, liquidity=(snap or {}).get("liquidity_usd"))


def _fast_exit_pass():
    """Lightweight exit-only pass over OPEN positions across all portfolios.

    Runs every FAST_POLL_SEC between full ticks so stops/rugs are caught within
    seconds instead of up to a minute late — the single biggest source of the
    -25%/-90% stop fills in the trade history.
    """
    portfolios = sniper_engine.get_portfolios()
    held = {}   # addr -> list of (portfolio, pos)
    for pf in portfolios:
        for pos in sniper_engine.get_open_positions(pf["id"]):
            held.setdefault(pos["token_address"], []).append((pf, pos))
    if not held:
        return
    marks = sniper_data.latest_marks(list(held.keys()))
    for addr, items in held.items():
        m = marks.get(addr)
        price = (m or {}).get("price")
        if not price:
            continue
        for pf, pos in items:
            _evaluate_exit(pf, pos, price, liquidity=(m or {}).get("liquidity_usd"))


def _brain_score(feats):
    """The 'brain' — ML win-probability (0-100) when a model is trained, else the
    rule-based conviction score. Returned on a 0-100 scale so the existing
    conviction_floor and ranking keep working unchanged (floor 30 == prob 0.30)."""
    prob = sniper_ml.predict_prob(feats)
    if prob is not None:
        return round(prob * 100, 2)
    return compute_conviction(feats)


def _build_candidates(features_map):
    """Tokens passing the hard gates, scored by the brain (ML prob or rules) + rug."""
    gate_pf = _default_gate_portfolio()
    out = []
    for addr, feats in features_map.items():
        if not feats:
            continue
        ok, _ = passes_entry_gates(feats, gate_pf)
        if not ok:
            continue
        conviction = _brain_score(feats)
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
    # The breaker is a DYNAMIC gate: while the DAILY drawdown exceeds the limit we
    # skip new entries this tick, but we do NOT latch the wallet off. The drawdown
    # high-water mark resets at 00:00 UTC, so a tripped breaker clears at the next
    # day boundary even if no profitable trade closes in between. (Exits already
    # ran in step 4 regardless.) `is_active` is reserved for the user's manual
    # pause/resume only.
    for pf in portfolios:
        if not pf["is_active"]:
            continue
        cb = sniper_engine.circuit_breaker_state(pf["id"])
        if cb.get("tripped"):
            print(f"[sniper] circuit breaker gating entries pf={pf['name']} "
                  f"dd={cb.get('current_drawdown', 0):.1f}% (auto-resumes on recovery)")
            continue
        _execute_entries(pf, candidates, snapshots, sym_map)

    # 10. Retention
    sniper_data.cleanup_old_snapshots()

    # 11. Scheduled ML brain retrain (non-blocking; every RETRAIN_INTERVAL_HOURS)
    _maybe_retrain()


def sniper_engine_update_scores(candidates, features_map):
    """Upsert per-token scores (conviction/rug/prob) for the watchlist UI."""
    from database import SessionLocal
    from models import SniperModelScore
    scored = {addr: (conv, rug) for addr, _f, conv, rug in candidates}
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        for addr, feats in features_map.items():
            conv, rug = scored.get(addr, (_brain_score(feats), 0))
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
    global _running, _last_full_tick
    sniper_engine.ensure_initialized()
    sniper_macro.refresh_macro()
    _running = True
    status["running"] = True
    _last_full_tick = 0.0
    brain = "ML model (LightGBM)" if sniper_ml.is_ready() else "rule-based conviction (no model trained yet)"
    print("[sniper] Strategy #3 (Intelligent Sniper) loop started — simulated trading "
          f"(full tick {cfg.POLL_INTERVAL_SEC}s, fast exit poll {cfg.FAST_POLL_SEC}s) "
          f"| brain: {brain}")

    while _running:
        t0 = time.time()
        try:
            if t0 - _last_full_tick >= cfg.POLL_INTERVAL_SEC:
                # Full pass: discovery + features + exits + entries.
                _tick()
                _last_full_tick = t0
            else:
                # Between full ticks: only watch open positions for exits/rugs.
                _fast_exit_pass()
        except Exception as e:
            import traceback
            print(f"[sniper] tick error: {e}")
            traceback.print_exc()
        elapsed = time.time() - t0
        status["last_tick"] = datetime.utcnow().isoformat()
        status["last_tick_seconds"] = round(elapsed, 1)
        # Sleep the rest of the fast interval, 1s at a time for responsive shutdown.
        remaining = max(0, cfg.FAST_POLL_SEC - elapsed)
        end = time.time() + remaining
        while _running and time.time() < end:
            time.sleep(1)

    status["running"] = False
    print("[sniper] loop stopped cleanly")
