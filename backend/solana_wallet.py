"""Solana signing/balance helpers for LIVE trading (Part B).

Deliberately minimal and DEFENSIVE:
  * The wallet key is loaded LAZILY and only from config (Azure env/Key Vault) —
    never logged, never persisted.
  * `solders`/`base58` are imported inside functions so the whole app runs fine
    without them installed while live trading is OFF (the default).
  * Nothing here trades; it only signs/sends a transaction Jupiter already built.

Used by copytrade_live.py, which is itself gated by LIVE_TRADING_ENABLED.
"""
import base64

import requests

import copytrade_config as cfg

_keypair = None   # cached Keypair once loaded


def _load_keypair():
    """Load the signing keypair from config. Accepts a Phantom base58 export or
    a JSON byte-array. Raises if unset or malformed. Never logs the secret."""
    global _keypair
    if _keypair is not None:
        return _keypair
    raw = (cfg.SOLANA_PRIVATE_KEY or "").strip()
    if not raw:
        raise RuntimeError("SOLANA_PRIVATE_KEY is not set")

    from solders.keypair import Keypair
    if raw.startswith("["):
        import json
        kp = Keypair.from_bytes(bytes(json.loads(raw)))
    else:
        kp = Keypair.from_base58_string(raw)
    _keypair = kp
    return kp


def get_pubkey():
    """Public address of the loaded key (safe to display/log)."""
    return str(_load_keypair().pubkey())


def wallet_matches_expected():
    """True if the loaded key produces the address we expect (LIVE_TRADING_WALLET).
    A guard so a wrong/rotated key can't silently trade from another wallet."""
    if not cfg.LIVE_TRADING_WALLET:
        return True
    return get_pubkey() == cfg.LIVE_TRADING_WALLET


def _rpc(method, params):
    r = requests.post(cfg.SOLANA_RPC_URL,
                      json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                      timeout=cfg.HTTP_TIMEOUT)
    r.raise_for_status()
    j = r.json()
    if j.get("error"):
        raise RuntimeError(f"RPC {method} error: {j['error']}")
    return j.get("result")


def get_sol_balance(pubkey=None):
    """Wallet SOL balance (float). Uses the loaded key's address if not given."""
    addr = pubkey or get_pubkey()
    res = _rpc("getBalance", [addr])
    lamports = (res or {}).get("value", 0) if isinstance(res, dict) else res
    return float(lamports or 0) / 1e9


def token_decimals(mint):
    """Decimals for an SPL mint (needed to convert token qty <-> base units)."""
    res = _rpc("getTokenSupply", [mint])
    return int(((res or {}).get("value") or {}).get("decimals", 0))


def sign_and_send(swap_tx_b64):
    """Sign a base64 (versioned) transaction from Jupiter and submit it.
    Returns the transaction signature string. Does NOT wait for confirmation."""
    from solders.versioned_transaction import VersionedTransaction

    kp = _load_keypair()
    raw = base64.b64decode(swap_tx_b64)
    unsigned = VersionedTransaction.from_bytes(raw)
    signed = VersionedTransaction(unsigned.message, [kp])
    encoded = base64.b64encode(bytes(signed)).decode("utf-8")
    sig = _rpc("sendTransaction", [encoded, {"encoding": "base64", "skipPreflight": False,
                                             "maxRetries": 3}])
    return sig


def confirm(signature, timeout_sec=None):
    """Poll until the signature is confirmed/finalized. Returns True on success."""
    import time
    deadline = time.time() + (timeout_sec or cfg.LIVE_CONFIRM_TIMEOUT_SEC)
    while time.time() < deadline:
        res = _rpc("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])
        val = ((res or {}).get("value") or [None])[0]
        if val:
            if val.get("err"):
                return False
            status = val.get("confirmationStatus")
            if status in ("confirmed", "finalized"):
                return True
        time.sleep(2)
    return False
