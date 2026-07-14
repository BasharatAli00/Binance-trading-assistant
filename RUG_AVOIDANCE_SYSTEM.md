# Rug-Pull / Scam-Token Avoidance System — Full Documentation

> Reference for re-implementing SignalScope's pump-bot rug/scam avoidance in another project.
> Source files: `backend/pump_bot/{rug_risk,watchlist,trader,features,config}.py`.

## 1. OVERVIEW

**Plain-English summary (end to end):**

The system watches Solana pump.fun tokens and blocks rugs/scams at **three stages**:

1. **Discovery filter** — A watchlist is rebuilt from DexScreener (+ CoinGecko + internal pipeline). A name/symbol blacklist rejects impersonation scams (TRUMP, BINANCE, "OFFICIAL…"), and basic structural filters require minimum liquidity/volume/age and real price movement.
2. **Structural on-chain gate** — For every surviving watchlist token, it queries Solana RPC for **mint authority** and **freeze authority**. Any token where either is still active (not revoked) is permanently removed — these are on-chain trade blockers / infinite-mint rug vectors.
3. **Entry-time veto** — Just before buying, it computes a **0–100 rug-risk score** from holder concentration + authorities + liquidity/price/social/age signals. Score `>= 45` is a hard veto. Additional independent vetoes catch live liquidity pulls, price dumps, and tokens that recently rugged (history blacklist).

There is **no ML in the rug logic** — it is deterministic rules + a weighted additive score. The ML model (entry gate) is a *separate* quality filter, not a rug filter.

**Files involved:**

| File | Role |
|---|---|
| `backend/pump_bot/rug_risk.py` | Core rug logic: `fetch_holder_concentration()` (on-chain RPC), `compute_rug_risk()` (score), tiers, veto threshold. |
| `backend/pump_bot/watchlist.py` | Token discovery + name/symbol scam blacklist (`_is_scam_name`) + structural filters (`_passes_filters`) + Step-5 mint/freeze authority removal. |
| `backend/pump_bot/trader.py` | Entry-time veto block (calls `fetch_holder_concentration` + `compute_rug_risk`), plus history-based rug blacklist (`_get_history_gates`). |
| `backend/pump_bot/features.py` | Builds the `features` dict consumed by `compute_rug_risk` (esp. `liq_quote_change_10m`, `liq_to_mcap_ratio`, `has_socials`, `is_graduated`, `token_age_hours`, `buy_sell_ratio_15m`). |
| `backend/pump_bot/config.py` | All tunable constants (liquidity/age/volume minimums, DexScreener endpoints, Helius key). |

Note: `RUG_RISK_VETO_THRESHOLD` and `RUG_RISK_*` live in `rug_risk.py`, **not** in `config.py`.

---

## 2. THE RUG-RISK SCORE (verbatim)

Full function with imports, exactly as written in `rug_risk.py`:

