"""Phase 3: features (no look-ahead), regime, strategies, risk, wallets, decision core, replay."""
import copy

import pytest

import rhc_config as cfg
from rhc_decision import DecisionCore, replay
from rhc_features import closed_until, features
from rhc_regime import regime
from rhc_risk import OpenPosition, RiskState, size_and_check
from rhc_strategies import Setup, VolumeBreakout, confirm
from rhc_wallets import ClosedPosition, evaluate, positions, scores, smart_flow

T0 = 1_790_000_100 - (1_790_000_100 % 3600)


def candle(i, close, vol=100.0, buy_share=0.5, traders=3, hi=None, lo=None, liq=1e6):
    b = T0 + i * 60
    return {"bucket": b, "o": close, "h": hi or close * 1.002, "l": lo or close * 0.998, "c": close, "c_usd": close,
            "vol_usd": vol, "buys": 2, "sells": 2, "buy_usd": vol * buy_share, "sell_usd": vol * (1 - buy_share),
            "traders": traders, "large": 0, "liq": liq, "liq_usd": None}


def quiet_then_breakout(n_quiet=80, breakout_at=None):
    cs = [candle(i, 1.0 + 0.0005 * (i % 5), vol=100) for i in range(n_quiet)]
    i = n_quiet
    # breakout candle: ~1.6% above the prior 30m high (inside the 3% anti-chase limit)
    cs.append(candle(i, 1.02, vol=2000, buy_share=0.85, traders=12, hi=1.021, lo=1.0))
    cs.append(candle(i + 1, 1.025, vol=900, buy_share=0.7, traders=9))                      # confirming candle
    for k in range(2, 30):
        cs.append(candle(i + k, 1.03, vol=150))
    return cs


# ── features ──────────────────────────────────────────────────────────────────
def test_features_ignore_future_candles():
    cs = quiet_then_breakout()
    as_of = T0 + 70 * 60
    base = features([c for c in cs if c["bucket"] + 60 <= as_of], as_of)
    with_future = features(cs, as_of)                     # same call with future rows present
    assert base == with_future
    assert with_future["last_bucket"] == T0 + 69 * 60
    assert closed_until(cs, as_of)[-1]["bucket"] + 60 <= as_of


def test_open_candle_is_excluded():
    cs = [candle(0, 1.0), candle(1, 2.0)]
    f = features(cs, T0 + 60 + 59)                        # second candle not closed yet
    assert f["last_bucket"] == T0 and f["price_usd"] == 1.0


def test_feature_values_on_breakout():
    cs = quiet_then_breakout()
    f = features(cs, T0 + 81 * 60)
    assert f["breakout_30m"] is True
    assert f["imbalance_5m"] > 0.6 and f["vol_ratio_5m"] > 3
    assert f["ret_1m"] == pytest.approx(1.02 / cs[79]["c"] - 1)
    assert 0 < f["atr14"] < 0.1 and f["coverage_60m"] == 1.0


# ── regime ────────────────────────────────────────────────────────────────────
def test_regime_labels_and_no_trade():
    mv = [(T0 + i * 300, 100.0) for i in range(60)] + [(T0 + i * 300, 1.0) for i in range(60, 72)]
    eth = [(T0 + i * 300, 3000.0) for i in range(60)] + [(T0 + i * 300, 2850.0) for i in range(60, 72)]
    as_of = T0 + 72 * 300
    r = regime(mv, eth, as_of, cfg)
    assert r["label"] == "cold" and "REGIME_COLD" in r["no_trade"] and "ETH_DUMP" in r["no_trade"]
    hot = regime([(b, (1000.0 if i >= 60 else 100.0)) for i, (b, _) in enumerate(mv)], eth[:60], as_of, cfg)
    assert hot["label"] == "hot"


def test_regime_unknown_with_little_history_and_ignores_future():
    mv = [(T0 + i * 300, 100.0) for i in range(10)]
    assert regime(mv, [], T0 + 10 * 300, cfg)["label"] == "unknown"
    mv2 = [(T0 + i * 300, 100.0) for i in range(40)]
    a = regime(mv2, [], T0 + 30 * 300, cfg)
    b = regime(mv2 + [(T0 + i * 300, 9e9) for i in range(40, 50)], [], T0 + 30 * 300, cfg)
    assert a == b


# ── strategies ────────────────────────────────────────────────────────────────
def test_breakout_fires_with_explained_conditions_and_clamped_stop():
    f = features(quiet_then_breakout(), T0 + 81 * 60)
    s = VolumeBreakout(cfg).evaluate(f, 7)
    assert s is not None and s.strategy == "volume_breakout"
    assert all(c["ok"] for c in s.evidence["conditions"].values())
    assert cfg.RHC_STOP_MIN_PCT <= s.stop_pct <= cfg.RHC_STOP_MAX_PCT
    assert s.stop < s.entry_ref < s.targets[0] < s.targets[1]


