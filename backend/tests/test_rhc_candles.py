import random

import pytest

from rhc_candles import TF_1M, TF_5M, CandleBook, PoolActivity, select_tracked
from rhc_market import Trade

T0 = 1_780_000_200  # divisible by 300


def tr(ts, price, usd=10.0, side="buy", pk=1, tx=None, trader=None, li=0):
    return Trade(pool_pk=pk, pool_id=f"p{pk}", ts=ts, block=ts, tx=tx or f"0x{ts}{li}", log_index=li, side=side,
                 base_amt=1.0, quote_amt=usd, price_q=price, price_usd=price, usd=usd, trader=trader)


def test_bucketing_and_ohlc():
    b = CandleBook(grace_s=5)
    for t in [tr(T0 + 1, 10), tr(T0 + 20, 12, side="sell"), tr(T0 + 50, 9), tr(T0 + 59, 11)]:
        b.add_trade(t)
    b.add_trade(tr(T0 + 61, 20))
    closed = b.close_until(T0 + 60 + 4)            # within grace: nothing closes
    assert closed == []
    closed = b.close_until(T0 + 65)
    one = [c for c in closed if c.tf == TF_1M]
    assert len(one) == 1
    c = one[0].to_row()
    assert (c["o"], c["h"], c["l"], c["c"]) == (10, 12, 9, 11)
    assert (c["buys"], c["sells"], c["vol_usd"], c["sell_usd"]) == (3, 1, 40.0, 10.0)
    # 5m candle still open and includes the 6th-minute trade later
    closed5 = [c for c in b.close_until(T0 + 305) if c.tf == TF_5M]
    assert closed5[0].to_row()["h"] == 20 and closed5[0].n == 5


def test_traders_exact_flag_and_unique_count():
    b = CandleBook()
    b.add_trade(tr(T0 + 1, 1, trader="0xa"))
    b.add_trade(tr(T0 + 2, 1, trader="0xa"))
    b.add_trade(tr(T0 + 3, 1, trader="0xb"))
    c = [x for x in b.close_until(T0 + 400) if x.tf == TF_1M][0]
    assert c.traders == 2 and c.traders_exact
    b.add_trade(tr(T0 + 401, 1))                 # unresolved trader -> falls back to tx, flagged inexact
    c = [x for x in b.close_until(T0 + 900) if x.tf == TF_1M][0]
    assert not c.traders_exact


def test_large_trade_count():
    b = CandleBook(large_usd=1000)
    b.add_trade(tr(T0 + 1, 1, usd=999))
    b.add_trade(tr(T0 + 2, 1, usd=1000))
    c = [x for x in b.close_until(T0 + 100) if x.tf == TF_1M][0]
    assert c.large == 1


def test_skip_before_ts():
    b = CandleBook()
    b.skip_before_ts = T0 + 300
    assert b.add_trade(tr(T0 + 10, 1)) is False
    assert b.add_trade(tr(T0 + 300, 1)) is True


def test_idempotent_same_trades_same_rows():
    trades = [tr(T0 + i * 7, 1 + (i % 5), usd=float(i), side="buy" if i % 3 else "sell", li=i, trader=f"0x{i % 4}")
              for i in range(200)]

    def run(ts):
        b = CandleBook()
        for t in ts:
            b.add_trade(t)
        return sorted((c.to_row() for c in b.close_until(T0 + 10_000)), key=lambda r: (r["tf"], r["bucket"]))

    assert run(trades) == run(list(trades))


def test_oldest_open_start():
    b = CandleBook()
    assert b.oldest_open_start(TF_5M, T0 + 123) == T0
    b.add_trade(tr(T0 + 610, 1))
    b.add_trade(tr(T0 + 950, 1))
    assert b.oldest_open_start(TF_5M, T0 + 999) == T0 + 600


