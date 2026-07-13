"""Live-only pre-buy safety gate for Strategy #4 — the "Bouncer" + "Seatbelt".

ONLY the Live wallet(s) route through here. The Sim wallet keeps entering on the
old criteria (liquidity floor + no-chase) so it stays a clean control we can
compare against. Motivation from the live trade history: the book was profitable
EXCEPT for rug-pulls that blew straight through the -20% price stop (one -97%
trade erased ten good ones). These checks refuse the risky entry up front.

Layers, cheapest first (we only pay for RPC/API calls if the free local checks
pass):

  * Seatbelt (local, no network)
      - token age gate (disabled by default; CT_LIVE_MIN_AGE_H)
      - re-entry block: don't re-buy a coin traded in the last N hours
      - rug blacklist: don't re-buy a coin that RUGGED (< -50%) in the last 24h
      - exposure cap: never let one coin exceed a % of equity

  * Bouncer (on-chain RPC + DexScreener)
      - hard authority veto: mint & freeze authority must be revoked
      - rug-risk score (0-100), ported from the pump-bot system: holder
        concentration + liquidity drain + socials + graduation + age + sell
        pressure + liq/mcap + authorities. Score >= threshold => veto.

Honeypot ("can we even sell it?") is already enforced downstream in
copytrade_live.execute_buy via check_sellable, so it is not repeated here.

Known limitation (inherited from the source system): holder concentration is
NOT pool-excluded, so on pump.fun/pumpswap tokens the bonding-curve/pool vault
inflates top1/top10. That biases toward vetoing fresh, concentrated tokens.
A pool-exclusion + explicit LP-lock check are the planned precise upgrades.

Every function is defensive: any unexpected error returns a SKIP (fail safe),
never an accidental buy. On-chain + feature results are cached so re-proposed
candidates don't hammer the endpoints on every 10s tick.
"""
import time
from datetime import datetime, timedelta

import requests

import copytrade_config as cfg
import copytrade_engine as engine

# One retry node if the primary RPC errors (mirrors sniper_rug's fallback).
_RPC_FALLBACK = "https://solana-rpc.publicnode.com"
_DEX_BASE = "https://api.dexscreener.com"

# Tokens on these DEXes have left the pump.fun bonding curve = "graduated".
_GRADUATED_DEXES = {"raydium", "orca", "meteora", "pumpswap"}

# mint -> (holders_dict | None, ts). None = RPC failed. 6h TTL (authorities +
# concentration change slowly; the RPC is the scarce resource).
_holder_cache: dict = {}
_HOLDER_TTL_SEC = 21600
# mint -> (features_dict, ts). Short TTL — momentum/liquidity move fast.
_feature_cache: dict = {}
_FEATURE_TTL_SEC = 120


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
        # ---- Seatbelt 0: token must be old enough (off by default) ----
        ok, reason = _age_ok(mark)
        if not ok:
            return False, reason

        # ---- Seatbelt 1: no re-entry of a recently traded coin ----
        if cfg.LIVE_REENTRY_BLOCK_HOURS > 0:
            since = datetime.utcnow() - timedelta(hours=cfg.LIVE_REENTRY_BLOCK_HOURS)
            if engine.has_traded_mint_since(portfolio_id, mint, since):
                return False, "reentry_blocked"

        # ---- Seatbelt 1b: rug blacklist — coin rugged (< -50%) in last 24h ----
        if cfg.LIVE_RUG_BLACKLIST_HOURS > 0:
            since = datetime.utcnow() - timedelta(hours=cfg.LIVE_RUG_BLACKLIST_HOURS)
            if engine.has_recent_rug(portfolio_id, mint, since, cfg.LIVE_RUG_BLACKLIST_PCT):
                return False, "rug_blacklisted"

        # ---- Seatbelt 2: single-coin exposure cap ----
        ok, reason = _exposure_ok(portfolio_id, portfolio, size_usd)
        if not ok:
            return False, reason

        # ---- Bouncer: on-chain (fetch holders once, reuse below) ----
        holders = _fetch_holders(mint)
        ok, reason = _authority_ok(holders)
        if not ok:
            return False, reason

        # ---- Ported rug-risk score (LOG-ONLY by default; veto opt-in) ----
        if cfg.LIVE_RUG_SCORE_ENABLED:
            feats = _fetch_features(mint)
            score, breakdown = compute_rug_risk(feats, holders or {})
            gate = "VETO" if (cfg.LIVE_RUG_SCORE_VETO and score >= cfg.LIVE_RUG_VETO_THRESHOLD) else "log"
            print(f"[copytrade.safety] {mint[:8]} rug_score={int(round(score))} ({gate}) {breakdown}")
            if cfg.LIVE_RUG_SCORE_VETO and score >= cfg.LIVE_RUG_VETO_THRESHOLD:
                return False, f"rug_risk_{int(round(score))}"

        return True, "ok"
    except Exception as e:
        # Anything unexpected -> fail safe (skip), never buy blind.
        print(f"[copytrade.safety] error on {mint[:8]}: {e}")
        return False, "safety_error"


