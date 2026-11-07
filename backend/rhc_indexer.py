"""Robinhood Chain indexer: polls eth_getLogs, decodes DEX events, builds 1m/5m
candles + flow for tracked pools, with restart-safe checkpoints, reorg checks,
gap recording and range backfill.

Checkpoint semantics (restart safety)
-------------------------------------
Candles are flushed only when closed. The durable checkpoint is the last processed
chunk-end block whose timestamp is earlier than the oldest still-open 5m bucket
(S). It is saved with resume_from_ts = S. After a restart we re-process from
checkpoint+1 and ignore trades with ts < S (they are already in flushed candles),
so every bucket >= S is rebuilt from complete data and re-upserted identically.

Run standalone (e.g. an Azure WebJob):  python rhc_indexer.py run
Backfill a recorded gap:                python rhc_indexer.py backfill-gap <id>
"""
import logging
import sys
import threading
import time

import rhc_config as cfg
from rhc_candles import TF_5M, CandleBook, PoolActivity, select_tracked
from rhc_decoders import ALL_TOPICS, LiquidityEv, PoolCreatedEv, SwapEv, SyncEv, decode_log
from rhc_market import QuotePricer, swap_to_trade
from rhc_util import ceil_to

log = logging.getLogger("rhc.indexer")

STREAM = "chain"
V3_SLOT0 = "0x3850c7bd"


class WriterLeaseLost(RuntimeError):
    pass


