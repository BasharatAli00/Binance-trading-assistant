"""Phase 4: fill model, exits, PaperBroker, metrics + sample gate, backtest, go-live gate, LiveBroker."""
import copy
import sys
from types import SimpleNamespace

import pytest

import rhc_config as cfg
from rhc_gate import evaluate as gate
from rhc_live_broker import LiveBroker, LiveTradingDisabled
from rhc_market import PoolMeta, QuotePricer
from rhc_metrics import bootstrap_ci, compute, max_drawdown, sample_gate, wilson
from rhc_paper import PaperBroker, Position, fails, gas_usd, manage
from rhc_sim import SellResult, SimResult, interpret_sell

ETH = "0x" + "0" * 40
MEME = "0x" + "ab" * 20


def pos(**kw):
    base = dict(pool_pk=1, token=MEME, strategy="s", opened_ts=0, entry_price=1.0, tokens=100.0, tokens_raw=100 * 10 ** 18,
                cost_usd=100.0, stop=0.95, stop_pct=0.05, targets=[1.075, 1.15], time_stop_ts=10_000, peak=1.0)
    base.update(kw)
    return Position(**base)


def C(o, h, l, c):
    return {"o_usd": o, "h_usd": h, "l_usd": l, "c_usd": c}


# ── exits ─────────────────────────────────────────────────────────────────────
def test_stop_fills_at_stop_or_at_gap_open():
    assert manage(pos(), C(1.0, 1.01, 0.94, 0.96), 100) == [("SELL", 1.0, "STOP", 0.95)]
    assert manage(pos(), C(0.90, 0.92, 0.85, 0.9), 100) == [("SELL", 1.0, "STOP", 0.90)]      # gap -> open


def test_stop_wins_when_stop_and_target_touch_same_candle():
    assert manage(pos(), C(1.0, 1.2, 0.9, 1.1), 100)[0][2] == "STOP"


def test_tp1_partial_breakeven_then_trailing_then_tp2():
    p = pos()
    acts = manage(p, C(1.0, 1.08, 0.99, 1.07), 100)
    # break-even, then trailing from this candle's high (only checked against LATER candles)
    assert acts == [("SELL", cfg.RHC_TP1_FRACTION, "TP1", 1.075)] and p.tp1_done
    assert p.stop == pytest.approx(max(1.0, 1.08 * 0.95))
    acts = manage(p, C(1.07, 1.12, 1.06, 1.11), 160)
    assert acts == [] and p.stop == pytest.approx(1.12 * 0.95)                          # trails the peak
    assert manage(p, C(1.11, 1.16, 1.10, 1.15), 220) == [("SELL", 1.0, "TP2", 1.15)]


def test_time_stop():
    assert manage(pos(), C(1.0, 1.01, 0.99, 1.0), 10_000) == [("SELL", 1.0, "TIME_STOP", 1.0)]


# ── fill helpers ──────────────────────────────────────────────────────────────
def test_failures_are_deterministic_and_near_rate():
    assert fails("k1", 0.5) == fails("k1", 0.5)
    rate = sum(fails(f"order{i}", 0.02) for i in range(20_000)) / 20_000
    assert 0.012 < rate < 0.028
    assert not fails("x", 0.0) and fails("x", 1.0)


def test_gas_model():
    assert gas_usd(None, None, None) == cfg.RHC_PAPER_GAS_FLOOR_USD
    v = gas_usd(150_000, int(0.02e9), 2233.0)
    assert v == pytest.approx(max(cfg.RHC_PAPER_GAS_FLOOR_USD, 150_000 * 1.6 * 0.02e9 / 1e18 * 2233))


def test_interpret_sell():
    r = interpret_sell([0, 0, 1000, 950, 500, 499, 0, 60_000], 1000)
    assert r.ok and r.proceeds == 499 and r.sell_tax == pytest.approx(0.05) and r.gas == 60_000
    assert interpret_sell([2, 0, 1000, 0, 0, 0, 0, 1], 1000).status == "SELL_TRANSFER_BLOCKED"


