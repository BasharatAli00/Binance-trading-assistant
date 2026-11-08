"""End-to-end indexer tests against a deterministic fake chain (no network, no DB)."""
import pytest

import rhc_config as cfg
from rhc_fakes import (ETH, MEME, PM, REF, T0, FakeRpc, FakeStore, sqrt_x96, standard_calls, v3_swap, v4_init,
                       v4_swap, wu)
from rhc_indexer import Indexer
from rhc_registry import Registry

HEAD = 100_000
MEME_ID = "0x" + "cd" * 32
OLD_ID = "0x" + "ee" * 32           # pool initialised long before the indexer's start window


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(cfg, "RHC_TRACK_REVIEW_S", 0)
    monkeypatch.setattr(cfg, "RHC_TRACK_MIN_VOL_USD_1H", 0.0)
    monkeypatch.setattr(cfg, "RHC_TRACK_MIN_SWAPS_1H", 1)
    monkeypatch.setattr(cfg, "RHC_RESOLVE_TRADERS", False)
    monkeypatch.setattr(cfg, "RHC_START_LOOKBACK_BLOCKS", 6_000)
    monkeypatch.setattr(cfg, "RHC_CONFIRMATIONS", 20)


def chain_logs():
    logs = [v4_init(OLD_ID, ETH, MEME, 1000 * 2 ** 96, 10)]
    sp_ref = sqrt_x96(3000.0, 18, 6)
    for i, b in enumerate(range(93_000, HEAD, 50)):
        amt = (i % 7 + 1) * 10 ** 16
        if i % 2:
            logs.append(v3_swap(REF, amt, -int(amt / 1e18 * 3000 * 1e6), sp_ref, b, li=0))
        else:
            logs.append(v3_swap(REF, -amt, int(amt / 1e18 * 3000 * 1e6), sp_ref, b, li=0))
    logs.append(v4_init(MEME_ID, ETH, MEME, 1000 * 2 ** 96, 94_000, li=1))
    for i, b in enumerate(range(94_010, HEAD, 30)):
        price_tokens_per_eth = 1_000_000 - (i % 50) * 1000      # MEME/ETH varies
        sp = int((price_tokens_per_eth ** 0.5) * 2 ** 96)
        eth = (i % 5 + 1) * 10 ** 16
        if i % 3:
            logs.append(v4_swap(MEME_ID, -eth, eth * price_tokens_per_eth, sp, b, li=2))
        else:
            logs.append(v4_swap(MEME_ID, eth, -eth * price_tokens_per_eth, sp, b, li=2))
    for i, b in enumerate(range(95_005, HEAD, 400)):
        logs.append(v4_swap(OLD_ID, -10 ** 16, 10 ** 22, 1000 * 2 ** 96, b, li=3))
    return logs


def make(store=None, rpc=None):
    rpc = rpc or FakeRpc(chain_logs(), head=HEAD, calls=standard_calls())
    store = store or FakeStore()
    reg = Registry(rpc, store, clock=lambda: T0 + 20_000)
    idx = Indexer(rpc, store, reg, clock=lambda: T0 + 10_000, sleep=lambda s: None)
    return idx, store, rpc


def run_until_caught_up(idx, max_steps=500, stop_after=None):
    steps = 0
    while steps < max_steps:
        if stop_after is not None and steps >= stop_after:
            return steps
        if not idx.step():
            return steps
        steps += 1
    raise AssertionError("did not catch up")


def test_full_run_builds_closed_complete_candles():
    idx, store, rpc = make()
    idx.bootstrap()
    first_full = idx.book.skip_before_ts
    assert first_full % 300 == 0 and first_full >= rpc.ts(HEAD - 20 - 6000)
    run_until_caught_up(idx)
    assert idx.next_block == HEAD - 20 + 1
    meme = idx.registry.get(MEME_ID)
    ref = idx.registry.get(REF)
    assert meme.supported and ref.supported and meme.quote_class == "eth" and ref.quote_class == "stable"
    assert idx.pricer.eth_usd == pytest.approx(3000.0, rel=1e-6)
    rows = list(store.candles.values())
    assert {r["pool_pk"] for r in rows} >= {meme.pk, ref.pk}
    last_ts = idx.metrics["processed_ts"]
    for r in rows:
        assert r["bucket"] >= first_full, "no partial first bucket may be written"
        assert r["bucket"] + r["tf"] + cfg.RHC_CANDLE_GRACE_S <= last_ts, "only closed candles are written"
        assert r["l"] <= min(r["o"], r["c"]) and r["h"] >= max(r["o"], r["c"])
    # 1m volume sums to the 5m volume for every complete 5m bucket of the meme pool
    by5 = {r["bucket"]: r for r in rows if r["pool_pk"] == meme.pk and r["tf"] == 300}
    for b5, r5 in by5.items():
        ones = [r for r in rows if r["pool_pk"] == meme.pk and r["tf"] == 60 and b5 <= r["bucket"] < b5 + 300]
        assert sum(o["vol_usd"] for o in ones) == pytest.approx(r5["vol_usd"])
        assert sum(o["buys"] + o["sells"] for o in ones) == r5["buys"] + r5["sells"]
    # MEME price in USD = (1 / tokens_per_eth) * 3000 -> around 0.003
    usd_prices = [r["c_usd"] for r in rows if r["pool_pk"] == meme.pk]
    assert all(0.0029 < p < 0.0032 for p in usd_prices)


