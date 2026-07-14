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

import requests

import pumpgainer_config as pgcfg   # reuse the Solana Tracker base + API key

BASE = pgcfg.SOLANATRACKER_BASE
KEY = pgcfg.SOLANATRACKER_API_KEY

# Curated blue-chip / community-driven Solana tokens that SURVIVED (not rugs).
# These seed the trader search. Expand/refresh over time; a wrong or dead address
# simply returns no traders and is skipped.
RELIABLE_TOKEN_SEEDS = {
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
}


def fetch_top_traders(token):
    r = requests.get(f"{BASE}/top-traders/{token}",
                     headers={"x-api-key": KEY}, timeout=pgcfg.HTTP_TIMEOUT)
    r.raise_for_status()
    d = r.json()
    return d if isinstance(d, list) else (d.get("traders") or d.get("wallets") or [])


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
def sync_watched_wallets(max_wallets=40, min_seeds=2, refresh_hours=24):
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
