"""Config & feature flags for Strategy #4 — Smart-Money Copy Trade.

Watches the wallets that qualified in the Top-Gainer finder (pump_top_gainer)
via Helius, and when 2+ of them buy the SAME token within a short window, opens
a simulated position and manages the exit itself. Fully isolated: own wallet,
own tables (all prefixed `copy_`), own loop. Sim-only until LIVE is wired.

Pure configuration, mirroring sniper_config.py.
"""
import os


def _flag(name, default="true"):
    return os.getenv(name, default).lower() in ("1", "true", "yes")


# ---- Master switch -------------------------------------------------------
# Off => the loop/thread is never started and the app is byte-for-byte
# unaffected. Also effectively idle if no Helius key is configured.
COPYTRADE_ENABLED = _flag("COPYTRADE_ENABLED", "true")

# ---- LIVE trading (Part B) — OFF by default. REAL MONEY when enabled. --------
# Master kill switch. While false, NOTHING can trade for real — every fill is
# simulated regardless of a portfolio's mode. This is the single flag that gates
# all real execution.
LIVE_TRADING_ENABLED = _flag("COPYTRADE_LIVE", "false")

# Wallet secret — store ONLY in Azure (env var or Key Vault), NEVER in git/DB.
# Accepts a Phantom base58 export OR a JSON byte array. Loaded lazily and only
# when LIVE_TRADING_ENABLED is true.
SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY", "")
# The public address we EXPECT that key to produce — a safety cross-check so a
# wrong/rotated key can't silently trade from an unexpected wallet.
LIVE_TRADING_WALLET = os.getenv("LIVE_TRADING_WALLET",
                                "5KPDALxU65m7ncB5hpFBaX9ts3xHyjb83fupvnWz7gLd")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

# Live safety rails (all enforced before any real order):
LIVE_MAX_TRADE_USD = float(os.getenv("CT_LIVE_MAX_TRADE_USD", "25"))    # hard cap per trade
LIVE_MAX_TRADES_PER_DAY = int(os.getenv("CT_LIVE_MAX_TRADES_DAY", "20"))
LIVE_MIN_SOL_BALANCE = float(os.getenv("CT_LIVE_MIN_SOL", "0.02"))      # keep a gas buffer
LIVE_SLIPPAGE_BPS = int(os.getenv("CT_LIVE_SLIPPAGE_BPS", "150"))       # 1.5%
LIVE_PRIORITY_FEE_LAMPORTS = int(os.getenv("CT_LIVE_PRIORITY_FEE", "200000"))
LIVE_CONFIRM_TIMEOUT_SEC = int(os.getenv("CT_LIVE_CONFIRM_TIMEOUT", "45"))

# Jupiter free/keyless tier (same as the sniper uses). No API key required.
JUPITER_QUOTE_URL = os.getenv("JUPITER_QUOTE_URL", "https://lite-api.jup.ag/swap/v1/quote")
JUPITER_SWAP_URL = os.getenv("JUPITER_SWAP_URL", "https://lite-api.jup.ag/swap/v1/swap")
JUPITER_PRICE_URL = os.getenv("JUPITER_PRICE_URL", "https://lite-api.jup.ag/price/v3")

# ---- Helius (real-time wallet watching) ---------------------------------
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
# Public URL Helius POSTs events to — our receiver route. Must be reachable
# from the internet (the backend is deployed). e.g. https://<host>/api/copytrade/helius
HELIUS_WEBHOOK_URL = os.getenv("HELIUS_WEBHOOK_URL", "")
# Shared secret we set as the webhook's authHeader and verify on each POST.
HELIUS_WEBHOOK_SECRET = os.getenv("HELIUS_WEBHOOK_SECRET", "")
HELIUS_API_BASE = os.getenv("HELIUS_API_BASE", "https://api.helius.xyz")
HTTP_TIMEOUT = 20

