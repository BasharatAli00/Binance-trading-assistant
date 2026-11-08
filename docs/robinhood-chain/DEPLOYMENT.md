# Robinhood Chain System: Deploying to Azure + Supabase

Everything ships **off by default**: merging changes nothing in production until `RHC_ENABLED=true` and `RHC_DATABASE_URL` are set on the App Service. Paper mode only, and live trading is disabled in code.

## 0. Before merging (security)
1. **Rotate the leaked secrets.**
   - `Binance-trading-assistant.env` is tracked in git and holds live keys, a Solana private key and the production database URL. Rotate all of them.
   - Remove the file from git (`git rm --cached Binance-trading-assistant.env`) and add `*.env` to `.gitignore`.
2. **Reset the dedicated RHC database password.** It was shared in a chat. Then update it everywhere it's used (`backend/.env`, and the Azure setting below).

## 1. Merge and deploy (switched off)
1. Open a pull request `new-feature → main`, review it, and merge. GitHub Actions deploys:
   - the backend → App Service `Bushutrading` (no new Python packages; `requirements.txt` is unchanged);
   - the frontend → Static Web Apps, with the new **Robinhood Chain** sidebar entry.
2. Check the backend still boots normally: existing pages work, and `GET /api/rhc/health` (when logged in) returns `"status": "disabled"`.

## 2. Turn it on (App Service → Settings → Environment variables)
| Name | Value |
|---|---|
| `RHC_DATABASE_URL` | the dedicated Supabase **Session pooler** URI (never the production DB) |
| `RHC_ENABLED` | `true` |

Save, then restart the App Service.

Also check these App Service settings:
- **General settings → Always On = On.** Without it the app sleeps, the indexer stops, and gaps appear. Downtime under ~1 day is caught up automatically; longer downtime is recorded as a gap.
- **Plan size:** the indexer keeps the active-pool registry and open candles in memory. Use at least a B1 plan [NEEDS VERIFICATION: measure memory in the first day].
- **Workers:** more than one worker is fine. A database lease lets only one write; the others show `standby_other_writer`.

## 3. Verify within the first hour (Robinhood Chain page → System Health tab)
- `service: running`, `indexer: live`, and lag under about 30 s.
- Data sources show OK counts rising. Occasional GeckoTerminal errors are normal on the free tier.
- **Discovery & Watchlist:** candidates appear within minutes, then screenings (`watch` or `rejected`, with codes).
- **Signals & Decisions:** setups appear only when conditions are met, which can take hours in quiet markets.
- **Storage:** the database percentage stays low. Check again after 24 h; expect roughly 5–10 MB per day.

## 4. Optional: indexer as its own process (recommended later)
Running indexing inside the web app competes with API traffic. To separate them:
- create a second App Service or WebJob that runs `cd backend && python rhc_indexer.py run`, with the same `RHC_DATABASE_URL` and `RHC_ENABLED=true`;
- set `RHC_ENABLED=false` on the web app.

The page keeps working because it reads from the database. Only the System Health tab's live process metrics are then visible in the indexer's own logs instead.

## 5. Operating it
- **Daily:** System Health (lag, errors, storage) and the Risk tab (kill switch, daily P&L).
- **Weekly:** the Performance & Validation tab. Everything will read *"insufficient sample"* for roughly **3+ weeks** (gate: 200 trades, 30 tokens, 21 days). Don't tune thresholds on a handful of trades.
- **Changing a threshold:** use an environment variable (see `backend/.env.example`), note the date, and compare backtests by their `config_hash`.
- **Emergency:** the Risk tab's **Activate kill switch** blocks every new paper entry. `RHC_ENABLED=false` plus a restart stops the whole subsystem. Neither touches the existing app.

## 6. Going live (not part of this project)
Only after `GET /api/rhc/go-live-gate` passes every automatic check on a real sample, and only through the separate, approved change described in [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md): a dedicated low-balance wallet, hard caps, a slippage limit and a small pilot.
