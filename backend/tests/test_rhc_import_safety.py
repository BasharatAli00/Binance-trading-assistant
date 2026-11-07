"""Production-safety tests: RHC must be inert when disabled and must never need the database at import."""
import importlib

import pytest


def _reload(monkeypatch, **env):
    for k in ("RHC_ENABLED", "RHC_DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import rhc_config
    importlib.reload(rhc_config)
    import rhc_service
    importlib.reload(rhc_service)
    return rhc_config, rhc_service


def test_disabled_by_default(monkeypatch):
    cfg, svc = _reload(monkeypatch)
    assert cfg.RHC_ENABLED is False and cfg.RHC_LIVE_ENABLED is False and cfg.RHC_MODE == "paper"
    assert svc.start_safe() is False
    st = svc.status()
    assert st["service"]["status"] == "disabled" and st["live_trading"] == "disabled"


def test_enabled_without_database_stays_off(monkeypatch):
    cfg, svc = _reload(monkeypatch, RHC_ENABLED="true")
    assert svc.start_safe() is False
    assert svc.status()["service"]["status"] == "disabled_no_database"


def test_live_flag_cannot_be_enabled_from_env(monkeypatch):
    cfg, _ = _reload(monkeypatch, RHC_LIVE_ENABLED="true")
    assert cfg.RHC_LIVE_ENABLED is False


def test_no_fallback_to_production_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod-should-never-be-used/x")
    cfg, _ = _reload(monkeypatch, RHC_ENABLED="true")
    import rhc_db
    importlib.reload(rhc_db)
    with pytest.raises(rhc_db.RhcDbNotConfigured):
        rhc_db.get_engine()


def test_api_router_imports_and_health_works_when_disabled(monkeypatch):
    _reload(monkeypatch)
    import rhc_api
    importlib.reload(rhc_api)
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(rhc_api.router)
    paths = {r.path for r in app.routes}
    assert {"/api/rhc/health", "/api/rhc/pools/tracked", "/api/rhc/candles", "/api/rhc/gaps"} <= paths
    assert all(p.startswith("/api/rhc") and not p.startswith("/api/liquidity") for p in paths
               if p.startswith("/api/")), "must stay behind the JWT middleware"
    h = rhc_api.health()
    assert h["live_trading"] == "disabled" and h["mode"] == "paper"
    assert rhc_api.tracked_pools(limit=10).status_code == 503
    assert rhc_api.candles(pool_id="0x1", tf=61, limit=10, before=None).status_code == 400


def test_rhc_models_do_not_touch_production_base():
    """Static check (importing database.py would load real credentials): RHC tables use their
    own base and no table name collides with the production models."""
    import ast
    import os
    import rhc_models
    src = open(os.path.join(os.path.dirname(rhc_models.__file__), "models.py"), encoding="utf-8").read()
    prod_tables = {n.value.value for n in ast.walk(ast.parse(src))
                   if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "__tablename__" for t in n.targets)
                   and isinstance(n.value, ast.Constant)}
    assert prod_tables, "expected to find production table names"
    assert not (set(rhc_models.RhcBase.metadata.tables) & prod_tables)
    assert all(t.startswith("rhc_") for t in rhc_models.RhcBase.metadata.tables)
    assert "database" not in open(rhc_models.__file__, encoding="utf-8").read().split("RhcBase")[0]
