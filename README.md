# StockTrader

StockTrader is a full-stack stock and options prediction platform with paper trading, replay streaming, production-style automation controls, and optional Angel One SmartAPI live market integration.

The repository is now aligned to this deployment architecture:

- Backend: Render Python web service
- Frontend: Vercel
- Source control and CI/CD: GitHub

## Overview

StockTrader keeps all broker access on the backend. The Angular frontend talks only to your own FastAPI APIs plus your own WebSocket or SSE endpoints. If live broker auth fails, if the SmartAPI websocket drops, or if optional systems like Redis or MLflow are unavailable, the app degrades to replay mode or demo mode instead of crashing.

## Architecture

```text
Angular SPA on Vercel
  -> HTTPS API calls -> Render FastAPI backend
  -> WebSocket/SSE  -> Render FastAPI backend

Render backend
  -> Prediction APIs
  -> Paper trading
  -> Replay CSV streaming
  -> Optional Angel One SmartAPI live feed
  -> Optional Redis/Celery/MLflow/Sentry integrations
```

## Features

- FastAPI backend with centralized environment-driven config
- Render-friendly structured logging and consistent API error responses
- Paper trading and replay mode available without broker credentials
- Backend-only Angel One auth, session, feed token, and websocket handling
- Live tick normalization with replay fallback
- Account-state-aware trading execution for both real and paper accounts
- Dedicated equity bot plus a paper-safe options bot section
- Runtime health view for market state, bot readiness, and execution support
- Structured audit logging for bot actions, trade intents, executions, and fallback activation
- Demo prediction fallback when model artifacts are missing
- Detailed model metadata endpoint for version, feature contract, calibration, and fallback state
- Optional Redis, Celery, MLflow, and Sentry
- Angular frontend prepared for Vercel with Render-aware reconnect behavior

## Local Development

Supported local toolchain:

- Python 3.12
- Node.js 22.22.1 LTS

### Backend

```bash
cd stocktrader
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run_backend.py
```

If you want backend auto-reload while editing backend code only:

```bash
cd stocktrader
python run_backend.py --reload
```

If you prefer PowerShell wrappers, these do the same thing:

```bash
cd stocktrader
pwsh -File .\scripts\run_backend_dev.ps1 -NoReload
pwsh -File .\scripts\run_backend_dev.ps1
```

Backend health:

```bash
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/
```

### Frontend

```bash
cd stocktrader/frontend
npm install --legacy-peer-deps
npm start
```

The Angular dev server uses `proxy.conf.json` for `/api` calls during local development.

## Minimum Free Deployment Mode

This is the intended lowest-cost production-compatible mode:

- Render free web service for the backend
- Vercel for the frontend
- SQLite fallback when `DATABASE_URL` is not set
- Replay CSV feed enabled
- Paper trading enabled
- Demo prediction fallback enabled
- Live broker disabled unless you explicitly enable it
- Redis, Celery, MLflow, and Sentry left unset

In this mode the backend still starts and serves:

- `/`
- `/api/v1/health`
- prediction endpoints
- paper trading endpoints
- equity bot endpoints
- options bot endpoints
- bot runtime health endpoint
- stream status
- replay WebSocket and SSE feeds

## Automation Layer

The project now includes two automation profiles:

- Equity Bot
  - long-only equity automation
  - refreshes latest account state before every cycle
  - checks holdings, cash, open orders, and risk limits before entry or exit
- Options Bot
  - currently designed as a production-safe paper-mode automation path
  - uses underlying model signals to choose CE or PE contracts
  - applies option-specific sizing, expiry, strike-distance, and exit rules

Current bot API endpoints:

- `/api/v1/bot/start`
- `/api/v1/bot/stop`
- `/api/v1/bot/status`
- `/api/v1/bot/config`
- `/api/v1/bot/consent`
- `/api/v1/bot/options/start`
- `/api/v1/bot/options/stop`
- `/api/v1/bot/options/status`
- `/api/v1/bot/options/config`
- `/api/v1/bot/options/consent`
- `/api/v1/bot/runtime-health`
- `/api/v1/model/metadata`

Important options-bot note:

- the options bot is production-safe in paper mode
- a reusable option contract resolution layer now exists for expiry, strike, CE/PE selection, premium estimation, Greeks, and broker symbol lookup
- live options execution is still kept fail-safe by default until broker position and order normalization is fully validated end to end
- this is intentional, so the app fails safe instead of pretending live options are ready

## Backend Deployment to Render

Primary backend deployment uses native Python on Render, not Docker.

### Render build command

```bash
pip install -r requirements.txt
```

### Render start command

```bash
uvicorn backend.api.main:app --host 0.0.0.0 --port $PORT
```

### Render steps

