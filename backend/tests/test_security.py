"""Security regression tests. Offline: no database, network or real credentials.

Modules that import database.py (main, auth, copytrade_api) would load real
credentials, so those are checked from their source instead of being imported.
"""
import ast
import os

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    with open(os.path.join(BACKEND, name), encoding="utf-8") as f:
        return f.read()


# --- JWT secret ---------------------------------------------------------------
def test_no_public_default_jwt_secret():
    src = _src("auth.py")
    assert "super-secret-default-key" not in src
    assert 'os.getenv("JWT_SECRET_KEY", "")' in src and "secrets.token_urlsafe" in src


# --- auth middleware exemptions -----------------------------------------------
def _exempt_paths():
    tree = ast.parse(_src("main.py"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "auth_middleware")
    lists = [n for n in ast.walk(fn) if isinstance(n, ast.List)
             and n.elts and all(isinstance(e, ast.Constant) for e in n.elts)]
    prefix_calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                    and getattr(n.func, "attr", "") == "startswith"
                    and n.args and isinstance(n.args[0], ast.Constant)]
    return {e.value for lst in lists for e in lst.elts}, {c.args[0].value for c in prefix_calls}


def test_middleware_exempts_only_exact_paths():
    exact, prefixes = _exempt_paths()
    assert exact == {"/api/login", "/api/copytrade/helius", "/api/copytrade/quicknode"}
    # The only prefix test allowed is the "/api" scope check itself.
    assert prefixes <= {"/api", "Bearer "}, f"unexpected prefix exemption: {prefixes}"


# --- webhooks ------------------------------------------------------------------
def test_webhooks_require_a_secret():
    src = _src("copytrade_api.py")
    assert src.count('"webhook secret not configured"') == 2   # Helius and QuickNode fail closed
    assert "hmac.compare_digest" in src
    assert "To be implemented" not in src


def test_secret_compare_helper():
    tree = ast.parse(_src("copytrade_api.py"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_secret_ok")
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "copytrade_api", "exec"), ns)
    ok = ns["_secret_ok"]
    assert ok("s3cret", "s3cret")
    assert not ok("wrong", "s3cret")
    assert not ok(None, "s3cret") and not ok("", "s3cret")
    assert not ok("", "") and not ok(None, "")


# --- admin password script -----------------------------------------------------
def test_reset_password_has_no_hardcoded_password():
    src = _src("reset_password.py")
    assert "password123" not in src
    assert "getpass" in src and "ADMIN_NEW_PASSWORD" in src


# --- Robinhood desk slippage / price impact ------------------------------------
def test_relay_quote_sends_slippage_limit(monkeypatch):
    import robinhood_config as cfg
    import robinhood_live as live
    sent = {}

    class Resp:
        ok = True

        def json(self):
            return {"steps": []}

    def fake_post(url, json=None, **kw):
        sent.update(json)
        return Resp()

    monkeypatch.setattr(live._S, "post", fake_post)
    live.get_relay_swap_quote("0xabc", live.ETH_ZERO_ADDRESS, "0xdef", 10**18)
    assert sent["slippageTolerance"] == str(cfg.ROBINHOOD_MAX_SLIPPAGE_BPS)


@pytest.mark.parametrize("out_usd,ref,blocked", [
    (97.0, 100.0, False),    # 3% cost: allowed under the 10% default
    (89.0, 100.0, True),     # 11% cost: refused
    (None, 100.0, True),     # no USD value in the quote: refused (fail closed)
    (50.0, 0.0, True),       # no reference value: refused
])
def test_quote_cost_guard(monkeypatch, out_usd, ref, blocked):
    import robinhood_config as cfg
    import robinhood_live as live
    monkeypatch.setattr(cfg, "ROBINHOOD_MAX_PRICE_IMPACT_PCT", 10.0)
    quote = {"details": {"currencyOut": {"amountUsd": out_usd}}} if out_usd is not None else {}
    assert (live.check_quote_cost(quote, ref) is not None) is blocked
