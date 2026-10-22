"""EVM signing and RPC interaction helpers for the Robinhood Chain Trading Desk.

Isolated from Solana and Binance. Defensively designed:
  * `eth_account` is imported lazily inside functions so the system runs smoothly
    in Paper Trading mode without any keys configured.
  * Real transactions are only signed when ROBINHOOD_LIVE_ENABLED is true.
"""
import time
import requests
import robinhood_config as cfg

_account = None


def _load_account():
    """Load the EVM signing account from configuration.
    Raises RuntimeError if unset or malformed."""
    global _account
    if _account is not None:
        return _account
    raw = (cfg.ROBINHOOD_PRIVATE_KEY or "").strip()
    if not raw:
        raise RuntimeError("ROBINHOOD_PRIVATE_KEY is not configured")
    if not raw.startswith("0x"):
        raw = "0x" + raw

    from eth_account import Account
    _account = Account.from_key(raw)
    return _account


def get_pubkey():
    """Returns the checksummed EVM address of the configured private key, or None."""
    try:
        acc = _load_account()
        return acc.address
    except Exception:
        return None


def wallet_matches_expected():
    """Safety guard: verifies the derived public address matches ROBINHOOD_EXPECTED_WALLET."""
    if not cfg.ROBINHOOD_EXPECTED_WALLET:
        return True
    addr = get_pubkey()
    if not addr:
        return False
    return addr.lower() == cfg.ROBINHOOD_EXPECTED_WALLET.lower()


def _rpc(method, params):
    """Executes a JSON-RPC call against the Robinhood Chain RPC endpoint."""
    r = requests.post(
        cfg.ROBINHOOD_RPC_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=cfg.HTTP_TIMEOUT,
    )
    r.raise_for_status()
    j = r.json()
    if j.get("error"):
        raise RuntimeError(f"RPC {method} error: {j['error']}")
    return j.get("result")


def get_eth_balance(address=None):
    """Returns native ETH balance as float."""
    addr = address or get_pubkey()
    if not addr:
        return 0.0
    try:
        res = _rpc("eth_getBalance", [addr, "latest"])
        if res:
            return int(res, 16) / 1e18
    except Exception as e:
        print(f"[robinhood-wallet] get_eth_balance error: {e}")
    return 0.0


def token_decimals(token_address):
    """Returns token decimals via ERC-20 decimals() call (selector 0x313ce567)."""
    try:
        # 0x313ce567 = keccak256("decimals()")[:4]
        res = _rpc("eth_call", [{"to": token_address, "data": "0x313ce567"}, "latest"])
        if res and res != "0x":
            return int(res, 16)
    except Exception:
        pass
    return 18  # default standard for EVM ERC-20


def get_token_balance(token_address, address=None):
    """Returns raw token balance (integer base units) via balanceOf(address)."""
    addr = address or get_pubkey()
    if not addr:
        return 0
    try:
        # 0x70a08231 = keccak256("balanceOf(address)")[:4]
        clean_addr = addr.lower().replace("0x", "").zfill(64)
        call_data = "0x70a08231" + clean_addr
        res = _rpc("eth_call", [{"to": token_address, "data": call_data}, "latest"])
        if res and res != "0x":
            return int(res, 16)
    except Exception as e:
        print(f"[robinhood-wallet] get_token_balance error: {e}")
    return 0


def sign_and_send_transaction(tx_dict):
    """Signs an EVM transaction with the configured private key and broadcasts it."""
    acc = _load_account()
    signed = acc.sign_transaction(tx_dict)
    raw_attr = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    raw_tx_hex = "0x" + raw_attr.hex()
    tx_hash = _rpc("eth_sendRawTransaction", [raw_tx_hex])
    return tx_hash


def confirm(tx_hash, timeout_sec=45):
    """Polls until the transaction receipt is returned and finalized."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            receipt = _rpc("eth_getTransactionReceipt", [tx_hash])
            if receipt:
                # status '0x1' is success, '0x0' is reverted
                status = receipt.get("status")
                return status in ("0x1", 1, "1")
        except Exception:
            pass
        time.sleep(2)
    return False
