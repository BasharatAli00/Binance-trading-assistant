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
from datetime import datetime, timedelta

import copytrade_config as cfg
import copytrade_engine as engine
import copytrade_signal as signal
import copytrade_helius as helius
import copytrade_quicknode as quicknode
import copytrade_event_merge as merge
import copytrade_strategy as strat
import copytrade_safety as safety   # live-only Bouncer + Seatbelt (Sim is exempt)
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

# --------------------------------------------------------------------------
# Pending-retry queue for live buys that failed with 'jupiter_route_failed'
# Each entry: {mint, symbol, price_at_signal, wallets, size_usd, portfolio_id,
#              first_tried_at, next_retry_at}
# --------------------------------------------------------------------------
_pending_live: list = []
LIVE_RETRY_INTERVAL_SEC = 30          # retry every 30 seconds
LIVE_RETRY_MAX_MINUTES = 20           # give up after 20 minutes
LIVE_RETRY_MAX_PRICE_MULT = 3.0       # abort if price > 3x signal price


def stop():
    global _running
    _running = False


# --------------------------------------------------------------------------
# Exits — across all portfolios (execute_sell routes live vs sim per position)
# --------------------------------------------------------------------------
def _manage_exits(portfolios):
    positions = []
    pf_modes = {}
    for pf in portfolios:
        positions.extend(engine.get_open_positions(pf["id"]))
        pf_modes[pf["id"]] = pf["mode"]
    status["open_positions"] = len(positions)
    if not positions:
        return
    marks = sniper_data.latest_marks(list({p["mint"] for p in positions}))
    for pos in positions:
        m = marks.get(pos["mint"]) or {}
        price = m.get("price") or sniper_data.latest_price(pos["mint"])
        if not price:
            continue
        cur_liq = m.get("liquidity_usd") or 0
        engine.update_position_mark(pos["id"], price, liquidity=cur_liq)

        is_live = pf_modes.get(pos["portfolio_id"]) == "live"

        # ── Fire Alarm (live-only): a rug drains the pool faster than the -20%
        # price stop can react, so if pool liquidity has collapsed from its peak
        # we bail NOW, ahead of every other exit rule. Only ever sells, so a
        # false trigger just exits early — cheap insurance against a wipeout.
        if is_live and cfg.LIVE_LIQ_ALARM_ENABLED and cur_liq > 0:
            peak_liq = max(pos.get("peak_liquidity") or 0, cur_liq)
            if peak_liq >= cfg.LIVE_LIQ_ALARM_MIN_USD:
                drop_pct = (1 - cur_liq / peak_liq) * 100.0
                if drop_pct >= cfg.LIVE_LIQ_ALARM_DROP_PCT:
                    res = engine.execute_sell(pos, price, "liquidity_drop")
                    if res:
                        print(f"[copytrade:live] LIQUIDITY-DROP EXIT "
                              f"{pos['symbol'] or pos['mint'][:8]} pool ${cur_liq:,.0f} "
                              f"(-{drop_pct:.0f}% from ${peak_liq:,.0f}) "
                              f"ret={res['return_pct']:.1f}% pnl=${res['realized_pnl']:.2f}")
                    continue   # position closed — skip the rest of the exit logic

        entry_time = pos.get("entry_time")
        sold = signal.sellers_since(pos["mint"], entry_time, pos.get("trigger_wallets") or [])
        for w in sold:
            engine.mark_wallet_exited(pos["id"], w)
        triggers = pos.get("trigger_wallets") or []
        smart_exit = bool(triggers) and (len(sold) / len(triggers)) >= cfg.SMART_EXIT_SELL_FRACTION

        pos["peak_price"] = max(pos.get("peak_price") or pos["entry_price"], price)
        pos["_hold_minutes"] = ((datetime.utcnow() - entry_time).total_seconds() / 60
                                if entry_time else 0.0)

        # Do not mirror smart money exits for LIVE portfolios to avoid slippage/dumping
        # Sim portfolios still mirror them for theoretical tracking
        if is_live:
            smart_exit = False

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
    max_liq = cfg.LIVE_MAX_LIQUIDITY_USD if live else cfg.MAX_LIQUIDITY_USD

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
        # QuickNode live-trading gate (Stage 2)
        if live and not cfg.QUICKNODE_LIVE_ENABLED:
            sources = set(c.get("sources", ["helius"]))
            if sources == {"quicknode"}:
                continue  # Skip QuickNode-exclusive signals for live wallet
                
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
        ok, reason = strat.passes_entry_gates(mark, min_liquidity=min_liq, max_liquidity=max_liq)
        if not ok:
            signal.record_signal(c, "skipped", reason)
            continue
        # LIVE-ONLY safety gate (Bouncer + Seatbelt). Sim is intentionally exempt
        # so it stays a clean control on the old criteria.
        if live:
            safe, sreason = safety.passes_live_entry(pid, mint, pf, tier1_usd)
            if not safe:
                signal.record_signal(c, "skipped", sreason)
                print(f"[copytrade:live] SAFETY-SKIP {c.get('symbol') or mint[:8]} — {sreason}")
                continue
        res = engine.execute_buy(pid, mint, c.get("symbol") or (mint[:6] + "…"),
                                 mark.get("price"), c["wallets"], size_usd=tier1_usd)
        if res and res.get("skipped") in ("jupiter_route_failed", "jupiter_tx_build_failed") and live:
            # Jupiter doesn't know this token yet — queue for patient retry
            now = datetime.utcnow()
            already_queued = any(p["mint"] == mint and p["portfolio_id"] == pid
                                 for p in _pending_live)
            if not already_queued:
                _pending_live.append({
                    "mint": mint, "symbol": c.get("symbol") or (mint[:6] + "…"),
                    "price_at_signal": mark.get("price") or 0,
                    "wallets": c["wallets"], "size_usd": tier1_usd,
                    "portfolio_id": pid,
                    "first_tried_at": now,
                    "next_retry_at": now + timedelta(seconds=LIVE_RETRY_INTERVAL_SEC),
                })
                print(f"[copytrade:live] QUEUED {mint[:8]} — Jupiter route missing, "
                      f"will retry every {LIVE_RETRY_INTERVAL_SEC}s for up to {LIVE_RETRY_MAX_MINUTES}m")
                signal.record_signal(c, "skipped", "jupiter_route_failed_retrying")
        elif res and res.get("skipped"):
            signal.record_signal(c, "skipped", res["skipped"])
        elif res:
            slots -= 1
            signal.record_signal(c, "entered", f"{pf['mode']}_tier1_{c['wallet_count']}w")
            print(f"[copytrade:{pf['mode']}] ENTRY {c.get('symbol') or mint[:8]} "
                  f"@ ${mark.get('price'):.8f} tier1 ${tier1_usd:.0f}")
        else:
            signal.record_signal(c, "skipped", "insufficient_cash")


