"""Volume-quality / wash-trading heuristics from a pool's recent swaps.

Pulls the pool's swap logs for the last window, normalises them to trades, resolves the
real sender (tx.from) for the most recent ones and reads sender nonces to spot brand-new
wallets. All thresholds live in rhc_config; the metrics are also kept as evidence.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median

from rhc_decoders import TOPICS, decode_log
from rhc_market import swap_to_trade


@dataclass
class FlowReport:
    trades: int = 0
    traders: int = 0
    buys: int = 0
    sells: int = 0
    vol_usd: float = 0.0
    buy_usd: float = 0.0
    sell_usd: float = 0.0
    median_usd: float = 0.0
    top3_share: float = 0.0          # share of volume from the 3 busiest wallets
    roundtrip_share: float = 0.0     # share of traders that both bought and sold
    fresh_trader_share: float = 0.0  # traders with nonce <= fresh threshold
    fresh_volume_share: float = 0.0
    bundled_blocks: int = 0          # blocks with >= 3 buys from distinct wallets
    resolved: int = 0
    window_blocks: int = 0
    extra: dict = field(default_factory=dict)


def analyse(trades, nonces=None, fresh_nonce=5):
    """Pure: trades have .side, .usd, .trader, .block. nonces: {trader: nonce}."""
    rep = FlowReport(trades=len(trades))
    if not trades:
        return rep
    by_trader = defaultdict(float)
    sides = defaultdict(set)
    block_buyers = defaultdict(set)
    sizes = []
    for t in trades:
        usd = t.usd or 0.0
        sizes.append(usd)
        rep.vol_usd += usd
        if t.side == "buy":
            rep.buys += 1
            rep.buy_usd += usd
        else:
            rep.sells += 1
            rep.sell_usd += usd
        who = t.trader or t.tx
        by_trader[who] += usd
        sides[who].add(t.side)
        if t.side == "buy" and t.trader:
            block_buyers[t.block].add(t.trader)
    rep.traders = len(by_trader)
    rep.median_usd = median(sizes)
    if rep.vol_usd > 0:
        rep.top3_share = sum(sorted(by_trader.values(), reverse=True)[:3]) / rep.vol_usd
    rep.roundtrip_share = sum(1 for s in sides.values() if len(s) == 2) / rep.traders
    rep.bundled_blocks = sum(1 for b in block_buyers.values() if len(b) >= 3)
    rep.resolved = sum(1 for t in trades if t.trader)
    if nonces:
        fresh = {w for w, n in nonces.items() if n is not None and n <= fresh_nonce}
        known = [w for w in by_trader if w in nonces]
        if known:
            rep.fresh_trader_share = sum(1 for w in known if w in fresh) / len(known)
            vol_known = sum(by_trader[w] for w in known)
            if vol_known > 0:
                rep.fresh_volume_share = sum(by_trader[w] for w in known if w in fresh) / vol_known
    return rep


def is_wash(rep, max_top3=0.6, max_roundtrip=0.5, min_traders=4):
    """Pure heuristic: few wallets doing most of the volume while trading both ways."""
    if rep.trades >= 20 and rep.traders < min_traders:
        return True
    return rep.top3_share >= max_top3 and rep.roundtrip_share >= max_roundtrip


def flow_report(rpc, meta, pricer, head, window_blocks, max_resolve, managers, fresh_nonce=5, max_nonces=60):
    """Fetch recent swaps of one pool and analyse them."""
    frm = max(1, head - window_blocks)
    if meta.kind == "v4":
        flt = {"address": next(iter(managers)), "topics": [TOPICS["v4_swap"], meta.pool_id]}
    else:
        flt = {"address": meta.pool_id, "topics": [TOPICS["v2_swap" if meta.kind == "v2" else "v3_swap"]]}
    logs = rpc.get_logs(flt, frm, head, max_span=max(window_blocks + 1, 1))
    qusd = pricer.usd(meta.quote_class)
    trades = []
    for lg in logs:
        ev = decode_log(lg, managers)
        if ev is None or not hasattr(ev, "d0"):
            continue
        t = swap_to_trade(meta, ev, 0, qusd)
        if t is not None:
            trades.append(t)
    last_block = {}
    for t in trades:
        last_block[t.tx] = max(last_block.get(t.tx, 0), t.block)
    recent = sorted(last_block, key=last_block.get)[-max_resolve:]
    if len(last_block) > max_resolve:
        # Busy pool: analyse the most recent max_resolve transactions, all with resolved senders.
        keep = set(recent)
        trades = [t for t in trades if t.tx in keep]
    senders = {}
    if recent:
        res = rpc.batch([("eth_getTransactionByHash", [h]) for h in recent])
        senders = {h: (r.get("from") or "").lower() for h, r in zip(recent, res) if isinstance(r, dict)}
    for t in trades:
        t.trader = senders.get(t.tx) or None
    vol = defaultdict(float)
    for t in trades:
        if t.trader:
            vol[t.trader] += t.usd or 0.0
    wallets = sorted(vol, key=vol.get, reverse=True)[:max_nonces]      # wallet age for the biggest traders
    nonces = {}
    if wallets:
        res = rpc.batch([("eth_getTransactionCount", [w, "latest"]) for w in wallets])
        nonces = {w: int(r, 16) for w, r in zip(wallets, res) if isinstance(r, str)}
    rep = analyse(trades, nonces, fresh_nonce)
    rep.window_blocks = window_blocks
    return rep