```python
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")


def compute_rug_risk(features: dict, holders: dict | None = None) -> tuple[float, dict]:
    """
    Compute rug risk score (0-100). Higher = more dangerous.
    Returns (score, breakdown).
    """
    breakdown = {}

    # ── 1. Top 10 holder concentration (0-25 pts) ────────────────────────────
    top10 = (holders or {}).get("top10_pct", 0)
    if top10 >= 80:
        h10_pts = 25
    elif top10 >= 60:
        h10_pts = 20
    elif top10 >= 40:
        h10_pts = 12
    elif top10 >= 25:
        h10_pts = 5
    else:
        h10_pts = 0
    breakdown["top10_concentration"] = h10_pts

    # ── 2. Top 1 holder (0-15 pts) ───────────────────────────────────────────
    top1 = (holders or {}).get("top1_pct", 0)
    if top1 >= 50:
        h1_pts = 15
    elif top1 >= 30:
        h1_pts = 12
    elif top1 >= 15:
        h1_pts = 7
    elif top1 >= 10:
        h1_pts = 3
    else:
        h1_pts = 0
    breakdown["top1_concentration"] = h1_pts

    # ── 3. SOL liquidity dropping (0-15 pts) ─────────────────────────────────
    liq_change = features.get("liq_quote_change_10m", 0)
    if liq_change < -15:
        liq_pts = 15
    elif liq_change < -8:
        liq_pts = 10
    elif liq_change < -3:
        liq_pts = 5
    else:
        liq_pts = 0
    breakdown["liquidity_drain"] = liq_pts

    # ── 4. No socials (0-10 pts) ─────────────────────────────────────────────
    has_socials = features.get("has_socials", 0)
    social_pts = 0 if has_socials else 10
    breakdown["no_socials"] = social_pts

    # ── 5. Not graduated (0-10 pts) ──────────────────────────────────────────
    is_graduated = features.get("is_graduated", 0)
    grad_pts = 0 if is_graduated else 10
    breakdown["not_graduated"] = grad_pts

    # ── 6. Very new token (0-10 pts) ─────────────────────────────────────────
    age = features.get("token_age_hours", 999)
    if age < 1:
        age_pts = 10
    elif age < 3:
        age_pts = 7
    elif age < 12:
        age_pts = 3
    else:
        age_pts = 0
    breakdown["very_new"] = age_pts

    # ── 7. Sell pressure (0-10 pts) ──────────────────────────────────────────
    buy_ratio = features.get("buy_sell_ratio_15m", features.get("buyer_seller_ratio_h1", 1))
    if buy_ratio < 0.3:
        sell_pts = 10
    elif buy_ratio < 0.5:
        sell_pts = 7
    elif buy_ratio < 0.7:
        sell_pts = 3
    else:
        sell_pts = 0
    breakdown["sell_pressure"] = sell_pts

    # ── 8. Low liquidity/mcap ratio (0-5 pts) ────────────────────────────────
    liq_ratio = features.get("liq_to_mcap_ratio", 0)
    if liq_ratio < 0.01:
        lr_pts = 5
    elif liq_ratio < 0.03:
        lr_pts = 3
    else:
        lr_pts = 0
    breakdown["low_liq_ratio"] = lr_pts

    # ── 9. Mint authority not revoked (0-20 pts) — MOST DANGEROUS ────────────
    # Dev can print infinite tokens and dump — the #1 rug vector on Solana
    mint_auth = (holders or {}).get("mint_authority")
    if mint_auth and mint_auth != "unknown":
        mint_pts = 20  # Dev can print tokens — extreme risk
    elif mint_auth == "unknown":
        mint_pts = 5   # Can't verify — slight risk
    else:
        mint_pts = 0   # Revoked (None) — safe
    breakdown["mint_authority"] = mint_pts

    # ── 10. Freeze authority not revoked (0-10 pts) ──────────────────────────
    # Dev can freeze your tokens so you can't sell
    freeze_auth = (holders or {}).get("freeze_authority")
    if freeze_auth and freeze_auth != "unknown":
        freeze_pts = 10  # Dev can freeze your tokens
    elif freeze_auth == "unknown":
        freeze_pts = 3
    else:
        freeze_pts = 0   # Revoked — safe
    breakdown["freeze_authority"] = freeze_pts

    total = min(100, max(0, sum(breakdown.values())))
    return total, breakdown
```

**Signal-by-signal table** (condition → points → why):

| # | Signal (breakdown key) | Condition | Points | Why |
|---|---|---|---|---|
| 1 | `top10_concentration` | top10 >= 80% | 25 | Top-10 holders can dump and crash price |
| | | 60–80% | 20 | |
| | | 40–60% | 12 | |
| | | 25–40% | 5 | |
| | | < 25% | 0 | |
| 2 | `top1_concentration` | top1 >= 50% | 15 | Single wallet can nuke the pool |
| | | 30–50% | 12 | |
| | | 15–30% | 7 | |
| | | 10–15% | 3 | |
| | | < 10% | 0 | |
| 3 | `liquidity_drain` | `liq_quote_change_10m` < -15% | 15 | SOL being pulled from pool = rug in progress |
| | | < -8% | 10 | |
| | | < -3% | 5 | |
| | | >= -3% | 0 | |
| 4 | `no_socials` | `has_socials` falsy | 10 | No socials → no accountability |
| | | truthy | 0 | |
| 5 | `not_graduated` | `is_graduated` falsy | 10 | Still on bonding curve, not on Raydium/Orca/Meteora |
| | | truthy | 0 | |
| 6 | `very_new` | age < 1h | 10 | Newest tokens rug most |
| | | 1–3h | 7 | |
| | | 3–12h | 3 | |
| | | >= 12h | 0 | |
| 7 | `sell_pressure` | `buy_sell_ratio_15m` < 0.3 | 10 | Insiders exiting |
| | | < 0.5 | 7 | |
| | | < 0.7 | 3 | |
| | | >= 0.7 | 0 | |
| 8 | `low_liq_ratio` | `liq_to_mcap_ratio` < 0.01 | 5 | Thin, easily manipulated pool |
| | | < 0.03 | 3 | |
| | | >= 0.03 | 0 | |
| 9 | `mint_authority` | active (not None/"unknown") | 20 | **#1 rug vector** — dev can mint infinite supply and dump |
| | | "unknown" | 5 | Couldn't verify |
| | | revoked (None) | 0 | |
| 10 | `freeze_authority` | active | 10 | Dev can freeze your wallet so you can't sell |
| | | "unknown" | 3 | |
| | | revoked (None) | 0 | |

**Range & clamping:** `total = min(100, max(0, sum(...)))`. Raw max of the buckets sums to 130 (25+15+15+10+10+10+10+5+20+10), so it **clamps to 100**. Minimum is 0.

**Tier buckets** (`rug_risk_tier`, verbatim):