def test_breakout_does_not_fire_in_quiet_market():
    f = features(quiet_then_breakout(), T0 + 70 * 60)
    assert VolumeBreakout(cfg).evaluate(f, 7) is None


def test_confirm_rules():
    s = Setup("x", 1, T0, 1.0, 0.95, [1.1], 240, 0.05, {"_last_bucket": T0})
    same = {"price_usd": 1.0, "last_bucket": T0, "imbalance_5m": 0.9}
    assert confirm(s, same, cfg) == (None, None)
    assert confirm(s, dict(same, last_bucket=T0 + 60, price_usd=0.98), cfg) == (False, "CONFIRM_FAILED_DIP")
    assert confirm(s, dict(same, last_bucket=T0 + 60, price_usd=1.05), cfg) == (False, "CONFIRM_FAILED_CHASE")
    assert confirm(s, dict(same, last_bucket=T0 + 60, imbalance_5m=0.3), cfg) == (False, "CONFIRM_FAILED_FLOW")
    assert confirm(s, dict(same, last_bucket=T0 + 60, price_usd=1.005), cfg) == (True, None)


# ── risk ──────────────────────────────────────────────────────────────────────
def test_sizing_fixed_fractional_and_caps():
    st = RiskState(equity_usd=1000)
    size, reasons, ev = size_and_check(st, "0xt", 0.25, T0, [], None, cfg)       # raw = 1000*1%/25% = 40
    assert reasons == [] and size == pytest.approx(40)
    size, _, ev = size_and_check(st, "0xt", 0.05, T0, [], None, cfg)             # raw 200 -> max position 50
    assert size == cfg.RHC_MAX_POSITION_USD
    size, _, ev = size_and_check(st, "0xt", 0.05, T0, [], 0.04, cfg)             # liquidity cap 25*0.02/0.04 = 12.5
    assert size == pytest.approx(12.5) and ev["caps"]["liquidity"] == pytest.approx(12.5)


@pytest.mark.parametrize("state_kw,no_trade,code", [
    ({"kill_switch": True}, [], "KILL_SWITCH"),
    ({}, ["REGIME_COLD"], "NO_TRADE_REGIME_COLD"),
    ({"open_positions": [OpenPosition(i, f"0x{i}", 10) for i in range(5)]}, [], "MAX_OPEN_POSITIONS"),
    ({"realized_today_usd": -31.0}, [], "DAILY_LOSS_LIMIT"),
    ({"last_exit_ts": {"0xt": T0 - 60}}, [], "TOKEN_COOLDOWN"),
])
def test_risk_blocks(state_kw, no_trade, code):
    st = RiskState(equity_usd=1000, **state_kw)
    size, reasons, _ = size_and_check(st, "0xt", 0.05, T0, no_trade, None, cfg)
    assert size == 0 and code in reasons


def test_exposure_and_per_token_headroom_and_min_size():
    st = RiskState(equity_usd=1000, open_positions=[OpenPosition(1, "0xa", 240)])
    size, reasons, _ = size_and_check(st, "0xb", 0.05, T0, [], None, cfg)      # only $10 exposure headroom left
    assert reasons == [] and size == pytest.approx(10)
    st2 = RiskState(equity_usd=1000, open_positions=[OpenPosition(1, "0xa", 245)])
    size, reasons, _ = size_and_check(st2, "0xb", 0.05, T0, [], None, cfg)
    assert size == 0 and "SIZE_BELOW_MIN" in reasons
    st3 = RiskState(equity_usd=1000, open_positions=[OpenPosition(1, "0xt", 45)])
    size, reasons, _ = size_and_check(st3, "0xt", 0.05, T0, [], None, cfg)      # per-token headroom $5
    assert "SIZE_BELOW_MIN" in reasons


# ── wallets ───────────────────────────────────────────────────────────────────
def wt(w, ts, side, amt, usd, pk=1):
    return {"wallet": w, "pool_pk": pk, "ts": ts, "side": side, "base_amt": amt, "usd": usd}


def test_positions_average_cost_and_unseen_entries():
    trades = [wt("a", 1, "buy", 100, 10), wt("a", 2, "buy", 100, 30), wt("a", 3, "sell", 196, 60),
              wt("b", 1, "sell", 50, 5),                                   # entry never observed -> ignored
              wt("c", 1, "buy", 100, 10), wt("c", 2, "sell", 50, 4)]       # still open -> not closed
    closed = positions(trades)
    assert len(closed) == 1 and closed[0].wallet == "a" and closed[0].ret == pytest.approx(0.5)


