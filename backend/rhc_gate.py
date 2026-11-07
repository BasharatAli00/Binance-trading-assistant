"""Go-live gate: the documented checklist that must pass before real execution may even be
CONSIDERED. Passing it does not enable anything; live trading stays hard-disabled in code and
needs a separate, explicitly approved change (dedicated wallet, LiveBroker wiring, pilot)."""


def evaluate(paper_metrics, backtest_holdout, cfg, manual=None):
    """Pure. paper_metrics/backtest_holdout: rhc_metrics.compute() results (or None)."""
    manual = manual or {}
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    pm = paper_metrics or {}
    add("forward paper sample is sufficient", (pm.get("gate") or {}).get("sufficient"),
        (pm.get("gate") or {}).get("missing") or "ok")
    lo = (pm.get("expectancy_usd_ci95") or (None, None))[0]
    add("forward paper expectancy 95% CI lower bound > 0 (after all modelled costs)", lo is not None and lo > 0,
        f"lower bound = {lo}")
    pf_lo = (pm.get("profit_factor_ci95") or (None, None))[0]
    add(f"profit factor CI lower bound >= {cfg.RHC_GATE_MIN_PF_LO}", pf_lo is not None and pf_lo >= cfg.RHC_GATE_MIN_PF_LO,
        f"lower bound = {pf_lo}")
    dd = pm.get("max_drawdown_pct")
    enough = bool((pm.get("gate") or {}).get("sufficient"))
    # An empty or tiny record has no drawdown yet: that is not a pass.
    add(f"max drawdown <= {cfg.RHC_GATE_MAX_DD_PCT}% (on a sufficient sample)",
        enough and dd is not None and dd <= cfg.RHC_GATE_MAX_DD_PCT, f"{dd}% over {pm.get('trades', 0)} trades")
    bh = backtest_holdout or {}
    blo = (bh.get("expectancy_usd_ci95") or (None, None))[0]
    add("backtest hold-out expectancy CI lower bound > 0", blo is not None and blo > 0, f"lower bound = {blo}")
    pe, be_ci = pm.get("expectancy_usd"), bh.get("expectancy_usd_ci95") or (None, None)
    consistent = pe is not None and be_ci[0] is not None and be_ci[0] <= pe <= be_ci[1]
    add("forward paper expectancy inside the backtest hold-out CI (no overfit signal)", consistent,
        f"paper {pe} vs backtest CI {be_ci}")
    add("dedicated low-balance wallet configured and approved (manual)", manual.get("dedicated_wallet"), "manual")
    add("hard caps + kill switch tested end-to-end (manual)", manual.get("kill_switch_tested"), "manual")
    add("small-size live pilot approved by the owner (manual)", manual.get("pilot_approved"), "manual")
    add("LiveBroker enabled in code (separate approved change)", False, "hard-disabled in this build")
    return {"ready": all(c["pass"] for c in checks), "checks": checks}
