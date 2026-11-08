"""Third-party data sources behind one interface.

Each adapter: token-bucket rate limit, TTL cache, retry with backoff on 429/5xx
(honouring Retry-After), and health tracking. Sources ENRICH and CROSS-CHECK our
own on-chain data; they never block indexing.

Normalised pool snapshot: {"source", "pool_id", "price_usd", "liquidity_usd",
"volume_24h", "dex_id", "base_symbol", "quote_symbol"}
"""
import logging
import time

import requests

import rhc_config as cfg
from rhc_util import TokenBucket, TTLCache

log = logging.getLogger("rhc.sources")


class SourceError(Exception):
    pass


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


class HttpSource:
    name = "base"

    def __init__(self, base, per_min, session=None, ttl_s=None, sleep=time.sleep, clock=time.monotonic,
                 retries=3, timeout=None):
        self.base = base
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "rhc-indexer/1.0")
        self.session.headers.setdefault("Accept", "application/json")
        self.bucket = TokenBucket.per_minute(per_min, clock=clock, sleep=sleep)
        self.cache = TTLCache(cfg.RHC_SOURCE_CACHE_TTL_S if ttl_s is None else ttl_s, clock=clock)
        self.sleep = sleep
        self.retries = retries
        self.timeout = timeout or cfg.RHC_HTTP_TIMEOUT_S
        self.health = {"ok_count": 0, "err_count": 0, "last_ok_ts": None, "last_err_ts": None,
                       "last_err": None, "last_latency_ms": None}

    def _record_ok(self, ms):
        self.health["ok_count"] += 1
        self.health["last_ok_ts"] = int(time.time())
        self.health["last_latency_ms"] = int(ms)

    def _record_err(self, msg):
        self.health["err_count"] += 1
        self.health["last_err_ts"] = int(time.time())
        self.health["last_err"] = str(msg)[:300]

    def get_json(self, path, params=None, cache_key=None, ttl_s=None):
        key = cache_key or (path, tuple(sorted((params or {}).items())))
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        url = self.base + path
        last = None
        for attempt in range(self.retries + 1):
            if not self.bucket.acquire(timeout=120):
                raise SourceError(f"{self.name}: local rate limit wait exceeded")
            t0 = time.monotonic()
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                last = f"network: {e}"
                self._record_err(last)
                self.sleep(min(2 ** attempt, 20))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                self._record_err(last)
                retry_after = _f(r.headers.get("Retry-After")) or min(5 * 2 ** attempt, 60)
                self.sleep(retry_after)
                continue
            if r.status_code != 200:
                last = f"HTTP {r.status_code}"
                self._record_err(last)
                raise SourceError(f"{self.name}: {last}")
            try:
                data = r.json()
            except ValueError:
                self._record_err("invalid JSON")
                raise SourceError(f"{self.name}: invalid JSON")
            self._record_ok((time.monotonic() - t0) * 1000)
            self.cache.set(key, data, ttl_s)
            return data
        raise SourceError(f"{self.name}: failed after retries ({last})")

    def health_row(self):
        return {"source": self.name, **self.health}


class DexScreenerSource(HttpSource):
    name = "dexscreener"

    def __init__(self, **kw):
        super().__init__(cfg.RHC_DEXSCREENER_BASE, cfg.RHC_DS_MAX_PER_MIN, **kw)

    @staticmethod
    def normalise(p):
        base, quote = p.get("baseToken") or {}, p.get("quoteToken") or {}
        base_usd = _f(p.get("priceUsd"))
        native = _f(p.get("priceNative"))          # DS base priced in DS quote
        quote_usd = (base_usd / native) if base_usd and native else None
        prices = {}
        if base.get("address"):
            prices[base["address"].lower()] = base_usd
        if quote.get("address"):
            prices[quote["address"].lower()] = quote_usd
        return {"source": "dexscreener", "pool_id": (p.get("pairAddress") or "").lower(),
                "price_usd": base_usd, "token_prices_usd": prices,
                "liquidity_usd": _f((p.get("liquidity") or {}).get("usd")),
                "volume_24h": _f((p.get("volume") or {}).get("h24")), "dex_id": p.get("dexId"),
                "labels": p.get("labels"), "base_symbol": base.get("symbol"), "quote_symbol": quote.get("symbol"),
                "base_address": (base.get("address") or "").lower()}

    def pools(self, pool_ids):
        """Up to 30 pools per request (DexScreener pairs endpoint)."""
        out = {}
        ids = [p.lower() for p in pool_ids]
        for i in range(0, len(ids), 30):
            part = ids[i:i + 30]
            data = self.get_json(f"/latest/dex/pairs/{cfg.RHC_DS_CHAIN}/{','.join(part)}")
            for p in (data.get("pairs") or []) if isinstance(data, dict) else []:
                if p.get("chainId") == cfg.RHC_DS_CHAIN:
                    n = self.normalise(p)
                    out[n["pool_id"]] = n
        return out