class Indexer:
    def __init__(self, rpc, store, registry, clock=time.time, sleep=time.sleep, stream=STREAM, durable=True):
        self.rpc = rpc
        self.store = store
        self.registry = registry
        self.clock = clock
        self.sleep = sleep
        self.stream = stream
        self.durable = durable
        self.managers = frozenset(cfg.RHC_V4_POOL_MANAGERS)
        self.book = CandleBook(grace_s=cfg.RHC_CANDLE_GRACE_S, large_usd=cfg.RHC_LARGE_TRADE_USD,
                               ring_size=cfg.RHC_RING_CANDLES)
        self.activity = PoolActivity()
        self.pricer = QuotePricer(cfg.RHC_STABLE_USD)
        self.reserves = {}               # pool_pk -> (r0, r1) latest v2 reserves
        self.tracked = set()
        self.raw_swap_pools = set()      # Phase 4 sets this for open paper positions
        self.next_block = None
        self.last_to = None              # (block, hash)
        self.chunk_ends = []             # [(block, ts, hash)] since last durable checkpoint
        self.paused = False              # set by the storage guard
        self.stop_event = threading.Event()
        self.ref_pool = cfg.RHC_ETH_USD_REF_POOL
        self._last_review = 0.0
        self._last_progress_log = 0.0
        self.write_gate = lambda: True     # service sets this to "writer lease held"
        self.always_track = set()          # watch-listed pools (set by the screener) stay tracked
        self.recent_liq_adds = {}          # pool_pk -> ts of the last large priced liquidity add
        self.last_price = {}               # pool_pk -> (latest trade price_usd, ts), for cross-checks
        self.resync_needed = False
        self._pending_last_swap = {}
        self.metrics = {"chunks": 0, "logs": 0, "trades": 0, "candles_written": 0, "liq_events": 0,
                        "head": None, "processed_block": None, "processed_ts": None, "lag_blocks": None,
                        "lag_s": None, "last_error": None, "last_error_at": None, "mode": "init",
                        "reorgs": 0, "decode_skipped": 0, "started_at": int(clock())}

    # ── bootstrap ────────────────────────────────────────────────────────────
    def bootstrap(self):
        head = self.rpc.block_number() - cfg.RHC_CONFIRMATIONS
        self.registry.load(since_ts=int(self.clock()) - 7 * 86400)
        self.tracked = self.registry.tracked_pks()
        self._ensure_reference_pool()
        cp = self.store.load_checkpoint(self.stream) if self.durable else None
        if cp is None:
            self._fresh_start(head, reason=None)
        elif head - cp["block"] > cfg.RHC_MAX_CATCHUP_BLOCKS:
            start = head - cfg.RHC_START_LOOKBACK_BLOCKS
            self.store.record_gap(self.stream, cp["block"] + 1, start - 1, "downtime_exceeds_max_catchup")
            log.warning("checkpoint %s too old (head %s): gap recorded, restarting near head", cp["block"], head)
            self._fresh_start(head, reason="gap")
        else:
            self.next_block = cp["block"] + 1
            self.book.skip_before_ts = cp["resume_from_ts"]
            self.last_to = (cp["block"], cp["block_hash"])
            log.info("resuming from block %s (skip trades before ts %s)", self.next_block, cp["resume_from_ts"])
        self._seed_eth_price()
        # Activity is in-memory and empty after a restart: give already-tracked pools a
        # fresh idle window instead of untracking them on the first review.
        seed_ts = self.book.skip_before_ts or int(self.clock())
        for pk in self.tracked:
            self.activity.last_ts.setdefault(pk, seed_ts)

    def _fresh_start(self, head, reason):
        start = max(1, head - cfg.RHC_START_LOOKBACK_BLOCKS)
        blk = self.rpc.get_block(start)
        ts = int(blk["timestamp"], 16)
        self.next_block = start
        # Skip the partial first bucket so no incomplete candle is ever written.
        self.book.skip_before_ts = ceil_to(ts, TF_5M)
        self.last_to = None
        if self.durable:
            self.store.save_checkpoint(self.stream, start - 1, ts, None, self.book.skip_before_ts)
        log.info("fresh start at block %s (%s), first full bucket ts %s", start, reason or "new", self.book.skip_before_ts)

    def _ensure_reference_pool(self):
        self.registry.resolve({self.ref_pool: "v3"})
        m = self.registry.get(self.ref_pool)
        if m is None or m.pk is None:
            log.warning("ETH/USD reference pool %s not resolvable", self.ref_pool)
            return
        if m.pk not in self.tracked:
            self.tracked.add(m.pk)
            self.store.set_tracked({m.pk}, set(), int(self.clock()))
            m.tracked = True

    def _seed_eth_price(self):
        m = self.registry.get(self.ref_pool)
        if m is None or m.dec0 is None:
            return
        try:
            res = self.rpc.eth_call(self.ref_pool, V3_SLOT0)
            sqrtp = int(res[2:66], 16)
            from rhc_decoders import price1_per_0_from_sqrt
            p10 = price1_per_0_from_sqrt(sqrtp, m.dec0, m.dec1)
            price = p10 if m.base_index == 0 else (1.0 / p10 if p10 else None)
            if price and m.quote_class == "stable":
                self.pricer.set_eth_usd(price * cfg.RHC_STABLE_USD, int(self.clock()))
        except Exception as e:
            log.warning("could not seed ETH price: %s", e)

    # ── main loop ────────────────────────────────────────────────────────────
    def run_forever(self):
        backoff = 1.0
        while not self.stop_event.is_set():
            try:
                if self.paused:
                    self.metrics["mode"] = "paused_storage"
                    self.stop_event.wait(30)
                    continue
                did = self.step()
                backoff = 1.0
                if not did:
                    self.stop_event.wait(cfg.RHC_POLL_INTERVAL_S)
            except Exception as e:
                self.metrics["last_error"] = f"{type(e).__name__}: {str(e)[:300]}"
                self.metrics["last_error_at"] = int(self.clock())
                log.exception("indexer step failed")
                # A failed step may have half-updated in-memory state (e.g. trades already in the
                # candle book). Retrying the same range would double-count, so always rewind.
                self.resync_needed = True
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, 60.0)

    def step(self):
        if not self.write_gate():
            self.metrics["mode"] = "standby_no_lease"
            return False
        if self.resync_needed:
            self.resync_needed = False
            self._resync_from_checkpoint("resync requested (failed step or lease change)")
            return True
        calls = [("eth_blockNumber", [])]
        if self.last_to and self.last_to[1]:
            calls.append(("eth_getBlockByNumber", [hex(self.last_to[0]), False]))
        res = self.rpc.batch(calls)
        if isinstance(res[0], Exception):
            raise res[0]
        chain_head = int(res[0], 16)
        head = chain_head - cfg.RHC_CONFIRMATIONS
        self.metrics["head"] = chain_head
        if len(res) > 1 and isinstance(res[1], dict) and res[1].get("hash") != self.last_to[1]:
            self._handle_reorg()
            return True
        if self.next_block > head:
            self.metrics["lag_blocks"] = max(0, chain_head - (self.next_block - 1))
            self._maybe_review()
            return False
        lag = head - self.next_block
        catchup = lag > cfg.RHC_LIVE_CHUNK_BLOCKS * 2
        self.metrics["mode"] = "catchup" if catchup else "live"
        chunk = cfg.RHC_CATCHUP_CHUNK_BLOCKS if catchup else cfg.RHC_LIVE_CHUNK_BLOCKS
        to = min(head, self.next_block + chunk - 1)
        logs = self.rpc.get_logs({"topics": [ALL_TOPICS]}, self.next_block, to, max_span=cfg.RHC_GETLOGS_TOPIC_SPAN)
        self.process_range(self.next_block, to, logs, resolve_traders=(not catchup) and cfg.RHC_RESOLVE_TRADERS)
        self.metrics["lag_blocks"] = max(0, chain_head - to)
        self._maybe_review()
        return True

    def _handle_reorg(self):
        self.metrics["reorgs"] += 1
        self._resync_from_checkpoint(f"reorg at {self.last_to}")

    def _resync_from_checkpoint(self, reason):
        """Drop in-memory state and continue from the durable checkpoint (idempotent re-processing)."""
        cp = self.store.load_checkpoint(self.stream)
        log.warning("%s: rewinding to durable checkpoint %s", reason, cp and cp["block"])
        self.book.reset()
        # Replayed trades would otherwise be counted twice in the rolling tracking stats.
        self.activity.reset()
        seed_ts = (cp or {}).get("resume_from_ts") or int(self.clock())
        for pk in self.tracked:
            self.activity.last_ts[pk] = seed_ts
        self.reserves.clear()
        self.chunk_ends.clear()
        if cp:
            self.next_block = cp["block"] + 1
            self.book.skip_before_ts = cp["resume_from_ts"]
            self.last_to = (cp["block"], cp["block_hash"])
        else:
            self._fresh_start(self.rpc.block_number() - cfg.RHC_CONFIRMATIONS, reason="reorg")

    # ── timestamps ───────────────────────────────────────────────────────────
    def _timestamps(self, blocks, frm, to):
        """Exact timestamps for small ranges; sampled + interpolated for big ranges."""
        want = sorted(set(blocks) | {to})
        if (to - frm) <= cfg.RHC_EXACT_TS_MAX_BLOCKS or len(want) <= 40:
            fetch = want
        else:
            step = cfg.RHC_TS_SAMPLE_STEP
            fetch = sorted(set(range(frm, to + 1, step)) | {frm, to})
        res = self.rpc.batch([("eth_getBlockByNumber", [hex(b), False]) for b in fetch])
        known = {}
        hashes = {}
        for b, r in zip(fetch, res):
            if isinstance(r, dict):
                known[b] = int(r["timestamp"], 16)
                hashes[b] = r.get("hash")
        if to not in known:
            raise RuntimeError(f"timestamp for block {to} unavailable")
        if fetch is want:
            missing = [b for b in want if b not in known]
            if missing:
                raise RuntimeError(f"missing timestamps for {len(missing)} blocks")
            return known, hashes.get(to)
        pts = sorted(known.items())
        out = {}
        j = 0
        for b in want:
            while j + 1 < len(pts) and pts[j + 1][0] <= b:
                j += 1
            b0, t0 = pts[j]
            if b == b0 or j + 1 >= len(pts):
                out[b] = t0
            else:
                b1, t1 = pts[j + 1]
                out[b] = int(t0 + (t1 - t0) * (b - b0) / (b1 - b0))
        return out, hashes.get(to)

    # ── processing ───────────────────────────────────────────────────────────
    def process_range(self, frm, to, logs, resolve_traders=True):
        events = []
        for lg in logs:
            ev = decode_log(lg, self.managers)
            if ev is None:
                self.metrics["decode_skipped"] += 1
                continue
            events.append(ev)
        events.sort(key=lambda e: (e.ref.block, e.ref.log_index))
        ts_by_block, to_hash = self._timestamps([e.ref.block for e in events], frm, to)
        to_ts = ts_by_block[to]

        created = [e for e in events if isinstance(e, PoolCreatedEv)]
        if created:
            self.registry.register_created(created, ts_by_block)
        refs = {}
        for e in events:
            if isinstance(e, (SwapEv, LiquidityEv)):
                refs.setdefault(e.pool_id, e.kind)
            elif isinstance(e, SyncEv):
                refs.setdefault(e.pool_id, "v2")
        if refs:
            self.registry.resolve(refs)

        trades, liq_rows = [], []
        for e in events:
            if isinstance(e, PoolCreatedEv):
                continue
            meta = self.registry.get(e.pool_id)
            if meta is None or not meta.supported or meta.pk is None:
                continue
            ts = ts_by_block[e.ref.block]
            if isinstance(e, SyncEv):
                self.reserves[meta.pk] = (e.reserve0, e.reserve1)
            elif isinstance(e, SwapEv):
                t = swap_to_trade(meta, e, ts, self.pricer.usd(meta.quote_class), self.reserves.get(meta.pk))
                if t is None or (t.usd or 0) > cfg.RHC_MAX_TRADE_USD_SANITY:
                    continue
                if meta.pool_id == self.ref_pool and meta.quote_class == "stable":
                    self.pricer.set_eth_usd(t.price_usd, ts)
                if t.exec_usd:
                    # Sources report the last trade's execution price, so compare like with like.
                    self.last_price[meta.pk] = (t.exec_usd, ts)
                trades.append(t)
            elif isinstance(e, LiquidityEv) and meta.pk in self.tracked:
                row = self._liq_row(meta, e, ts)
                big_add = e.action == "add" and row["usd"] is not None and row["usd"] >= cfg.RHC_LIQ_ADD_MIN_USD
                if big_add:
                    self.recent_liq_adds[meta.pk] = ts
                if e.action == "remove" or cfg.RHC_LIQ_STORE_ALL_ADDS or big_add:
                    liq_rows.append(row)

        if resolve_traders:
            self._resolve_traders([t for t in trades if t.pool_pk in self.tracked])
        for t in trades:
            self.activity.add(t)
            self.book.add_trade(t)
            self._pending_last_swap[t.pool_pk] = max(self._pending_last_swap.get(t.pool_pk, 0), t.ts)

        if not self.write_gate():
            # Lease lost mid-chunk: write nothing and discard in-memory state; when the lease is
            # back we resume from the durable checkpoint.
            self.resync_needed = True
            raise WriterLeaseLost("writer lease not held; chunk discarded")
        closed = self.book.close_until(to_ts, keep_ring_for=self._ring_pools(to_ts))
        rows = [c.to_row() for c in closed if c.pool_pk in self.tracked]
        if rows:
            self.metrics["candles_written"] += self.store.upsert_candles(rows)
        if liq_rows:
            self.store.insert_liquidity(liq_rows)
            self.metrics["liq_events"] += len(liq_rows)
        raw = [self._swap_row(t) for t in trades if t.pool_pk in self.raw_swap_pools]
        if raw:
            self.store.insert_swaps(raw)

        self.chunk_ends.append((to, to_ts, to_hash))
        if self.durable:
            self._save_durable_checkpoint(to_ts)
        else:
            self.chunk_ends = self.chunk_ends[-5:]
        self.next_block = to + 1
        self.last_to = (to, to_hash)
        self.metrics.update(chunks=self.metrics["chunks"] + 1, logs=self.metrics["logs"] + len(logs),
                            trades=self.metrics["trades"] + len(trades), processed_block=to, processed_ts=to_ts,
                            lag_s=max(0, int(self.clock()) - to_ts))
        now = self.clock()
        if now - self._last_progress_log >= 60:
            self._last_progress_log = now
            log.info("progress: block %s lag %ss mode %s | trades %s candles %s tracked %s pools %s eth $%s",
                     to, self.metrics["lag_s"], self.metrics["mode"], self.metrics["trades"],
                     self.metrics["candles_written"], len(self.tracked), len(self.registry.by_id),
                     round(self.pricer.eth_usd, 2) if self.pricer.eth_usd else None)

    def _save_durable_checkpoint(self, to_ts):
        s = self.book.oldest_open_start(TF_5M, to_ts)
        if self.book.skip_before_ts is not None:
            s = max(s, min(self.book.skip_before_ts, ceil_to(to_ts, TF_5M)))
        eligible = [ce for ce in self.chunk_ends if ce[1] < s]
        if not eligible:
            return
        blk, ts, h = eligible[-1]
        self.store.save_checkpoint(self.stream, blk, ts, h, s)
        self.chunk_ends = [ce for ce in self.chunk_ends if ce[0] > blk]

    def _ring_pools(self, now_ts):
        stats = self.activity.stats(now_ts)
        return {pk for pk, (usd, _, _) in stats.items() if usd >= cfg.RHC_RING_MIN_VOL_USD_1H} | self.tracked

    def _resolve_traders(self, trades):
        txs = sorted({t.tx for t in trades})
        if not txs:
            return
        try:
            res = self.rpc.batch([("eth_getTransactionByHash", [h]) for h in txs])
        except Exception as e:
            log.warning("trader resolution failed: %s", e)
            return
        frm = {h: (r.get("from") or "").lower() for h, r in zip(txs, res) if isinstance(r, dict)}
        for t in trades:
            t.trader = frm.get(t.tx) or None

    def _liq_row(self, meta, e, ts):
        a0 = e.amount0 / 10 ** meta.dec0 if e.amount0 is not None else None
        a1 = e.amount1 / 10 ** meta.dec1 if e.amount1 is not None else None
        usd = None
        qusd = self.pricer.usd(meta.quote_class)
        if qusd:
            qa = a1 if meta.base_index == 0 else a0
            if qa is not None:
                usd = 2.0 * qa * qusd
        return {"tx_hash": e.ref.tx, "log_index": e.ref.log_index, "pool_pk": meta.pk, "block": e.ref.block, "ts": ts,
                "action": e.action, "amount0": a0, "amount1": a1,
                "liquidity_delta": float(e.liquidity_delta) if e.liquidity_delta is not None else None, "usd": usd}

    @staticmethod
    def _swap_row(t):
        return {"tx_hash": t.tx, "log_index": t.log_index, "pool_pk": t.pool_pk, "block": t.block, "ts": t.ts,
                "side": t.side, "base_amt": t.base_amt, "quote_amt": t.quote_amt, "price_usd": t.price_usd,
                "usd": t.usd, "trader": t.trader}

    # ── tracking review ──────────────────────────────────────────────────────
    def _maybe_review(self):
        now = self.clock()
        if now - self._last_review < cfg.RHC_TRACK_REVIEW_S:
            return
        self._last_review = now
        chain_now = self.metrics.get("processed_ts") or int(now)
        stats = self.activity.stats(chain_now)
        for pk in self.tracked:
            if pk not in stats:
                stats[pk] = (0.0, 0, self.activity.last_ts.get(pk, 0))
        ref = self.registry.get(self.ref_pool)
        always = {ref.pk} if ref and ref.pk else set()
        always |= set(list(self.always_track)[:cfg.RHC_WATCH_MAX])
        new = select_tracked(self.tracked, stats, always, chain_now, cfg.RHC_MAX_TRACKED_POOLS,
                             cfg.RHC_TRACK_MIN_VOL_USD_1H, cfg.RHC_TRACK_MIN_SWAPS_1H, cfg.RHC_UNTRACK_IDLE_MIN)
        added, removed = new - self.tracked, self.tracked - new
        if added or removed:
            self.store.set_tracked(added, removed, int(chain_now))
            for pk in added:
                m = self.registry.by_pk.get(pk)
                if m:
                    m.tracked = True
                ring = [c.to_row() for c in self.book.ring(pk)]
                if ring:
                    self.metrics["candles_written"] += self.store.upsert_candles(ring)
            for pk in removed:
                m = self.registry.by_pk.get(pk)
                if m:
                    m.tracked = False
            self.tracked = new
            log.info("tracking: +%d -%d -> %d pools", len(added), len(removed), len(new))
        if self._pending_last_swap:
            # All supported pools (not only tracked): lets the registry trimmer tell live pools from dead ones.
            self.store.update_last_swap(dict(self._pending_last_swap))
            self._pending_last_swap.clear()
        self.book.drop_rings_except(self._ring_pools(chain_now))

    # ── backfill ─────────────────────────────────────────────────────────────
    def backfill(self, frm, to):
        """Rebuild candles of currently tracked pools for [frm, to]. Edge buckets that
        cannot be complete are skipped; the live checkpoint is untouched."""
        self.durable = False
        first = self.rpc.get_block(frm)
        self.book.skip_before_ts = ceil_to(int(first["timestamp"], 16), TF_5M)
        self._seed_eth_price()
        cur = frm
        while cur <= to and not self.stop_event.is_set():
            end = min(to, cur + cfg.RHC_CATCHUP_CHUNK_BLOCKS - 1)
            logs = self.rpc.get_logs({"topics": [ALL_TOPICS]}, cur, end, max_span=cfg.RHC_GETLOGS_TOPIC_SPAN)
            self.process_range(cur, end, logs, resolve_traders=False)
            cur = end + 1
        # Remaining open candles are incomplete at the right edge -> dropped.
        self.book.reset()


def _cli():
    import rhc_service
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if len(sys.argv) < 2 or sys.argv[1] not in ("run", "backfill-gap", "backfill-range"):
        print(__doc__)
        return 2
    if sys.argv[1] == "run":
        return rhc_service.run_standalone()
    store, rpc, reg = rhc_service.build_components()
    idx = Indexer(rpc, store, reg, stream="backfill", durable=False)
    reg.load(since_ts=int(time.time()) - 7 * 86400)
    idx.tracked = reg.tracked_pks()
    if sys.argv[1] == "backfill-gap":
        gap = store.get_gap(int(sys.argv[2]))
        if not gap:
            print("gap not found")
            return 1
        idx.backfill(gap["start_block"], gap["end_block"])
        store.mark_gap_filled(gap["id"])
    else:
        idx.backfill(int(sys.argv[2]), int(sys.argv[3]))
    print("backfill done", idx.metrics)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
