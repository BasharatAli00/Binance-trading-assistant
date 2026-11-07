"""Discovery + safety screening.

Each cycle:
  1. discover: rank active supported pools (new pools, volume surges, top volume, large liquidity
     adds) and upsert them into the watchlist as candidates;
  2. screen the most important due entries: cheap checks first, expensive RPC checks only while
     nothing has rejected the pool yet (every executed check is recorded as evidence);
  3. expire pools without activity; publish watch-state pools so the indexer keeps them tracked.

Checks: market (quote/venue/age), activity, liquidity, round-trip simulation (honeypot, taxes,
cost, price impact), contract permissions, holder concentration, flow quality, LP control.
Nothing here trades or signs anything.
"""
import logging
import time

import rhc_config as cfg
import rhc_watchlist as wl
from rhc_contract_scan import classify, scan_contract
from rhc_decoders import ZERO_ADDR
from rhc_flow import flow_report, is_wash
from rhc_holders import holder_report
from rhc_lp import lp_history
from rhc_reasons import severity
from rhc_sim import Simulator
from rhc_util import TTLCache

log = logging.getLogger("rhc.screener")

_REASON_TO_CODE = {"no_supported_quote": "QUOTE_UNSUPPORTED", "wrap_pair": "QUOTE_UNSUPPORTED",
                   "stable_stable": "QUOTE_UNSUPPORTED", "factory_unrecognized": "VENUE_UNSUPPORTED",
                   "decimals_unavailable": "VENUE_UNSUPPORTED"}
_SIM_TO_CODE = {"BUY_FAILED": "BUY_BLOCKED", "SELL_TRANSFER_BLOCKED": "HONEYPOT", "SELL_FAILED": "HONEYPOT",
                "ZERO_RECEIVED": "TAX_100", "NO_LIQUIDITY": "ILLIQUID"}


def _r(x, n=4):
    return round(x, n) if isinstance(x, float) else x


class Verdict:
    """Accumulates codes from checks and resolves their severity."""

    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.rejects, self.warns, self.infos = [], [], []
        self.evidence = {}

    def add(self, check, codes, metrics=None):
        for c in codes:
            sev = severity(c, self.overrides)
            bucket = self.rejects if sev == "reject" else self.warns if sev == "warn" else self.infos
            if c not in bucket:
                bucket.append(c)
        self.evidence[check] = {"codes": list(codes), **({k: _r(v) for k, v in (metrics or {}).items()})}

    @property
    def rejected(self):
        return bool(self.rejects)

    @property
    def verdict(self):
        return "reject" if self.rejects else "pass"