def test_ring_keeps_recent_closed():
    b = CandleBook(ring_size=3)
    for m in range(6):
        b.add_trade(tr(T0 + m * 60 + 1, 1))
    b.close_until(T0 + 10_000, keep_ring_for={1})
    ring_1m = [c for c in b.ring(1) if c.tf == TF_1M]
    assert len(ring_1m) == 3 and ring_1m[-1].bucket == T0 + 300


def test_pool_activity_window():
    a = PoolActivity(window_s=3600)
    a.add(tr(T0, 1, usd=100, pk=1))
    a.add(tr(T0 + 30, 1, usd=50, pk=1))
    a.add(tr(T0 + 4000, 1, usd=7, pk=2))
    s = a.stats(T0 + 4000)
    assert 1 not in s and s[2][0] == 7
    s2 = PoolActivity()
    s2.add(tr(T0, 1, usd=100, pk=1))
    s2.add(tr(T0 + 30, 1, usd=50, pk=1))
    assert s2.stats(T0 + 60)[1] == (150, 2, T0 + 30)


def test_surge_window_splits_recent_and_prior():
    a = PoolActivity()
    now = T0 + 3600
    a.add(tr(now - 60, 1, usd=100, pk=1))          # recent (last 15 min)
    a.add(tr(now - 1800, 1, usd=40, pk=1))         # prior 45 min
    a.add(tr(now - 3700, 1, usd=999, pk=1))        # older than 60 min -> neither
    assert a.surge_window(1, now) == (100, 40)
    assert isinstance(a.window, int)               # the window length attribute is not shadowed


def test_execution_price_drives_ohlc_and_marginal_is_kept():
    b = CandleBook()
    t = tr(T0 + 1, 2.0)
    t.exec_q, t.exec_usd = 1.8, 1.8                # paid 1.8; pool marginal price after the swap is 2.0
    b.add_trade(t)
    c = [x for x in b.close_until(T0 + 100) if x.tf == TF_1M][0].to_row()
    assert c["c"] == 1.8 and c["c_usd"] == 1.8 and c["c_mid"] == 2.0


def test_select_tracked_policy():
    now = T0 + 10_000
    stats = {1: (100_000, 500, now), 2: (8_000, 30, now), 3: (6_000, 25, now), 4: (4_000, 100, now),
             5: (9_000, 5, now), 9: (0, 0, now - 50_000)}
    got = select_tracked(set(), stats, always={9}, now_ts=now, max_pools=3, min_vol_usd=5_000, min_swaps=20,
                         idle_min=120)
    assert got == {9, 1, 2}                       # ref pool always; pools 4/5 fail thresholds
    # Hysteresis: with spare capacity, tracked pool 3 stays while active even if it no longer qualifies
    stats[3] = (100, 1, now)
    got2 = select_tracked({9, 1, 3}, stats, {9}, now, 4, 5_000, 20, 120)
    assert 3 in got2
    # ...but at the cap a much busier candidate (pool 2) displaces it
    got3 = select_tracked({9, 1, 3}, stats, {9}, now, 3, 5_000, 20, 120)
    assert 3 not in got3 and 2 in got3
    # Idle pools are dropped
    stats[3] = (0, 0, now - 3 * 3600)
    assert 3 not in select_tracked({9, 1, 3}, stats, {9}, now, 3, 5_000, 20, 120)


def test_select_tracked_displaces_much_quieter_pool_at_cap():
    now = T0
    stats = {1: (6_000, 30, now), 2: (900_000, 900, now)}
    got = select_tracked({1}, stats, set(), now, 1, 5_000, 20, 120)
    assert got == {2}


def test_select_tracked_cap_random():
    rng = random.Random(1)
    now = T0
    stats = {pk: (rng.uniform(0, 50_000), rng.randint(0, 100), now) for pk in range(300)}
    got = select_tracked(set(), stats, {999}, now, 50, 5_000, 20, 120)
    assert len(got) <= 50 and 999 in got
    qualifying = sorted((pk for pk, (u, n, _) in stats.items() if u >= 5_000 and n >= 20),
                        key=lambda pk: stats[pk][0], reverse=True)
    assert set(qualifying[:49]) <= got