# --------------------------------------------------------------------------
# Seatbelt — token age
# --------------------------------------------------------------------------
def _age_ok(mark):
    """Reject pairs younger than LIVE_MIN_TOKEN_AGE_HOURS. Unknown age -> allow
    (don't block on missing data)."""
    min_h = cfg.LIVE_MIN_TOKEN_AGE_HOURS
    if min_h <= 0:
        return True, "ok"
    created_ms = (mark or {}).get("pair_created_at")
    if not created_ms:
        return True, "ok"
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
        return True, "ok"
    if float(size_usd) > (cap_pct / 100.0) * equity:
        return False, f"exposure_cap_{cap_pct:.0f}pct"
    return True, "ok"


# --------------------------------------------------------------------------
# Bouncer — hard authority veto
# --------------------------------------------------------------------------
def _authority_ok(holders):
    if holders is None:
        # Couldn't verify the token on-chain.
        if cfg.LIVE_SKIP_IF_UNVERIFIED:
            return False, "safety_unverified"
        return True, "ok"
    ma = holders.get("mint_authority")
    fa = holders.get("freeze_authority")
    # A real pubkey (not None, not "unknown") = authority still active = danger.
    if cfg.LIVE_REQUIRE_MINT_REVOKED and ma is not None and ma != "unknown":
        return False, "mint_authority_active"
    if cfg.LIVE_REQUIRE_FREEZE_REVOKED and fa is not None and fa != "unknown":
        return False, "freeze_authority_active"
    if cfg.LIVE_CHECK_TOP_HOLDER and (holders.get("top1_pct") or 0) > cfg.LIVE_MAX_TOP_HOLDER_PCT:
        return False, f"holder_concentration_{holders.get('top1_pct'):.0f}pct"
    return True, "ok"


# --------------------------------------------------------------------------
# Ported rug-risk score (from the pump-bot system, verbatim weights)
# --------------------------------------------------------------------------
def compute_rug_risk(features, holders=None):
    """0-100 rug-risk score (higher = more dangerous). Returns (score, breakdown).
    Ported from the pump-bot rug_risk.compute_rug_risk with identical weights."""
    b = {}
    holders = holders or {}

    top10 = holders.get("top10_pct", 0) or 0
    b["top10_concentration"] = 25 if top10 >= 80 else 20 if top10 >= 60 else 12 if top10 >= 40 else 5 if top10 >= 25 else 0

    top1 = holders.get("top1_pct", 0) or 0
    b["top1_concentration"] = 15 if top1 >= 50 else 12 if top1 >= 30 else 7 if top1 >= 15 else 3 if top1 >= 10 else 0

    liq_change = features.get("liq_quote_change_10m", 0) or 0
    b["liquidity_drain"] = 15 if liq_change < -15 else 10 if liq_change < -8 else 5 if liq_change < -3 else 0

    b["no_socials"] = 0 if features.get("has_socials", 0) else 10
    b["not_graduated"] = 0 if features.get("is_graduated", 0) else 10

    age = features.get("token_age_hours", 999)
    b["very_new"] = 10 if age < 1 else 7 if age < 3 else 3 if age < 12 else 0

    buy_ratio = features.get("buy_sell_ratio_15m", features.get("buyer_seller_ratio_h1", 1))
    b["sell_pressure"] = 10 if buy_ratio < 0.3 else 7 if buy_ratio < 0.5 else 3 if buy_ratio < 0.7 else 0

    liq_ratio = features.get("liq_to_mcap_ratio", 0) or 0
    b["low_liq_ratio"] = 5 if liq_ratio < 0.01 else 3 if liq_ratio < 0.03 else 0

    mint_auth = holders.get("mint_authority")
    b["mint_authority"] = 20 if (mint_auth and mint_auth != "unknown") else 5 if mint_auth == "unknown" else 0

    freeze_auth = holders.get("freeze_authority")
    b["freeze_authority"] = 10 if (freeze_auth and freeze_auth != "unknown") else 3 if freeze_auth == "unknown" else 0

    total = min(100, max(0, sum(b.values())))
    return total, b


