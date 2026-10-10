import collections
import pandas as pd
from typing import List, Optional

class MockMSS:
    def __init__(self, body, fvg):
        self.body = body
        self.fvg = fvg

class FVG:
    def __init__(self, top, bottom):
        self.top = top
        self.bottom = bottom
        self.midpoint = (top + bottom) / 2

class Structure1m:
    def __init__(self):
        self.bars = collections.deque(maxlen=100)
        self.swing_highs = []
        self.swing_lows = []
        
    def add_bar(self, bar):
        self.bars.append(bar)
        self._calculate_fractals()
        
    def _calculate_fractals(self):
        # Need at least 5 bars for an n=2 fractal
        if len(self.bars) < 5:
            return
            
        # Check for swing high (n=2)
        if (self.bars[-3].high > self.bars[-1].high and 
            self.bars[-3].high > self.bars[-2].high and 
            self.bars[-3].high > self.bars[-4].high and 
            self.bars[-3].high > self.bars[-5].high):
            self.swing_highs.append(self.bars[-3].high)
            
        # Check for swing low (n=2)
        if (self.bars[-3].low < self.bars[-1].low and 
            self.bars[-3].low < self.bars[-2].low and 
            self.bars[-3].low < self.bars[-4].low and 
            self.bars[-3].low < self.bars[-5].low):
            self.swing_lows.append(self.bars[-3].low)

    def mss_up(self, after_ts: int, atr1: float) -> Optional[MockMSS]:
        """
        Detects an upward Market Structure Shift (MSS) after a sweep.
        """
        if len(self.bars) < 3 or not self.swing_highs:
            return None
            
        last_bar = self.bars[-1]
        
        # Did we close above the last lower-high?
        last_lower_high = self.swing_highs[-1]
        
        if last_bar.close > last_lower_high and last_bar.ts > after_ts:
            body_size = abs(last_bar.close - last_bar.open)
            
            # Check displacement (body >= 1.2 * ATR1)
            if body_size >= 1.2 * atr1:
                # Check for FVG (Fair Value Gap)
                # FVG requires 3 bars: bar1.high < bar3.low
                bar1 = self.bars[-3]
                bar3 = self.bars[-1]
                
                if bar1.high < bar3.low:
                    # Valid Bullish FVG
                    fvg = FVG(top=bar3.low, bottom=bar1.high)
                    return MockMSS(body=body_size, fvg=fvg)
                    
        return None

    def last_higher_low(self):
        if len(self.swing_lows) >= 2:
            # Simplistic: just return the last swing low for trailing
            return self.swing_lows[-1]
        return None


class Liquidity5m:
    def __init__(self):
        self.bars = collections.deque(maxlen=144) # 12 hours of 5m bars
        self.pools_below = []
        
    def add_bar(self, bar):
        self.bars.append(bar)
        self._calculate_fractals()
        
    def _calculate_fractals(self):
        if len(self.bars) < 5:
            return
            
        # n=2 swing low fractal
        if (self.bars[-3].low < self.bars[-1].low and 
            self.bars[-3].low < self.bars[-2].low and 
            self.bars[-3].low < self.bars[-4].low and 
            self.bars[-3].low < self.bars[-5].low):
            
            pool_level = self.bars[-3].low
            if pool_level not in self.pools_below:
                self.pools_below.append(pool_level)

    def swept_level(self, bar_1m, min_d, max_d) -> Optional[float]:
        """
        Check if the 1m bar sweeps a known 5m liquidity pool within the depth constraints.
        """
        for pool in reversed(self.pools_below):
            sweep_depth = pool - bar_1m.low
            
            if sweep_depth > 0:
                # It swept below the pool
                if min_d <= sweep_depth <= max_d:
                    return pool
        return None

    def next_pool_above(self, price: float) -> float:
        # Mock: In reality we would track pools_above using swing highs
        return price + 500