def _flush_pending_live():
    """Retry queued live buys that failed with jupiter_route_failed.
    Aborts if the token has pumped too far or the retry window has expired."""
    if not _pending_live:
        return
    now = datetime.utcnow()
    to_remove = []
    for item in _pending_live:
        if now < item["next_retry_at"]:
            continue   # not time yet
        mint = item["mint"]
        pid = item["portfolio_id"]
        age_min = (now - item["first_tried_at"]).total_seconds() / 60

        # Expired: give up
        if age_min >= LIVE_RETRY_MAX_MINUTES:
            print(f"[copytrade:live] RETRY EXPIRED {mint[:8]} after {age_min:.0f}m — canceling")
            to_remove.append(item)
            continue

        # Already bought by another path?
        if engine.is_holding(pid, mint):
            to_remove.append(item)
            continue

        # Price guard: if token has pumped too far, cancel
        mark = (sniper_data.latest_marks([mint]) or {}).get(mint) or {}
        current_price = mark.get("price") or 0
        signal_price = item["price_at_signal"] or 0
        if signal_price and current_price and current_price > signal_price * LIVE_RETRY_MAX_PRICE_MULT:
            print(f"[copytrade:live] RETRY ABORTED {mint[:8]} — price pumped "
                  f"{current_price/signal_price:.1f}x from signal, too late to enter safely")
            to_remove.append(item)
            continue

        # Try Jupiter again
        print(f"[copytrade:live] RETRYING {mint[:8]} (attempt #{int(age_min*60/LIVE_RETRY_INTERVAL_SEC)+1})")
        pf_list = [p for p in engine.get_portfolios() if p["id"] == pid]
        if not pf_list:
            to_remove.append(item)
            continue
        pf = pf_list[0]
        res = engine.execute_buy(pid, mint, item["symbol"],
                                 current_price or signal_price, item["wallets"],
                                 size_usd=item["size_usd"])
        if res and res.get("skipped") == "jupiter_route_failed":
            # Still no route — schedule next retry
            item["next_retry_at"] = now + timedelta(seconds=LIVE_RETRY_INTERVAL_SEC)
        elif res and res.get("skipped"):
            print(f"[copytrade:live] RETRY SKIPPED {mint[:8]}: {res['skipped']}")
            to_remove.append(item)
        elif res:
            print(f"[copytrade:live] RETRY SUCCESS {mint[:8]} — entered live position!")
            to_remove.append(item)
        else:
            to_remove.append(item)

    for item in to_remove:
        if item in _pending_live:
            _pending_live.remove(item)


def _process_signals():
    portfolios = engine.get_portfolios()
    candidates = signal.detect_consensus_buys()   # shared detection (MIN_WALLETS)
    for pf in portfolios:
        _process_portfolio(pf, candidates)
    _flush_pending_live()
    return portfolios


# --------------------------------------------------------------------------
# Wallet + webhook sync
# --------------------------------------------------------------------------
def _sync_wallets():
    wallets = helius.sync_watched_wallets()
    status["watched_wallets"] = len(wallets)
    status["webhook_id"] = helius.ensure_webhook(wallets)
    
    if cfg.ENABLE_QUICKNODE_FEED:
        quicknode.ensure_webhook(wallets)
    else:
        quicknode.delete_webhook()


def _tick():
    global _last_wallet_sync, _last_wallet_filter
    now = time.time()
    
    # Run the Wallet Filter every 24 hours
    if now - _last_wallet_filter >= 24 * 3600:
        try:
            import wallet_filter
            wallet_filter.analyze_wallets()
        except Exception as e:
            print(f"[copytrade] Wallet filter error: {e}")
        _last_wallet_filter = now

    if now - _last_wallet_sync >= cfg.WALLET_SYNC_MINUTES * 60:
        _sync_wallets()
        signal.prune_old_events()
        _last_wallet_sync = now
        
    merge.check_heartbeats()
    
    portfolios = engine.get_portfolios()
    _manage_exits(portfolios)
    _process_signals()

    # Manual Trade desk (Solana): fill pending MCap limit buys + auto-exit TP/SL.
    # Guarded so a manual-desk error can never kill the copy-trade loop.
    try:
        import copytrade_manual
        copytrade_manual.monitor()
    except Exception as e:
        print(f"[copytrade] manual-desk monitor error: {e}")


def run_copytrade():
    global _running, _last_wallet_sync, _last_wallet_filter
    engine.ensure_initialized()
    _running = True
    status["running"] = True
    _last_wallet_sync = 0.0
    _last_wallet_filter = 0.0
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
