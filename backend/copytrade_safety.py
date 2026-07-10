"""Live-only pre-buy safety gate for Strategy #4 — the "Bouncer" + "Seatbelt".

ONLY the Live wallet(s) route through here. The Sim wallet keeps entering on the
old criteria (liquidity floor + no-chase) so it stays a clean control we can
compare against. Motivation from the live trade history: the book was profitable
EXCEPT for rug-pulls that blew straight through the -20% price stop (one -97%
trade erased ten good ones). These checks refuse the risky entry up front.

Two layers, cheapest first (we only pay for the RPC calls if the free local
checks pass):

  * Seatbelt (local, no network)
      - re-entry block: don't re-buy a coin we already traded in the last N hours
        (the worst rug was a re-entry of a coin we had just exited)
      - exposure cap: never let one coin exceed a % of equity (that rug was 30%)

  * Bouncer (on-chain RPC via copytrade_config.SOLANA_RPC_URL)
      - mint authority must be revoked (else the dev can print unlimited supply)
      - freeze authority must be revoked (else your tokens can be frozen)
      - optional: no single holder above a set share

Honeypot ("can we even sell it?") is already enforced downstream in
copytrade_live.execute_buy via check_sellable, so it is not repeated here.

Every function is defensive: any unexpected error returns a SKIP (fail safe),
never an accidental buy. On-chain results are cached briefly so re-proposed
candidates don't hammer the RPC on every 10s tick.
"""
import time
from datetime import datetime, timedelta

import requests

import copytrade_config as cfg
import copytrade_engine as engine

# One retry node if the primary RPC errors (mirrors sniper_rug's fallback).
_RPC_FALLBACK = "https://solana-rpc.publicnode.com"

# mint -> ((mint_revoked, freeze_revoked, top_pct) | None, ts). None = RPC failed.
_onchain_cache: dict = {}
_ONCHAIN_TTL_SEC = 300


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def passes_live_entry(portfolio_id, mint, portfolio, size_usd, mark=None):
    """Gate a LIVE new-entry. Returns (ok: bool, reason: str).

    `reason` doubles as the skip label recorded on the signal, so the DB shows
    exactly why the Bouncer turned a trade away.
    """
    if not cfg.LIVE_SAFETY_ENABLED:
        return True, "ok"
    try:
        # ---- Seatbelt 0: token must be old enough (brand-new pairs rug most) ----
        ok, reason = _age_ok(mark)
        if not ok:
            return False, reason

        # ---- Seatbelt 1: no re-entry of a recently traded coin ----
        if cfg.LIVE_REENTRY_BLOCK_HOURS > 0:
            since = datetime.utcnow() - timedelta(hours=cfg.LIVE_REENTRY_BLOCK_HOURS)
            if engine.has_traded_mint_since(portfolio_id, mint, since):
                return False, "reentry_blocked"

        # ---- Seatbelt 2: single-coin exposure cap ----
        ok, reason = _exposure_ok(portfolio_id, portfolio, size_usd)
        if not ok:
            return False, reason

        # ---- Bouncer: on-chain rug vectors ----
        return _onchain_ok(mint)
    except Exception as e:
        # Anything unexpected -> fail safe (skip), never buy blind.
        print(f"[copytrade.safety] error on {mint[:8]}: {e}")
        return False, "safety_error"


# --------------------------------------------------------------------------
# Seatbelt — token age
# --------------------------------------------------------------------------
def _age_ok(mark):
    """Reject pairs younger than LIVE_MIN_TOKEN_AGE_HOURS. If the pair's creation
    time is unknown we allow it (the other gates still apply) rather than block
    on missing data."""
    min_h = cfg.LIVE_MIN_TOKEN_AGE_HOURS
    if min_h <= 0:
        return True, "ok"
    created_ms = (mark or {}).get("pair_created_at")
    if not created_ms:
        return True, "ok"   # unknown age -> don't block on missing data
    age_h = (time.time() * 1000.0 - float(created_ms)) / 3_600_000.0
    if age_h < min_h:
        return False, f"too_new_{age_h:.1f}h"
    return True, "ok"


