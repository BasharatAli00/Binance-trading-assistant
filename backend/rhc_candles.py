"""Pure candle + flow aggregation, rolling pool activity, and the tracking policy.

Candles are keyed by (pool_pk, tf, bucket_start). A candle is only emitted once
it is CLOSED: bucket_end + grace <= processed chain time. Re-processing the
same trades always yields identical rows, so DB upserts are idempotent.
"""
from collections import defaultdict, deque

TF_1M = 60
TF_5M = 300
TF_15M = 900


class Candle:
    __slots__ = ("pool_pk", "tf", "bucket", "o", "h", "l", "c", "c_usd", "c_mid", "vol_usd", "buys", "sells",
                 "buy_usd", "sell_usd", "_traders", "traders_exact", "large", "liq", "liq_usd", "n")

    def __init__(self, pool_pk, tf, bucket):
        self.pool_pk = pool_pk
        self.tf = tf
        self.bucket = bucket
        self.o = self.h = self.l = self.c = None
        self.c_usd = None
        self.c_mid = None
        self.vol_usd = 0.0
        self.buys = self.sells = 0
        self.buy_usd = self.sell_usd = 0.0
        self._traders = set()
        self.traders_exact = True
        self.large = 0
        self.liq = None
        self.liq_usd = None
        self.n = 0

    def add(self, t, large_usd):
        # OHLC from EXECUTION prices (what traders actually paid), matching GeckoTerminal/DexScreener.
        # The marginal post-swap price is kept separately as c_mid (better "current price").
        p = t.exec_q if t.exec_q else t.price_q
        if self.o is None:
            self.o = self.h = self.l = p
        else:
            self.h = max(self.h, p)
            self.l = min(self.l, p)
        self.c = p
        usd_px = t.exec_usd if t.exec_usd is not None else t.price_usd
        if usd_px is not None:
            self.c_usd = usd_px
        if t.price_usd is not None:
            self.c_mid = t.price_usd
        usd = t.usd or 0.0
        self.vol_usd += usd
        if t.side == "buy":
            self.buys += 1
            self.buy_usd += usd
        else:
            self.sells += 1
            self.sell_usd += usd
        if t.trader:
            self._traders.add(t.trader)
        else:
            self._traders.add(t.tx)
            self.traders_exact = False
        if usd >= large_usd:
            self.large += 1
        if t.liq is not None:
            self.liq = t.liq
        if t.liq_usd is not None:
            self.liq_usd = t.liq_usd
        self.n += 1

    @property
    def traders(self):
        return len(self._traders)

    def to_row(self):
        return {
            "pool_pk": self.pool_pk, "tf": self.tf, "bucket": self.bucket,
            "o": self.o, "h": self.h, "l": self.l, "c": self.c, "c_usd": self.c_usd, "c_mid": self.c_mid,
            "vol_usd": round(self.vol_usd, 6), "buys": self.buys, "sells": self.sells,
            "buy_usd": round(self.buy_usd, 6), "sell_usd": round(self.sell_usd, 6),
            "traders": self.traders, "traders_exact": self.traders_exact, "large": self.large,
            "liq": self.liq, "liq_usd": self.liq_usd,
        }