# ── PaperBroker (fakes) ───────────────────────────────────────────────────────
class FakeSim:
    def __init__(self, buy=None, sells=None):
        self.buy = buy
        self.sells = list(sells or [])

    def run(self, meta, amount, fee):
        return self.buy

    def run_sell(self, meta, tokens, fee):
        r = self.sells.pop(0)
        return r(tokens) if callable(r) else r


class PStore:
    def __init__(self):
        self.positions, self.fills, self.candle, self.last = {}, [], None, 1.0
        self._id = 0

    def load_open_paper_positions(self):
        return []

    def insert_paper_position(self, p, intent):
        self._id += 1
        self.positions[self._id] = p
        return self._id

    def update_paper_position(self, p):
        self.positions[p.id] = p

    def insert_paper_fill(self, *a):
        self.fills.append(a)

    def last_close_usd(self, pk):
        return self.last

    def last_candle_usd(self, pk, since=0):
        return self.candle

    def watch_state(self, pk):
        return "watch"

    def latest_reject_is_permanent(self, pk):
        return False


def broker(sim, monkeypatch, fail=0.0):
    monkeypatch.setattr(cfg, "RHC_PAPER_FAIL_PROB", fail)
    meta = PoolMeta("0xpool", "v4", ETH, MEME, dec0=18, dec1=18, base_index=1, quote_token=ETH, quote_class="eth",
                    supported=True, pk=1, fee=3000, tick_spacing=60)
    pr = QuotePricer()
    pr.set_eth_usd(2000.0, 0)
    reg = SimpleNamespace(by_pk={1: meta})
    rpc = SimpleNamespace(call=lambda m, p: hex(int(0.02e9)))
    st = PStore()
    b = PaperBroker(rpc, st, reg, pr, sim=sim, clock=lambda: 1_000, sleep=lambda s: None)
    return b, st


INTENT = {"pool_pk": 1, "token": MEME, "strategy": "volume_breakout", "as_of": 960, "size_usd": 40.0,
          "entry_ref": 0.001, "stop": 0.00095, "targets": [0.00106, 0.00115], "time_stop_min": 240,
          "evidence": {"regime": {"label": "normal"}}}


def test_entry_fill_uses_simulated_tokens_haircut_and_gas(monkeypatch):
    # $40 at ETH $2000 = 0.02 ETH; simulator says 39,000 tokens arrive (fees/impact/taxes inside)
    buy = SimResult("ok", 0, raw=[0, 39_100 * 10 ** 18, 39_000 * 10 ** 18, 0, 0, 0, 150_000, 50_000], buy_tax=0.0026)
    b, st = broker(FakeSim(buy=buy), monkeypatch)
    res = b.submit(INTENT)
    assert res["status"] == "filled" and res["executed"] is False
    p = st.positions[res["paper_position_id"]]
    assert p.tokens == pytest.approx(39_000 * (1 - cfg.RHC_PAPER_EXTRA_SLIP_BPS / 10_000), rel=1e-9)
    assert p.cost_usd == pytest.approx(40.0 + res["gas_usd"]) and p.entry_price > INTENT["entry_ref"]
    assert p.stop == pytest.approx(p.entry_price * 0.95) and p.risk_usd == pytest.approx(40 * 0.05)


def test_failed_entry_pays_gas_and_opens_nothing(monkeypatch):
    buy = SimResult("ok", 0, raw=[0, 1, 1, 0, 0, 0, 1, 1])
    b, st = broker(FakeSim(buy=buy), monkeypatch, fail=1.0)
    res = b.submit(INTENT)
    assert res["status"] == "failed" and not st.positions and st.fills[-1][4] == "ENTRY_FAILED"


def test_stop_exit_and_realized_pnl(monkeypatch):
    buy = SimResult("ok", 0, raw=[0, 40_000 * 10 ** 18, 40_000 * 10 ** 18, 0, 0, 0, 1, 1])
    sell = SellResult("ok", 0, proceeds=int(0.018 * 10 ** 18), gas=60_000)        # 0.018 ETH back = $36
    b, st = broker(FakeSim(buy=buy, sells=[sell]), monkeypatch)
    pid = b.submit(INTENT)["paper_position_id"]
    p = st.positions[pid]
    st.candle = C(p.entry_price, p.entry_price, p.stop * 0.99, p.stop)               # hits the stop
    b.process(2_000)
    assert p.status == "closed" and p.legs[-1].reason == "STOP"
    assert p.realized_usd == pytest.approx(36 * (1 - cfg.RHC_PAPER_EXTRA_SLIP_BPS / 1e4) - p.legs[-1].gas_usd - p.cost_usd)
    assert not b.positions


