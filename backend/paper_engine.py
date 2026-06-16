"""
Simulated (paper) trading engine.

A self-contained virtual wallet that starts at 5,000 USDT and trades using LIVE
market prices, but NEVER places a real order on Binance. All state (cash,
positions, trades) is persisted in the database so it survives restarts and
redeploys.
"""
from datetime import datetime

from sqlalchemy import func, text

from database import SessionLocal, engine, Base
from models import PaperAccount, Position, Trade

STARTING_BALANCE = 5000.0   # virtual starting capital, matches Binance demo
FEE_RATE = 0.001            # 0.1% simulated Binance spot taker fee per trade


def ensure_initialized():
    """Create tables, self-heal the trades schema, and seed the wallet once."""
    Base.metadata.create_all(bind=engine, checkfirst=True)

    # Self-heal: add the new trade columns to an existing 'trades' table.
    with engine.connect() as conn:
        for col, typ in [
            ("quote_amount", "FLOAT"),
            ("fee", "FLOAT"),
            ("realized_pnl", "FLOAT"),
            ("balance_after", "FLOAT"),
            ("reason", "VARCHAR"),
        ]:
            conn.execute(text(f"ALTER TABLE trades ADD COLUMN IF NOT EXISTS {col} {typ};"))
        conn.commit()

    db = SessionLocal()
    try:
        if not db.query(PaperAccount).first():
            now = datetime.utcnow()
            db.add(PaperAccount(
                usdt_balance=STARTING_BALANCE,
                starting_balance=STARTING_BALANCE,
                created_at=now,
                updated_at=now,
            ))
            db.commit()
            print(f"[paper] Initialized paper wallet with {STARTING_BALANCE} USDT")
    finally:
        db.close()


def _get_account(db):
    acc = db.query(PaperAccount).first()
    if not acc:
        now = datetime.utcnow()
        acc = PaperAccount(
            usdt_balance=STARTING_BALANCE,
            starting_balance=STARTING_BALANCE,
            created_at=now,
            updated_at=now,
        )
        db.add(acc)
        db.commit()
    return acc


def get_position(symbol):
    """Return a plain dict for the open position, or None if flat."""
    db = SessionLocal()
    try:
        p = db.query(Position).filter(Position.symbol == symbol).first()
        if not p or p.quantity <= 0:
            return None
        return {
            "symbol": p.symbol,
            "quantity": p.quantity,
            "avg_entry_price": p.avg_entry_price,
        }
    finally:
        db.close()


def execute_buy(symbol, quote_usdt, price, reason=""):
    """Spend `quote_usdt` cash to buy `symbol` at `price`. Returns dict or None."""
    if quote_usdt <= 0 or price <= 0:
        return None
    db = SessionLocal()
    try:
        acc = _get_account(db)
        if acc.usdt_balance < quote_usdt:
            return None  # not enough cash; caller should size correctly

        fee = quote_usdt * FEE_RATE
        qty = (quote_usdt - fee) / price

        acc.usdt_balance -= quote_usdt
        acc.updated_at = datetime.utcnow()

        pos = db.query(Position).filter(Position.symbol == symbol).first()
        if pos and pos.quantity > 0:
            total_cost = pos.avg_entry_price * pos.quantity + price * qty
            pos.quantity += qty
            pos.avg_entry_price = total_cost / pos.quantity
            pos.updated_at = datetime.utcnow()
        elif pos:
            pos.quantity = qty
            pos.avg_entry_price = price
            pos.updated_at = datetime.utcnow()
        else:
            db.add(Position(symbol=symbol, quantity=qty, avg_entry_price=price,
                            updated_at=datetime.utcnow()))

        db.add(Trade(
            symbol=symbol, timestamp=datetime.utcnow(), side="BUY", price=price,
            quantity=qty, quote_amount=quote_usdt, fee=fee, realized_pnl=0.0,
            balance_after=acc.usdt_balance, reason=reason, status="FILLED",
        ))
        db.commit()
        return {"qty": qty, "fee": fee, "price": price}
    finally:
        db.close()


