"""Holder concentration from replayed ERC-20 Transfer logs (+ live balanceOf for the top holders).

The public node keeps logs since genesis and allows 10M-block spans for address-filtered
queries, so a young token's full transfer history is a handful of calls. Very active tokens
exceed RHC_HOLDER_MAX_LOGS; their stats are then built from the most recent window only and
flagged HOLDERS_PARTIAL (balances are re-read with balanceOf, so top holders are still right,
but holders who never moved inside the window are missed).
"""
from collections import defaultdict
from dataclasses import dataclass, field

from rhc_decoders import ZERO_ADDR, addr, hexint

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DEAD = "0x000000000000000000000000000000000000dead"
BURN = {ZERO_ADDR, DEAD}


@dataclass
class HolderReport:
    total_supply: int = 0
    holders: int = 0
    top1_pct: float = 0.0
    top10_pct: float = 0.0
    burned_pct: float = 0.0
    deployer: str = None
    deployer_pct: float = 0.0
    insider_pct: float = 0.0
    partial: bool = False
    transfers: int = 0
    top: list = field(default_factory=list)      # [(address, pct)]


def replay(transfers):
    """Pure: transfers = [(block, log_index, from, to, value)] -> balances dict (chain order)."""
    bal = defaultdict(int)
    for _, _, frm, to, v in sorted(transfers, key=lambda t: (t[0], t[1])):
        if frm != ZERO_ADDR:
            bal[frm] -= v
        bal[to] += v
    return bal


def analyse(transfers, total_supply, excluded, balances_override=None, insider_first_n=50, partial=False):
    """Pure: compute concentration metrics.

    excluded: addresses that are not "holders" (pools, PoolManager, the token itself).
    balances_override: {address: live balance} to correct replayed balances (e.g. rebasing/taxes).
    """
    rep = HolderReport(total_supply=total_supply, partial=partial, transfers=len(transfers))
    bal = replay(transfers)
    if balances_override:
        bal.update(balances_override)
    ordered = sorted(transfers, key=lambda t: (t[0], t[1]))
    mints = [t for t in ordered if t[2] == ZERO_ADDR]
    if mints:
        rep.deployer = mints[0][3]
    # Early holders: the first N distinct recipients, whether via the deployer (team/airdrop wallets)
    # or via the pool (launch snipers). Both are concentration risks if they still hold.
    insiders = []
    for t in ordered:
        to = t[3]
        if to not in excluded and to not in BURN and to not in insiders:
            insiders.append(to)
        if len(insiders) >= insider_first_n:
            break
    supply = total_supply or sum(v for v in bal.values() if v > 0)
    if supply <= 0:
        return rep
    burned = sum(max(0, bal.get(a, 0)) for a in BURN)
    rep.burned_pct = 100.0 * burned / supply
    holders = {a: v for a, v in bal.items() if v > 0 and a not in BURN and a not in excluded}
    rep.holders = len(holders)
    top = sorted(holders.items(), key=lambda kv: kv[1], reverse=True)
    rep.top = [(a, round(100.0 * v / supply, 4)) for a, v in top[:10]]
    rep.top1_pct = rep.top[0][1] if rep.top else 0.0
    rep.top10_pct = round(sum(p for _, p in rep.top), 4)
    if rep.deployer and rep.deployer not in excluded:
        rep.deployer_pct = round(100.0 * max(0, bal.get(rep.deployer, 0)) / supply, 4)
    rep.insider_pct = round(100.0 * sum(max(0, bal.get(a, 0)) for a in insiders) / supply, 4)
    return rep


def decode_transfer(lg):
    t = lg.get("topics") or []
    if len(t) != 3 or t[0].lower() != TRANSFER:
        return None   # ERC-721 transfers have 4 topics; ignore anything else
    try:
        return (hexint(lg["blockNumber"]), hexint(lg["logIndex"]), addr(t[1]), addr(t[2]), int(lg["data"], 16))
    except (ValueError, KeyError):
        return None


def holder_report(rpc, token, from_block, head, excluded, max_logs, span, top_verify=20):
    """Fetch transfers and compute the report. Scans newest-first until max_logs is reached."""
    logs, partial, to = [], False, head
    while to >= from_block:
        frm = max(from_block, to - span + 1)
        chunk = rpc.get_logs({"address": token, "topics": [TRANSFER]}, frm, to, max_span=span)
        logs = chunk + logs
        if len(logs) > max_logs:
            partial = True
            break
        to = frm - 1
    transfers = [t for t in (decode_transfer(lg) for lg in logs) if t]
    calls = [("eth_call", [{"to": token, "data": "0x18160ddd"}, "latest"])]
    prelim = analyse(transfers, 0, excluded, partial=partial)
    cand = [a for a, _ in prelim.top[:top_verify]]
    if prelim.deployer and prelim.deployer not in cand:
        cand.append(prelim.deployer)
    calls += [("eth_call", [{"to": token, "data": "0x70a08231" + a[2:].rjust(64, "0")}, "latest"]) for a in cand]
    res = rpc.batch(calls)
    supply = int(res[0], 16) if isinstance(res[0], str) and len(res[0]) > 2 else 0
    live = {a: int(r, 16) for a, r in zip(cand, res[1:]) if isinstance(r, str) and len(r) > 2}
    return analyse(transfers, supply, excluded, balances_override=live, partial=partial)