1. Push the repository to GitHub.
2. In Render, create a new Web Service from the GitHub repo.
3. Set:
   - Root Directory: repository root
   - Runtime: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn backend.api.main:app --host 0.0.0.0 --port $PORT`
4. Set health check path to `/api/v1/health`.
5. Add environment variables from [backend/.env.example](C:\Users\merkr\OneDrive\Documents\New%20project\stocktrader\backend\.env.example).
6. For minimum free mode, set:
   - `APP_ENV=production`
   - `SECRET_KEY=<strong secret>`
   - `PAPER_MODE=true`
   - `ENABLE_DEMO_MODE=true`
   - `ENABLE_REPLAY_FALLBACK=true`
   - `ENABLE_LIVE_BROKER=false`
7. Deploy.

The included [render.yaml](C:\Users\merkr\OneDrive\Documents\New%20project\stocktrader\render.yaml) matches this setup and can be used as the source of truth.

## Frontend Deployment to Vercel

Vercel should host only the Angular build output.

### Vercel steps

1. Import the GitHub repository into Vercel.
2. Set the project root to `frontend`.
3. Vercel uses [frontend/vercel.json](C:\Users\merkr\OneDrive\Documents\New%20project\stocktrader\frontend\vercel.json).
4. Ensure the production backend URL in [frontend/src/environments/environment.production.ts](C:\Users\merkr\OneDrive\Documents\New%20project\stocktrader\frontend\src\environments\environment.production.ts) matches your Render backend URL.
5. Build output is `dist/stocktrader-frontend/browser`.
6. Deploy.

## Environment Variables

Important backend variables:

| Variable | Purpose | Required |
|---|---|---|
| `APP_ENV` | `development`, `testing`, `staging`, `production` | Yes |
| `SECRET_KEY` | API/auth secret | Yes in production |
| `API_V1_PREFIX` | API prefix, default `/api/v1` | No |
| `DATABASE_URL` | Optional Postgres URL | No |
| `REDIS_URL` | Optional Redis URL | No |
| `CELERY_BROKER_URL` | Optional Celery broker | No |
| `CELERY_RESULT_BACKEND` | Optional Celery backend | No |
| `ALLOWED_ORIGINS` | CORS allowlist | Recommended |
| `FRONTEND_URL` | Vercel frontend URL | Recommended |
| `PAPER_MODE` | Enable paper trading | No |
| `LOG_LEVEL` | Logging level | No |
| `MLFLOW_TRACKING_URI` | Optional MLflow endpoint | No |
| `SENTRY_DSN` | Optional Sentry DSN | No |
| `ANGEL_API_KEY` | Broker API key | Only for live broker |
| `ANGEL_CLIENT_ID` | Broker client ID | Only for live broker |
| `ANGEL_CLIENT_PIN` | Broker client pin/mpin | Only for live broker |
| `ANGEL_TOTP_SECRET` | Broker TOTP secret | Only for live broker |
| `MODEL_REGISTRY_PATH` | Model registry location | No |
| `STORAGE_PATH` | Storage root | No |
| `ENABLE_LIVE_BROKER` | Enable backend broker connection | No |
| `ENABLE_REPLAY_FALLBACK` | Replay fallback toggle | No |
| `ENABLE_DEMO_MODE` | Demo-safe fallback toggle | No |
| `AUTO_CONNECT_LIVE_FEED_ON_STARTUP` | Auto-connect live feed during backend startup | No |

## Demo Mode

Demo mode is designed for free-host and recruiter-friendly deployments:

- no live broker required
- no Redis required
- no MLflow required
- no trained model required

If no model artifacts are present, the backend returns deterministic demo-safe predictions instead of failing startup.

## Live Feed via Angel One SmartAPI Through Backend

Broker credentials are never exposed to the frontend.

The backend handles:

1. TOTP generation from `ANGEL_TOTP_SECRET`
2. SmartAPI session creation
3. feed token acquisition
4. websocket connection
5. subscription management
6. tick normalization
7. fanout to frontend clients through your own `/api/v1/stream/*` endpoints

If auth or websocket setup fails, the backend stays online and falls back to replay or unavailable mode.

## Replay Fallback Mode

Replay fallback is the default resilience path for:

- missing broker credentials
- Render cold starts
- SmartAPI auth failures
- SmartAPI websocket failures
- temporary live-feed outages

Frontend stream services now expose states such as:

- connected
- reconnecting
- replay mode
- unavailable
- waking backend

## Known Free-Tier Limitations

- Render free services can sleep after inactivity
- first request after sleep may take time while the backend wakes
- websocket clients may need to reconnect after a sleep cycle
- optional background jobs are synchronous when Redis/Celery is not configured
- MLflow features are disabled unless explicitly configured

This repository now treats those limitations as expected behavior and degrades gracefully.

## Testing

Run backend tests:

```bash
cd stocktrader
pytest backend/tests -q
```

Run frontend build verification:

```bash
cd stocktrader/frontend
npm ci
npx ng build --configuration production
```

## Frontend UX

The bot panel now includes:

- `Equity Bot` tab
- `Options Bot` tab
- `Runtime Health` tab

Most major sections also expose hover descriptions so first-time users can understand what each section does and how to use it.

## CI/CD

The repository includes:

- [backend-ci.yml](C:\Users\merkr\OneDrive\Documents\New%20project\stocktrader\.github\workflows\backend-ci.yml)
- [frontend-ci.yml](C:\Users\merkr\OneDrive\Documents\New%20project\stocktrader\.github\workflows\frontend-ci.yml)
- existing deployment workflows for GitHub-based automation

For dashboard follow-up, you still need to:

1. set Render environment variables
2. set the production backend URL in the Angular production environment
3. connect the GitHub repo to Render and Vercel
4. add any deployment secrets needed by your GitHub workflows
