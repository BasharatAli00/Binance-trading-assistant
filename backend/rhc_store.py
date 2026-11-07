"""Persistence layer for RHC (dedicated database only). All writes are idempotent
upserts keyed on natural keys, so re-processing a block range is safe."""
import json
import logging
import time
from datetime import datetime

from sqlalchemy import and_, case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

import rhc_db
from rhc_market import PoolMeta
from rhc_models import (RhcBacktestRun, RhcCandle, RhcCheckpoint, RhcDecision, RhcGap, RhcKv, RhcLiquidityEvent,
                        RhcPaperFill, RhcPaperPosition, RhcPool, RhcScreen, RhcSourceHealth, RhcSourceSnapshot,
                        RhcSwap, RhcToken, RhcWalletPosition, RhcWalletTrade, RhcWatch)

log = logging.getLogger("rhc.store")
CHUNK = 500

# Methods that are safe to repeat after a dropped connection: reads and idempotent upserts
# (ON CONFLICT ... / UPDATE ... to the same values). Plain INSERTs (decisions, paper fills and
# positions, screens, snapshots, gaps, backtest runs) are deliberately NOT retried - a commit that
# failed ambiguously could otherwise be applied twice.
_RETRY_SAFE = [
    "load_checkpoint", "save_checkpoint", "upsert_tokens", "load_tokens", "upsert_pools", "load_pools_by_ids",
    "load_active_pools", "set_tracked", "update_last_swap", "upsert_candles", "insert_liquidity", "insert_swaps",
    "list_gaps", "get_gap", "upsert_source_health", "kv_set", "kv_get", "latest_close_usd", "tracked_pools",
    "candles", "pool_pk", "snapshots", "counts", "upsert_watch_candidates", "due_watch", "set_watch_state",
    "expire_stale", "watch_pks", "watchlist", "screens", "recent_lp_removals", "insert_wallet_trades",
    "wallet_trades_since", "wallet_trades_pool", "upsert_wallet_positions", "wallet_positions_since",
    "market_volume_5m", "pool_closes", "watch_tokens", "latest_screen_impact", "decisions",
    "update_paper_position", "load_open_paper_positions", "paper_positions", "paper_fills", "closed_paper_trades",
    "paper_realized_since", "paper_last_exit_by_token", "last_close_usd", "last_candle_usd", "watch_state",
    "latest_reject_is_permanent",
]


