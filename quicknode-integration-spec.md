# QuickNode Redundant Feed Integration — Implementation Spec

**Audience:** Coding agent/developer implementing this change.
**System:** Smart-Money Copy Trade (Strategy #4) — includes a LIVE trading portfolio that executes real on-chain swaps with real money.
**Priority:** Safety and non-disruption of the existing pipeline is more important than speed of delivery. Read this entire document before writing any code.

---

## 0. Prime Directive

This system has a live-money execution path (`copytrade_live.py`). Any bug introduced here can cause **real financial loss** — duplicate trades, missed exits, or corrupted position state. This task is additive infrastructure work, not a rewrite. If at any point a requirement below is ambiguous, choose the more conservative interpretation (i.e., the one less likely to touch live trading logic) and flag it rather than guessing.

**Do not modify `copytrade_strategy.py`, `copytrade_live.py`, `copytrade_engine.py`, or the entry/exit decision logic in this task.** This task is scoped strictly to the data-ingestion layer (the part that receives and normalizes wallet trade events before they ever reach signal/strategy logic).

---

## 1. Goal

Currently the system has a single point of failure: Helius is the only source of wallet trade events. This task adds QuickNode Streams as a second, independent, simultaneous data source watching the same wallets, so that:

1. Both Helius and QuickNode send trade events to the system **at the same time**, continuously (not one-as-fallback-only — both are always active).
2. Duplicate events (the same on-chain transaction reported by both sources) are detected and only processed once.
3. Each source is monitored independently with a heartbeat. If one source goes silent while the other is healthy, the system logs/alerts clearly which source failed, and continues operating normally on the surviving source.
4. If a source is down, the trading pipeline is not blocked — it simply relies on whichever source is still delivering events.

---

## 2. Non-Negotiable Constraints

- **No changes to signal consensus logic, entry logic, exit logic, or live execution logic.** This task ends at producing a clean, deduplicated, normalized event — same shape/schema as what `copytrade_helius.py` currently emits. From the perspective of `copytrade_signal.py` and everything downstream, nothing should change.
- **Feature-flagged.** The QuickNode feed must be controlled by a config flag (e.g., `ENABLE_QUICKNODE_FEED = False` by default) in `copytrade_config.py`. It must be possible to disable QuickNode instantly by flipping this flag back to `False`, with zero effect on Helius operation.
- **No behavior change when the flag is off.** With `ENABLE_QUICKNODE_FEED = False`, the system must behave byte-for-byte identically to the current production system.
- **Additive files, not rewritten files.** Create new files (e.g., `copytrade_quicknode.py`) mirroring the structure of `copytrade_helius.py`. Do not refactor or restructure `copytrade_helius.py` itself beyond the minimal hook needed to merge the two event streams — see Section 4.
- **Never let live trading depend on a code path that hasn't been tested in shadow mode first.** See Section 6 (Rollout Plan). Live money must not touch this new code until it has run in a non-trading "shadow" mode for a defined observation period.
- **No silent failures.** Every failure mode (webhook registration failure, parse failure, heartbeat timeout) must log clearly and, where currently supported, trigger the existing alert mechanism. Do not swallow exceptions.
- **No duplicate trades.** This is the single most important correctness requirement. If deduplication logic has any bug, the system must fail closed (i.e., prefer to under-trade / skip a duplicate-looking event) rather than fail open (risk double-executing a trade). When in doubt about whether an event is a duplicate, treat it as a duplicate and drop it, logging the ambiguous case for review.

---

## 3. Architecture

```
                ┌─────────────────┐
                │  Helius Webhook  │──┐
                └─────────────────┘  │
                                     ▼
                             ┌───────────────┐        ┌──────────────────┐
                             │  Event Merge  │──────▶│ copytrade_signal │──▶ (unchanged downstream)
                             │  + Dedup      │        └──────────────────┘
                             ┌───────────────┐
                ┌─────────────────┐  │
                │ QuickNode Stream │──┘
                └─────────────────┘

     Each source also feeds an independent heartbeat monitor.
```

### New module: `copytrade_quicknode.py`
Mirrors the responsibilities of `copytrade_helius.py`:
- Registers/updates a QuickNode Stream (their webhook-equivalent product) subscribed to the same watched-wallet list used by Helius (read from the same source of truth — do not maintain a second, possibly-divergent wallet list).
- Exposes a webhook receiver endpoint (separate URL path from the Helius one, e.g. `/webhook/quicknode` vs `/webhook/helius`).
- Parses QuickNode's payload format into the **exact same normalized event schema** Helius events currently use before hitting `copytrade_signal.py`. If schemas differ, write an explicit mapping function with unit tests — do not assume field names line up.

### New/updated module: event merge + dedup layer
This can live in a new small module (e.g., `copytrade_event_merge.py`) or as a thin function both webhook receivers call before forwarding to `copytrade_signal.py`. Responsibilities:
- Compute a dedup key per incoming event — the on-chain transaction signature is the natural key (it's unique per transaction regardless of which source reported it).
- Maintain a short-lived cache (e.g., last 10 minutes of transaction signatures) — in-memory with TTL, or existing DB/cache infra if already present. Reuse existing infra rather than introducing a new dependency if one already exists in the project.
- If an incoming event's signature is already in the cache → drop it, log at debug level (`"duplicate event from <source>, already processed via <original_source>"`).
- If not in the cache → add it, forward to `copytrade_signal.py` unchanged.
- This is a race: both sources may arrive within milliseconds of each other. Use a lock or atomic check-and-set on the cache to avoid a race where both slip through simultaneously.

### Heartbeat monitor (per source)
- Track `last_event_received_at` independently for Helius and for QuickNode.
- Background check (reuse the existing loop cadence in `copytrade_loop.py` if there's already a periodic task runner) — if a source's `last_event_received_at` exceeds a configurable threshold (e.g., `SOURCE_SILENT_THRESHOLD_SECONDS`, default suggestion: 600s, tune based on your wallets' actual trade frequency), log a clear warning identifying which source went silent, and fire the existing alert mechanism if one exists in the codebase.
- **Do not pause new trade entries when only one source is silent and the other is healthy** — that's the entire point of redundancy. Only escalate to "pause new entries" behavior if **both** sources go silent simultaneously (this is the true "flying blind" case). If a "pause entries" mechanism doesn't already exist, do not build a new one as part of this task — just log/alert loudly and stop here; flag it as a follow-up.

---

## 4. Minimal touch point in existing files

The only change to `copytrade_helius.py` (or wherever the current webhook receiver lives) should be:
1. Route its parsed, normalized event through the new merge/dedup function before it currently gets forwarded to `copytrade_signal.py`.
2. Update its `last_event_received_at` heartbeat variable.

That's it. If implementing this requires touching more than a handful of lines in `copytrade_helius.py`, stop and reconsider the design — the goal is a parallel addition, not a refactor.

---

## 5. Config additions (`copytrade_config.py`)

```python
ENABLE_QUICKNODE_FEED = False          # master switch, default off
QUICKNODE_WEBHOOK_URL = ""             # set once registered
QUICKNODE_API_KEY = ""                 # from env var, never hardcoded
SOURCE_SILENT_THRESHOLD_SECONDS = 600  # tune based on observed wallet activity
DEDUP_CACHE_TTL_SECONDS = 600
```
Load API keys from environment variables / existing secrets mechanism — do not commit keys to the repo.

---

## 6. Rollout Plan (mandatory, do not skip)

1. **Shadow mode first.** With `ENABLE_QUICKNODE_FEED = True`, run QuickNode's events through parsing + dedup + heartbeat, but log everything without allowing QuickNode-sourced events to reach the paper OR live portfolio yet (e.g., a temporary `QUICKNODE_SHADOW_ONLY = True` sub-flag that forwards events to a logger instead of `copytrade_signal.py`). Confirm for several days that:
   - QuickNode events are parsed correctly.
   - Dedup correctly identifies the same transaction reported by both sources.
   - No parse errors or schema mismatches occur.
2. **Paper portfolio only.** Once shadow mode looks clean, allow merged events (Helius + QuickNode, deduped) to flow into the paper/simulated portfolio only. Compare paper trading behavior before/after — position count, entry timing, any anomalies.
3. **Live portfolio.** Only after the above two stages have run cleanly should merged events be allowed to influence the live trading portfolio. This should be a deliberate, manual config change, not automatic.
4. **Rollback:** at any stage, setting `ENABLE_QUICKNODE_FEED = False` must instantly and fully revert to Helius-only behavior with no residual effects (no stuck state, no partial dedup cache issues).

---

## 7. Testing Requirements

- Unit tests for the QuickNode payload → normalized event mapping function, covering at least: a buy event, a sell event, and a malformed/unexpected payload (should fail loudly, not silently drop or crash the receiver).
- Unit tests for the dedup function: same transaction signature arriving twice → second is dropped; two different signatures → both pass; concurrent/simultaneous arrival (simulate the race) → still only one passes.
- A manual test plan entry confirming: disabling the flag mid-run cleanly stops QuickNode processing without affecting Helius.

---

## 8. Explicit "Do Not" List

- Do NOT modify stop-loss, take-profit, trailing-stop, or time-exit logic.
- Do NOT modify the Jupiter route-check/build-tx execution flow.
- Do NOT change the watched-wallet source-of-truth table/query — both feeds must read the same wallet list.
- Do NOT let a QuickNode parsing bug crash the Helius receiver (they must be isolated — a failure in one path must not take down the other).
- Do NOT let live trades be influenced by QuickNode-sourced events before shadow mode and paper-mode validation (Section 6) are complete.
- Do NOT hardcode API keys or webhook secrets in source files.
- Do NOT remove or weaken any existing Helius functionality as part of this change.

---

## 9. Definition of Done

- [ ] `copytrade_quicknode.py` created, registers QuickNode Stream on the same wallet list as Helius.
- [ ] Normalized event schema matches existing Helius event schema exactly.
- [ ] Dedup layer implemented and unit-tested, fails closed on ambiguity.
- [ ] Per-source heartbeat implemented; silent-source warning logs/alerts correctly.
- [ ] Feature flag fully gates the new behavior; flag-off state is provably identical to current production.
- [ ] Shadow mode run for an observation period with no errors before touching paper or live portfolios.
- [ ] Rollback tested and confirmed instantaneous.
