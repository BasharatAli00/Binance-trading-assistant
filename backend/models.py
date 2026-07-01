import uuid
from sqlalchemy import Column, String, Float, DateTime, Boolean, JSON, Integer
from sqlalchemy.dialects.postgresql import UUID
from database import Base

class Candle(Base):
    __tablename__ = "candles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    price_change_1h = Column(Float)
    price_change_4h = Column(Float)
    price_change_24h = Column(Float)
    high_24h = Column(Float)
    low_24h = Column(Float)
    volume_change_24h = Column(Float)
    volatility = Column(Float)
    candle_body = Column(Float)
    is_bullish = Column(Boolean)

class Indicator(Base):
    __tablename__ = "indicators"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    name = Column(String, index=True)
    value = Column(Float)
    rsi_change = Column(Float)
    price_vs_ema20 = Column(Float)
    price_vs_ema50 = Column(Float)
    ema20_vs_ema50 = Column(Float)
    macd_histogram = Column(Float)
    signal_strength = Column(Integer)

class Trade(Base):
    __tablename__ = "trades"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    side = Column(String)
    price = Column(Float)
    quantity = Column(Float)
    quote_amount = Column(Float)      # USDT value of the trade (qty * price)
    fee = Column(Float)               # simulated trading fee in USDT
    realized_pnl = Column(Float)      # profit/loss locked in on SELL (0 for BUY)
    balance_after = Column(Float)     # USDT cash balance right after this trade
    reason = Column(String)           # human-readable why the bot traded
    status = Column(String)


class PaperAccount(Base):
    """Single-row virtual wallet for simulated (paper) trading."""
    __tablename__ = "paper_account"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    usdt_balance = Column(Float)       # free cash
    starting_balance = Column(Float)   # baseline used for total P&L %
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class Position(Base):
    """Current open holding per symbol in the paper wallet."""
    __tablename__ = "positions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    quantity = Column(Float)
    avg_entry_price = Column(Float)
    updated_at = Column(DateTime)
    # Strategy risk state (trend-following stop management)
    stop_price = Column(Float)        # current (trailing) stop
    init_stop = Column(Float)         # initial stop at entry (for R math)
    highest_price = Column(Float)     # high-water mark since entry (chandelier)

class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    predicted_price = Column(Float)
    confidence = Column(Float)

class MarketStats(Base):
    __tablename__ = "market_stats"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    price_change_24h_pct = Column(Float)
    high_24h = Column(Float)
    low_24h = Column(Float)
    volume_24h = Column(Float)
    quote_volume_24h = Column(Float)
    trade_count_24h = Column(Integer)
    weighted_avg_price = Column(Float)

class NewsArticle(Base):
    __tablename__ = "news_articles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    timestamp = Column(DateTime, index=True)
    title = Column(String)
    url = Column(String)
    sentiment = Column(String)
    source = Column(String)

class OnChainStats(Base):
    __tablename__ = "onchain_stats"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    timestamp = Column(DateTime, index=True)
    n_tx = Column(Integer)
    total_fees_btc = Column(Float)
    hash_rate = Column(Float)
    difficulty = Column(Float)
    estimated_transaction_volume_usd = Column(Float)

class TaapiIndicator(Base):
    """Supplementary technical indicators fetched from the Taapi.io API.

    Stored separately from the locally-computed `Indicator` rows so the
    external source never overwrites our own calculations.
    """
    __tablename__ = "taapi_indicators"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    rsi = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    macd_hist = Column(Float)
    ema20 = Column(Float)

class GoogleTrend(Base):
    """Google Trends search-interest for a keyword (e.g. "Bitcoin")."""
    __tablename__ = "google_trends"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    keyword = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    trend_score = Column(Float)        # latest week's search interest (0-100)
    prev_score = Column(Float)         # previous week's value
    wow_change_pct = Column(Float)     # week-over-week % change


class PivotLevels(Base):
    """Daily floor-trader pivot levels computed from the prior day's OHLC.

    Pure calculation (no external API) — derived from the previous completed
    daily candle's High/Low/Close pulled via the Binance kline client.
    """
    __tablename__ = "pivot_levels"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    pp = Column(Float)                 # central pivot point (H+L+C)/3
    r1 = Column(Float)
    r2 = Column(Float)
    r3 = Column(Float)
    s1 = Column(Float)
    s2 = Column(Float)
    s3 = Column(Float)
    trend = Column(String)             # "Uptrend" / "Downtrend" / "Neutral" (price vs PP)
    interval_hours = Column(Integer)   # recompute/candle period these levels were derived from