```python
def rug_risk_tier(score: float) -> str:
    if score >= 70:
        return "HIGH"
    elif score >= 40:
        return "MEDIUM"
    elif score >= 20:
        return "LOW"
    else:
        return "SAFE"
```

- **HIGH** >= 70 · **MEDIUM** 40–69 · **LOW** 20–39 · **SAFE** < 20

**Veto threshold** (defined in `rug_risk.py`):

```python
# Threshold for hard veto — stricter with expanded scoring (mint/freeze authority)
RUG_RISK_VETO_THRESHOLD = 45
```

Applied in `trader.py`: `if rug_score >= RUG_RISK_VETO_THRESHOLD: continue`. Note the veto (45) sits **inside the MEDIUM tier** — it's stricter than the HIGH tier label.

---

## 3. INPUT CONTRACT

`compute_rug_risk(features, holders)` reads from **two dicts**.

### 3a. `holders` dict (from `fetch_holder_concentration`)

| Key | Type | Meaning | Example | Source |
|---|---|---|---|---|
| `top1_pct` | float | Largest single account's % of supply | `34.2` | RPC `getTokenLargestAccounts` + `getTokenSupply` |
| `top10_pct` | float | Sum of top-10 accounts' % of supply | `61.5` | same |
| `holder_count` | int | # accounts returned (<=20, **not** true holder count) | `20` | `getTokenLargestAccounts` |
| `mint_authority` | str \| None \| "unknown" | Mint authority pubkey; `None` = revoked/safe | `None` | `getAccountInfo` |
| `freeze_authority` | str \| None \| "unknown" | Freeze authority pubkey; `None` = revoked/safe | `None` | `getAccountInfo` |

### 3b. `features` dict — only the **6 keys** the score reads

`compute_rug_risk` only touches these (the full features dict has ~50 keys, built in `features.py`):

| Key | Type | Meaning | Example | Source → exact field |
|---|---|---|---|---|
| `liq_quote_change_10m` | float (%) | % change in **quote (SOL)** liquidity over last 10 snapshots | `-12.4` | Computed in `features.py` `_compute_liq_quote_change` from `pump_token_snapshots.liquidity_quote` (first vs last of 10 rows). Underlying value originates from DexScreener pair `liquidity.quote`. |
| `has_socials` | int (0/1) | Has >=1 social/website link | `1` | DexScreener pair `info.socials` / `info.websites` → stored in snapshot `has_socials`. |
| `is_graduated` | int (0/1) | Trading on Raydium/Orca/Meteora (off bonding curve) | `0` | DexScreener pair `dexId` in {raydium, orca, meteora} → snapshot `dex_id`. |
| `token_age_hours` | float | Hours since pair creation | `2.5` | DexScreener pair `pairCreatedAt` (ms) → snapshot `pair_created_at`. Defaults to `999` if missing. |
| `buy_sell_ratio_15m` | float | 15-min buys/sells ratio (falls back to `buyer_seller_ratio_h1`) | `0.42` | Computed in `features.py` from snapshot `buys_m5`/`sells_m5` summed over 15 min. |
| `liq_to_mcap_ratio` | float | liquidity_usd / market_cap | `0.02` | Computed in `features.py`; inputs DexScreener `liquidity.usd` and `marketCap`/`fdv`. |

All `features.get(...)` calls have defaults, so a missing key never crashes — it scores as the "safe" branch (except `token_age_hours` default 999 = old = safe, and `buy_sell_ratio` default 1 = safe).

**Where the raw data lives:** features come from the `pump_token_snapshots` DB table (1-minute snapshots ingested from DexScreener), **not** live API calls at scoring time. The `holders` dict is the only piece fetched live (from Solana RPC) at scoring time.

---

## 4. ON-CHAIN CHECKS (verbatim)

Full `fetch_holder_concentration` + cache + RPC URL helper, exactly as in `rug_risk.py`:

