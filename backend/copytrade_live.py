"""LIVE execution for Strategy #4 via Jupiter (free/keyless tier).

Two deliberate switches stand between deployed and spending:
  * LIVE_TRADING_ENABLED (master)  — off => everything simulated.
  * LIVE_DRYRUN                     — on (default) => build the REAL Jupiter
    quote (to measure real slippage) but DO NOT send. Real money moves only
    when master is on AND dry-run is off.

Buys also pass a slippage/price-impact guard — if a $1 swap would move the
price more than LIVE_MAX_PRICE_IMPACT_PCT, we skip (pool too thin).

Flow (two-step Jupiter):
  1. _route_check()  — GET /swap/v2/order WITHOUT taker  → verify route + impact
  2. _build_tx()     — GET /swap/v2/order WITH taker     → get the real transaction
  3. sign_and_send() → RPC submit
  4. confirm()       → wait for finality

Separating step 1 and 2 is critical: Jupiter often fails (500) when asked to
build a transaction (step 2) for tokens where it can still ROUTE fine (step 1).
This gives us accurate error labels instead of a blanket "jupiter_route_failed".
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


def _route_check(input_mint, output_mint, amount_base):
    """Step 1 — Ask Jupiter for a route WITHOUT the taker wallet.
    This is a pure routing check: it always works if a DEX pool exists,
    regardless of our wallet's token account state.
    Returns the parsed JSON dict, or None on any failure."""
    try:
        r = requests.get(cfg.JUPITER_QUOTE_URL, params={
            "inputMint": input_mint, "outputMint": output_mint,
            "amount": int(amount_base), "slippageBps": cfg.LIVE_SLIPPAGE_BPS,
        }, timeout=cfg.HTTP_TIMEOUT)
        if r.status_code >= 400:
            print(f"[copytrade-live] route_check HTTP {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        if not data.get("outAmount"):
            print(f"[copytrade-live] route_check no route: {data.get('error', 'unknown')}")
            return None
        return data
    except Exception as e:
        print(f"[copytrade-live] route_check exception: {e}")
        return None


def _build_tx(input_mint, output_mint, amount_base):
    """Step 2 — Ask Jupiter to build a real signed transaction WITH our wallet
    as the taker. Returns the full response dict, or None on failure.
    This step can fail for wallet-specific reasons even when routing works."""
    try:
        r = requests.get(cfg.JUPITER_QUOTE_URL, params={
            "inputMint": input_mint, "outputMint": output_mint,
            "amount": int(amount_base), "slippageBps": cfg.LIVE_SLIPPAGE_BPS,
            "taker": wallet.get_pubkey(),
        }, timeout=cfg.HTTP_TIMEOUT)
        if r.status_code >= 400:
            print(f"[copytrade-live] build_tx HTTP {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        if data.get("error"):
            print(f"[copytrade-live] build_tx Jupiter error: {data['error']}")
            return None
        return data
    except Exception as e:
        print(f"[copytrade-live] build_tx exception: {e}")
        return None


def check_sellable(mint):
    """Verify a sell route exists for `mint` (route check only — no wallet needed).
    Guards against buying tokens that are immediately impossible to sell."""
    try:
        decimals = wallet.token_decimals(mint)
        amount_base = int(10 ** decimals) if decimals >= 0 else 1
        if amount_base <= 0:
            amount_base = 1
        r = requests.get(cfg.JUPITER_QUOTE_URL, params={
            "inputMint": mint, "outputMint": cfg.WSOL_MINT,
            "amount": amount_base, "slippageBps": cfg.LIVE_SLIPPAGE_BPS,
        }, timeout=cfg.HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False
        data = r.json()
        return bool(data.get("outAmount"))
    except Exception:
        return False


def _impact_pct(quote):
    try:
        return float(quote.get("priceImpactPct") or 0) * 100.0
    except (TypeError, ValueError):
        return 0.0


def execute_buy(mint, usd_amount):
    """Buy `usd_amount` of `mint` with SOL. Returns a fill dict, {"skipped":...}, or None.
    In dry-run: returns the REAL quoted fill (with slippage) without sending.

    Two-step Jupiter flow:
      Step 1 (_route_check): Verify routing works, measure impact. No wallet needed.
      Step 2 (_build_tx):    Build the real transaction with our wallet as taker.
    """
    if not _guarded():
        return None
    try:
        # ── Pre-flight: can we sell this token at all? ──────────────────────
        if not check_sellable(mint):
            return {"skipped": "not_sellable"}

        sol_price = _sol_price_usd()
        if not sol_price:
            return None
        lamports_in = int(usd_amount / sol_price * 1e9)

        # ── Step 1: Pure route check (no taker) ────────────────────────────
        route = _route_check(cfg.WSOL_MINT, mint, lamports_in)
        if not route:
            return {"skipped": "jupiter_route_failed"}

        impact = _impact_pct(route)
        if impact > cfg.LIVE_MAX_PRICE_IMPACT_PCT:
            return {"skipped": f"slippage_{impact:.1f}pct"}

        decimals = wallet.token_decimals(mint)
        qty = int(route.get("outAmount") or 0) / (10 ** decimals) if decimals >= 0 else 0
        fill_price = (usd_amount / qty) if qty else 0.0
        base = {"confirmed": True, "qty": qty, "fill_price": fill_price,
                "spent_usd": usd_amount, "impact": impact}

        # ── Dry-run: route is valid, report fill without sending ────────────
        if cfg.LIVE_DRYRUN:
            print(f"[copytrade-live] DRY-RUN buy {mint[:8]} ${usd_amount} "
                  f"@ {fill_price:.10f} (impact {impact:.1f}%)")
            return {**base, "tx_hash": None, "dry_run": True}

        # ── Step 2: Build real transaction with our wallet as taker ─────────
        tx_data = _build_tx(cfg.WSOL_MINT, mint, lamports_in)
        if not tx_data:
            # Routing works but Jupiter can't build a tx for our wallet.
            # This is a wallet-config issue, not a routing issue.
            return {"skipped": "jupiter_tx_build_failed"}

        tx = tx_data.get("transaction")
        if not tx:
            print(f"[copytrade-live] Jupiter returned no transaction bytes for {mint[:8]}")
            return {"skipped": "jupiter_no_tx"}

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
    proceeds without sending. (No slippage skip on exits — we always want out.)

    Same two-step flow: route_check first, then build_tx with taker.
    """
    if not _guarded():
        return None
    try:
        sol_price = _sol_price_usd()
        if not sol_price:
            return None
        decimals = wallet.token_decimals(mint)
        amount_base = int(qty_tokens * (10 ** decimals))
        
        # FIX: Cap the amount to the actual token balance on chain to avoid Jupiter "Insufficient funds"
        actual_balance = wallet.get_token_balance_base(mint)
        if actual_balance > 0 and amount_base > actual_balance:
            amount_base = actual_balance
            
        if amount_base <= 0:
            return None

        # Step 1: Route check (no taker)
        route = _route_check(mint, cfg.WSOL_MINT, amount_base)
        if not route:
            print(f"[copytrade-live] SELL route_check failed for {mint[:8]} — aborting sell")
            return None

        proceeds_sol = int(route.get("outAmount") or 0) / 1e9
        proceeds_usd = proceeds_sol * sol_price
        fill_price = (proceeds_usd / qty_tokens) if qty_tokens else 0.0
        base = {"confirmed": True, "proceeds_usd": proceeds_usd, "fill_price": fill_price}

        if cfg.LIVE_DRYRUN:
            print(f"[copytrade-live] DRY-RUN sell {mint[:8]} -> ${proceeds_usd:.4f}")
            return {**base, "tx_hash": None, "dry_run": True}

        # Step 2: Build transaction with taker
        tx_data = _build_tx(mint, cfg.WSOL_MINT, amount_base)
        if not tx_data:
            print(f"[copytrade-live] SELL build_tx failed for {mint[:8]}")
            return None

        tx = tx_data.get("transaction")
        if not tx:
            print(f"[copytrade-live] Jupiter returned no transaction bytes for sell {mint[:8]}")
            return None
        sig = wallet.sign_and_send(tx)
        if not wallet.confirm(sig):
            return {"confirmed": False, "tx_hash": sig}
        print(f"[copytrade-live] REAL sell {mint[:8]} tx={sig}")
        return {**base, "tx_hash": sig, "dry_run": False}
    except Exception as e:
        print(f"[copytrade-live] sell failed: {e}")
        return None
