"""Strategy #4 main loop — `run_copytrade()` runs in its own daemon thread.

Every FAST_POLL_SEC it, for BOTH the Sim and Live wallets:
  1. manages exits on open positions (stop / TP / trail / time / mirror-sell),
  2. processes tiered entries/adds from the shared smart-money signals,
and every WALLET_SYNC_MINUTES re-syncs the watched wallet list + webhook.

Signal DETECTION is shared (one set of wallet events); the entry/exit DECISIONS
are per-portfolio (own positions, slots, cooldowns, sizes). The Live wallet
routes through copytrade_live (Jupiter, dry-run/real); Sim fills on paper.
Fully isolated: every tick is wrapped so a fault can't reach other strategies.
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
# Exits — across all portfolios (execute_sell routes live vs sim per position)
# --------------------------------------------------------------------------
def _manage_exits(portfolios):
    positions = []
    for pf in portfolios:
        positions.extend(engine.get_open_positions(pf["id"]))
    status["open_positions"] = len(positions)
    if not positions:
        return
    marks = sniper_data.latest_marks(list({p["mint"] for p in positions}))
    for pos in positions:
        m = marks.get(pos["mint"]) or {}
        price = m.get("price") or sniper_data.latest_price(pos["mint"])
        if not price:
            continue
        engine.update_position_mark(pos["id"], price)

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
# Entries + adds — per portfolio
# --------------------------------------------------------------------------
def _process_portfolio(pf, candidates):
    pid = pf["id"]
    if not pf["is_active"] or engine.circuit_breaker_tripped(pid):
        return
    live = pf["mode"] == "live"
    tier1_usd, add_usd = cfg.tier_sizes(pf)
    min_liq = cfg.LIVE_MIN_LIQUIDITY_USD if live else cfg.MIN_LIQUIDITY_USD

    # 1) ADDS: another qualified wallet bought a coin this wallet already holds.
    for pos in engine.get_open_positions(pid):
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
            if engine.execute_add(pos["id"], price, add_usd, w):
                credited.add(w)
                print(f"[copytrade:{pf['mode']}] ADD {pos['symbol'] or pos['mint'][:8]} "
                      f"+${add_usd:.0f} ({w[:4]} agrees)")

    # 2) NEW entries (tier 1): a single qualified wallet's buy on an un-held coin.
    open_now = len(engine.get_open_positions(pid))
    slots = pf["max_open_positions"] - open_now
    for c in candidates:
        mint = c["mint"]
        if engine.is_holding(pid, mint):
            continue
        if slots <= 0:
            signal.record_signal(c, "skipped", "no_slots")
            continue
        if engine.in_cooldown(pid, mint):
            signal.record_signal(c, "skipped", "cooldown")
            continue
        mark = (sniper_data.latest_marks([mint]) or {}).get(mint) or {}
        ok, reason = strat.passes_entry_gates(mark, min_liquidity=min_liq)
        if not ok:
            signal.record_signal(c, "skipped", reason)
            continue
        res = engine.execute_buy(pid, mint, c.get("symbol") or (mint[:6] + "…"),
                                 mark.get("price"), c["wallets"], size_usd=tier1_usd)
        if res and res.get("skipped"):
            signal.record_signal(c, "skipped", res["skipped"])
        elif res:
            slots -= 1
            signal.record_signal(c, "entered", f"{pf['mode']}_tier1_{c['wallet_count']}w")
            print(f"[copytrade:{pf['mode']}] ENTRY {c.get('symbol') or mint[:8]} "
                  f"@ ${mark.get('price'):.8f} tier1 ${tier1_usd:.0f}")
        else:
            signal.record_signal(c, "skipped", "insufficient_cash")


def _process_signals():
    portfolios = engine.get_portfolios()
    candidates = signal.detect_consensus_buys()   # shared detection (MIN_WALLETS)
    for pf in portfolios:
        _process_portfolio(pf, candidates)
    return portfolios


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
    portfolios = engine.get_portfolios()
    _manage_exits(portfolios)
    _process_signals()


def run_copytrade():
    global _running, _last_wallet_sync
    engine.ensure_initialized()
    _running = True
    status["running"] = True
    _last_wallet_sync = 0.0
    live_state = ("OFF (sim only)" if not cfg.LIVE_TRADING_ENABLED
                  else ("DRY-RUN" if cfg.LIVE_DRYRUN else "REAL MONEY"))
    print(f"[copytrade] Strategy #4 loop started — Sim + Live wallets | "
          f"live: {live_state} | poll {cfg.FAST_POLL_SEC}s")

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
