"""Live on-chain execution seam (Jupiter swaps) — STUBBED for future use.

Strategy #3 runs fully simulated for now. This module is the single place real
execution will live, so the rest of the system already calls into a stable
interface (`execute_buy` / `execute_sell`). Until LIVE_TRADING_ENABLED is set and
this is implemented, `sniper_engine` never imports it for a real fill.

To go live later (do NOT enable until sim is proven for >= 1 week):
  1. pip install solders cryptography
  2. Store a Fernet-encrypted Solana keypair; set WALLET_ENCRYPTION_KEY.
  3. Implement the Jupiter quote -> swap-tx -> sign -> send -> confirm flow below.
  4. Set LIVE_TRADING_ENABLED=true and start with a tiny position_size.

The functions return {"confirmed": bool, "tx_hash": str, "fill_price": float}.
While stubbed they return confirmed=False so the engine safely declines the fill.
"""
import os

import sniper_config as cfg

WSOL_MINT = cfg.WSOL_MINT


def _not_ready(action, token_mint):
    print(f"[sniper.live] {action} requested for {token_mint[:8]} but live "
          f"execution is not implemented/enabled — declining (sim only).")
    return {"confirmed": False, "tx_hash": None, "fill_price": None}


def execute_buy(token_mint: str, usd_amount: float) -> dict:
    """BUY `usd_amount` of `token_mint` with SOL via Jupiter. Stubbed."""
    if not cfg.LIVE_TRADING_ENABLED:
        return _not_ready("BUY", token_mint)

    # ----- FUTURE IMPLEMENTATION SKETCH (kept for reference) -----
    # from cryptography.fernet import Fernet
    # from solders.keypair import Keypair
    # from solders.transaction import VersionedTransaction
    # import base64, requests, time
    # from sniper_macro import get_macro
    #
    # keypair = _load_keypair()
    # lamports = int((usd_amount / get_macro()["sol_price_usd"]) * 1e9)
    # quote = requests.get(cfg.JUPITER_QUOTE_URL, params={
    #     "inputMint": WSOL_MINT, "outputMint": token_mint,
    #     "amount": lamports, "slippageBps": 500}).json()
    # if float(quote.get("priceImpactPct", 0)) > 5:
    #     return {"confirmed": False, "tx_hash": None, "fill_price": None}
    # swap = requests.post(cfg.JUPITER_SWAP_URL, json={
    #     "quoteResponse": quote, "userPublicKey": str(keypair.pubkey()),
    #     "wrapAndUnwrapSol": True}).json()
    # tx = VersionedTransaction.from_bytes(base64.b64decode(swap["swapTransaction"]))
    # tx.sign([keypair])
    # sig = _send_and_confirm(tx)
    # fill_price = _derive_fill_price(quote)
    # return {"confirmed": bool(sig), "tx_hash": sig, "fill_price": fill_price}
    return _not_ready("BUY", token_mint)


def execute_sell(token_mint: str, qty: float) -> dict:
    """SELL `qty` of `token_mint` for SOL via Jupiter. Stubbed."""
    if not cfg.LIVE_TRADING_ENABLED:
        return _not_ready("SELL", token_mint)
    return _not_ready("SELL", token_mint)


def _load_keypair():
    """Decrypt the Solana keypair from env (Fernet). Implemented at go-live."""
    raise NotImplementedError("Live wallet not configured")
