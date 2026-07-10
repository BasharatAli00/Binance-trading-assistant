"""Manual-trade desk for Strategy #4 (Solana meme coins).

The copy-trade dashboard's "Manual Trade" tab lets a user hand-pick a token
mint, a USD size, and optional Buy / Take-Profit / Stop-Loss targets entered in
**Market Cap ($)**. This module:

  * converts MCap -> price ONCE, here, on request receipt (Pump.fun-style tokens
    have a fixed 1B supply), so everything downstream works purely in price;
  * reuses `copytrade_live.execute_buy` / `execute_sell` for real Jupiter
    routing/slippage/signing — it never re-implements swap logic;
  * tracks each position in its own table (`manual_sol_position`, tagged
    source="manual") so it's isolated from the automated copy-trade positions;
  * auto-exits open positions on TP/SL via a dedicated monitor driven each pass
    of the copy-trade loop — the copy-trade consensus watcher is NOT a price
    target watcher, so we run our own.

Execution respects the same two live switches as the rest of Strategy #4:
LIVE_TRADING_ENABLED (master) and LIVE_DRYRUN. With the master off, a manual buy
is rejected with a clear message rather than silently doing nothing.
"""
import re
from datetime import datetime

import requests
from sqlalchemy.exc import SQLAlchemyError

from database import SessionLocal, engine, Base
from models import ManualSolPosition
import copytrade_live

# Fixed-supply assumption for Pump.fun-style Solana meme tokens. If a token's
# real supply is not 1B this conversion is wrong (out of scope for v1 — see the
# feature spec). TODO(v1+): fetch actual on-chain supply and divide by that.
TOTAL_SUPPLY = 1_000_000_000
MAX_POSITIONS = 5                       # "Up to 5 concurrent positions" (pending + open)
DEXSCREENER_BASE = "https://api.dexscreener.com"

_S = requests.Session()


# ---- MCap <-> price ------------------------------------------------------

def mcap_to_price(mcap):
    """Convert a Market-Cap ($) to price (USD per token). None passes through."""
    if mcap in (None, ""):
        return None
    return float(mcap) / TOTAL_SUPPLY


# ---- Helpers -------------------------------------------------------------

_MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")   # base58, Solana mint length


def _valid_mint(mint):
    return bool(mint and _MINT_RE.match(mint.strip()))


def ensure_initialized():
    """Create the manual-desk table (idempotent)."""
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
    except Exception as e:
        print(f"[manual-sol] create_all warn: {e}")


def _token_info(mint):
    """Best-effort symbol + live price + liquidity for a mint from DexScreener.
    Returns {"symbol", "price", "liquidity_usd"} (price/liquidity 0 if unknown)."""
    try:
        r = _S.get(f"{DEXSCREENER_BASE}/latest/dex/tokens/{mint}", timeout=8)
        r.raise_for_status()
        pairs = r.json().get("pairs") or []
        if pairs:
            best = max(pairs, key=lambda p: (p.get("liquidity", {}).get("usd", 0) or 0))
            return {
                "symbol": (best.get("baseToken", {}) or {}).get("symbol") or "",
                "price": float(best.get("priceUsd", 0) or 0),
                "liquidity_usd": best.get("liquidity", {}).get("usd", 0) or 0,
            }
    except Exception as e:
        print(f"[manual-sol] token_info error for {mint[:8]}: {e}")
    return {"symbol": "", "price": 0.0, "liquidity_usd": 0.0}


def _active_count(db):
    return db.query(ManualSolPosition).filter(
        ManualSolPosition.status.in_(["pending", "open"])).count()


def active_count():
    db = SessionLocal()
    try:
        return _active_count(db)
    finally:
        db.close()


def _mode_of(fill):
    """Classify the execution mode from a copytrade_live fill dict."""
    return "dry_run" if fill.get("dry_run") else "live"


