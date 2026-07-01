"""LIVE execution for Strategy #4 via Jupiter (free/keyless tier).

REAL MONEY. Every entry point is hard-gated by LIVE_TRADING_ENABLED — if the
master switch is off, these return None / a safe status and never touch the chain.

Flow for a real trade:
  quote (Jupiter) -> build swap tx (Jupiter) -> sign (solana_wallet) -> send ->
  confirm -> report the actual fill back to the engine.

Untested on-chain in this environment by design; validate with ONE tiny funded
trade before trusting it (see preflight()).
"""
import requests

import copytrade_config as cfg
import solana_wallet as wallet


def _guarded():
    return bool(cfg.LIVE_TRADING_ENABLED and cfg.SOLANA_PRIVATE_KEY)


def preflight():
    """Read-only health check — NEVER trades. Safe to call anytime/from the UI.

    Shows the wallet's live SOL balance using the loaded key's address if a key
    is set, otherwise the configured public address (balance is public info, so
    no private key is needed just to display it)."""
    out = {
        "live_enabled": cfg.LIVE_TRADING_ENABLED,
        "key_present": bool(cfg.SOLANA_PRIVATE_KEY),
        "expected_wallet": cfg.LIVE_TRADING_WALLET,
        "address": None, "pubkey": None, "wallet_matches": None,
        "sol_balance": None, "min_sol_required": cfg.LIVE_MIN_SOL_BALANCE,
        "ready": False, "error": None,
    }
    try:
        if cfg.SOLANA_PRIVATE_KEY:
            out["pubkey"] = wallet.get_pubkey()
            out["wallet_matches"] = wallet.wallet_matches_expected()
        # Prefer the key's real address; fall back to the configured public one.
        addr = out["pubkey"] or cfg.LIVE_TRADING_WALLET or None
        out["address"] = addr
        if addr:
            out["sol_balance"] = wallet.get_sol_balance(addr)
        out["ready"] = bool(
            cfg.LIVE_TRADING_ENABLED and cfg.SOLANA_PRIVATE_KEY
            and out["wallet_matches"]
            and (out["sol_balance"] or 0) >= cfg.LIVE_MIN_SOL_BALANCE
        )
    except Exception as e:
        out["error"] = str(e)
    return out


def _sol_price_usd():
    try:
        r = requests.get(cfg.JUPITER_PRICE_URL, params={"ids": cfg.WSOL_MINT},
                         timeout=cfg.HTTP_TIMEOUT)
        r.raise_for_status()
        data = (r.json() or {}).get(cfg.WSOL_MINT) or {}
        price = float(data.get("usdPrice") or 0)
        return price or None
    except Exception:
        return None


def _quote(input_mint, output_mint, amount_base):
    r = requests.get(cfg.JUPITER_QUOTE_URL, params={
        "inputMint": input_mint, "outputMint": output_mint,
        "amount": int(amount_base), "slippageBps": cfg.LIVE_SLIPPAGE_BPS,
        "restrictIntermediateTokens": "true",
    }, timeout=cfg.HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _swap_tx(quote):
    r = requests.post(cfg.JUPITER_SWAP_URL, json={
        "quoteResponse": quote, "userPublicKey": wallet.get_pubkey(),
        "wrapAndUnwrapSol": True, "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": cfg.LIVE_PRIORITY_FEE_LAMPORTS,
    }, timeout=cfg.HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json().get("swapTransaction")


def execute_buy(mint, usd_amount):
    """Buy `usd_amount` of `mint` with SOL. Returns fill dict or None."""
    if not _guarded():
        return None
    try:
        sol_price = _sol_price_usd()
        if not sol_price:
            return None
        lamports_in = int(usd_amount / sol_price * 1e9)
        quote = _quote(cfg.WSOL_MINT, mint, lamports_in)
        tx = _swap_tx(quote)
        if not tx:
            return None
        sig = wallet.sign_and_send(tx)
        if not wallet.confirm(sig):
            return {"confirmed": False, "tx_hash": sig}

        decimals = wallet.token_decimals(mint)
        qty = int(quote.get("outAmount") or 0) / (10 ** decimals) if decimals >= 0 else 0
        fill_price = (usd_amount / qty) if qty else 0.0
        return {"confirmed": True, "tx_hash": sig, "qty": qty,
                "fill_price": fill_price, "spent_usd": usd_amount}
    except Exception as e:
        print(f"[copytrade-live] buy failed: {e}")
        return None


def execute_sell(mint, qty_tokens):
    """Sell `qty_tokens` of `mint` for SOL. Returns fill dict or None."""
    if not _guarded():
        return None
    try:
        sol_price = _sol_price_usd()
        if not sol_price:
            return None
        decimals = wallet.token_decimals(mint)
        amount_base = int(qty_tokens * (10 ** decimals))
        if amount_base <= 0:
            return None
        quote = _quote(mint, cfg.WSOL_MINT, amount_base)
        tx = _swap_tx(quote)
        if not tx:
            return None
        sig = wallet.sign_and_send(tx)
        if not wallet.confirm(sig):
            return {"confirmed": False, "tx_hash": sig}

        proceeds_sol = int(quote.get("outAmount") or 0) / 1e9
        proceeds_usd = proceeds_sol * sol_price
        fill_price = (proceeds_usd / qty_tokens) if qty_tokens else 0.0
        return {"confirmed": True, "tx_hash": sig, "proceeds_usd": proceeds_usd,
                "fill_price": fill_price}
    except Exception as e:
        print(f"[copytrade-live] sell failed: {e}")
        return None
