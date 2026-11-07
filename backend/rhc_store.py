"""Persistence layer for RHC (dedicated database only). All writes are idempotent
upserts keyed on natural keys, so re-processing a block range is safe."""
import json
import logging
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

import rhc_db
from rhc_market import PoolMeta
from rhc_models import (RhcCandle, RhcCheckpoint, RhcGap, RhcKv, RhcLiquidityEvent, RhcPool, RhcSourceHealth,
                        RhcSourceSnapshot, RhcSwap, RhcToken)

log = logging.getLogger("rhc.store")
CHUNK = 500


def _chunks(rows, n=CHUNK):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


class Store:
    # ── checkpoints ──────────────────────────────────────────────────────────
    def load_checkpoint(self, stream):
        with rhc_db.session_scope() as s:
            r = s.get(RhcCheckpoint, stream)
            if r is None:
                return None
            return {"block": r.block, "block_ts": r.block_ts, "block_hash": r.block_hash,
                    "resume_from_ts": r.resume_from_ts}

    def save_checkpoint(self, stream, block, block_ts, block_hash, resume_from_ts):
        stmt = pg_insert(RhcCheckpoint).values(stream=stream, block=block, block_ts=block_ts, block_hash=block_hash,
                                               resume_from_ts=resume_from_ts, updated_at=datetime.utcnow())
        stmt = stmt.on_conflict_do_update(index_elements=["stream"], set_={
            "block": stmt.excluded.block, "block_ts": stmt.excluded.block_ts, "block_hash": stmt.excluded.block_hash,
            "resume_from_ts": stmt.excluded.resume_from_ts, "updated_at": stmt.excluded.updated_at})
        with rhc_db.session_scope() as s:
            s.execute(stmt)

    # ── tokens / pools ───────────────────────────────────────────────────────
    def upsert_tokens(self, rows):
        if not rows:
            return
        with rhc_db.session_scope() as s:
            for ch in _chunks(rows):
                stmt = pg_insert(RhcToken).values(ch)
                s.execute(stmt.on_conflict_do_update(index_elements=["address"], set_={
                    "symbol": stmt.excluded.symbol, "decimals": stmt.excluded.decimals}))

    def load_tokens(self, addresses):
        if not addresses:
            return {}
        out = {}
        with rhc_db.session_scope() as s:
            for ch in _chunks(list(addresses)):
                for r in s.execute(select(RhcToken.address, RhcToken.decimals, RhcToken.symbol)
                                   .where(RhcToken.address.in_(ch))):
                    out[r[0]] = (r[1], r[2])
        return out

    def upsert_pools(self, metas, created=None):
        """Insert pools (or refresh classification). Returns {pool_id: pk}.
        created: {pool_id: (block, ts, via)}"""
        if not metas:
            return {}
        created = created or {}
        rows = []
        for m in metas:
            blk, ts, via = created.get(m.pool_id, (None, None, "on_demand"))
            rows.append({
                "pool_id": m.pool_id, "kind": m.kind, "venue": m.venue, "hooks": m.hooks,
                "token0": m.token0, "token1": m.token1, "fee": m.fee, "tick_spacing": None,
                "base_index": m.base_index, "quote_token": m.quote_token, "quote_class": m.quote_class,
                "supported": bool(m.supported), "reason": m.reason, "created_block": blk, "created_ts": ts,
                "discovered_via": via, "tracked": False,
            })
        out = {}
        with rhc_db.session_scope() as s:
            for ch in _chunks(rows):
                stmt = pg_insert(RhcPool).values(ch)
                stmt = stmt.on_conflict_do_update(index_elements=["pool_id"], set_={
                    "base_index": stmt.excluded.base_index, "quote_token": stmt.excluded.quote_token,
                    "quote_class": stmt.excluded.quote_class, "supported": stmt.excluded.supported,
                    "reason": stmt.excluded.reason,
                    "created_block": func.coalesce(RhcPool.created_block, stmt.excluded.created_block),
                    "created_ts": func.coalesce(RhcPool.created_ts, stmt.excluded.created_ts),
                }).returning(RhcPool.id, RhcPool.pool_id)
                for pk, pid in s.execute(stmt):
                    out[pid] = pk
        return out

    def _rows_to_meta(self, rows, tokens):
        metas = []
        for p in rows:
            d0 = tokens.get(p.token0, (None, None))[0]
            d1 = tokens.get(p.token1, (None, None))[0]
            metas.append(PoolMeta(pool_id=p.pool_id, kind=p.kind, token0=p.token0, token1=p.token1, dec0=d0, dec1=d1,
                                  venue=p.venue, hooks=p.hooks, fee=p.fee, base_index=p.base_index,
                                  quote_token=p.quote_token, quote_class=p.quote_class, supported=p.supported,
                                  reason=p.reason, pk=p.id, tracked=p.tracked))
        return metas

    def load_pools_by_ids(self, pool_ids):
        if not pool_ids:
            return []
        rows = []
        with rhc_db.session_scope() as s:
            for ch in _chunks(list(pool_ids)):
                rows.extend(s.execute(select(RhcPool).where(RhcPool.pool_id.in_(ch))).scalars().all())
            s.expunge_all()
        tokens = self.load_tokens({p.token0 for p in rows} | {p.token1 for p in rows})
        return self._rows_to_meta(rows, tokens)

    def load_active_pools(self, since_ts):
        with rhc_db.session_scope() as s:
            rows = s.execute(select(RhcPool).where(or_(RhcPool.tracked.is_(True), RhcPool.last_swap_ts >= since_ts,
                                                       RhcPool.created_ts >= since_ts))).scalars().all()
            s.expunge_all()
        tokens = self.load_tokens({p.token0 for p in rows} | {p.token1 for p in rows})
        return self._rows_to_meta(rows, tokens)

    def set_tracked(self, added, removed, ts):
        with rhc_db.session_scope() as s:
            if added:
                s.execute(update(RhcPool).where(RhcPool.id.in_(list(added)))
                          .values(tracked=True, tracked_since=ts))
            if removed:
                s.execute(update(RhcPool).where(RhcPool.id.in_(list(removed))).values(tracked=False))

    def update_last_swap(self, pk_ts):
        if not pk_ts:
            return
        with rhc_db.session_scope() as s:
            for pk, ts in pk_ts.items():
                s.execute(update(RhcPool).where(RhcPool.id == pk)
                          .values(last_swap_ts=func.greatest(func.coalesce(RhcPool.last_swap_ts, 0), ts)))

    # ── market data ──────────────────────────────────────────────────────────
    def upsert_candles(self, rows):
        if not rows:
            return 0
        cols = ["o", "h", "l", "c", "c_usd", "vol_usd", "buys", "sells", "buy_usd", "sell_usd", "traders",
                "traders_exact", "large", "liq", "liq_usd"]
        with rhc_db.session_scope() as s:
            for ch in _chunks(rows):
                stmt = pg_insert(RhcCandle).values(ch)
                s.execute(stmt.on_conflict_do_update(index_elements=["pool_pk", "tf", "bucket"],
                                                     set_={c: getattr(stmt.excluded, c) for c in cols}))
        return len(rows)

    def insert_liquidity(self, rows):
        if not rows:
            return
        with rhc_db.session_scope() as s:
            for ch in _chunks(rows):
                s.execute(pg_insert(RhcLiquidityEvent).values(ch).on_conflict_do_nothing())

    def insert_swaps(self, rows):
        if not rows:
            return
        with rhc_db.session_scope() as s:
            for ch in _chunks(rows):
                s.execute(pg_insert(RhcSwap).values(ch).on_conflict_do_nothing())

    # ── gaps ─────────────────────────────────────────────────────────────────
    def record_gap(self, stream, start_block, end_block, reason):
        with rhc_db.session_scope() as s:
            g = RhcGap(stream=stream, start_block=start_block, end_block=end_block, reason=reason)
            s.add(g)
            s.flush()
            return g.id

    def mark_gap_filled(self, gap_id):
        with rhc_db.session_scope() as s:
            s.execute(update(RhcGap).where(RhcGap.id == gap_id).values(filled_at=datetime.utcnow()))

    def list_gaps(self, limit=100):
        with rhc_db.session_scope() as s:
            rows = s.execute(select(RhcGap).order_by(RhcGap.id.desc()).limit(limit)).scalars().all()
            return [{"id": g.id, "stream": g.stream, "start_block": g.start_block, "end_block": g.end_block,
                     "reason": g.reason, "detected_at": g.detected_at.isoformat() if g.detected_at else None,
                     "filled_at": g.filled_at.isoformat() if g.filled_at else None} for g in rows]

    def get_gap(self, gap_id):
        with rhc_db.session_scope() as s:
            g = s.get(RhcGap, gap_id)
            return None if g is None else {"id": g.id, "start_block": g.start_block, "end_block": g.end_block,
                                           "filled_at": g.filled_at}

    # ── sources ──────────────────────────────────────────────────────────────
    def insert_snapshots(self, rows):
        if not rows:
            return
        with rhc_db.session_scope() as s:
            s.execute(pg_insert(RhcSourceSnapshot).values(rows))

    def upsert_source_health(self, rows):
        if not rows:
            return
        with rhc_db.session_scope() as s:
            stmt = pg_insert(RhcSourceHealth).values(rows)
            s.execute(stmt.on_conflict_do_update(index_elements=["source"], set_={
                c: getattr(stmt.excluded, c) for c in ("ok_count", "err_count", "last_ok_ts", "last_err_ts",
                                                       "last_err", "last_latency_ms", "updated_at")}))

    def kv_set(self, key, value):
        stmt = pg_insert(RhcKv).values(key=key, value=json.dumps(value)[:2000], updated_at=datetime.utcnow())
        with rhc_db.session_scope() as s:
            s.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
                "value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at}))

    def kv_get(self, key):
        with rhc_db.session_scope() as s:
            r = s.get(RhcKv, key)
            return json.loads(r.value) if r and r.value else None

    # ── read API ─────────────────────────────────────────────────────────────
    def latest_close_usd(self, pks, tf=60):
        if not pks:
            return {}
        q = text("select distinct on (pool_pk) pool_pk, c_usd, bucket from rhc_candle "
                 "where tf = :tf and pool_pk = any(:pks) order by pool_pk, bucket desc")
        with rhc_db.session_scope() as s:
            return {r[0]: (r[1], r[2]) for r in s.execute(q, {"tf": tf, "pks": list(pks)})}

    def tracked_pools(self, limit=200):
        q = text("""
            select p.id, p.pool_id, p.kind, p.venue, p.hooks, p.token0, p.token1, p.base_index, p.quote_class,
                   p.tracked_since, p.last_swap_ts, p.created_ts,
                   t.symbol as base_symbol,
                   case when p.quote_token = '0x0000000000000000000000000000000000000000' then 'ETH'
                        else qt.symbol end as quote_symbol
            from rhc_pool p
            left join rhc_token t on t.address = case when p.base_index = 0 then p.token0 else p.token1 end
            left join rhc_token qt on qt.address = p.quote_token
            where p.tracked order by p.last_swap_ts desc nulls last limit :lim""")
        with rhc_db.session_scope() as s:
            return [dict(r._mapping) for r in s.execute(q, {"lim": limit})]

    def candles(self, pool_pk, tf, limit=500, before=None):
        q = select(RhcCandle).where(RhcCandle.pool_pk == pool_pk, RhcCandle.tf == tf)
        if before:
            q = q.where(RhcCandle.bucket < before)
        q = q.order_by(RhcCandle.bucket.desc()).limit(limit)
        with rhc_db.session_scope() as s:
            rows = s.execute(q).scalars().all()
            return [{c.name: getattr(r, c.name) for c in RhcCandle.__table__.columns} for r in reversed(rows)]

    def pool_pk(self, pool_id):
        with rhc_db.session_scope() as s:
            return s.execute(select(RhcPool.id).where(RhcPool.pool_id == pool_id.lower())).scalar()

    def snapshots(self, pool_pk, limit=100):
        with rhc_db.session_scope() as s:
            rows = s.execute(select(RhcSourceSnapshot).where(RhcSourceSnapshot.pool_pk == pool_pk)
                             .order_by(RhcSourceSnapshot.ts.desc()).limit(limit)).scalars().all()
            return [{c.name: getattr(r, c.name) for c in RhcSourceSnapshot.__table__.columns} for r in rows]

    def counts(self):
        q = text("select (select count(*) from rhc_pool), (select count(*) from rhc_pool where tracked), "
                 "(select count(*) from rhc_candle), (select count(*) from rhc_token)")
        with rhc_db.session_scope() as s:
            p, t, c, k = s.execute(q).one()
            return {"pools": p, "tracked": t, "candles": c, "tokens": k}

    # ── retention ────────────────────────────────────────────────────────────
    def prune(self, now_ts, retain_1m_h, retain_liq_d, retain_snap_d, retain_swap_h):
        with rhc_db.session_scope() as s:
            res = {
                "candle_1m": s.execute(delete(RhcCandle).where(
                    and_(RhcCandle.tf == 60, RhcCandle.bucket < now_ts - retain_1m_h * 3600))).rowcount,
                "liquidity": s.execute(delete(RhcLiquidityEvent).where(
                    RhcLiquidityEvent.ts < now_ts - retain_liq_d * 86400)).rowcount,
                "snapshot": s.execute(delete(RhcSourceSnapshot).where(
                    RhcSourceSnapshot.ts < now_ts - retain_snap_d * 86400)).rowcount,
                "swap": s.execute(delete(RhcSwap).where(RhcSwap.ts < now_ts - retain_swap_h * 3600)).rowcount,
            }
        return res

    def rollup_5m_to_15m(self, older_than_ts):
        """Aggregate 5m candles older than the cutoff into 15m candles, then delete them."""
        sql = text("""
            insert into rhc_candle (pool_pk, tf, bucket, o, h, l, c, c_usd, vol_usd, buys, sells, buy_usd, sell_usd,
                                    traders, traders_exact, large, liq, liq_usd)
            select pool_pk, 900, (bucket / 900) * 900,
                   (array_agg(o order by bucket))[1], max(h), min(l), (array_agg(c order by bucket desc))[1],
                   (array_agg(c_usd order by bucket desc))[1], sum(vol_usd), sum(buys), sum(sells),
                   sum(buy_usd), sum(sell_usd), max(traders), false, sum(large),
                   (array_agg(liq order by bucket desc))[1], (array_agg(liq_usd order by bucket desc))[1]
            from rhc_candle where tf = 300 and bucket < :cut
            group by pool_pk, (bucket / 900) * 900
            on conflict (pool_pk, tf, bucket) do nothing""")
        with rhc_db.session_scope() as s:
            s.execute(sql, {"cut": older_than_ts})
            n = s.execute(delete(RhcCandle).where(and_(RhcCandle.tf == 300, RhcCandle.bucket < older_than_ts))).rowcount
        return n
