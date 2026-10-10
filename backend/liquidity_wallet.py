from datetime import datetime
from sqlalchemy import func
from database import SessionLocal, engine, Base
from models import LiquidityAccount, LiquidityPosition, LiquidityTrade

STARTING_BALANCE = 5000.0
FEE_RATE = 0.001

def ensure_initialized():
    Base.metadata.create_all(bind=engine, checkfirst=True)
    db = SessionLocal()
    try:
        if not db.query(LiquidityAccount).first():
            now = datetime.utcnow()
            db.add(LiquidityAccount(
                usdt_balance=STARTING_BALANCE,
                starting_balance=STARTING_BALANCE,
                created_at=now,
                updated_at=now,
            ))
            db.commit()
            print(f"[liquidity] Initialized isolated wallet with {STARTING_BALANCE} USDT")
    finally:
        db.close()

def _get_account(db):
    acc = db.query(LiquidityAccount).first()
    if not acc:
        now = datetime.utcnow()
        acc = LiquidityAccount(
            usdt_balance=STARTING_BALANCE,
            starting_balance=STARTING_BALANCE,
            created_at=now,
            updated_at=now,
        )
        db.add(acc)
        db.commit()
    return acc

def get_position(symbol):
    db = SessionLocal()
    try:
        p = db.query(LiquidityPosition).filter(LiquidityPosition.symbol == symbol).first()
        if not p or p.quantity <= 0: return None
        return {
            "symbol": p.symbol, "quantity": p.quantity, "avg_entry_price": p.avg_entry_price,
            "stop_price": p.stop_price, "init_stop": p.init_stop, "highest_price": p.highest_price,
        }
    finally:
        db.close()

def execute_buy(symbol, quote_usdt, price, reason="", stop=None):
    if quote_usdt <= 0 or price <= 0: return None
    db = SessionLocal()
    try:
        acc = _get_account(db)
        if acc.usdt_balance < quote_usdt: return None
        fee = quote_usdt * FEE_RATE
        qty = (quote_usdt - fee) / price
        acc.usdt_balance -= quote_usdt
        acc.updated_at = datetime.utcnow()

        pos = db.query(LiquidityPosition).filter(LiquidityPosition.symbol == symbol).first()
        if pos and pos.quantity > 0:
            total_cost = pos.avg_entry_price * pos.quantity + price * qty
            pos.quantity += qty
            pos.avg_entry_price = total_cost / pos.quantity
            pos.updated_at = datetime.utcnow()
            if stop is not None:
                pos.stop_price = stop
                pos.init_stop = stop
            pos.highest_price = max(pos.highest_price or price, price)
        elif pos:
            pos.quantity = qty
            pos.avg_entry_price = price
            pos.updated_at = datetime.utcnow()
            pos.stop_price = stop
            pos.init_stop = stop
            pos.highest_price = price
        else:
            db.add(LiquidityPosition(symbol=symbol, quantity=qty, avg_entry_price=price,
                            updated_at=datetime.utcnow(),
                            stop_price=stop, init_stop=stop, highest_price=price))

        db.add(LiquidityTrade(
            symbol=symbol, timestamp=datetime.utcnow(), side="BUY", price=price,
            quantity=qty, quote_amount=quote_usdt, fee=fee, realized_pnl=0.0,
            balance_after=acc.usdt_balance, reason=reason, status="FILLED",
        ))
        db.commit()
        return {"qty": qty, "fee": fee, "price": price}
    finally:
        db.close()

def execute_sell(symbol, qty, price, reason=""):
    if price <= 0: return None
    db = SessionLocal()
    try:
        pos = db.query(LiquidityPosition).filter(LiquidityPosition.symbol == symbol).first()
        if not pos or pos.quantity <= 0: return None
        qty = min(qty, pos.quantity)
        if qty <= 0: return None

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

        db.add(LiquidityTrade(
            symbol=symbol, timestamp=datetime.utcnow(), side="SELL", price=price,
            quantity=qty, quote_amount=proceeds, fee=fee, realized_pnl=realized,
            balance_after=acc.usdt_balance, reason=reason, status="FILLED",
        ))
        db.commit()
        return {"qty": qty, "fee": fee, "realized_pnl": realized}
    finally:
        db.close()

def portfolio_summary(prices):
    db = SessionLocal()
    try:
        acc = _get_account(db)
        positions = db.query(LiquidityPosition).filter(LiquidityPosition.quantity > 0).all()
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
                "symbol": p.symbol, "base": base, "quantity": p.quantity,
                "avg_entry_price": p.avg_entry_price, "current_price": price,
                "value": value, "unrealized_pnl": u,
                "unrealized_pnl_pct": ((price - p.avg_entry_price) / p.avg_entry_price * 100) if p.avg_entry_price else 0.0,
            })
        realized_total = db.query(func.coalesce(func.sum(LiquidityTrade.realized_pnl), 0.0)).scalar() or 0.0
        equity = acc.usdt_balance + positions_value
        total_pnl = equity - acc.starting_balance
        total_pnl_pct = (total_pnl / acc.starting_balance * 100) if acc.starting_balance else 0.0
        return {
            "balances": balances, "cash": acc.usdt_balance, "positions_value": positions_value,
            "total_equity": equity, "unrealized_pnl": unrealized, "realized_pnl": realized_total,
            "total_pnl": total_pnl, "total_pnl_pct": total_pnl_pct, "starting_balance": acc.starting_balance,
            "holdings": holdings,
        }
    finally:
        db.close()

def get_recent_trades(symbol=None, limit=20):
    db = SessionLocal()
    try:
        q = db.query(LiquidityTrade)
        if symbol: q = q.filter(LiquidityTrade.symbol == symbol)
        rows = q.order_by(LiquidityTrade.timestamp.desc()).limit(limit).all()
        return [{
            "timestamp": r.timestamp.strftime('%Y-%m-%d %H:%M:%S') if r.timestamp else "",
            "symbol": r.symbol, "side": r.side, "price": r.price, "quantity": r.quantity,
            "quote_amount": r.quote_amount, "fee": r.fee, "realized_pnl": r.realized_pnl, "reason": r.reason or "",
        } for r in rows]
    finally:
        db.close()
