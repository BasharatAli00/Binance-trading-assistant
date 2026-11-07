"""Phase 2 pure-logic tests: contract scan, holders, flow, watchlist, simulation interpretation."""
import hashlib
import os
from types import SimpleNamespace

import pytest
from eth_utils import function_signature_to_4byte_selector, keccak

import rhc_config as cfg
import rhc_watchlist as wl
from rhc_contract_scan import ContractReport, classify, extract_push4, minimal_proxy_target, scan_selectors
from rhc_flow import analyse as flow_analyse
from rhc_flow import is_wash
from rhc_holders import DEAD, analyse as holder_analyse
from rhc_holders import decode_transfer
from rhc_reasons import REASONS, is_permanent, severity
from rhc_sim import interpret, mapping_slot

ZERO = "0x" + "0" * 40


def sel(sig):
    return function_signature_to_4byte_selector(sig).hex()


# ── contract scan ─────────────────────────────────────────────────────────────
def test_extract_push4_skips_push_data():
    mint = sel("mint(address,uint256)")
    # PUSH32 whose data contains 0x63 + 4 bytes must NOT produce a selector; a real PUSH4 must.
    fake_inside = "63" + sel("pause()")
    code = "0x" + "7f" + fake_inside.ljust(64, "0") + "63" + mint + "14"
    found = extract_push4(code)
    assert "0x" + mint in found
    assert "0x" + sel("pause()") not in found


def test_scan_selectors_and_classify_matrix():
    code = "0x" + "".join("63" + sel(s) for s in ("mint(address,uint256)", "pause()", "setBuyFee(uint256)"))
    funcs = scan_selectors(code)
    assert funcs["MINT_FN"] == ["mint(address,uint256)"] and funcs["PAUSE_FN"] == ["pause()"]
    live = ContractReport("0xt", True, owner="0x" + "11" * 20, owner_active=True, functions=funcs)
    assert set(classify(live)) == {"MINTABLE", "PAUSABLE", "FEE_SETTER", "OWNER_ACTIVE"}
    renounced = ContractReport("0xt", True, owner=ZERO, owner_active=False, functions=funcs)
    assert classify(renounced) == []
    no_owner_fn = ContractReport("0xt", True, owner=None, owner_active=False, functions=funcs)
    assert {"MINTABLE", "PAUSABLE"} <= set(classify(no_owner_fn))     # cannot prove renounced
    proxy = ContractReport("0xt", True, proxy="eip1967", owner=ZERO, functions={})
    assert classify(proxy) == ["UPGRADEABLE"]
    assert classify(ContractReport("0xt", False)) == ["NO_CODE"]


def test_minimal_proxy_target():
    impl = "ab" * 20
    assert minimal_proxy_target("0x363d3d373d3d3d363d73" + impl + "5af43d82803e903d91602b57fd5bf3") == "0x" + impl
    assert minimal_proxy_target("0x6080604052") is None


# ── holders ───────────────────────────────────────────────────────────────────
POOL = "0x" + "aa" * 20
DEV = "0x" + "d0" * 20
A, B, C = ("0x" + x * 20 for x in ("a1", "b2", "c3"))


def test_holder_concentration_excludes_pools_and_burn():
    supply = 1_000
    tx = [(1, 0, ZERO, DEV, 1_000),          # mint to deployer
          (2, 0, DEV, POOL, 600),            # liquidity
          (3, 0, DEV, DEAD, 100),            # burn
          (4, 0, POOL, A, 150), (5, 0, POOL, B, 50), (6, 0, POOL, C, 10)]
    rep = holder_analyse(tx, supply, excluded={POOL})
    assert rep.deployer == DEV and rep.deployer_pct == pytest.approx(30.0)
    assert rep.burned_pct == pytest.approx(10.0)
    assert rep.holders == 4 and rep.top1_pct == pytest.approx(30.0)
    assert rep.top10_pct == pytest.approx(30 + 15 + 5 + 1)
    assert rep.insider_pct == pytest.approx(51.0)            # DEV, A, B, C are the first recipients


def test_holder_live_balance_override():
    tx = [(1, 0, ZERO, A, 100)]
    rep = holder_analyse(tx, 100, excluded=set(), balances_override={A: 40})
    assert rep.top1_pct == pytest.approx(40.0)


def test_decode_transfer_ignores_erc721():
    t0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    pad = lambda a: "0x" + "0" * 24 + a[2:]
    erc20 = {"topics": [t0, pad(A), pad(B)], "data": "0x" + "0" * 63 + "5", "blockNumber": "0x1", "logIndex": "0x0"}
    erc721 = {"topics": [t0, pad(A), pad(B), "0x" + "0" * 63 + "1"], "data": "0x", "blockNumber": "0x1",
              "logIndex": "0x0"}
    assert decode_transfer(erc20) == (1, 0, A, B, 5)
    assert decode_transfer(erc721) is None


# ── flow ──────────────────────────────────────────────────────────────────────
def T(side, usd, trader, block=1, tx=None):
    return SimpleNamespace(side=side, usd=usd, trader=trader, block=block, tx=tx or f"0x{trader}{block}{side}")


def test_flow_metrics_and_wash_detection():
    organic = [T("buy", 10, f"w{i}", block=i) for i in range(30)] + [T("sell", 5, f"w{i}", block=100 + i)
                                                                       for i in range(5)]
    rep = flow_analyse(organic, nonces={f"w{i}": (0 if i < 3 else 50) for i in range(30)})
    assert rep.traders == 30 and rep.buys == 30 and rep.sells == 5
    assert rep.top3_share < 0.2 and not is_wash(rep)
    assert rep.fresh_trader_share == pytest.approx(3 / 30)
    wash = [T("buy" if i % 2 else "sell", 100, f"x{i % 2}", block=i) for i in range(40)]
    rep2 = flow_analyse(wash)
    assert rep2.traders == 2 and is_wash(rep2)


