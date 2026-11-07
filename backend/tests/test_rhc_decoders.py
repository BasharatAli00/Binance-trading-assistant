"""Decoder tests on synthetic encodings AND real recorded Robinhood Chain logs."""
import pytest

from rhc_decoders import (LiquidityEv, PoolCreatedEv, SwapEv, SyncEv, TOPICS, decode_abi_string, decode_log,
                          price1_per_0_from_reserves, price1_per_0_from_sqrt)
from rhc_fakes import ETH, MEME, PM, REF, USDG, WETH, load_fixture, mklog, sqrt_x96, topic_addr, v3_swap, v4_init, \
    v4_swap, wa, wu

MANAGERS = frozenset({PM})


def test_v3_swap_sign_normalised_to_user_perspective():
    # Pool RECEIVED 1 WETH (amount0 > 0) and SENT 3000 USDG (amount1 < 0): the user sold WETH.
    ev = decode_log(v3_swap(REF, 10 ** 18, -3000 * 10 ** 6, sqrt_x96(3000, 18, 6), 10), MANAGERS)
    assert isinstance(ev, SwapEv) and ev.kind == "v3"
    assert ev.d0 == -10 ** 18 and ev.d1 == 3000 * 10 ** 6


def test_v4_swap_sign_normalised_to_user_perspective():
    pid = "0x" + "cd" * 32
    ev = decode_log(v4_swap(pid, -10 ** 17, 10 ** 23, 1000 * 2 ** 96, 10), MANAGERS)
    assert ev.kind == "v4" and ev.pool_id == pid
    assert ev.d0 == -10 ** 17 and ev.d1 == 10 ** 23 and ev.fee == 3000


def test_v4_events_from_unknown_contract_ignored():
    lg = v4_swap("0x" + "cd" * 32, -1, 1, 2 ** 96, 10)
    lg["address"] = "0x" + "99" * 20
    assert decode_log(lg, MANAGERS) is None


def test_v4_initialize_fields():
    pid = "0x" + "ef" * 32
    hooks = "0x" + "4e" * 20
    ev = decode_log(v4_init(pid, ETH, MEME, 2 ** 96, 5, hooks=hooks), MANAGERS)
    assert isinstance(ev, PoolCreatedEv)
    assert (ev.kind, ev.pool_id, ev.token0, ev.token1, ev.fee, ev.tick_spacing, ev.hooks) == \
        ("v4", pid, ETH, MEME, 3000, 60, hooks)


def test_v2_swap_and_sync():
    pair = "0x" + "77" * 20
    swap = mklog(pair, [TOPICS["v2_swap"], topic_addr(pair), topic_addr(pair)],
                 [wu(5 * 10 ** 17), wu(0), wu(0), wu(123 * 10 ** 18)], 3)
    ev = decode_log(swap, MANAGERS)
    assert ev.kind == "v2" and ev.d0 == -5 * 10 ** 17 and ev.d1 == 123 * 10 ** 18 and ev.sqrt_price_x96 is None
    sync = decode_log(mklog(pair, [TOPICS["v2_sync"]], [wu(7), wu(9)], 3), MANAGERS)
    assert isinstance(sync, SyncEv) and (sync.reserve0, sync.reserve1) == (7, 9)


def test_negative_ticks_in_v3_mint():
    pool = "0x" + "66" * 20
    lg = mklog(pool, [TOPICS["v3_mint"], topic_addr(pool), "0x" + wu(-887220), "0x" + wu(887220)],
               [wa(pool), wu(1000), wu(5), wu(6)], 1)
    ev = decode_log(lg, MANAGERS)
    assert isinstance(ev, LiquidityEv) and ev.action == "add"
    assert ev.tick_lower == -887220 and ev.tick_upper == 887220 and ev.amount0 == 5 and ev.liquidity_delta == 1000


def test_malformed_and_unknown_logs_return_none():
    assert decode_log({"topics": ["0x" + "00" * 32], "address": REF, "data": "0x"}, MANAGERS) is None
    bad = v3_swap(REF, 1, -1, 2 ** 96, 1)
    bad["data"] = "0x1234"
    assert decode_log(bad, MANAGERS) is None
    removed = v3_swap(REF, 1, -1, 2 ** 96, 1)
    removed["removed"] = True
    assert decode_log(removed, MANAGERS) is None


def test_price_math():
    assert price1_per_0_from_sqrt(sqrt_x96(3000, 18, 6), 18, 6) == pytest.approx(3000, rel=1e-9)
    assert price1_per_0_from_reserves(2 * 10 ** 18, 6000 * 10 ** 6, 18, 6) == pytest.approx(3000)
    assert price1_per_0_from_reserves(0, 5, 18, 6) is None


def test_decode_abi_string_strips_embedded_nul_and_control_chars():
    raw = "41" + "00" + "42" + "0a" + "43"          # "A\x00B\nC"
    hexs = "0x" + wu(32) + wu(5) + raw.ljust(64, "0")
    assert decode_abi_string(hexs) == "ABC"
    assert decode_abi_string("0x" + "00" * 32) is None


def test_decode_abi_string():
    s = "0x" + wu(32) + wu(4) + "48454c4c4f".ljust(64, "0")[:64]
    assert decode_abi_string("0x" + wu(32) + wu(4) + "4f4f4f4f".ljust(64, "0")) == "OOOO"
    assert decode_abi_string("0x" + "5553444700".ljust(64, "0")) == "USDG"
    assert decode_abi_string("0x") is None
    assert s  # constructed without error


# ── real recorded chain data ──────────────────────────────────────────────────
@pytest.fixture(scope="module")
def fx():
    return load_fixture()


def test_real_logs_all_decode(fx):
    for name, logs in fx["logs"].items():
        for lg in logs:
            ev = decode_log(lg, MANAGERS)
            assert ev is not None, f"failed to decode real {name} log"


def test_real_v3_ref_swaps_give_plausible_eth_price(fx):
    meta = fx["meta"][REF]
    assert meta["token0"] == WETH and meta["token1"] == USDG
    for lg in fx["logs"]["v3_swap"]:
        ev = decode_log(lg, MANAGERS)
        assert (ev.d0 > 0) != (ev.d1 > 0), "a real swap moves tokens in opposite directions"
        eth_usd = price1_per_0_from_sqrt(ev.sqrt_price_x96, meta["dec0"], meta["dec1"])
        assert 500 < eth_usd < 20_000


def test_real_v4_swaps_opposite_signs(fx):
    for lg in fx["logs"]["v4_swap"]:
        ev = decode_log(lg, MANAGERS)
        assert ev.kind == "v4" and (ev.d0 > 0) != (ev.d1 > 0)


def test_real_v2_swap_has_matching_sync(fx):
    sw = decode_log(fx["logs"]["v2_swap"][0], MANAGERS)
    sy = decode_log(fx["logs"]["v2_sync"][0], MANAGERS)
    assert sw.pool_id == sy.pool_id and sw.ref.tx == sy.ref.tx and sy.ref.log_index < sw.ref.log_index
