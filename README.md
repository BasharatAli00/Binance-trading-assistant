# Nexus Trading Terminal

*Formerly "Binance Trading Assistant". GitHub repository: `BasharatAli00/Intelligent-Crypto-Trader`.*

A full-stack crypto trading assistant: a **FastAPI** backend that runs several independent trading strategies and data collectors, and a **Next.js** dashboard to watch and control them. Most strategies trade **on paper** (simulated wallets on live market prices). Real-money execution only happens where a strategy's live switches are explicitly turned on.

> ⚠️ **Not financial advice.** This is experimental software. Strategies can lose money, simulated results overstate live results, and crypto tokens (especially meme coins) can go to zero. Use real funds only if you understand and accept that risk.

---

## Features

| Area | What it does | Mode |
|---|---|---|
| **Strategy #1: BTC trend pullback** (`strategy.py`, `trader.py`) | Long-only BTC/USDT 1h trend-following: buys pullbacks in an uptrend. The same rules drive the backtest (`backtest.py`) and the live trader. | Paper wallet (`paper_engine.py`, 5,000 USDT start) |
| **Strategy #2: Pivot bracket** (`pivot_*.py`) | Pivot-level entries with laddered exits on its own isolated wallet. The recompute interval is configurable. | Paper |
| **Strategy Three: Manual BTC desk** (`manual_engine.py`) | Place BTC buys and limits by hand; isolated wallet. | Paper |
| **Strategy #4: Smart-money copy trade** (`copytrade_*.py`, `smart_wallet_finder.py`) | Watches selected Solana wallets (via Helius / QuickNode feeds) and mirrors their buys, with safety filters and rug checks. Includes a manual Solana desk. | Sim + optional **live** via Jupiter (two switches, see below) |
| **Strategy #5: Liquidity scalper** (`liquidity_*.py`) | Scalps BTC liquidity sweeps from the Binance WebSocket stream. | Paper |
| **Robinhood Chain manual desk** (`robinhood_*.py`) | Manual buy/sell with TP/SL on Robinhood Chain (chain 4663), routed through Relay. | Paper by default; live behind two switches |
| **Robinhood Chain system (RHC)** (`rhc_*.py`) | Autonomous token discovery, safety screening (buy/sell simulation, contract permissions, holders, flow, rug detection), signals, a risk engine and **paper trading** with validation. | **Paper only**; live is disabled in code |
| **Pump top-gainer wallet finder** (`pumpgainer_*.py`) | Ranks Solana wallets by realized performance on top-gaining tokens. | Research |
| **Market data** | Candles, indicators (`ta`, TAAPI), Fear & Greed, futures stats, Google Trends, news, on-chain stats, pivots | Background collectors (APScheduler) |

The dashboard pages are Dashboard, Market Analysis, Liquidity Pool, Portfolio, Watchlist, AI Signals, Copy Trade (with the Solana and Robinhood manual desks), **Robinhood Chain**, and News.

## Architecture

```
frontend/ (Next.js 16, Tailwind v4)  ──HTTPS + JWT──►  backend/ (FastAPI, Uvicorn)
   Netlify / AWS Amplify / Azure SWA                       Azure App Service
                                                             │  background threads: strategies,
                                                             │  copy-trade loop, scalper, RHC indexer
                                                             │  APScheduler: data collectors
                                                             ▼
                                  PostgreSQL (Supabase)  ◄── SQLAlchemy
                                  ├─ main database   (DATABASE_URL)
                                  └─ RHC database    (RHC_DATABASE_URL, separate, free tier)
External: Binance API/WebSocket · Helius · QuickNode · Jupiter · DexScreener ·
          GeckoTerminal · DefiLlama · Relay · Robinhood Chain RPC · TAAPI · CryptoCompare
```

