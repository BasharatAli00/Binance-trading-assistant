"""Screener orchestration tests with fakes (no network, no DB)."""
from types import SimpleNamespace

import pytest

import rhc_config as cfg
from rhc_candles import PoolActivity
from rhc_market import PoolMeta, QuotePricer
from rhc_screener import Screener, Verdict
from rhc_sim import SimResult

ETH = "0x" + "0" * 40
MEME = "0x" + "ab" * 20


class FakeStore:
    def __init__(self):
        self.saved, self.candidates, self.watch = [], [], {}

    def upsert_watch_candidates(self, rows, now):
        self.candidates.extend(rows)
        for r in rows:
            self.watch.setdefault(r["pool_pk"], dict(r, state="candidate", next_screen_ts=now, score=r["score"]))

    def due_watch(self, now, limit):
        rows = [w for w in self.watch.values() if w["state"] in ("candidate", "watch", "rejected")
                and w["next_screen_ts"] <= now]
        return rows[:limit]

    def save_screen(self, pk, token, ts, verdict, rejects, warns, evidence, ms, state, next_ts):
        self.saved.append(dict(pk=pk, verdict=verdict, rejects=rejects, warns=warns, evidence=evidence))
        self.watch[pk].update(state=state, next_screen_ts=next_ts)

    def expire_stale(self, cutoff):
        return 0

    def watch_pks(self):
        return {pk for pk, w in self.watch.items() if w["state"] == "watch"}

    def recent_lp_removals(self, pk, since):
        return 0, 0.0

    def set_watch_state(self, pk, state):
        self.watch[pk]["state"] = state


def make(now=2_000_000):
    meta = PoolMeta(pool_id="0x" + "cd" * 32, kind="v4", token0=ETH, token1=MEME, dec0=18, dec1=18, base_index=1,
                    quote_token=ETH, quote_class="eth", supported=True, pk=7, fee=3000, tick_spacing=60,
                    created_ts=now - 7200, created_block=1_000)
    act = PoolActivity()
    for i in range(60):
        act.add(SimpleNamespace(pool_pk=7, ts=now - 60 * i, usd=500.0))
    pricer = QuotePricer()
    pricer.set_eth_usd(3000.0, now)
    indexer = SimpleNamespace(activity=act, pricer=pricer, metrics={"processed_ts": now}, recent_liq_adds={},
                              ref_pool="0xref", always_track=set())
    registry = SimpleNamespace(by_pk={7: meta}, by_id={meta.pool_id: meta}, get=lambda pid: None,
                               complete_v4_key=lambda m: m)
    store = FakeStore()
    s = Screener(rpc=None, store=store, registry=registry, indexer=indexer, ds=None, clock=lambda: now)
    calls = []

    def stub(name, codes, metrics=None):
        def f(meta_, v, *a):
            calls.append(name)
            v.add(name, codes, metrics or {})
        return f
    for name in ("liquidity", "contract", "holders", "flow", "lp"):
        setattr(s, f"_check_{name}", stub(name, []))
    return s, store, meta, calls, stub


def sim_returning(results):
    seq = list(results)

    class FakeSim:
        def run(self, meta, amount, fee):
            return seq.pop(0)
    return FakeSim()


def test_pass_runs_every_check_and_records_evidence():
    s, store, meta, calls, _ = make()
    ok_big = SimResult("ok", 10, raw=[0, 1_000_000, 1_000_000, 1_000_000, 9, 9, 1, 1], buy_tax=0.0, sell_tax=0.0,
                       round_trip_cost=0.006)
    # $1 probe gets 40,100 tokens; $25 gets 1,000,000 (not 1,002,500) -> 0.25% price impact
    ok_small = SimResult("ok", 1, raw=[0, 40_100, 40_100, 40_100, 1, 1, 1, 1])
    s.sim = sim_returning([ok_big, ok_small])
    s.cycle()
    assert calls == ["liquidity", "contract", "holders", "flow", "lp"]
    rec = store.saved[0]
    assert rec["verdict"] == "pass" and rec["rejects"] == []
    assert rec["evidence"]["simulation"]["impact"] is not None
    assert store.watch[7]["state"] == "watch" and s.indexer.always_track == {7}


def test_honeypot_rejects_and_skips_expensive_checks():
    s, store, meta, calls, _ = make()
    s.sim = sim_returning([SimResult("SELL_FAILED", 10, raw=[3, 5, 5, 0, 0, 0, 1, 0])])
    s.cycle()
    rec = store.saved[0]
    assert rec["verdict"] == "reject" and rec["rejects"] == ["HONEYPOT"]
    assert calls == ["liquidity"]                         # contract/holders/flow/lp not spent on it
    assert rec["evidence"]["_skipped_after_reject"] is True
    assert store.watch[7]["state"] == "rejected"