# --------------------------------------------------------------------------
# On-chain holders (top1/top10 + mint/freeze authority) — 6h cache
# --------------------------------------------------------------------------
def _fetch_holders(mint):
    cached = _holder_cache.get(mint)
    if cached and time.time() - cached[1] < _HOLDER_TTL_SEC:
        return cached[0]
    try:
        res = _rpc_holders(mint)
    except Exception as e:
        print(f"[copytrade.safety] holders RPC error {mint[:8]}: {e}")
        res = None
    _holder_cache[mint] = (res, time.time())
    return res


def _rpc(method, params, rpc_url):
    r = requests.post(rpc_url, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
    }, timeout=10)
    r.raise_for_status()
    return r.json()


def _rpc_holders(mint):
    """{top1_pct, top10_pct, mint_authority, freeze_authority}. Raises only if
    the first (largest-accounts) call fails on BOTH primary and fallback."""
    rpc_url = cfg.SOLANA_RPC_URL
    try:
        acc = _rpc("getTokenLargestAccounts", [mint], rpc_url)
    except Exception:
        rpc_url = _RPC_FALLBACK
        acc = _rpc("getTokenLargestAccounts", [mint], rpc_url)

    out = {"top1_pct": 0.0, "top10_pct": 0.0, "mint_authority": None, "freeze_authority": None}
    accounts = (acc.get("result", {}) or {}).get("value", []) or []
    if accounts:
        try:
            time.sleep(0.15)
            sup = _rpc("getTokenSupply", [mint], rpc_url)
            total = float(((sup.get("result", {}) or {}).get("value", {}) or {}).get("uiAmount") or 0)
            if total > 0:
                top1 = float(accounts[0].get("uiAmount") or 0)
                top10 = sum(float(a.get("uiAmount") or 0) for a in accounts[:10])
                out["top1_pct"] = round(top1 / total * 100.0, 2)
                out["top10_pct"] = round(top10 / total * 100.0, 2)
        except Exception:
            pass   # concentration best-effort; authority below is the hard gate

    # mint / freeze authority
    try:
        time.sleep(0.15)
        info = _rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}], rpc_url)
        value = (info.get("result", {}) or {}).get("value", {}) or {}
        data = value.get("data") if isinstance(value, dict) else None
        parsed = data.get("parsed", {}).get("info", {}) if isinstance(data, dict) else {}
        out["mint_authority"] = parsed.get("mintAuthority")     # None = revoked (safe)
        out["freeze_authority"] = parsed.get("freezeAuthority")
    except Exception:
        out["mint_authority"] = "unknown"
        out["freeze_authority"] = "unknown"

    return out


# --------------------------------------------------------------------------
# DexScreener features for the rug score — short cache
# --------------------------------------------------------------------------
def _fetch_features(mint):
    cached = _feature_cache.get(mint)
    if cached and time.time() - cached[1] < _FEATURE_TTL_SEC:
        return cached[0]
    feats = {}
    try:
        r = requests.get(f"{_DEX_BASE}/latest/dex/tokens/{mint}", timeout=8)
        r.raise_for_status()
        pairs = [p for p in (r.json().get("pairs") or [])
                 if p.get("baseToken", {}).get("address") == mint]
        if pairs:
            best = max(pairs, key=lambda p: (p.get("liquidity", {}).get("usd", 0) or 0))
            liq = best.get("liquidity", {}) or {}
            liq_usd = liq.get("usd", 0) or 0
            mcap = best.get("marketCap") or best.get("fdv") or 0
            txns_h1 = (best.get("txns", {}) or {}).get("h1", {}) or {}
            buys = txns_h1.get("buys", 0) or 0
            sells = txns_h1.get("sells", 0) or 0
            ratio = (buys / sells) if sells > 0 else (1.0 if buys == 0 else 2.0)
            created = best.get("pairCreatedAt")
            age_h = (time.time() * 1000.0 - created) / 3_600_000.0 if created else 999
            info = best.get("info", {}) or {}
            has_soc = bool(info.get("socials") or info.get("websites"))
            dex_id = (best.get("dexId") or "").lower()
            feats = {
                "has_socials": 1 if has_soc else 0,
                "is_graduated": 1 if dex_id in _GRADUATED_DEXES else 0,
                "token_age_hours": age_h,
                "buy_sell_ratio_15m": ratio,
                "liq_to_mcap_ratio": (liq_usd / mcap) if mcap else 0,
                "liq_quote_change_10m": 0,   # no snapshot history at entry; Fire Alarm covers live drain
            }
    except Exception as e:
        print(f"[copytrade.safety] features fetch error {mint[:8]}: {e}")
        feats = {}   # missing features -> score's "safe" branches (biases to allow)
    _feature_cache[mint] = (feats, time.time())
    return feats