class Screener:
    def __init__(self, rpc, store, registry, indexer, ds=None, clock=time.time):
        self.rpc = rpc
        self.store = store
        self.registry = registry
        self.indexer = indexer
        self.ds = ds
        self.clock = clock
        self.sim = Simulator(rpc)
        self.token_cache = TTLCache(cfg.RHC_TOKEN_CHECK_TTL_S)
        self.metrics = {"cycles": 0, "screened": 0, "passed": 0, "rejected": 0, "last_error": None,
                        "last_cycle_ts": None}

    # ── discovery ────────────────────────────────────────────────────────────
    def discover(self, now):
        idx = self.indexer
        chain_now = idx.metrics.get("processed_ts") or int(now)
        stats = idx.activity.stats(chain_now)
        ranked = sorted(stats.items(), key=lambda kv: kv[1][0], reverse=True)
        rows = []
        majors = set(cfg.RHC_ETH_QUOTES) | set(cfg.RHC_STABLE_QUOTES)
        for rank, (pk, st) in enumerate(ranked):
            m = self.registry.by_pk.get(pk)
            if m is None or not m.supported or pk == getattr(self.registry.get(idx.ref_pool), "pk", None):
                continue
            if m.base_token in majors:
                continue   # ETH/USDG-type major pairs are reference markets, not discovery targets
            reasons = wl.discovery_reasons(st, idx.activity.surge_window(pk, chain_now), m.created_ts, chain_now,
                                           rank, cfg)
            if reasons and pk in idx.recent_liq_adds and chain_now - idx.recent_liq_adds[pk] < 3600:
                reasons.append("liquidity_add")
            if reasons:
                rows.append({"pool_pk": pk, "token": m.base_token, "discovery": ",".join(reasons),
                             "score": wl.score(st, reasons), "last_activity_ts": int(st[2])})
        self.store.upsert_watch_candidates(rows, int(now))
        return len(rows)

    # ── screening ────────────────────────────────────────────────────────────
    def screen(self, meta, now=None):
        now = int(now or self.clock())
        t0 = time.time()
        v = Verdict(cfg.RHC_SEVERITY_OVERRIDES)
        self._check_market(meta, v, now)
        if not v.rejected:
            self._check_activity(meta, v)
        if not v.rejected:
            self._check_liquidity(meta, v)
        if not v.rejected:
            self._check_simulation(meta, v)
        if not v.rejected:
            self._check_contract(meta, v)
        if not v.rejected:
            self._check_holders(meta, v)
        if not v.rejected:
            self._check_flow(meta, v)
        if not v.rejected:
            self._check_lp(meta, v, now)
        v.evidence["_skipped_after_reject"] = v.rejected
        return v, int((time.time() - t0) * 1000)

    def _check_market(self, meta, v, now):
        codes = []
        if not meta.supported:
            codes.append(_REASON_TO_CODE.get(meta.reason or "", "VENUE_UNSUPPORTED"))
        age_min = (now - meta.created_ts) / 60 if meta.created_ts else None
        if age_min is not None and age_min < cfg.RHC_MIN_POOL_AGE_MIN:
            codes.append("TOO_NEW")
        v.add("market", codes, {"kind": meta.kind, "quote": meta.quote_class, "age_min": age_min,
                                "hooks": meta.hooks if meta.hooks and meta.hooks != ZERO_ADDR else None})

    def _check_activity(self, meta, v):
        idx = self.indexer
        st = idx.activity.stats(idx.metrics.get("processed_ts") or int(self.clock())).get(meta.pk, (0.0, 0, 0))
        codes = ["LOW_ACTIVITY"] if st[1] < cfg.RHC_MIN_TRADES_1H else []
        v.add("activity", codes, {"vol_usd_1h": st[0], "swaps_1h": st[1]})

    def _quote_usd(self, meta):
        return self.indexer.pricer.usd(meta.quote_class)

    def _check_liquidity(self, meta, v):
        liq, src = None, None
        qusd = self._quote_usd(meta)
        try:
            if meta.kind == "v2" and qusd:
                res = self.rpc.eth_call(meta.pool_id, "0x0902f1ac")
                r0, r1 = int(res[2:66], 16), int(res[66:130], 16)
                q_raw, q_dec = (r1, meta.dec1) if meta.base_index == 0 else (r0, meta.dec0)
                liq, src = 2.0 * q_raw / 10 ** q_dec * qusd, "reserves"
            elif self.ds is not None:
                snap = self.ds.pools([meta.pool_id]).get(meta.pool_id.lower())
                if snap and snap.get("liquidity_usd") is not None:
                    liq, src = snap["liquidity_usd"], "dexscreener"
        except Exception as e:
            log.debug("liquidity lookup failed for %s: %s", meta.pool_id, e)
        codes = []
        if liq is None:
            codes.append("LIQ_UNKNOWN")
        elif liq < cfg.RHC_MIN_LIQ_USD:
            codes.append("ILLIQUID")
        v.add("liquidity", codes, {"liquidity_usd": liq, "source": src})

    def _amount(self, meta, usd):
        qusd = self._quote_usd(meta)
        qdec = meta.dec1 if meta.base_index == 0 else meta.dec0
        if not qusd or qdec is None:
            return None
        return int(usd / qusd * 10 ** qdec)

    def _check_simulation(self, meta, v):
        self.registry.complete_v4_key(meta)
        size = self._amount(meta, cfg.RHC_SCREEN_TRADE_USD)
        probe = self._amount(meta, cfg.RHC_SCREEN_PROBE_USD)
        if not size or not probe:
            v.add("simulation", ["SIM_UNAVAILABLE"], {"error": "no quote price"})
            return
        fee = cfg.RHC_V2_FEE_BPS.get(meta.venue or "", cfg.RHC_V2_FEE_BPS_DEFAULT)
        big = self.sim.run(meta, size, fee)
        m = {"trade_usd": cfg.RHC_SCREEN_TRADE_USD, "status": big.status, "buy_tax": big.buy_tax,
             "sell_tax": big.sell_tax, "round_trip_cost": big.round_trip_cost, "gas_buy": big.gas_buy,
             "gas_sell": big.gas_sell, "error": big.error}
        codes = []
        if not big.ok:
            code = _SIM_TO_CODE.get(big.status, "SIM_UNAVAILABLE")
            if big.status == "NO_LIQUIDITY":
                # Thin pool, or pulled liquidity? The on-chain add/remove history decides.
                h = self._lp_hist(meta)
                if h is not None:
                    m.update(lp_adds=h.n_adds, lp_removes=h.n_removes, lp_removed_frac=h.removed_frac)
                    if h.n_removes and h.removed_frac >= cfg.RHC_RUG_REMOVED_FRAC:
                        code = "RUG_PULLED"
            codes.append(code)
        else:
            small = self.sim.run(meta, probe, fee)
            impact = None
            if small.ok and small.raw[1] and big.raw[1]:
                impact = max(0.0, 1.0 - (big.raw[1] / size) / (small.raw[1] / probe))
            m["impact"] = impact
            if (big.buy_tax or 0) > cfg.RHC_MAX_BUY_TAX or (big.sell_tax or 0) > cfg.RHC_MAX_SELL_TAX:
                codes.append("TAX_HIGH")
            if (big.round_trip_cost or 0) > cfg.RHC_MAX_ROUNDTRIP_COST:
                codes.append("COST_TOO_HIGH")
            if impact is None or impact > cfg.RHC_MAX_IMPACT:
                codes.append("IMPACT_TOO_HIGH")
        v.add("simulation", codes, m)

    def _check_contract(self, meta, v):
        token = meta.base_token
        rep = self.token_cache.get(("contract", token))
        if rep is None:
            rep = scan_contract(self.rpc, token)
            self.token_cache.set(("contract", token), rep)
        v.add("contract", classify(rep), {
            "proxy": rep.proxy, "owner": rep.owner, "owner_active": rep.owner_active, "code_size": rep.code_size,
            "code_hash": rep.code_hash,
            "functions": ",".join(sorted(k for k, s in rep.functions.items() if s)) or None})

    def _excluded(self, meta):
        ex = {meta.base_token, ZERO_ADDR, *cfg.RHC_V4_POOL_MANAGERS, *cfg.RHC_V4_POSITION_MANAGERS}
        for m in list(self.registry.by_id.values()):
            if m.kind in ("v2", "v3") and m.base_token == meta.base_token:
                ex.add(m.pool_id)
        return ex

    def _check_holders(self, meta, v):
        token = meta.base_token
        rep = self.token_cache.get(("holders", token))
        if rep is None:
            head = self.rpc.block_number()
            start = max(1, (meta.created_block or head - cfg.RHC_HOLDER_LOOKBACK_BLOCKS) - 100_000)
            rep = holder_report(self.rpc, token, start, head, self._excluded(meta), cfg.RHC_HOLDER_MAX_LOGS,
                                cfg.RHC_GETLOGS_ADDRESS_SPAN)
            self.token_cache.set(("holders", token), rep)
        codes = []
        if rep.top1_pct > cfg.RHC_MAX_TOP1_PCT or rep.top10_pct > cfg.RHC_MAX_TOP10_PCT:
            codes.append("CONCENTRATED")
        if max(rep.insider_pct, rep.deployer_pct) > cfg.RHC_MAX_INSIDER_PCT:
            codes.append("INSIDER_HEAVY")
        if rep.partial:
            codes.append("HOLDERS_PARTIAL")
        if rep.holders < cfg.RHC_MIN_HOLDERS:
            codes.append("FEW_HOLDERS")
        v.add("holders", codes, {"holders": rep.holders, "top1_pct": rep.top1_pct, "top10_pct": rep.top10_pct,
                                 "deployer_pct": rep.deployer_pct, "insider_pct": rep.insider_pct,
                                 "burned_pct": rep.burned_pct, "transfers": rep.transfers,
                                 "top3": [(a, p) for a, p in rep.top[:3]]})

    def _check_flow(self, meta, v):
        head = self.rpc.block_number()
        rep = flow_report(self.rpc, meta, self.indexer.pricer, head, cfg.RHC_FLOW_WINDOW_BLOCKS,
                          cfg.RHC_FLOW_MAX_RESOLVE, frozenset(cfg.RHC_V4_POOL_MANAGERS), cfg.RHC_FRESH_NONCE,
                          cfg.RHC_FLOW_MAX_NONCES)
        codes = []
        if rep.traders < cfg.RHC_MIN_TRADERS_1H:
            codes.append("LOW_ACTIVITY")
        if is_wash(rep, cfg.RHC_WASH_TOP3_SHARE, cfg.RHC_WASH_ROUNDTRIP_SHARE):
            codes.append("WASH_SUSPECT")
        if rep.fresh_volume_share >= cfg.RHC_FRESH_VOLUME_WARN:
            codes.append("FRESH_WALLET_HEAVY")
        if rep.bundled_blocks >= cfg.RHC_BUNDLED_BLOCKS_WARN:
            codes.append("BUNDLED_BUYS")
        v.add("flow", codes, {"trades": rep.trades, "traders": rep.traders, "vol_usd": rep.vol_usd,
                              "buy_usd": rep.buy_usd, "sell_usd": rep.sell_usd, "median_usd": rep.median_usd,
                              "top3_share": rep.top3_share, "roundtrip_share": rep.roundtrip_share,
                              "fresh_trader_share": rep.fresh_trader_share,
                              "fresh_volume_share": rep.fresh_volume_share, "bundled_blocks": rep.bundled_blocks})

    def _lp_hist(self, meta):
        key = ("lp", meta.pool_id)
        h = self.token_cache.get(key)
        if h is None:
            try:
                h = lp_history(self.rpc, meta, self.rpc.block_number(), cfg.RHC_LP_HISTORY_BLOCKS,
                               frozenset(cfg.RHC_V4_POOL_MANAGERS))
            except Exception as e:
                log.debug("lp history failed for %s: %s", meta.pool_id, e)
                return None
            self.token_cache.set(key, h, ttl_s=120)
        return h

    def _check_lp(self, meta, v, now):
        codes, m = [], {}
        if meta.kind == "v2":
            res = self.rpc.batch([
                ("eth_call", [{"to": meta.pool_id, "data": "0x18160ddd"}, "latest"]),
                ("eth_call", [{"to": meta.pool_id, "data": "0x70a08231" + "0" * 64}, "latest"]),
                ("eth_call", [{"to": meta.pool_id, "data": "0x70a08231" + "0" * 24 +
                               "000000000000000000000000000000000000dead"}, "latest"])])
            vals = [int(r, 16) if isinstance(r, str) and len(r) > 2 else 0 for r in res]
            burned = 100.0 * (vals[1] + vals[2]) / vals[0] if vals[0] else 0.0
            m["lp_burned_pct"] = burned
            if burned < cfg.RHC_LP_MIN_BURNED_PCT:
                codes.append("LP_NOT_BURNED")
        else:
            codes.append("LP_LOCK_UNKNOWN")
        h = self._lp_hist(meta)
        if h is not None:
            m.update(lp_adds_2h=h.n_adds, lp_removes_2h=h.n_removes, lp_removed_frac_2h=h.removed_frac)
            if h.n_removes and h.removed_frac >= cfg.RHC_LP_REMOVAL_WARN_FRAC:
                codes.append("RECENT_LP_REMOVAL")
        else:
            m["lp_history_error"] = True
        v.add("lp", codes, m)

    # ── cycle ────────────────────────────────────────────────────────────────
    def cycle(self):
        now = int(self.clock())
        self.metrics["cycles"] += 1
        self.metrics["last_cycle_ts"] = now
        found = self.discover(now)
        screened = 0
        for row in self.store.due_watch(now, cfg.RHC_SCREEN_PER_CYCLE):
            meta = self.registry.by_pk.get(row["pool_pk"])
            if meta is None:
                # Not in the in-memory registry (no recent activity): expire instead of blocking the queue.
                # Discovery revives it as a candidate if it trades again.
                self.store.set_watch_state(row["pool_pk"], "expired")
                continue
            try:
                v, ms = self.screen(meta, now)
            except Exception as e:
                log.warning("screening %s failed: %s", meta.pool_id, e)
                self.metrics["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
                v, ms = Verdict(cfg.RHC_SEVERITY_OVERRIDES), 0
                v.add("error", ["SIM_UNAVAILABLE"], {"error": str(e)[:200]})
            state, next_ts = wl.after_screen(v.verdict, v.rejects, now, cfg)
            self.store.save_screen(meta.pk, meta.base_token, now, v.verdict, v.rejects, v.warns + v.infos,
                                   v.evidence, ms, state, next_ts)
            screened += 1
            self.metrics["screened"] += 1
            self.metrics["passed" if v.verdict == "pass" else "rejected"] += 1
        self.store.expire_stale(now - int(cfg.RHC_WATCH_EXPIRE_H * 3600))
        self.indexer.always_track = self.store.watch_pks()
        return {"discovered": found, "screened": screened}
