"""LIVE execution for Strategy #4 via Jupiter (free/keyless tier).

Two deliberate switches stand between deployed and spending:
  * LIVE_TRADING_ENABLED (master)  — off => everything simulated.
  * LIVE_DRYRUN                     — on (default) => build the REAL Jupiter
    quote (to measure real slippage) but DO NOT send. Real money moves only
    when master is on AND dry-run is off.

Buys also pass a slippage/price-impact guard — if a $1 swap would move the
price more than LIVE_MAX_PRICE_IMPACT_PCT, we skip (pool too thin).

Flow: quote (Jupiter) -> slippage check -> [dry-run: stop here with real fill
numbers] / [real: build swap -> sign -> send -> confirm] -> report the fill.
"""
import requests

import copytrade_config as cfg
import solana_wallet as wallet


def _guarded():
    return bool(cfg.LIVE_TRADING_ENABLED and cfg.SOLANA_PRIVATE_KEY)


def preflight():
    """Read-only health check — NEVER trades. Shows real on-chain balance +
    an estimate of how many live trades of runway remain."""
    out = {
        "live_enabled": cfg.LIVE_TRADING_ENABLED, "dry_run": cfg.LIVE_DRYRUN,
        "key_present": bool(cfg.SOLANA_PRIVATE_KEY),
        "expected_wallet": cfg.LIVE_TRADING_WALLET,
        "address": None, "pubkey": None, "wallet_matches": None,
        "sol_balance": None, "usd_balance": None, "trades_runway": None,
        "min_sol_required": cfg.LIVE_MIN_SOL_BALANCE, "ready": False, "error": None,
    }
    try:
        if cfg.SOLANA_PRIVATE_KEY:
            out["pubkey"] = wallet.get_pubkey()
            out["wallet_matches"] = wallet.wallet_matches_expected()
        addr = out["pubkey"] or cfg.LIVE_TRADING_WALLET or None
        out["address"] = addr
        if addr:
            out["sol_balance"] = wallet.get_sol_balance(addr)
        out["ready"] = bool(
            cfg.LIVE_TRADING_ENABLED and cfg.SOLANA_PRIVATE_KEY
            and out["wallet_matches"]
            and (out["sol_balance"] or 0) >= cfg.LIVE_MIN_SOL_BALANCE
        )
        # Runway estimate (best-effort; ignores errors).
        if out["sol_balance"] is not None:
            price = _sol_price_usd()
            if price:
                out["usd_balance"] = round(out["sol_balance"] * price, 2)
                per_trade_sol = cfg.LIVE_POSITION_USD / price
                avail = max(0.0, out["sol_balance"] - cfg.LIVE_MIN_SOL_BALANCE)
                out["trades_runway"] = int(avail / per_trade_sol) if per_trade_sol > 0 else None
    except Exception as e:
        out["error"] = str(e)
    return out


def _sol_price_usd():
    try:
        r = requests.get(cfg.JUPITER_PRICE_URL, params={"ids": cfg.WSOL_MINT},
                         timeout=cfg.HTTP_TIMEOUT)
        r.raise_for_status()
        data = (r.json() or {}).get(cfg.WSOL_MINT) or {}
        return float(data.get("usdPrice") or 0) or None
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


def _impact_pct(quote):
    try:
        return float(quote.get("priceImpactPct") or 0) * 100.0
    except (TypeError, ValueError):
        return 0.0


def execute_buy(mint, usd_amount):
    """Buy `usd_amount` of `mint` with SOL. Returns a fill dict, {"skip":...}, or None.
    In dry-run: returns the REAL quoted fill (with slippage) without sending."""
    if not _guarded():
        return None
    try:
        sol_price = _sol_price_usd()
        if not sol_price:
            return None
        lamports_in = int(usd_amount / sol_price * 1e9)
        quote = _quote(cfg.WSOL_MINT, mint, lamports_in)

        impact = _impact_pct(quote)
        if impact > cfg.LIVE_MAX_PRICE_IMPACT_PCT:
            return {"skip": True, "reason": f"slippage_{impact:.1f}pct"}

        decimals = wallet.token_decimals(mint)
        qty = int(quote.get("outAmount") or 0) / (10 ** decimals) if decimals >= 0 else 0
        fill_price = (usd_amount / qty) if qty else 0.0
        base = {"confirmed": True, "qty": qty, "fill_price": fill_price,
                "spent_usd": usd_amount, "impact": impact}

        if cfg.LIVE_DRYRUN:
            print(f"[copytrade-live] DRY-RUN buy {mint[:8]} ${usd_amount} "
                  f"@ {fill_price:.10f} (impact {impact:.1f}%)")
            return {**base, "tx_hash": None, "dry_run": True}

        tx = _swap_tx(quote)
        if not tx:
            return None
        sig = wallet.sign_and_send(tx)
        if not wallet.confirm(sig):
            return {"confirmed": False, "tx_hash": sig}
        print(f"[copytrade-live] REAL buy {mint[:8]} ${usd_amount} tx={sig}")
        return {**base, "tx_hash": sig, "dry_run": False}
    except Exception as e:
        print(f"[copytrade-live] buy failed: {e}")
        return None


def execute_sell(mint, qty_tokens):
    """Sell `qty_tokens` of `mint` for SOL. Dry-run returns the real quoted
    proceeds without sending. (No slippage skip on exits — we always want out.)"""
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
        proceeds_sol = int(quote.get("outAmount") or 0) / 1e9
        proceeds_usd = proceeds_sol * sol_price
        fill_price = (proceeds_usd / qty_tokens) if qty_tokens else 0.0
        base = {"confirmed": True, "proceeds_usd": proceeds_usd, "fill_price": fill_price}

        if cfg.LIVE_DRYRUN:
            print(f"[copytrade-live] DRY-RUN sell {mint[:8]} -> ${proceeds_usd:.4f}")
            return {**base, "tx_hash": None, "dry_run": True}

        tx = _swap_tx(quote)
        if not tx:
            return None
        sig = wallet.sign_and_send(tx)
        if not wallet.confirm(sig):
            return {"confirmed": False, "tx_hash": sig}
        print(f"[copytrade-live] REAL sell {mint[:8]} tx={sig}")
        return {**base, "tx_hash": sig, "dry_run": False}
    except Exception as e:
        print(f"[copytrade-live] sell failed: {e}")
        return None