class GeckoTerminalSource(HttpSource):
    name = "geckoterminal"

    def __init__(self, **kw):
        super().__init__(cfg.RHC_GECKOTERMINAL_BASE, cfg.RHC_GT_MAX_PER_MIN, **kw)

    @staticmethod
    def normalise(item):
        a = item.get("attributes") or {}
        rel = item.get("relationships") or {}
        dex = ((rel.get("dex") or {}).get("data") or {}).get("id")

        def tok(k):
            tid = ((rel.get(k) or {}).get("data") or {}).get("id") or ""
            return tid.split("_", 1)[1].lower() if "_" in tid else None

        prices = {}
        if tok("base_token"):
            prices[tok("base_token")] = _f(a.get("base_token_price_usd"))
        if tok("quote_token"):
            prices[tok("quote_token")] = _f(a.get("quote_token_price_usd"))
        return {"source": "geckoterminal", "pool_id": (a.get("address") or "").lower(),
                "price_usd": _f(a.get("base_token_price_usd")), "token_prices_usd": prices,
                "liquidity_usd": _f(a.get("reserve_in_usd")),
                "volume_24h": _f((a.get("volume_usd") or {}).get("h24")), "dex_id": dex,
                "name": a.get("name"), "created_at": a.get("pool_created_at")}

    def pools(self, pool_ids):
        out = {}
        ids = [p.lower() for p in pool_ids]
        for i in range(0, len(ids), 30):
            part = ids[i:i + 30]
            data = self.get_json(f"/networks/{cfg.RHC_GT_NETWORK}/pools/multi/{','.join(part)}")
            for item in (data.get("data") or []) if isinstance(data, dict) else []:
                n = self.normalise(item)
                out[n["pool_id"]] = n
        return out

    def ohlcv(self, pool_id, timeframe="minute", aggregate=1, limit=1000, before_ts=None):
        params = {"aggregate": aggregate, "limit": limit}
        if before_ts:
            params["before_timestamp"] = int(before_ts)
        data = self.get_json(f"/networks/{cfg.RHC_GT_NETWORK}/pools/{pool_id}/ohlcv/{timeframe}", params)
        rows = (((data or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        return [{"ts": int(r[0]), "o": _f(r[1]), "h": _f(r[2]), "l": _f(r[3]), "c": _f(r[4]), "vol_usd": _f(r[5])}
                for r in rows]


class DefiLlamaSource(HttpSource):
    name = "defillama"

    def __init__(self, **kw):
        kw.setdefault("ttl_s", cfg.RHC_CONTEXT_REFRESH_S)
        super().__init__(cfg.RHC_DEFILLAMA_BASE, cfg.RHC_LLAMA_MAX_PER_MIN, **kw)

    def chain_context(self):
        chains = self.get_json("/v2/chains")
        tvl = None
        for c in chains if isinstance(chains, list) else []:
            if c.get("chainId") == cfg.CHAIN_ID:
                tvl = _f(c.get("tvl"))
        dex = self.get_json("/overview/dexs/Robinhood", {"excludeTotalDataChart": "true",
                                                         "excludeTotalDataChartBreakdown": "true"})
        return {"tvl_usd": tvl, "dex_volume_24h": _f((dex or {}).get("total24h")),
                "dex_volume_7d": _f((dex or {}).get("total7d"))}


class RelaySource(HttpSource):
    """Health only in Phase 1. Executable quotes come in Phase 4 (paper fills)."""
    name = "relay"

    def __init__(self, **kw):
        kw.setdefault("ttl_s", cfg.RHC_CONTEXT_REFRESH_S)
        super().__init__(cfg.RHC_RELAY_BASE, cfg.RHC_RELAY_MAX_PER_MIN, **kw)

    def chain_supported(self):
        data = self.get_json("/chains")
        return any(c.get("id") == cfg.CHAIN_ID for c in (data or {}).get("chains", []))


def deviation_pct(ours, theirs):
    if not ours or not theirs:
        return None
    return abs(ours - theirs) / theirs * 100.0


class SourceHub:
    """Periodic enrichment + cross-source consistency checks for tracked pools."""

    def __init__(self, store, sources=None, clock=time.time):
        self.store = store
        self.clock = clock
        self.ds = (sources or {}).get("dexscreener") or DexScreenerSource()
        self.gt = (sources or {}).get("geckoterminal") or GeckoTerminalSource()
        self.llama = (sources or {}).get("defillama") or DefiLlamaSource()
        self.relay = (sources or {}).get("relay") or RelaySource()
        self.context = {}
        self.last_xcheck = {}
        self._gt_cursor = 0
        self._last_context = 0.0
        self._over_last = {}

    @property
    def all(self):
        return [self.ds, self.gt, self.llama, self.relay]

    def health(self):
        return {s.name: s.health_row() for s in self.all}

    def snapshot_cycle(self, tracked, ours=None):
        """tracked: list of (pk, pool_id, base_token) ordered by priority.
        ours: optional {pk: (price_usd, ts)} of our LATEST trade prices (seconds old). Without it,
        the last closed 1m candle is used, which lags volatile tokens and inflates deviations."""
        now = int(self.clock())
        top = [(pk, pid) for pk, pid, _ in tracked[:cfg.RHC_SNAPSHOT_TOP_N]]
        base_of = {pk: (b or "").lower() for pk, _, b in tracked[:cfg.RHC_SNAPSHOT_TOP_N]}
        if not top:
            return {"snapshots": 0}
        if ours is None:
            ours = self.store.latest_close_usd([pk for pk, _ in top])
        id_to_pk = {pid: pk for pk, pid in top}
        rows, flagged = [], []

        def add(results, source):
            for pid, snap in results.items():
                pk = id_to_pk.get(pid)
                if pk is None:
                    continue
                our = (ours.get(pk) or (None, None))[0]
                # Compare the SAME token: our base token's USD price as seen by the source.
                theirs = (snap.get("token_prices_usd") or {}).get(base_of.get(pk))
                dev = deviation_pct(our, theirs)
                rows.append({"source": source, "pool_pk": pk, "ts": now, "price_usd": theirs,
                             "liquidity_usd": snap.get("liquidity_usd"), "volume_24h": snap.get("volume_24h"),
                             "our_price_usd": our, "dev_pct": dev})
                over = dev is not None and dev > cfg.RHC_XCHECK_MAX_DEV_PCT
                key = (pk, source)
                # Flag only persistent disagreement (two consecutive cycles), not one-off timing noise.
                if over and self._over_last.get(key):
                    flagged.append({"pool_pk": pk, "source": source, "dev_pct": round(dev, 2)})
                self._over_last[key] = over

        try:
            add(self.ds.pools([pid for _, pid in top]), "dexscreener")
        except Exception as e:
            log.warning("dexscreener snapshot failed: %s", e)
        n = cfg.RHC_GT_XCHECK_PER_CYCLE
        if n > 0:
            start = self._gt_cursor % len(top)
            part = (top[start:] + top[:start])[:n]
            self._gt_cursor += n
            try:
                add(self.gt.pools([pid for _, pid in part]), "geckoterminal")
            except Exception as e:
                log.warning("geckoterminal snapshot failed: %s", e)
        if rows:
            self.store.insert_snapshots(rows)
        self.last_xcheck = {"ts": now, "rows": len(rows), "flagged": flagged[:50]}
        return {"snapshots": len(rows), "flagged": len(flagged)}

    def context_cycle(self):
        now = self.clock()
        if now - self._last_context < cfg.RHC_CONTEXT_REFRESH_S and self.context:
            return self.context
        self._last_context = now
        ctx = {"ts": int(now)}
        try:
            ctx.update(self.llama.chain_context())
        except Exception as e:
            ctx["defillama_error"] = str(e)[:200]
        try:
            ctx["relay_supports_chain"] = self.relay.chain_supported()
        except Exception as e:
            ctx["relay_error"] = str(e)[:200]
        self.context = ctx
        return ctx
