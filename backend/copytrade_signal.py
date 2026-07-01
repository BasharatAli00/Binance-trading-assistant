"""Consensus signal detection for Strategy #4.

Stores wallet buy/sell events and answers two questions the loop asks:
  * detect_consensus_buys() — which tokens did MIN_WALLETS+ distinct watched
    wallets BUY within the last CONSENSUS_WINDOW_MIN minutes? (the entry signal)
  * sellers_since() — which of a position's triggering wallets have SOLD since
    we entered? (feeds the mirror-sell exit)
"""
from datetime import datetime, timedelta

from database import SessionLocal
from models import CopyWalletEvent, CopySignal, CopyPosition
import copytrade_config as cfg


def record_events(events):
    """Persist a batch of wallet events (dedup by signature+wallet+mint+side)."""
    if not events:
        return 0
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        inserted = 0
        for e in events:
            sig = e.get("signature")
            exists = db.query(CopyWalletEvent.id).filter(
                CopyWalletEvent.signature == sig,
                CopyWalletEvent.wallet == e["wallet"],
                CopyWalletEvent.mint == e["mint"],
                CopyWalletEvent.side == e["side"],
            ).first() if sig else None
            if exists:
                continue
            db.add(CopyWalletEvent(
                wallet=e["wallet"], mint=e["mint"], symbol=e.get("symbol"),
                side=e["side"], sol_amount=e.get("sol_amount"),
                price_usd=e.get("price_usd"), signature=sig,
                block_time=e.get("block_time") or now, received_at=now,
            ))
            inserted += 1
        db.commit()
        return inserted
    finally:
        db.close()


def prune_old_events():
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=cfg.EVENT_RETENTION_HOURS)
        db.query(CopyWalletEvent).filter(CopyWalletEvent.block_time < cutoff).delete()
        db.commit()
    finally:
        db.close()


def detect_consensus_buys():
    """Return candidate signals: [{mint, symbol, wallets[], wallet_count,
    first_buy_time}] where MIN_WALLETS+ distinct wallets bought the mint within
    the window and no signal for that mint fired recently."""
    db = SessionLocal()
    try:
        window_start = datetime.utcnow() - timedelta(minutes=cfg.CONSENSUS_WINDOW_MIN)
        rows = db.query(CopyWalletEvent).filter(
            CopyWalletEvent.side == "buy",
            CopyWalletEvent.block_time >= window_start,
        ).all()

        by_mint = {}
        for r in rows:
            m = by_mint.setdefault(r.mint, {"wallets": {}, "symbol": None,
                                            "first": r.block_time})
            m["wallets"].setdefault(r.wallet, r.block_time)
            m["symbol"] = m["symbol"] or r.symbol
            if r.block_time and (m["first"] is None or r.block_time < m["first"]):
                m["first"] = r.block_time

        out = []
        for mint, m in by_mint.items():
            if len(m["wallets"]) < cfg.MIN_WALLETS:
                continue
            if _recent_signal(db, mint):
                continue
            out.append({
                "mint": mint, "symbol": m["symbol"],
                "wallets": sorted(m["wallets"].keys()),
                "wallet_count": len(m["wallets"]), "first_buy_time": m["first"],
            })
        return out
    finally:
        db.close()


def _recent_signal(db, mint):
    cutoff = datetime.utcnow() - timedelta(minutes=cfg.SIGNAL_COOLDOWN_MIN)
    return db.query(CopySignal.id).filter(
        CopySignal.mint == mint, CopySignal.fired_at >= cutoff).first() is not None


def record_signal(candidate, status, reason):
    db = SessionLocal()
    try:
        db.add(CopySignal(
            mint=candidate["mint"], symbol=candidate.get("symbol"),
            wallet_count=candidate["wallet_count"], wallets=candidate["wallets"],
            first_buy_time=candidate.get("first_buy_time"),
            fired_at=datetime.utcnow(), status=status, reason=reason,
        ))
        db.commit()
    finally:
        db.close()


def sellers_since(mint, since, trigger_wallets):
    """Which of `trigger_wallets` have a SELL event for `mint` since `since`."""
    if not trigger_wallets:
        return set()
    db = SessionLocal()
    try:
        rows = db.query(CopyWalletEvent.wallet).filter(
            CopyWalletEvent.mint == mint, CopyWalletEvent.side == "sell",
            CopyWalletEvent.block_time >= since,
            CopyWalletEvent.wallet.in_(list(trigger_wallets)),
        ).all()
        return {w for (w,) in rows}
    finally:
        db.close()
