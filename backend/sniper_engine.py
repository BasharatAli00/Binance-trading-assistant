"""Isolated simulated wallet engine for Strategy #3 (Intelligent Sniper).

Multi-portfolio: we seed a 'live' and a 'sim' wallet (both simulated for now).
Each has independent cash, positions, and trade log — nothing here touches
paper_engine (Strategy #1) or pivot_engine (Strategy #2).

Live execution is routed through sniper_live.py ONLY when a portfolio is
mode='live' AND LIVE_TRADING_ENABLED is set; otherwise every fill is simulated
at the given price with a friction proxy (FEE_RATE).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text

from database import SessionLocal, engine, Base
from models import (SniperPortfolio, SniperPosition, SniperTrade,
                    SniperCooldown, SniperSnapshot)
import sniper_config as cfg

# Strategy params the UI is allowed to edit via PUT /api/sniper/config.
EDITABLE_FIELDS = [
    "is_active", "position_size", "max_open_positions", "stop_loss_pct",
    "take_profit_pct", "time_exit_minutes", "trail_start_pct",
    "trail_start_distance", "trail_end_pct", "trail_end_distance",
    "conviction_floor", "min_buy_pressure", "rug_veto_threshold",
    "cb_enabled", "cb_max_drawdown",
]


def ensure_initialized():
    """Create the sniper tables and seed the two wallets once."""
    Base.metadata.create_all(bind=engine, checkfirst=True)
    # Self-heal: add columns that may be missing on a pre-existing table.
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE sniper_position ADD COLUMN IF NOT EXISTS last_price FLOAT;"))
        conn.commit()

    db = SessionLocal()
    try:
        existing = {p.name for p in db.query(SniperPortfolio).all()}
        now = datetime.utcnow()
        for seed in cfg.SEED_PORTFOLIOS:
            if seed["name"] in existing:
                continue
            db.add(SniperPortfolio(created_at=now, updated_at=now, **seed))
        if set(s["name"] for s in cfg.SEED_PORTFOLIOS) - existing:
            db.commit()
            print("[sniper] Initialized sniper wallets:",
                  ", ".join(s["name"] for s in cfg.SEED_PORTFOLIOS))
    finally:
        db.close()


# ---- Portfolio config ----------------------------------------------------

def get_portfolios():
    db = SessionLocal()
    try:
        return [_portfolio_dict(p) for p in db.query(SniperPortfolio).order_by(SniperPortfolio.id).all()]
    finally:
        db.close()


def get_portfolio_row(db, portfolio_id):
    return db.query(SniperPortfolio).filter(SniperPortfolio.id == portfolio_id).first()


def _portfolio_dict(p):
    return {c.name: getattr(p, c.name) for c in p.__table__.columns}


def update_config(portfolio_id, fields):
    """Update whitelisted strategy params for a portfolio."""
    db = SessionLocal()
    try:
        p = get_portfolio_row(db, portfolio_id)
        if not p:
            return None
        for k, v in fields.items():
            if k in EDITABLE_FIELDS and v is not None:
                setattr(p, k, v)
        p.updated_at = datetime.utcnow()
        db.commit()
        return _portfolio_dict(p)
    finally:
        db.close()


# ---- Positions -----------------------------------------------------------

def get_open_positions(portfolio_id):
    db = SessionLocal()
    try:
        rows = db.query(SniperPosition).filter(
            SniperPosition.portfolio_id == portfolio_id,
            SniperPosition.status == "open",
        ).all()
        return [_position_dict(r) for r in rows]
    finally:
        db.close()


def count_open(db, portfolio_id):
    return db.query(SniperPosition).filter(
        SniperPosition.portfolio_id == portfolio_id,
        SniperPosition.status == "open",
    ).count()


def is_holding(portfolio_id, token_address):
    db = SessionLocal()
    try:
        return db.query(SniperPosition.id).filter(
            SniperPosition.portfolio_id == portfolio_id,
            SniperPosition.token_address == token_address,
            SniperPosition.status == "open",
        ).first() is not None
    finally:
        db.close()


def _position_dict(p):
    return {c.name: getattr(p, c.name) for c in p.__table__.columns}


def update_position_mark(position_id, price):
    """Update the latest mark + ratchet the peak price for an open position."""
    db = SessionLocal()
    try:
        p = db.query(SniperPosition).filter(SniperPosition.id == position_id).first()
        if not p or p.status != "open":
            return
        p.last_price = price
        if price > (p.peak_price or p.entry_price):
            p.peak_price = price
        db.commit()
    finally:
        db.close()


# ---- Cooldowns -----------------------------------------------------------

def in_cooldown(token_address):
    db = SessionLocal()
    try:
        row = db.query(SniperCooldown).filter(
            SniperCooldown.token_address == token_address).first()
        return bool(row and row.cooldown_until and row.cooldown_until > datetime.utcnow())
    finally:
        db.close()


def _set_cooldown(db, token_address, reason):
    minutes = cfg.COOLDOWN_MINUTES.get(reason, cfg.COOLDOWN_MINUTES["default"])
    if minutes <= 0:
        return
    until = datetime.utcnow() + timedelta(minutes=minutes)
    row = db.query(SniperCooldown).filter(
        SniperCooldown.token_address == token_address).first()
    if row:
        row.cooldown_until = until
    else:
        db.add(SniperCooldown(token_address=token_address, cooldown_until=until))


# ---- Execution (simulated; live seam via sniper_live) --------------------

def execute_buy(portfolio, token_address, symbol, price, *, conviction=0.0,
                rug=0.0, dex_id="", pair_address="", source="watchlist"):
    """Open a fixed-size position for `portfolio` (a dict). Returns dict or None."""
    if price <= 0:
        return None
    pid = portfolio["id"]
    position_usd = float(portfolio.get("position_size") or 0)
    if position_usd <= 0:
        return None

    db = SessionLocal()
    try:
        p = get_portfolio_row(db, pid)
        if not p or p.cash_balance < position_usd:
            return None

        tx_hash = None
        # Live seam: only real when explicitly enabled. Safe no-op otherwise.
        if p.mode == "live" and cfg.LIVE_TRADING_ENABLED:
            import sniper_live
            res = sniper_live.execute_buy(token_address, position_usd)
            if not res or not res.get("confirmed"):
                return None
            tx_hash = res.get("tx_hash")
            price = res.get("fill_price", price)

        fee = position_usd * cfg.FEE_RATE
        qty = (position_usd - fee) / price
        p.cash_balance -= position_usd
        p.updated_at = datetime.utcnow()

        now = datetime.utcnow()
        pos = SniperPosition(
            portfolio_id=pid, token_address=token_address, symbol=symbol,
            entry_price=price, entry_time=now, qty=qty, position_usd=position_usd,
            peak_price=price, last_price=price, conviction_score=conviction,
            rug_risk_score=rug, entry_dex_id=dex_id, entry_pair_address=pair_address,
            discovery_source=source, tx_hash_buy=tx_hash, status="open",
        )
        db.add(pos)
        db.flush()  # get pos.id

        db.add(SniperTrade(
            portfolio_id=pid, position_id=pos.id, token_address=token_address,
            symbol=symbol, timestamp=now, side="buy", price=price, quantity=qty,
            usd_value=position_usd, fee=fee, realized_pnl=0.0,
            balance_after=p.cash_balance, reason=source, tx_hash=tx_hash, status="FILLED",
        ))
        db.commit()
        return {"position_id": str(pos.id), "qty": qty, "price": price}
    finally:
        db.close()


def execute_sell(position, price, reason):
    """Close an open position (dict) at `price`. Returns dict with realized P&L."""
    if price <= 0:
        return None
    db = SessionLocal()
    try:
        pos = db.query(SniperPosition).filter(
            SniperPosition.id == position["id"]).first()
        if not pos or pos.status != "open":
            return None
        p = get_portfolio_row(db, pos.portfolio_id)

        tx_hash = None
        if p and p.mode == "live" and cfg.LIVE_TRADING_ENABLED:
            import sniper_live
            res = sniper_live.execute_sell(pos.token_address, pos.qty)
            if res and res.get("confirmed"):
                tx_hash = res.get("tx_hash")
                price = res.get("fill_price", price)

        proceeds = pos.qty * price
        fee = proceeds * cfg.FEE_RATE
        net = proceeds - fee
        realized = net - pos.position_usd        # true cash P&L vs what we spent
        now = datetime.utcnow()
        hold_min = (now - pos.entry_time).total_seconds() / 60 if pos.entry_time else 0.0

        pos.status = "closed"
        pos.exit_price = price
        pos.exit_time = now
        pos.last_price = price
        pos.exit_reason = reason
        pos.realized_pnl = realized
        pos.return_pct = (realized / pos.position_usd * 100) if pos.position_usd else 0.0
        pos.hold_minutes = hold_min
        pos.tx_hash_sell = tx_hash

        if p:
            p.cash_balance += net
            p.updated_at = now

        db.add(SniperTrade(
            portfolio_id=pos.portfolio_id, position_id=pos.id,
            token_address=pos.token_address, symbol=pos.symbol, timestamp=now,
            side="sell", price=price, quantity=pos.qty, usd_value=proceeds, fee=fee,
            realized_pnl=realized, balance_after=(p.cash_balance if p else 0.0),
            reason=reason, tx_hash=tx_hash, status="FILLED",
        ))
        _set_cooldown(db, pos.token_address, reason)
        db.commit()
        return {"realized_pnl": realized, "return_pct": pos.return_pct, "reason": reason}
    finally:
        db.close()


# ---- Reporting / summaries ----------------------------------------------

def _latest_prices(db, addrs):
    """Latest snapshot price per token address (for marking open positions)."""
    if not addrs:
        return {}
    rows = db.query(
        SniperSnapshot.token_address,
        func.max(SniperSnapshot.snapshot_time).label("t"),
    ).filter(SniperSnapshot.token_address.in_(addrs)).group_by(
        SniperSnapshot.token_address).all()
    latest = {}
    for addr, t in rows:
        snap = db.query(SniperSnapshot.price_usd).filter(
            SniperSnapshot.token_address == addr,
            SniperSnapshot.snapshot_time == t,
        ).first()
        if snap and snap[0]:
            latest[addr] = snap[0]
    return latest


def _stats_for(db, portfolio_id, since=None):
    """Aggregate closed-position stats (count, wins, losses, pnl) optionally since a time."""
    q = db.query(SniperPosition).filter(
        SniperPosition.portfolio_id == portfolio_id,
        SniperPosition.status == "closed",
    )
    if since is not None:
        q = q.filter(SniperPosition.exit_time >= since)
    wins = losses = 0
    pnl = 0.0
    n = 0
    for r in q.all():
        n += 1
        pnl += r.realized_pnl or 0.0
        if (r.realized_pnl or 0.0) > 0:
            wins += 1
        else:
            losses += 1
    return {"trades": n, "wins": wins, "losses": losses, "pnl": pnl,
            "win_rate": (wins / n * 100) if n else 0.0}


def _cumulative_pnl(db, portfolio_id, initial_balance=0.0):
    """Cumulative realized-P&L series + EQUITY-based drawdown for the circuit breaker.

    Drawdown is measured against the realized-equity curve (initial_balance +
    cumulative realized P&L), NOT against cumulative P&L alone. Measuring % drop
    from peak *P&L* is pathologically sensitive when P&L is small (a single loser
    after any peak looks like a huge % drop), which made the 20% breaker trip
    permanently. Equity drawdown is the standard, meaningful definition: you have
    to actually lose ~20% of capital from the equity high-water mark to trip.
    """
    rows = db.query(SniperPosition.exit_time, SniperPosition.realized_pnl).filter(
        SniperPosition.portfolio_id == portfolio_id,
        SniperPosition.status == "closed",
        SniperPosition.exit_time.isnot(None),
    ).order_by(SniperPosition.exit_time.asc()).all()

    base = initial_balance or 0.0
    series, cum = [], 0.0
    peak_equity = base
    cur_dd = 0.0
    max_dd = 0.0
    for ts, pnl in rows:
        cum += pnl or 0.0
        equity = base + cum
        if equity > peak_equity:
            peak_equity = equity
        if peak_equity > 0:
            cur_dd = (peak_equity - equity) / peak_equity * 100
            max_dd = max(max_dd, cur_dd)
        series.append({"ts": ts.isoformat() if ts else None, "cum_pnl": round(cum, 4)})
    return series, {"cum_pnl": cum, "peak_equity": peak_equity,
                    "current_drawdown": max(cur_dd, 0.0), "max_drawdown": max_dd}


def _daily_drawdown(db, portfolio_id, initial_balance=0.0):
    """Rolling DAILY drawdown for the circuit breaker (resets at 00:00 UTC).

    A standard 'daily max loss' breaker: the equity high-water mark is reseeded at
    each UTC day boundary to the day's opening equity, so a tripped breaker clears
    automatically the next day instead of latching forever. (The previous all-time
    high-water-mark drawdown could never recover once tripped — no entry could open,
    so no position could close, so the drawdown number never moved: a deadlock.)

    Drawdown is measured against the realized-equity curve for *today's* closed
    positions, seeded at the equity carried into the day.
    """
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Equity carried into today = initial balance + all realized P&L booked before today.
    prior = db.query(func.coalesce(func.sum(SniperPosition.realized_pnl), 0.0)).filter(
        SniperPosition.portfolio_id == portfolio_id,
        SniperPosition.status == "closed",
        SniperPosition.exit_time.isnot(None),
        SniperPosition.exit_time < day_start,
    ).scalar() or 0.0
    day_open_equity = (initial_balance or 0.0) + prior

    rows = db.query(SniperPosition.realized_pnl).filter(
        SniperPosition.portfolio_id == portfolio_id,
        SniperPosition.status == "closed",
        SniperPosition.exit_time.isnot(None),
        SniperPosition.exit_time >= day_start,
    ).order_by(SniperPosition.exit_time.asc()).all()

    equity = peak_equity = day_open_equity
    cur_dd = max_dd = 0.0
    for (pnl,) in rows:
        equity += pnl or 0.0
        if equity > peak_equity:
            peak_equity = equity
        if peak_equity > 0:
            cur_dd = (peak_equity - equity) / peak_equity * 100
            max_dd = max(max_dd, cur_dd)
    return {"peak_equity": peak_equity, "current_drawdown": max(cur_dd, 0.0),
            "max_drawdown": max_dd, "day_open_equity": day_open_equity}


def portfolio_summary(portfolio_id):
    """Everything the Overview tab needs for one wallet."""
    db = SessionLocal()
    try:
        p = get_portfolio_row(db, portfolio_id)
        if not p:
            return None

        open_rows = db.query(SniperPosition).filter(
            SniperPosition.portfolio_id == portfolio_id,
            SniperPosition.status == "open",
        ).all()
        addrs = [r.token_address for r in open_rows]
        marks = _latest_prices(db, addrs)

        positions_value = 0.0
        unrealized = 0.0
        exposure = 0.0
        for r in open_rows:
            mark = marks.get(r.token_address) or r.last_price or r.entry_price
            value = r.qty * mark
            positions_value += value
            unrealized += value - r.position_usd
            exposure += r.position_usd

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        overall = _stats_for(db, portfolio_id)
        today = _stats_for(db, portfolio_id, since=today_start)
        cb = _daily_drawdown(db, portfolio_id, p.initial_balance)

        equity = p.cash_balance + positions_value
        total_pnl = equity - p.initial_balance
        total_pnl_pct = (total_pnl / p.initial_balance * 100) if p.initial_balance else 0.0

        headroom_pct = max(0.0, p.cb_max_drawdown - cb["current_drawdown"]) if p.cb_enabled else None
        headroom_usd = (cb["peak_equity"] * headroom_pct / 100) if (headroom_pct is not None) else None

        return {
            "id": p.id,
            "name": p.name,
            "mode": p.mode,
            "is_active": p.is_active,
            "cash_balance": p.cash_balance,
            "initial_balance": p.initial_balance,
            "position_size": p.position_size,
            "max_open_positions": p.max_open_positions,
            "open_positions": len(open_rows),
            "open_exposure": exposure,
            "positions_value": positions_value,
            "total_value": equity,
            "unrealized_pnl": unrealized,
            "realized_pnl": overall["pnl"],
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "win_rate": overall["win_rate"],
            "today": today,
            "overall": overall,
            "circuit_breaker": {
                "enabled": p.cb_enabled,
                "max_drawdown": p.cb_max_drawdown,
                "current_drawdown": cb["current_drawdown"],
                "headroom_pct": headroom_pct,
                "headroom_usd": headroom_usd,
                "tripped": bool(p.cb_enabled and cb["current_drawdown"] >= p.cb_max_drawdown),
            },
            "config": _portfolio_dict(p),
        }
    finally:
        db.close()


def get_positions(portfolio_id, status="open", limit=200):
    db = SessionLocal()
    try:
        q = db.query(SniperPosition).filter(SniperPosition.portfolio_id == portfolio_id)
        if status:
            q = q.filter(SniperPosition.status == status)
        order = (SniperPosition.entry_time.desc() if status == "open"
                 else SniperPosition.exit_time.desc())
        rows = q.order_by(order).limit(limit).all()
        out = []
        for r in rows:
            d = _position_dict(r)
            for k in ("id", "portfolio_id"):
                d[k] = str(d[k])
            for k in ("entry_time", "exit_time"):
                d[k] = d[k].isoformat() if d.get(k) else None
            mark = r.last_price or r.entry_price
            d["unrealized_pnl"] = (r.qty * mark - r.position_usd) if r.status == "open" else 0.0
            out.append(d)
        return out
    finally:
        db.close()


def get_trades(portfolio_id, limit=100):
    db = SessionLocal()
    try:
        rows = db.query(SniperTrade).filter(
            SniperTrade.portfolio_id == portfolio_id,
        ).order_by(SniperTrade.timestamp.desc()).limit(limit).all()
        return [{
            "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M:%S") if r.timestamp else "",
            "token_address": r.token_address,
            "symbol": r.symbol,
            "side": r.side,
            "price": r.price,
            "quantity": r.quantity,
            "usd_value": r.usd_value,
            "fee": r.fee,
            "realized_pnl": r.realized_pnl,
            "reason": r.reason or "",
            "tx_hash": r.tx_hash,
        } for r in rows]
    finally:
        db.close()


def chart_pnl(portfolio_id):
    db = SessionLocal()
    try:
        series, _ = _cumulative_pnl(db, portfolio_id)
        return series
    finally:
        db.close()


def circuit_breaker_state(portfolio_id):
    """Used by the loop to decide whether to pause entries."""
    db = SessionLocal()
    try:
        p = get_portfolio_row(db, portfolio_id)
        if not p or not p.cb_enabled:
            return {"tripped": False}
        cb = _daily_drawdown(db, portfolio_id, p.initial_balance)
        return {"tripped": cb["current_drawdown"] >= p.cb_max_drawdown,
                "current_drawdown": cb["current_drawdown"]}
    finally:
        db.close()


def reset_portfolio(portfolio_id):
    """Flatten positions/trades and restore the starting balance for one wallet."""
    db = SessionLocal()
    try:
        p = get_portfolio_row(db, portfolio_id)
        if not p:
            return None
        db.query(SniperPosition).filter(SniperPosition.portfolio_id == portfolio_id).delete()
        db.query(SniperTrade).filter(SniperTrade.portfolio_id == portfolio_id).delete()
        p.cash_balance = p.initial_balance
        p.is_active = True
        p.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "reset", "cash_balance": p.cash_balance}
    finally:
        db.close()
