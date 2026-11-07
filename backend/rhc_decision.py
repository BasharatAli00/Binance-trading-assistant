"""Decision engine: features -> setups -> confirmation -> regime & risk -> sizing -> broker.

DecisionCore is deterministic and I/O-free: given the same candles, regime inputs, wallet data
and risk state it produces the same decisions, so live runs and replays agree (tested).

Every step is recorded as a decision row:
  SETUP_DETECTED  a strategy's conditions all fired on a closed candle
  NOT_CONFIRMED   the next candle failed confirmation (dip / chase / flow)
  EXPIRED         no confirming candle within RHC_CONFIRM_TIMEOUT_MIN
  REJECTED_RISK   confirmed, but risk/regime rules blocked the entry (reasons listed)
  ENTER_INTENT    confirmed and sized; handed to the broker

Phase 3 uses IntentOnlyBroker: it records the intent and executes nothing. Phase 4 swaps in the
PaperBroker with the realistic fill model; the LiveBroker stays disabled.
"""
import json
import logging
import time

import rhc_config as cfg
from rhc_features import features
from rhc_regime import regime as compute_regime
from rhc_risk import RiskState, size_and_check
from rhc_strategies import build as build_strategies
from rhc_strategies import confirm
from rhc_wallets import scores as wallet_scores
from rhc_wallets import smart_flow

log = logging.getLogger("rhc.decision")

FEATURE_KEYS = ("price_usd", "ret_5m", "ret_15m", "ret_60m", "vol_ratio_5m", "imbalance_5m", "imbalance_15m",
                "traders_15m", "atr14", "dist_vwap_60m", "liq_change_60m", "coverage_60m", "smart_buy_usd_15m",
                "smart_buyers_15m")


class Broker:
    name = "base"
    executes = False

    def submit(self, intent):
        raise NotImplementedError

    def open_positions(self):
        return []


class IntentOnlyBroker(Broker):
    """Phase 3: records intents, executes nothing."""
    name = "intent_only"

    def submit(self, intent):
        return {"status": "recorded", "executed": False}


def _r(x):
    return round(x, 6) if isinstance(x, float) else x


class DecisionCore:
    def __init__(self, config=cfg, strategies=None):
        self.cfg = config
        self.strategies = strategies if strategies is not None else build_strategies(config)
        self.pending = {}        # (pool_pk, strategy) -> Setup
        self.cooldown = {}       # (pool_pk, strategy) -> ts until which new setups are ignored
        self.last_bucket = {}    # pool_pk -> last evaluated candle bucket

    def _decision(self, s, action, token, reasons=(), size=None, f=None, extra=None):
        ev = {"features": {k: _r(f.get(k)) for k in FEATURE_KEYS} if f else None,
              "conditions": s.evidence.get("conditions")}
        if extra:
            ev.update(extra)
        return {"as_of": s.as_of if action == "SETUP_DETECTED" else (f or {}).get("as_of", s.as_of),
                "pool_pk": s.pool_pk, "token": token, "strategy": s.strategy, "action": action,
                "reasons": list(reasons), "size_usd": size, "entry_ref": s.entry_ref, "stop": s.stop,
                "targets": [round(t, 12) for t in s.targets], "time_stop_min": s.time_stop_min, "evidence": ev}

    def step(self, pool_pk, token, f, reg, risk_state, screen_impact):
        """Evaluate one pool at one point in time. Returns a list of decision dicts."""
        out = []
        now = f.get("as_of")
        # 0) expire stale setups by TIME, even when the pool stopped trading (no new candle) -
        #    otherwise a setup could "confirm" much later at a completely different price.
        if now is not None:
            for key in [k for k in self.pending if k[0] == pool_pk]:
                s = self.pending[key]
                if now - s.as_of > self.cfg.RHC_CONFIRM_TIMEOUT_MIN * 60:
                    out.append(self._decision(s, "EXPIRED", token, ["CONFIRM_TIMEOUT"], f=f))
                    del self.pending[key]
        lb = f.get("last_bucket")
        if lb is None or self.last_bucket.get(pool_pk) == lb:
            return out                                          # no new closed candle: nothing more to do
        self.last_bucket[pool_pk] = lb

        # 1) resolve pending setups for this pool on the new candle
        for key in [k for k in self.pending if k[0] == pool_pk]:
            s = self.pending[key]
            ok, why = confirm(s, f, self.cfg)
            if ok is None:
                continue
            del self.pending[key]
            if not ok:
                out.append(self._decision(s, "NOT_CONFIRMED", token, [why], f=f))
                continue
            size, reasons, risk_ev = size_and_check(risk_state, token, s.stop_pct, now, reg.get("no_trade", []),
                                                    screen_impact, self.cfg)
            extra = {"regime": {k: reg.get(k) for k in ("label", "pct", "eth_ret_1h", "no_trade")},
                     "risk": {k: (_r(v) if not isinstance(v, dict) else {kk: _r(vv) for kk, vv in v.items()})
                              for k, v in risk_ev.items()}}
            self.cooldown[key] = now + self.cfg.RHC_SIGNAL_COOLDOWN_MIN * 60
            if reasons:
                out.append(self._decision(s, "REJECTED_RISK", token, reasons, f=f, extra=extra))
            else:
                # Entry reference moves to the confirming candle's close; stop/targets keep their distance.
                scale = f["price_usd"] / s.entry_ref
                s.entry_ref, s.stop = f["price_usd"], s.stop * scale
                s.targets = [t * scale for t in s.targets]
                out.append(self._decision(s, "ENTER_INTENT", token, [], size=size, f=f, extra=extra))

        # 2) detect new setups
        for strat in self.strategies:
            key = (pool_pk, strat.name)
            if key in self.pending or self.cooldown.get(key, 0) > now:
                continue
            s = strat.evaluate(f, pool_pk)
            if s is None:
                continue
            s.evidence["_last_bucket"] = lb
            self.pending[key] = s
            out.append(self._decision(s, "SETUP_DETECTED", token, [], f=f))
        return out


