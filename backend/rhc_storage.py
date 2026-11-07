"""Storage guard for the free-tier RHC database.

Policy (all thresholds in rhc_config):
  * every check: apply normal retention (1m candles, liquidity events, snapshots, raw swaps)
    and roll 5m candles older than RHC_RETAIN_5M_DAYS up to 15m;
  * >= PRUNE_AT %: aggressive retention (halved windows);
  * >= PAUSE_AT %: pause all RHC writes, VACUUM FULL RHC tables, resume once < RESUME_BELOW %.
"""
import logging
import time

import rhc_config as cfg
from rhc_util import floor_to

log = logging.getLogger("rhc.storage")


def decide(size_mb, budget_mb, paused, prune_at, pause_at, resume_below):
    """Pure decision. Returns (level, paused_after): level in normal|prune|critical."""
    pct = 100.0 * size_mb / budget_mb if budget_mb > 0 else 100.0
    if pct >= pause_at:
        return "critical", True
    if paused and pct >= resume_below:
        return "critical", True
    if pct >= prune_at:
        return "prune", False
    return "normal", False


class StorageGuard:
    def __init__(self, store, db, clock=time.time):
        self.store = store
        self.db = db
        self.clock = clock
        self.paused = False
        self.last = {}

    def check(self):
        now = int(self.clock())
        size = self.db.db_size_mb()
        level, paused = decide(size, cfg.RHC_DB_BUDGET_MB, self.paused, cfg.RHC_PRUNE_AT_PCT,
                               cfg.RHC_PAUSE_AT_PCT, cfg.RHC_RESUME_BELOW_PCT)
        factor = 1.0 if level == "normal" else 0.5
        pruned = self.store.prune(
            now,
            retain_1m_h=max(6, int(cfg.RHC_RETAIN_1M_HOURS * factor)),
            retain_liq_d=max(1, int(cfg.RHC_RETAIN_LIQ_DAYS * factor)),
            retain_snap_d=max(1, int(cfg.RHC_RETAIN_SNAPSHOT_DAYS * factor)),
            retain_swap_h=max(6, int(cfg.RHC_RETAIN_SWAP_HOURS * factor)),
        )
        days_5m = cfg.RHC_RETAIN_5M_DAYS if level == "normal" else max(3, cfg.RHC_RETAIN_5M_DAYS // 2)
        rolled = self.store.rollup_5m_to_15m(floor_to(now - days_5m * 86400, 900))
        pruned["screens"] = self.store.prune_screens(now, max(1, int(cfg.RHC_RETAIN_SCREEN_DAYS * factor)))
        pruned["dead_pools"] = self.store.prune_dead_pools(now, cfg.RHC_PRUNE_DEAD_POOLS_DAYS)
        if level == "critical":
            try:
                from rhc_models import RHC_TABLES
                self.db.vacuum_full(RHC_TABLES)
            except Exception as e:
                log.warning("vacuum full failed: %s", e)
            size = self.db.db_size_mb()
            level, paused = decide(size, cfg.RHC_DB_BUDGET_MB, True, cfg.RHC_PRUNE_AT_PCT,
                                   cfg.RHC_PAUSE_AT_PCT, cfg.RHC_RESUME_BELOW_PCT)
        if paused != self.paused:
            log.warning("storage guard: writes %s (%.1f MB of %.0f MB budget)",
                        "PAUSED" if paused else "resumed", size, cfg.RHC_DB_BUDGET_MB)
        self.paused = paused
        self.last = {"ts": now, "size_mb": round(size, 2), "budget_mb": cfg.RHC_DB_BUDGET_MB,
                     "pct": round(100.0 * size / cfg.RHC_DB_BUDGET_MB, 1), "level": level, "paused": paused,
                     "pruned": pruned, "rolled_5m_rows": rolled}
        try:
            self.store.kv_set("storage_guard", self.last)
        except Exception:
            pass
        return self.last
