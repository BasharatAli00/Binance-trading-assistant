"""Buy -> sell round-trip simulation via eth_call state overrides (no keys, no funds, no txs).

The simulator contract (contracts/RhcSimulator.sol) is injected at a throw-away address.
Quote assets are supplied by overriding the simulator's balance: native ETH via the account
balance, ERC-20 quotes (WETH, USDG) via the token's balance-mapping storage slot, which is
discovered once per token.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import function_signature_to_4byte_selector, keccak

import rhc_config as cfg
from rhc_decoders import ZERO_ADDR
from rhc_rpc import RpcError

log = logging.getLogger("rhc.sim")

SIM_ADDR = "0x00000000000000000000000000000000005151a0"
SIM_ETH_BALANCE = 10 ** 27
OZ5_ERC20_NAMESPACE = 0x52c63247e1f47db19d5ce0460030c497f067ca4cebf71ba98eeadabe20bace00

SEL_V2 = "0x" + function_signature_to_4byte_selector("simV2(address,address,address,uint256,uint256)").hex()
SEL_V3 = "0x" + function_signature_to_4byte_selector("simV3(address,address,address,uint256)").hex()
SEL_V4 = "0x" + function_signature_to_4byte_selector(
    "simV4(address,(address,address,uint24,int24,address),bool,uint256)").hex()
SEL_SELL_V2 = "0x" + function_signature_to_4byte_selector(
    "simSellV2(address,address,address,uint256,uint256)").hex()
SEL_SELL_V3 = "0x" + function_signature_to_4byte_selector("simSellV3(address,address,address,uint256)").hex()
SEL_SELL_V4 = "0x" + function_signature_to_4byte_selector(
    "simSellV4(address,(address,address,uint24,int24,address),bool,uint256)").hex()
SEL_BALANCE_OF = "0x70a08231"

STATUS = {0: "ok", 1: "BUY_FAILED", 2: "SELL_TRANSFER_BLOCKED", 3: "SELL_FAILED", 4: "ZERO_RECEIVED"}


@dataclass
class SimResult:
    status: str
    amount_in: int
    raw: list = field(default_factory=list)
    buy_tax: Optional[float] = None
    sell_tax: Optional[float] = None
    round_trip_cost: Optional[float] = None
    gas_buy: Optional[int] = None
    gas_sell: Optional[int] = None
    error: Optional[str] = None

    @property
    def ok(self):
        return self.status == "ok"

    def as_dict(self):
        return {"status": self.status, "buy_tax": self.buy_tax, "sell_tax": self.sell_tax,
                "round_trip_cost": self.round_trip_cost, "gas_buy": self.gas_buy, "gas_sell": self.gas_sell,
                "error": self.error}


def _ratio_loss(got, expected):
    if not expected:
        return None
    return max(0.0, 1.0 - got / expected)


def interpret(r, amount_in):
    """Pure: turn the simulator's uint256[8] into taxes and costs."""
    status = STATUS.get(r[0], f"UNKNOWN_{r[0]}")
    if r[0] == 4 and not r[1]:
        status = "NO_LIQUIDITY"       # the pool itself returned nothing (vs. a 100% transfer tax)
    res = SimResult(status=status, amount_in=amount_in, raw=list(r), gas_buy=r[6] or None, gas_sell=r[7] or None)
    if r[1]:
        res.buy_tax = _ratio_loss(r[2], r[1])
    if r[2] and r[0] in (0, 3):
        res.sell_tax = _ratio_loss(r[3], r[2])
    if r[0] == 0 and amount_in:
        res.round_trip_cost = max(0.0, 1.0 - r[5] / amount_in)
    return res


@dataclass
class SellResult:
    status: str
    tokens: int
    proceeds: int = 0           # quote units actually received
    sell_tax: Optional[float] = None
    gas: Optional[int] = None
    error: Optional[str] = None

    @property
    def ok(self):
        return self.status == "ok"


def interpret_sell(r, tokens):
    """Pure: sell-only simulator output -> SellResult."""
    status = STATUS.get(r[0], f"UNKNOWN_{r[0]}")
    res = SellResult(status=status, tokens=tokens, proceeds=r[5], gas=r[7] or None)
    if r[2] and r[0] in (0, 3):
        res.sell_tax = _ratio_loss(r[3], r[2])
    return res


