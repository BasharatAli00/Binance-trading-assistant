"""Execution layer for Robinhood Chain tokens (Paper, Dry-Run, and Live).

Isolated from Strategy #4 (Solana). Implements the two-level safety switch:
  * ROBINHOOD_LIVE_ENABLED=false => Pure Paper Trading (No keys needed, $0 spent).
  * ROBINHOOD_LIVE_DRYRUN=true   => Quotes real DEX pricing, validates liquidity, but skips broadcast.
  * Real on-chain broadcast only occurs when BOTH are configured for live.
"""
import re
import requests
import robinhood_config as cfg
import robinhood_wallet as wallet

_S = requests.Session()
_HEX_ADDR_RE = re.compile(r"0x[a-fA-F0-9]{40,64}")

_last_eth_price = 2400.0
_last_eth_price_ts = 0.0


def get_eth_price_usd():
    """Returns approximate ETH price in USD with 60s in-memory caching."""
    global _last_eth_price, _last_eth_price_ts
    import time
    now = time.time()
    if now - _last_eth_price_ts < 60.0:
        return _last_eth_price
    try:
        r = _S.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", timeout=3)
        if r.ok:
            _last_eth_price = float(r.json().get("price", 0) or 0)
            _last_eth_price_ts = now
            return _last_eth_price
    except Exception:
        pass
    return _last_eth_price


def clean_token_input(raw):
    """Extracts hex address or hash from raw input, handling URLs or raw addresses."""
    if not raw:
        return ""
    s = str(raw).strip()
    m = _HEX_ADDR_RE.search(s)
    return m.group(0).lower() if m else s.lower()


def _guarded():
    return bool(cfg.ROBINHOOD_LIVE_ENABLED and cfg.ROBINHOOD_PRIVATE_KEY)


def get_token_market_info(token_address):
    """Fetches real-time price, market cap, symbol and liquidity from DexScreener.
    Supports:
      1. Standard 20-byte token address (0x + 40 hex chars)
      2. Uniswap v4 32-byte Pool ID / pair address (0x + 64 hex chars)
      3. DexScreener URLs containing either token or pool address
    """
    token_address = clean_token_input(token_address)
    if not token_address:
        return {"symbol": "", "price": 0.0, "mcap": 0.0, "liquidity_usd": 0.0, "address": ""}

    try:
        # 1. If input is 66 chars (32 bytes hex), it is a Uniswap v4 Pool ID
        if len(token_address) == 66 and token_address.startswith("0x"):
            try:
                p_url = f"{cfg.DEXSCREENER_BASE}/latest/dex/pairs/robinhood/{token_address}"
                pr = _S.get(p_url, timeout=cfg.HTTP_TIMEOUT)
                if pr.ok:
                    pair = pr.json().get("pair")
                    if pair:
                        base = pair.get("baseToken", {}) or {}
                        resolved_addr = base.get("address") or token_address
                        return {
                            "symbol": base.get("symbol") or "",
                            "price": float(pair.get("priceUsd", 0) or 0),
                            "mcap": float(pair.get("marketCap") or pair.get("fdv") or 0),
                            "liquidity_usd": float((pair.get("liquidity", {}) or {}).get("usd", 0) or 0),
                            "address": resolved_addr,
                            "is_pool_resolved": True,
                        }
            except Exception as pe:
                print(f"[robinhood-live] pair lookup warning for {token_address[:10]}: {pe}")

        # 2. Try standard tokens endpoint
        url = f"{cfg.DEXSCREENER_BASE}/latest/dex/tokens/{token_address}"
        r = _S.get(url, timeout=cfg.HTTP_TIMEOUT)
        pairs = r.json().get("pairs") or [] if r.ok else []

        # 3. Fallback to DexScreener search endpoint if no direct token match
        if not pairs:
            try:
                s_url = f"{cfg.DEXSCREENER_BASE}/latest/dex/search?q={token_address}"
                sr = _S.get(s_url, timeout=cfg.HTTP_TIMEOUT)
                if sr.ok:
                    pairs = sr.json().get("pairs") or []
            except Exception:
                pass

        if not pairs:
            return {"symbol": "", "price": 0.0, "mcap": 0.0, "liquidity_usd": 0.0, "address": token_address}

        # Filter for pairs where this token is the base token
        matches = [p for p in pairs if (p.get("baseToken", {}) or {}).get("address", "").lower() == token_address]
        best = max(matches or pairs, key=lambda p: (p.get("liquidity", {}).get("usd", 0) or 0))

        base_info = best.get("baseToken", {}) or {}
        resolved_address = base_info.get("address") or token_address
        symbol = base_info.get("symbol") or ""
        price = float(best.get("priceUsd", 0) or 0)
        mcap = float(best.get("marketCap") or best.get("fdv") or 0)
        liquidity = float((best.get("liquidity", {}) or {}).get("usd", 0) or 0)
        is_pool = bool(len(token_address) == 66 or resolved_address.lower() != token_address.lower())

        return {
            "symbol": symbol,
            "price": price,
            "mcap": mcap,
            "liquidity_usd": liquidity,
            "address": resolved_address,
            "is_pool_resolved": is_pool,
        }
    except Exception as e:
        print(f"[robinhood-live] token info error for {token_address[:10]}: {e}")
        return {"symbol": "", "price": 0.0, "mcap": 0.0, "liquidity_usd": 0.0, "address": token_address}


