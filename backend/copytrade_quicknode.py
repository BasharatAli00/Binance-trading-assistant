"""QuickNode Redundant Feed Integration.
Mirrors the Helius module but uses QuickNode Streams.
"""
import copytrade_config as cfg

from datetime import datetime

def ensure_webhook(wallets):
    """Register/Update QuickNode Stream for the watched wallets."""
    # TODO: implement actual QuickNode stream registration once API is known
    # Requires QuickNode API key and specific stream ID configuration
    return "qn_stream_stub"

def delete_webhook():
    """Teardown QuickNode Stream when disabled."""
    pass

def parse_webhook_payload(payload, watched_set):
    """
    Parse a QuickNode Stream payload into the normalized event shape.
    QuickNode payloads typically come as a list of blocks, each containing 'transactions'.
    """
    if not isinstance(payload, list):
        payload = [payload]
        
    events = []
    for item in payload:
        block = item.get("block", {})
        ts = block.get("blockTime")
        block_time = datetime.utcfromtimestamp(ts) if ts else datetime.utcnow()
        
        txs = item.get("transactions", [])
        for tx in txs:
            ev = _parse_tx(tx, block_time, watched_set)
            if ev:
                events.append(ev)
    return events

def _parse_tx(tx_wrapper, block_time, watched_set):
    wallets = tx_wrapper.get("wallets", [])
    wallet = next((w for w in wallets if w in watched_set), None) if watched_set else None
    if not wallet and wallets:
        wallet = wallets[0]  # fallback
    if not wallet:
        return None
        
    raw = tx_wrapper.get("raw", {})
    meta = raw.get("meta", {})
    transaction = raw.get("transaction", {})
    
    sig = (transaction.get("signatures") or [None])[0]
    if not sig: 
        return None
    
    pre_tokens = meta.get("preTokenBalances", [])
    post_tokens = meta.get("postTokenBalances", [])
    
    def get_token_amt(balances, mint):
        for b in balances:
            if b.get("owner") == wallet and b.get("mint") == mint:
                return float(b.get("uiTokenAmount", {}).get("uiAmount") or 0.0)
        return 0.0

    account_keys = transaction.get("message", {}).get("accountKeys", [])
    wallet_idx = -1
    for i, k in enumerate(account_keys):
        if isinstance(k, dict) and k.get("pubkey") == wallet:
            wallet_idx = i
            break
        elif isinstance(k, str) and k == wallet:
            wallet_idx = i
            break
            
    native_pre = 0.0
    native_post = 0.0
    if wallet_idx >= 0:
        pre_bals = meta.get("preBalances", [])
        post_bals = meta.get("postBalances", [])
        if wallet_idx < len(pre_bals): native_pre = pre_bals[wallet_idx] / 1e9
        if wallet_idx < len(post_bals): native_post = post_bals[wallet_idx] / 1e9
        
    wsol_mint = "So11111111111111111111111111111111111111112"
    wsol_pre = get_token_amt(pre_tokens, wsol_mint)
    wsol_post = get_token_amt(post_tokens, wsol_mint)
    
    sol_change = (native_post - native_pre) + (wsol_post - wsol_pre)
    
    all_mints = {b.get("mint") for b in pre_tokens + post_tokens 
                 if b.get("owner") == wallet and b.get("mint") != wsol_mint}
    
    target_mint = None
    max_abs_change = 0
    for m in all_mints:
        pre = get_token_amt(pre_tokens, m)
        post = get_token_amt(post_tokens, m)
        if abs(post - pre) > max_abs_change:
            max_abs_change = abs(post - pre)
            target_mint = m
            
    if not target_mint:
        return None
        
    target_pre = get_token_amt(pre_tokens, target_mint)
    target_post = get_token_amt(post_tokens, target_mint)
    
    if target_post > target_pre and sol_change < -0.0001:
        return _event(wallet, target_mint, "buy", abs(sol_change), sig, block_time)
    elif target_post < target_pre and sol_change > 0.0001:
        return _event(wallet, target_mint, "sell", sol_change, sig, block_time)
        
    return None

def _event(wallet, mint, side, sol_amount, sig, block_time):
    return {"wallet": wallet, "mint": mint, "symbol": None, "side": side,
            "sol_amount": sol_amount, "price_usd": None, "signature": sig,
            "block_time": block_time}