class PivotConfig(Base):
    """Single-row tunable settings for strategy #2 (pivot-bracket).

    Currently just the recompute interval — how often (and from what candle
    period) the Support/Resistance bracket is recomputed. Restricted to the
    candle intervals Binance serves natively (1, 2, 4, 6, 8, 12h).
    """
    __tablename__ = "pivot_config"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    interval_hours = Column(Integer)
    updated_at = Column(DateTime)


class PivotAccount(Base):
    """Isolated virtual wallet for the second strategy (pivot-bracket).

    Completely separate from PaperAccount so strategy #1 and #2 trade with
    independent capital and their P&L can be compared head-to-head.
    """
    __tablename__ = "pivot_account"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    usdt_balance = Column(Float)
    starting_balance = Column(Float)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class PivotPosition(Base):
    """Open holding for the pivot-bracket strategy (its own positions table)."""
    __tablename__ = "pivot_positions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    quantity = Column(Float)
    avg_entry_price = Column(Float)
    updated_at = Column(DateTime)
    take_profit = Column(Float)       # current ladder target (R1 -> R2 -> R3) for display
    stop_price = Column(Float)        # S1 stop at entry
    pivot_day = Column(String)        # 12h bucket of the pivots used (flatten-at-rollover anchor)
    # Laddered-exit state (persisted across loop passes):
    rung = Column(Integer)            # 0=target R1, 1=R1 broken (target R2), 2=R2 broken (target R3)
    peak_price = Column(Float)        # highest price since entry (for the 0.5%-from-peak trail)
    watch_count = Column(Integer)     # consecutive passes price has held at/above the level being tested


class PivotTrade(Base):
    """Trade log for the pivot-bracket strategy (separate from the core log)."""
    __tablename__ = "pivot_trades"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    side = Column(String)
    price = Column(Float)
    quantity = Column(Float)
    quote_amount = Column(Float)
    fee = Column(Float)
    realized_pnl = Column(Float)
    balance_after = Column(Float)
    reason = Column(String)
    status = Column(String)


class FuturesStats(Base):
    """Perpetual-futures sentiment from Binance Futures public data endpoints.

    Keyless/unauthenticated: long/short account ratio + current funding rate.
    Used as a contrarian/positioning signal even though trading is spot-only.
    """
    __tablename__ = "futures_stats"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    long_pct = Column(Float)           # % of accounts net long (0-100)
    short_pct = Column(Float)          # % of accounts net short (0-100)
    long_short_ratio = Column(Float)   # long/short account ratio
    funding_rate = Column(Float)       # last funding rate (fraction, e.g. 0.0001 = 0.01%)
    funding_direction = Column(String) # "Longs pay" / "Shorts pay" / "Neutral"
    next_funding_time = Column(DateTime)


# =====================================================================
# Strategy #3 — Intelligent Sniper (Solana pump.fun meme-coin bot)
# =====================================================================
# A third, fully isolated strategy. Its own tables (all prefixed `sniper_`),
# its own simulated wallets, its own loop. Nothing here is shared with
# Strategy #1 (paper_engine) or Strategy #2 (pivot_engine). Live trading is
# stubbed for the future; everything runs in simulation for now.

