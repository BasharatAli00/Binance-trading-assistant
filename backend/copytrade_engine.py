"""Simulated wallet engine for Strategy #4 (Smart-Money Copy Trade).

One isolated sim portfolio. Buy/sell/partial-sell + reporting + a daily
circuit breaker, adapted from sniper_engine but single-wallet and copy-specific
(positions remember which wallets triggered them, for the mirror-sell exit).
Nothing here touches the other strategies.
"""
from datetime import datetime, timedelta

from sqlalchemy import func

from database import SessionLocal, engine, Base
from models import (CopyTradePortfolio, CopyPosition, CopyTrade,
                    CopyCooldown, CopySignal)
import copytrade_config as cfg

EDITABLE_FIELDS = ["is_active", "position_size", "max_open_positions", "initial_balance"]


def ensure_initialized():
    """Create Strategy #4 tables and seed the single sim wallet once."""
    Base.metadata.create_all(bind=engine, checkfirst=True)
    db = SessionLocal()
    try:
        if not db.query(CopyTradePortfolio).first():
            now = datetime.utcnow()
            db.add(CopyTradePortfolio(
                name="CopyTrade Sim", mode="sim", is_active=True,
                cash_balance=cfg.INITIAL_BALANCE, initial_balance=cfg.INITIAL_BALANCE,
                position_size=cfg.POSITION_SIZE_USD,
                max_open_positions=cfg.MAX_OPEN_POSITIONS,
                created_at=now, updated_at=now,
            ))
            db.commit()
            print("[copytrade] Initialized copy-trade sim wallet")
    finally:
        db.close()


# ---- Portfolio -----------------------------------------------------------

def _row_dict(r):
    return {c.name: getattr(r, c.name) for c in r.__table__.columns}


def get_portfolio_row(db):
    return db.query(CopyTradePortfolio).order_by(CopyTradePortfolio.id).first()


def get_portfolio():
    db = SessionLocal()
    try:
        p = get_portfolio_row(db)
        return _row_dict(p) if p else None
    finally:
        db.close()


def update_config(fields):
    db = SessionLocal()
    try:
        p = get_portfolio_row(db)
        if not p:
            return None
        for k, v in fields.items():
            if k in EDITABLE_FIELDS and v is not None:
                setattr(p, k, v)
        p.updated_at = datetime.utcnow()
        db.commit()
        return _row_dict(p)
    finally:
        db.close()


# ---- Positions -----------------------------------------------------------

def get_open_positions():
    db = SessionLocal()
    try:
        rows = db.query(CopyPosition).filter(CopyPosition.status == "open").all()
        return [_row_dict(r) for r in rows]
    finally:
        db.close()


def is_holding(mint):
    db = SessionLocal()
    try:
        return db.query(CopyPosition.id).filter(
            CopyPosition.mint == mint, CopyPosition.status == "open").first() is not None
    finally:
        db.close()


def update_position_mark(position_id, price):
    db = SessionLocal()
    try:
        p = db.query(CopyPosition).filter(CopyPosition.id == position_id).first()
        if not p or p.status != "open":
            return
        p.last_price = price
        if price > (p.peak_price or p.entry_price):
            p.peak_price = price
        db.commit()
    finally:
        db.close()


def mark_wallet_exited(position_id, wallet):
    """Record that a triggering wallet has sold — feeds the mirror-sell exit."""
    db = SessionLocal()
    try:
        p = db.query(CopyPosition).filter(CopyPosition.id == position_id).first()
        if not p or p.status != "open":
            return 0
        exited = set(p.exited_wallets or [])
        triggers = set(p.trigger_wallets or [])
        if wallet in triggers:
            exited.add(wallet)
            p.exited_wallets = sorted(exited)
            db.commit()
        return len(exited)
    finally:
        db.close()


# ---- Cooldown ------------------------------------------------------------

def in_cooldown(mint):
    db = SessionLocal()
    try:
        row = db.query(CopyCooldown).filter(CopyCooldown.mint == mint).first()
        return bool(row and row.cooldown_until and row.cooldown_until > datetime.utcnow())
    finally:
        db.close()


def _set_cooldown(db, mint, reason):
    minutes = cfg.COOLDOWN_MINUTES.get(reason, cfg.COOLDOWN_MINUTES["default"])
    if minutes <= 0:
        return
    until = datetime.utcnow() + timedelta(minutes=minutes)
    row = db.query(CopyCooldown).filter(CopyCooldown.mint == mint).first()
    if row:
        row.cooldown_until = until
    else:
        db.add(CopyCooldown(mint=mint, cooldown_until=until))


# ---- Execution (simulated) ----------------------------------------------