def test_unsellable_position_becomes_stuck_with_total_loss(monkeypatch):
    monkeypatch.setattr(cfg, "RHC_PAPER_STUCK_AFTER", 2)
    buy = SimResult("ok", 0, raw=[0, 1000, 1000, 0, 0, 0, 1, 1])
    bad = SellResult("SELL_FAILED", 0)
    b, st = broker(FakeSim(buy=buy, sells=[bad, bad]), monkeypatch)
    p = st.positions[b.submit(INTENT)["paper_position_id"]]
    st.candle = C(p.entry_price, p.entry_price, p.stop * 0.5, p.stop * 0.5)          # far through the stop
    b.process(2_000)
    assert p.status == "open" and p.sell_failures == 1
    b.process(2_060)
    assert p.status == "stuck" and p.tokens_raw == 0 and p.realized_usd <= -p.cost_usd


def test_approx_sell_fallback_when_token_slot_unknown(monkeypatch):
    buy = SimResult("ok", 0, raw=[0, 40_000 * 10 ** 18, 40_000 * 10 ** 18, 0, 0, 0, 1, 1])
    rt_for_exit = SimResult("ok", 0, raw=[0, 1, 2 * 10 ** 18, 0, 0, 10 ** 15, 1, 1], round_trip_cost=0.02)
    sim = FakeSim(buy=buy, sells=[SellResult("SIM_TOKEN_SLOT_UNKNOWN", 0)])
    b, st = broker(sim, monkeypatch)
    p = st.positions[b.submit(INTENT)["paper_position_id"]]
    sim.buy = rt_for_exit
    st.candle = C(p.entry_price, p.entry_price, p.stop * 0.99, p.stop)
    b.process(2_000)
    assert p.status == "closed" and "approx" in st.fills[-1][9] and st.fills[-1][9]["approx"] is True


# ── metrics ───────────────────────────────────────────────────────────────────
def T(pnl, i, token="t", risk=5.0, strat="s"):
    return {"pnl_usd": pnl, "cost_usd": 50, "risk_usd": risk, "strategy": strat, "regime": "normal", "token": token,
            "entry_ts": i * 3600, "exit_ts": i * 3600 + 600, "exit_reason": "TP1" if pnl > 0 else "STOP"}


def test_wilson_and_drawdown_and_bootstrap_determinism():
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)
    assert max_drawdown([10, -30, 5], 100) == pytest.approx(30 / 110)
    v = [1.0, -2.0, 3.0, 0.5, -1.0]
    assert bootstrap_ci(v, lambda x: sum(x) / len(x)) == bootstrap_ci(v, lambda x: sum(x) / len(x))


def test_never_profitable_below_sample_gate():
    trades = [T(5.0, i, token=f"t{i}") for i in range(50)]                          # 50 straight winners
    m = compute(trades, 1000, cfg)
    assert m["win_rate"] == 1.0 and m["gate"]["sufficient"] is False
    assert m["verdict"] == "insufficient sample - no conclusion"


def test_verdict_above_gate(monkeypatch):
    monkeypatch.setattr(cfg, "RHC_MIN_TRADES_FOR_STATS", 40)
    monkeypatch.setattr(cfg, "RHC_MIN_TOKENS_FOR_STATS", 5)
    monkeypatch.setattr(cfg, "RHC_MIN_DAYS_FOR_STATS", 1)
    good = [T(5.0 if i % 3 else -2.0, i * 2, token=f"t{i % 10}") for i in range(60)]
    m = compute(good, 1000, cfg)
    assert m["gate"]["sufficient"] and m["verdict"].startswith("positive expectancy")
    coin = [T(5.0 if i % 2 else -5.0, i * 2, token=f"t{i % 10}") for i in range(60)]
    assert compute(coin, 1000, cfg)["verdict"] == "edge not demonstrated"