```python
# Cache holder data. Holder concentration + mint/freeze authority change slowly,
# so a long TTL cuts Helius calls sharply (this is the top Helius consumer, and
# getTokenLargestAccounts has no public-RPC fallback — free-tier conservation).
_holder_cache: dict[str, dict] = {}
_holder_cache_time: dict[str, datetime] = {}
HOLDER_CACHE_TTL_SEC = 21600  # 6 hours


def _get_rpc_url() -> str:
    if HELIUS_API_KEY:
        return f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    return "https://api.mainnet-beta.solana.com"


def fetch_holder_concentration(token_address: str) -> dict:
    """
    Fetch top holder concentration + mint/freeze authority for a token via Solana RPC.
    Returns {top1_pct, top10_pct, holder_count, mint_authority, freeze_authority} or cached values.
    """
    now = datetime.now(timezone.utc)

    # Check cache
    if token_address in _holder_cache:
        cached_time = _holder_cache_time.get(token_address)
        if cached_time and (now - cached_time).total_seconds() < HOLDER_CACHE_TTL_SEC:
            return _holder_cache[token_address]

    rpc = _get_rpc_url()
    result = {"top1_pct": 0, "top10_pct": 0, "holder_count": 0, "mint_authority": None, "freeze_authority": None}

    try:
        with httpx.Client(timeout=10) as client:
            # Get top 20 holders
            resp = client.post(rpc, json={
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [token_address]
            })
            accounts = resp.json().get("result", {}).get("value", [])

            if not accounts:
                _holder_cache[token_address] = result
                _holder_cache_time[token_address] = now
                return result

            # Get total supply
            resp2 = client.post(rpc, json={
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenSupply",
                "params": [token_address]
            })
            total_supply = float(resp2.json().get("result", {}).get("value", {}).get("uiAmount", 0))

            if total_supply <= 0:
                _holder_cache[token_address] = result
                _holder_cache_time[token_address] = now
                return result

            top1 = float(accounts[0].get("uiAmount") or 0)
            top10 = sum(float(a.get("uiAmount") or 0) for a in accounts[:10])

            result = {
                "top1_pct": round(top1 / total_supply * 100, 2),
                "top10_pct": round(top10 / total_supply * 100, 2),
                "holder_count": len(accounts),
                "mint_authority": None,
                "freeze_authority": None,
            }

            # Check mint/freeze authority (most common rug vector)
            try:
                resp3 = client.post(rpc, json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getAccountInfo",
                    "params": [token_address, {"encoding": "jsonParsed"}],
                })
                parsed = resp3.json().get("result", {}).get("value", {}).get("data", {}).get("parsed", {}).get("info", {})
                result["mint_authority"] = parsed.get("mintAuthority")       # None = revoked (safe)
                result["freeze_authority"] = parsed.get("freezeAuthority")   # None = revoked (safe)
            except Exception as e:
                logger.debug(f"Mint/freeze authority check failed for {token_address[:12]}: {e}")
                result["mint_authority"] = "unknown"
                result["freeze_authority"] = "unknown"

    except Exception as e:
        logger.warning(f"Holder concentration fetch failed for {token_address[:12]}: {e}")

    _holder_cache[token_address] = result
    _holder_cache_time[token_address] = now
    return result
```

Batch helper (verbatim):

```python
def fetch_holder_batch(addresses: list[str]) -> dict[str, dict]:
    """Fetch holder data for multiple tokens. Rate-limited."""
    results = {}
    for addr in addresses:
        results[addr] = fetch_holder_concentration(addr)
        time.sleep(0.2)  # Rate limit: ~5 req/sec
    return results
```

**RPC methods and what's computed:**

| RPC method | Params | Used for |
|---|---|---|
| `getTokenLargestAccounts` | `[token_address]` | Returns up to 20 largest token accounts (`value[].uiAmount`). `top1` = `accounts[0].uiAmount`; `top10` = sum of first 10. |
| `getTokenSupply` | `[token_address]` | `value.uiAmount` = total supply. Denominator for the percentages. |
| `getAccountInfo` | `[token_address, {"encoding":"jsonParsed"}]` | `result.value.data.parsed.info.mintAuthority` and `.freezeAuthority`. |

**Mint/freeze "revoked / safe" determination:** the RPC returns `mintAuthority`/`freezeAuthority` as either a pubkey string (still active) or `null`. In Python that null becomes `None`, which the code treats as **revoked = safe (0 pts)**. A non-null pubkey = active = dangerous. If the `getAccountInfo` call throws, the value is set to the string `"unknown"` (partial penalty: 5 pts mint / 3 pts freeze).

**Holder concentration computation — IMPORTANT LIMITATION:** Concentration is `top1/total_supply` and `sum(top10)/total_supply` taken **directly from `getTokenLargestAccounts`**. **The code does NOT exclude the liquidity pool / bonding-curve / AMM vault account from the "top holder" set.** On pump.fun/pumpswap tokens, the bonding-curve or pool vault is almost always the #1 "holder," so `top1_pct` and `top10_pct` are **systematically inflated** by the pool's own reserves. There is no logic to identify or subtract the LP/curve account (no known-program-owner check, no pool-address exclusion). This is a real weakness — see §10.

Also note `holder_count` is capped at 20 (length of the RPC response), so it is **not** a real unique-holder count and is not used in scoring.

**RPC provider / fallback:** Helius (`https://mainnet.helius-rpc.com/?api-key=<HELIUS_API_KEY>`) when the key is set; otherwise the public `https://api.mainnet-beta.solana.com`. The comment notes `getTokenLargestAccounts` effectively has no reliable public-RPC fallback (rate limits), which is why the cache TTL is long.

---

## 5. LP / LIQUIDITY CHECKS

**Is there an explicit "LP locked or burned" check?** **No.** There is **no** LP-lock or LP-burn detection anywhere in this system. It does not check whether LP tokens were burned, sent to a locker (e.g. a lock program), or held by the dev. The only liquidity-related protections are:

