"""Discovery + snapshots for the sniper (all free, keyless sources).

Discovery: DexScreener boost/profile endpoints, optionally unioned with
GeckoTerminal new/trending Solana pools (free, no key) when USE_GECKOTERMINAL is
set. Both feed the SAME filter/rank funnel, so GeckoTerminal just widens the net
and degrades gracefully to DexScreener-only on any error.

Snapshots: one DexScreener call per 30 tokens, best-pair-per-token, persisted as
SniperSnapshot rows (1 row / token / tick).
"""
import time
from datetime import datetime

import requests
from sqlalchemy import asc

from database import SessionLocal
from models import SniperToken, SniperSnapshot
import sniper_config as cfg

_S = requests.Session()

DEX_DISCOVERY = [
    (f"{cfg.DEXSCREENER_BASE}/token-boosts/top/v1",      "boost_top",    30),
    (f"{cfg.DEXSCREENER_BASE}/token-boosts/latest/v1",   "boost_latest", 30),
    (f"{cfg.DEXSCREENER_BASE}/token-profiles/latest/v1", "profile",      20),
]


# ===================== Discovery =====================

def refresh_watchlist():
    """Discover, filter, rank and upsert the top tokens. Returns ranked list."""
    candidates = {}   # addr -> {"source": tag}

    # 1a. DexScreener discovery endpoints
    for url, tag, limit in DEX_DISCOVERY:
        try:
            r = _S.get(url, timeout=cfg.HTTP_TIMEOUT)
            r.raise_for_status()
            body = r.json()
            items = body if isinstance(body, list) else body.get("pairs", [])
            for item in items[:limit]:
                addr = item.get("tokenAddress") or item.get("address", "") or ""
                if addr.endswith("pump"):
                    candidates.setdefault(addr, {"source": tag})
        except Exception as e:
            print(f"[sniper.data] discovery {tag} error: {e}")
        time.sleep(0.5)

    # 1b. GeckoTerminal new + trending Solana pools (optional, free, no key)
    if cfg.USE_GECKOTERMINAL:
        for ep, tag in [("new_pools", "gt_new"), ("trending_pools", "gt_trend")]:
            try:
                for addr in _geckoterminal_addresses(ep):
                    if addr.endswith("pump"):
                        candidates.setdefault(addr, {"source": tag})
            except Exception as e:
                print(f"[sniper.data] geckoterminal {tag} error: {e}")
            time.sleep(2.0)   # stay within 30 req/min

    if not candidates:
        return []

    # 2. Enrich with pair data (batch 30)
    addrs = list(candidates.keys())
    enriched = []
    for i in range(0, len(addrs), 30):
        batch = addrs[i:i+30]
        try:
            r = _S.get(f"{cfg.DEXSCREENER_BASE}/latest/dex/tokens/{','.join(batch)}",
                       timeout=cfg.HTTP_TIMEOUT)
            r.raise_for_status()
            pairs = r.json().get("pairs", []) or []
            for pair in pairs:
                token = _best_pair(pair, pairs)
                if token and _passes_filters(token):
                    a = token["baseToken"]["address"]
                    token["_source"] = candidates.get(a, {}).get("source", "unknown")
                    enriched.append(token)
        except Exception as e:
            print(f"[sniper.data] enrich error: {e}")
        time.sleep(1.0)

    # 3. Dedup by address, keep best-ranked pair
    seen = {}
    for t in enriched:
        a = t["baseToken"]["address"]
        score = _rank_score(t)
        if a not in seen or score > seen[a]["_rank"]:
            t["_rank"] = score
            seen[a] = t

    ranked = sorted(seen.values(), key=lambda x: x["_rank"], reverse=True)[:cfg.WATCHLIST_MAX_TOKENS]
    _upsert_watchlist(ranked)
    return ranked


def _geckoterminal_addresses(endpoint):
    """Return base-token addresses from a GeckoTerminal Solana pools endpoint."""
    url = f"{cfg.GECKOTERMINAL_BASE}/networks/solana/{endpoint}"
    r = _S.get(url, headers={"Accept": "application/json"}, timeout=cfg.HTTP_TIMEOUT)
    r.raise_for_status()
    out = []
    for pool in r.json().get("data", []) or []:
        rel = (pool.get("relationships", {}) or {}).get("base_token", {}).get("data", {}) or {}
        gid = rel.get("id", "")   # e.g. "solana_<mint>"
        if gid.startswith("solana_"):
            out.append(gid.split("solana_", 1)[1])
    return out


def _best_pair(pair, all_pairs):
    addr = pair.get("baseToken", {}).get("address", "")
    matches = [p for p in all_pairs if p.get("baseToken", {}).get("address") == addr]
    pump = [p for p in matches if p.get("dexId") == "pumpswap"]
    if pump:
        return max(pump, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)
    if matches:
        return max(matches, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)
    return pair