class CandleBook:
    """Holds open candles; emits closed ones; keeps a small ring of recent closed candles."""

    def __init__(self, tfs=(TF_1M, TF_5M), grace_s=5, large_usd=1000.0, ring_size=60):
        self.tfs = tuple(tfs)
        self.grace = grace_s
        self.large_usd = large_usd
        self.ring_size = ring_size
        self.open = {}
        self.rings = defaultdict(lambda: deque(maxlen=ring_size))
        self.skip_before_ts = None

    def add_trade(self, t):
        if self.skip_before_ts is not None and t.ts < self.skip_before_ts:
            return False
        for tf in self.tfs:
            b = (t.ts // tf) * tf
            key = (t.pool_pk, tf, b)
            c = self.open.get(key)
            if c is None:
                c = Candle(t.pool_pk, tf, b)
                self.open[key] = c
            c.add(t, self.large_usd)
        return True

    def close_until(self, chain_ts, keep_ring_for=None):
        """Pop candles whose bucket_end + grace <= chain_ts. Returns list of Candle."""
        closed = []
        for key in [k for k, c in self.open.items() if c.bucket + c.tf + self.grace <= chain_ts]:
            c = self.open.pop(key)
            closed.append(c)
            if keep_ring_for is None or c.pool_pk in keep_ring_for:
                self.rings[(c.pool_pk, c.tf)].append(c)
        closed.sort(key=lambda c: (c.pool_pk, c.tf, c.bucket))
        return closed

    def oldest_open_start(self, tf, default_ts):
        starts = [c.bucket for c in self.open.values() if c.tf == tf]
        if starts:
            return min(starts)
        return (int(default_ts) // tf) * tf

    def ring(self, pool_pk):
        out = []
        for tf in self.tfs:
            out.extend(self.rings.get((pool_pk, tf), ()))
        return out

    def drop_rings_except(self, keep):
        for key in [k for k in self.rings if k[0] not in keep]:
            self.rings.pop(key, None)

    def reset(self):
        self.open.clear()
        self.rings.clear()


class PoolActivity:
    """Rolling per-minute volume/count per pool for the tracking decision."""

    def __init__(self, window_s=3600):
        self.window = window_s
        self._mins = defaultdict(deque)   # pk -> deque[(minute, usd, n)]
        self.last_ts = {}

    def add(self, t):
        m = (t.ts // 60) * 60
        dq = self._mins[t.pool_pk]
        if dq and dq[-1][0] == m:
            _, usd, n = dq[-1]
            dq[-1] = (m, usd + (t.usd or 0.0), n + 1)
        else:
            dq.append((m, t.usd or 0.0, 1))
        prev = self.last_ts.get(t.pool_pk)
        if prev is None or t.ts > prev:
            self.last_ts[t.pool_pk] = t.ts

    def prune(self, now_ts):
        cutoff = now_ts - self.window
        for pk in list(self._mins):
            dq = self._mins[pk]
            while dq and dq[0][0] < cutoff:
                dq.popleft()
            if not dq:
                del self._mins[pk]

    def surge_window(self, pk, now_ts, recent_s=900, prior_s=2700):
        """(usd in the last recent_s, usd in the prior_s before that) for surge detection."""
        recent = prior = 0.0
        for m, usd, _ in list(self._mins.get(pk, ())):
            age = now_ts - m
            if age < recent_s:
                recent += usd
            elif age < recent_s + prior_s:
                prior += usd
        return recent, prior

    def stats(self, now_ts):
        self.prune(now_ts)
        return {pk: (sum(x[1] for x in dq), sum(x[2] for x in dq), self.last_ts.get(pk, 0))
                for pk, dq in self._mins.items()}

    def reset(self):
        self._mins.clear()
        self.last_ts.clear()


def select_tracked(current, stats, always, now_ts, max_pools, min_vol_usd, min_swaps, idle_min):
    """Decide the tracked pool set (pure).

    current: set of pks tracked now; stats: pk -> (usd_1h, swaps_1h, last_ts);
    always: pks that must stay tracked (reference pools). Returns new set.
    Hysteresis: a tracked pool stays until idle > idle_min or evicted by a busier pool at the cap.
    """
    idle_cut = now_ts - idle_min * 60
    keep = set(always)
    for pk in current:
        last = stats.get(pk, (0.0, 0, 0))[2]
        if pk in always or last >= idle_cut:
            keep.add(pk)
    candidates = [pk for pk, (usd, n, _) in stats.items()
                  if usd >= min_vol_usd and n >= min_swaps and pk not in keep]
    candidates.sort(key=lambda pk: stats[pk][0], reverse=True)
    result = set(keep)
    for pk in candidates:
        if len(result) >= max_pools:
            break
        result.add(pk)
    if len(result) > max_pools:
        evictable = sorted((pk for pk in result if pk not in always), key=lambda pk: stats.get(pk, (0.0,))[0])
        while len(result) > max_pools and evictable:
            result.discard(evictable.pop(0))
    # A busier candidate may displace the quietest non-reference tracked pool.
    if len(result) >= max_pools:
        outside = [pk for pk in candidates if pk not in result]
        if outside:
            quietest = min((pk for pk in result if pk not in always),
                           key=lambda pk: stats.get(pk, (0.0,))[0], default=None)
            best = outside[0]
            if quietest is not None and stats[best][0] > 2.0 * stats.get(quietest, (0.0,))[0]:
                result.discard(quietest)
                result.add(best)
    return result