def enrich_smart(f, wallet_trades, closed_positions, pool_pk, config=cfg):
    """Adds smart-money flow features computed strictly as of f['as_of']."""
    if not f.get("as_of"):
        return f
    sc = wallet_scores(closed_positions, f["as_of"], config)
    usd, n = smart_flow(wallet_trades, sc, pool_pk, f["as_of"])
    f["smart_buy_usd_15m"], f["smart_buyers_15m"] = usd, n
    return f


def replay(pools, candles_by_pool, market_vol_5m, eth_5m, wallet_trades, closed_positions, start_ts, end_ts,
           config=cfg, screen_impact=None, equity=None):
    """Deterministic replay over [start_ts, end_ts] at 1-minute steps. pools: {pool_pk: token}."""
    core = DecisionCore(config)
    state = RiskState(equity_usd=equity or config.RHC_PAPER_EQUITY_USD)
    out = []
    t = (start_ts // 60) * 60
    while t <= end_ts:
        reg = compute_regime(market_vol_5m, eth_5m, t, config)
        for pk in sorted(pools):
            f = features(candles_by_pool.get(pk, []), t)
            enrich_smart(f, wallet_trades, closed_positions, pk, config)
            out.extend(core.step(pk, pools[pk], f, reg, state, (screen_impact or {}).get(pk)))
        t += 60
    return out


class DecisionEngine:
    """Live wrapper: reads stored candles for watch-listed pools and records decisions."""

    def __init__(self, store, indexer, broker=None, clock=time.time):
        self.store = store
        self.indexer = indexer
        self.broker = broker or IntentOnlyBroker()
        self.clock = clock
        self.core = DecisionCore(cfg)
        self.closed_positions = []
        self._last_rebuild = 0.0
        self.last_regime = {}
        self.metrics = {"cycles": 0, "decisions": 0, "intents": 0, "last_error": None, "last_cycle_ts": None}

    def _risk_state(self, now):
        kill = bool((self.store.kv_get("kill_switch") or {}).get("enabled"))
        realized_today = self.broker.realized_today(now) if hasattr(self.broker, "realized_today") else 0.0
        last_exit = self.broker.last_exit_ts() if hasattr(self.broker, "last_exit_ts") else {}
        realized_total = self.store.paper_realized_since(0) if hasattr(self.broker, "realized_today") else 0.0
        return RiskState(equity_usd=cfg.RHC_PAPER_EQUITY_USD + realized_total,
                         open_positions=self.broker.open_positions(), realized_today_usd=realized_today,
                         last_exit_ts=last_exit, kill_switch=kill)

    def _rebuild_wallets(self, now):
        if now - self._last_rebuild < cfg.RHC_WALLET_REBUILD_S and self._last_rebuild:
            return
        from rhc_wallets import positions
        self._last_rebuild = now
        trades = self.store.wallet_trades_since(int(now) - cfg.RHC_RETAIN_WALLET_TRADE_DAYS * 86400)
        closed = positions(trades)
        self.store.upsert_wallet_positions(closed)
        self.closed_positions = self.store.wallet_positions_since(int(now) - cfg.RHC_RETAIN_WALLET_POS_DAYS * 86400)

    def cycle(self):
        now = int(self.clock())
        self.metrics["cycles"] += 1
        self.metrics["last_cycle_ts"] = now
        chain_now = self.indexer.metrics.get("processed_ts") or now
        as_of = ((chain_now - cfg.RHC_CANDLE_GRACE_S) // 60) * 60
        self._rebuild_wallets(now)
        ref = self.indexer.registry.get(self.indexer.ref_pool)
        mv = self.store.market_volume_5m(as_of - (cfg.RHC_REGIME_LOOKBACK_5M + 12) * 300)
        eth = self.store.pool_closes(ref.pk, 300, as_of - 3 * 3600) if ref and ref.pk else []
        reg = compute_regime(mv, eth, as_of, cfg)
        lag = self.indexer.metrics.get("lag_s")
        if lag is not None and lag > cfg.RHC_NO_TRADE_MAX_LAG_S:
            reg["no_trade"] = reg["no_trade"] + ["DATA_LAG"]
        self.last_regime = reg
        if hasattr(self.broker, "process"):
            self.broker.process(now)                     # manage exits before new entries
        state = self._risk_state(now)
        rows = []
        for pk, token in self.store.watch_tokens().items():
            candles = self.store.candles(pk, 60, limit=cfg.RHC_FEATURE_LOOKBACK_MIN)
            f = features(candles, as_of)
            wt = self.store.wallet_trades_pool(pk, as_of - 900)
            enrich_smart(f, wt, self.closed_positions, pk)
            for d in self.core.step(pk, token, f, reg, state, self.store.latest_screen_impact(pk)):
                if d["action"] == "ENTER_INTENT":
                    d["broker_result"] = self.broker.submit(d)
                    self.metrics["intents"] += 1
                rows.append(d)
        if rows:
            self.store.insert_decisions(rows, now, self.broker.name)
            self.metrics["decisions"] += len(rows)
        return {"decisions": len(rows), "regime": reg.get("label")}


def to_json(evidence):
    return json.dumps(evidence, default=str)[:6000]
