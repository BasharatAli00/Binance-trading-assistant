"""Isolated paper-trading engine for the manual-trade desk (Strategy Three).

A self-contained virtual wallet the user drives by hand: place a BTC buy
(market, or a limit at a chosen price) with an optional take-profit and
stop-loss. The trader loop calls `monitor()` every pass to fill pending
limit orders and auto-exit open positions when TP/SL is touched.

Everything here is isolated from the automated strategies — its own account,
positions and trade log (manual_account / manual_positions / manual_trades) —
using the same fee model and live-price fills, persisted to the DB.
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from database import SessionLocal, engine, Base
from models import ManualAccount, ManualPosition, ManualTrade

STARTING_BALANCE = 10000.0   # manual desk starts with more room for concurrent bets
FEE_RATE = 0.001             # 0.1% simulated spot taker fee per trade
MAX_POSITIONS = 5            # "Up to 5 concurrent positions" (pending + open)
DEFAULT_SYMBOL = "BTCUSDT"   # the manual desk trades BTC only for now


def ensure_initialized():
    """Create the manual-desk tables and seed the wallet once."""
    Base.metadata.create_all(bind=engine, checkfirst=True)
    db = SessionLocal()
    try:
        if not db.query(ManualAccount).first():
            now = datetime.utcnow()
            db.add(ManualAccount(
                usdt_balance=STARTING_BALANCE,
                starting_balance=STARTING_BALANCE,
                created_at=now,
                updated_at=now,
            ))
            db.commit()
            print(f"[manual] Initialized manual-trade wallet with {STARTING_BALANCE} USDT")
    finally:
        db.close()


def _get_account(db):
    acc = db.query(ManualAccount).first()
    if not acc:
        now = datetime.utcnow()
        acc = ManualAccount(
            usdt_balance=STARTING_BALANCE,
            starting_balance=STARTING_BALANCE,
            created_at=now,
            updated_at=now,
        )
        db.add(acc)
        db.commit()
    return acc


def _active_count(db, symbol=None):
    q = db.query(ManualPosition).filter(ManualPosition.status.in_(["pending", "open"]))
    if symbol:
        q = q.filter(ManualPosition.symbol == symbol)
    return q.count()


def _record_buy(db, pos, acc, price, reason):
    """Turn a reserved order into an open position (records a BUY fill)."""
    fee = pos.amount_usdt * FEE_RATE
    qty = (pos.amount_usdt - fee) / price
    pos.quantity = qty
    pos.avg_entry_price = price
    pos.status = "open"
    pos.filled_at = datetime.utcnow()
    pos.updated_at = datetime.utcnow()
    db.add(ManualTrade(
        symbol=pos.symbol, timestamp=datetime.utcnow(), side="BUY", price=price,
        quantity=qty, quote_amount=pos.amount_usdt, fee=fee, realized_pnl=0.0,
        balance_after=acc.usdt_balance, reason=reason, status="FILLED",
    ))


def _close(db, pos, acc, price, reason):
    """Sell an open position at `price` and bank the proceeds (records a SELL)."""
    proceeds = pos.quantity * price
    fee = proceeds * FEE_RATE
    net = proceeds - fee
    realized = net - pos.quantity * pos.avg_entry_price

    acc.usdt_balance += net
    acc.updated_at = datetime.utcnow()

    db.add(ManualTrade(
        symbol=pos.symbol, timestamp=datetime.utcnow(), side="SELL", price=price,
        quantity=pos.quantity, quote_amount=proceeds, fee=fee, realized_pnl=realized,
        balance_after=acc.usdt_balance, reason=reason, status="FILLED",
    ))

    pos.status = "closed"
    pos.exit_price = price
    pos.realized_pnl = realized
    pos.exit_reason = reason
    pos.updated_at = datetime.utcnow()
    return realized


def place_order(amount_usdt, limit_price=None, take_profit=None, stop_price=None,
                live_price=None, symbol=DEFAULT_SYMBOL):
    """Place a manual buy. Market fills now; a limit fills when price touches it.

    Returns a dict describing the result, or {"error": ...} on rejection.
    """
    try:
        amount_usdt = float(amount_usdt)
    except (TypeError, ValueError):
        return {"error": "Invalid amount"}
    if amount_usdt <= 0:
        return {"error": "Amount must be greater than 0"}

    limit_price = float(limit_price) if limit_price not in (None, "") else None
    take_profit = float(take_profit) if take_profit not in (None, "") else None
    stop_price = float(stop_price) if stop_price not in (None, "") else None

    db = SessionLocal()
    try:
        if _active_count(db) >= MAX_POSITIONS:
            return {"error": f"Max {MAX_POSITIONS} concurrent positions reached"}

        acc = _get_account(db)
        if acc.usdt_balance < amount_usdt:
            return {"error": "Insufficient cash"}

        # Reserve the cash up front (refunded if a pending order is cancelled).
        acc.usdt_balance -= amount_usdt
        acc.updated_at = datetime.utcnow()

        now = datetime.utcnow()
        pos = ManualPosition(
            symbol=symbol, status="pending", amount_usdt=amount_usdt,
            limit_price=limit_price, quantity=0.0, avg_entry_price=0.0,
            take_profit=take_profit, stop_price=stop_price, realized_pnl=0.0,
            created_at=now, updated_at=now,
        )
        db.add(pos)

        # Fill immediately when it's a market order, or a limit that the current
        # price already satisfies (buy limit fills at or below the limit).
        filled = False
        if live_price and live_price > 0:
            if limit_price is None or live_price <= limit_price:
                fill_price = live_price if limit_price is None else min(live_price, limit_price)
                _record_buy(db, pos, acc, fill_price,
                            "Manual market buy" if limit_price is None else "Manual limit filled")
                filled = True

        db.commit()
        return {
            "status": "filled" if filled else "pending",
            "id": str(pos.id),
            "symbol": symbol,
            "amount_usdt": amount_usdt,
            "avg_entry_price": pos.avg_entry_price,
            "limit_price": limit_price,
        }
    except SQLAlchemyError as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


def monitor(live_price, symbol=DEFAULT_SYMBOL):
    """Fill pending limits and auto-exit open positions on TP/SL. Loop-driven."""
    if not live_price or live_price <= 0:
        return
    db = SessionLocal()
    try:
        acc = _get_account(db)
        rows = db.query(ManualPosition).filter(
            ManualPosition.symbol == symbol,
            ManualPosition.status.in_(["pending", "open"]),
        ).all()
        changed = False
        for pos in rows:
            if pos.status == "pending":
                # Buy limit fills once the market trades at or below the limit.
                if pos.limit_price is not None and live_price <= pos.limit_price:
                    _record_buy(db, pos, acc, min(live_price, pos.limit_price), "Manual limit filled")
                    changed = True
            elif pos.status == "open":
                if pos.take_profit and live_price >= pos.take_profit:
                    r = _close(db, pos, acc, live_price, "Take-profit hit")
                    print(f"[manual {symbol}] TP hit @ ${live_price:.2f} | P&L ${r:.2f}")
                    changed = True
                elif pos.stop_price and live_price <= pos.stop_price:
                    r = _close(db, pos, acc, live_price, "Stop-loss hit")
                    print(f"[manual {symbol}] SL hit @ ${live_price:.2f} | P&L ${r:.2f}")
                    changed = True
        if changed:
            db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        print(f"[manual] monitor error: {e}")
    finally:
        db.close()


def cancel_order(order_id):
    """Cancel a pending limit order and refund its reserved cash."""
    db = SessionLocal()
    try:
        pos = db.query(ManualPosition).filter(ManualPosition.id == order_id).first()
        if not pos:
            return {"error": "Order not found"}
        if pos.status != "pending":
            return {"error": "Only pending orders can be cancelled"}
        acc = _get_account(db)
        acc.usdt_balance += pos.amount_usdt   # refund the reservation
        acc.updated_at = datetime.utcnow()
        pos.status = "closed"
        pos.exit_reason = "Cancelled"
        pos.realized_pnl = 0.0
        pos.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "cancelled", "id": str(pos.id)}
    finally:
        db.close()


def close_position(order_id, live_price):
    """Manually sell an open position at the current market price."""
    if not live_price or live_price <= 0:
        return {"error": "No live price available"}
    db = SessionLocal()
    try:
        pos = db.query(ManualPosition).filter(ManualPosition.id == order_id).first()
        if not pos:
            return {"error": "Position not found"}
        if pos.status != "open":
            return {"error": "Only open positions can be closed"}
        acc = _get_account(db)
        realized = _close(db, pos, acc, live_price, "Manual close")
        db.commit()
        return {"status": "closed", "id": str(pos.id), "realized_pnl": realized}
    finally:
        db.close()


def get_open_orders(symbol=None):
    """Return pending + open manual positions (newest first) as plain dicts."""
    db = SessionLocal()
    try:
        q = db.query(ManualPosition).filter(ManualPosition.status.in_(["pending", "open"]))
        if symbol:
            q = q.filter(ManualPosition.symbol == symbol)
        rows = q.order_by(ManualPosition.created_at.desc()).all()
        return [{
            "id": str(p.id),
            "symbol": p.symbol,
            "status": p.status,
            "amount_usdt": p.amount_usdt,
            "limit_price": p.limit_price,
            "quantity": p.quantity,
            "avg_entry_price": p.avg_entry_price,
            "take_profit": p.take_profit,
            "stop_price": p.stop_price,
            "created_at": p.created_at.strftime('%Y-%m-%d %H:%M:%S') if p.created_at else "",
        } for p in rows]
    finally:
        db.close()


def portfolio_summary(prices):
    """Build the manual-desk wallet snapshot. `prices` maps base asset -> price."""
    db = SessionLocal()
    try:
        acc = _get_account(db)
        rows = db.query(ManualPosition).filter(
            ManualPosition.status.in_(["pending", "open"])
        ).all()

        positions_value = 0.0
        unrealized = 0.0
        reserved = 0.0
        open_count = 0
        pending_count = 0

        for p in rows:
            if p.status == "pending":
                reserved += p.amount_usdt
                pending_count += 1
                continue
            open_count += 1
            base = p.symbol.replace("USDT", "")
            price = prices.get(base, 0.0) or 0.0
            positions_value += p.quantity * price
            unrealized += (price - p.avg_entry_price) * p.quantity

        realized_total = db.query(func.coalesce(func.sum(ManualTrade.realized_pnl), 0.0)).scalar() or 0.0
        # Reserved cash for unfilled limits is still the user's money -> counts to equity.
        equity = acc.usdt_balance + reserved + positions_value
        total_pnl = equity - acc.starting_balance
        total_pnl_pct = (total_pnl / acc.starting_balance * 100) if acc.starting_balance else 0.0

        return {
            "cash": acc.usdt_balance,
            "reserved": reserved,
            "positions_value": positions_value,
            "total_equity": equity,
            "unrealized_pnl": unrealized,
            "realized_pnl": realized_total,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "starting_balance": acc.starting_balance,
            "open_positions": open_count,
            "pending_orders": pending_count,
            "max_positions": MAX_POSITIONS,
        }
    finally:
        db.close()


def get_recent_trades(symbol=None, limit=20):
    """Return recent manual-desk trades (newest first) as plain dicts."""
    db = SessionLocal()
    try:
        q = db.query(ManualTrade)
        if symbol:
            q = q.filter(ManualTrade.symbol == symbol)
        rows = q.order_by(ManualTrade.timestamp.desc()).limit(limit).all()
        return [{
            "timestamp": r.timestamp.strftime('%Y-%m-%d %H:%M:%S') if r.timestamp else "",
            "symbol": r.symbol,
            "side": r.side,
            "price": r.price,
            "quantity": r.quantity,
            "quote_amount": r.quote_amount,
            "fee": r.fee,
            "realized_pnl": r.realized_pnl,
            "reason": r.reason or "",
        } for r in rows]
    finally:
        db.close()


def reset_wallet(clear_trades=True):
    """Reset the manual wallet to its starting balance and drop all positions."""
    db = SessionLocal()
    try:
        db.query(ManualPosition).delete()
        if clear_trades:
            db.query(ManualTrade).delete()
        acc = _get_account(db)
        acc.usdt_balance = STARTING_BALANCE
        acc.starting_balance = STARTING_BALANCE
        acc.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "reset", "usdt_balance": STARTING_BALANCE}
    finally:
        db.close()
