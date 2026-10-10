import copytrade_engine as eng
import copytrade_config as cfg
cfg.CONSENSUS_WINDOW_MIN=14400
import copytrade_signal as sig
import copytrade_strategy as strat
import sniper_data

eng.ensure_initialized()
pf = eng.get_portfolios()[0]
c = sig.detect_consensus_buys()[0]
print(f"pf id: {pf['id']}, active: {pf['is_active']}")
print(f"Holding: {eng.is_holding(pf['id'], c['mint'])}")
mark = (sniper_data.latest_marks([c["mint"]]) or {}).get(c["mint"]) or {}
ok, reason = strat.passes_entry_gates(mark, min_liquidity=cfg.MIN_LIQUIDITY_USD, max_liquidity=cfg.MAX_LIQUIDITY_USD)
print(f"Gate: {ok}, {reason}")
