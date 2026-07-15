"""Token-first smart-wallet discovery for Strategy #4 (copy-trade).

The PnL leaderboard rewards wallets that make money on ANY token — including
ruggers who buy early and escape. This module inverts that: it sources candidate
wallets FROM known-reliable, community-driven tokens.

For each seed token we pull its top traders (Solana Tracker /top-traders/{token})
and keep wallets that rank across MULTIPLE reliable tokens. That cross-token
consistency is the key signal — one lucky BONK win is noise; being a top trader
on 3+ different community tokens is skill, and it can only come from trading real
tokens (the seeds aren't rugs). Output feeds the copy-trade watchlist.

Budget: 1 API call per seed token per run (~30 calls), well within the free tier.
"""
import math
import time

import requests

import pumpgainer_config as pgcfg   # reuse the Solana Tracker base + API key

BASE = pgcfg.SOLANATRACKER_BASE
KEY = pgcfg.SOLANATRACKER_API_KEY

# Curated blue-chip / community-driven Solana tokens that SURVIVED (not rugs).
# These seed the trader search. Expand/refresh over time; a wrong or dead address
# simply returns no traders and is skipped.
# Each was validated against live DexScreener data (real liquidity, >=$1M mcap,
# >30 days old) or proven to return traders from /top-traders. A dead/wrong
# address simply returns no traders and is skipped, so the list fails safe.
RELIABLE_TOKEN_SEEDS = {
    # --- originals (all proven to return traders) ---
    "BONK":     "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF":      "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "POPCAT":   "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "MEW":      "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5",
    "GIGA":     "63LfDmNb3MQ8mw9MtZ2To9bEA2M71kZUUGq5tiJxcqj9",
    "PNUT":     "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump",
    "MOODENG":  "ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY",
    "FARTCOIN": "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
    "AI16Z":    "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC",
    "GOAT":     "CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump",
    # --- validated additions (liquidity / mcap / age checked live) ---
    "TRUMP":    "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN",
    "BOME":     "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82",
    "ARC":      "61V8vBaqAGMpgDQi4JcAwo1dmBGHsyhzodcPqnEVpump",
    "ZEREBRO":  "8x5VqbHA8D7NkD52uNuS5nnt3PwA8pLD34ymskeSo2Wn",
    "PONKE":    "5z3EqYQo9HiCEs3R84RCDMu2n7anpDMxRhdK8PSWmrRC",
    "GRIFFAIN": "KENJSUYLASHUMfHyy5o4Hp2FdNqZg1AsUPhfH2kYvEP",
    "ACT":      "GJAFwWjJ3vnTsrQVabjBVK2TYB1YtRCQXRDfDgUnpump",
    "SWARMS":   "74SBV4zDXxTRgv1pEMoECskKBkZHc2yGPnc7GYVepump",
    "CHILLGUY": "Df6yfrKC8kZE3KNkrHERKzAetSxbrWeniQfyJY4Jpump",
    "DADDY":    "4Cnk9EPnW5ixfLZatCPJjDB1PUtcRpVVgTQukm9epump",
    "RETARDIO": "6ogzHhzdrQr9Pgv6hZ2MNze7UrzBMAFyBBWUYp1Fhitx",
}


WSOL = "So11111111111111111111111111111111111111112"
_STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}   # USDT


def fetch_top_traders(token):
    r = requests.get(f"{BASE}/top-traders/{token}",
                     headers={"x-api-key": KEY}, timeout=pgcfg.HTTP_TIMEOUT)
    r.raise_for_status()
    d = r.json()
    return d if isinstance(d, list) else (d.get("traders") or d.get("wallets") or [])