def _passes_filters(pair: dict) -> bool:
    addr = pair.get("baseToken", {}).get("address", "")
    chain = pair.get("chainId", "")
    liq = pair.get("liquidity", {}).get("usd", 0) or 0
    vol_h1 = pair.get("volume", {}).get("h1", 0) or 0
    created = pair.get("pairCreatedAt")
    txns_m5 = (pair.get("txns", {}).get("m5", {}).get("buys", 0) or 0) + \
              (pair.get("txns", {}).get("m5", {}).get("sells", 0) or 0)
    pc_m5 = abs(pair.get("priceChange", {}).get("m5", 0) or 0)
    pc_h1 = abs(pair.get("priceChange", {}).get("h1", 0) or 0)

    if not addr.endswith("pump"):       return False
    if chain != "solana":               return False
    if liq < cfg.MIN_LIQUIDITY:         return False
    if vol_h1 < cfg.MIN_VOLUME_H1:      return False
    if txns_m5 == 0:                    return False
    if pc_m5 < cfg.MIN_PRICE_MOVE_M5 and pc_h1 < cfg.MIN_PRICE_MOVE_H1:
        return False
    if created:
        age_min = (time.time() * 1000 - created) / 60_000
        if age_min < cfg.MIN_TOKEN_AGE_MIN or age_min > cfg.MAX_TOKEN_AGE_DAYS * 1440:
            return False
    return True


def _rank_score(pair: dict) -> float:
    liq = pair.get("liquidity", {}).get("usd", 1) or 1
    vol_h1 = pair.get("volume", {}).get("h1", 0) or 0
    buys_m5 = pair.get("txns", {}).get("m5", {}).get("buys", 0) or 0
    sells_m5 = pair.get("txns", {}).get("m5", {}).get("sells", 0) or 0
    pc_m5 = abs(pair.get("priceChange", {}).get("m5", 0) or 0)
    pc_h1 = abs(pair.get("priceChange", {}).get("h1", 0) or 0)

    vol_liq = vol_h1 / liq
    buy_pressure = buys_m5 / (sells_m5 + 1)
    momentum = pc_m5 + pc_h1 / 2
    return vol_liq * (1 + buy_pressure) * (1 + momentum / 10)


def _upsert_watchlist(tokens: list):
    db = SessionLocal()
    try:
        # Mark everything inactive, then re-activate the current set.
        db.query(SniperToken).filter(SniperToken.is_active == True).update(
            {SniperToken.is_active: False})
        now = datetime.utcnow()
        for t in tokens:
            addr = t["baseToken"]["address"]
            row = db.query(SniperToken).filter(SniperToken.token_address == addr).first()
            fields = dict(
                symbol=t["baseToken"].get("symbol", ""),
                name=t["baseToken"].get("name", ""),
                pair_address=t.get("pairAddress", ""),
                dex_id=t.get("dexId", ""),
                liquidity_usd=t.get("liquidity", {}).get("usd", 0),
                volume_h1=t.get("volume", {}).get("h1", 0),
                price_usd=float(t.get("priceUsd", 0) or 0),
                market_cap=t.get("marketCap", 0),
                discovery_source=t.get("_source", "unknown"),
                rank_score=t.get("_rank", 0),
                is_active=True,
                has_socials=bool(t.get("info", {}).get("socials")),
                boost_count=(t.get("boosts", {}) or {}).get("active", 0) or 0,
                logo_url=t.get("info", {}).get("imageUrl", ""),
                updated_at=now,
            )
            if row:
                for k, v in fields.items():
                    setattr(row, k, v)
            else:
                db.add(SniperToken(token_address=addr, created_at=now, **fields))
        db.commit()
    finally:
        db.close()


def get_active_addresses():
    db = SessionLocal()
    try:
        rows = db.query(SniperToken.token_address, SniperToken.symbol).filter(
            SniperToken.is_active == True).all()
        return [(r[0], r[1]) for r in rows]
    finally:
        db.close()


# ===================== Snapshots =====================

def fetch_snapshots(addresses: list[str]) -> dict:
    """Fetch + store snapshots for all addresses. Returns addr -> snapshot dict."""
    results = {}
    db = SessionLocal()
    try:
        for i in range(0, len(addresses), 30):
            batch = addresses[i:i+30]
            try:
                r = _S.get(f"{cfg.DEXSCREENER_BASE}/latest/dex/tokens/{','.join(batch)}",
                           timeout=cfg.HTTP_TIMEOUT)
                r.raise_for_status()
                pairs = r.json().get("pairs") or []
                by_addr = {}
                for p in pairs:
                    addr = p.get("baseToken", {}).get("address", "")
                    if not addr:
                        continue
                    liq = p.get("liquidity", {}).get("usd", 0) or 0
                    is_pump = p.get("dexId") == "pumpswap"
                    ex = by_addr.get(addr)
                    if not ex or is_pump or liq > (ex.get("liquidity", {}).get("usd", 0) or 0):
                        by_addr[addr] = p
                now = datetime.utcnow()
                for addr, p in by_addr.items():
                    snap = _extract_snapshot(addr, p, now)
                    results[addr] = snap
                    _store_snapshot(db, snap)
                db.commit()
            except Exception as e:
                print(f"[sniper.data] snapshot batch error: {e}")
            time.sleep(1.0)
    finally:
        db.close()
    return results