def _row_public(p):
    """Serialize a position for the API. MCap is recomputed from price, never stored."""
    return {
        "id": str(p.id),
        "source": p.source,
        "mode": p.mode,
        "mint": p.mint,
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
        # Display-only MCap views (recomputed, per the fixed-supply assumption).
        "entry_mcap": (p.entry_price or 0) * TOTAL_SUPPLY,
        "tp_mcap": (p.tp_price * TOTAL_SUPPLY) if p.tp_price else None,
        "sl_mcap": (p.sl_price * TOTAL_SUPPLY) if p.sl_price else None,
        "buy_target_mcap": (p.buy_target_price * TOTAL_SUPPLY) if p.buy_target_price else None,
        "tx_hash_buy": p.tx_hash_buy,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ---- Create --------------------------------------------------------------

def create_manual_position(token_mint, amount_usd, buy_mcap=None, tp_mcap=None,
                           sl_mcap=None, auto_sell=True):
    """Open a manual Solana position (market now, or a pending limit buy).

    MCap inputs are converted to price here and only price is persisted. Returns
    a result dict, or {"error": ...} on any rejection.
    """
    # ── Validate ────────────────────────────────────────────────────────────
    token_mint = (token_mint or "").strip()
    if not _valid_mint(token_mint):
        return {"error": "Invalid token mint address"}
    try:
        amount_usd = float(amount_usd)
    except (TypeError, ValueError):
        return {"error": "Invalid amount"}
    if amount_usd <= 0:
        return {"error": "Amount must be greater than 0"}

    # MCap -> price (once, here). Reject non-positive MCap inputs.
    for label, val in (("Buy", buy_mcap), ("TP", tp_mcap), ("SL", sl_mcap)):
        if val not in (None, "") and float(val) <= 0:
            return {"error": f"{label} MCap must be greater than 0"}
    buy_target_price = mcap_to_price(buy_mcap)
    tp_price = mcap_to_price(tp_mcap)
    sl_price = mcap_to_price(sl_mcap)

    db = SessionLocal()
    try:
        # ── Enforce the 5-position cap server-side (recount at request time) ─
        if _active_count(db) >= MAX_POSITIONS:
            return {"error": f"Up to {MAX_POSITIONS} concurrent positions — close one to open another."}

        info = _token_info(token_mint)
        symbol = info["symbol"] or token_mint[:6]
        now = datetime.utcnow()

        pos = ManualSolPosition(
            source="manual", mode="sim", mint=token_mint, symbol=symbol,
            status="pending", amount_usd=amount_usd,
            buy_target_price=buy_target_price, tp_price=tp_price, sl_price=sl_price,
            auto_sell=bool(auto_sell), qty=0.0, entry_price=0.0,
            last_price=info["price"] or 0.0, peak_price=0.0, realized_pnl=0.0,
            created_at=now, updated_at=now,
        )
        db.add(pos)
        db.flush()   # assign pos.id

        # ── Limit buy: leave pending; the monitor fires it when price crosses ─
        if buy_target_price is not None:
            db.commit()
            return {
                "success": True, "status": "pending", "position_id": str(pos.id),
                "token_mint": token_mint, "symbol": symbol,
                "buy_target_price": buy_target_price, "tp_price": tp_price,
                "sl_price": sl_price, "entry_price": None, "tx_signature": None,
            }

        # ── Market buy now via the live pipeline ────────────────────────────
        fill = copytrade_live.execute_buy(token_mint, amount_usd)
        if fill is None:
            db.rollback()
            return {"error": "Live trading is OFF — enable the master switch (dry-run is fine) to place manual trades."}
        if fill.get("skipped"):
            db.rollback()
            return {"error": f"Trade skipped: {fill['skipped']}"}
        if not fill.get("confirmed"):
            db.rollback()
            return {"error": "Swap failed to confirm on-chain — try again."}

        price = fill.get("fill_price") or info["price"] or 0.0
        qty = fill.get("qty") or 0.0
        if price <= 0 or qty <= 0:
            db.rollback()
            return {"error": "Could not determine a fill price — try again."}

        pos.status = "open"
        pos.mode = _mode_of(fill)
        pos.entry_price = price
        pos.last_price = price
        pos.peak_price = price
        pos.qty = qty
        pos.tx_hash_buy = fill.get("tx_hash")   # None in dry-run
        pos.filled_at = now
        pos.updated_at = now
        db.commit()

        return {
            "success": True, "status": "open", "position_id": str(pos.id),
            "token_mint": token_mint, "symbol": symbol, "entry_price": price,
            "tx_signature": pos.tx_hash_buy,
            "buy_target_price": None, "tp_price": tp_price, "sl_price": sl_price,
        }
    except SQLAlchemyError as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


# ---- Monitor (loop-driven) ----------------------------------------------

def monitor():
    """Fill pending limit buys and auto-exit open positions on TP/SL.

    Called each pass of the copy-trade loop. Prices come from DexScreener via
    `sniper_data.latest_marks` (same source the copy-trade exit poll uses).
    """
    import sniper_data
    db = SessionLocal()
    try:
        rows = db.query(ManualSolPosition).filter(
            ManualSolPosition.status.in_(["pending", "open"])).all()
        if not rows:
            return
        marks = sniper_data.latest_marks(list({p.mint for p in rows}))
        for pos in rows:
            m = marks.get(pos.mint) or {}
            price = m.get("price") or sniper_data.latest_price(pos.mint)
            if not price or price <= 0:
                continue

            if pos.status == "pending":
                # Buy limit fills once the market trades at or below the target.
                if pos.buy_target_price is not None and price <= pos.buy_target_price:
                    _fill_pending(pos, price)
                pos.last_price = price
                pos.updated_at = datetime.utcnow()
                continue

            # open — mark + check TP/SL (only if auto_sell was requested)
            pos.last_price = price
            if price > (pos.peak_price or pos.entry_price or 0):
                pos.peak_price = price
            pos.updated_at = datetime.utcnow()
            if not pos.auto_sell:
                continue
            if pos.tp_price and price >= pos.tp_price:
                _exit(db, pos, price, "take_profit")
            elif pos.sl_price and price <= pos.sl_price:
                _exit(db, pos, price, "stop_loss")

        db.commit()   # persist price marks + any fills/exits
    except SQLAlchemyError as e:
        db.rollback()
        print(f"[manual-sol] monitor error: {e}")
    finally:
        db.close()


def _fill_pending(pos, price):
    """Turn a pending limit order into an open position via a market buy now."""
    fill = copytrade_live.execute_buy(pos.mint, pos.amount_usd)
    if not fill or fill.get("skipped") or not fill.get("confirmed"):
        # Leave it pending; try again next pass (route may recover / live may be off).
        return False
    fill_price = fill.get("fill_price") or price
    qty = fill.get("qty") or 0.0
    if fill_price <= 0 or qty <= 0:
        return False
    now = datetime.utcnow()
    pos.status = "open"
    pos.mode = _mode_of(fill)
    pos.entry_price = fill_price
    pos.last_price = fill_price
    pos.peak_price = fill_price
    pos.qty = qty
    pos.tx_hash_buy = fill.get("tx_hash")
    pos.filled_at = now
    pos.updated_at = now
    print(f"[manual-sol] LIMIT FILLED {pos.symbol or pos.mint[:8]} @ {fill_price:.10f}")
    return True


def _exit(db, pos, price, reason):
    """Sell an open manual position at market via the live pipeline."""
    fill = copytrade_live.execute_sell(pos.mint, pos.qty)
    if not fill or not fill.get("confirmed"):
        return False   # keep the position; retry next pass
    exit_price = fill.get("fill_price") or price
    proceeds = fill.get("proceeds_usd")
    if proceeds is None:
        proceeds = pos.qty * exit_price
    realized = proceeds - (pos.amount_usd or 0.0)
    now = datetime.utcnow()
    pos.status = "closed"
    pos.exit_price = exit_price
    pos.last_price = exit_price
    pos.realized_pnl = realized
    pos.exit_reason = reason
    pos.tx_hash_sell = fill.get("tx_hash")
    pos.updated_at = now
    print(f"[manual-sol] {reason.upper()} {pos.symbol or pos.mint[:8]} "
          f"@ {exit_price:.10f} | P&L ${realized:.2f}")
    return True


# ---- Reads (API) ---------------------------------------------------------

def status():
    """Active count + cap for the "X/5 active" badge and server-side enforcement."""
    return {"active_count": active_count(), "max_positions": MAX_POSITIONS}


def get_positions(status_filter="open", limit=100):
    db = SessionLocal()
    try:
        q = db.query(ManualSolPosition)
        if status_filter == "active":
            q = q.filter(ManualSolPosition.status.in_(["pending", "open"]))
        elif status_filter:
            q = q.filter(ManualSolPosition.status == status_filter)
        rows = q.order_by(ManualSolPosition.created_at.desc()).limit(limit).all()
        return [_row_public(p) for p in rows]
    finally:
        db.close()
