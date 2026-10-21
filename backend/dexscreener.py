"""DexScreener price and liquidity utilities for token tracking (no DB writes)."""
import time
import requests

_S = requests.Session()
DEXSCREENER_BASE = "https://api.dexscreener.com"


def latest_marks(addresses: list[str]) -> dict:
    """Batch price + liquidity per token for fast exit/entry checks (no DB writes).

    Returns addr -> {"price": float, "liquidity_usd": float, "pair_created_at": ms epoch}.
    """
    out = {}
    for i in range(0, len(addresses), 30):
        batch = addresses[i : i + 30]
        try:
            r = _S.get(
                f"{DEXSCREENER_BASE}/latest/dex/tokens/{','.join(batch)}",
                timeout=8,
            )
            r.raise_for_status()
            pairs = r.json().get("pairs") or []
            for addr in batch:
                matches = [
                    p
                    for p in pairs
                    if p.get("baseToken", {}).get("address") == addr
                ]
                if not matches:
                    continue
                best = max(
                    matches,
                    key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0,
                )
                out[addr] = {
                    "price": float(best.get("priceUsd", 0) or 0),
                    "liquidity_usd": best.get("liquidity", {}).get("usd", 0) or 0,
                    "pair_created_at": best.get("pairCreatedAt"),  # ms epoch (for age gate)
                }
        except Exception as e:
            print(f"[dexscreener] latest_marks error: {e}")
        time.sleep(0.3)
    return out


def latest_price(pair_or_addr: str) -> float | None:
    """Live price for a held token."""
    try:
        r = _S.get(
            f"{DEXSCREENER_BASE}/latest/dex/tokens/{pair_or_addr}",
            timeout=8,
        )
        r.raise_for_status()
        pairs = r.json().get("pairs") or []
        if pairs:
            best = max(
                pairs, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0
            )
            return float(best.get("priceUsd", 0) or 0)
    except Exception:
        pass
    return None