1. **Mint/freeze authority revocation** (§4) — proxy for "dev can't nuke the token," but distinct from LP lock.
2. **Live SOL-side liquidity drain detection** via `liq_quote_change_10m`.

**Liquidity-pull detection (verbatim source)** — from `features.py`:

```python
def _compute_liq_quote_change(rows: list[dict]) -> float:
    """Compute % change of quote (SOL) liquidity over last 10 snapshots."""
    if len(rows) < 2:
        return 0.0
    latest_lq = rows[0].get("liquidity_quote") or 0
    oldest_lq = rows[-1].get("liquidity_quote") or 0
    if oldest_lq > 0:
        return ((latest_lq - oldest_lq) / oldest_lq) * 100
    return 0.0
```

It compares `liquidity_quote` (SOL side of the pool, from DexScreener) in the newest vs oldest of the last 10 one-minute snapshots. This feeds **two** independent checks:

- **Score signal #3** (`liquidity_drain`): -3%/-8%/-15% thresholds → 5/10/15 pts.
- **Hard entry veto** (`trader.py`): `if feats.get("liq_quote_change_10m", 0) < -10: continue` — any >10% SOL drain over 10 minutes is an immediate skip, independent of the score.

---

## 6. ENTRY-TIME VETO (verbatim)

The rug-relevant tail of the veto/gate block for the **default (non-TCN) strategy**, from `trader.py` (the momentum/model gates above it are shown for order):

```python
        # Momentum: require m5 >= 3%
        m5_change = feats.get("price_change_m5", 0)
        m15_change = feats.get("price_change_15m", 0)
        if m5_change < 3.0:
            logger.info(f"  {symbol:10s} | SKIP — m5 too low ({m5_change:.1f}% < 3%)")
            continue

        # Signal quality filter
        sig_vol = breakdown.get("volume_score", 0)
        sig_bp = breakdown.get("buy_pressure", 0)
        sig_mom = breakdown.get("momentum", 0)
        if sig_vol > 5 or sig_bp > 12 or sig_mom < 3:
            logger.info(...)
            continue

        # Dump vetoes
        if m5_change < -3 and m15_change < -5:
            logger.info(f"  {symbol:10s} | VETO — price dumping (m5={m5_change:.1f}%, m15={m15_change:.1f}%)")
            continue
        if m5_change < -5:
            logger.info(f"  {symbol:10s} | VETO — sharp 5m drop ({m5_change:.1f}%)")
            continue

        # Rug veto: liquidity pull
        if feats.get("liq_quote_change_10m", 0) < -10:
            logger.info(f"  {symbol:10s} | VETO — liquidity pull detected ({feats['liq_quote_change_10m']:.1f}%)")
            continue

        # Rug risk check
        holders = fetch_holder_concentration(addr)
        rug_score, rug_breakdown = compute_rug_risk(feats, holders)
        rug_tier = rug_risk_tier(rug_score)

        logger.info(f"  {symbol:10s} | rug_risk={rug_score:.0f}/100 ({rug_tier}) | top1={holders.get('top1_pct', 0):.1f}% top10={holders.get('top10_pct', 0):.1f}%")

        if rug_score >= RUG_RISK_VETO_THRESHOLD:
            logger.info(f"  {symbol:10s} | VETO — rug risk too high ({rug_score:.0f}/100)")
            continue
```

Earlier in the same loop, the **history-based rug blacklist** (verbatim):

```python
        # Gate 1: Rug blacklist — token rugged (<-50%) in last 24h
        if addr in history["rug_blacklist"]:
            logger.info(f"  {symbol:10s} | VETO — rug blacklisted (rugged in last 24h)")
            continue

        # Gate 2: Token loss streak — 3+ stop losses on this token in last 24h
        if addr in history["loss_streak_blocked"]:
            logger.info(f"  {symbol:10s} | VETO — loss streak (3+ stop losses in 24h)")
            continue
```

**Every hard-veto condition, in evaluation order** (default strategy):

1. Already in an open position → skip.
2. In cooldown → skip.
3. `liquidity_usd < MIN_LIQUIDITY` (10 000) → skip.
4. No trades in last 5m (`buys_m5 + sells_m5 == 0`) → skip.
5. `vol_accel_score < min_vol_accel` → skip.
6. **Rug blacklist** — token had a trade close at `return_pct < -50%` in the last 24h (dynamic window: -50→-70% = 6h, -70→-90% = 12h, -90%+ = 24h) → VETO.
7. **Loss streak** — 3+ stop-losses on this token recently → VETO.
8. `buy_pressure_10m < min_buy_pressure` (0.5) → skip.
9. Reversal gate — sells > buys in both current and previous snapshot → VETO.
10. Model P(win) below portfolio threshold (ML entry gate — quality, not rug) → skip.
11. Conviction below dynamic floor (unless model P(win) >= 0.70) → skip.
12. Poor token win-rate history (<40% WR) needs +10 conviction → skip.
13. `price_change_m5 < 3%` → skip.
14. Signal-quality filter → skip.
15. **Dump veto:** `m5 < -3% AND m15 < -5%` → VETO.
16. **Sharp drop veto:** `m5 < -5%` → VETO.
17. **Liquidity-pull veto:** `liq_quote_change_10m < -10%` → VETO.
18. **Rug-risk-score veto:** `compute_rug_risk(...) >= 45` → VETO.