# Pump.fun / PumpSwap programs — we only care about swaps on these.
PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL_MINT = "So11111111111111111111111111111111111111112"

# ---- Watched wallet set --------------------------------------------------
# Taken from the qualified leaderboard. Union of both windows, capped.
WATCH_FROM_WINDOWS = ["7d", "24h"]
MAX_WATCHED_WALLETS = int(os.getenv("CT_MAX_WATCHED", "40"))
WALLET_SYNC_MINUTES = int(os.getenv("CT_WALLET_SYNC_MIN", "30"))  # re-sync list + webhook

# ---- Consensus signal (the core edge) -----------------------------------
MIN_WALLETS = int(os.getenv("CT_MIN_WALLETS", "2"))            # 2+ distinct wallets
CONSENSUS_WINDOW_MIN = int(os.getenv("CT_WINDOW_MIN", "10"))   # ...within this many minutes
SIGNAL_COOLDOWN_MIN = int(os.getenv("CT_SIGNAL_COOLDOWN_MIN", "120"))  # re-signal same mint
EVENT_RETENTION_HOURS = int(os.getenv("CT_EVENT_RETENTION_H", "24"))   # prune wallet events

# ---- Entry gates ---------------------------------------------------------
MIN_LIQUIDITY_USD = float(os.getenv("CT_MIN_LIQ", "8000"))
# Don't chase: if price already ran past this since the FIRST triggering buy we
# can detect, skip — we missed the entry and would be buying the top.
MAX_PRICE_MOVE_SINCE_SIGNAL_PCT = float(os.getenv("CT_MAX_CHASE_PCT", "40"))

# ---- Simulated wallet + risk --------------------------------------------
INITIAL_BALANCE = float(os.getenv("CT_INITIAL_BALANCE", "1000"))
POSITION_SIZE_USD = float(os.getenv("CT_POSITION_SIZE", "50"))
MAX_OPEN_POSITIONS = int(os.getenv("CT_MAX_OPEN", "8"))
DAILY_MAX_LOSS_PCT = float(os.getenv("CT_DAILY_MAX_LOSS", "20"))   # circuit breaker

# ---- Exits ---------------------------------------------------------------
STOP_LOSS_PCT = float(os.getenv("CT_STOP_LOSS", "-25"))       # hard stop
TAKE_PROFIT_PCT = float(os.getenv("CT_TAKE_PROFIT", "60"))    # scale-out trigger
SCALE_OUT_FRACTION = float(os.getenv("CT_SCALE_OUT_FRAC", "0.5"))  # sell half at TP, run the rest
RUNNER_TRAIL_PCT = float(os.getenv("CT_RUNNER_TRAIL", "30"))  # give-back trail after scale-out
TRAIL_START_PCT = float(os.getenv("CT_TRAIL_START", "25"))    # start trailing once up this much
TRAIL_DISTANCE_PCT = float(os.getenv("CT_TRAIL_DIST", "12"))  # trail distance before scale-out
TIME_EXIT_MINUTES = int(os.getenv("CT_TIME_EXIT_MIN", "180"))
# Mirror the smart money: exit when this fraction of the wallets that triggered
# our entry have SOLD the token. 0.5 = exit once half of them are out.
SMART_EXIT_SELL_FRACTION = float(os.getenv("CT_SMART_EXIT_FRAC", "0.5"))

# ---- Fees / loop ---------------------------------------------------------
FEE_RATE = float(os.getenv("CT_FEE_RATE", "0.01"))   # same friction proxy as the sniper
FAST_POLL_SEC = int(os.getenv("CT_FAST_POLL_SEC", "10"))   # exit + signal processing cadence

# Cooldown (minutes) after an exit before we'll re-enter the same token.
COOLDOWN_MINUTES = {
    "stop_loss": 30, "trailing_stop": 10, "take_profit": 5,
    "time_exit": 10, "smart_money_exit": 15, "manual": 0, "default": 10,
}
