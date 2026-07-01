"""Helius integration for Strategy #4.

Three jobs:
  1. sync_watched_wallets() — pull the qualified wallets from the leaderboard
     (pump_top_gainer) into copy_watched_wallet, capped and deduped.
  2. ensure_webhook() — register/update ONE Helius webhook that watches those
     wallets for SWAP transactions and POSTs them to our public receiver.
  3. parse_webhook_payload() — turn an incoming Helius enhanced-transaction
     payload into normalized buy/sell events for the consensus detector.

The parser is isolated on purpose: the exact enhanced-tx shape / buy-sell
convention should be eyeballed against one real payload and tweaked here only.
"""
from datetime import datetime

import requests

from database import SessionLocal
from models import CopyWatchedWallet, PumpTopGainer
import copytrade_config as cfg


# --------------------------------------------------------------------------
# 1. Watched wallet list (from the qualified leaderboard)
# --------------------------------------------------------------------------
def sync_watched_wallets():
    """Rebuild copy_watched_wallet from the current leaderboard. Returns the
    list of watched wallet addresses."""
    db = SessionLocal()
    try:
        best = {}   # wallet -> (score, window, rank)
        for window in cfg.WATCH_FROM_WINDOWS:
            rows = db.query(PumpTopGainer).filter(
                PumpTopGainer.window == window
            ).order_by(PumpTopGainer.rank.asc()).all()
            for r in rows:
                cur = best.get(r.wallet_address)
                if cur is None or (r.score or 0) > cur[0]:
                    best[r.wallet_address] = (r.score or 0, window, r.rank)

        ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)
        ranked = ranked[: cfg.MAX_WATCHED_WALLETS]
        keep = {w for w, _ in ranked}

        now = datetime.utcnow()
        existing = {w.wallet: w for w in db.query(CopyWatchedWallet).all()}
        for wallet, (score, window, rank) in ranked:
            row = existing.get(wallet)
            if row:
                row.source_window, row.rank, row.score, row.last_synced = window, rank, score, now
            else:
                db.add(CopyWatchedWallet(wallet=wallet, source_window=window, rank=rank,
                                         score=score, added_at=now, last_synced=now))
        # Drop wallets that no longer qualify.
        for wallet, row in existing.items():
            if wallet not in keep:
                db.delete(row)
        db.commit()
        return sorted(keep)
    finally:
        db.close()


def get_watched_wallets():
    db = SessionLocal()
    try:
        return [w.wallet for w in db.query(CopyWatchedWallet).all()]
    finally:
        db.close()


# --------------------------------------------------------------------------
# 2. Helius webhook registration
# --------------------------------------------------------------------------
def _api(path):
    return f"{cfg.HELIUS_API_BASE}{path}?api-key={cfg.HELIUS_API_KEY}"


def ensure_webhook(wallets):
    """Create or update the single webhook that watches `wallets`. No-op if
    Helius isn't fully configured. Returns the webhook id or None."""
    if not (cfg.HELIUS_API_KEY and cfg.HELIUS_WEBHOOK_URL):
        print("[copytrade] Helius not fully configured — skipping webhook sync")
        return None
    if not wallets:
        return None

    body = {
        "webhookURL": cfg.HELIUS_WEBHOOK_URL,
        "transactionTypes": ["SWAP"],
        "accountAddresses": wallets,
        "webhookType": "enhanced",
    }
    if cfg.HELIUS_WEBHOOK_SECRET:
        body["authHeader"] = cfg.HELIUS_WEBHOOK_SECRET

    try:
        existing = requests.get(_api("/v0/webhooks"), timeout=cfg.HTTP_TIMEOUT)
        existing.raise_for_status()
        mine = next((w for w in existing.json()
                     if w.get("webhookURL") == cfg.HELIUS_WEBHOOK_URL), None)
        if mine:
            r = requests.put(_api(f"/v0/webhooks/{mine['webhookID']}"),
                             json=body, timeout=cfg.HTTP_TIMEOUT)
        else:
            r = requests.post(_api("/v0/webhooks"), json=body, timeout=cfg.HTTP_TIMEOUT)
        r.raise_for_status()
        wid = r.json().get("webhookID")
        print(f"[copytrade] Helius webhook synced ({len(wallets)} wallets) id={wid}")
        return wid
    except Exception as e:
        print(f"[copytrade] Helius webhook sync failed: {e}")
        return None


# --------------------------------------------------------------------------
# 3. Parse incoming enhanced-transaction payloads
# --------------------------------------------------------------------------
def parse_webhook_payload(payload, watched_set):
    """Helius enhanced-tx payload (a list of txs) -> normalized event dicts.

    A watched wallet BUYS a token when it spends SOL and receives that token;
    SELLS when it sends the token and receives SOL. Only pump.fun/PumpSwap-ish
    SOL-denominated swaps are kept.
    """
    if isinstance(payload, dict):
        payload = [payload]
    events = []
    for tx in payload or []:
        ev = _parse_tx(tx, watched_set)
        if ev:
            events.append(ev)
    return events


def _parse_tx(tx, watched_set):
    wallet = tx.get("feePayer")
    if not wallet or (watched_set and wallet not in watched_set):
        return None
    swap = (tx.get("events") or {}).get("swap")
    if not swap:
        return None

    sig = tx.get("signature")
    ts = tx.get("timestamp")
    block_time = datetime.utcfromtimestamp(ts) if ts else datetime.utcnow()

    native_in = _lamports(swap.get("nativeInput"))    # SOL the wallet spent
    native_out = _lamports(swap.get("nativeOutput"))  # SOL the wallet received

    def _non_sol(entries):
        for e in entries or []:
            mint = e.get("mint")
            if mint and mint != cfg.WSOL_MINT:
                return mint
        return None

    token_bought = _non_sol(swap.get("tokenOutputs"))  # tokens received
    token_sold = _non_sol(swap.get("tokenInputs"))     # tokens sent

    if native_in > 0 and token_bought:
        return _event(wallet, token_bought, "buy", native_in, sig, block_time)
    if native_out > 0 and token_sold:
        return _event(wallet, token_sold, "sell", native_out, sig, block_time)
    return None


def _lamports(native):
    if not native:
        return 0.0
    amt = native.get("amount") if isinstance(native, dict) else native
    try:
        return float(amt) / 1e9
    except (TypeError, ValueError):
        return 0.0


def _event(wallet, mint, side, sol_amount, sig, block_time):
    return {"wallet": wallet, "mint": mint, "symbol": None, "side": side,
            "sol_amount": sol_amount, "price_usd": None, "signature": sig,
            "block_time": block_time}