- **Auth:** `POST /api/login` returns a JWT. A global middleware protects every `/api/*` route except the login, the two webhook endpoints and `/api/liquidity*`. The frontend attaches the token to every API call automatically.
- **Isolation:** each strategy has its own wallet and tables, and its loop runs on its own thread with its own error handling.
- **Database tables** are created on startup (`ensure_initialized()`) with additive migrations; there is no Alembic.

## Repository layout

```
backend/
  main.py                FastAPI app, routers, startup (threads + scheduler)
  auth.py                login / JWT
  database.py, models.py SQLAlchemy engine + models (main database)
  trader.py, strategy.py, backtest.py, paper_engine.py     Strategy #1
  pivot_*.py                                               Strategy #2
  manual_engine.py                                         Strategy Three
  copytrade_*.py, smart_wallet_finder.py, solana_wallet.py Strategy #4
  liquidity_*.py                                           Strategy #5
  robinhood_*.py                                           Robinhood Chain manual desk
  rhc_*.py, contracts/                                     Robinhood Chain system (see docs)
  pumpgainer_*.py                                          Top-gainer wallet finder
  *_fetcher.py, data_collector.py, news_fetcher.py         Market-data collectors
  tests/                                                   pytest suite (offline)
  .env.example                                             documented env template (RHC section)
frontend/
  app/                   App Router pages + components (app/components/rhc/ for Robinhood Chain)
  lib/config.ts          backend URL (localhost:8000 when running locally)
  middleware.ts          redirects to /login without a token cookie
docs/robinhood-chain/    Robinhood Chain system docs (plan, architecture, screening, decisions,
                         validation, go-live checklist, deployment)
.github/workflows/       CI/CD to Azure (backend App Service, frontend Static Web Apps)
frontend/netlify.toml    Netlify build config (Next.js runtime plugin)
```

## Getting started (local)

### Prerequisites
- **Python 3.11 or 3.12.** CI uses 3.11. Python 3.13+/3.14 can't install some pinned packages (for example `pandas==2.2.0` and `pydantic==2.6.0`).
- **Node.js 20+** and npm.
- **A PostgreSQL database**, for example a free Supabase project.

### 1. Backend
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env`. It is git-ignored: **never commit it**. These are the core variables; the rest of each strategy's settings are optional with defaults in its `*_config.py`:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (main database) |
| `JWT_SECRET_KEY` | Long random secret for login tokens. **Required:** without it, a random key is used and everyone is logged out on each restart. |
| `BINANCE_API_KEY`, `BINANCE_SECRET_KEY` | Binance market data / account |
| `TAAPI_API_KEY`, `CRYPTOCOMPARE_API_KEY` | Indicator and news collectors |
| `HELIUS_API_KEY`, `HELIUS_WEBHOOK_URL`, `QUICKNODE_*` | Copy-trade wallet feeds |
| `HELIUS_WEBHOOK_SECRET`, `QUICKNODE_WEBHOOK_SECRET` | **Required** for the matching webhook: without its secret, a webhook rejects every call |
| `SOLANA_RPC_URL`, `SOLANA_PRIVATE_KEY`, `LIVE_TRADING_WALLET` | Copy-trade live execution only |
| `ROBINHOOD_RPC_URL`, `ROBINHOOD_PRIVATE_KEY`, `ROBINHOOD_EXPECTED_WALLET` | Robinhood manual desk live execution only |
| `RHC_ENABLED`, `RHC_DATABASE_URL` | Robinhood Chain system (off unless both are set). See `backend/.env.example`. |

Generate a JWT secret with:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Start the API:
```bash
uvicorn main:app --reload --port 8000
```

> ⚠️ **Starting `main.py` starts every strategy loop.** Before running it, check the live-money switches in your `.env` (see [Live trading switches](#live-trading-switches)). To run only the Robinhood Chain system, use `python rhc_indexer.py run`, which starts no other bots.

### 2. Frontend
```bash
cd frontend
npm ci
npm run dev          # http://localhost:3000
```
On `localhost` the frontend calls `http://localhost:8000` automatically. Elsewhere it uses `NEXT_PUBLIC_API_URL`, set at build time.