**TCN strategy path** (`trader.py`): if any active portfolio uses `entry_strategy == "tcn_v2"`, almost all of the above is bypassed — **only the rug blacklist (step 6) still applies**, and the TCN model decides everything else. The `compute_rug_risk` veto does **not** run on the TCN path. Worth flagging when porting.

---

## 7. DISCOVERY / WATCHLIST FILTERS (verbatim)

**Name/symbol scam blacklist** — from `watchlist.py`:

```python
_SCAM_KEYWORDS = {
    # Political figures — common pump & dump bait
    "TRUMP", "BIDEN", "OBAMA", "MAGA", "MELANIA", "BARRON",
    "KAMALA", "DESANTIS", "VIVEK", "PUTIN", "ZELENSKY", "MODI",
    # Crypto celebrities — impersonation scams
    "ANSEM", "MURAD", "GCR", "HSAKA", "GIGANTIC",
    # Major projects — fake versions
    "ETHEREUM", "BITCOIN", "CARDANO", "CHAINLINK", "UNISWAP",
    # Exchanges — always scam on pump.fun
    "BINANCE", "COINBASE", "KRAKEN", "BYBIT", "OKX",
    # Companies
    "TESLA", "APPLE", "NVIDIA", "MICROSOFT", "AMAZON", "META",
    # Celebrities
    "ELON", "ELONMUSK",
}

# Patterns that indicate impersonation (substring match)
_SCAM_PATTERNS = [
    "OFFICIAL", "REAL", "ORIGINAL", "LEGIT", "VERIFIED",
    "2.0", "3.0",  # fake "new version"
]

# Exact known scam symbols (add as discovered)
_SCAM_EXACT = {
    "TRUMP250", "ANSEMWIFHAT", "TRUMPCOIN", "TRUMPSOL",
    "ELONCOIN", "MUSKTOKEN", "BIDENCOIN",
}


def _is_scam_name(symbol: str, name: str) -> bool:
    """Detect likely scam/impersonation tokens by name patterns.

    Returns True if the token name/symbol matches known scam patterns.
    These tokens use famous names to attract buyers but are rugs.
    """
    sym = symbol.upper().strip()
    nm = name.upper().strip()
    combined = sym + " " + nm

    # Exact match on known scams
    if sym in _SCAM_EXACT:
        return True

    # Keyword match — symbol contains a famous name
    for kw in _SCAM_KEYWORDS:
        if kw in sym and sym != kw:
            # e.g. "TRUMPSOL", "ANSEMWIF" — contains keyword but isn't exactly the keyword
            return True
        if kw in nm and len(nm) > len(kw) + 3:
            # Name contains keyword with extra chars = derivative scam
            return True

    # Pattern match — contains impersonation patterns
    for pat in _SCAM_PATTERNS:
        if pat in sym or pat in nm:
            return True

    # Number suffix scam — "TOKEN123", "TOKEN2025", "TOKEN250"
    import re
    if re.match(r'^[A-Z]+\d{2,}$', sym) and len(sym) > 4:
        return True

    return False
```

**Structural pre-filter** — `_passes_filters` from `watchlist.py`:

```python
def _passes_filters(pair: dict, skip_age_check: bool = False) -> bool:
    base = pair.get("baseToken", {})
    address = base.get("address", "")

    if not _is_pump_token(address):          # address must end in "pump"
        return False
    if pair.get("chainId", "") != "solana":
        return False

    # Scam name filter — reject tokens impersonating famous names/projects
    symbol = (base.get("symbol") or "").upper()
    name = (base.get("name") or "").upper()
    if _is_scam_name(symbol, name):
        return False

    liq = (pair.get("liquidity") or {}).get("usd", 0) or 0
    if liq < MIN_LIQUIDITY:                  # 10_000
        return False

    vol_h1 = (pair.get("volume") or {}).get("h1", 0) or 0
    if vol_h1 < MIN_VOLUME_H1:               # 1_000
        return False

    if not skip_age_check:
        age_min = _token_age_minutes(pair.get("pairCreatedAt"))
        if age_min < MIN_TOKEN_AGE_MIN:      # 30 min
            return False
        if age_min > MAX_TOKEN_AGE_DAYS * 24 * 60:   # 7 days
            return False

    # Must have at least 1 trade in last 5 min
    txns_m5 = pair.get("txns", {}).get("m5", {})
    if (txns_m5.get("buys", 0) + txns_m5.get("sells", 0)) == 0:
        return False

    # Must show meaningful price movement — flat tokens waste watchlist slots
    price_change = pair.get("priceChange") or {}
    m5 = abs(float(price_change.get("m5", 0) or 0))
    h1 = abs(float(price_change.get("h1", 0) or 0))
    if m5 < 2.0 and h1 < 5.0:
        return False

    return True
```

