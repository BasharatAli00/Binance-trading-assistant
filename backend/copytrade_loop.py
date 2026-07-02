"""Strategy #4 main loop — `run_copytrade()` runs in its own daemon thread.

Every FAST_POLL_SEC it:
  1. manages exits on open positions (stop / TP / trail / time / mirror-sell),
  2. processes consensus buy signals into new sim entries,
and every WALLET_SYNC_MINUTES it re-syncs the watched wallet list + webhook.

Fully isolated: every tick is wrapped so a fault can't reach the other three
strategies. Trading is simulated. Incoming wallet events arrive out-of-band via
the Helius webhook receiver (copytrade_api) — this loop only reads them.
"""
import time
from datetime import datetime

import copytrade_config as cfg
import copytrade_engine as engine
import copytrade_signal as signal
import copytrade_helius as helius
import copytrade_strategy as strat
import sniper_data   # reused pure DexScreener price/liquidity fetch

status = {
    "running": False,
    "last_tick": None,
    "watched_wallets": 0,
    "open_positions": 0,
    "webhook_id": None,
}

_running = False
_last_wallet_sync = 0.0


def stop():
    global _running
    _running = False


# --------------------------------------------------------------------------
# Exits
# --------------------------------------------------------------------------
def _manage_exits():
    positions = engine.get_open_positions()
    status["open_positions"] = len(positions)
    if not positions:
        return
    marks = sniper_data.latest_marks([p["mint"] for p in positions])
    for pos in positions:
        m = marks.get(pos["mint"]) or {}
        price = m.get("price") or sniper_data.latest_price(pos["mint"])
        if not price:
            continue
        engine.update_position_mark(pos["id"], price)

        # Mirror-sell: have enough of the triggering wallets sold since entry?
        entry_time = pos.get("entry_time")
        sold = signal.sellers_since(pos["mint"], entry_time, pos.get("trigger_wallets") or [])
        for w in sold:
            engine.mark_wallet_exited(pos["id"], w)
        triggers = pos.get("trigger_wallets") or []
        smart_exit = bool(triggers) and (len(sold) / len(triggers)) >= cfg.SMART_EXIT_SELL_FRACTION

        pos["peak_price"] = max(pos.get("peak_price") or pos["entry_price"], price)
        pos["_hold_minutes"] = ((datetime.utcnow() - entry_time).total_seconds() / 60
                                if entry_time else 0.0)

        decision = strat.exit_decision(pos, price, smart_money_exiting=smart_exit)
        if not decision:
            continue
        if decision["action"] == "partial":
            res = engine.execute_partial_sell(pos, price, decision["fraction"], decision["reason"])
            if res:
                print(f"[copytrade] SCALE-OUT {pos['symbol'] or pos['mint'][:8]} "
                      f"pnl=${res['realized_pnl']:.2f}")
        else:
            res = engine.execute_sell(pos, price, decision["reason"])
            if res:
                print(f"[copytrade] EXIT {pos['symbol'] or pos['mint'][:8]} "
                      f"{decision['reason']} ret={res['return_pct']:.1f}% "
                      f"pnl=${res['realized_pnl']:.2f}")


# --------------------------------------------------------------------------
# Entries
# --------------------------------------------------------------------------
def _process_signals():
    p = engine.get_portfolio()
    if not p or not p["is_active"]:
        return
    if engine.circuit_breaker_tripped():
        return

    # --- 1) ADDS: another qualified wallet bought a coin we ALREADY hold ---
    for pos in engine.get_open_positions():
        credited = set(pos.get("trigger_wallets") or [])
        if len(credited) >= 1 + cfg.MAX_WALLET_ADDS:
            continue
        newcomers = signal.new_buyers_for(pos["mint"], pos.get("entry_time"), credited)
        if not newcomers:
            continue
        m = (sniper_data.latest_marks([pos["mint"]]) or {}).get(pos["mint"]) or {}
        price = m.get("price") or sniper_data.latest_price(pos["mint"])
        if not price:
            continue
        for w in sorted(newcomers):
            if len(credited) >= 1 + cfg.MAX_WALLET_ADDS:
                break
            res = engine.execute_add(pos["id"], price, cfg.ADD_USD, w)
            if res:
                credited.add(w)
                print(f"[copytrade] ADD {pos['symbol'] or pos['mint'][:8]} "
                      f"+${cfg.ADD_USD:.0f} ({w[:4]} agrees, now {res['wallets']} wallets)")

    # --- 2) NEW entries (tier 1): a single qualified wallet's buy ---
    candidates = signal.detect_consensus_buys()   # MIN_WALLETS=1 -> single-wallet mints
    open_now = len(engine.get_open_positions())
    slots = p["max_open_positions"] - open_now

    for c in candidates:
        mint = c["mint"]
        if engine.is_holding(mint):
            continue   # already held -> handled by the ADD path above
        if slots <= 0:
            signal.record_signal(c, "skipped", "no_slots")
            continue
        if engine.in_cooldown(mint):
            signal.record_signal(c, "skipped", "cooldown")
            continue

        mark = (sniper_data.latest_marks([mint]) or {}).get(mint) or {}
        price = mark.get("price")
        ok, reason = strat.passes_entry_gates(mark)
        if not ok:
            signal.record_signal(c, "skipped", reason)
            continue

        res = engine.execute_buy(mint, c.get("symbol") or (mint[:6] + "…"), price,
                                 c["wallets"], size_usd=cfg.TIER1_USD)
        if res:
            slots -= 1
            signal.record_signal(c, "entered", f"tier1_{c['wallet_count']}w")
            print(f"[copytrade] ENTRY {c.get('symbol') or mint[:8]} @ ${price:.8f} "
                  f"tier1 ${cfg.TIER1_USD:.0f} ({', '.join(w[:4] for w in c['wallets'])})")
        else:
            signal.record_signal(c, "skipped", "insufficient_cash")


# --------------------------------------------------------------------------
# Wallet + webhook sync
# --------------------------------------------------------------------------
def _sync_wallets():
    wallets = helius.sync_watched_wallets()
    status["watched_wallets"] = len(wallets)
    status["webhook_id"] = helius.ensure_webhook(wallets)


def _tick():
    global _last_wallet_sync
    now = time.time()
    if now - _last_wallet_sync >= cfg.WALLET_SYNC_MINUTES * 60:
        _sync_wallets()
        signal.prune_old_events()
        _last_wallet_sync = now
    _manage_exits()
    _process_signals()


def run_copytrade():
    global _running, _last_wallet_sync
    engine.ensure_initialized()
    _running = True
    status["running"] = True
    _last_wallet_sync = 0.0
    print(f"[copytrade] Strategy #4 (Smart-Money Copy Trade) loop started — simulated "
          f"(poll {cfg.FAST_POLL_SEC}s, consensus {cfg.MIN_WALLETS}+ wallets / "
          f"{cfg.CONSENSUS_WINDOW_MIN}min)")

    while _running:
        t0 = time.time()
        try:
            _tick()
        except Exception as e:
            import traceback
            print(f"[copytrade] tick error: {e}")
            traceback.print_exc()
        status["last_tick"] = datetime.utcnow().isoformat()
        end = time.time() + max(0, cfg.FAST_POLL_SEC - (time.time() - t0))
        while _running and time.time() < end:
            time.sleep(1)

    status["running"] = False
    print("[copytrade] loop stopped cleanly")