def preflight():
    """Health check for the Robinhood Chain Trading Desk."""
    pubkey = wallet.get_pubkey() if cfg.ROBINHOOD_PRIVATE_KEY else None
    display_addr = pubkey or (cfg.ROBINHOOD_EXPECTED_WALLET if cfg.ROBINHOOD_EXPECTED_WALLET else None)
    eth_bal = wallet.get_eth_balance(display_addr) if display_addr else None
    eth_price = get_eth_price_usd()
    eth_bal_usd = round(eth_bal * eth_price, 2) if eth_bal is not None else None

    is_live = bool(cfg.ROBINHOOD_LIVE_ENABLED and not cfg.ROBINHOOD_LIVE_DRYRUN)
    mode = "live" if is_live else ("dry_run" if cfg.ROBINHOOD_LIVE_ENABLED else "paper")
    ready = bool(
        is_live
        and pubkey
        and wallet.wallet_matches_expected()
        and (eth_bal or 0) >= cfg.ROBINHOOD_MIN_ETH_BALANCE
    )

    return {
        "enabled": cfg.ROBINHOOD_ENABLED,
        "mode": mode,
        "live_enabled": cfg.ROBINHOOD_LIVE_ENABLED,
        "dry_run": cfg.ROBINHOOD_LIVE_DRYRUN,
        "wallet_configured": bool(cfg.ROBINHOOD_PRIVATE_KEY),
        "address": display_addr,
        "eth_balance": eth_bal,
        "eth_balance_usd": eth_bal_usd,
        "ready": ready if is_live else True,  # Paper mode is always ready
    }


RELAY_API_BASE = "https://api.relay.link"
ETH_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def get_relay_swap_quote(user_address, from_currency, to_currency, amount_wei, trade_type="EXACT_INPUT"):
    """Fetches an execution quote and calldata payload from Relay on Robinhood Chain."""
    url = f"{RELAY_API_BASE}/quote"
    payload = {
        "user": user_address,
        "originChainId": cfg.ROBINHOOD_CHAIN_ID,
        "destinationChainId": cfg.ROBINHOOD_CHAIN_ID,
        "originCurrency": from_currency,
        "destinationCurrency": to_currency,
        "amount": str(int(amount_wei)),
        "tradeType": trade_type,
    }
    r = _S.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=cfg.HTTP_TIMEOUT)
    if not r.ok:
        try:
            err = r.json().get("message")
        except Exception:
            err = r.text
        raise RuntimeError(f"DEX swap quote error: {err}")
    return r.json()