def test_scores_have_no_leakage_and_shrinkage():
    closed = [ClosedPosition("w", 1, 0, 100 + i, 10, 15) for i in range(6)] + [ClosedPosition("w", 1, 0, 10_000, 10, 1)]
    early = scores(closed, 200, cfg)["w"]
    assert early["n"] == 6 and early["wins"] == 6 and early["smart"]
    assert early["score"] == pytest.approx(7 / 8)
    late = scores(closed, 20_000, cfg)["w"]
    assert late["n"] == 7                                            # the loss counts only after it closed
    assert "w" not in scores(closed, 50, cfg)


def test_smart_flow_window_and_as_of():
    sc = {"s": {"smart": True}, "n": {"smart": False}}
    trades = [wt("s", 100, "buy", 1, 50), wt("s", 1000, "buy", 1, 70), wt("n", 950, "buy", 1, 999),
              wt("s", 1100, "buy", 1, 5)]                            # at as_of -> excluded (strictly before)
    assert smart_flow(trades, sc, 1, 1100, window_s=900) == (70, 1)


def test_evaluate_requires_sample():
    assert evaluate([(i, 1.0, 0.1) for i in range(10)], cfg)["conclusion"] == "insufficient sample"
    samples = [(i, 1.0 if i % 2 else 0.0, 0.05 if i % 2 else -0.01) for i in range(400)]
    r = evaluate(samples, cfg)
    assert r["lift"] == pytest.approx(0.06) and r["conclusion"].startswith("positive lift")


# ── decision core & replay ────────────────────────────────────────────────────
NEUTRAL = {"label": "normal", "pct": 0.5, "eth_ret_1h": 0.0, "no_trade": []}


def run_core(cs, state=None, reg=NEUTRAL, minutes=range(70, 95)):
    core = DecisionCore(cfg)
    state = state or RiskState(equity_usd=1000)
    out = []
    for m in minutes:
        f = features(cs, T0 + m * 60)
        out += core.step(7, "0xt", f, reg, state, None)
    return out


def test_detect_then_confirm_then_intent():
    out = run_core(quiet_then_breakout())
    acts = [(d["strategy"], d["action"]) for d in out]
    det = next(d for d in out if d["action"] == "SETUP_DETECTED")
    assert det["as_of"] == T0 + 81 * 60                                  # detected on the breakout candle itself
    assert ("volume_breakout", "SETUP_DETECTED") in acts and ("volume_breakout", "ENTER_INTENT") in acts
    intent = next(d for d in out if d["action"] == "ENTER_INTENT")
    assert intent["size_usd"] > 0 and intent["stop"] < intent["entry_ref"]
    assert intent["evidence"]["risk"]["raw_size"] > 0 and intent["evidence"]["regime"]["label"] == "normal"
    # cooldown: the same setup does not fire again for the next hour
    assert sum(1 for s, a in acts if s == "volume_breakout" and a == "SETUP_DETECTED") == 1


def test_confirm_failure_and_risk_rejection():
    cs = quiet_then_breakout()
    cs[81] = candle(81, 1.0, vol=900, buy_share=0.7)                    # next candle dumps -> not confirmed
    acts = [(d["strategy"], d["action"], d["reasons"]) for d in run_core(cs)]
    assert ("volume_breakout", "NOT_CONFIRMED", ["CONFIRM_FAILED_DIP"]) in acts
    killed = run_core(quiet_then_breakout(), state=RiskState(equity_usd=1000, kill_switch=True))
    rej = [d for d in killed if d["action"] == "REJECTED_RISK"]
    assert rej and "KILL_SWITCH" in rej[0]["reasons"] and not any(d["action"] == "ENTER_INTENT" for d in killed)


def test_expiry_when_no_new_candle():
    cs = quiet_then_breakout()[:81]                                       # nothing after the breakout candle
    core = DecisionCore(cfg)
    st = RiskState(equity_usd=1000)
    out = core.step(7, "0xt", features(cs, T0 + 81 * 60), NEUTRAL, st, None)
    assert any(d["action"] == "SETUP_DETECTED" for d in out)
    # The pool stops trading: no new candle ever arrives, yet the setup must expire by time.
    assert core.step(7, "0xt", features(cs, T0 + 83 * 60), NEUTRAL, st, None) == []     # within timeout
    out2 = core.step(7, "0xt", features(cs, T0 + 90 * 60), NEUTRAL, st, None)
    assert [d["action"] for d in out2] == ["EXPIRED"] and out2[0]["reasons"] == ["CONFIRM_TIMEOUT"]
    assert not core.pending


def test_replay_is_deterministic():
    cs = quiet_then_breakout()
    args = ({7: "0xt"}, {7: cs}, [], [], [], [], T0 + 60 * 60, T0 + 100 * 60)
    a = replay(*args)
    b = replay(*copy.deepcopy(args))
    assert a == b and any(d["action"] == "ENTER_INTENT" for d in a)
