"""Pool & token registry: in-memory cache backed by the RHC database, with
batched on-chain resolution for pools first seen through their swaps.

* v2/v3 pools: eth_call token0()/token1()/factory()/fee(); trusted only if the
  factory is allow-listed (otherwise recorded as unsupported "factory_unrecognized").
* v4 pools: the PoolManager cannot map id -> key on-chain, so ids are resolved
  from Initialize logs, scanning 10M-block windows backwards with many ids per call.
"""
import logging
import time
from collections import Counter

import rhc_config as cfg
from rhc_decoders import TOPICS, ZERO_ADDR, addr, decode_abi_string
from rhc_market import PoolMeta, classify_pool
from rhc_rpc import RpcError

log = logging.getLogger("rhc.registry")

SEL_TOKEN0 = "0x0dfe1681"
SEL_TOKEN1 = "0xd21220a7"
SEL_FACTORY = "0xc45a0155"
SEL_FEE = "0xddca3f43"
SEL_DECIMALS = "0x313ce567"
SEL_SYMBOL = "0x95d89b41"
SEL_POOL_KEYS = "0x86b6be7d"   # PositionManager.poolKeys(bytes25)


class Registry:
    def __init__(self, rpc, store, clock=time.time):
        self.rpc = rpc
        self.store = store
        self.clock = clock
        self.by_id = {}
        self.by_pk = {}
        self.tokens = {}                 # address -> (decimals, symbol)
        self._unresolvable = {}          # pool_id -> retry_after_ts
        self.unrecognized_factories = Counter()
        self.stable = set(cfg.RHC_STABLE_QUOTES)
        self.eth = set(cfg.RHC_ETH_QUOTES)
        self.tokens[ZERO_ADDR] = (18, "ETH")

    # ── cache ────────────────────────────────────────────────────────────────
    def _put(self, m):
        self.by_id[m.pool_id] = m
        if m.pk is not None:
            self.by_pk[m.pk] = m

    def get(self, pool_id):
        return self.by_id.get(pool_id)

    def load(self, since_ts):
        metas = self.store.load_active_pools(since_ts)
        for m in metas:
            self._put(m)
            for t, d in ((m.token0, m.dec0), (m.token1, m.dec1)):
                if d is not None:
                    self.tokens.setdefault(t, (d, None))
        return len(metas)

    def tracked_pks(self):
        return {m.pk for m in self.by_id.values() if m.tracked and m.pk is not None}

    # ── tokens ───────────────────────────────────────────────────────────────
    def ensure_tokens(self, addresses):
        need = [a for a in set(addresses) if a not in self.tokens]
        if not need:
            return
        known = self.store.load_tokens(need)
        for a, (d, sym) in known.items():
            if d is not None:
                self.tokens[a] = (d, sym)
        need = [a for a in need if a not in self.tokens]
        if not need:
            return
        calls = []
        for a in need:
            calls.append(("eth_call", [{"to": a, "data": SEL_DECIMALS}, "latest"]))
            calls.append(("eth_call", [{"to": a, "data": SEL_SYMBOL}, "latest"]))
        res = self.rpc.batch(calls)
        rows = []
        now = int(self.clock())
        for i, a in enumerate(need):
            dr, sr = res[2 * i], res[2 * i + 1]
            dec = None
            if isinstance(dr, str) and dr not in ("0x", ""):
                try:
                    v = int(dr, 16)
                    dec = v if 0 <= v <= 36 else None
                except ValueError:
                    dec = None
            sym = decode_abi_string(sr) if isinstance(sr, str) else None
            if sym:
                sym = sym[:64]
            self.tokens[a] = (dec, sym)
            rows.append({"address": a, "symbol": sym, "decimals": dec, "first_seen_ts": now})
        self.store.upsert_tokens(rows)

    # ── classification ───────────────────────────────────────────────────────
    def _finish(self, m):
        m.dec0 = self.tokens.get(m.token0, (None,))[0]
        m.dec1 = self.tokens.get(m.token1, (None,))[0]
        b, qt, qc, reason = classify_pool(m.token0, m.token1, self.stable, self.eth)
        m.base_index, m.quote_token, m.quote_class = b, qt, qc
        if reason is None and (m.dec0 is None or m.dec1 is None):
            reason = "decimals_unavailable"
        if reason is None and m.kind in ("v2", "v3"):
            allow = cfg.RHC_V2_FACTORIES if m.kind == "v2" else cfg.RHC_V3_FACTORIES
            if (m.venue or "") not in allow:
                reason = "factory_unrecognized"
                self.unrecognized_factories[m.venue or "unknown"] += 1
        m.reason = reason
        m.supported = reason is None
        return m

    def _persist(self, metas, created):
        if not metas:
            return
        pks = self.store.upsert_pools(metas, created)
        for m in metas:
            m.pk = pks.get(m.pool_id)
            self._put(m)

    # ── creation events ──────────────────────────────────────────────────────
    def register_created(self, events, ts_by_block):
        metas, created = [], {}
        for ev in events:
            if ev.pool_id in self.by_id:
                continue
            metas.append(PoolMeta(pool_id=ev.pool_id, kind=ev.kind, token0=ev.token0, token1=ev.token1,
                                  venue=ev.venue, hooks=ev.hooks, fee=ev.fee, tick_spacing=ev.tick_spacing))
            created[ev.pool_id] = (ev.ref.block, ts_by_block.get(ev.ref.block), "creation")
        if not metas:
            return []
        self.ensure_tokens({m.token0 for m in metas} | {m.token1 for m in metas})
        for m in metas:
            self._finish(m)
        for m in metas:
            m.created_block, m.created_ts = created[m.pool_id][0], created[m.pool_id][1]
        self._persist(metas, created)
        return metas

    # ── on-demand resolution ─────────────────────────────────────────────────
    def resolve(self, refs):
        """refs: {pool_id: kind}. Ensures every resolvable pool is in the cache."""
        now = self.clock()
        todo = {pid: k for pid, k in refs.items()
                if pid not in self.by_id and self._unresolvable.get(pid, 0) <= now}
        if not todo:
            return
        for m in self.store.load_pools_by_ids(list(todo)):
            self._put(m)
            todo.pop(m.pool_id, None)
        if not todo:
            return
        metas = []
        evm = [pid for pid, k in todo.items() if k in ("v2", "v3")]
        if evm:
            metas.extend(self._resolve_evm(evm, todo))
        v4 = [pid for pid, k in todo.items() if k == "v4"]
        deferred = set()
        if v4:
            v4_metas, deferred = self._resolve_v4(v4)
            metas.extend(v4_metas)
        found = {m.pool_id for m in metas}
        for pid in todo:
            if pid not in found and pid not in deferred:
                self._unresolvable[pid] = now + cfg.RHC_UNRESOLVABLE_RETRY_S
        if metas:
            self.ensure_tokens({m.token0 for m in metas} | {m.token1 for m in metas})
            for m in metas:
                self._finish(m)
            self._persist(metas, {})

    def _resolve_evm(self, pools, kinds):
        calls = []
        for p in pools:
            calls += [("eth_call", [{"to": p, "data": SEL_TOKEN0}, "latest"]),
                      ("eth_call", [{"to": p, "data": SEL_TOKEN1}, "latest"]),
                      ("eth_call", [{"to": p, "data": SEL_FACTORY}, "latest"]),
                      ("eth_call", [{"to": p, "data": SEL_FEE}, "latest"])]
        res = self.rpc.batch(calls)
        out = []
        for i, p in enumerate(pools):
            t0, t1, fac, fee = res[4 * i:4 * i + 4]
            if not all(isinstance(x, str) and len(x) >= 66 for x in (t0, t1)):
                continue
            fee_v = int(fee, 16) if isinstance(fee, str) and len(fee) >= 66 else None
            fac_v = addr(fac[2:]) if isinstance(fac, str) and len(fac) >= 66 else None
            out.append(PoolMeta(pool_id=p, kind=kinds[p], token0=addr(t0[2:]), token1=addr(t1[2:]),
                                venue=fac_v, fee=fee_v))
        return out

    def complete_v4_key(self, meta):
        """Fill fee/tickSpacing/hooks for v4 pools stored before tick_spacing was recorded."""
        if meta.kind != "v4" or (meta.tick_spacing is not None and meta.fee is not None):
            return meta
        got = self._resolve_v4_posm([meta.pool_id]) or self._resolve_v4_scan([meta.pool_id])
        if got:
            g = got[0]
            meta.fee, meta.tick_spacing, meta.hooks = g.fee, g.tick_spacing, g.hooks
            self.store.upsert_pools([meta], {})
        return meta

    def _resolve_v4(self, ids):
        """Returns (metas, deferred_ids). Deferred ids were not attempted this call (scan cap)."""
        out = self._resolve_v4_posm(ids)
        found = {m.pool_id for m in out}
        rest = [i for i in ids if i not in found]
        scan, deferred = rest[:cfg.RHC_V4_SCAN_MAX_IDS], rest[cfg.RHC_V4_SCAN_MAX_IDS:]
        if scan:
            out.extend(self._resolve_v4_scan(scan))
        return out, set(deferred)

    def _resolve_v4_posm(self, ids):
        """PositionManager.poolKeys(bytes25): one eth_call per id, result verified by re-hashing."""
        from eth_utils import keccak
        out, remaining = [], list(ids)
        pm = cfg.RHC_V4_POOL_MANAGERS[0] if cfg.RHC_V4_POOL_MANAGERS else None
        for posm in cfg.RHC_V4_POSITION_MANAGERS:
            if not remaining:
                break
            calls = [("eth_call", [{"to": posm, "data": SEL_POOL_KEYS + pid[2:52].ljust(64, "0")}, "latest"])
                     for pid in remaining]
            try:
                res = self.rpc.batch(calls)
            except Exception as e:
                log.warning("poolKeys lookup failed: %s", e)
                continue
            still = []
            for pid, r in zip(remaining, res):
                if not isinstance(r, str) or len(r) < 2 + 64 * 5:
                    still.append(pid)
                    continue
                w = [r[2 + 64 * i:2 + 64 * (i + 1)] for i in range(5)]
                c0, c1, hooks = addr(w[0]), addr(w[1]), addr(w[4])
                if c1 == ZERO_ADDR:
                    still.append(pid)
                    continue
                # Verify: PoolId = keccak256(abi.encode(PoolKey)) must equal the swap's id.
                if "0x" + keccak(hexstr="".join(w)).hex().removeprefix("0x") != pid:
                    still.append(pid)
                    continue
                fee = int(w[2], 16)
                ts_raw = int(w[3], 16)
                tick_spacing = ts_raw - (1 << 256) if ts_raw >= (1 << 255) else ts_raw
                out.append(PoolMeta(pool_id=pid, kind="v4", token0=c0, token1=c1, venue=pm, hooks=hooks, fee=fee,
                                    tick_spacing=tick_spacing))
            remaining = still
        return out

    def _resolve_v4_scan(self, ids):
        """Fallback: single-id Initialize scans, newest window first (one value per topic
        position allows 10M-block spans; OR-lists are limited to 100k blocks)."""
        from rhc_decoders import decode_log
        managers = frozenset(cfg.RHC_V4_POOL_MANAGERS)
        out = []
        try:
            head = self.rpc.block_number()
        except Exception as e:
            log.warning("v4 resolve: head unavailable: %s", e)
            return out
        span = cfg.RHC_GETLOGS_ADDRESS_SPAN
        for pid in ids:
            to, windows, hit = head, 0, None
            while to >= 1 and windows < cfg.RHC_V4_SCAN_MAX_WINDOWS and hit is None:
                frm = max(1, to - span + 1)
                for pm in managers:
                    try:
                        logs = self.rpc.get_logs({"address": pm, "topics": [TOPICS["v4_initialize"], pid]},
                                                 frm, to, max_span=span)
                    except RpcError as e:
                        log.warning("v4 resolve scan failed: %s", e)
                        logs = []
                    for lg in logs:
                        ev = decode_log(lg, managers)
                        if ev is not None and ev.pool_id == pid:
                            hit = ev
                windows += 1
                to = frm - 1
            if hit is not None:
                out.append(PoolMeta(pool_id=hit.pool_id, kind="v4", token0=hit.token0, token1=hit.token1,
                                    venue=hit.venue, hooks=hit.hooks, fee=hit.fee, tick_spacing=hit.tick_spacing))
        return out
