"""Manual-trade desk for Robinhood Chain meme tokens.

Fully isolated from Strategy #4 (Solana) and Binance desks.
Manages the `robinhood_position` table, converts user-provided MCap targets into
price targets based on real-time market cap ratios, and monitors TP/SL auto-exits.
"""
import re
from datetime import datetime

from sqlalchemy import or_, text
from sqlalchemy.exc import SQLAlchemyError

from database import SessionLocal, engine, Base
from models import RobinhoodPosition
import robinhood_config as cfg
import robinhood_live as live

_ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _valid_address(address):
    return bool(address and _ETH_ADDR_RE.match(address.strip()))


def ensure_initialized():
    """Create the robinhood_position table if it does not already exist, and auto-migrate columns."""
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
    except Exception as e:
        print(f"[robinhood-desk] ensure_initialized warning: {e}")

    new_cols = [
        ("scale_in_enabled", "BOOLEAN DEFAULT FALSE"),
        ("add_count", "INTEGER DEFAULT 0"),
        ("max_adds", "INTEGER DEFAULT 2"),
        ("initial_amount_usd", "FLOAT"),
        ("initial_entry_price", "FLOAT"),
        ("tier1_pct", "FLOAT DEFAULT 5.0"),
        ("tier1_add_usd", "FLOAT DEFAULT 0.5"),
        ("tier2_pct", "FLOAT DEFAULT 10.0"),
        ("tier2_add_usd", "FLOAT DEFAULT 1.0"),
    ]
    try:
        with engine.connect() as conn:
            for col_name, col_type in new_cols:
                try:
                    conn.execute(text(f"ALTER TABLE robinhood_position ADD COLUMN IF NOT EXISTS {col_name} {col_type};"))
                    conn.commit()
                except Exception:
                    pass
    except Exception as e:
        print(f"[robinhood-desk] column migration warning: {e}")


def _mode_filter(q, mode):
    if not mode or mode == "all":
        return q
    if mode == "live":
        return q.filter(RobinhoodPosition.mode == "live")
    if mode in ("paper", "dry_run", "sim"):
        return q.filter(RobinhoodPosition.mode.in_(["paper", "dry_run"]))
    return q.filter(RobinhoodPosition.mode == mode)


def _active_count(db, mode=None):
    q = db.query(RobinhoodPosition).filter(
        RobinhoodPosition.status.in_(["pending", "open"])
    )
    if mode is None:
        target_mode = "live" if (cfg.ROBINHOOD_LIVE_ENABLED and not cfg.ROBINHOOD_LIVE_DRYRUN) else "paper"
        q = _mode_filter(q, target_mode)
    else:
        q = _mode_filter(q, mode)
    return q.count()


def active_count(mode=None):
    db = SessionLocal()
    try:
        return _active_count(db, mode=mode)
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
        "scale_in_enabled": bool(p.scale_in_enabled),
        "add_count": p.add_count or 0,
        "max_adds": p.max_adds or 2,
        "initial_amount_usd": p.initial_amount_usd or p.amount_usd,
        "initial_entry_price": p.initial_entry_price or p.entry_price,
        "tier1_pct": p.tier1_pct or 5.0,
        "tier1_add_usd": p.tier1_add_usd or 0.5,
        "tier2_pct": p.tier2_pct or 10.0,
        "tier2_add_usd": p.tier2_add_usd or 1.0,
    }


