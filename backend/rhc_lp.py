"""Liquidity add/remove history for one pool, straight from chain logs (works for any pool,
tracked or not). Used to tell a pulled pool (rug) from one that is merely thin."""
from dataclasses import dataclass

from rhc_decoders import TOPICS, LiquidityEv, decode_log


@dataclass
class LpHistory:
    adds: float = 0.0          # v3/v4: liquidity units; v2: quote-token amount
    removes: float = 0.0
    n_adds: int = 0
    n_removes: int = 0
    last_remove_block: int = None

    @property
    def removed_frac(self):
        if self.adds > 0:
            return min(1.0, self.removes / self.adds)
        return 1.0 if self.removes > 0 else 0.0


def summarise(events, meta):
    """Pure: LiquidityEv list -> LpHistory. For v2, amounts are measured on the quote side."""
    h = LpHistory()
    q_is_0 = meta.base_index == 1
    for e in events:
        if e.kind in ("v3", "v4"):
            amt = abs(float(e.liquidity_delta or 0))
        else:
            raw = e.amount0 if q_is_0 else e.amount1
            amt = float(raw or 0)
        if e.action == "add":
            h.adds += amt
            h.n_adds += 1
        else:
            h.removes += amt
            h.n_removes += 1
            h.last_remove_block = max(h.last_remove_block or 0, e.ref.block)
    return h


def lp_history(rpc, meta, head, blocks, managers):
    frm = max(1, head - blocks)
    if meta.kind == "v4":
        flt = {"address": next(iter(managers)), "topics": [TOPICS["v4_modify_liquidity"], meta.pool_id]}
    elif meta.kind == "v3":
        flt = {"address": meta.pool_id, "topics": [[TOPICS["v3_mint"], TOPICS["v3_burn"]]]}
    else:
        flt = {"address": meta.pool_id, "topics": [[TOPICS["v2_mint"], TOPICS["v2_burn"]]]}
    # OR-lists in a topic position are limited to 100k-block spans on this node.
    logs = rpc.get_logs(flt, frm, head, max_span=99_000)
    evs = [ev for ev in (decode_log(lg, managers) for lg in logs) if isinstance(ev, LiquidityEv)]
    return summarise(evs, meta)
