"""On-chain safety / rug-risk score 0-100 via the free public Solana RPC.

Higher = riskier. The strategy vetoes entries at/above a per-portfolio threshold
(default 45). RPC results are cached 5 min per token to stay polite to the free
public endpoint. Feature-derived components need no RPC at all, so even if the
RPC is down we still produce a usable (slightly penalized) score.
"""
import time
import requests

import sniper_config as cfg

_cache = {}   # token_address -> (score, ts)


def compute_rug_risk(token_address: str, features: dict) -> int:
    cached = _cache.get(token_address)
    if cached and time.time() - cached[1] < 300:
        return cached[0]

    score = 0

    # ---- Feature-derived components (no RPC) ----
    liq_mcap = features.get("liq_to_mcap_ratio", 0)
    liq_drain = features.get("liq_quote_change_10m", 0)
    has_socials = features.get("has_socials", 0)
    age_hours = features.get("token_age_hours", 0)
    sells_m5 = features.get("sells_m5", 0)
    buys_m5 = features.get("buys_m5", 0)
    is_grad = features.get("is_graduated", 0)

    if liq_drain < -10:    score += 15   # liquidity draining
    if not has_socials:    score += 10
    if not is_grad:        score += 10   # not graduated off pumpswap
    if age_hours < 1:      score += 10   # very new
    if liq_mcap < 0.05:    score += 5    # thin liquidity vs mcap
    if sells_m5 / (buys_m5 + 1) > 2:  score += 10   # heavy sell pressure

    # ---- On-chain components via public RPC ----
    try:
        mint_ok, freeze_ok, top_pct = _check_onchain(token_address)
        if not mint_ok:    score += 20   # mint authority not revoked (#1 rug vector)
        if not freeze_ok:  score += 10   # freeze authority active
        if top_pct > 50:   score += 15   # extreme concentration
        elif top_pct > 30: score += 8
    except Exception as e:
        print(f"[sniper.rug] RPC error {token_address[:8]}: {e}")
        score += 10   # penalize if we can't verify

    score = min(score, 100)
    _cache[token_address] = (score, time.time())
    return score


def _rpc(method, params, rpc_url):
    r = requests.post(rpc_url, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
    }, timeout=10)
    r.raise_for_status()
    return r.json()


def _check_onchain(mint_address: str):
    """Return (mint_revoked, freeze_revoked, top_holder_pct) via public RPC."""
    rpc_url = cfg.SOLANA_RPC_URL
    try:
        info = _rpc("getAccountInfo",
                    [mint_address, {"encoding": "jsonParsed"}], rpc_url)
    except Exception:
        rpc_url = cfg.SOLANA_RPC_FALLBACK   # one retry on the fallback node
        info = _rpc("getAccountInfo",
                    [mint_address, {"encoding": "jsonParsed"}], rpc_url)

    parsed = (info.get("result", {}) or {}).get("value", {}) or {}
    parsed = parsed.get("data", {}).get("parsed", {}).get("info", {}) if isinstance(parsed.get("data"), dict) else {}
    mint_revoked = parsed.get("mintAuthority") is None
    freeze_revoked = parsed.get("freezeAuthority") is None

    top_pct = 0.0
    try:
        time.sleep(0.2)
        holders = _rpc("getTokenLargestAccounts", [mint_address], rpc_url)
        supply = _rpc("getTokenSupply", [mint_address], rpc_url)
        hlist = (holders.get("result", {}) or {}).get("value", []) or []
        total = float(((supply.get("result", {}) or {}).get("value", {}) or {}).get("uiAmount", 1) or 1)
        top_amt = float(hlist[0]["uiAmount"]) if hlist and hlist[0].get("uiAmount") else 0
        top_pct = (top_amt / total * 100) if total else 0
    except Exception:
        pass

    return mint_revoked, freeze_revoked, top_pct