def create_position(token_address, amount_usd, buy_price=None, tp_price=None, sl_price=None,
                    auto_sell=True, buy_mcap=None, tp_mcap=None, sl_mcap=None,
                    scale_in_enabled=False, tier1_pct=5.0, tier1_add_usd=0.5,
                    tier2_pct=10.0, tier2_add_usd=1.0):
    """Opens a Robinhood Chain position (Market Now or Limit Buy).
    Direct price inputs (buy_price, tp_price, sl_price) are preferred.
    """
    raw_addr = (token_address or "").strip()
    clean_addr = live.clean_token_input(raw_addr)
    if not clean_addr:
        return {"error": "Invalid EVM contract address or Uniswap v4 Pool ID."}

    # Fetch real-time token info (resolves pool IDs to real token contract addresses)
    info = live.get_token_market_info(clean_addr)
    token_address = info.get("address") or clean_addr
    if not _valid_address(token_address):
        return {"error": "Could not resolve to a valid EVM contract address (must be 42 characters)."}

    try:
        amount_usd = float(amount_usd)
    except (TypeError, ValueError):
        return {"error": "Invalid amount."}

    if amount_usd <= 0:
        return {"error": "Amount must be greater than 0."}

    cur_price = info.get("price") or 0.0
    cur_mcap = info.get("mcap") or 0.0
    symbol = info.get("symbol") or token_address[:6]

    if cur_price <= 0:
        return {"error": "Could not fetch current market price for this token. Verify liquidity."}

    # Parse price targets directly; fallback to mcap conversion if only mcap given
    def _parse_target(pval, mcap_val):
        if pval not in (None, ""):
            try:
                v = float(pval)
                return v if v > 0 else None
            except (ValueError, TypeError):
                return None
        if mcap_val not in (None, ""):
            try:
                mv = float(mcap_val)
                mcap_ratio = (cur_price / cur_mcap) if cur_mcap > 0 else (1.0 / 1_000_000_000)
                return (mv * mcap_ratio) if mv > 0 else None
            except (ValueError, TypeError):
                return None
        return None

    buy_target_price = _parse_target(buy_price, buy_mcap)
    tp_target_price = _parse_target(tp_price, tp_mcap)
    sl_target_price = _parse_target(sl_price, sl_mcap)

    ref_price = buy_target_price if buy_target_price is not None else cur_price
    if sl_target_price is not None and sl_target_price >= ref_price:
        return {"error": f"Stop-loss (${sl_target_price:g}) must be strictly BELOW entry price (${ref_price:g})."}
    if tp_target_price is not None and tp_target_price <= ref_price:
        return {"error": f"Take-profit (${tp_target_price:g}) must be strictly ABOVE entry price (${ref_price:g})."}

    tp_price = tp_target_price
    sl_price = sl_target_price

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
            initial_amount_usd=amount_usd,
            buy_target_price=buy_target_price,
            tp_price=tp_price,
            sl_price=sl_price,
            auto_sell=bool(auto_sell),
            qty=0.0,
            entry_price=0.0,
            initial_entry_price=0.0,
            last_price=cur_price,
            peak_price=0.0,
            realized_pnl=0.0,
            scale_in_enabled=bool(scale_in_enabled),
            add_count=0,
            max_adds=2,
            tier1_pct=float(tier1_pct if tier1_pct is not None else 5.0),
            tier1_add_usd=float(tier1_add_usd if tier1_add_usd is not None else 0.5),
            tier2_pct=float(tier2_pct if tier2_pct is not None else 10.0),
            tier2_add_usd=float(tier2_add_usd if tier2_add_usd is not None else 1.0),
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
        pos.initial_entry_price = fill_price
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

            # ── Smart Momentum Pyramiding Check ──
            if pos.scale_in_enabled and (pos.add_count or 0) < (pos.max_adds or 2):
                anchor_price = pos.initial_entry_price or pos.entry_price or 0.0
                if anchor_price > 0:
                    t1_pct = pos.tier1_pct if pos.tier1_pct is not None else 5.0
                    t1_add = pos.tier1_add_usd if pos.tier1_add_usd is not None else 0.5
                    t2_pct = pos.tier2_pct if pos.tier2_pct is not None else 10.0
                    t2_add = pos.tier2_add_usd if pos.tier2_add_usd is not None else 1.0

                    # Tier 1 Add: at +5% gain -> add $0.50 & move SL to Breakeven
                    if (pos.add_count or 0) == 0 and price >= anchor_price * (1.0 + t1_pct / 100.0):
                        add_fill = live.execute_buy(pos.token_address, t1_add)
                        if add_fill and not add_fill.get("error"):
                            new_fill_price = add_fill.get("fill_price") or price
                            new_qty = add_fill.get("qty") or (t1_add / new_fill_price)
                            total_spent = (pos.amount_usd or 0.0) + t1_add
                            total_qty = (pos.qty or 0.0) + new_qty
                            pos.entry_price = (total_spent / total_qty) if total_qty > 0 else new_fill_price
                            pos.amount_usd = total_spent
                            pos.qty = total_qty
                            pos.add_count = 1
                            # Smart Trailing SL: lock in Breakeven on original entry
                            pos.sl_price = anchor_price
                            pos.updated_at = now
                            print(f"[robinhood-desk] SMART ADD #1 for {pos.symbol or pos.token_address[:6]}: "
                                  f"+${t1_add:.2f} @ ${price:.8f} | New avg: ${pos.entry_price:.8f} | "
                                  f"SL moved to Breakeven (${anchor_price:.8f})")

                    # Tier 2 Add: at +10% gain -> add $1.00 & move SL to +4% Profit
                    elif (pos.add_count or 0) == 1 and price >= anchor_price * (1.0 + t2_pct / 100.0):
                        add_fill = live.execute_buy(pos.token_address, t2_add)
                        if add_fill and not add_fill.get("error"):
                            new_fill_price = add_fill.get("fill_price") or price
                            new_qty = add_fill.get("qty") or (t2_add / new_fill_price)
                            total_spent = (pos.amount_usd or 0.0) + t2_add
                            total_qty = (pos.qty or 0.0) + new_qty
                            pos.entry_price = (total_spent / total_qty) if total_qty > 0 else new_fill_price
                            pos.amount_usd = total_spent
                            pos.qty = total_qty
                            pos.add_count = 2
                            # Smart Trailing SL: lock in +4% profit above anchor
                            pos.sl_price = anchor_price * 1.04
                            pos.updated_at = now
                            print(f"[robinhood-desk] SMART ADD #2 for {pos.symbol or pos.token_address[:6]}: "
                                  f"+${t2_add:.2f} @ ${price:.8f} | New avg: ${pos.entry_price:.8f} | "
                                  f"SL moved to +4% Profit (${pos.sl_price:.8f})")

            if not pos.auto_sell:
                continue

            if pos.tp_price and price >= pos.tp_price:
                ok, err = _exit(db, pos, price, "take_profit")
                if not ok:
                    print(f"[robinhood-desk] TP exit failed for {pos.symbol}: {err}")
            elif pos.sl_price and price <= pos.sl_price:
                ok, err = _exit(db, pos, price, "stop_loss")
                if not ok:
                    print(f"[robinhood-desk] SL exit failed for {pos.symbol}: {err}")

        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        print(f"[robinhood-desk] monitor error: {e}")
    finally:
        db.close()