### 3. Log in
Log in with an `admin_users` account. To create or reset the `admin` user, run `python reset_password.py`. It asks for the new password (at least 12 characters) or reads `ADMIN_NEW_PASSWORD`, and never prints it.

## Tests
```bash
cd backend
python -m pytest tests -q
```
The suite runs **offline**: it uses fakes and recorded chain data and needs no database or network. The frontend has no unit tests yet. Check it with `npm run lint` and `npm run build`.

## Live trading switches
Real money only moves when **both** switches of a strategy are set for live:

| Strategy | Master switch (default) | Dry-run switch (default) |
|---|---|---|
| Copy trade (Solana, Jupiter) | `COPYTRADE_LIVE` (`false`) | `COPYTRADE_LIVE_DRYRUN` (`true`) |
| Robinhood manual desk (Relay) | `ROBINHOOD_LIVE_ENABLED` (`false`) | `ROBINHOOD_LIVE_DRYRUN` (`true`) |
| Robinhood Chain system | none: **disabled in code** | — |

Keep the defaults unless you intend to trade real funds. If you do, use a dedicated, low-balance wallet.

## Deployment
Pushing to `main` deploys automatically through GitHub Actions:
- **Backend** → Azure App Service (`.github/workflows/main_bushutrading.yml`; Python 3.11, dependencies installed by Oryx).
- **Frontend:** it can be hosted in three places:
  - **Netlify**, configured by `frontend/netlify.toml` with the Next.js runtime plugin;
  - **AWS Amplify**;
  - **Azure Static Web Apps**, deployed by `.github/workflows/azure-static-web-apps-*.yml`.
- **CORS:** the backend only accepts browser calls from the frontend addresses listed in `allow_origins` in `backend/main.py`. When you add a frontend host, add its exact URL there, or the browser will block every API call from it.

Set secrets **only** in the Azure App Service environment variables, never in the repository. To roll out the Robinhood Chain system, follow [`docs/robinhood-chain/DEPLOYMENT.md`](docs/robinhood-chain/DEPLOYMENT.md).

## Robinhood Chain system docs
- [Plan & research](docs/robinhood-chain/PLAN.md)
- [Architecture](docs/robinhood-chain/ARCHITECTURE.md)
- [Setup](docs/robinhood-chain/SETUP.md) · [Operations](docs/robinhood-chain/OPERATIONS.md)
- [Screening](docs/robinhood-chain/SCREENING.md) · [Signals & decisions](docs/robinhood-chain/DECISIONS.md)
- [Validation](docs/robinhood-chain/VALIDATION.md) · [Go-live checklist](docs/robinhood-chain/GO_LIVE_CHECKLIST.md)
- [Deployment](docs/robinhood-chain/DEPLOYMENT.md)

## Security
- **Never commit `.env` files.** `.gitignore` ignores `*.env` and `.env.*`; only `*.env.example` templates are tracked.
- **This repository is public.** `Binance-trading-assistant.env` was committed in the past. It's no longer tracked, but it remains in git history, so **every credential it contained must be treated as compromised and rotated.**
- **Login protection:** every `/api/*` route needs a valid token except `/api/login` and the two webhooks, which are exempted by exact path and check their own shared secret.
- **Robinhood desk live trades:** they send `ROBINHOOD_MAX_SLIPPAGE_BPS` to Relay, and refuse a quote whose value is more than `ROBINHOOD_MAX_PRICE_IMPACT` % below the market price.
- **Tests:** `tests/test_security.py` guards these rules against regressions.
- **Recommended:** enable GitHub **Secret scanning** and **Push protection** for this repository.

## Contributing
- **Branches:** create a branch from `main`, and open a pull request. Merging to `main` deploys to production.
- **Before pushing:** run the backend tests and `npm run build`.
- **New strategies:** keep each strategy isolated (its own config module, tables and thread), and guard its startup so a failure can't stop the backend from booting.