class SniperPortfolio(Base):
    """One tunable wallet for the sniper. We seed two: a 'live' and a 'sim'
    portfolio (both simulated for now — 'live' becomes real once
    sniper_live.py is wired). All strategy params are editable from the UI."""
    __tablename__ = "sniper_portfolio"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String)
    mode = Column(String, default="sim")           # 'sim' | 'live'
    is_active = Column(Boolean, default=True)       # trading active / paused
    cash_balance = Column(Float, default=1000.0)    # free cash (USD)
    initial_balance = Column(Float, default=1000.0) # baseline for total P&L
    position_size = Column(Float, default=50.0)     # USD per trade
    max_open_positions = Column(Integer, default=5)
    stop_loss_pct = Column(Float, default=-15.0)    # % (negative) — tighter than the old -20
    take_profit_pct = Column(Float, default=1000.0) # % (effectively let-it-run)
    time_exit_minutes = Column(Integer, default=120)
    trail_start_pct = Column(Float, default=15.0)
    trail_start_distance = Column(Float, default=5.0)
    trail_end_pct = Column(Float, default=30.0)
    trail_end_distance = Column(Float, default=2.0)
    # --- Scale-out / runner management (fixes the inverted-payoff problem) ---
    scale_out_pct = Column(Float, default=25.0)      # bank first tranche at this gain
    scale_out_fraction = Column(Float, default=0.5)  # fraction of qty sold at scale-out
    runner_trail_pct = Column(Float, default=35.0)   # wide give-back trail for the runner
    no_progress_minutes = Column(Integer, default=25)# cull dead trades after this long...
    no_progress_pct = Column(Float, default=8.0)     # ...if peak gain never reached this
    conviction_floor = Column(Integer, default=30)  # raised from 20 (the 20-29 bucket bled)
    min_buy_pressure = Column(Float, default=0.5)
    rug_veto_threshold = Column(Integer, default=45)
    cb_enabled = Column(Boolean, default=True)      # circuit breaker on
    cb_max_drawdown = Column(Float, default=20.0)   # % drawdown that trips it
    cb_action = Column(String, default="pause")     # 'pause' for now
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class SniperToken(Base):
    """Active/tracked tokens (the discovery watchlist)."""
    __tablename__ = "sniper_token"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    token_address = Column(String, unique=True, index=True)
    symbol = Column(String)
    name = Column(String)
    pair_address = Column(String)
    dex_id = Column(String)
    liquidity_usd = Column(Float)
    volume_h1 = Column(Float)
    price_usd = Column(Float)
    market_cap = Column(Float)
    discovery_source = Column(String)
    rank_score = Column(Float)
    is_active = Column(Boolean, default=True)
    logo_url = Column(String)
    has_socials = Column(Boolean, default=False)
    boost_count = Column(Integer, default=0)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class SniperSnapshot(Base):
    """1-minute time-series snapshot per tracked token (DexScreener)."""
    __tablename__ = "sniper_snapshot"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    token_address = Column(String, index=True)
    snapshot_time = Column(DateTime, index=True)
    price_usd = Column(Float)
    price_native = Column(Float)
    volume_m5 = Column(Float)
    volume_h1 = Column(Float)
    volume_h6 = Column(Float)
    volume_h24 = Column(Float)
    buys_m5 = Column(Integer)
    sells_m5 = Column(Integer)
    buys_h1 = Column(Integer)
    sells_h1 = Column(Integer)
    buys_h6 = Column(Integer)
    sells_h6 = Column(Integer)
    buys_h24 = Column(Integer)
    sells_h24 = Column(Integer)
    price_change_m5 = Column(Float)
    price_change_h1 = Column(Float)
    price_change_h6 = Column(Float)
    price_change_h24 = Column(Float)
    liquidity_usd = Column(Float)
    liquidity_base = Column(Float)
    liquidity_quote = Column(Float)
    market_cap = Column(Float)
    fdv = Column(Float)
    pair_created_at = Column(DateTime)
    has_socials = Column(Boolean)
    pool_count = Column(Integer)
    boost_count = Column(Integer)
    dex_id = Column(String)
    pair_address = Column(String)


class SniperPosition(Base):
    """Open or closed sniper position, scoped to a portfolio."""
    __tablename__ = "sniper_position"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    portfolio_id = Column(Integer, index=True)
    token_address = Column(String, index=True)
    symbol = Column(String)
    entry_price = Column(Float)
    entry_time = Column(DateTime)
    exit_price = Column(Float)
    exit_time = Column(DateTime)
    qty = Column(Float)
    position_usd = Column(Float)       # ORIGINAL USD invested (return_pct denominator; never reduced)
    cost_basis = Column(Float)         # USD cost of the qty still held (drops on each scale-out)
    scaled_out = Column(Boolean, default=False)  # True once the first profit tranche is banked
    peak_price = Column(Float)
    last_price = Column(Float)         # most recent mark (for unrealized P&L in UI)
    exit_reason = Column(String)
    realized_pnl = Column(Float)
    return_pct = Column(Float)
    hold_minutes = Column(Float)
    conviction_score = Column(Float)
    rug_risk_score = Column(Float)
    entry_dex_id = Column(String)
    entry_pair_address = Column(String)
    discovery_source = Column(String)
    tx_hash_buy = Column(String)       # populated only in live mode
    tx_hash_sell = Column(String)
    status = Column(String, default="open")   # 'open' | 'closed'


