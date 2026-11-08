"""Risk engine (pure): position sizing and entry permission.

Rules (all config-driven):
  * global kill switch, and no-trade regime codes, block every new entry;
  * max open positions, max total exposure (% of equity), per-token exposure cap;
  * daily loss limit (realized + unrealized, UTC day) blocks new entries once hit;
  * per-token cooldown after an exit;
  * size = equity * risk_pct / stop_pct (fixed-fractional), clamped to [min, max] position size,
    to the remaining exposure/per-token headroom, and to a liquidity cap derived from the
    simulated price impact at the screening size (impact grows roughly linearly with size for
    small trades, so size_cap = screen_size * max_impact / impact_at_screen_size).
"""
from dataclasses import dataclass, field


@dataclass
class OpenPosition:
    pool_pk: int
    token: str
    size_usd: float
    unrealized_usd: float = 0.0


@dataclass
class RiskState:
    equity_usd: float
    open_positions: list = field(default_factory=list)
    realized_today_usd: float = 0.0
    last_exit_ts: dict = field(default_factory=dict)      # token -> ts
    kill_switch: bool = False

    @property
    def exposure_usd(self):
        return sum(p.size_usd for p in self.open_positions)

    @property
    def unrealized_usd(self):
        return sum(p.unrealized_usd for p in self.open_positions)

    def token_exposure(self, token):
        return sum(p.size_usd for p in self.open_positions if p.token == token)


def size_and_check(state, token, stop_pct, now_ts, no_trade_codes, screen_impact, cfg):
    """Returns (size_usd or 0, reasons[], evidence{}). reasons empty => entry allowed."""
    reasons = []
    ev = {"equity": state.equity_usd, "exposure": state.exposure_usd, "open": len(state.open_positions),
          "realized_today": state.realized_today_usd, "unrealized": state.unrealized_usd}
    if state.kill_switch or cfg.RHC_KILL_SWITCH:
        reasons.append("KILL_SWITCH")
    reasons += [f"NO_TRADE_{c}" for c in no_trade_codes]
    if len(state.open_positions) >= cfg.RHC_MAX_OPEN:
        reasons.append("MAX_OPEN_POSITIONS")
    day_pnl = state.realized_today_usd + state.unrealized_usd
    if day_pnl <= -cfg.RHC_MAX_DAILY_LOSS_PCT * state.equity_usd:
        reasons.append("DAILY_LOSS_LIMIT")
    last = state.last_exit_ts.get(token)
    if last is not None and now_ts - last < cfg.RHC_TOKEN_COOLDOWN_MIN * 60:
        reasons.append("TOKEN_COOLDOWN")
    if not stop_pct or stop_pct <= 0:
        reasons.append("INVALID_STOP")
        return 0.0, reasons, ev

    raw = state.equity_usd * cfg.RHC_RISK_PCT / stop_pct
    caps = {"max_position": cfg.RHC_MAX_POSITION_USD,
            "exposure_headroom": cfg.RHC_MAX_EXPOSURE_PCT * state.equity_usd - state.exposure_usd,
            "token_headroom": cfg.RHC_MAX_PER_TOKEN_USD - state.token_exposure(token)}
    if screen_impact is not None and screen_impact > 0:
        caps["liquidity"] = cfg.RHC_SCREEN_TRADE_USD * cfg.RHC_MAX_IMPACT / screen_impact
    size = min([raw] + list(caps.values()))
    ev.update(raw_size=raw, caps=caps, stop_pct=stop_pct)
    if size < cfg.RHC_MIN_POSITION_USD:
        reasons.append("SIZE_BELOW_MIN")
        size = 0.0
    if reasons:
        return 0.0, reasons, ev
    return round(size, 2), [], ev
