import time
from typing import Optional, List

class Plan:
    def __init__(self, entry: float, stop: float, tp1: float, tp2: float, qty: float, net_rr: float):
        self.entry = entry
        self.stop = stop
        self.tp1 = tp1
        self.tp2 = tp2
        self.qty = qty
        self.net_rr = net_rr

class Position:
    def __init__(self, plan: Plan, entry_ts: int, fees: float):
        self.entry = plan.entry
        self.stop = plan.stop
        self.tp1 = plan.tp1
        self.tp2 = plan.tp2
        self.qty = plan.qty
        self.entry_ts = entry_ts
        self.fees = fees
        self.tp1_hit = False

class Sweep:
    def __init__(self, level: float, low: float, ts: int):
        self.level = level
        self.low = low
        self.ts = ts

class ScalpFSM:
    """
    1m/5m "Sweep -> Reclaim -> MSS -> FVG" Scalper FSM
    Core strategy state machine tracking the setup cycle.
    """
    def __init__(self):
        self.state = "IDLE"  # IDLE -> SWEPT -> ARMED -> IN_POSITION
        self.sweep: Optional[Sweep] = None
        self.active_plan: Optional[Plan] = None

    def reset(self, reason: str):
        print(f"FSM Reset: {reason}")
        self.state = "IDLE"
        self.sweep = None
        self.active_plan = None

    def on_1m_close(self, bar, ctx):
        """
        Called on every 1-minute candle close.
        `bar`: contains o, h, l, c, v, ts
        `ctx`: provides market context (ATR, regime, liquidity levels, flow confirmation)
        """
        if not (ctx.regime_ok and ctx.in_killzone and ctx.cost_ok):
            return self.reset("filters")

        if self.state == "IDLE":
            # Stage 2: Sweep detection
            lvl = ctx.liq5m.swept_level(bar, min_d=0.15 * ctx.atr5, max_d=0.8 * ctx.atr5)
            if lvl and ctx.reclaimed_within(lvl, bars=3) and bar.vol >= 2 * ctx.vol_med30:
                if ctx.flow.count_confirms("long") >= 2 and not ctx.flow.breakout_veto():
                    self.sweep = Sweep(lvl, bar.low, bar.ts)
                    self.state = "SWEPT"
                    print(f"FSM: Detected sweep at {lvl}")

        elif self.state == "SWEPT":
            # Invalidation
            if ctx.closes_below(self.sweep.low, n=1) or ctx.bars_since(self.sweep.ts) > 8:
                return self.reset("invalid/timeout")
            
            # Stage 3: Micro Market Structure Shift (MSS)
            mss = ctx.structure1m.mss_up(after=self.sweep.ts)
            if mss and mss.body >= 1.2 * ctx.atr1 and mss.fvg:
                plan = self.build_plan(mss.fvg, self.sweep, ctx)
                if plan and ctx.score(self.sweep, mss, plan) >= 5 and plan.net_rr >= 2.0:
                    ctx.exec.place_post_only(plan, ttl_bars=8)
                    self.active_plan = plan
                    self.state = "ARMED"
                    print("FSM: ARMED, placed post-only limit entry.")

    def build_plan(self, fvg, sweep, ctx) -> Optional[Plan]:
        TICK = ctx.TICK_SIZE
        FEES = ctx.ESTIMATED_FEES
        
        entry = fvg.midpoint
        stop = sweep.low - max(0.2 * ctx.atr1, 4 * TICK, 1.5 * ctx.spread)
        dist = entry - stop
        
        # Minimum stop distance cost-check
        if not (0.0018 * entry <= dist <= 1.2 * ctx.atr5): 
            return None
            
        tp1 = entry + 1.5 * dist
        tp2 = ctx.liq5m.next_pool_above(entry)
        
        # Sizing and Risk Math
        qty = ctx.size_position(ctx.equity, 0.005, entry, stop, FEES, ctx.slip)
        net_rr = ctx.calculate_net_rr(entry, stop, tp2, FEES, ctx.slip)
        
        return Plan(entry, stop, tp1, tp2, qty, net_rr)

# Tick-driven trade manager for live positions
def on_tick(pos: Position, px: float, ctx):
    """
    Evaluated on incoming tick / aggregate trade data.
    """
    if px <= pos.stop:
        ctx.exec.exit_market(pos, "STOP")
    elif not pos.tp1_hit and px >= pos.tp1:
        pos.tp1_hit = True
        pos.stop = pos.entry + pos.fees  # Break-even + fees
        print("TP1 hit. Stop moved to BE+fees.")
    elif pos.tp1_hit:
        # Trail behind new higher-lows after TP1
        hl = ctx.structure1m.last_higher_low()
        if hl:
            pos.stop = max(pos.stop, hl - ctx.buffer)
    
    # Time exit (20 bars)
    if ctx.bars_since(pos.entry_ts) > 20 and not pos.tp1_hit:
        ctx.exec.exit_market(pos, "TIME")
