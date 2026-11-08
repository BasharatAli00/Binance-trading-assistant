"""Pure decoders: raw eth_getLogs entries -> typed DEX events.

Swap amounts are normalised to the USER's perspective:
    d0 / d1 > 0  -> user RECEIVED that token
    d0 / d1 < 0  -> user PAID that token
Conventions verified on live chain data (2026-11-07):
    * Uniswap v3 Swap: amount > 0 means the pool received it (user paid)  -> d = -amount
    * Uniswap v4 Swap: amount < 0 means the user paid                      -> d = amount
    * Uniswap v2 Swap: amountIn paid, amountOut received                    -> d = out - in

All functions are pure and never raise on malformed input (they return None).
"""
from dataclasses import dataclass
from typing import Optional

# topic0 hashes (keccak256 of canonical signatures, verified)
TOPICS = {
    "v2_pair_created": "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9",
    "v2_swap": "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822",
    "v2_sync": "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1",
    "v2_mint": "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f",
    "v2_burn": "0xdccd412f0b1252819cb1fd330b93224ca42612892bb3f4f789976e6d81936496",
    "v3_pool_created": "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118",
    "v3_swap": "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67",
    "v3_mint": "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde",
    "v3_burn": "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c",
    "v4_initialize": "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438",
    "v4_swap": "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f",
    "v4_modify_liquidity": "0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec",
}
TOPIC_TO_NAME = {v: k for k, v in TOPICS.items()}
ALL_TOPICS = list(TOPICS.values())
V4_TOPICS = {TOPICS["v4_initialize"], TOPICS["v4_swap"], TOPICS["v4_modify_liquidity"]}

ZERO_ADDR = "0x" + "0" * 40
Q96 = 2 ** 96


# ── ABI word helpers ──────────────────────────────────────────────────────────
def words(data):
    d = data[2:] if data.startswith("0x") else data
    return [d[i:i + 64] for i in range(0, len(d), 64)]


def u256(w):
    return int(w, 16)


def s256(w):
    v = int(w, 16)
    return v - (1 << 256) if v >= (1 << 255) else v


def addr(w):
    return ("0x" + w[-40:]).lower()


def hexint(x):
    return int(x, 16) if isinstance(x, str) else int(x)


def clean_text(s):
    """Remove NUL/control characters (Postgres rejects NUL in text) and trim."""
    if s is None:
        return None
    s = "".join(ch for ch in s if ch >= " " and ch != "\x7f")
    return s.strip() or None


def decode_abi_string(result_hex):
    """Decode an eth_call result that is either an ABI string or bytes32. Never returns NULs."""
    if not result_hex or result_hex == "0x":
        return None
    try:
        b = bytes.fromhex(result_hex[2:])
        if len(b) >= 64:
            off = int.from_bytes(b[0:32], "big")
            if off + 32 <= len(b):
                ln = int.from_bytes(b[off:off + 32], "big")
                if off + 32 + ln <= len(b) and ln <= 256:
                    return clean_text(b[off + 32:off + 32 + ln].decode("utf-8", "replace"))
        return clean_text(b[:32].decode("utf-8", "replace"))
    except Exception:
        return None


# ── Event types ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LogRef:
    block: int
    tx: str
    log_index: int
    address: str


@dataclass(frozen=True)
class PoolCreatedEv:
    kind: str            # v2 | v3 | v4
    pool_id: str         # address (v2/v3) or bytes32 id (v4)
    venue: str           # factory (v2/v3) or PoolManager (v4)
    token0: str
    token1: str
    fee: Optional[int]
    tick_spacing: Optional[int]
    hooks: Optional[str]
    sqrt_price_x96: Optional[int]
    ref: LogRef


@dataclass(frozen=True)
class SwapEv:
    kind: str
    pool_id: str
    d0: int              # user perspective raw amount of token0
    d1: int
    sqrt_price_x96: Optional[int]
    liquidity: Optional[int]
    tick: Optional[int]
    fee: Optional[int]
    ref: LogRef


@dataclass(frozen=True)
class SyncEv:
    pool_id: str
    reserve0: int
    reserve1: int
    ref: LogRef


