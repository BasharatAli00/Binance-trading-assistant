"""LiveBroker: DISABLED adapter around the existing Robinhood Chain desk's execution.

It has the same interface as PaperBroker so the decision engine could use it unchanged, but in
this build it can never execute:
  * RHC_LIVE_ENABLED is a constant False in rhc_config (no env switch);
  * submit() refuses and returns the reasons;
  * the wrapped call into robinhood_live.execute_buy/execute_sell is behind _armed(), which
    returns False, and robinhood_live is imported lazily only inside that call - importing this
    module touches neither the existing desk nor any private key.
Enabling live trading requires a separate, explicitly approved change: a dedicated low-balance
wallet (the existing desk uses its own global key and switches), hard per-trade/daily caps, a
tested kill switch, the go-live gate passing, and a small-size pilot.
"""
import rhc_config as cfg
from rhc_decision import Broker


class LiveTradingDisabled(RuntimeError):
    pass


class LiveBroker(Broker):
    name = "live_disabled"
    executes = False

    def _armed(self):
        return False            # hard-disabled in this build, by design

    def refusal_reasons(self):
        reasons = ["RHC_LIVE_ENABLED is hard-disabled in code"]
        if not cfg.RHC_LIVE_ENABLED:
            reasons.append("live flag off")
        reasons += ["dedicated wallet not configured", "go-live gate not passed", "owner approval missing"]
        return reasons

    def submit(self, intent):
        return {"status": "refused", "executed": False, "reasons": self.refusal_reasons()}

    def _execute_via_existing_desk(self, token_address, amount_usd):
        """Would wrap robinhood_live.execute_buy (unchanged). Unreachable while _armed() is False."""
        if not self._armed() or not cfg.RHC_LIVE_ENABLED:
            raise LiveTradingDisabled("live execution is disabled in this build")
        import robinhood_live  # pragma: no cover - never reached in this build
        return robinhood_live.execute_buy(token_address, amount_usd)