def execute_sell(symbol, qty, price, reason=""):
    """Sell `qty` of `symbol` at `price`. Returns dict (with realized P&L) or None."""
    if price <= 0:
        return None
    db = SessionLocal()
    try:
        pos = db.query(Position).filter(Position.symbol == symbol).first()
        if not pos or pos.quantity <= 0:
            return None

        qty = min(qty, pos.quantity)
        if qty <= 0:
            return None

        proceeds = qty * price
        fee = proceeds * FEE_RATE
        net = proceeds - fee
        realized = net - qty * pos.avg_entry_price

        acc = _get_account(db)
        acc.usdt_balance += net
        acc.updated_at = datetime.utcnow()

        pos.quantity -= qty
        if pos.quantity <= 1e-12:
            pos.quantity = 0.0
            pos.avg_entry_price = 0.0
        pos.updated_at = datetime.utcnow()

        db.add(Trade(
            symbol=symbol, timestamp=datetime.utcnow(), side="SELL", price=price,
            quantity=qty, quote_amount=proceeds, fee=fee, realized_pnl=realized,
            balance_after=acc.usdt_balance, reason=reason, status="FILLED",
        ))
        db.commit()
        return {"qty": qty, "fee": fee, "realized_pnl": realized}
    finally:
        db.close()


def portfolio_summary(prices):
    """Build the full wallet snapshot. `prices` maps base asset -> current price."""
    db = SessionLocal()
    try:
        acc = _get_account(db)
        positions = db.query(Position).filter(Position.quantity > 0).all()

        balances = {"USDT": acc.usdt_balance}
        holdings = []
        positions_value = 0.0
        unrealized = 0.0

        for p in positions:
            base = p.symbol.replace("USDT", "")
            price = prices.get(base, 0.0) or 0.0
            value = p.quantity * price
            u = (price - p.avg_entry_price) * p.quantity
            positions_value += value
            unrealized += u
            balances[base] = p.quantity
            holdings.append({
                "symbol": p.symbol,
                "base": base,
                "quantity": p.quantity,
                "avg_entry_price": p.avg_entry_price,
                "current_price": price,
                "value": value,
                "unrealized_pnl": u,
                "unrealized_pnl_pct": ((price - p.avg_entry_price) / p.avg_entry_price * 100)
                                      if p.avg_entry_price else 0.0,
            })

        realized_total = db.query(func.coalesce(func.sum(Trade.realized_pnl), 0.0)).scalar() or 0.0
        equity = acc.usdt_balance + positions_value
        total_pnl = equity - acc.starting_balance
        total_pnl_pct = (total_pnl / acc.starting_balance * 100) if acc.starting_balance else 0.0

        return {
            "balances": balances,
            "cash": acc.usdt_balance,
            "positions_value": positions_value,
            "total_equity": equity,
            "unrealized_pnl": unrealized,
            "realized_pnl": realized_total,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "starting_balance": acc.starting_balance,
            "holdings": holdings,
        }
    finally:
        db.close()


def get_recent_trades(symbol=None, limit=20):
    """Return recent trades (newest first) as plain dicts."""
    db = SessionLocal()
    try:
        q = db.query(Trade)
        if symbol:
            q = q.filter(Trade.symbol == symbol)
        rows = q.order_by(Trade.timestamp.desc()).limit(limit).all()
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
    """Reset the wallet back to the starting balance and flatten all positions."""
    db = SessionLocal()
    try:
        db.query(Position).delete()
        if clear_trades:
            db.query(Trade).delete()
        acc = _get_account(db)
        acc.usdt_balance = STARTING_BALANCE
        acc.starting_balance = STARTING_BALANCE
        acc.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "reset", "usdt_balance": STARTING_BALANCE}
    finally:
        db.close()
