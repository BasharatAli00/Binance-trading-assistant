# Robinhood Chain System: Setup

The system is **off by default**. It never writes to the production database and **never trades**: it runs in paper mode only, and live trading is disabled in code.

## 1. Dedicated database
1. Create a separate free Supabase project (for example `robinhood-chain-data`).
2. Open **Connect → Connection String → Session pooler** and copy the URI.
3. Put the project's database password into the URI. Letters and numbers only is simplest; anything else must be URL-encoded.

Tables are created automatically on first start. All of them are prefixed `rhc_`.

## 2. Environment variables
Add these to `backend/.env` locally. On Azure, add them under **App Service → Settings → Environment variables**.

```
RHC_ENABLED=true
RHC_DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Every other setting has a safe default. They're documented in [`backend/.env.example`](../../backend/.env.example) and [`backend/rhc_config.py`](../../backend/rhc_config.py).

## 3. Ways to run

| Mode | How | When |
|---|---|---|
| Inside the backend | Set `RHC_ENABLED=true`. `main.py` starts RHC on background threads at startup. | Default on Azure App Service |
| Standalone process | `cd backend && python rhc_indexer.py run` | Local testing, or a separate Azure WebJob/Container (recommended later) |

**Only one writer runs at a time.** A lease row in `rhc_lease` guarantees it: the owner renews it every 20 s and it expires after 120 s. A second process (or a second Gunicorn/Uvicorn worker) waits in `standby_other_writer` and takes over if the owner dies. Postgres advisory locks were tried first and rejected: behind the Supabase pooler they outlive the process that took them.

> ⚠️ Running the full backend locally (`uvicorn main:app`) also starts **all the existing trading bots** with whatever `backend/.env` contains, which may include live-money settings. To test RHC alone, use the standalone mode.

## 4. Check it's working
- `GET /api/rhc/health` (requires login; same JWT as the rest of the API). Check that `service.status` is `running`, `indexer.lag_blocks` is small, `indexer.mode` is `live`, and `storage.pct` is well below 70.
- `GET /api/rhc/pools/tracked` lists the pools whose candles are being stored.
- `GET /api/rhc/candles?pool_id=<pool>&tf=60` (or `tf=300`) returns OHLCV candles plus flow.

## 5. Tests
```
cd backend
python -m pytest tests -q
```
The tests use recorded real chain logs (`tests/fixtures/rhc_logs.json`) and fakes. They need no network and no database. To refresh the fixtures, run `python tests/fixtures/record_rhc_fixtures.py`, which is read-only against the public RPC.

## 6. Turning it off
Set `RHC_ENABLED=false`, or remove the variable, and restart. Nothing else in the app changes.