def _pad(addr_or_int):
    if isinstance(addr_or_int, str):
        return bytes.fromhex(addr_or_int[2:].rjust(64, "0"))
    return addr_or_int.to_bytes(32, "big")


def mapping_slot(holder, base_slot, vyper=False):
    """Storage slot of mapping[holder] for a mapping at base_slot (Solidity or Vyper layout)."""
    key = _pad(base_slot) + _pad(holder) if vyper else _pad(holder) + _pad(base_slot)
    return "0x" + keccak(key).hex().removeprefix("0x")


class Simulator:
    def __init__(self, rpc):
        self.rpc = rpc
        self.balance_slots = {}      # token -> (base_slot, vyper) or None if undiscoverable

    # ── quote balance slot discovery ─────────────────────────────────────────
    def discover_balance_slot(self, token):
        if token in self.balance_slots:
            return self.balance_slots[token]
        probe = 123456789123456789
        # 0..120 covers upgradeable layouts (e.g. OZ ERC20Upgradeable after the 50-slot gaps -> slot 51).
        cands = [(i, False) for i in range(0, 121)] + [(i, True) for i in range(0, 20)] + \
                [(OZ5_ERC20_NAMESPACE, False)]
        calls = []
        for base, vy in cands:
            slot = mapping_slot(SIM_ADDR, base, vy)
            calls.append(("eth_call", [{"to": token, "data": SEL_BALANCE_OF + _pad(SIM_ADDR).hex()}, "latest",
                                       {token: {"stateDiff": {slot: "0x" + probe.to_bytes(32, "big").hex()}}}]))
        found = None
        try:
            res = self.rpc.batch(calls)
            for (base, vy), r in zip(cands, res):
                if isinstance(r, str) and len(r) >= 66 and int(r[2:66], 16) == probe:
                    found = (base, vy)
                    break
        except Exception as e:
            log.warning("balance slot discovery failed for %s: %s", token, e)
            return None
        self.balance_slots[token] = found
        return found

    def _overrides(self, quote, amount):
        ov = {SIM_ADDR: {"code": self._runtime(), "balance": hex(SIM_ETH_BALANCE)}}
        if quote != ZERO_ADDR:
            slot = self.discover_balance_slot(quote)
            if slot is None:
                return None
            ov[quote] = {"stateDiff": {mapping_slot(SIM_ADDR, slot[0], slot[1]):
                                       "0x" + (amount * 4).to_bytes(32, "big").hex()}}
        return ov

    @staticmethod
    def _runtime():
        from rhc_sim_bytecode import RUNTIME
        return RUNTIME

    # ── simulation ───────────────────────────────────────────────────────────
    def build_call(self, meta, amount_in, v2_fee_bps):
        """Returns (call_dict, overrides) or (None, reason)."""
        quote, token = meta.quote_token, meta.base_token
        if quote is None or token is None:
            return None, "SIM_UNSUPPORTED_POOL"
        ov = self._overrides(quote, amount_in)
        if ov is None:
            return None, "SIM_QUOTE_SLOT_UNKNOWN"
        if meta.kind == "v2":
            data = SEL_V2 + abi_encode(["address", "address", "address", "uint256", "uint256"],
                                       [meta.pool_id, quote, token, amount_in, v2_fee_bps]).hex()
            call = {"from": SIM_ADDR, "to": SIM_ADDR, "data": data}
        elif meta.kind == "v3":
            data = SEL_V3 + abi_encode(["address", "address", "address", "uint256"],
                                       [meta.pool_id, quote, token, amount_in]).hex()
            call = {"from": SIM_ADDR, "to": SIM_ADDR, "data": data}
        elif meta.kind == "v4":
            if meta.fee is None or meta.tick_spacing is None:
                return None, "SIM_V4_KEY_INCOMPLETE"
            key = (meta.token0, meta.token1, int(meta.fee), int(meta.tick_spacing), meta.hooks or ZERO_ADDR)
            data = SEL_V4 + abi_encode(["address", "(address,address,uint24,int24,address)", "bool", "uint256"],
                                       [meta.venue or cfg.RHC_V4_POOL_MANAGERS[0], key, meta.base_index == 1,
                                        amount_in]).hex()
            call = {"from": SIM_ADDR, "to": SIM_ADDR, "data": data,
                    "value": hex(amount_in) if quote == ZERO_ADDR else "0x0"}
        else:
            return None, "SIM_UNSUPPORTED_POOL"
        return (call, ov), None

    def run_sell(self, meta, tokens, v2_fee_bps=100):
        """Simulate selling `tokens` (base units) through the pool, as if we held them."""
        quote, token = meta.quote_token, meta.base_token
        if quote is None or token is None:
            return SellResult(status="SIM_UNSUPPORTED_POOL", tokens=tokens)
        slot = self.discover_balance_slot(token)
        if slot is None:
            return SellResult(status="SIM_TOKEN_SLOT_UNKNOWN", tokens=tokens)
        ov = {SIM_ADDR: {"code": self._runtime(), "balance": hex(SIM_ETH_BALANCE)},
              token: {"stateDiff": {mapping_slot(SIM_ADDR, slot[0], slot[1]): "0x" + tokens.to_bytes(32, "big").hex()}}}
        if meta.kind == "v2":
            data = SEL_SELL_V2 + abi_encode(["address", "address", "address", "uint256", "uint256"],
                                            [meta.pool_id, quote, token, tokens, v2_fee_bps]).hex()
        elif meta.kind == "v3":
            data = SEL_SELL_V3 + abi_encode(["address", "address", "address", "uint256"],
                                            [meta.pool_id, quote, token, tokens]).hex()
        elif meta.kind == "v4":
            if meta.fee is None or meta.tick_spacing is None:
                return SellResult(status="SIM_V4_KEY_INCOMPLETE", tokens=tokens)
            key = (meta.token0, meta.token1, int(meta.fee), int(meta.tick_spacing), meta.hooks or ZERO_ADDR)
            data = SEL_SELL_V4 + abi_encode(["address", "(address,address,uint24,int24,address)", "bool", "uint256"],
                                            [meta.venue or cfg.RHC_V4_POOL_MANAGERS[0], key, meta.base_index == 1,
                                             tokens]).hex()
        else:
            return SellResult(status="SIM_UNSUPPORTED_POOL", tokens=tokens)
        call = {"from": SIM_ADDR, "to": SIM_ADDR, "data": data, "gas": hex(cfg.RHC_SIM_GAS_LIMIT)}
        try:
            out = self.rpc.call("eth_call", [call, "latest", ov])
        except RpcError as e:
            return SellResult(status="SIM_CALL_REVERTED", tokens=tokens, error=e.message[:200])
        except Exception as e:
            return SellResult(status="SIM_RPC_ERROR", tokens=tokens, error=str(e)[:200])
        if not isinstance(out, str) or len(out) < 2 + 64 * 8:
            return SellResult(status="SIM_BAD_RESULT", tokens=tokens, error=str(out)[:100])
        return interpret_sell(list(abi_decode(["uint256[8]"], bytes.fromhex(out[2:]))[0]), tokens)

    def run(self, meta, amount_in, v2_fee_bps=100):
        built, reason = self.build_call(meta, amount_in, v2_fee_bps)
        if built is None:
            return SimResult(status=reason, amount_in=amount_in)
        call, ov = built
        call["gas"] = hex(cfg.RHC_SIM_GAS_LIMIT)
        try:
            out = self.rpc.call("eth_call", [call, "latest", ov])
        except RpcError as e:
            return SimResult(status="SIM_CALL_REVERTED", amount_in=amount_in, error=e.message[:200])
        except Exception as e:
            return SimResult(status="SIM_RPC_ERROR", amount_in=amount_in, error=str(e)[:200])
        if not isinstance(out, str) or len(out) < 2 + 64 * 8:
            return SimResult(status="SIM_BAD_RESULT", amount_in=amount_in, error=str(out)[:100])
        r = list(abi_decode(["uint256[8]"], bytes.fromhex(out[2:]))[0])
        return interpret(r, amount_in)
