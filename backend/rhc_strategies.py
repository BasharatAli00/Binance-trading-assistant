"""Pluggable strategies: features -> Setup (entry, stop, targets, evidence) or None.

All thresholds are config-driven and UNVALIDATED defaults. Nothing here claims an edge; the
Phase 4 validation framework decides whether any strategy is worth anything. Each Setup
records exactly which conditions fired, so every signal is explainable.
"""
from dataclasses import dataclass, field


@dataclass
class Setup:
    strategy: str
    pool_pk: int
    as_of: int
    entry_ref: float            # reference USD price at detection (last closed 1m close)
    stop: float
    targets: list
    time_stop_min: int
    stop_pct: float
    evidence: dict = field(default_factory=dict)

    def as_dict(self):
        return {"strategy": self.strategy, "pool_pk": self.pool_pk, "as_of": self.as_of, "entry_ref": self.entry_ref,
                "stop": self.stop, "targets": self.targets, "time_stop_min": self.time_stop_min,
                "stop_pct": self.stop_pct, "evidence": self.evidence}


def _ok(v, op, x):
    if v is None:
        return False
    return {">=": v >= x, "<=": v <= x, ">": v > x, "<": v < x}[op]


class Strategy:
    name = "base"
    enabled_flag = None

    def __init__(self, cfg):
        self.cfg = cfg

    def conditions(self, f):
        """Return list of (label, value, op, threshold)."""
        raise NotImplementedError

    def enabled(self):
        return bool(getattr(self.cfg, self.enabled_flag, True)) if self.enabled_flag else True

    def evaluate(self, f, pool_pk):
        if not self.enabled() or not f.get("price_usd"):
            return None
        common = [("coverage_60m", f.get("coverage_60m"), ">=", self.cfg.RHC_MIN_COVERAGE_60M),
                  ("minutes_since_last_trade", f.get("minutes_since_last_trade"), "<=", 3.0)]
        conds = common + self.conditions(f)
        checks = {label: {"value": v, "op": op, "threshold": x, "ok": _ok(v, op, x)} for label, v, op, x in conds}
        if not all(c["ok"] for c in checks.values()):
            return None
        stop_pct = self.stop_pct(f)
        entry = f["price_usd"]
        stop = entry * (1.0 - stop_pct)
        targets = [entry * (1.0 + r * stop_pct) for r in self.cfg.RHC_TARGET_R]
        return Setup(self.name, pool_pk, f["as_of"], entry, stop, targets, self.cfg.RHC_TIME_STOP_MIN, stop_pct,
                     {"conditions": checks})

    def stop_pct(self, f):
        """ATR-based stop, clamped to [min, max]."""
        atr = f.get("atr14") or 0.0
        return min(max(self.cfg.RHC_STOP_ATR_MULT * atr, self.cfg.RHC_STOP_MIN_PCT), self.cfg.RHC_STOP_MAX_PCT)


class VolumeBreakout(Strategy):
    """Close above the prior 30m high on a volume burst with buy-side dominance."""
    name = "volume_breakout"
    enabled_flag = "RHC_STRAT_BREAKOUT_ENABLED"

    def conditions(self, f):
        c = self.cfg
        return [("breakout_30m", 1.0 if f.get("breakout_30m") else 0.0, ">=", 1.0),
                ("vol_ratio_5m", f.get("vol_ratio_5m"), ">=", c.RHC_BRK_VOL_RATIO),
                ("imbalance_5m", f.get("imbalance_5m"), ">=", c.RHC_BRK_IMBALANCE),
                ("traders_5m", f.get("traders_5m"), ">=", c.RHC_BRK_MIN_TRADERS),
                ("dist_prior_high", f.get("dist_prior_high"), "<=", c.RHC_MAX_CHASE)]