def _extract_snapshot(addr, pair, now):
    vol = pair.get("volume", {})
    txns = pair.get("txns", {})
    pc = pair.get("priceChange", {})
    liq = pair.get("liquidity", {})
    created = pair.get("pairCreatedAt")
    created_dt = None
    if created:
        try:
            created_dt = datetime.utcfromtimestamp(created / 1000.0)
        except Exception:
            created_dt = None
    return {
        "token_address": addr, "snapshot_time": now,
        "price_usd": float(pair.get("priceUsd", 0) or 0),
        "price_native": float(pair.get("priceNative", 0) or 0),
        "volume_m5": vol.get("m5", 0), "volume_h1": vol.get("h1", 0),
        "volume_h6": vol.get("h6", 0), "volume_h24": vol.get("h24", 0),
        "buys_m5": txns.get("m5", {}).get("buys", 0), "sells_m5": txns.get("m5", {}).get("sells", 0),
        "buys_h1": txns.get("h1", {}).get("buys", 0), "sells_h1": txns.get("h1", {}).get("sells", 0),
        "buys_h6": txns.get("h6", {}).get("buys", 0), "sells_h6": txns.get("h6", {}).get("sells", 0),
        "buys_h24": txns.get("h24", {}).get("buys", 0), "sells_h24": txns.get("h24", {}).get("sells", 0),
        "price_change_m5": pc.get("m5", 0), "price_change_h1": pc.get("h1", 0),
        "price_change_h6": pc.get("h6", 0), "price_change_h24": pc.get("h24", 0),
        "liquidity_usd": liq.get("usd", 0), "liquidity_base": liq.get("base", 0),
        "liquidity_quote": liq.get("quote", 0),
        "market_cap": pair.get("marketCap", 0), "fdv": pair.get("fdv", 0),
        "pair_created_at": created_dt,
        "has_socials": bool(pair.get("info", {}).get("socials")),
        "pool_count": pair.get("info", {}).get("pairCount", 1) or 1,
        "boost_count": (pair.get("boosts", {}) or {}).get("active", 0) or 0,
        "dex_id": pair.get("dexId", ""), "pair_address": pair.get("pairAddress", ""),
    }


def _store_snapshot(db, snap):
    db.add(SniperSnapshot(**snap))


def cleanup_old_snapshots():
    from datetime import timedelta
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=cfg.SNAPSHOT_RETENTION_DAYS)
        db.query(SniperSnapshot).filter(SniperSnapshot.snapshot_time < cutoff).delete()
        db.commit()
    finally:
        db.close()


def latest_marks(addresses: list[str]) -> dict:
    """Batch price + liquidity per token for the fast exit poll (no DB writes).

    Returns addr -> {"price": float, "liquidity_usd": float}. Lightweight on
    purpose: open positions are few, and this runs every FAST_POLL_SEC to catch
    stops/rugs long before the 60s discovery tick would.
    """
    out = {}
    for i in range(0, len(addresses), 30):
        batch = addresses[i:i+30]
        try:
            r = _S.get(f"{cfg.DEXSCREENER_BASE}/latest/dex/tokens/{','.join(batch)}",
                       timeout=8)
            r.raise_for_status()
            pairs = r.json().get("pairs") or []
            for addr in batch:
                matches = [p for p in pairs
                           if p.get("baseToken", {}).get("address") == addr]
                if not matches:
                    continue
                best = max(matches, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)
                out[addr] = {
                    "price": float(best.get("priceUsd", 0) or 0),
                    "liquidity_usd": best.get("liquidity", {}).get("usd", 0) or 0,
                }
        except Exception as e:
            print(f"[sniper.data] latest_marks error: {e}")
        time.sleep(0.3)
    return out


def latest_price(pair_or_addr: str) -> float | None:
    """Live price for a held token (used by exit checks)."""
    try:
        r = _S.get(f"{cfg.DEXSCREENER_BASE}/latest/dex/tokens/{pair_or_addr}",
                   timeout=8)
        r.raise_for_status()
        pairs = r.json().get("pairs") or []
        if pairs:
            best = max(pairs, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)
            return float(best.get("priceUsd", 0) or 0)
    except Exception:
        pass
    return None