def test_restart_produces_identical_candles():
    a, store_a, _ = make()
    a.bootstrap()
    run_until_caught_up(a)

    b, store_b, rpc_b = make()
    b.bootstrap()
    run_until_caught_up(b, stop_after=2)          # crash mid-way
    cp = store_b.checkpoints["chain"]
    assert cp["resume_from_ts"] % 300 == 0
    b2 = Indexer(rpc_b, store_b, Registry(rpc_b, store_b, clock=lambda: T0 + 20_000),
                 clock=lambda: T0 + 10_000, sleep=lambda s: None)
    b2.bootstrap()
    assert b2.next_block == cp["block"] + 1 and b2.book.skip_before_ts == cp["resume_from_ts"]
    run_until_caught_up(b2)
    assert store_b.candles == store_a.candles


def test_lease_loss_stops_writes_and_resync_gives_identical_candles():
    from rhc_indexer import WriterLeaseLost
    a, store_a, _ = make()
    a.bootstrap()
    run_until_caught_up(a)

    b, store_b, rpc = make()
    held = {"v": True}
    b.write_gate = lambda: held["v"]
    b.bootstrap()
    run_until_caught_up(b, stop_after=2)
    held["v"] = False
    writes_before = store_b.writes
    assert b.step() is False and b.metrics["mode"] == "standby_no_lease"
    # Lost mid-chunk: nothing is written and a resync is forced.
    with pytest.raises(WriterLeaseLost):
        b.process_range(b.next_block, b.next_block + 500, rpc.get_logs({}, b.next_block, b.next_block + 500))
    assert store_b.writes == writes_before and b.resync_needed
    held["v"] = True
    run_until_caught_up(b)
    assert store_b.candles == store_a.candles


def test_failed_step_never_double_counts():
    """A DB error after trades entered the candle book must not lead to double counting."""
    a, store_a, _ = make()
    a.bootstrap()
    run_until_caught_up(a)

    b, store_b, _ = make()
    b.bootstrap()
    run_until_caught_up(b, stop_after=1)
    real = store_b.upsert_candles
    state = {"fail": True}

    def flaky(rows):
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("server closed the connection unexpectedly")
        return real(rows)
    store_b.upsert_candles = flaky
    raised = False
    for _ in range(200):
        try:
            if not b.step():
                break
        except RuntimeError:
            raised = True
            b.resync_needed = True       # what run_forever's handler does
            break
    assert raised, "the injected failure must have fired after trades entered the book"
    run_until_caught_up(b)
    common = set(store_a.candles) & set(store_b.candles)
    assert common, "runs must overlap"
    for k in common:   # no double counting: every candle both runs wrote is identical
        assert store_a.candles[k] == store_b.candles[k], k
    ref_pk = b.registry.get(REF).pk          # always tracked -> its series must match exactly
    assert {k: v for k, v in store_a.candles.items() if k[0] == ref_pk} == \
           {k: v for k, v in store_b.candles.items() if k[0] == ref_pk}


def test_run_forever_sets_resync_on_failure():
    idx, store, _ = make()
    idx.bootstrap()
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        idx.stop_event.set()
        raise RuntimeError("x")
    idx.step = boom
    idx.sleep = lambda s: None
    idx.run_forever()
    assert calls["n"] == 1 and idx.resync_needed is True


def test_checkpoint_only_before_oldest_open_bucket():
    idx, store, rpc = make()
    idx.bootstrap()
    run_until_caught_up(idx, stop_after=1)
    cp = store.checkpoints["chain"]
    assert cp["block_ts"] < cp["resume_from_ts"]
    assert cp["resume_from_ts"] <= idx.book.oldest_open_start(300, idx.metrics["processed_ts"])


def test_on_demand_v4_resolution_from_old_initialize():
    idx, store, _ = make()
    idx.bootstrap()
    run_until_caught_up(idx)
    old = idx.registry.get(OLD_ID)
    assert old is not None and old.supported and old.pk is not None


def test_untracked_pools_write_nothing(monkeypatch):
    monkeypatch.setattr(cfg, "RHC_TRACK_MIN_VOL_USD_1H", 10 ** 12)   # nothing qualifies except the ref pool
    idx, store, _ = make()
    idx.bootstrap()
    run_until_caught_up(idx)
    ref = idx.registry.get(REF)
    assert {r["pool_pk"] for r in store.candles.values()} == {ref.pk}