class SniperTrade(Base):
    """Immutable sniper trade log (separate from the core/pivot logs)."""
    __tablename__ = "sniper_trade"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    portfolio_id = Column(Integer, index=True)
    position_id = Column(UUID(as_uuid=True), index=True)
    token_address = Column(String, index=True)
    symbol = Column(String)
    timestamp = Column(DateTime, index=True)
    side = Column(String)              # 'buy' | 'sell'
    price = Column(Float)
    quantity = Column(Float)
    usd_value = Column(Float)
    fee = Column(Float)
    realized_pnl = Column(Float)
    balance_after = Column(Float)
    reason = Column(String)
    tx_hash = Column(String)
    status = Column(String, default="FILLED")


class SniperCooldown(Base):
    """Per-token cooldown after an exit (avoid immediate re-entry chop)."""
    __tablename__ = "sniper_cooldown"
    token_address = Column(String, primary_key=True)
    cooldown_until = Column(DateTime)


class SniperModelScore(Base):
    """Latest per-token scores, refreshed each tick (for the UI watchlist)."""
    __tablename__ = "sniper_model_score"
    token_address = Column(String, primary_key=True)
    prob_win = Column(Float)
    conviction_score = Column(Float)
    rug_risk_score = Column(Float)
    updated_at = Column(DateTime)


# =====================================================================
# Top-Gainer Wallet Finder (Milestone 1)
# =====================================================================
# Discovers and ranks the best-performing Solana meme-coin trader wallets via
# the Solana Tracker Data API leaderboard, then re-applies our own local
# filters (creator/bot exclusion, net-positive) and composite ranking score.
# Fully isolated (tables prefixed `pump_`); shares nothing with the trading
# strategies above. Read-only leaderboard output — NOT a trading bot.
# See pumpgainer_*.py. PnL/volume are in the provider's units (USD).

class PumpWalletStats(Base):
    """Every wallet the provider returned for one run/window, with our local
    eligibility verdict — kept for audit/debugging and filter tuning."""
    __tablename__ = "pump_wallet_stats"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    wallet_address = Column(String, index=True)
    window = Column(String, index=True)        # '24h' | '7d'
    run_timestamp = Column(DateTime, index=True)
    realized_pnl = Column(Float)               # provider realized PnL (strict mode), USD
    roi_pct = Column(Float)
    volume = Column(Float)                      # traded volume, USD
    round_trip_count = Column(Integer)         # provider trade count
    distinct_tokens = Column(Integer)          # tokens traded
    win_rate = Column(Float)                    # 0..1
    passed_eligibility = Column(Boolean)
    exclusion_reason = Column(String)          # first failing local filter, if any


class PumpTopGainer(Base):
    """Final ranked leaderboard (current run only — replaced each run).
    One table with a `window` column, matching how the rest of this codebase
    stores per-window series."""
    __tablename__ = "pump_top_gainer"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    window = Column(String, index=True)        # '24h' | '7d'
    rank = Column(Integer)                     # 1 = best
    wallet_address = Column(String, index=True)
    score = Column(Float)                      # our composite score
    realized_pnl = Column(Float)               # USD
    roi_pct = Column(Float)
    win_rate = Column(Float)                    # 0..1
    round_trip_count = Column(Integer)
    distinct_tokens = Column(Integer)
    volume = Column(Float)                      # USD
    last_updated = Column(DateTime, index=True)


class PumpRunHistory(Base):
    """Audit log — one row per (run, window)."""
    __tablename__ = "pump_run_history"
    run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    run_timestamp = Column(DateTime, index=True)
    window = Column(String, index=True)
    wallets_fetched = Column(Integer)          # rows the provider returned this run
    wallets_evaluated = Column(Integer)
    wallets_passed_eligibility = Column(Integer)
    status = Column(String)                    # success / partial / failed
    error_message = Column(String)