def execute_buy(mint, symbol, price, trigger_wallets):
    if price <= 0:
        return None
    db = SessionLocal()
    try:
        p = get_portfolio_row(db)
        size = float(p.position_size or 0) if p else 0
        if not p or size <= 0 or p.cash_balance < size:
            return None

        fee = size * cfg.FEE_RATE
        qty = (size - fee) / price
        now = datetime.utcnow()
        p.cash_balance -= size
        p.updated_at = now

        pos = CopyPosition(
            portfolio_id=p.id, mint=mint, symbol=symbol, entry_price=price,
            entry_time=now, qty=qty, position_usd=size, cost_basis=size,
            scaled_out=False, peak_price=price, last_price=price,
            trigger_wallets=sorted(set(trigger_wallets or [])), exited_wallets=[],
            status="open",
        )
        db.add(pos)
        db.flush()
        db.add(CopyTrade(
            portfolio_id=p.id, position_id=pos.id, mint=mint, symbol=symbol,
            timestamp=now, side="buy", price=price, quantity=qty, usd_value=size,
            fee=fee, realized_pnl=0.0, balance_after=p.cash_balance,
            reason="consensus_entry", status="FILLED",
        ))
        db.commit()
        return {"position_id": str(pos.id), "qty": qty, "price": price}
    finally:
        db.close()


def execute_sell(position, price, reason):
    if price <= 0:
        return None
    db = SessionLocal()
    try:
        pos = db.query(CopyPosition).filter(CopyPosition.id == position["id"]).first()
        if not pos or pos.status != "open":
            return None
        p = get_portfolio_row(db)

        proceeds = pos.qty * price
        fee = proceeds * cfg.FEE_RATE
        net = proceeds - fee
        basis = pos.cost_basis if pos.cost_basis is not None else pos.position_usd
        realized_now = net - basis
        total_realized = (pos.realized_pnl or 0.0) + realized_now
        now = datetime.utcnow()
        hold_min = (now - pos.entry_time).total_seconds() / 60 if pos.entry_time else 0.0

        pos.status = "closed"
        pos.exit_price = price
        pos.exit_time = now
        pos.last_price = price
        pos.exit_reason = reason
        pos.realized_pnl = total_realized
        pos.return_pct = (total_realized / pos.position_usd * 100) if pos.position_usd else 0.0
        pos.cost_basis = 0.0
        pos.hold_minutes = hold_min

        if p:
            p.cash_balance += net
            p.updated_at = now

        db.add(CopyTrade(
            portfolio_id=pos.portfolio_id, position_id=pos.id, mint=pos.mint,
            symbol=pos.symbol, timestamp=now, side="sell", price=price,
            quantity=pos.qty, usd_value=proceeds, fee=fee, realized_pnl=realized_now,
            balance_after=(p.cash_balance if p else 0.0), reason=reason, status="FILLED",
        ))
        _set_cooldown(db, pos.mint, reason)
        db.commit()
        return {"realized_pnl": total_realized, "return_pct": pos.return_pct, "reason": reason}
    finally:
        db.close()


def execute_partial_sell(position, price, fraction, reason="take_profit"):
    if price <= 0 or not (0 < fraction < 1):
        return None
    db = SessionLocal()
    try:
        pos = db.query(CopyPosition).filter(CopyPosition.id == position["id"]).first()
        if not pos or pos.status != "open" or not pos.qty:
            return None
        p = get_portfolio_row(db)

        sell_qty = pos.qty * fraction
        proceeds = sell_qty * price
        fee = proceeds * cfg.FEE_RATE
        net = proceeds - fee
        basis = pos.cost_basis if pos.cost_basis is not None else pos.position_usd
        sold_basis = basis * fraction
        realized = net - sold_basis
        now = datetime.utcnow()

        pos.qty -= sell_qty
        pos.cost_basis = basis - sold_basis
        pos.scaled_out = True
        pos.last_price = price
        pos.realized_pnl = (pos.realized_pnl or 0.0) + realized
        pos.return_pct = (pos.realized_pnl / pos.position_usd * 100) if pos.position_usd else 0.0

        if p:
            p.cash_balance += net
            p.updated_at = now

        db.add(CopyTrade(
            portfolio_id=pos.portfolio_id, position_id=pos.id, mint=pos.mint,
            symbol=pos.symbol, timestamp=now, side="sell", price=price,
            quantity=sell_qty, usd_value=proceeds, fee=fee, realized_pnl=realized,
            balance_after=(p.cash_balance if p else 0.0), reason=reason, status="FILLED",
        ))
        db.commit()
        return {"realized_pnl": realized, "sold_qty": sell_qty, "reason": reason}
    finally:
        db.close()


# ---- Circuit breaker (daily max loss) -----------------------------------

def _daily_drawdown(db, portfolio_id, initial_balance):
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    prior = db.query(func.coalesce(func.sum(CopyPosition.realized_pnl), 0.0)).filter(
        CopyPosition.portfolio_id == portfolio_id, CopyPosition.status == "closed",
        CopyPosition.exit_time.isnot(None), CopyPosition.exit_time < day_start,
    ).scalar() or 0.0
    day_open_equity = (initial_balance or 0.0) + prior

    rows = db.query(CopyPosition.realized_pnl).filter(
        CopyPosition.portfolio_id == portfolio_id, CopyPosition.status == "closed",
        CopyPosition.exit_time.isnot(None), CopyPosition.exit_time >= day_start,
    ).order_by(CopyPosition.exit_time.asc()).all()

    equity = peak = day_open_equity
    cur_dd = 0.0
    for (pnl,) in rows:
        equity += pnl or 0.0
        peak = max(peak, equity)
        if peak > 0:
            cur_dd = (peak - equity) / peak * 100
    return {"current_drawdown": max(cur_dd, 0.0), "day_open_equity": day_open_equity}