def execute_buy(token_address, amount_usd):
    """Executes a buy order for token_address on Robinhood Chain.
    Defaults safely to Paper Trading unless live switches are explicitly set.
    """
    token_address = clean_token_input(token_address)
    info = get_token_market_info(token_address)
    target_contract = info.get("address") or token_address
    price = info.get("price") or 0.0
    symbol = info.get("symbol") or target_contract[:6]

    if price <= 0:
        return {"error": "Could not determine a valid market price for this token."}

    qty = amount_usd / price

    # ── Safe Paper Trading / Dry-Run (Default) ───────────────────────────
    if not _guarded() or cfg.ROBINHOOD_LIVE_DRYRUN:
        mode = "dry_run" if cfg.ROBINHOOD_LIVE_DRYRUN else "paper"
        print(f"[robinhood-desk] {mode.upper()} BUY {symbol} (${amount_usd:.2f}) @ ${price:.8f} (qty: {qty:,.2f})")
        return {
            "confirmed": True,
            "mode": mode,
            "symbol": symbol,
            "fill_price": price,
            "qty": qty,
            "spent_usd": amount_usd,
            "tx_hash": None,
        }

    # ── Real Money Live Execution (Gated by switches) ────────────────────
    try:
        pubkey = wallet.get_pubkey()
        if not pubkey:
            return {"error": "Private key is not configured for live execution."}
        if not wallet.wallet_matches_expected():
            return {"error": "Configured wallet does not match expected safety address."}

        eth_price = get_eth_price_usd()
        if eth_price <= 0:
            return {"error": "Unable to determine live ETH price for trade sizing."}

        amount_eth = amount_usd / eth_price
        amount_wei = int(amount_eth * 1e18)

        # Pre-check ETH balance (trade cost + gas buffer ~0.00015 ETH)
        eth_bal = wallet.get_eth_balance(pubkey)
        gas_buffer_eth = 0.00015
        if eth_bal < (amount_eth + gas_buffer_eth):
            return {
                "error": f"Insufficient ETH balance ({eth_bal:.5f} ETH). Trade requires {amount_eth:.5f} ETH + ~{gas_buffer_eth} ETH gas buffer."
            }

        # Fetch live swap routing payload from Relay
        quote = get_relay_swap_quote(
            user_address=pubkey,
            from_currency=ETH_ZERO_ADDRESS,
            to_currency=target_contract,
            amount_wei=amount_wei,
        )

        steps = quote.get("steps") or []
        if not steps:
            return {"error": "DEX router did not return an executable swap route for this token."}

        nonce = int(wallet._rpc("eth_getTransactionCount", [pubkey, "latest"]), 16)
        gas_price = int(wallet._rpc("eth_gasPrice", []), 16)
        last_tx_hash = None

        for step in steps:
            for item in step.get("items") or []:
                raw_tx = item.get("data") or {}
                to_addr = raw_tx.get("to")
                tx_val = int(raw_tx.get("value", 0))
                calldata = raw_tx.get("data", "0x")

                # Estimate gas dynamically with 25% safety buffer
                try:
                    est = wallet._rpc("eth_estimateGas", [{
                        "from": pubkey,
                        "to": to_addr,
                        "value": hex(tx_val),
                        "data": calldata,
                    }])
                    gas_limit = int(int(est, 16) * 1.25)
                except Exception as ge:
                    print(f"[robinhood-live] buy gas estimation fallback: {ge}")
                    gas_limit = 500000

                tx_payload = {
                    "from": pubkey,
                    "to": to_addr,
                    "value": tx_val,
                    "data": calldata,
                    "gas": gas_limit,
                    "gasPrice": gas_price,
                    "nonce": nonce,
                    "chainId": cfg.ROBINHOOD_CHAIN_ID,
                }
                last_tx_hash = wallet.sign_and_send_transaction(tx_payload)
                if not wallet.confirm(last_tx_hash, timeout_sec=60):
                    return {"error": "Swap transaction submitted but failed to confirm on-chain.", "tx_hash": last_tx_hash}
                nonce += 1

        # Check filled token quantity on-chain
        decimals = wallet.token_decimals(target_contract)
        token_bal_raw = wallet.get_token_balance(target_contract, pubkey)
        filled_qty = token_bal_raw / (10 ** decimals) if token_bal_raw > 0 else qty

        return {
            "confirmed": True,
            "mode": "live",
            "symbol": symbol,
            "fill_price": price,
            "qty": filled_qty,
            "spent_usd": amount_usd,
            "tx_hash": last_tx_hash,
        }
    except Exception as e:
        print(f"[robinhood-desk] Live buy error: {e}")
        return {"error": str(e)}


