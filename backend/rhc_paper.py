"""Paper trading: fill model, position management and the PaperBroker.

Fill model (forward paper trading, live chain state):
  * the order executes RHC_PAPER_LATENCY_S after the decision, against the pool state THEN
    (intervening trades are reflected: adverse selection is not ignored);
  * entry = simulated buy at the intended size through the pool's own contract (fees, hook fees,
    price impact and token taxes are all inside the simulation);
  * exit  = simulated sell of the exact tokens held;
  * plus gas (simulated gas x router-overhead multiplier x live gas price x ETH/USD), a safety
    slippage haircut RHC_PAPER_EXTRA_SLIP_BPS on every fill, and a deterministic failed-tx
    probability (a failed tx pays gas and fills nothing);
  * a position whose sell keeps failing is marked STUCK and booked as a 100% loss.
Exits (pure `manage`, shared with the backtester):
  * stop is checked against the candle LOW; a gap through the stop fills at the open, not at the stop;
  * if stop and target are touched in the same candle the stop is assumed first (conservative);
  * target 1 sells RHC_TP1_FRACTION and moves the stop to break-even; then the stop trails the
    peak by the original stop distance; target 2 sells the rest; time stop exits everything.
Paper results will still OVERSTATE live results (see docs/robinhood-chain/VALIDATION.md).
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field

import rhc_config as cfg
from rhc_decision import Broker
from rhc_risk import OpenPosition

log = logging.getLogger("rhc.paper")


# ── pure helpers ──────────────────────────────────────────────────────────────
def fails(order_key, prob):
    """Deterministic pseudo-random failure: same order key -> same outcome (reproducible)."""
    h = int(hashlib.sha256(order_key.encode()).hexdigest()[:8], 16)
    return (h % 10_000) < int(prob * 10_000)


def gas_usd(sim_gas, gas_price_wei, eth_usd, config=cfg):
    if not sim_gas or not gas_price_wei or not eth_usd:
        return config.RHC_PAPER_GAS_FLOOR_USD
    return max(config.RHC_PAPER_GAS_FLOOR_USD,
               sim_gas * config.RHC_PAPER_GAS_OVERHEAD_MULT * gas_price_wei / 1e18 * eth_usd)


@dataclass
class Leg:
    ts: int
    side: str
    reason: str
    tokens: float          # human units
    usd: float             # spent (buy, incl. gas) or received (sell, net of gas)
    price_usd: float       # effective price per token
    gas_usd: float
    ok: bool = True


@dataclass
class Position:
    pool_pk: int
    token: str
    strategy: str
    opened_ts: int
    entry_price: float        # effective (all-in) USD price per token
    tokens: float             # tokens currently held (human units)
    tokens_raw: int           # raw base units currently held
    cost_usd: float           # total USD spent incl. gas
    stop: float
    stop_pct: float
    targets: list
    time_stop_ts: int
    regime: str = None
    risk_usd: float = 0.0
    tp1_done: bool = False
    peak: float = 0.0
    status: str = "open"      # open | closed | stuck
    proceeds_usd: float = 0.0
    sell_failures: int = 0
    legs: list = field(default_factory=list)
    id: int = None

    @property
    def realized_usd(self):
        return self.proceeds_usd - self.cost_usd if self.status != "open" else None


def manage(pos, candle, now_ts, config=cfg):
    """Pure exit logic for one closed candle (dict with o,h,l,c in USD). Returns a list of
    actions: ("SELL", fraction_of_current, reason, ref_price). Mutates pos.stop / pos.peak."""
    if pos.status != "open" or candle is None:
        return []
    o, h, l, c = (candle.get(k) for k in ("o_usd", "h_usd", "l_usd", "c_usd"))
    if not all((o, h, l, c)):
        return []
    acts = []
    # Stop first (conservative when the same candle also touches a target).
    if l <= pos.stop:
        ref = o if o <= pos.stop else pos.stop                    # gap through the stop -> the open
        return [("SELL", 1.0, "STOP" if not pos.tp1_done else "TRAIL_STOP", ref)]
    if not pos.tp1_done and pos.targets and h >= pos.targets[0]:
        acts.append(("SELL", config.RHC_TP1_FRACTION, "TP1", max(o, pos.targets[0])))
        pos.tp1_done = True
        pos.stop = max(pos.stop, pos.entry_price)                 # break-even
    if len(pos.targets) > 1 and pos.tp1_done and h >= pos.targets[1]:
        return acts + [("SELL", 1.0, "TP2", max(o, pos.targets[1]))]
    pos.peak = max(pos.peak or 0.0, h)
    if pos.tp1_done:
        pos.stop = max(pos.stop, pos.peak * (1.0 - pos.stop_pct))
    if now_ts >= pos.time_stop_ts:
        acts.append(("SELL", 1.0, "TIME_STOP", c))
    return acts


# ── PaperBroker (forward paper trading on live state) ─────────────────────────
class PaperBroker(Broker):
    name = "paper"
    executes = False          # never touches real funds

    def __init__(self, rpc, store, registry, pricer, sim=None, clock=time.time, sleep=time.sleep, config=cfg):
        from rhc_sim import Simulator
        self.rpc = rpc
        self.store = store
        self.registry = registry
        self.pricer = pricer
        self.sim = sim or Simulator(rpc)
        self.clock = clock
        self.sleep = sleep
        self.cfg = config
        self.positions = []          # open positions (loaded from DB on start)
        self.metrics = {"entries": 0, "failed_entries": 0, "exits": 0, "stuck": 0, "last_error": None}
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.positions = self.store.load_open_paper_positions()
            self._loaded = True

    def _gas_price(self):
        try:
            return int(self.rpc.call("eth_gasPrice", []), 16)
        except Exception:
            return None

    def _qdec(self, meta):
        return meta.dec1 if meta.base_index == 0 else meta.dec0

    def _bdec(self, meta):
        return meta.dec0 if meta.base_index == 0 else meta.dec1

    def open_positions(self):
        self._ensure_loaded()
        out = []
        for p in self.positions:
            last = self.store.last_close_usd(p.pool_pk)
            unreal = (p.tokens * last - (p.cost_usd - p.proceeds_usd)) if last else 0.0
            out.append(OpenPosition(p.pool_pk, p.token, p.cost_usd - p.proceeds_usd, unreal))
        return out

    def realized_today(self, now):
        return self.store.paper_realized_since(int(now) - int(now) % 86400)

    def last_exit_ts(self):
        return self.store.paper_last_exit_by_token()

    # entries
    def submit(self, intent):
        self._ensure_loaded()
        meta = self.registry.by_pk.get(intent["pool_pk"])
        if meta is None:
            return {"status": "rejected", "executed": False, "reason": "POOL_NOT_CACHED"}
        self.sleep(self.cfg.RHC_PAPER_LATENCY_S)                 # execute against the state after latency
        now = int(self.clock())
        qusd = self.pricer.usd(meta.quote_class)
        qdec, bdec = self._qdec(meta), self._bdec(meta)
        if not qusd or qdec is None or bdec is None:
            return {"status": "rejected", "executed": False, "reason": "NO_QUOTE_PRICE"}
        size = float(intent["size_usd"])
        amount = int(size / qusd * 10 ** qdec)
        fee = self.cfg.RHC_V2_FEE_BPS.get(meta.venue or "", self.cfg.RHC_V2_FEE_BPS_DEFAULT)
        key = f"entry:{intent['pool_pk']}:{intent['strategy']}:{intent['as_of']}"
        res = self.sim.run(meta, amount, fee)
        gas = gas_usd(res.gas_buy, self._gas_price(), self.pricer.eth_usd, self.cfg)
        if fails(key, self.cfg.RHC_PAPER_FAIL_PROB) or not res.raw or not res.raw[2] or res.status not in ("ok",):
            self.metrics["failed_entries"] += 1
            self.store.insert_paper_fill(None, intent["pool_pk"], now, "buy", "ENTRY_FAILED", 0.0, gas, None, False,
                                         {"sim_status": res.status, "error": res.error})
            return {"status": "failed", "executed": False, "sim_status": res.status, "gas_usd": gas}
        haircut = 1.0 - self.cfg.RHC_PAPER_EXTRA_SLIP_BPS / 10_000
        tokens_raw = int(res.raw[2] * haircut)
        tokens = tokens_raw / 10 ** bdec
        cost = size + gas
        entry_px = cost / tokens if tokens else 0.0
        scale = entry_px / intent["entry_ref"] if intent.get("entry_ref") else 1.0
        stop_pct = 1.0 - intent["stop"] / intent["entry_ref"]
        pos = Position(pool_pk=intent["pool_pk"], token=intent.get("token") or meta.base_token,
                       strategy=intent["strategy"], opened_ts=now, entry_price=entry_px, tokens=tokens,
                       tokens_raw=tokens_raw, cost_usd=cost, stop=entry_px * (1.0 - stop_pct), stop_pct=stop_pct,
                       targets=[t * scale for t in intent["targets"]],
                       time_stop_ts=now + int(intent.get("time_stop_min", self.cfg.RHC_TIME_STOP_MIN)) * 60,
                       regime=((intent.get("evidence") or {}).get("regime") or {}).get("label"),
                       risk_usd=size * stop_pct, peak=entry_px)
        pos.legs.append(Leg(now, "buy", "ENTRY", tokens, cost, entry_px, gas))
        pos.id = self.store.insert_paper_position(pos, intent)
        self.store.insert_paper_fill(pos.id, pos.pool_pk, now, "buy", "ENTRY", cost, gas, entry_px, True,
                                     {"sim_status": res.status, "buy_tax": res.buy_tax, "slippage_vs_ref":
                                      entry_px / intent["entry_ref"] - 1.0 if intent.get("entry_ref") else None})
        self.positions.append(pos)
        self.metrics["entries"] += 1
        return {"status": "filled", "executed": False, "paper_position_id": pos.id, "entry_price": entry_px,
                "slippage_vs_ref": scale - 1.0, "gas_usd": gas}

    # exits
    def _sell(self, pos, meta, frac, reason, now):
        tokens_raw = pos.tokens_raw if frac >= 0.999 else int(pos.tokens_raw * frac)
        fee = self.cfg.RHC_V2_FEE_BPS.get(meta.venue or "", self.cfg.RHC_V2_FEE_BPS_DEFAULT)
        key = f"exit:{pos.id}:{reason}:{now // 60}"
        res = self.sim.run_sell(meta, tokens_raw, fee)
        approx = False
        if res.status == "SIM_TOKEN_SLOT_UNKNOWN":
            res, approx = self._approx_sell(meta, pos, tokens_raw, fee), True
        gas = gas_usd(res.gas, self._gas_price(), self.pricer.eth_usd, self.cfg)
        if fails(key, self.cfg.RHC_PAPER_FAIL_PROB) or not res.ok:
            pos.sell_failures += 1
            pos.proceeds_usd -= gas                                    # failed tx still pays gas
            self.store.insert_paper_fill(pos.id, pos.pool_pk, now, "sell", f"{reason}_FAILED", 0.0, gas, None, False,
                                         {"sim_status": res.status, "error": res.error})
            if pos.sell_failures >= self.cfg.RHC_PAPER_STUCK_AFTER:
                pos.status = "stuck"                                   # cannot exit: book a 100% loss
                pos.tokens, pos.tokens_raw = 0.0, 0
                self.metrics["stuck"] += 1
            self.store.update_paper_position(pos)
            return False
        qusd = self.pricer.usd(meta.quote_class) or 0.0
        haircut = 1.0 - self.cfg.RHC_PAPER_EXTRA_SLIP_BPS / 10_000
        received = res.proceeds / 10 ** self._qdec(meta) * qusd * haircut - gas
        sold = tokens_raw / 10 ** self._bdec(meta)
        pos.proceeds_usd += received
        pos.tokens_raw -= tokens_raw
        pos.tokens = pos.tokens_raw / 10 ** self._bdec(meta)
        px = received / sold if sold else 0.0
        pos.legs.append(Leg(now, "sell", reason, sold, received, px, gas))
        self.store.insert_paper_fill(pos.id, pos.pool_pk, now, "sell", reason, received, gas, px, True,
                                     {"sim_status": res.status, "sell_tax": res.sell_tax, "approx": approx})
        if pos.tokens_raw <= 0:
            pos.status = "closed"
        self.store.update_paper_position(pos)
        self.metrics["exits"] += 1
        return True

    def _approx_sell(self, meta, pos, tokens_raw, fee):
        """Fallback when the token's balance slot cannot be overridden (non-standard ERC-20):
        a round trip of similar size gives quote-per-token on its sell leg; that leg starts after our
        own buy pushed the price up, so half the round-trip cost is deducted again (conservative)."""
        from rhc_sim import SellResult
        last = self.store.last_close_usd(pos.pool_pk)
        qusd = self.pricer.usd(meta.quote_class)
        if not last or not qusd:
            return SellResult(status="SIM_APPROX_UNAVAILABLE", tokens=tokens_raw)
        value_quote = tokens_raw / 10 ** self._bdec(meta) * last / qusd
        rt = self.sim.run(meta, max(1, int(value_quote * 10 ** self._qdec(meta))), fee)
        if not rt.ok or not rt.raw[2]:
            return SellResult(status=f"APPROX_{rt.status}", tokens=tokens_raw)
        per_token = rt.raw[5] / rt.raw[2]
        proceeds = int(tokens_raw * per_token * (1.0 - (rt.round_trip_cost or 0.0) / 2.0))
        return SellResult(status="ok", tokens=tokens_raw, proceeds=proceeds, sell_tax=rt.sell_tax, gas=rt.gas_sell)

    def process(self, now=None):
        """Manage open positions on their latest closed candle."""
        self._ensure_loaded()
        now = int(now or self.clock())
        for pos in list(self.positions):
            meta = self.registry.by_pk.get(pos.pool_pk)
            if meta is None:
                continue
            emergency = self.store.watch_state(pos.pool_pk) == "rejected" and self.store.latest_reject_is_permanent(
                pos.pool_pk)
            candle = self.store.last_candle_usd(pos.pool_pk, since=pos.opened_ts)
            acts = [("SELL", 1.0, "EMERGENCY", None)] if emergency else manage(pos, candle, now, self.cfg)
            for _, frac, reason, _ in acts:
                if pos.status != "open":
                    break
                self._sell(pos, meta, frac, reason, now)
            self.store.update_paper_position(pos)
            if pos.status != "open":
                self.positions.remove(pos)
