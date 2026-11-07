"""Lifecycle for the RHC system inside (or alongside) the FastAPI backend.

Safety contract with main.py:
  * start_safe()/stop_safe() never raise and return immediately.
  * Nothing runs unless RHC_ENABLED=true AND RHC_DATABASE_URL is set.
  * All database and network work happens on background daemon threads, so a
    slow or unreachable RHC database can never delay or break app startup.
"""
import logging
import os
import threading
import time
from datetime import datetime

import rhc_config as cfg

log = logging.getLogger("rhc.service")

_state = {"status": "not_started", "error": None, "started_at": None, "lock_held": False}
_threads = []
_stop = threading.Event()
_components = {}


def build_components():
    """Construct store, rpc client and registry (no I/O)."""
    from rhc_registry import Registry
    from rhc_rpc import RpcClient
    from rhc_store import Store
    store = Store()
    rpc = RpcClient(cfg.RHC_RPC_URLS, timeout=cfg.RHC_RPC_TIMEOUT_S, max_rps=cfg.RHC_RPC_MAX_RPS,
                    retries=cfg.RHC_RPC_MAX_RETRIES, batch_size=cfg.RHC_RPC_BATCH_SIZE,
                    max_items_per_s=cfg.RHC_RPC_MAX_ITEMS_PER_S)
    return store, rpc, Registry(rpc, store)