def test_sample_gate_reasons():
    g = sample_gate(10, 2, 1.0, cfg)
    assert not g["sufficient"] and len(g["missing"]) == 3


# ── backtest ──────────────────────────────────────────────────────────────────
def test_backtest_is_deterministic_and_costs_matter(monkeypatch):
    from test_rhc_phase3 import T0, quiet_then_breakout
    import rhc_backtest
    cs = quiet_then_breakout()
    args = ({7: "0xt"}, {7: cs}, [], [], T0 + 60 * 60, T0 + 120 * 60)
    a, da = rhc_backtest.run(*args, config=cfg)
    b, db = rhc_backtest.run(*copy.deepcopy(args), config=cfg)
    assert a == b and len(a) >= 1 and a[0]["strategy"] == "volume_breakout"
    cheap, _ = rhc_backtest.run(*args, config=cfg, cost_by_pool={7: {"round_trip_cost": 0.0}})
    dear, _ = rhc_backtest.run(*args, config=cfg, cost_by_pool={7: {"round_trip_cost": 0.10}})
    assert dear[0]["pnl_usd"] < cheap[0]["pnl_usd"]
    s = rhc_backtest.summarize(a, da, T0 + 3600, T0 + 7200, cfg)
    assert len(s["walk_forward"]["folds"]) == cfg.RHC_BT_FOLDS and s["overall"]["verdict"].startswith("insufficient")


# ── store retry policy ────────────────────────────────────────────────────────
def test_db_retry_only_for_transient_errors_and_never_for_plain_inserts(monkeypatch):
    import rhc_store
    from sqlalchemy.exc import OperationalError, ProgrammingError
    monkeypatch.setattr(rhc_store.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise OperationalError("select 1", {}, Exception("server closed the connection unexpectedly"))
        return "ok"
    assert rhc_store._retrying(flaky)() == "ok" and calls["n"] == 3

    def bad_sql():
        raise ProgrammingError("x", {}, Exception("syntax error"))
    with pytest.raises(ProgrammingError):
        rhc_store._retrying(bad_sql)()
    for name in ("insert_decisions", "insert_paper_position", "insert_paper_fill", "save_screen", "record_gap",
                 "insert_snapshots", "insert_backtest_run"):
        assert not hasattr(getattr(rhc_store.Store, name), "__wrapped__"), f"{name} must not be retried"
        assert name not in rhc_store._RETRY_SAFE


# ── go-live gate & live broker ────────────────────────────────────────────────
def test_gate_never_ready_in_this_build():
    g = gate(None, None, cfg)
    assert g["ready"] is False and all(not c["pass"] for c in g["checks"])
    empty = compute([], 1000, cfg)                     # 0 trades -> 0% drawdown must NOT count as a pass
    assert empty["max_drawdown_pct"] == 0.0
    assert all(not c["pass"] for c in gate(empty, None, cfg)["checks"])
    great = {"gate": {"sufficient": True}, "expectancy_usd_ci95": (1, 2), "profit_factor_ci95": (1.5, 2),
             "max_drawdown_pct": 5, "expectancy_usd": 1.5}
    g2 = gate(great, {"expectancy_usd_ci95": (1, 2)}, cfg,
              {"dedicated_wallet": True, "kill_switch_tested": True, "pilot_approved": True})
    assert g2["ready"] is False and [c["check"] for c in g2["checks"] if not c["pass"]] == \
        ["LiveBroker enabled in code (separate approved change)"]


def test_live_broker_refuses_and_cannot_execute():
    sys.modules.pop("robinhood_live", None)
    lb = LiveBroker()
    r = lb.submit(INTENT)
    assert r["status"] == "refused" and r["executed"] is False and lb.executes is False
    with pytest.raises(LiveTradingDisabled):
        lb._execute_via_existing_desk(MEME, 10.0)
    assert "robinhood_live" not in sys.modules, "the existing desk must not even be imported"
    assert cfg.RHC_LIVE_ENABLED is False
