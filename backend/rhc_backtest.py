"""Event-driven backtest + walk-forward over RECORDED candles.

The same DecisionCore (signals, confirmation, regime, risk) and the same `manage` exit rules as
forward paper trading are used; only the fill source differs. Historical pool state cannot be
re-simulated (the public node keeps ~100 s of state), so fills are modelled from candles:
  entry = confirming close x (1 + entry cost); exit = stop/target level (or the open on a gap)
  x (1 - exit cost); costs = half the screened round-trip cost (else RHC_BT_DEFAULT_COST_PCT)
  + a latency penalty of RHC_BT_LATENCY_ATR x ATR + the paper safety haircut; gas per leg.
Risk state evolves with the simulated book (open positions, exposure, daily loss, cooldowns).
Walk-forward: parameters are fixed (no fitting), so trades are split into consecutive time folds
to show stability; the last RHC_BT_OOS_FRACTION of time is reported separately as hold-out.
"""
import hashlib
import json

import rhc_config as cfg
from rhc_decision import DecisionCore, enrich_smart
from rhc_features import features
from rhc_metrics import breakdown, compute
from rhc_paper import Position, manage
from rhc_regime import regime as compute_regime
from rhc_risk import OpenPosition, RiskState


def config_hash(config=cfg):
    keys = sorted(k for k in dir(config) if k.startswith("RHC_") and not k.endswith("URL") and "KEY" not in k)
    blob = json.dumps({k: getattr(config, k) for k in keys}, default=str, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _usd_candle(c):
    if not c.get("c") or not c.get("c_usd"):
        return None
    k = c["c_usd"] / c["c"]
    return {"o_usd": c["o"] * k, "h_usd": c["h"] * k, "l_usd": c["l"] * k, "c_usd": c["c_usd"]}


def run(pools, candles_by_pool, market_vol_5m, eth_5m, start_ts, end_ts, config=cfg, cost_by_pool=None,
        wallet_trades=(), closed_positions=(), equity0=None):
    """Returns (trades, decisions). pools: {pool_pk: token}."""
    equity0 = equity0 or config.RHC_PAPER_EQUITY_USD
    core = DecisionCore(config)
    index = {pk: {c["bucket"]: c for c in cs} for pk, cs in candles_by_pool.items()}
    book, trades, decisions = [], [], []
    realized_by_day, last_exit = {}, {}
    gas = config.RHC_BT_GAS_USD
    haircut = config.RHC_PAPER_EXTRA_SLIP_BPS / 10_000
    t = (start_ts // 60) * 60
    while t <= end_ts:
        # 1) manage open positions on the candle that just closed
        for pos in list(book):
            c = index.get(pos.pool_pk, {}).get(t - 60)
            uc = _usd_candle(c) if c else None
            for _, frac, reason, ref in manage(pos, uc, t, config):
                if pos.status != "open":
                    break
                f = pos.extra_cost
                sold = pos.tokens if frac >= 0.999 else pos.tokens * frac
                received = sold * ref * (1 - f - haircut) - gas
                pos.proceeds_usd += received
                pos.tokens -= sold
                pos.legs.append((t, reason))
                if pos.tokens <= 1e-12:
                    pos.status = "closed"
            if pos.status != "open":
                book.remove(pos)
                pnl = pos.proceeds_usd - pos.cost_usd
                day = t - t % 86400
                realized_by_day[day] = realized_by_day.get(day, 0.0) + pnl
                last_exit[pos.token] = t
                trades.append({"pnl_usd": pnl, "cost_usd": pos.cost_usd, "risk_usd": pos.risk_usd,
                               "strategy": pos.strategy, "regime": pos.regime, "token": pos.token,
                               "pool_pk": pos.pool_pk, "entry_ts": pos.opened_ts, "exit_ts": t,
                               "exit_reason": pos.legs[-1][1]})
        # 2) decisions with the current simulated risk state
        reg = compute_regime(market_vol_5m, eth_5m, t, config)
        day = t - t % 86400
        opens = []
        for p in book:
            c = index.get(p.pool_pk, {}).get(t - 60)
            px = c["c_usd"] if c and c.get("c_usd") else p.entry_price
            opens.append(OpenPosition(p.pool_pk, p.token, p.cost_usd - p.proceeds_usd, p.tokens * px - p.cost_usd))
        state = RiskState(equity_usd=equity0 + sum(x["pnl_usd"] for x in trades), open_positions=opens,
                          realized_today_usd=realized_by_day.get(day, 0.0), last_exit_ts=dict(last_exit))
        for pk in sorted(pools):
            f = features(candles_by_pool.get(pk, []), t)
            enrich_smart(f, list(wallet_trades), list(closed_positions), pk, config)
            cost = (cost_by_pool or {}).get(pk, {})
            for d in core.step(pk, pools[pk], f, reg, state, cost.get("impact")):
                decisions.append(d)
                if d["action"] != "ENTER_INTENT":
                    continue
                rt = cost.get("round_trip_cost")
                side_cost = (rt / 2.0 if rt is not None else config.RHC_BT_DEFAULT_COST_PCT)
                side_cost += config.RHC_BT_LATENCY_ATR * (f.get("atr14") or 0.0)
                entry = d["entry_ref"] * (1 + side_cost + haircut)
                size = d["size_usd"]
                stop_pct = 1.0 - d["stop"] / d["entry_ref"]
                scale = entry / d["entry_ref"]
                pos = Position(pool_pk=pk, token=pools[pk], strategy=d["strategy"], opened_ts=t, entry_price=entry,
                               tokens=size / entry, tokens_raw=0, cost_usd=size + gas, stop=entry * (1 - stop_pct),
                               stop_pct=stop_pct, targets=[x * scale for x in d["targets"]],
                               time_stop_ts=t + d["time_stop_min"] * 60, regime=reg.get("label"),
                               risk_usd=size * stop_pct, peak=entry)
                pos.extra_cost = side_cost
                book.append(pos)
                state.open_positions.append(OpenPosition(pk, pools[pk], size, 0.0))
        t += 60
    # Positions still open when the data ends are closed at the last close (with exit costs),
    # so an unfinished loser can never disappear from the results.
    for pos in book:
        cs = [c for b_, c in sorted(index.get(pos.pool_pk, {}).items()) if b_ + 60 <= end_ts and c.get("c_usd")]
        last = cs[-1]["c_usd"] if cs else pos.entry_price
        received = pos.tokens * last * (1 - pos.extra_cost - haircut) - gas
        pnl = pos.proceeds_usd + received - pos.cost_usd
        trades.append({"pnl_usd": pnl, "cost_usd": pos.cost_usd, "risk_usd": pos.risk_usd, "strategy": pos.strategy,
                       "regime": pos.regime, "token": pos.token, "pool_pk": pos.pool_pk, "entry_ts": pos.opened_ts,
                       "exit_ts": end_ts, "exit_reason": "END_OF_DATA"})
    return trades, decisions


def walk_forward(trades, start_ts, end_ts, config=cfg, equity0=None):
    equity0 = equity0 or config.RHC_PAPER_EQUITY_USD
    k = max(1, config.RHC_BT_FOLDS)
    span = max(1, end_ts - start_ts)
    folds = []
    for i in range(k):
        a, b = start_ts + span * i // k, start_ts + span * (i + 1) // k
        ft = [x for x in trades if a <= x["entry_ts"] < b]
        m = compute(ft, equity0, config, a, b)
        folds.append({"fold": i + 1, "start": a, "end": b, "trades": m["trades"], "net_pnl_usd": m["net_pnl_usd"],
                      "expectancy_usd": m["expectancy_usd"], "win_rate": m["win_rate"]})
    cut = end_ts - int(span * config.RHC_BT_OOS_FRACTION)
    oos = compute([x for x in trades if x["entry_ts"] >= cut], equity0, config, cut, end_ts)
    return {"folds": folds, "holdout_start": cut, "holdout": oos}


def summarize(trades, decisions, start_ts, end_ts, config=cfg, equity0=None):
    equity0 = equity0 or config.RHC_PAPER_EQUITY_USD
    return {"config_hash": config_hash(config), "window": [start_ts, end_ts],
            "overall": compute(trades, equity0, config, start_ts, end_ts),
            "by_strategy": breakdown(trades, "strategy", equity0, config),
            "by_regime": breakdown(trades, "regime", equity0, config),
            "walk_forward": walk_forward(trades, start_ts, end_ts, config, equity0),
            "decisions": {a: sum(1 for d in decisions if d["action"] == a)
                          for a in sorted({d["action"] for d in decisions})},
            "fill_model": "candle-based (historical state is not available); see VALIDATION.md"}