def test_tax_cost_and_impact_limits():
    s, store, meta, calls, _ = make()
    big = SimResult("ok", 10, raw=[0, 900_000, 800_000, 800_000, 9, 9, 1, 1], buy_tax=0.11, sell_tax=0.0,
                    round_trip_cost=0.2)
    small = SimResult("ok", 1, raw=[0, 100_000, 100_000, 100_000, 1, 1, 1, 1])
    s.sim = sim_returning([big, small])
    v = Verdict()
    s._check_simulation(meta, v)
    assert set(v.rejects) == {"TAX_HIGH", "COST_TOO_HIGH", "IMPACT_TOO_HIGH"}
    assert v.evidence["simulation"]["impact"] == pytest.approx(1 - (900_000 / s._amount(meta, 25.0)) /
                                                               (100_000 / s._amount(meta, 1.0)), rel=1e-6)


def test_too_new_and_low_activity(monkeypatch):
    s, store, meta, calls, _ = make()
    meta.created_ts = 2_000_000 - 60
    v = Verdict()
    s._check_market(meta, v, 2_000_000)
    assert v.rejects == ["TOO_NEW"]
    monkeypatch.setattr(cfg, "RHC_MIN_TRADES_1H", 10_000)
    v2 = Verdict()
    s._check_activity(meta, v2)
    assert v2.rejects == ["LOW_ACTIVITY"]


def test_severity_override_turns_reject_into_warning(monkeypatch):
    monkeypatch.setattr(cfg, "RHC_SEVERITY_OVERRIDES", {"WASH_SUSPECT": "warn"})
    s, store, meta, calls, stub = make()
    s._check_flow = stub("flow", ["WASH_SUSPECT"])
    s.sim = sim_returning([SimResult("ok", 10, raw=[0, 1000, 1000, 1000, 9, 9, 1, 1], buy_tax=0, sell_tax=0,
                                     round_trip_cost=0.0),
                           SimResult("ok", 1, raw=[0, 40, 40, 40, 1, 1, 1, 1])])
    s.cycle()
    rec = store.saved[0]
    assert rec["verdict"] == "pass" and "WASH_SUSPECT" in rec["warns"]


def test_no_liquidity_plus_withdrawn_lp_is_rug_pulled():
    from rhc_lp import LpHistory
    s, store, meta, calls, _ = make()
    s.sim = sim_returning([SimResult("NO_LIQUIDITY", 10, raw=[4, 0, 0, 0, 0, 0, 165_019, 0])])
    s._lp_hist = lambda m: LpHistory(adds=2.5e22, removes=2.5e22, n_adds=1, n_removes=1, last_remove_block=9)
    v = Verdict()
    s._check_simulation(meta, v)
    assert v.rejects == ["RUG_PULLED"] and v.evidence["simulation"]["lp_removed_frac"] == 1.0
    s.sim = sim_returning([SimResult("NO_LIQUIDITY", 10, raw=[4, 0, 0, 0, 0, 0, 1, 0])])
    s._lp_hist = lambda m: LpHistory()                    # never had liquidity removed: just thin
    v2 = Verdict()
    s._check_simulation(meta, v2)
    assert v2.rejects == ["ILLIQUID"]


def test_lp_history_summary():
    from rhc_decoders import LiquidityEv, LogRef
    from rhc_lp import summarise
    ref = lambda b: LogRef(b, "0x" + "1" * 64, 0, "0xp")
    evs = [LiquidityEv("v4", "id", "add", None, None, 100, -1, 1, ref(1)),
           LiquidityEv("v4", "id", "remove", None, None, -40, -1, 1, ref(5))]
    h = summarise(evs, PoolMeta("id", "v4", ETH, MEME, base_index=1))
    assert (h.n_adds, h.n_removes, h.last_remove_block) == (1, 1, 5) and h.removed_frac == pytest.approx(0.4)
    v2 = [LiquidityEv("v2", "p", "add", 10, 999, None, None, None, ref(1)),
          LiquidityEv("v2", "p", "remove", 10, 999, None, None, None, ref(2))]
    h2 = summarise(v2, PoolMeta("p", "v2", ETH, MEME, base_index=1))     # quote is token0 -> amount0
    assert h2.adds == 10 and h2.removed_frac == 1.0
    assert summarise([], PoolMeta("p", "v2", ETH, MEME, base_index=1)).removed_frac == 0.0


def test_unsupported_pool_rejected_without_rpc():
    s, store, meta, calls, _ = make()
    meta.supported, meta.reason = False, "factory_unrecognized"
    v, _ = s.screen(meta, 2_000_000)
    assert v.rejects == ["VENUE_UNSUPPORTED"] and calls == []


def test_discovery_skips_major_pairs():
    s, store, meta, calls, _ = make()
    meta.token0, meta.token1, meta.base_index = ETH, cfg.USDG, 0     # ETH/USDG: base is native ETH
    meta.quote_token, meta.quote_class = cfg.USDG, "stable"
    assert s.discover(2_000_000) == 0 and store.candidates == []


def test_discovery_creates_candidates():
    s, store, meta, calls, _ = make()
    n = s.discover(2_000_000)
    assert n == 1 and store.candidates[0]["pool_pk"] == 7
    assert "new_pool" in store.candidates[0]["discovery"] and "top_volume" in store.candidates[0]["discovery"]