def test_bundled_buy_blocks():
    trades = [T("buy", 10, f"b{i}", block=7) for i in range(4)] + [T("buy", 10, "solo", block=8)]
    assert flow_analyse(trades).bundled_blocks == 1


# ── watchlist ─────────────────────────────────────────────────────────────────
def test_discovery_reasons_and_score():
    now = 10_000_000
    st = (50_000.0, 200, now)
    r = wl.discovery_reasons(st, (20_000.0, 9_000.0), now - 3600, now, 5, cfg)
    assert r == ["new_pool", "volume_surge", "top_volume"]
    assert wl.discovery_reasons((100.0, 2, now), (0, 0), None, now, 0, cfg) == []
    assert wl.score(st, r) > wl.score(st, ["top_volume"])


def test_after_screen_cooldowns():
    now = 1_000_000
    assert wl.after_screen("pass", [], now, cfg) == ("watch", now + cfg.RHC_RESCREEN_WATCH_MIN * 60)
    assert wl.after_screen("reject", ["HONEYPOT"], now, cfg) == ("rejected", now + cfg.RHC_RESCREEN_PERMANENT_H * 3600)
    assert wl.after_screen("reject", ["ILLIQUID"], now, cfg) == ("rejected", now + cfg.RHC_RESCREEN_TRANSIENT_MIN * 60)


def test_due_order_candidates_first_then_score():
    rows = [{"pool_pk": 1, "state": "watch", "next_screen_ts": 0, "score": 9},
            {"pool_pk": 2, "state": "candidate", "next_screen_ts": 0, "score": 1},
            {"pool_pk": 3, "state": "rejected", "next_screen_ts": 999, "score": 9},
            {"pool_pk": 4, "state": "expired", "next_screen_ts": 0, "score": 9}]
    assert [r["pool_pk"] for r in wl.due(rows, 100, 5)] == [2, 1]


def test_should_expire():
    assert wl.should_expire("watch", 0 + 1, 10 ** 9, cfg)
    assert not wl.should_expire("watch", 10 ** 9 - 60, 10 ** 9, cfg)


# ── reasons catalog ───────────────────────────────────────────────────────────
def test_every_emitted_code_is_catalogued():
    import rhc_screener
    emitted = set(rhc_screener._SIM_TO_CODE.values()) | set(rhc_screener._REASON_TO_CODE.values())
    emitted |= {"MINTABLE", "BLACKLIST", "PAUSABLE", "UPGRADEABLE", "FEE_SETTER", "MAXTX_SETTER", "TRADING_TOGGLE",
                "OWNER_ACTIVE", "NO_CODE", "TOO_NEW", "LOW_ACTIVITY", "ILLIQUID", "LIQ_UNKNOWN", "TAX_HIGH",
                "COST_TOO_HIGH", "IMPACT_TOO_HIGH", "SIM_UNAVAILABLE", "CONCENTRATED", "INSIDER_HEAVY",
                "HOLDERS_PARTIAL", "WASH_SUSPECT", "FRESH_WALLET_HEAVY", "BUNDLED_BUYS", "LP_NOT_BURNED",
                "LP_LOCK_UNKNOWN", "RECENT_LP_REMOVAL"}
    src = open(rhc_screener.__file__, encoding="utf-8").read()
    for code in emitted:
        assert code in REASONS, code
    for code in REASONS:
        assert code in src or code in emitted, f"{code} is catalogued but never emitted"
    assert severity("WASH_SUSPECT", {"WASH_SUSPECT": "warn"}) == "warn"
    assert is_permanent("HONEYPOT") and not is_permanent("ILLIQUID")


# ── simulation ────────────────────────────────────────────────────────────────
def test_interpret_taxes_and_statuses():
    ok = interpret([0, 1000, 950, 900, 500, 490, 100_000, 40_000], 520)
    assert ok.ok and ok.buy_tax == pytest.approx(0.05) and ok.sell_tax == pytest.approx(900 / 950 * -1 + 1)
    assert ok.round_trip_cost == pytest.approx(1 - 490 / 520)
    assert interpret([4, 0, 0, 0, 0, 0, 1, 0], 10).status == "NO_LIQUIDITY"
    assert interpret([4, 500, 0, 0, 0, 0, 1, 0], 10).status == "ZERO_RECEIVED"
    hp = interpret([3, 100, 100, 0, 0, 0, 1, 0], 10)
    assert hp.status == "SELL_FAILED" and hp.round_trip_cost is None
    assert interpret([2, 100, 100, 0, 0, 0, 1, 0], 10).status == "SELL_TRANSFER_BLOCKED"


def test_mapping_slot_matches_solidity_layout():
    holder = "0x" + "12" * 20
    expected = "0x" + keccak(bytes.fromhex("0" * 24 + "12" * 20) + (51).to_bytes(32, "big")).hex().removeprefix("0x")
    assert mapping_slot(holder, 51) == expected
    vy = "0x" + keccak((3).to_bytes(32, "big") + bytes.fromhex("0" * 24 + "12" * 20)).hex().removeprefix("0x")
    assert mapping_slot(holder, 3, vyper=True) == vy


def test_simulator_bytecode_is_built_from_current_source():
    import rhc_sim_bytecode as b
    src = os.path.join(os.path.dirname(b.__file__), "contracts", "RhcSimulator.sol")
    with open(src, "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == b.SOURCE_SHA256, \
            "RhcSimulator.sol changed: rebuild with contracts/build_simulator.js"
    assert b.RUNTIME.startswith("0x") and len(b.RUNTIME) > 1000