def _exit(db, pos, price, reason):
    """Executes position exit and updates database record.
    Returns (True, None) on success, or (False, error_str) on failure.
    """
    fill = live.execute_sell(pos.token_address, pos.qty)
    if not fill or fill.get("error"):
        err = fill.get("error") if fill else "Execution returned empty result."
        print(f"[robinhood-desk] Exit failed for {pos.symbol} ({reason}): {err}")
        return False, err

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
    return True, None


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
            success, err_msg = _exit(db, pos, price, "manual")
            if not success:
                return {"ok": False, "error": err_msg or "Exit execution failed."}
            db.commit()
            return {"ok": True, "status": "closed", "tx_signature": pos.tx_hash_sell}

        return {"ok": False, "error": f"Position already {pos.status}"}
    finally:
        db.close()


def update_targets(position_id, tp_price=None, sl_price=None, tp_mcap=None, sl_mcap=None):
    """Updates TP and SL price targets for an open position."""
    db = SessionLocal()
    try:
        pos = db.query(RobinhoodPosition).filter(RobinhoodPosition.id == position_id).first()
        if not pos:
            return {"ok": False, "error": "Position not found"}

        info = live.get_token_market_info(pos.token_address)
        cur_price = info.get("price") or pos.entry_price or 0.0
        cur_mcap = info.get("mcap") or 0.0

        def _parse_target(pval, mcap_val):
            if pval not in (None, ""):
                try:
                    v = float(pval)
                    return v if v > 0 else None
                except (ValueError, TypeError):
                    return None
            if mcap_val not in (None, ""):
                try:
                    mv = float(mcap_val)
                    mcap_ratio = (cur_price / cur_mcap) if cur_mcap > 0 else (1.0 / 1_000_000_000)
                    return (mv * mcap_ratio) if mv > 0 else None
                except (ValueError, TypeError):
                    return None
            return None

        new_tp = _parse_target(tp_price, tp_mcap)
        new_sl = _parse_target(sl_price, sl_mcap)

        ref_price = cur_price if cur_price > 0 else (pos.entry_price or 0.0)
        if new_sl is not None and ref_price > 0 and new_sl >= ref_price:
            return {"ok": False, "error": f"Stop-loss (${new_sl:g}) must be below current market price (${ref_price:g})."}
        if new_tp is not None and ref_price > 0 and new_tp <= ref_price:
            return {"ok": False, "error": f"Take-profit (${new_tp:g}) must be above current market price (${ref_price:g})."}

        pos.tp_price = new_tp
        pos.sl_price = new_sl
        pos.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "tp_price": new_tp, "sl_price": new_sl}
    finally:
        db.close()