class MomentumContinuation(Strategy):
    """Sustained gains with growing participation and stable liquidity, not over-extended."""
    name = "momentum"
    enabled_flag = "RHC_STRAT_MOMENTUM_ENABLED"

    def conditions(self, f):
        c = self.cfg
        prev = f.get("traders_prev15m") or 0
        growth = (f.get("traders_15m") or 0) / prev if prev else None
        return [("ret_15m", f.get("ret_15m"), ">=", c.RHC_MOM_RET_15M),
                ("ret_60m", f.get("ret_60m"), ">=", c.RHC_MOM_RET_60M),
                ("trader_growth_15m", growth, ">=", c.RHC_MOM_TRADER_GROWTH),
                ("imbalance_15m", f.get("imbalance_15m"), ">=", c.RHC_MOM_IMBALANCE),
                ("dist_vwap_60m", f.get("dist_vwap_60m"), "<=", c.RHC_MOM_MAX_VWAP_DIST),
                ("liq_change_15m", f.get("liq_change_15m") if f.get("liq_change_15m") is not None else 0.0,
                 ">=", -c.RHC_MOM_MAX_LIQ_DROP)]


class VolatilityExpansion(Strategy):
    """Range compression followed by a strong expansion candle that closes near its high."""
    name = "vol_expansion"
    enabled_flag = "RHC_STRAT_VOLEXP_ENABLED"

    def conditions(self, f):
        c = self.cfg
        atr = f.get("atr14")
        expansion = (f.get("range_1m") / atr) if atr and f.get("range_1m") else None
        return [("atr_ratio", f.get("atr_ratio"), "<=", c.RHC_VEX_MAX_ATR_RATIO),
                ("range_expansion", expansion, ">=", c.RHC_VEX_MIN_EXPANSION),
                ("close_pos_1m", f.get("close_pos_1m"), ">=", c.RHC_VEX_MIN_CLOSE_POS),
                ("ret_1m", f.get("ret_1m"), ">", 0.0),
                ("imbalance_5m", f.get("imbalance_5m"), ">=", c.RHC_VEX_IMBALANCE)]


class LiquidityGrowth(Strategy):
    """Liquidity growing with organic buy-side flow and a non-negative trend."""
    name = "liquidity_growth"
    enabled_flag = "RHC_STRAT_LIQ_ENABLED"

    def conditions(self, f):
        c = self.cfg
        return [("liq_change_60m", f.get("liq_change_60m"), ">=", c.RHC_LIQ_MIN_GROWTH_60M),
                ("ret_60m", f.get("ret_60m"), ">=", 0.0),
                ("imbalance_15m", f.get("imbalance_15m"), ">=", c.RHC_LIQ_IMBALANCE),
                ("traders_15m", f.get("traders_15m"), ">=", c.RHC_LIQ_MIN_TRADERS)]


class SmartMoneyFlow(Strategy):
    """Buys from wallets with good PAST realized outcomes. Off by default until the smart-money
    feature shows predictive value out of sample (see rhc_wallets.evaluate)."""
    name = "smart_money"
    enabled_flag = "RHC_STRAT_SMART_ENABLED"

    def conditions(self, f):
        c = self.cfg
        return [("smart_buy_usd_15m", f.get("smart_buy_usd_15m"), ">=", c.RHC_SMART_MIN_BUY_USD),
                ("smart_buyers_15m", f.get("smart_buyers_15m"), ">=", c.RHC_SMART_MIN_BUYERS),
                ("imbalance_15m", f.get("imbalance_15m"), ">=", 0.5),
                ("dist_vwap_60m", f.get("dist_vwap_60m"), "<=", c.RHC_MOM_MAX_VWAP_DIST)]


ALL = [VolumeBreakout, MomentumContinuation, VolatilityExpansion, LiquidityGrowth, SmartMoneyFlow]


def build(cfg):
    return [S(cfg) for S in ALL]


def confirm(setup, f_next, cfg):
    """Pure: confirmation on the NEXT closed candle. Returns (confirmed, reason_code)."""
    p = f_next.get("price_usd")
    if not p or f_next.get("last_bucket") is None or f_next["last_bucket"] <= setup.evidence.get("_last_bucket", 0):
        return None, None                                         # no new candle yet: keep waiting
    if p <= setup.entry_ref * (1.0 - cfg.RHC_CONFIRM_MAX_DIP):
        return False, "CONFIRM_FAILED_DIP"
    if p >= setup.entry_ref * (1.0 + cfg.RHC_MAX_CHASE):
        return False, "CONFIRM_FAILED_CHASE"
    if (f_next.get("imbalance_5m") or 0) < cfg.RHC_CONFIRM_MIN_IMBALANCE:
        return False, "CONFIRM_FAILED_FLOW"
    return True, None