**Structural on-chain removal (watchlist Step 5)** — from `watchlist.py`:

```python
    from pump_bot.rug_risk import fetch_holder_concentration

    safe_map: dict[str, dict] = {}
    skipped = {"mint_auth": 0, "freeze_auth": 0}

    for addr, token in token_map.items():
        sym = token.get("symbol", addr[:8])

        # On-chain checks via Helius (cached 1h)
        holders = fetch_holder_concentration(addr)
        mint_auth = holders.get("mint_authority")
        freeze_auth = holders.get("freeze_authority")

        if mint_auth and mint_auth != "unknown":
            logger.info(f"Watchlist: SKIP {sym} — mint authority active")
            skipped["mint_auth"] += 1
            continue

        if freeze_auth and freeze_auth != "unknown":
            logger.info(f"Watchlist: SKIP {sym} — freeze authority active")
            skipped["freeze_auth"] += 1
            continue

        safe_map[addr] = token
```

Note the comment says "cached 1h" but the actual TTL constant is **6 hours** (`HOLDER_CACHE_TTL_SEC = 21600`) — the comment is stale.

Deliberate design choice: the **rug-risk score is intentionally NOT applied at watchlist time** — only the permanent on-chain blockers (mint/freeze) are. High-risk-but-tradeable tokens stay on the watchlist as negative training examples and are blocked later at entry.

---

## 8. CONFIG & THRESHOLDS

Rug/scam-relevant constants. Note: the ones in `rug_risk.py` are **not** env-configurable (hardcoded); only a few in `config.py` read env vars.

| Constant | Value | Location | Env var |
|---|---|---|---|
| `RUG_RISK_VETO_THRESHOLD` | `45` | rug_risk.py | — (hardcoded) |
| Tier cutoffs (HIGH/MED/LOW) | 70 / 40 / 20 | rug_risk.py `rug_risk_tier` | — |
| `HOLDER_CACHE_TTL_SEC` | `21600` (6h) | rug_risk.py | — |
| Per-signal point thresholds | see §2 table | rug_risk.py `compute_rug_risk` | — (hardcoded) |
| `HELIUS_API_KEY` | `""` | rug_risk.py & config.py | `HELIUS_API_KEY` |
| `MIN_LIQUIDITY` | `10_000` | config.py | — |
| `MIN_TOKEN_AGE_MIN` | `30` | config.py | — |
| `MAX_TOKEN_AGE_DAYS` | `7` | config.py | — |
| `MIN_VOLUME_H1` | `1_000` | config.py | — |
| `MAX_WATCHLIST` | `50` | config.py | — |
| `CG_WATCHLIST_CACHE_MIN` | `30` | config.py | — |
| Liquidity-pull entry veto | `< -10%` | trader.py (inline) | — |
| Dump veto | `m5<-3 & m15<-5`, or `m5<-5` | trader.py (inline) | — |
| Rug-blacklist trigger | `return_pct < -50%` in 24h | trader.py `_get_history_gates` | — |
| `COINGECKO_PRO_API_KEY` | — | watchlist.py | `COINGECKO_PRO_API_KEY` |
| `MODE` / `DATABASE_*_URL` | — | config.py | `MODE`, `DATABASE_{PRODUCTION,STAGING,DEVELOPMENT}_URL` |

The entry vetoes in trader.py (liquidity pull -10%, dump thresholds, rug-risk 45) are **inline magic numbers**, not named constants — porting them cleanly means extracting them.

---

## 9. EXTERNAL DEPENDENCIES

**Third-party APIs:**

| API | Endpoint(s) | Key required? | Notes / limits |
|---|---|---|---|
| **Solana RPC via Helius** | `https://mainnet.helius-rpc.com/?api-key=…` — methods `getTokenLargestAccounts`, `getTokenSupply`, `getAccountInfo` | Yes (`HELIUS_API_KEY`); falls back to public RPC if unset | The scarce resource — heavily cached (6h). Public fallback `api.mainnet-beta.solana.com` is rate-limited and unreliable for `getTokenLargestAccounts`. |
| **DexScreener** | `api.dexscreener.com` — `/latest/dex/tokens/{addrs}`, `/latest/dex/search`, `/token-boosts/top/v1`, `/token-boosts/latest/v1`, `/token-profiles/latest/v1`, `/token-profiles/recent-updates/v1` | No key | Free public API. Batch = 30 addresses/call; code sleeps 0.5–1s between calls as courtesy. Source of all pair/liquidity/volume/socials/txns data. |
| **CoinGecko Pro** | `pro-api.coingecko.com/api/v3/onchain/networks/solana/{trending_pools,new_pools}?dex=pumpswap` | Yes (`COINGECKO_PRO_API_KEY`) — optional fallback | Only used as watchlist fallback when DexScreener yields too few. Cached 30 min. |