# =====================================================================
# Strategy #4 — Smart-Money Copy Trade
# =====================================================================
# Watches the qualified top-gainer wallets (from pump_top_gainer) via Helius.
# When MIN_WALLETS of them buy the same token within a short window, opens a
# simulated position and manages the exit. Fully isolated: own wallet, own
# tables (prefixed `copy_`), own loop. Sim-only for now. See copytrade_*.py.

class CopyTradePortfolio(Base):
    """The single simulated copy-trade wallet (params the UI can edit)."""
    __tablename__ = "copy_portfolio"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String, default="CopyTrade Sim")
    mode = Column(String, default="sim")            # 'sim' | 'live'
    is_active = Column(Boolean, default=True)
    cash_balance = Column(Float, default=1000.0)
    initial_balance = Column(Float, default=1000.0)
    position_size = Column(Float, default=50.0)     # USD per trade
    max_open_positions = Column(Integer, default=8)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class CopyWatchedWallet(Base):
    """The set of smart-money wallets we currently watch (synced from the
    qualified leaderboard). Registered with Helius."""
    __tablename__ = "copy_watched_wallet"
    wallet = Column(String, primary_key=True)
    source_window = Column(String)                  # '24h' | '7d' (where it qualified)
    rank = Column(Integer)                           # its leaderboard rank
    score = Column(Float)
    added_at = Column(DateTime)
    last_synced = Column(DateTime)


class CopyWalletEvent(Base):
    """A buy/sell by a watched wallet, delivered by Helius (or a poll)."""
    __tablename__ = "copy_wallet_event"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    wallet = Column(String, index=True)
    mint = Column(String, index=True)
    symbol = Column(String)
    side = Column(String)                            # 'buy' | 'sell' (of the token)
    sol_amount = Column(Float)
    price_usd = Column(Float)
    signature = Column(String, index=True)
    block_time = Column(DateTime, index=True)
    received_at = Column(DateTime)


class CopySignal(Base):
    """A fired consensus signal (2+ wallets bought the same mint in-window)."""
    __tablename__ = "copy_signal"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    mint = Column(String, index=True)
    symbol = Column(String)
    wallet_count = Column(Integer)
    wallets = Column(JSON)                           # list of triggering wallets
    first_buy_time = Column(DateTime)
    fired_at = Column(DateTime, index=True)
    status = Column(String)                          # 'entered' | 'skipped'
    reason = Column(String)                          # entry reason or skip reason


class CopyPosition(Base):
    """Open or closed simulated copy-trade position."""
    __tablename__ = "copy_position"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    portfolio_id = Column(Integer, index=True)
    mint = Column(String, index=True)
    symbol = Column(String)
    entry_price = Column(Float)
    entry_time = Column(DateTime)
    exit_price = Column(Float)
    exit_time = Column(DateTime)
    qty = Column(Float)
    position_usd = Column(Float)                      # original USD invested (return denominator)
    cost_basis = Column(Float)                        # USD cost of qty still held (drops on scale-out)
    scaled_out = Column(Boolean, default=False)
    peak_price = Column(Float)
    last_price = Column(Float)
    exit_reason = Column(String)
    realized_pnl = Column(Float)
    return_pct = Column(Float)
    hold_minutes = Column(Float)
    trigger_wallets = Column(JSON)                    # wallets whose buy triggered entry
    exited_wallets = Column(JSON)                     # triggering wallets that have since sold
    status = Column(String, default="open")          # 'open' | 'closed'


class CopyTrade(Base):
    """Immutable copy-trade fill log."""
    __tablename__ = "copy_trade"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    portfolio_id = Column(Integer, index=True)
    position_id = Column(UUID(as_uuid=True), index=True)
    mint = Column(String, index=True)
    symbol = Column(String)
    timestamp = Column(DateTime, index=True)
    side = Column(String)                            # 'buy' | 'sell'
    price = Column(Float)
    quantity = Column(Float)
    usd_value = Column(Float)
    fee = Column(Float)
    realized_pnl = Column(Float)
    balance_after = Column(Float)
    reason = Column(String)
    status = Column(String, default="FILLED")


class CopyCooldown(Base):
    """Per-token cooldown after an exit (avoid immediate re-entry)."""
    __tablename__ = "copy_cooldown"
    mint = Column(String, primary_key=True)
    cooldown_until = Column(DateTime)