def test_gap_recorded_when_downtime_exceeds_catchup(monkeypatch):
    monkeypatch.setattr(cfg, "RHC_MAX_CATCHUP_BLOCKS", 1_000)
    idx, store, _ = make()
    store.save_checkpoint("chain", 50_000, T0, "0x" + "00" * 32, T0)
    idx.bootstrap()
    assert store.gaps and store.gaps[0][0] == "chain" and store.gaps[0][1] == 50_001
    assert store.gaps[0][3] == "downtime_exceeds_max_catchup"
    assert idx.next_block == HEAD - 20 - 6000


def test_resume_within_catchup_window_no_gap():
    idx, store, _ = make()
    idx.bootstrap()
    run_until_caught_up(idx, stop_after=1)
    idx2, _, _ = make(store=store)
    idx2.bootstrap()
    assert store.gaps == []


class ForkingRpc(FakeRpc):
    fork = False

    def _block(self, b):
        blk = super()._block(b)
        if self.fork:
            blk["hash"] = "0x" + format(b + 7, "064x")
        return blk


def test_reorg_rewinds_to_durable_checkpoint():
    rpc = ForkingRpc(chain_logs(), head=HEAD, calls=standard_calls())
    idx, store, _ = make(rpc=rpc)
    idx.bootstrap()
    run_until_caught_up(idx, stop_after=2)
    cp = store.checkpoints["chain"]
    rpc.fork = True
    assert idx.step() is True
    assert idx.metrics["reorgs"] == 1 and idx.next_block == cp["block"] + 1
    rpc.fork = False
    run_until_caught_up(idx)


def test_v4_resolution_via_position_manager_is_hash_verified():
    from eth_utils import keccak
    from rhc_fakes import wa
    posm = cfg.RHC_V4_POSITION_MANAGERS[0]
    words = [wa(ETH), wa(MEME), wu(3000), wu(60), wa(ETH)]
    real_id = "0x" + keccak(hexstr="".join(words)).hex().removeprefix("0x")
    fake_id = "0x" + "aa" * 32           # PositionManager returns the same key, but it hashes to real_id
    calls = standard_calls()
    for pid in (real_id, fake_id):
        calls[(posm, "0x86b6be7d" + pid[2:52].ljust(64, "0"))] = "0x" + "".join(words)
    rpc = FakeRpc([], head=HEAD, calls=calls)
    reg = Registry(rpc, FakeStore())
    reg.resolve({real_id: "v4", fake_id: "v4"})
    m = reg.get(real_id)
    assert m is not None and (m.token0, m.token1, m.fee) == (ETH, MEME, 3000) and m.supported
    assert reg.get(fake_id) is None, "a key that does not hash to the pool id must be rejected"


def test_v4_scan_cap_defers_instead_of_marking_unresolvable(monkeypatch):
    monkeypatch.setattr(cfg, "RHC_V4_SCAN_MAX_IDS", 1)
    rpc = FakeRpc([], head=HEAD, calls=standard_calls())
    reg = Registry(rpc, FakeStore())
    ids = {"0x" + f"{i:02x}" * 32: "v4" for i in range(1, 4)}
    reg.resolve(ids)
    assert len(reg._unresolvable) == 1          # only the one actually scanned


def test_liquidity_event_storage_policy():
    from rhc_decoders import LiquidityEv, LogRef
    idx, store, _ = make()
    idx.bootstrap()
    run_until_caught_up(idx)
    meme = idx.registry.get(MEME_ID)
    ref = LogRef(block=HEAD - 30, tx="0x" + "77" * 32, log_index=9, address=PM)
    add = LiquidityEv("v4", MEME_ID, "add", None, None, 10 ** 18, -60, 60, ref)
    rem = LiquidityEv("v4", MEME_ID, "remove", None, None, -10 ** 18, -60, 60,
                      LogRef(HEAD - 30, "0x" + "78" * 32, 10, PM))
    row_add = idx._liq_row(meme, add, 1)
    assert row_add["usd"] is None                           # v4 adds are unpriced -> not stored by default
    keep = [e for e in (add, rem) if e.action == "remove" or cfg.RHC_LIQ_STORE_ALL_ADDS
            or (idx._liq_row(meme, e, 1)["usd"] or 0) >= cfg.RHC_LIQ_ADD_MIN_USD]
    assert keep == [rem]


def test_unknown_factory_v3_pool_is_unsupported():
    rogue = "0x" + "99" * 20
    calls = standard_calls()
    calls.update({(rogue, "0x0dfe1681"): "0x" + "0" * 24 + MEME[2:], (rogue, "0xd21220a7"): calls[(REF, "0x0dfe1681")],
                  (rogue, "0xc45a0155"): "0x" + "0" * 24 + "12" * 20, (rogue, "0xddca3f43"): "0x" + wu(3000)})
    logs = chain_logs() + [v3_swap(rogue, 10 ** 18, -10 ** 15, 2 ** 96, 98_000, li=5)]
    rpc = FakeRpc(logs, head=HEAD, calls=calls)
    idx, store, _ = make(rpc=rpc)
    idx.bootstrap()
    run_until_caught_up(idx)
    m = idx.registry.get(rogue)
    assert m is not None and not m.supported and m.reason == "factory_unrecognized"
    assert idx.registry.unrecognized_factories["0x" + "12" * 20] == 1