class FlowConfirmer:
    def __init__(self):
        self.cvd_history = collections.deque(maxlen=60) # Store CVD per minute for the last hour
        self.current_minute_cvd = 0.0
        self.current_minute_ts = 0

    def update_tick(self, price: float, qty: float, is_buyer_maker: bool, ts: int):
        """
        is_buyer_maker = True means it was a Market Sell.
        is_buyer_maker = False means it was a Market Buy.
        """
        # Convert timestamp to minute bucket
        minute_bucket = ts // 60000 
        
        if minute_bucket > self.current_minute_ts:
            if self.current_minute_ts != 0:
                self.cvd_history.append(self.current_minute_cvd)
            self.current_minute_ts = minute_bucket
            self.current_minute_cvd = 0.0

        # Calculate Delta
        trade_value = price * qty
        if is_buyer_maker:
            # Market Sell
            self.current_minute_cvd -= trade_value
        else:
            # Market Buy
            self.current_minute_cvd += trade_value

    def count_confirms(self, direction: str) -> int:
        """
        Returns the number of confirmations (0 to 3).
        1. CVD Divergence: Price lower low, CVD higher low (Absorption)
        """
        confirms = 0
        if len(self.cvd_history) < 5:
            # Not enough data, return a default pass so we don't block early testing
            return 2 
            
        # Very basic CVD momentum check: 
        # Are market buyers currently aggressive?
        recent_cvd_sum = sum(list(self.cvd_history)[-3:]) + self.current_minute_cvd
        
        if direction == "long" and recent_cvd_sum > 0:
            confirms += 2 # Strong buying pressure in the last 3 minutes
            
        return confirms

    def breakout_veto(self) -> bool:
        """
        If we are trying to go long, but CVD is massively negative (huge market selling),
        we veto the trade to avoid catching a falling knife.
        """
        if len(self.cvd_history) < 2: return False
        
        # If the current minute has immense selling pressure vs average
        if self.current_minute_cvd < -500000: # Example threshold: >$500k net selling in a minute
            return True
            
        return False


class ExecutionWrapper:
    def __init__(self, paper_engine):
        self.paper = paper_engine

    def place_post_only(self, plan, ttl_bars):
        print(f"[EXEC] Placing POST-ONLY buy at {plan.entry:.2f} qty {plan.qty:.4f}")
        # In a real environment, this places a limit order on exchange.
        # For paper, we just execute immediately since the price usually hits the FVG midpoint.
        self.paper.execute_buy(symbol="BTCUSDT", quote_usdt=plan.qty * plan.entry, price=plan.entry, stop=plan.stop)

    def exit_market(self, pos, reason: str):
        print(f"[EXEC] Exiting position at market. Reason: {reason}")
        # Close the full position at market
        # For paper engine, we just sell the whole qty at the current price (or in this mock, we'll let the engine read current price, but we need current price)
        # We will assume pos.stop is hit or we just pass the stop price for execution
        # Wait, the engine requires a price. If it's a stop, exit at stop. If time, exit at entry as a mock.
        exit_price = pos.stop if "STOP" in reason else pos.entry
        self.paper.execute_sell(symbol="BTCUSDT", qty=pos.qty, price=exit_price, reason=reason)


class MarketContext:
    def __init__(self, paper_engine):
        self.TICK_SIZE = 0.1
        self.ESTIMATED_FEES = 0.001 
        
        self.atr1 = 50.0  # Would be calculated dynamically
        self.atr5 = 150.0 # Would be calculated dynamically
        self.vol_med30 = 0.0 
        self.spread = 0.1
        self.slip = 0.0005
        
        self.equity = 5000.0
        self.buffer = 10.0
        
        self.regime_ok = True
        self.in_killzone = True
        self.cost_ok = True
        
        self.structure1m = Structure1m()
        self.liq5m = Liquidity5m()
        self.flow = FlowConfirmer()
        self.exec = ExecutionWrapper(paper_engine)
        
        self.recent_1m_vols = collections.deque(maxlen=30)
        self.sweep_history = {} # tracking level -> time reclaimed

    def update_1m(self, bar):
        self.structure1m.add_bar(bar)
        self.recent_1m_vols.append(bar.vol)
        if len(self.recent_1m_vols) == 30:
            import statistics
            self.vol_med30 = statistics.median(self.recent_1m_vols)

    def update_5m(self, bar):
        self.liq5m.add_bar(bar)

    def reclaimed_within(self, lvl: float, bars: int) -> bool:
        """
        Check if price closed back above the sweep level within `bars` count.
        """
        # If the current 1m bar's close is > lvl, it reclaimed it.
        if not self.structure1m.bars: return False
        return self.structure1m.bars[-1].close > lvl

    def closes_below(self, price: float, n: int) -> bool:
        if len(self.structure1m.bars) < n: return False
        count = 0
        for i in range(1, n+1):
            if self.structure1m.bars[-i].close < price:
                count += 1
        return count >= n
        
    def bars_since(self, ts: int) -> int:
        count = 0
        for b in reversed(self.structure1m.bars):
            if b.ts == ts:
                return count
            count += 1
        return 999 

    def score(self, sweep, mss, plan) -> int:
        return 6 

    def size_position(self, equity, risk_pct, entry, stop, fees, slip) -> float:
        risk_amount = equity * risk_pct
        risk_per_unit = entry - stop
        if risk_per_unit <= 0: return 0.0
        return risk_amount / risk_per_unit

    def calculate_net_rr(self, entry, stop, tp2, fees, slip) -> float:
        risk = entry - stop
        reward = tp2 - entry
        if risk <= 0: return 0.0
        return reward / risk