def profile_wallet(wallet, days=30):
    """What does this wallet ACTUALLY trade right now?

    Returns {median_mcap, trades, idle_days} or None. Ranking wallets by past PnL
    on big tokens surfaced traders whose CURRENT activity is $5k micro-cap junk
    (they earned their rank months ago). This measures present behaviour instead:
    the median market cap of tokens they've traded recently, and how long since
    their last trade.
    """
    try:
        r = requests.get(f"{BASE}/wallet/{wallet}/trades",
                         headers={"x-api-key": KEY}, timeout=pgcfg.HTTP_TIMEOUT)
        r.raise_for_status()
        trades = (r.json() or {}).get("trades") or []
    except Exception as e:
        print(f"[smartwallet] profile failed {wallet[:8]}: {e}")
        return None

    now_ms = time.time() * 1000.0
    cutoff = now_ms - days * 86400 * 1000.0
    mcaps, newest = [], 0
    for t in trades:
        tm = t.get("time") or 0
        if tm > newest:
            newest = tm
        if tm < cutoff:
            continue
        # take the non-SOL/stable side — that's the token they actually traded
        for side in ("from", "to"):
            s = t.get(side) or {}
            addr = s.get("address")
            if addr and addr != WSOL and addr not in _STABLES:
                mc = s.get("marketCap")
                if mc:
                    mcaps.append(float(mc))
                break
    if not mcaps:
        return None
    mcaps.sort()
    return {
        "median_mcap": mcaps[len(mcaps) // 2],
        "trades": len(mcaps),
        "idle_days": (now_ms - newest) / 86400000.0 if newest else 999.0,
    }


def filter_by_behavior(cands, min_median_mcap, max_idle_days, max_profile=40):
    """Keep only wallets that CURRENTLY trade real (liquid) tokens and are active.

    Costs 1 API call per candidate, so we only profile the top `max_profile`
    (already ranked by cross-token consistency) to stay inside the free tier —
    with ~21 seeds that's ~61 calls per refresh, and the refresh is once a day.
    """
    kept = []
    for c in cands[:max_profile]:
        p = profile_wallet(c["wallet"])
        time.sleep(0.25)   # be polite to the provider
        if not p:
            continue
        if p["median_mcap"] < min_median_mcap or p["idle_days"] > max_idle_days:
            continue
        c.update(p)
        kept.append(c)
    # Most-active liquid traders first (they generate the usable signals).
    kept.sort(key=lambda c: (c["median_mcap"] >= 1_000_000, c["trades"]), reverse=True)
    return kept


def _tx_total(t):
    txc = t.get("tx_counts") or t.get("txCounts") or {}
    if isinstance(txc, dict):
        return sum(int(v) for v in txc.values() if isinstance(v, (int, float)))
    if isinstance(txc, (int, float)):
        return int(txc)
    return 0


def find_candidates(seeds=None, min_seeds=2, max_tx_per_seed=4000):
    """Return ranked candidate wallets sourced from the reliable-token seeds.

    min_seeds       — must rank on at least this many DIFFERENT reliable tokens
                      (the cross-token consistency filter).
    max_tx_per_seed — anti-bot: drop wallets whose avg tx-count per seed is absurd.
    """
    seeds = seeds or RELIABLE_TOKEN_SEEDS
    agg = {}
    per_seed = {}
    for name, mint in seeds.items():
        try:
            traders = fetch_top_traders(mint)
        except Exception as e:
            print(f"[smartwallet] {name} fetch failed: {e}")
            per_seed[name] = 0
            continue
        per_seed[name] = len(traders)
        for t in traders:
            w = t.get("wallet")
            if not w:
                continue
            a = agg.setdefault(w, {"wallet": w, "seeds": set(),
                                   "realized": 0.0, "invested": 0.0, "tx": 0})
            a["seeds"].add(name)
            a["realized"] += float(t.get("realized") or 0)
            a["invested"] += float(t.get("total_invested") or 0)
            a["tx"] += _tx_total(t)

    out = []
    for w, a in agg.items():
        n = len(a["seeds"])
        if n < min_seeds:                             # consistency filter
            continue
        if a["realized"] <= 0:                        # net profitable on real tokens
            continue
        if max_tx_per_seed and a["tx"] > max_tx_per_seed * n:   # anti-bot
            continue
        a["seed_count"] = n
        a["seeds"] = sorted(a["seeds"])
        a["roi"] = (a["realized"] / a["invested"]) if a["invested"] > 0 else 0.0
        # Consistency dominates; then log-scaled realized PnL; then capped ROI.
        a["score"] = n * 100 + math.log10(max(a["realized"], 1.0)) + min(a["roi"], 5.0)
        out.append(a)

    out.sort(key=lambda x: x["score"], reverse=True)
    return out, per_seed


# --------------------------------------------------------------------------
# Watchlist sync — replaces copy_watched_wallet with the finder's picks.
# Gated so the (paid-ish) Solana Tracker calls run at most once per refresh
# window; between refreshes it just returns the existing smart watchlist.
# --------------------------------------------------------------------------
def sync_watched_wallets(max_wallets=40, min_seeds=2, refresh_hours=24,
                         behavior_filter=True, min_median_mcap=500_000.0,
                         max_idle_days=7.0, max_profile=40):
    from datetime import datetime, timedelta

    from database import SessionLocal
    from models import CopyWatchedWallet, CopyBannedWallet

    # 1) Freshness check — skip the API calls if the smart list is still fresh.
    db = SessionLocal()
    try:
        rows = db.query(CopyWatchedWallet).all()
        smart_rows = [r for r in rows if (r.source_window or "").startswith("smart")]
        newest = max((r.last_synced for r in smart_rows if r.last_synced), default=None)
        if smart_rows and newest and (datetime.utcnow() - newest) < timedelta(hours=refresh_hours):
            return sorted(r.wallet for r in smart_rows)
    finally:
        db.close()

    # 2) Run the finder (network) with no DB connection held.
    cands, per_seed = find_candidates(min_seeds=min_seeds)
    if not cands:
        print("[smartwallet] finder returned 0 candidates — keeping existing watchlist")
        return get_watched()

    # 2b) Behaviour filter — drop wallets whose CURRENT trades are micro-cap junk.
    # Without this, "top traders of GOAT/WIF" get watched even though today they
    # only spam $5k husks, which is what actually lost money in the dry-run.
    if behavior_filter:
        before = len(cands)
        cands = filter_by_behavior(cands, min_median_mcap, max_idle_days,
                                   max_profile=max_profile)
        print(f"[smartwallet] behaviour filter: {before} -> {len(cands)} wallets "
              f"(median mcap >= ${min_median_mcap:,.0f}, active <= {max_idle_days}d)")
        if not cands:
            print("[smartwallet] no wallets passed the behaviour filter — keeping existing")
            return get_watched()

    # 3) Rewrite copy_watched_wallet with the top picks (drops the old ones).
    db = SessionLocal()
    try:
        banned = {w.wallet for w in db.query(CopyBannedWallet).all()}
        picks = [c for c in cands if c["wallet"] not in banned][:max_wallets]
        keep = {c["wallet"] for c in picks}
        now = datetime.utcnow()
        existing = {w.wallet: w for w in db.query(CopyWatchedWallet).all()}
        for i, c in enumerate(picks, 1):
            src = ("smart:" + ",".join(c["seeds"][:3]))[:60]
            row = existing.get(c["wallet"])
            if row:
                row.source_window, row.rank, row.score, row.last_synced = src, i, c["score"], now
            else:
                db.add(CopyWatchedWallet(wallet=c["wallet"], source_window=src, rank=i,
                                         score=c["score"], added_at=now, last_synced=now))
        for wallet, row in existing.items():
            if wallet not in keep:
                db.delete(row)   # drop old/leaderboard wallets
        db.commit()
        print(f"[smartwallet] watchlist rebuilt: {len(keep)} wallets "
              f"(from {len(cands)} candidates across reliable-token seeds)")
        return sorted(keep)
    finally:
        db.close()


def get_watched():
    from database import SessionLocal
    from models import CopyWatchedWallet
    db = SessionLocal()
    try:
        return sorted(w.wallet for w in db.query(CopyWatchedWallet).all())
    finally:
        db.close()
