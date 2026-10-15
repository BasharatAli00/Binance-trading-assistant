"""Configuration and feature flags for the isolated Robinhood Chain Trading Desk.

Operates completely independently from Solana (Strategy #4) and Binance strategies.
Governed by two deliberate safety switches:
  * ROBINHOOD_LIVE_ENABLED (master kill switch) — off => 100% simulated paper trading.
  * ROBINHOOD_LIVE_DRYRUN — on by default => builds/checks real DEX quotes without
    spending any real ETH.
Real money moves ONLY when ROBINHOOD_LIVE_ENABLED=true AND ROBINHOOD_LIVE_DRYRUN=false.
"""
import os


def _flag(name, default="true"):
    return os.getenv(name, default).lower() in ("1", "true", "yes")


# Master feature switch
ROBINHOOD_ENABLED = _flag("ROBINHOOD_ENABLED", "true")

# Live trading switches (REAL MONEY when both are enabled)
ROBINHOOD_LIVE_ENABLED = _flag("ROBINHOOD_LIVE_ENABLED", "false")
ROBINHOOD_LIVE_DRYRUN = _flag("ROBINHOOD_LIVE_DRYRUN", "true")

# EVM Wallet & Network Configuration (Chain ID 4663 = Robinhood Chain L2)
ROBINHOOD_RPC_URL = os.getenv("ROBINHOOD_RPC_URL", "https://rpc.mainnet.chain.robinhood.com")
ROBINHOOD_CHAIN_ID = int(os.getenv("ROBINHOOD_CHAIN_ID", "4663"))
ROBINHOOD_PRIVATE_KEY = os.getenv("ROBINHOOD_PRIVATE_KEY", "").strip()
ROBINHOOD_EXPECTED_WALLET = os.getenv("ROBINHOOD_EXPECTED_WALLET", "").strip()

# Trade Safety & Limits
ROBINHOOD_MAX_POSITIONS = int(os.getenv("ROBINHOOD_MAX_POSITIONS", "5"))
ROBINHOOD_MAX_SLIPPAGE_BPS = int(os.getenv("ROBINHOOD_MAX_SLIPPAGE_BPS", "300"))      # 3%
ROBINHOOD_MAX_PRICE_IMPACT_PCT = float(os.getenv("ROBINHOOD_MAX_PRICE_IMPACT", "10.0"))
ROBINHOOD_MIN_ETH_BALANCE = float(os.getenv("ROBINHOOD_MIN_ETH", "0.001"))

# External URLs
DEXSCREENER_BASE = "https://api.dexscreener.com"
ROBINHOOD_EXPLORER_TX_BASE = "https://robinhoodchain.blockscout.com/tx/"
HTTP_TIMEOUT = 10