@dataclass(frozen=True)
class LiquidityEv:
    kind: str
    pool_id: str
    action: str          # add | remove
    amount0: Optional[int]
    amount1: Optional[int]
    liquidity_delta: Optional[int]
    tick_lower: Optional[int]
    tick_upper: Optional[int]
    ref: LogRef


def _ref(log):
    return LogRef(
        block=hexint(log["blockNumber"]),
        tx=log["transactionHash"].lower(),
        log_index=hexint(log["logIndex"]),
        address=log["address"].lower(),
    )


def decode_log(log, v4_managers=frozenset()):
    """Decode one raw log. Returns an event dataclass or None (unknown/malformed/removed)."""
    try:
        if log.get("removed"):
            return None
        topics = log.get("topics") or []
        if not topics:
            return None
        name = TOPIC_TO_NAME.get(topics[0].lower())
        if name is None:
            return None
        address = log["address"].lower()
        if topics[0].lower() in V4_TOPICS and address not in v4_managers:
            return None  # same signature from an unknown contract -> ignore
        w = words(log.get("data", "0x"))
        ref = _ref(log)

        if name == "v2_pair_created":
            return PoolCreatedEv("v2", addr(w[0]), address, addr(topics[1]), addr(topics[2]),
                                 None, None, None, None, ref)
        if name == "v3_pool_created":
            return PoolCreatedEv("v3", addr(w[1]), address, addr(topics[1]), addr(topics[2]),
                                 u256(topics[3][2:]), s256(w[0]), None, None, ref)
        if name == "v4_initialize":
            return PoolCreatedEv("v4", topics[1].lower(), address, addr(topics[2]), addr(topics[3]),
                                 u256(w[0]), s256(w[1]), addr(w[2]), u256(w[3]), ref)

        if name == "v2_swap":
            a0_in, a1_in, a0_out, a1_out = (u256(x) for x in w[:4])
            return SwapEv("v2", address, a0_out - a0_in, a1_out - a1_in, None, None, None, None, ref)
        if name == "v3_swap":
            return SwapEv("v3", address, -s256(w[0]), -s256(w[1]), u256(w[2]), u256(w[3]), s256(w[4]),
                          None, ref)
        if name == "v4_swap":
            return SwapEv("v4", topics[1].lower(), s256(w[0]), s256(w[1]), u256(w[2]), u256(w[3]),
                          s256(w[4]), u256(w[5]), ref)

        if name == "v2_sync":
            return SyncEv(address, u256(w[0]), u256(w[1]), ref)

        if name == "v2_mint":
            return LiquidityEv("v2", address, "add", u256(w[0]), u256(w[1]), None, None, None, ref)
        if name == "v2_burn":
            return LiquidityEv("v2", address, "remove", u256(w[0]), u256(w[1]), None, None, None, ref)
        if name == "v3_mint":
            return LiquidityEv("v3", address, "add", u256(w[2]), u256(w[3]), u256(w[1]),
                               s256(topics[2][2:]), s256(topics[3][2:]), ref)
        if name == "v3_burn":
            return LiquidityEv("v3", address, "remove", u256(w[1]), u256(w[2]), -u256(w[0]),
                               s256(topics[2][2:]), s256(topics[3][2:]), ref)
        if name == "v4_modify_liquidity":
            delta = s256(w[2])
            return LiquidityEv("v4", topics[1].lower(), "add" if delta >= 0 else "remove", None, None, delta,
                               s256(w[0]), s256(w[1]), ref)
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    return None


# ── Price math ────────────────────────────────────────────────────────────────
def price1_per_0_from_sqrt(sqrt_price_x96, dec0, dec1):
    """Human price of token0 expressed in token1 units."""
    if not sqrt_price_x96:
        return None
    r = sqrt_price_x96 / Q96
    return (r * r) * (10 ** (dec0 - dec1))


def price1_per_0_from_reserves(r0, r1, dec0, dec1):
    if not r0 or not r1:
        return None
    return (r1 / 10 ** dec1) / (r0 / 10 ** dec0)