**Python packages** (rug path only): `httpx` (HTTP), `psycopg2` (Postgres). Standard lib: `datetime`, `os`, `time`, `logging`, `math`, `re`. No web3/solana SDK is needed for the *detection* logic — it's raw JSON-RPC over httpx. (The trading/execution side uses `solders`/`solana`, but that's not part of rug avoidance.)

**Caching:**

| What | TTL | Where | Why |
|---|---|---|---|
| Holder concentration + mint/freeze authority (per token) | **6 hours** (`HOLDER_CACHE_TTL_SEC=21600`), in-process dict | rug_risk.py | These change slowly; Helius is the top consumer and `getTokenLargestAccounts` has no good free fallback. |
| CoinGecko watchlist addresses | 30 min (`CG_WATCHLIST_CACHE_MIN`), module-level list | watchlist.py | Cut CG calls from ~12/hr to ~2/hr. |

The holder cache is a plain module-level dict — **not shared across processes** and lost on restart. Porting to multiple workers would need Redis/DB-backed caching.

---

## 10. HONEST LIMITS

**Rug/scam types this system does NOT catch:**

- **LP not locked/burned** — there is **zero** LP-lock/LP-burn detection (§5). A token can pass every check and still have the dev holding removable LP. This is the single biggest gap.
- **Bonding-curve/pool not excluded from concentration** — `top1_pct`/`top10_pct` include the AMM/curve vault (§4), so concentration is inflated. This can cause **false vetoes** on legitimate tokens (the pool looks like a whale) and can also mask a real whale hiding behind the pool. No known-account exclusion exists.
- **Slow rugs / gradual dev dumps** — a dev selling steadily over hours won't trip the `liq_quote_change_10m < -10%` (10-min window) or the -50% history blacklist until damage is done. Detection is short-window.
- **Fake/honeypot sellability** — no simulated sell / transfer-tax / honeypot check. Freeze authority is checked, but custom transfer-hook or blacklist-based honeypots (Token-2022 extensions) are not. The `getAccountInfo` parse assumes classic SPL layout.
- **Coordinated multi-wallet dumps / Sybil holders** — concentration across many sub-threshold wallets looks safe. Only top-1/top-10 are measured (and only 20 accounts are fetched).
- **Insider pre-mine via many wallets**, sniper bundles, dev-linked wallet clusters — no wallet-graph/funding analysis.
- **Name-scam evasion** — the blacklist is a fixed keyword/pattern list; misspellings (e.g. "TRVMP"), unicode look-alikes, or new personas bypass it. `_SCAM_EXACT` must be maintained by hand.
- **Metadata/social spoofing** — `has_socials` only checks that a link *exists*, not that it's real or reachable.
- **Token-2022 fee/authority extensions** beyond mint/freeze — not inspected.

**Known false positives & handling:**

- **Pool-inflated concentration** (above) is the main false-positive source. It's partially mitigated by the *threshold design* — top10 needs >=40% for meaningful points and the veto is 45 total, so a single pool vault alone usually won't cross 45 without other signals stacking. But it's a real bias, not a fix.
- **"unknown" authority** (RPC parse failure) adds only 5/3 pts rather than vetoing — a deliberate soft-fail so transient RPC errors don't block everything.
- **Very-new-token penalty** (age <1h = 10 pts) systematically penalizes legit fresh launches; the design accepts this since the strategy targets slightly-aged momentum, and `MIN_TOKEN_AGE_MIN=30` already excludes the first 30 min.
- Missing features degrade to the "safe" branch rather than crashing — so **incomplete data biases toward permitting**, not blocking (except age/authority).

**Measured effectiveness:** There is **no explicit before/after rug-rate metric** in the code or comments. The tuning comments reference **win-rate backtests for the overall strategy** (e.g. "81.2% WR at 5 slots", "71.7% WR", stop-loss/trailing tuning in `config.py`), and the veto threshold comment says it was made "stricter with expanded scoring (mint/freeze authority)" — but there is no committed measurement isolating how many rugs the rug filter specifically prevents. The system also relies on a **feedback loop**: tokens that actually rug (`return_pct < -50%`) auto-populate the 24h `rug_blacklist`, and high-risk tokens are kept as negative training examples for the (separate) ML entry gate. Treat any rug-prevention rate as unquantified in this codebase.

---

**Two highest-leverage fixes if you re-implement this:** (1) exclude the pool/bonding-curve account from holder concentration (identify it by program owner or pool address), and (2) add a real LP-lock/burn check.
