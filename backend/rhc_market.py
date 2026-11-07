"""Pure market normalisation: pool classification, USD quoting, swap -> trade."""
from dataclasses import dataclass, field
from typing import Optional

from rhc_decoders import price1_per_0_from_reserves, price1_per_0_from_sqrt


@dataclass
class PoolMeta:
    pool_id: str
    kind: str
    token0: str
    token1: str
    dec0: Optional[int] = None
    dec1: Optional[int] = None
    venue: Optional[str] = None
    hooks: Optional[str] = None
    fee: Optional[int] = None
    base_index: Optional[int] = None    # 0 or 1: which token is the traded (base) asset
    quote_token: Optional[str] = None
    quote_class: Optional[str] = None   # "stable" | "eth"
    supported: bool = False
    reason: Optional[str] = None
    pk: Optional[int] = None
    tracked: bool = False

    @property
    def base_token(self):
        if self.base_index is None:
            return None
        return self.token0 if self.base_index == 0 else self.token1


def classify_pool(token0, token1, stable_quotes, eth_quotes):
    """Choose base/quote. Returns (base_index, quote_token, quote_class, reason).

    Preference: stable quote (USDG) > ETH-like quote (native ETH / WETH).
    """
    t0, t1 = token0.lower(), token1.lower()
    s0, s1 = t0 in stable_quotes, t1 in stable_quotes
    e0, e1 = t0 in eth_quotes, t1 in eth_quotes
    if s0 and s1:
        return None, None, None, "stable_stable"
    if s1:
        return 0, t1, "stable", None
    if s0:
        return 1, t0, "stable", None
    if e0 and e1:
        return None, None, None, "wrap_pair"
    if e1:
        return 0, t1, "eth", None
    if e0:
        return 1, t0, "eth", None
    return None, None, None, "no_supported_quote"


class QuotePricer:
    """USD value of quote assets, updated point-in-time from the reference pool."""

    def __init__(self, stable_usd=1.0):
        self.stable_usd = stable_usd
        self.eth_usd = None
        self.eth_usd_ts = None

    def set_eth_usd(self, price, ts):
        if price and price > 0:
            self.eth_usd = float(price)
            self.eth_usd_ts = ts

    def usd(self, quote_class):
        if quote_class == "stable":
            return self.stable_usd
        if quote_class == "eth":
            return self.eth_usd
        return None


@dataclass
class Trade:
    pool_pk: int
    pool_id: str
    ts: int
    block: int
    tx: str
    log_index: int
    side: str            # buy (user received base) | sell
    base_amt: float
    quote_amt: float
    price_q: float       # quote per base
    price_usd: Optional[float]
    usd: Optional[float]
    trader: Optional[str] = None
    liq: Optional[float] = None        # v3/v4 active liquidity after swap
    liq_usd: Optional[float] = None    # v2 depth (2 x quote reserve in USD)
    extra: dict = field(default_factory=dict)


def swap_to_trade(meta, ev, ts, quote_usd, reserves=None):
    """Convert a decoded SwapEv into a Trade from the base token's perspective.

    reserves: (r0, r1) post-swap reserves for v2 pools (from the preceding Sync).
    Returns None when amounts/decimals are unusable.
    """
    if meta.base_index is None or meta.dec0 is None or meta.dec1 is None:
        return None
    b = meta.base_index
    q = 1 - b
    decs = (meta.dec0, meta.dec1)
    deltas = (ev.d0, ev.d1)
    base_delta = deltas[b] / (10 ** decs[b])
    quote_delta = deltas[q] / (10 ** decs[q])
    if base_delta == 0 or quote_delta == 0:
        return None
    # A real swap moves the two tokens in opposite directions for the user.
    if (base_delta > 0) == (quote_delta > 0):
        return None
    side = "buy" if base_delta > 0 else "sell"

    p10 = None   # token0 price in token1
    if ev.sqrt_price_x96:
        p10 = price1_per_0_from_sqrt(ev.sqrt_price_x96, meta.dec0, meta.dec1)
    elif reserves:
        p10 = price1_per_0_from_reserves(reserves[0], reserves[1], meta.dec0, meta.dec1)
    if p10:
        price_q = p10 if b == 0 else 1.0 / p10
    else:
        price_q = abs(quote_delta) / abs(base_delta)

    usd = abs(quote_delta) * quote_usd if quote_usd else None
    price_usd = price_q * quote_usd if quote_usd else None

    liq = float(ev.liquidity) if ev.liquidity is not None else None
    liq_usd = None
    if reserves and quote_usd:
        liq_usd = 2.0 * (reserves[q] / (10 ** decs[q])) * quote_usd

    return Trade(
        pool_pk=meta.pk, pool_id=meta.pool_id, ts=int(ts), block=ev.ref.block, tx=ev.ref.tx,
        log_index=ev.ref.log_index, side=side, base_amt=abs(base_delta), quote_amt=abs(quote_delta),
        price_q=price_q, price_usd=price_usd, usd=usd, liq=liq, liq_usd=liq_usd,
    )
