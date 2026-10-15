"""Manual-trade desk for Robinhood Chain meme tokens.

Fully isolated from Strategy #4 (Solana) and Binance desks.
Manages the `robinhood_position` table, converts user-provided MCap targets into
price targets based on real-time market cap ratios, and monitors TP/SL auto-exits.
"""
import re
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from database import SessionLocal, engine, Base
from models import RobinhoodPosition
import robinhood_config as cfg
import robinhood_live as live

_ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _valid_address(address):
    return bool(address and _ETH_ADDR_RE.match(address.strip()))


def ensure_initialized():
    """Create the robinhood_position table if it does not already exist."""
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
    except Exception as e:
        print(f"[robinhood-desk] ensure_initialized warning: {e}")


def _active_count(db):
    return db.query(RobinhoodPosition).filter(
        RobinhoodPosition.status.in_(["pending", "open"])
    ).count()


def active_count():
    db = SessionLocal()
    try:
        return _active_count(db)
    finally:
        db.close()


def _row_public(p):
    """Serialize a Robinhood position for the frontend API."""
    cur_price = p.last_price or p.entry_price or 0.0
    entry_price = p.entry_price or 0.0

    return_pct = 0.0
    if entry_price > 0 and cur_price > 0:
        return_pct = ((cur_price / entry_price) - 1.0) * 100.0

    unrealized_pnl = 0.0
    if p.status == "open" and entry_price > 0 and cur_price > 0:
        unrealized_pnl = (cur_price - entry_price) * (p.qty or 0.0)

    realized_pct = 0.0
    if p.status == "closed" and entry_price > 0 and (p.exit_price or 0) > 0:
        realized_pct = (((p.exit_price / entry_price) - 1.0) * 100.0)

    return {
        "id": str(p.id),
        "source": p.source,
        "mode": p.mode,
        "token_address": p.token_address,
        "symbol": p.symbol or "",
        "status": p.status,
        "amount_usd": p.amount_usd,
        "auto_sell": p.auto_sell,
        "qty": p.qty,
        "entry_price": p.entry_price,
        "last_price": p.last_price,
        "buy_target_price": p.buy_target_price,
        "tp_price": p.tp_price,
        "sl_price": p.sl_price,
        "return_pct": return_pct,
        "unrealized_pnl": unrealized_pnl,
        "exit_price": p.exit_price,
        "realized_pnl": p.realized_pnl,
        "realized_pct": realized_pct,
        "exit_reason": p.exit_reason,
        "tx_hash_buy": p.tx_hash_buy,
        "tx_hash_sell": p.tx_hash_sell,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "closed_at": p.updated_at.isoformat() if (p.status == "closed" and p.updated_at) else None,
    }


