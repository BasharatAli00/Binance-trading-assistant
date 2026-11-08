# Robinhood Chain System: Discovery & Screening (Phase 2)

Paper mode only. Nothing in this phase signs, sends or executes a transaction.

## Pipeline
Every `RHC_SCREEN_CYCLE_S` (default 30 s), while the indexer is live and holds the writer lease, the screener runs three steps.

1. **Discover.**
   - It ranks active supported pools from the indexer's rolling activity.
   - A pool becomes a **candidate** when it has at least `RHC_DISCOVER_MIN_VOL_1H` of volume and `RHC_DISCOVER_MIN_SWAPS_1H` swaps in the last hour, **and** at least one discovery reason applies:
     - `new_pool`: created within `RHC_DISCOVER_NEW_POOL_H`;
     - `volume_surge`: last-15-minute volume at least `RHC_DISCOVER_SURGE_X` × the prior-45-minute pace;
     - `top_volume`: among the `RHC_DISCOVER_TOP_N` busiest pools;
     - `liquidity_add`: a priced liquidity add of at least `RHC_LIQ_ADD_MIN_USD` in the last hour.
   - Each candidate gets a score: log₁₀(1-hour volume) plus bonuses for new, surge and liquidity-add.
2. **Screen** up to `RHC_SCREEN_PER_CYCLE` due entries. Candidates go first, then by score. Checks run **cheapest first**, and once a check rejects the pool the remaining expensive checks are skipped. Every executed check is recorded with its metrics in `rhc_screen`, so rejections stay auditable.
3. **Maintain the watchlist.**
   - Pools with no activity for `RHC_WATCH_EXPIRE_H` expire.
   - Pools in the `watch` state are handed to the indexer as always-tracked (up to `RHC_WATCH_MAX`), so Phase 3 has their candles.

Each pool's watchlist state (`rhc_watchlist`) is one of:

| State | Meaning | Next screening |
|---|---|---|
| `candidate` | Discovered, not yet screened | Next cycle |
| `watch` | Passed every hard filter | Again after `RHC_RESCREEN_WATCH_MIN`, because taxes, owners and liquidity can change |
| `rejected` | At least one reject code | After `RHC_RESCREEN_TRANSIENT_MIN` (transient reasons) or `RHC_RESCREEN_PERMANENT_H` (permanent ones) |
| `expired` | No activity | Revived as a candidate when it trades again |

## Checks
| # | Check | How | Codes |
|---|---|---|---|
| 1 | Market | Pool classification, age from the creation event | `QUOTE_UNSUPPORTED` `VENUE_UNSUPPORTED` `TOO_NEW` |
| 2 | Activity | Indexer's 1-hour swap count | `LOW_ACTIVITY` |
| 3 | Liquidity | v2: live reserves; v3/v4: DexScreener | `ILLIQUID` `LIQ_UNKNOWN` |
| 4 | **Round-trip simulation** | `eth_call` with state overrides runs `contracts/RhcSimulator.sol`: buy at `RHC_SCREEN_TRADE_USD` through the pool's own contract, then sell everything back. A `RHC_SCREEN_PROBE_USD` probe measures price impact. | `BUY_BLOCKED` `HONEYPOT` `TAX_100` `TAX_HIGH` `COST_TOO_HIGH` `IMPACT_TOO_HIGH` `ILLIQUID` `RUG_PULLED` `SIM_UNAVAILABLE` |
| 5 | Contract permissions | Bytecode selector scan (mint, blacklist, pause, fee/limit setters, trading toggles, upgrades), EIP-1967/1167 proxy detection, `owner()` | `MINTABLE` `BLACKLIST` `PAUSABLE` `UPGRADEABLE` `FEE_SETTER` `MAXTX_SETTER` `TRADING_TOGGLE` `OWNER_ACTIVE` `NO_CODE` |
| 6 | Holders | Replays the token's `Transfer` logs, then re-reads the top balances with `balanceOf` | `CONCENTRATED` `INSIDER_HEAVY` `FEW_HOLDERS` `HOLDERS_PARTIAL` |
| 7 | Flow quality | Last ~1 hour of the pool's swaps, real senders (`tx.from`), sender nonces | `LOW_ACTIVITY` `WASH_SUSPECT` `FRESH_WALLET_HEAVY` `BUNDLED_BUYS` |
| 8 | LP control | v2: share of LP tokens burned; all pools: on-chain liquidity add/remove history (~2 h) | `LP_NOT_BURNED` `RECENT_LP_REMOVAL` `LP_LOCK_UNKNOWN` |

`GET /api/rhc/reasons` returns the full catalog: category, effective severity, whether the code is permanent, and a description. To change a severity without editing code, set `RHC_SEVERITY_OVERRIDES`, for example `WASH_SUSPECT=warn,LP_NOT_BURNED=reject`.

### Round-trip simulation details
- **What it uses:**
  - The simulator is never deployed. It's injected at a throw-away address for one `eth_call`, and the call's effects are discarded.
  - Quote assets are supplied by overriding balances: native ETH via the account balance; WETH (balance slot **51**, an upgradeable layout) and USDG (slot **1**) through their storage mappings. Slots are discovered automatically and verified with `balanceOf`.
- **What it measures:**
  - buy tax = 1 − received ÷ sent by the pool;
  - sell tax = 1 − arrived at the pool ÷ sent;
  - round-trip cost = 1 − quote back ÷ quote in (fees + taxes + impact, both ways);
  - price impact = the drop in tokens-per-quote between the probe and the full size.
- **Supported pools:**
  - Uniswap v2-style pairs, with the fee per factory in `RHC_V2_FEE_BPS`;
  - v3-style pools, including the Pancake and Algebra callback names;
  - Uniswap v4 through the PoolManager, including hooked pools (a hook that rejects our caller shows up as `BUY_BLOCKED`).
- **Verified live (2026-11-07):**
  - WETH/USDG 0.01% → 0.02% round trip and WETH/USDG 0.05% → 0.10%: exact.
  - A 5%/5% tax token was detected as 5% buy and 5% sell tax.
  - Three pools whose liquidity was withdrawn minutes after launch were flagged as `RUG_PULLED`.

## Known limits (be careful with conclusions)
- **Point in time only.** A token that passes can still change: an owner with `FEE_SETTER` or `TRADING_TOGGLE` powers can turn a passing token into a honeypot later. That's why watch-state pools are re-screened every 30 minutes, and why those powers are recorded as warnings.
- **Selector scanning can miss things.** Renamed or obfuscated functions, and restrictions hidden inside `transfer()`, aren't visible to it. The simulation covers the behaviour, but only at the moment and size simulated.
- **Our caller is generic.** Tokens or hooks that whitelist specific routers may revert for the simulator but not for a real router, which over-rejects. Tokens that only block sells above a size or after a delay may pass.
- **LP locks for v3/v4 aren't checked:** position NFTs and locker contracts aren't analysed, so these pools get `LP_LOCK_UNKNOWN`. Withdrawals in the last ~2 hours are detected.
- **Holder statistics count addresses, not people.** Clustering wallets by funding source isn't possible from logs (native ETH transfers emit no events), so one person controlling many wallets looks dispersed. `FRESH_WALLET_HEAVY` and `BUNDLED_BUYS` are partial proxies.
- **Liquidity for v3/v4 comes from DexScreener** and is missing for pools it hasn't indexed (`LIQ_UNKNOWN`). The simulated price impact at our trade size is the binding liquidity test.