def _main():
    import rhc_db
    from rhc_indexer import Indexer
    from rhc_sources import SourceHub
    from rhc_storage import StorageGuard

    backoff = 5
    while not _stop.is_set():
        try:
            _state["status"] = "initializing_db"
            rhc_db.init_schema()
            break
        except Exception as e:
            _state.update(status="db_unavailable", error=f"{type(e).__name__}: {str(e)[:200]}")
            log.warning("RHC database unavailable (retry in %ss): %s", backoff, e)
            _stop.wait(backoff)
            backoff = min(backoff * 2, 300)
    if _stop.is_set():
        return

    lease = rhc_db.LeaseLock("writer", ttl_s=cfg.RHC_LEASE_TTL_S)
    while not _stop.is_set():
        if lease.acquire():
            break
        _state.update(status="standby_other_writer", error=lease.last_error)
        _stop.wait(30)
    if _stop.is_set():
        lease.release()
        return
    _state["lock_held"] = True

    store, rpc, registry = build_components()
    guard = StorageGuard(store, rhc_db)
    indexer = Indexer(rpc, store, registry)
    indexer.write_gate = lambda: lease.held
    hub = SourceHub(store)
    _components.update(store=store, rpc=rpc, registry=registry, indexer=indexer, hub=hub, guard=guard, lock=lease)

    def _keep_lease():
        """Renew the writer lease on its own thread so slow work can never let it lapse."""
        while not _stop.is_set():
            was = lease.held
            lease.acquire()
            _state["lock_held"] = lease.held
            if was and not lease.held:
                log.error("RHC writer lease lost (%s); writes stopped, standing by", lease.last_error or "taken")
                lease.taken_by_other = lease.taken_by_other or lease.last_error is None
                _state["status"] = "standby_lease_lost"
            elif not was and lease.held:
                # Only another writer can have moved the durable state; a network blip on our
                # own lease needs no rewind (a chunk aborted mid-way forces its own resync).
                if lease.taken_by_other:
                    log.warning("RHC writer lease re-acquired after another writer held it; resyncing")
                    indexer.resync_needed = True
                else:
                    log.warning("RHC writer lease re-acquired (connection blip); continuing")
                lease.taken_by_other = False
                _state["status"] = "running"
            _stop.wait(cfg.RHC_LEASE_RENEW_S if lease.held else 30)

    t = threading.Thread(target=_keep_lease, name="rhc-lease", daemon=True)
    t.start()
    _threads.append(t)

    try:
        guard.check()
    except Exception as e:
        log.warning("initial storage check failed: %s", e)
    indexer.paused = guard.paused

    if cfg.RHC_INDEXER_ENABLED:
        def _run_indexer():
            while not _stop.is_set():
                try:
                    indexer.bootstrap()
                    break
                except Exception as e:
                    indexer.metrics["last_error"] = f"bootstrap: {type(e).__name__}: {str(e)[:200]}"
                    log.warning("indexer bootstrap failed: %s", e)
                    _stop.wait(30)
            if not _stop.is_set():
                indexer.stop_event = _stop
                indexer.run_forever()
        t = threading.Thread(target=_run_indexer, name="rhc-indexer", daemon=True)
        t.start()
        _threads.append(t)

    if cfg.RHC_SCREENER_ENABLED:
        from rhc_rpc import RpcClient
        from rhc_screener import Screener
        # Own RPC client and a smaller budget: screening must never starve the indexer.
        srpc = RpcClient(cfg.RHC_RPC_URLS, timeout=cfg.RHC_RPC_TIMEOUT_S, max_rps=cfg.RHC_SCREEN_RPC_MAX_RPS,
                         retries=cfg.RHC_RPC_MAX_RETRIES, batch_size=cfg.RHC_RPC_BATCH_SIZE,
                         max_items_per_s=cfg.RHC_SCREEN_RPC_MAX_ITEMS_PER_S)
        screener = Screener(srpc, store, registry, indexer, ds=hub.ds)
        _components["screener"] = screener

        def _run_screener():
            while not _stop.is_set():
                try:
                    ready = indexer.metrics.get("processed_ts") and indexer.metrics.get("mode") == "live"
                    if lease.held and not guard.paused and ready:
                        screener.cycle()
                except Exception as e:
                    screener.metrics["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
                    log.warning("screener cycle failed: %s", e)
                _stop.wait(cfg.RHC_SCREEN_CYCLE_S)
        t = threading.Thread(target=_run_screener, name="rhc-screener", daemon=True)
        t.start()
        _threads.append(t)

    _state.update(status="running", error=None)
    last_storage, last_snap = time.time(), 0.0
    while not _stop.is_set():
        now = time.time()
        try:
            if lease.held and now - last_storage >= cfg.RHC_STORAGE_CHECK_S:
                last_storage = now
                guard.check()
                indexer.paused = guard.paused
            if (lease.held and cfg.RHC_SOURCES_ENABLED and not guard.paused
                    and now - last_snap >= cfg.RHC_SNAPSHOT_INTERVAL_S):
                last_snap = now
                tracked = [(m.pk, m.pool_id, m.base_token) for m in list(registry.by_id.values())
                           if m.tracked and m.pk is not None]
                tracked.sort(key=lambda x: indexer.activity.last_ts.get(x[0], 0), reverse=True)
                hub.snapshot_cycle(tracked, ours=dict(indexer.last_price))
                hub.context_cycle()
                stamp = datetime.utcnow()
                store.upsert_source_health([{**h, "updated_at": stamp} for h in hub.health().values()])
        except Exception as e:
            _state["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            log.warning("RHC supervisor tick failed: %s", e)
        _stop.wait(5)
    lease.release()
    _state["lock_held"] = False


def start_safe():
    """Called from FastAPI lifespan. Never raises."""
    try:
        if not cfg.RHC_ENABLED:
            _state["status"] = "disabled"
            log.info("RHC disabled (RHC_ENABLED is not true)")
            return False
        if not cfg.RHC_DATABASE_URL:
            _state["status"] = "disabled_no_database"
            log.warning("RHC_ENABLED=true but RHC_DATABASE_URL is empty; RHC stays off")
            return False
        if any(t.is_alive() for t in _threads):
            return True
        _stop.clear()
        _state.update(status="starting", started_at=int(time.time()))
        t = threading.Thread(target=_main, name="rhc-supervisor", daemon=True)
        t.start()
        _threads.append(t)
        return True
    except Exception as e:
        _state.update(status="start_failed", error=str(e)[:200])
        log.exception("RHC start failed (backend continues normally)")
        return False


def stop_safe(timeout=5.0):
    try:
        _stop.set()
        for t in list(_threads):
            t.join(timeout=timeout)
        _threads.clear()
    except Exception:
        log.exception("RHC stop failed")


def run_standalone():
    """Run RHC as its own process (e.g. Azure WebJob): python rhc_indexer.py run"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    except Exception:
        pass
    import importlib
    importlib.reload(cfg)
    if not start_safe():
        print("RHC not started:", _state)
        return 1
    try:
        while any(t.is_alive() for t in _threads):
            time.sleep(1)
    except KeyboardInterrupt:
        stop_safe()
    return 0


def status():
    """Health snapshot for /api/rhc/health. Safe to call in any state."""
    out = {
        "mode": cfg.RHC_MODE,
        "live_trading": "disabled",
        "enabled": cfg.RHC_ENABLED,
        "database_configured": bool(cfg.RHC_DATABASE_URL),
        "service": dict(_state),
    }
    idx = _components.get("indexer")
    if idx is not None:
        m = dict(idx.metrics)
        m["tracked_pools"] = len(idx.tracked)
        m["eth_usd"] = idx.pricer.eth_usd
        m["paused"] = idx.paused
        out["indexer"] = m
    reg = _components.get("registry")
    if reg is not None:
        out["registry"] = {"cached_pools": len(reg.by_id), "cached_tokens": len(reg.tokens),
                           "unrecognized_factories": dict(reg.unrecognized_factories.most_common(10))}
    rpc = _components.get("rpc")
    if rpc is not None:
        out["rpc"] = rpc.health_summary()
    hub = _components.get("hub")
    if hub is not None:
        out["sources"] = hub.health()
        out["cross_check"] = hub.last_xcheck
        out["chain_context"] = hub.context
    guard = _components.get("guard")
    if guard is not None:
        out["storage"] = guard.last
    scr = _components.get("screener")
    if scr is not None:
        out["screener"] = dict(scr.metrics)
    return out


def store():
    return _components.get("store")