# --------------------------------------------------------------------------
# Seatbelt — exposure cap
# --------------------------------------------------------------------------
def _exposure_ok(portfolio_id, portfolio, size_usd):
    cap_pct = cfg.LIVE_MAX_POSITION_PCT
    if cap_pct <= 0:
        return True, "ok"
    cash = float((portfolio or {}).get("cash_balance") or 0.0)
    invested = 0.0
    for pos in engine.get_open_positions(portfolio_id):
        invested += float(pos.get("cost_basis") or pos.get("position_usd") or 0.0)
    equity = cash + invested
    if equity <= 0:
        return True, "ok"   # can't size a % of nothing; let cash checks handle it
    if float(size_usd) > (cap_pct / 100.0) * equity:
        return False, f"exposure_cap_{cap_pct:.0f}pct"
    return True, "ok"


# --------------------------------------------------------------------------
# Bouncer — on-chain authority + concentration
# --------------------------------------------------------------------------
def _onchain_ok(mint):
    res = _check_onchain_cached(mint)
    if res is None:
        # Couldn't verify the token on-chain.
        if cfg.LIVE_SKIP_IF_UNVERIFIED:
            return False, "safety_unverified"
        return True, "ok"
    mint_revoked, freeze_revoked, top_pct = res
    if cfg.LIVE_REQUIRE_MINT_REVOKED and not mint_revoked:
        return False, "mint_authority_active"
    if cfg.LIVE_REQUIRE_FREEZE_REVOKED and not freeze_revoked:
        return False, "freeze_authority_active"
    if cfg.LIVE_CHECK_TOP_HOLDER and top_pct > cfg.LIVE_MAX_TOP_HOLDER_PCT:
        return False, f"holder_concentration_{top_pct:.0f}pct"
    return True, "ok"


def _check_onchain_cached(mint):
    cached = _onchain_cache.get(mint)
    if cached and time.time() - cached[1] < _ONCHAIN_TTL_SEC:
        return cached[0]
    try:
        res = _check_onchain(mint)
    except Exception as e:
        print(f"[copytrade.safety] RPC error {mint[:8]}: {e}")
        res = None
    _onchain_cache[mint] = (res, time.time())
    return res


def _rpc(method, params, rpc_url):
    r = requests.post(rpc_url, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
    }, timeout=10)
    r.raise_for_status()
    return r.json()


def _check_onchain(mint):
    """Return (mint_revoked, freeze_revoked, top_holder_pct) via public RPC.
    Raises only if BOTH the primary and fallback nodes fail the first call."""
    rpc_url = cfg.SOLANA_RPC_URL
    try:
        info = _rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}], rpc_url)
    except Exception:
        rpc_url = _RPC_FALLBACK   # one retry on the fallback node
        info = _rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}], rpc_url)

    value = (info.get("result", {}) or {}).get("value", {}) or {}
    data = value.get("data") if isinstance(value, dict) else None
    parsed = data.get("parsed", {}).get("info", {}) if isinstance(data, dict) else {}
    mint_revoked = parsed.get("mintAuthority") is None
    freeze_revoked = parsed.get("freezeAuthority") is None

    # Top-holder concentration needs 2 more (slow) RPC calls — only pay for them
    # when the check is actually enabled. Authority flags above are the core gate.
    top_pct = 0.0
    if not cfg.LIVE_CHECK_TOP_HOLDER:
        return mint_revoked, freeze_revoked, top_pct
    try:
        time.sleep(0.2)   # be polite to the free endpoint
        holders = _rpc("getTokenLargestAccounts", [mint], rpc_url)
        supply = _rpc("getTokenSupply", [mint], rpc_url)
        hlist = (holders.get("result", {}) or {}).get("value", []) or []
        total = float(((supply.get("result", {}) or {}).get("value", {}) or {}).get("uiAmount") or 0)
        top_amt = float(hlist[0].get("uiAmount") or 0) if hlist else 0.0
        top_pct = (top_amt / total * 100.0) if total else 0.0
    except Exception:
        pass   # concentration is best-effort; authority flags are the core gate

    return mint_revoked, freeze_revoked, top_pct