def _retrying(fn, attempts=3, delay_s=1.0):
    import functools
    from sqlalchemy.exc import DBAPIError, OperationalError

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        for i in range(attempts):
            try:
                return fn(*a, **kw)
            except (OperationalError, DBAPIError) as e:
                transient = isinstance(e, OperationalError) or getattr(e, "connection_invalidated", False)
                if not transient or i == attempts - 1:
                    raise
                log.warning("db %s failed (%s); retry %d/%d", fn.__name__, str(e).splitlines()[0][:120], i + 1,
                            attempts - 1)
                time.sleep(delay_s * (i + 1))
    return wrapper


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
                "token0": m.token0, "token1": m.token1, "fee": m.fee, "tick_spacing": m.tick_spacing,
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
                    "fee": func.coalesce(stmt.excluded.fee, RhcPool.fee),
                    "tick_spacing": func.coalesce(stmt.excluded.tick_spacing, RhcPool.tick_spacing),
                    "hooks": func.coalesce(stmt.excluded.hooks, RhcPool.hooks),
                    "created_block": func.coalesce(RhcPool.created_block, stmt.excluded.created_block),
                    "created_ts": func.coalesce(RhcPool.created_ts, stmt.excluded.created_ts),
                }).returning(RhcPool.id, RhcPool.pool_id)
                for pk, pid in s.execute(stmt):
                    out[pid] = pk
        return out

    def _rows_to_meta(self, rows, tokens):
        tokens = dict(tokens)
        tokens.setdefault("0x0000000000000000000000000000000000000000", (18, "ETH"))   # native ETH (v4)
        metas = []
        for p in rows:
            d0 = tokens.get(p.token0, (None, None))[0]
            d1 = tokens.get(p.token1, (None, None))[0]
            metas.append(PoolMeta(pool_id=p.pool_id, kind=p.kind, token0=p.token0, token1=p.token1, dec0=d0, dec1=d1,
                                  venue=p.venue, hooks=p.hooks, fee=p.fee, tick_spacing=p.tick_spacing,
                                  base_index=p.base_index,
                                  quote_token=p.quote_token, quote_class=p.quote_class, supported=p.supported,
                                  reason=p.reason, pk=p.id, tracked=p.tracked, created_block=p.created_block,
                                  created_ts=p.created_ts))
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
        """One statement for any number of pools."""
        if not pk_ts:
            return
        ids, tss = list(pk_ts.keys()), [int(v) for v in pk_ts.values()]
        with rhc_db.session_scope() as s:
            s.execute(text(
                "update rhc_pool p set last_swap_ts = greatest(coalesce(p.last_swap_ts, 0), v.ts) "
                "from unnest(cast(:ids as integer[]), cast(:tss as bigint[])) as v(id, ts) where p.id = v.id"),
                {"ids": ids, "tss": tss})

    # ── market data ──────────────────────────────────────────────────────────
    def upsert_candles(self, rows):
        if not rows:
            return 0
        cols = ["o", "h", "l", "c", "c_usd", "c_mid", "vol_usd", "buys", "sells", "buy_usd", "sell_usd", "traders",
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

    # ── watchlist & screening ────────────────────────────────────────────────
    def upsert_watch_candidates(self, rows, now_ts):
        """rows: [{pool_pk, token, discovery, score, last_activity_ts}]. New pools enter as candidates;
        expired ones are revived; existing states are kept."""
        if not rows:
            return
        with rhc_db.session_scope() as s:
            for ch in _chunks([dict(r, state="candidate", first_seen_ts=now_ts, next_screen_ts=now_ts, screens=0)
                               for r in rows]):
                stmt = pg_insert(RhcWatch).values(ch)
                s.execute(stmt.on_conflict_do_update(index_elements=["pool_pk"], set_={
                    "discovery": stmt.excluded.discovery, "score": stmt.excluded.score,
                    "last_activity_ts": stmt.excluded.last_activity_ts,
                    "state": case((RhcWatch.state == "expired", "candidate"), else_=RhcWatch.state),
                    "next_screen_ts": case((RhcWatch.state == "expired", stmt.excluded.next_screen_ts),
                                           else_=RhcWatch.next_screen_ts),
                }))

    def due_watch(self, now_ts, limit):
        with rhc_db.session_scope() as s:
            rows = s.execute(select(RhcWatch).where(RhcWatch.state.in_(["candidate", "watch", "rejected"]),
                                                    RhcWatch.next_screen_ts <= now_ts)
                             .order_by((RhcWatch.state != "candidate"), RhcWatch.score.desc()).limit(limit)
                             ).scalars().all()
            return [{c.name: getattr(r, c.name) for c in RhcWatch.__table__.columns} for r in rows]

    def save_screen(self, pool_pk, token, ts, verdict, rejects, warns, evidence, duration_ms, state, next_ts):
        with rhc_db.session_scope() as s:
            s.add(RhcScreen(pool_pk=pool_pk, token=token, ts=ts, verdict=verdict, reject_codes=",".join(rejects),
                            warn_codes=",".join(warns), evidence=json.dumps(evidence, default=str)[:6000],
                            duration_ms=duration_ms))
            s.execute(update(RhcWatch).where(RhcWatch.pool_pk == pool_pk).values(
                state=state, reject_codes=",".join(rejects), warn_codes=",".join(warns), last_screened_ts=ts,
                next_screen_ts=next_ts, screens=func.coalesce(RhcWatch.screens, 0) + 1))

    def set_watch_state(self, pool_pk, state):
        with rhc_db.session_scope() as s:
            s.execute(update(RhcWatch).where(RhcWatch.pool_pk == pool_pk).values(state=state))

    def expire_stale(self, cutoff_ts):
        with rhc_db.session_scope() as s:
            return s.execute(update(RhcWatch).where(RhcWatch.state != "expired",
                                                    RhcWatch.last_activity_ts < cutoff_ts)
                             .values(state="expired")).rowcount

    def watch_pks(self):
        with rhc_db.session_scope() as s:
            return {r[0] for r in s.execute(select(RhcWatch.pool_pk).where(RhcWatch.state == "watch"))}

    def watchlist(self, state=None, limit=200):
        q = """
            select w.pool_pk, p.pool_id, p.kind, w.token, t.symbol, w.state, w.discovery, w.score,
                   w.reject_codes, w.warn_codes, w.first_seen_ts, w.last_screened_ts, w.next_screen_ts,
                   w.last_activity_ts, w.screens
            from rhc_watchlist w join rhc_pool p on p.id = w.pool_pk left join rhc_token t on t.address = w.token
            where (cast(:state as text) is null or w.state = :state)
            order by w.score desc nulls last limit :lim"""
        with rhc_db.session_scope() as s:
            return [dict(r._mapping) for r in s.execute(text(q), {"state": state, "lim": limit})]

    def screens(self, pool_pk=None, verdict=None, limit=50):
        q = """
            select s.id, s.pool_pk, p.pool_id, s.token, t.symbol, s.ts, s.verdict, s.reject_codes, s.warn_codes,
                   s.evidence, s.duration_ms
            from rhc_screen s join rhc_pool p on p.id = s.pool_pk left join rhc_token t on t.address = s.token
            where (cast(:pk as integer) is null or s.pool_pk = :pk)
              and (cast(:verdict as text) is null or s.verdict = :verdict)
            order by s.ts desc limit :lim"""
        with rhc_db.session_scope() as s:
            out = []
            for r in s.execute(text(q), {"pk": pool_pk, "verdict": verdict, "lim": limit}):
                d = dict(r._mapping)
                try:
                    d["evidence"] = json.loads(d["evidence"]) if d["evidence"] else None
                except ValueError:
                    pass
                out.append(d)
            return out

    def recent_lp_removals(self, pool_pk, since_ts):
        with rhc_db.session_scope() as s:
            n, usd = s.execute(text("select count(*), coalesce(sum(usd), 0) from rhc_liquidity_event "
                                    "where pool_pk = :k and action = 'remove' and ts >= :t"),
                               {"k": pool_pk, "t": since_ts}).one()
            return int(n), float(usd)

    # ── wallets & decisions (Phase 3) ────────────────────────────────────────
    def insert_wallet_trades(self, rows):
        if not rows:
            return
        with rhc_db.session_scope() as s:
            for ch in _chunks(rows):
                s.execute(pg_insert(RhcWalletTrade).values(ch).on_conflict_do_nothing())

    @staticmethod
    def _wtrade_dicts(rows):
        return [{"wallet": r.wallet, "pool_pk": r.pool_pk, "ts": r.ts, "side": r.side, "base_amt": r.base_amt,
                 "usd": r.usd, "log_index": r.log_index} for r in rows]

    def wallet_trades_since(self, since_ts, limit=500_000):
        with rhc_db.session_scope() as s:
            rows = s.execute(select(RhcWalletTrade).where(RhcWalletTrade.ts >= since_ts)
                             .order_by(RhcWalletTrade.ts).limit(limit)).scalars().all()
            return self._wtrade_dicts(rows)

    def wallet_trades_pool(self, pool_pk, since_ts):
        with rhc_db.session_scope() as s:
            rows = s.execute(select(RhcWalletTrade).where(RhcWalletTrade.pool_pk == pool_pk,
                                                          RhcWalletTrade.ts >= since_ts)
                             .order_by(RhcWalletTrade.ts)).scalars().all()
            return self._wtrade_dicts(rows)

    def upsert_wallet_positions(self, closed):
        if not closed:
            return
        rows = [{"wallet": p.wallet, "pool_pk": p.pool_pk, "open_ts": p.open_ts, "close_ts": p.close_ts,
                 "cost_usd": p.cost_usd, "proceeds_usd": p.proceeds_usd} for p in closed]
        with rhc_db.session_scope() as s:
            for ch in _chunks(rows):
                stmt = pg_insert(RhcWalletPosition).values(ch)
                s.execute(stmt.on_conflict_do_update(index_elements=["wallet", "pool_pk", "open_ts"], set_={
                    "close_ts": stmt.excluded.close_ts, "cost_usd": stmt.excluded.cost_usd,
                    "proceeds_usd": stmt.excluded.proceeds_usd}))

    def wallet_positions_since(self, since_ts):
        from rhc_wallets import ClosedPosition
        with rhc_db.session_scope() as s:
            rows = s.execute(select(RhcWalletPosition).where(RhcWalletPosition.close_ts >= since_ts)).scalars().all()
            return [ClosedPosition(r.wallet, r.pool_pk, r.open_ts, r.close_ts, r.cost_usd or 0.0, r.proceeds_usd or 0.0)
                    for r in rows]

    def market_volume_5m(self, since_bucket):
        q = text("select bucket, sum(vol_usd) from rhc_candle where tf = 300 and bucket >= :b "
                 "group by bucket order by bucket")
        with rhc_db.session_scope() as s:
            return [(int(b), float(v or 0)) for b, v in s.execute(q, {"b": since_bucket})]

    def pool_closes(self, pool_pk, tf, since_bucket):
        q = text("select bucket, c_usd from rhc_candle where pool_pk = :k and tf = :tf and bucket >= :b "
                 "order by bucket")
        with rhc_db.session_scope() as s:
            return [(int(b), c) for b, c in s.execute(q, {"k": pool_pk, "tf": tf, "b": since_bucket})]

    def watch_tokens(self):
        with rhc_db.session_scope() as s:
            return {r[0]: r[1] for r in s.execute(select(RhcWatch.pool_pk, RhcWatch.token)
                                                  .where(RhcWatch.state == "watch"))}

    def latest_screen_impact(self, pool_pk):
        with rhc_db.session_scope() as s:
            ev = s.execute(select(RhcScreen.evidence).where(RhcScreen.pool_pk == pool_pk,
                                                            RhcScreen.verdict == "pass")
                           .order_by(RhcScreen.ts.desc()).limit(1)).scalar()
        try:
            return (json.loads(ev).get("simulation") or {}).get("impact") if ev else None
        except ValueError:
            return None

    def insert_decisions(self, rows, now_ts, broker_name):
        if not rows:
            return
        recs = [{"ts": now_ts, "as_of": d["as_of"], "pool_pk": d["pool_pk"], "token": d.get("token"),
                 "strategy": d["strategy"], "action": d["action"], "reasons": ",".join(d.get("reasons") or []),
                 "size_usd": d.get("size_usd"), "entry_ref": d.get("entry_ref"), "stop": d.get("stop"),
                 "targets": ",".join(f"{t:.12g}" for t in (d.get("targets") or [])), "mode": "paper",
                 "broker": broker_name,
                 "evidence": json.dumps(dict(d.get("evidence") or {}, broker_result=d.get("broker_result")),
                                        default=str)[:6000]} for d in rows]
        with rhc_db.session_scope() as s:
            s.execute(pg_insert(RhcDecision).values(recs))

    def decisions(self, pool_pk=None, action=None, limit=100):
        q = """
            select d.id, d.ts, d.as_of, d.pool_pk, p.pool_id, d.token, t.symbol, d.strategy, d.action, d.reasons,
                   d.size_usd, d.entry_ref, d.stop, d.targets, d.mode, d.broker, d.evidence
            from rhc_decision d join rhc_pool p on p.id = d.pool_pk left join rhc_token t on t.address = d.token
            where (cast(:pk as integer) is null or d.pool_pk = :pk)
              and (cast(:action as text) is null or d.action = :action)
            order by d.id desc limit :lim"""
        with rhc_db.session_scope() as s:
            out = []
            for r in s.execute(text(q), {"pk": pool_pk, "action": action, "lim": limit}):
                d = dict(r._mapping)
                try:
                    d["evidence"] = json.loads(d["evidence"]) if d["evidence"] else None
                except ValueError:
                    pass
                out.append(d)
            return out

    def prune_phase3(self, now_ts, wallet_trade_days, wallet_pos_days, decision_days):
        with rhc_db.session_scope() as s:
            s.execute(delete(RhcPaperFill).where(RhcPaperFill.ts < now_ts - 60 * 86400))
            return {
                "wallet_trades": s.execute(delete(RhcWalletTrade).where(
                    RhcWalletTrade.ts < now_ts - wallet_trade_days * 86400)).rowcount,
                "wallet_positions": s.execute(delete(RhcWalletPosition).where(
                    RhcWalletPosition.close_ts < now_ts - wallet_pos_days * 86400)).rowcount,
                "decisions": s.execute(delete(RhcDecision).where(
                    RhcDecision.ts < now_ts - decision_days * 86400)).rowcount,
            }

    # ── paper trading (Phase 4) ──────────────────────────────────────────────
    @staticmethod
    def _pos_row(p, intent=None):
        row = {"pool_pk": p.pool_pk, "token": p.token, "strategy": p.strategy, "regime": p.regime,
               "status": p.status, "opened_ts": p.opened_ts,
               "closed_ts": (p.legs[-1].ts if p.legs and p.status != "open" else None),
               "entry_price": p.entry_price, "tokens": p.tokens, "tokens_raw": str(p.tokens_raw),
               "cost_usd": p.cost_usd, "proceeds_usd": p.proceeds_usd, "realized_usd": p.realized_usd,
               "risk_usd": p.risk_usd, "stop": p.stop, "stop_pct": p.stop_pct,
               "targets": ",".join(f"{t:.12g}" for t in p.targets), "time_stop_ts": p.time_stop_ts,
               "tp1_done": p.tp1_done, "peak": p.peak, "sell_failures": p.sell_failures,
               "exit_reason": (p.legs[-1].reason if p.legs and p.status != "open" else None)}
        if p.status == "stuck":
            row["exit_reason"] = "STUCK"
            row["closed_ts"] = row["closed_ts"] or p.opened_ts
        if intent is not None:
            row["decision_evidence"] = json.dumps(intent.get("evidence") or {}, default=str)[:4000]
        return row

    def insert_paper_position(self, p, intent):
        with rhc_db.session_scope() as s:
            rec = RhcPaperPosition(**self._pos_row(p, intent))
            s.add(rec)
            s.flush()
            return rec.id

    def update_paper_position(self, p):
        if p.id is None:
            return
        row = self._pos_row(p)
        with rhc_db.session_scope() as s:
            s.execute(update(RhcPaperPosition).where(RhcPaperPosition.id == p.id).values(**row))

    def insert_paper_fill(self, position_id, pool_pk, ts, side, reason, usd, gas, price, ok, detail):
        with rhc_db.session_scope() as s:
            s.add(RhcPaperFill(position_id=position_id, pool_pk=pool_pk, ts=ts, side=side, reason=reason, usd=usd,
                               gas_usd=gas, price_usd=price, ok=ok, detail=json.dumps(detail, default=str)[:1000]))

    def load_open_paper_positions(self):
        from rhc_paper import Position
        with rhc_db.session_scope() as s:
            rows = s.execute(select(RhcPaperPosition).where(RhcPaperPosition.status == "open")).scalars().all()
            out = []
            for r in rows:
                out.append(Position(pool_pk=r.pool_pk, token=r.token, strategy=r.strategy, opened_ts=r.opened_ts,
                                    entry_price=r.entry_price, tokens=r.tokens, tokens_raw=int(r.tokens_raw or 0),
                                    cost_usd=r.cost_usd, stop=r.stop, stop_pct=r.stop_pct,
                                    targets=[float(x) for x in (r.targets or "").split(",") if x],
                                    time_stop_ts=r.time_stop_ts, regime=r.regime, risk_usd=r.risk_usd or 0.0,
                                    tp1_done=bool(r.tp1_done), peak=r.peak or 0.0, status=r.status,
                                    proceeds_usd=r.proceeds_usd or 0.0, sell_failures=r.sell_failures or 0, id=r.id))
            return out

    def paper_positions(self, status=None, limit=200):
        q = select(RhcPaperPosition).order_by(RhcPaperPosition.id.desc()).limit(limit)
        if status:
            q = q.where(RhcPaperPosition.status == status)
        with rhc_db.session_scope() as s:
            return [{c.name: getattr(r, c.name) for c in RhcPaperPosition.__table__.columns if c.name != "decision_evidence"}
                    for r in s.execute(q).scalars().all()]

    def paper_fills(self, position_id=None, limit=200):
        q = select(RhcPaperFill).order_by(RhcPaperFill.id.desc()).limit(limit)
        if position_id:
            q = q.where(RhcPaperFill.position_id == position_id)
        with rhc_db.session_scope() as s:
            return [{c.name: getattr(r, c.name) for c in RhcPaperFill.__table__.columns}
                    for r in s.execute(q).scalars().all()]

    def closed_paper_trades(self):
        with rhc_db.session_scope() as s:
            rows = s.execute(select(RhcPaperPosition).where(RhcPaperPosition.status.in_(["closed", "stuck"]))
                             .order_by(RhcPaperPosition.closed_ts)).scalars().all()
            return [{"pnl_usd": r.realized_usd or 0.0, "cost_usd": r.cost_usd or 0.0, "risk_usd": r.risk_usd or 0.0,
                     "strategy": r.strategy, "regime": r.regime, "token": r.token, "pool_pk": r.pool_pk,
                     "entry_ts": r.opened_ts, "exit_ts": r.closed_ts or r.opened_ts, "exit_reason": r.exit_reason}
                    for r in rows]

    def paper_realized_since(self, since_ts):
        with rhc_db.session_scope() as s:
            v = s.execute(select(func.coalesce(func.sum(RhcPaperPosition.realized_usd), 0.0))
                          .where(RhcPaperPosition.closed_ts >= since_ts)).scalar()
            return float(v or 0.0)

    def paper_last_exit_by_token(self):
        with rhc_db.session_scope() as s:
            return {r[0]: int(r[1]) for r in s.execute(
                select(RhcPaperPosition.token, func.max(RhcPaperPosition.closed_ts))
                .where(RhcPaperPosition.closed_ts.isnot(None)).group_by(RhcPaperPosition.token))}

    def last_close_usd(self, pool_pk):
        with rhc_db.session_scope() as s:
            return s.execute(select(RhcCandle.c_usd).where(RhcCandle.pool_pk == pool_pk, RhcCandle.tf == 60)
                             .order_by(RhcCandle.bucket.desc()).limit(1)).scalar()

    def last_candle_usd(self, pool_pk, since=0):
        """Latest closed 1m candle (bucket >= since) with OHLC converted to USD."""
        with rhc_db.session_scope() as s:
            r = s.execute(select(RhcCandle).where(RhcCandle.pool_pk == pool_pk, RhcCandle.tf == 60,
                                                  RhcCandle.bucket >= since - 60)
                          .order_by(RhcCandle.bucket.desc()).limit(1)).scalar()
            if r is None or not r.c or not r.c_usd:
                return None
            k = r.c_usd / r.c
            return {"bucket": r.bucket, "o_usd": r.o * k, "h_usd": r.h * k, "l_usd": r.l * k, "c_usd": r.c_usd}

    def watch_state(self, pool_pk):
        with rhc_db.session_scope() as s:
            return s.execute(select(RhcWatch.state).where(RhcWatch.pool_pk == pool_pk)).scalar()

    def latest_reject_is_permanent(self, pool_pk):
        from rhc_reasons import is_permanent
        with rhc_db.session_scope() as s:
            codes = s.execute(select(RhcScreen.reject_codes).where(RhcScreen.pool_pk == pool_pk)
                              .order_by(RhcScreen.ts.desc()).limit(1)).scalar()
        return any(is_permanent(c) for c in (codes or "").split(",") if c)

    def insert_backtest_run(self, ts, start, end, config_hash, summary):
        with rhc_db.session_scope() as s:
            rec = RhcBacktestRun(ts=ts, window_start=start, window_end=end, config_hash=config_hash,
                                 summary=json.dumps(summary, default=str)[:8000])
            s.add(rec)
            s.flush()
            return rec.id

    # ── retention ────────────────────────────────────────────────────────────
    def prune_screens(self, now_ts, retain_days):
        with rhc_db.session_scope() as s:
            n = s.execute(delete(RhcScreen).where(RhcScreen.ts < now_ts - retain_days * 86400)).rowcount
            s.execute(delete(RhcWatch).where(RhcWatch.state == "expired",
                                             RhcWatch.last_activity_ts < now_ts - 7 * 86400))
            return n

    def prune_dead_pools(self, now_ts, days):
        """Drop pools that never traded (or are unsupported), were never tracked, aren't watch-listed and
        are older than `days`. Pools that traded are kept forever (no survivorship bias)."""
        cutoff = now_ts - days * 86400
        sql = text("""
            delete from rhc_pool p
            where not p.tracked and p.tracked_since is null
              and (not p.supported or p.last_swap_ts is null)
              and coalesce(p.created_ts, extract(epoch from p.first_seen_at)::bigint) < :cut
              and not exists (select 1 from rhc_candle c where c.pool_pk = p.id)
              and not exists (select 1 from rhc_watchlist w where w.pool_pk = p.id)""")
        with rhc_db.session_scope() as s:
            return s.execute(sql, {"cut": cutoff}).rowcount
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
            insert into rhc_candle (pool_pk, tf, bucket, o, h, l, c, c_usd, c_mid, vol_usd, buys, sells, buy_usd,
                                    sell_usd, traders, traders_exact, large, liq, liq_usd)
            select pool_pk, 900, (bucket / 900) * 900,
                   (array_agg(o order by bucket))[1], max(h), min(l), (array_agg(c order by bucket desc))[1],
                   (array_agg(c_usd order by bucket desc))[1], (array_agg(c_mid order by bucket desc))[1],
                   sum(vol_usd), sum(buys), sum(sells),
                   sum(buy_usd), sum(sell_usd), max(traders), false, sum(large),
                   (array_agg(liq order by bucket desc))[1], (array_agg(liq_usd order by bucket desc))[1]
            from rhc_candle where tf = 300 and bucket < :cut
            group by pool_pk, (bucket / 900) * 900
            on conflict (pool_pk, tf, bucket) do nothing""")
        with rhc_db.session_scope() as s:
            s.execute(sql, {"cut": older_than_ts})
            n = s.execute(delete(RhcCandle).where(and_(RhcCandle.tf == 300, RhcCandle.bucket < older_than_ts))).rowcount
        return n


for _name in _RETRY_SAFE:
    setattr(Store, _name, _retrying(getattr(Store, _name)))