def circuit_breaker_tripped():
    db = SessionLocal()
    try:
        p = get_portfolio_row(db)
        if not p:
            return False
        dd = _daily_drawdown(db, p.id, p.initial_balance)
        return dd["current_drawdown"] >= cfg.DAILY_MAX_LOSS_PCT
    finally:
        db.close()


# ---- Reporting -----------------------------------------------------------

def portfolio_summary():
    db = SessionLocal()
    try:
        p = get_portfolio_row(db)
        if not p:
            return None
        open_rows = db.query(CopyPosition).filter(CopyPosition.status == "open").all()
        positions_value = unrealized = exposure = 0.0
        for r in open_rows:
            mark = r.last_price or r.entry_price
            value = r.qty * mark
            basis = r.cost_basis if r.cost_basis is not None else r.position_usd
            positions_value += value
            unrealized += value - basis
            exposure += basis

        closed = db.query(CopyPosition).filter(CopyPosition.status == "closed").all()
        wins = sum(1 for r in closed if (r.realized_pnl or 0) > 0)
        realized = sum(r.realized_pnl or 0 for r in closed)
        equity = p.cash_balance + positions_value
        dd = _daily_drawdown(db, p.id, p.initial_balance)
        return {
            "id": p.id, "name": p.name, "mode": p.mode, "is_active": p.is_active,
            "cash_balance": p.cash_balance, "initial_balance": p.initial_balance,
            "position_size": p.position_size, "max_open_positions": p.max_open_positions,
            "open_positions": len(open_rows), "open_exposure": exposure,
            "positions_value": positions_value, "total_value": equity,
            "unrealized_pnl": unrealized, "realized_pnl": realized,
            "total_pnl": equity - p.initial_balance,
            "total_pnl_pct": ((equity - p.initial_balance) / p.initial_balance * 100)
                             if p.initial_balance else 0.0,
            "closed_trades": len(closed), "wins": wins,
            "win_rate": (wins / len(closed) * 100) if closed else 0.0,
            "circuit_breaker": {
                "enabled": True, "max_daily_loss": cfg.DAILY_MAX_LOSS_PCT,
                "current_drawdown": dd["current_drawdown"],
                "tripped": dd["current_drawdown"] >= cfg.DAILY_MAX_LOSS_PCT,
            },
        }
    finally:
        db.close()


def get_positions(status="open", limit=200):
    db = SessionLocal()
    try:
        q = db.query(CopyPosition)
        if status:
            q = q.filter(CopyPosition.status == status)
        order = (CopyPosition.entry_time.desc() if status == "open"
                 else CopyPosition.exit_time.desc())
        rows = q.order_by(order).limit(limit).all()
        out = []
        for r in rows:
            d = _row_dict(r)
            d["id"] = str(d["id"])
            for k in ("entry_time", "exit_time"):
                d[k] = d[k].isoformat() if d.get(k) else None
            mark = r.last_price or r.entry_price
            basis = r.cost_basis if r.cost_basis is not None else r.position_usd
            d["unrealized_pnl"] = (r.qty * mark - basis) if r.status == "open" else 0.0
            out.append(d)
        return out
    finally:
        db.close()


def get_trades(limit=100):
    db = SessionLocal()
    try:
        rows = db.query(CopyTrade).order_by(CopyTrade.timestamp.desc()).limit(limit).all()
        return [{
            "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M:%S") if r.timestamp else "",
            "mint": r.mint, "symbol": r.symbol, "side": r.side, "price": r.price,
            "quantity": r.quantity, "usd_value": r.usd_value, "fee": r.fee,
            "realized_pnl": r.realized_pnl, "reason": r.reason or "",
        } for r in rows]
    finally:
        db.close()


def get_signals(limit=50):
    db = SessionLocal()
    try:
        rows = db.query(CopySignal).order_by(CopySignal.fired_at.desc()).limit(limit).all()
        return [{
            "mint": r.mint, "symbol": r.symbol, "wallet_count": r.wallet_count,
            "wallets": r.wallets or [], "status": r.status, "reason": r.reason,
            "fired_at": r.fired_at.isoformat() if r.fired_at else None,
        } for r in rows]
    finally:
        db.close()


def reset():
    db = SessionLocal()
    try:
        p = get_portfolio_row(db)
        if not p:
            return None
        db.query(CopyPosition).delete()
        db.query(CopyTrade).delete()
        db.query(CopySignal).delete()
        db.query(CopyCooldown).delete()
        p.cash_balance = p.initial_balance
        p.is_active = True
        p.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "reset", "cash_balance": p.cash_balance}
    finally:
        db.close()