def execute_sell(token_address, qty_tokens):
    """Executes a sell order for token_address on Robinhood Chain."""
    token_address = clean_token_input(token_address)
    info = get_token_market_info(token_address)
    target_contract = info.get("address") or token_address
    price = info.get("price") or 0.0
    symbol = info.get("symbol") or target_contract[:6]

    if price <= 0:
        return {"error": "Could not determine a valid market price for this token."}

    proceeds_usd = qty_tokens * price

    # ── Safe Paper Trading / Dry-Run (Default) ───────────────────────────
    if not _guarded() or cfg.ROBINHOOD_LIVE_DRYRUN:
        mode = "dry_run" if cfg.ROBINHOOD_LIVE_DRYRUN else "paper"
        print(f"[robinhood-desk] {mode.upper()} SELL {symbol} ({qty_tokens:,.2f}) @ ${price:.8f} -> ${proceeds_usd:.2f}")
        return {
            "confirmed": True,
            "mode": mode,
            "symbol": symbol,
            "fill_price": price,
            "proceeds_usd": proceeds_usd,
            "tx_hash": None,
        }

    # ── Real Money Live Execution (Gated by switches) ────────────────────
    try:
        pubkey = wallet.get_pubkey()
        if not pubkey:
            return {"error": "Private key is not configured for live execution."}
        if not wallet.wallet_matches_expected():
            return {"error": "Configured wallet does not match expected safety address."}

        decimals = wallet.token_decimals(target_contract)
        raw_bal = wallet.get_token_balance(target_contract, pubkey)
        on_chain_qty = raw_bal / (10 ** decimals)

        # Cap sell amount to actual on-chain balance to prevent revert
        actual_qty = min(qty_tokens, on_chain_qty) if on_chain_qty > 0 else qty_tokens
        amount_raw = int(actual_qty * (10 ** decimals))

        if amount_raw <= 0:
            return {"error": f"Wallet holds 0 {symbol} tokens to sell."}

        # Fetch live swap routing payload from Relay (Token -> ETH)
        quote = get_relay_swap_quote(
            user_address=pubkey,
            from_currency=target_contract,
            to_currency=ETH_ZERO_ADDRESS,
            amount_wei=amount_raw,
        )

        steps = quote.get("steps") or []
        if not steps:
            return {"error": "DEX router did not return an exit swap route for this token."}

        nonce = int(wallet._rpc("eth_getTransactionCount", [pubkey, "latest"]), 16)
        gas_price = int(wallet._rpc("eth_gasPrice", []), 16)
        last_tx_hash = None

        for step in steps:
            for item in step.get("items") or []:
                raw_tx = item.get("data") or {}
                to_addr = raw_tx.get("to")
                tx_val = int(raw_tx.get("value", 0))
                calldata = raw_tx.get("data", "0x")

                try:
                    est = wallet._rpc("eth_estimateGas", [{
                        "from": pubkey,
                        "to": to_addr,
                        "value": hex(tx_val),
                        "data": calldata,
                    }])
                    gas_limit = int(int(est, 16) * 1.25)
                except Exception as ge:
                    print(f"[robinhood-live] sell gas estimation fallback: {ge}")
                    gas_limit = 500000

                tx_payload = {
                    "from": pubkey,
                    "to": to_addr,
                    "value": tx_val,
                    "data": calldata,
                    "gas": gas_limit,
                    "gasPrice": gas_price,
                    "nonce": nonce,
                    "chainId": cfg.ROBINHOOD_CHAIN_ID,
                }
                last_tx_hash = wallet.sign_and_send_transaction(tx_payload)
                if not wallet.confirm(last_tx_hash, timeout_sec=60):
                    return {"error": "Sell transaction submitted but failed to confirm on-chain.", "tx_hash": last_tx_hash}
                nonce += 1

        actual_proceeds = actual_qty * price
        return {
            "confirmed": True,
            "mode": "live",
            "symbol": symbol,
            "fill_price": price,
            "proceeds_usd": actual_proceeds,
            "tx_hash": last_tx_hash,
        }
    except Exception as e:
        print(f"[robinhood-desk] Live sell error: {e}")
        return {"error": str(e)}