def create_position(token_address, amount_usd, buy_mcap=None, tp_mcap=None, sl_mcap=None, auto_sell=True):
    """Opens a Robinhood Chain position (Market Now or Limit Buy)."""
    token_address = (token_address or "").strip()
    if not _valid_address(token_address):
        return {"error": "Invalid EVM contract address (must start with 0x and be 42 characters)."}

    try:
        amount_usd = float(amount_usd)
    except (TypeError, ValueError):
        return {"error": "Invalid amount."}

    if amount_usd <= 0:
        return {"error": "Amount must be greater than 0."}

    # Fetch real-time token info
    info = live.get_token_market_info(token_address)
    cur_price = info.get("price") or 0.0
    cur_mcap = info.get("mcap") or 0.0
    symbol = info.get("symbol") or token_address[:6]

    if cur_price <= 0:
        return {"error": "Could not fetch current market price for this token. Verify liquidity."}

    # Convert MCap targets to price targets dynamically based on current market ratio
    # price = target_mcap * (cur_price / cur_mcap)
    mcap_ratio = (cur_price / cur_mcap) if cur_mcap > 0 else 1.0

    def _to_price(mcap_val):
        if mcap_val in (None, ""):
            return None
        v = float(mcap_val)
        return (v * mcap_ratio) if cur_mcap > 0 else (v / 1_000_000_000)

    buy_target_price = _to_price(buy_mcap)
    tp_price = _to_price(tp_mcap)
    sl_price = _to_price(sl_mcap)

    ref_price = buy_target_price if buy_target_price is not None else cur_price
    if sl_price is not None and sl_price >= ref_price:
        return {"error": "Stop-loss must be strictly BELOW the entry price."}
    if tp_price is not None and tp_price <= ref_price:
        return {"error": "Take-profit must be strictly ABOVE the entry price."}

    db = SessionLocal()
    try:
        if _active_count(db) >= cfg.ROBINHOOD_MAX_POSITIONS:
            return {"error": f"Up to {cfg.ROBINHOOD_MAX_POSITIONS} concurrent positions allowed."}

        now = datetime.utcnow()
        pos = RobinhoodPosition(
            source="robinhood",
            mode="paper" if not cfg.ROBINHOOD_LIVE_ENABLED else ("dry_run" if cfg.ROBINHOOD_LIVE_DRYRUN else "live"),
            token_address=token_address,
            symbol=symbol,
            status="pending",
            amount_usd=amount_usd,
            buy_target_price=buy_target_price,
            tp_price=tp_price,
            sl_price=sl_price,
            auto_sell=bool(auto_sell),
            qty=0.0,
            entry_price=0.0,
            last_price=cur_price,
            peak_price=0.0,
            realized_pnl=0.0,
            created_at=now,
            updated_at=now,
        )
        db.add(pos)
        db.flush()

        # ── Limit Buy ────────────────────────────────────────────────────────
        if buy_target_price is not None:
            db.commit()
            return {
                "success": True,
                "status": "pending",
                "position_id": str(pos.id),
                "token_address": token_address,
                "symbol": symbol,
                "buy_target_price": buy_target_price,
                "tp_price": tp_price,
                "sl_price": sl_price,
            }

        # ── Immediate Market Buy ─────────────────────────────────────────────
        fill = live.execute_buy(token_address, amount_usd)
        if not fill or fill.get("error"):
            db.rollback()
            return {"error": fill.get("error") if fill else "Execution failed."}

        fill_price = fill.get("fill_price") or cur_price
        qty = fill.get("qty") or (amount_usd / fill_price)

        pos.status = "open"
        pos.mode = fill.get("mode") or "paper"
        pos.entry_price = fill_price
        pos.last_price = fill_price
        pos.peak_price = fill_price
        pos.qty = qty
        pos.tx_hash_buy = fill.get("tx_hash")
        pos.filled_at = now
        pos.updated_at = now
        db.commit()

        return {
            "success": True,
            "status": "open",
            "position_id": str(pos.id),
            "token_address": token_address,
            "symbol": symbol,
            "entry_price": fill_price,
            "mode": pos.mode,
            "tx_hash": pos.tx_hash_buy,
        }
    except SQLAlchemyError as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


def monitor():
    """Background monitor for Robinhood Chain positions (TP/SL exits & limit fills)."""
    db = SessionLocal()
    try:
        rows = db.query(RobinhoodPosition).filter(
            RobinhoodPosition.status.in_(["pending", "open"])
        ).all()
        if not rows:
            return

        for pos in rows:
            info = live.get_token_market_info(pos.token_address)
            price = info.get("price") or 0.0
            if price <= 0:
                continue

            pos.last_price = price
            now = datetime.utcnow()

            # Pending limit buy check
            if pos.status == "pending":
                if pos.buy_target_price and price <= pos.buy_target_price:
                    fill = live.execute_buy(pos.token_address, pos.amount_usd)
                    if fill and not fill.get("error"):
                        pos.status = "open"
                        pos.mode = fill.get("mode") or "paper"
                        pos.entry_price = fill.get("fill_price") or price
                        pos.qty = fill.get("qty") or (pos.amount_usd / pos.entry_price)
                        pos.peak_price = pos.entry_price
                        pos.tx_hash_buy = fill.get("tx_hash")
                        pos.filled_at = now
                pos.updated_at = now
                continue

            # Open position check
            if price > (pos.peak_price or pos.entry_price or 0.0):
                pos.peak_price = price
            pos.updated_at = now

            if not pos.auto_sell:
                continue

            entry = pos.entry_price or 0.0
            if pos.tp_price and pos.tp_price > entry and price >= pos.tp_price:
                _exit(db, pos, price, "take_profit")
            elif pos.sl_price and pos.sl_price < entry and price <= pos.sl_price:
                _exit(db, pos, price, "stop_loss")

        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        print(f"[robinhood-desk] monitor error: {e}")
    finally:
        db.close()


