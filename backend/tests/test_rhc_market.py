import pytest

from rhc_decoders import decode_log
from rhc_fakes import ETH, MEME, PM, REF, USDG, WETH, load_fixture, sqrt_x96, v3_swap, v4_swap
from rhc_market import PoolMeta, QuotePricer, classify_pool, swap_to_trade

STABLE = {USDG}
ETHS = {ETH, WETH}


@pytest.mark.parametrize("t0,t1,expect", [
    (WETH, USDG, (0, USDG, "stable", None)),
    (USDG, WETH, (1, USDG, "stable", None)),
    (ETH, MEME, (1, ETH, "eth", None)),
    (MEME, WETH, (0, WETH, "eth", None)),
    (MEME, USDG, (0, USDG, "stable", None)),
    (ETH, WETH, (None, None, None, "wrap_pair")),
    (MEME, "0x" + "12" * 20, (None, None, None, "no_supported_quote")),
])
def test_classify_pool(t0, t1, expect):
    assert classify_pool(t0, t1, STABLE, ETHS) == expect


def _meta(pool_id, kind, t0, t1, d0, d1):
    b, qt, qc, _ = classify_pool(t0, t1, STABLE, ETHS)
    return PoolMeta(pool_id=pool_id, kind=kind, token0=t0, token1=t1, dec0=d0, dec1=d1, base_index=b,
                    quote_token=qt, quote_class=qc, supported=True, pk=1)


def test_v3_sell_weth_into_usdg():
    meta = _meta(REF, "v3", WETH, USDG, 18, 6)
    ev = decode_log(v3_swap(REF, 10 ** 18, -2990 * 10 ** 6, sqrt_x96(2995, 18, 6), 10), frozenset({PM}))
    t = swap_to_trade(meta, ev, 1000, quote_usd=1.0)
    assert t.side == "sell" and t.base_amt == pytest.approx(1.0) and t.quote_amt == pytest.approx(2990)
    assert t.price_q == pytest.approx(2995, rel=1e-9)        # post-swap pool price, not execution price
    assert t.usd == pytest.approx(2990) and t.price_usd == pytest.approx(2995, rel=1e-9)


def test_v4_buy_meme_with_native_eth_quote_is_token0():
    pid = "0x" + "cd" * 32
    meta = _meta(pid, "v4", ETH, MEME, 18, 18)
    # 1 ETH = 1e6 MEME -> price of token0 in token1 = 1e6 -> MEME price = 1e-6 ETH
    ev = decode_log(v4_swap(pid, -10 ** 17, 10 ** 23, 1000 * 2 ** 96, 10), frozenset({PM}))
    t = swap_to_trade(meta, ev, 1000, quote_usd=3000.0)
    assert t.side == "buy"
    assert t.price_q == pytest.approx(1e-6, rel=1e-9)
    assert t.price_usd == pytest.approx(0.003, rel=1e-9)
    assert t.usd == pytest.approx(300.0)


def test_unusable_swaps_rejected():
    meta = _meta(REF, "v3", WETH, USDG, 18, 6)
    same_dir = decode_log(v3_swap(REF, -5, -5, 2 ** 96, 1), frozenset({PM}))
    assert swap_to_trade(meta, same_dir, 1, 1.0) is None
    zero = decode_log(v3_swap(REF, 0, -5, 2 ** 96, 1), frozenset({PM}))
    assert swap_to_trade(meta, zero, 1, 1.0) is None
    meta.dec1 = None
    ok = decode_log(v3_swap(REF, 5, -5, 2 ** 96, 1), frozenset({PM}))
    assert swap_to_trade(meta, ok, 1, 1.0) is None


def test_no_usd_when_quote_price_unknown():
    meta = _meta("0x" + "cd" * 32, "v4", ETH, MEME, 18, 18)
    ev = decode_log(v4_swap(meta.pool_id, -10 ** 17, 10 ** 23, 1000 * 2 ** 96, 1), frozenset({PM}))
    t = swap_to_trade(meta, ev, 1, quote_usd=QuotePricer().usd("eth"))
    assert t.usd is None and t.price_usd is None and t.price_q > 0


def test_real_v2_swap_with_reserves():
    fx = load_fixture()
    sw = decode_log(fx["logs"]["v2_swap"][0], frozenset({PM}))
    sy = decode_log(fx["logs"]["v2_sync"][0], frozenset({PM}))
    m = fx["meta"][sw.pool_id]
    meta = _meta(sw.pool_id, "v2", m["token0"], m["token1"], m["dec0"], m["dec1"])
    t = swap_to_trade(meta, sw, 1, quote_usd=3000.0, reserves=(sy.reserve0, sy.reserve1))
    assert t is not None and t.price_q > 0 and t.usd > 0 and t.liq_usd > 0