def get_positions(status_filter="active", limit=100, mode=None):
    db = SessionLocal()
    try:
        q = db.query(RobinhoodPosition)
        if status_filter == "active":
            q = q.filter(RobinhoodPosition.status.in_(["pending", "open"]))
        elif status_filter:
            q = q.filter(RobinhoodPosition.status == status_filter)

        if mode is None:
            target_mode = "live" if (cfg.ROBINHOOD_LIVE_ENABLED and not cfg.ROBINHOOD_LIVE_DRYRUN) else "paper"
            q = _mode_filter(q, target_mode)
        else:
            q = _mode_filter(q, mode)

        rows = q.order_by(RobinhoodPosition.created_at.desc()).limit(limit).all()
        return [_row_public(p) for p in rows]
    finally:
        db.close()


def get_desk_stats(mode=None):
    """Calculates aggregate performance metrics for Robinhood Chain trading desk.
    
    If mode is None, defaults to the current active desk mode ('live' or 'paper').
    Pass mode='all' to calculate combined metrics across both live and paper.
    """
    if mode is None:
        mode = "live" if (cfg.ROBINHOOD_LIVE_ENABLED and not cfg.ROBINHOOD_LIVE_DRYRUN) else "paper"

    db = SessionLocal()
    try:
        # Completed trades (exclude cancelled limit orders)
        q_closed = db.query(RobinhoodPosition).filter(
            RobinhoodPosition.status == "closed",
            or_(
                RobinhoodPosition.exit_reason.is_(None),
                RobinhoodPosition.exit_reason != "cancelled",
            ),
        )
        q_closed = _mode_filter(q_closed, mode)
        closed = q_closed.all()

        total_trades = len(closed)
        wins = sum(1 for p in closed if (p.realized_pnl or 0.0) > 0)
        losses = sum(1 for p in closed if (p.realized_pnl or 0.0) < 0)
        breakeven = total_trades - wins - losses
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
        realized_pnl = sum((p.realized_pnl or 0.0) for p in closed)

        # Open positions for live unrealized PnL
        q_open = db.query(RobinhoodPosition).filter(RobinhoodPosition.status == "open")
        q_open = _mode_filter(q_open, mode)
        open_rows = q_open.all()

        unrealized_pnl = 0.0
        for p in open_rows:
            entry = p.entry_price or 0.0
            cur = p.last_price or entry
            qty = p.qty or 0.0
            if entry > 0 and cur > 0 and qty > 0:
                unrealized_pnl += (cur - entry) * qty

        return {
            "mode": mode,
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate": round(win_rate, 2),
            "realized_pnl": round(realized_pnl, 4),
            "unrealized_pnl": round(unrealized_pnl, 4),
            "total_pnl": round(realized_pnl + unrealized_pnl, 4),
        }
    except Exception as e:
        print(f"[robinhood-desk] get_desk_stats error: {e}")
        return {
            "mode": mode or "all",
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "win_rate": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_pnl": 0.0,
        }
    finally:
        db.close()


def status():
    pf = live.preflight()
    current_mode = pf["mode"]
    s = get_desk_stats(mode=current_mode)
    return {
        "active_count": active_count(mode=current_mode),
        "max_positions": cfg.ROBINHOOD_MAX_POSITIONS,
        "mode": pf["mode"],
        "live_enabled": pf["live_enabled"],
        "dry_run": pf["dry_run"],
        "wallet_configured": pf.get("wallet_configured", False),
        "address": pf.get("address"),
        "eth_balance": pf.get("eth_balance"),
        "eth_balance_usd": pf.get("eth_balance_usd"),
        "ready": pf.get("ready", True),
        "total_trades": s["total_trades"],
        "wins": s["wins"],
        "losses": s["losses"],
        "win_rate": s["win_rate"],
        "realized_pnl": s["realized_pnl"],
        "unrealized_pnl": s["unrealized_pnl"],
        "total_pnl": s["total_pnl"],
        "stats": s,
    }


def token_info(address):
    clean_addr = live.clean_token_input(address)
    if not clean_addr:
        return {"error": "Invalid EVM contract address or Uniswap v4 Pool ID."}
    info = live.get_token_market_info(clean_addr)
    resolved_addr = info.get("address") or clean_addr
    return {
        "address": resolved_addr,
        "symbol": info.get("symbol") or "",
        "price": info.get("price") or 0.0,
        "mcap": info.get("mcap") or 0.0,
        "liquidity_usd": info.get("liquidity_usd") or 0.0,
        "is_pool_resolved": bool(info.get("is_pool_resolved")),
    }