def _exit(db, pos, price, reason):
    """Executes position exit and updates database record."""
    fill = live.execute_sell(pos.token_address, pos.qty)
    if not fill or fill.get("error"):
        return False

    exit_price = fill.get("fill_price") or price
    proceeds = fill.get("proceeds_usd") or (pos.qty * exit_price)
    realized = proceeds - (pos.amount_usd or 0.0)

    now = datetime.utcnow()
    pos.status = "closed"
    pos.exit_price = exit_price
    pos.last_price = exit_price
    pos.realized_pnl = realized
    pos.exit_reason = reason
    pos.tx_hash_sell = fill.get("tx_hash")
    pos.updated_at = now
    return True


def manual_sell(position_id):
    """Closes an open position or cancels a pending limit order on user request."""
    db = SessionLocal()
    try:
        pos = db.query(RobinhoodPosition).filter(RobinhoodPosition.id == position_id).first()
        if not pos:
            return {"ok": False, "error": "Position not found"}

        if pos.status == "pending":
            pos.status = "closed"
            pos.exit_reason = "cancelled"
            pos.updated_at = datetime.utcnow()
            db.commit()
            return {"ok": True, "status": "cancelled"}

        if pos.status == "open":
            info = live.get_token_market_info(pos.token_address)
            price = info.get("price") or pos.last_price or pos.entry_price
            success = _exit(db, pos, price, "manual")
            if not success:
                return {"ok": False, "error": "Exit execution failed."}
            db.commit()
            return {"ok": True, "status": "closed", "tx_signature": pos.tx_hash_sell}

        return {"ok": False, "error": f"Position already {pos.status}"}
    finally:
        db.close()


def update_targets(position_id, tp_mcap=None, sl_mcap=None):
    """Updates TP and SL targets for an open position."""
    db = SessionLocal()
    try:
        pos = db.query(RobinhoodPosition).filter(RobinhoodPosition.id == position_id).first()
        if not pos:
            return {"ok": False, "error": "Position not found"}

        info = live.get_token_market_info(pos.token_address)
        cur_price = info.get("price") or pos.entry_price or 0.0
        cur_mcap = info.get("mcap") or 0.0
        mcap_ratio = (cur_price / cur_mcap) if cur_mcap > 0 else 1.0

        def _to_price(mcap_val):
            if mcap_val in (None, ""):
                return None
            v = float(mcap_val)
            return (v * mcap_ratio) if cur_mcap > 0 else (v / 1_000_000_000)

        tp_price = _to_price(tp_mcap)
        sl_price = _to_price(sl_mcap)

        entry = pos.entry_price or 0.0
        if sl_price is not None and sl_price >= entry:
            return {"ok": False, "error": "Stop-loss must be strictly BELOW entry price."}
        if tp_price is not None and tp_price <= entry:
            return {"ok": False, "error": "Take-profit must be strictly ABOVE entry price."}

        pos.tp_price = tp_price
        pos.sl_price = sl_price
        pos.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True}
    finally:
        db.close()


def get_positions(status_filter="active", limit=100):
    db = SessionLocal()
    try:
        q = db.query(RobinhoodPosition)
        if status_filter == "active":
            q = q.filter(RobinhoodPosition.status.in_(["pending", "open"]))
        elif status_filter:
            q = q.filter(RobinhoodPosition.status == status_filter)
        rows = q.order_by(RobinhoodPosition.created_at.desc()).limit(limit).all()
        return [_row_public(p) for p in rows]
    finally:
        db.close()


def status():
    pf = live.preflight()
    return {
        "active_count": active_count(),
        "max_positions": cfg.ROBINHOOD_MAX_POSITIONS,
        "mode": pf["mode"],
        "live_enabled": pf["live_enabled"],
        "dry_run": pf["dry_run"],
    }


def token_info(address):
    address = (address or "").strip()
    if not _valid_address(address):
        return {"error": "Invalid EVM address."}
    info = live.get_token_market_info(address)
    return {
        "address": address,
        "symbol": info.get("symbol") or "",
        "price": info.get("price") or 0.0,
        "mcap": info.get("mcap") or 0.0,
        "liquidity_usd": info.get("liquidity_usd") or 0.0,
    }
