"""Catalog of screening reason codes.

Every rejection and warning the screener records uses one of these codes, so rejected tokens stay
auditable and the UI can explain them. Severity defaults can be overridden in rhc_config:
  reject  -> token is rejected
  warn    -> recorded as a risk, not blocking
  info    -> context only
`permanent` codes are unlikely to clear by themselves (re-screened rarely); transient ones
(liquidity, age, activity, RPC errors) are re-screened after a short cooldown.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Reason:
    code: str
    category: str
    severity: str
    permanent: bool
    description: str


_R = [
    # pool / market
    Reason("QUOTE_UNSUPPORTED", "market", "reject", True, "Pool is not quoted in ETH, WETH or USDG"),
    Reason("VENUE_UNSUPPORTED", "market", "reject", True, "Pool type/factory is not decoded or not allow-listed"),
    Reason("TOO_NEW", "market", "reject", False, "Pool younger than the minimum age"),
    Reason("ILLIQUID", "market", "reject", False, "Liquidity below the minimum, or the pool returned nothing"),
    Reason("LIQ_UNKNOWN", "market", "warn", False, "USD liquidity unavailable from sources (impact still measured)"),
    Reason("LOW_ACTIVITY", "market", "reject", False, "Too few trades or traders in the last hour"),
    # simulation
    Reason("BUY_BLOCKED", "simulation", "reject", True, "A buy through the pool reverted (trading disabled, hook gate, or restriction)"),
    Reason("HONEYPOT", "simulation", "reject", True, "Buy succeeded but selling back reverted"),
    Reason("TAX_100", "simulation", "reject", True, "Pool sent tokens but none arrived (100% transfer tax)"),
    Reason("TAX_HIGH", "simulation", "reject", False, "Measured buy or sell tax above the limit"),
    Reason("COST_TOO_HIGH", "simulation", "reject", False, "Round-trip cost (fees + taxes + impact) above the limit"),
    Reason("IMPACT_TOO_HIGH", "simulation", "reject", False, "Price impact at the intended trade size above the limit"),
    Reason("SIM_UNAVAILABLE", "simulation", "reject", False, "Simulation could not run (unsupported pool or RPC error)"),
    # contract permissions
    Reason("MINTABLE", "contract", "reject", True, "Owner-callable mint function and an active owner"),
    Reason("BLACKLIST", "contract", "reject", True, "Blacklist/bot-blocking function and an active owner"),
    Reason("PAUSABLE", "contract", "reject", True, "Pause function and an active owner"),
    Reason("UPGRADEABLE", "contract", "reject", True, "Token is an upgradeable proxy: its code can change"),
    Reason("FEE_SETTER", "contract", "warn", False, "Owner can change fees/taxes (measured tax may change later)"),
    Reason("MAXTX_SETTER", "contract", "warn", False, "Owner can change max transaction/wallet limits"),
    Reason("TRADING_TOGGLE", "contract", "warn", False, "Owner can enable/disable trading"),
    Reason("OWNER_ACTIVE", "contract", "info", False, "Ownership not renounced"),
    Reason("NO_CODE", "contract", "reject", True, "Token address has no contract code"),
    # holders
    Reason("CONCENTRATED", "holders", "reject", False, "Top holder(s) control too much of the supply"),
    Reason("INSIDER_HEAVY", "holders", "reject", False, "Deployer/early recipients still hold too much of the supply"),
    Reason("HOLDERS_PARTIAL", "holders", "info", False, "Transfer history too large; holder stats are approximate"),
    Reason("FEW_HOLDERS", "holders", "warn", False, "Very few wallets hold the token outside the pool (trading is in-and-out)"),
    # flow quality
    Reason("WASH_SUSPECT", "flow", "reject", False, "Volume dominated by few wallets trading back and forth"),
    Reason("FRESH_WALLET_HEAVY", "flow", "warn", False, "Most volume comes from brand-new wallets (possible sybil activity)"),
    Reason("BUNDLED_BUYS", "flow", "warn", False, "Several distinct wallets bought in the same block repeatedly"),
    # liquidity control
    Reason("RUG_PULLED", "liquidity", "reject", True, "Pool has no liquidity left and most added liquidity was withdrawn"),
    Reason("LP_NOT_BURNED", "liquidity", "warn", False, "v2 LP tokens are mostly not burned (liquidity can be withdrawn)"),
    Reason("RECENT_LP_REMOVAL", "liquidity", "warn", False, "Liquidity was removed from this pool recently"),
    Reason("LP_LOCK_UNKNOWN", "liquidity", "info", False, "LP lock status cannot be determined for this pool type"),
]

REASONS = {r.code: r for r in _R}


def severity(code, overrides=None):
    if overrides and code in overrides:
        return overrides[code]
    r = REASONS.get(code)
    return r.severity if r else "warn"


def is_permanent(code):
    r = REASONS.get(code)
    return bool(r and r.permanent)
