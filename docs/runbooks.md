# Operational Runbooks

> StockTrader Backend v0.1.0

---

## Table of Contents

1. [Deploy to Staging](#deploy-to-staging)
2. [Deploy to Production](#deploy-to-production)
3. [Rotate Secrets and API Keys](#rotate-secrets-and-api-keys)
4. [Rollback Model Version](#rollback-model-version)
5. [Handle Failed Retrain](#handle-failed-retrain)
6. [Emergency Stop Trading Engine](#emergency-stop-trading-engine)
7. [Database Operations](#database-operations)

---

## Deploy to Staging

### Via CI/CD (recommended)

1. Push to `main` branch — CD workflow triggers automatically.
2. Monitor the GitHub Actions **CD** workflow run.
3. Run the smoke test:
   ```bash
   python scripts/smoke_test.py https://staging.yourdomain.com
   ```

### Manual deployment (Fly.io)

```bash
# Deploy to Fly.io
fly deploy --config backend/fly.toml

# Check status
fly status
fly logs
```

---

## Deploy to Production

1. **Tag a release** on the `main` branch:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
2. The CD workflow builds and pushes the tagged image.
3. Deploy via Helm:
   ```bash
   helm upgrade stocktrader infra/helm/stocktrader \
     --set image.tag=v1.0.0 \
     -n stocktrader-prod
   ```
4. Verify:
   ```bash
   python scripts/smoke_test.py https://api.yourdomain.com
   ```

---

## Rotate Secrets and API Keys

### Environment variables

2. Update secrets via Fly.io:
   ```bash
   fly secrets set SECRET_KEY="new-value"
   ```
3. The app restarts automatically after setting secrets.

### Database credentials

1. Update `DATABASE_URL` in your secret manager.
2. **Do NOT** update the running database password until the new credential is deployed.
3. Rotate in this order:
   - Create new DB user/password
   - Deploy app with new credentials
   - Verify connectivity
   - Remove old DB user

### API keys (broker, data providers)

1. Generate new key from provider dashboard.
2. Update in secret manager.
3. Restart the service.
4. Verify by checking logs for successful API calls.

---

## Rollback Model Version

### Via API

```bash
curl -X POST http://localhost:8000/api/v1/model/reload \
  -H "Content-Type: application/json" \
  -d '{"version": "v20260310.080000"}'
```

### Manual rollback

1. Check available versions:
   ```bash
   cat models/registry.json | python -m json.tool
   ```
2. Update the `latest` field in `models/registry.json` to the desired version.
3. Call the reload endpoint or restart the service.

### Verify

```bash
curl http://localhost:8000/api/v1/model/status
```

---

## Handle Failed Retrain

### Symptoms

- `/api/v1/retrain` returns 500
- Logs show training errors
- Model accuracy drops significantly

### Steps

1. **Check logs:**
   ```bash
   docker logs stocktrader-api --tail 100
   ```

2. **Check data pipeline:**
   ```bash
   python -m backend.prediction_engine.data_pipeline.validation storage/raw
   ```

3. **Verify feature store:**
   ```bash
   python -c "from backend.prediction_engine.feature_store.feature_store import build_features; print(build_features(['RELIANCE']).shape)"
   ```

4. **If data is corrupted**, re-download:
   ```bash
   python scripts/sample_data/download_sample.py
   ```

5. **Rollback the model** to the last known good version (see above).

6. **Retry retrain** after fixing the root cause:
   ```bash
   curl -X POST http://localhost:8000/api/v1/retrain \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```

---

## Emergency Stop Trading Engine

### Immediate stop

1. Set `PAPER_MODE=true` in environment:
   ```bash
   fly secrets set PAPER_MODE=true
   ```

2. **Block the execute endpoint** at the load balancer / ingress level if needed.

3. **Review open orders:**
   ```sql
   SELECT * FROM orders WHERE status = 'pending' ORDER BY created_at DESC;
   ```

4. **Cancel pending orders** via the adapter:
   ```python
   from backend.trading_engine.angel_adapter import AngelPaperAdapter
   adapter = AngelPaperAdapter()
   adapter.cancel_order("ORDER_ID")
   ```

### Post-incident

1. Review audit logs:
   ```sql
   SELECT * FROM audit_log WHERE event LIKE 'ORDER%' ORDER BY timestamp DESC LIMIT 50;
   ```
2. Document the incident and update this runbook as needed.

---

## Database Operations

### Run migrations

```bash
# Create tables (using SQLAlchemy)
python -c "from backend.db.session import engine, Base; from backend.db.models import *; Base.metadata.create_all(bind=engine)"
```

### Backup

```bash
pg_dump -U stocktrader -h localhost stocktrader > backup_$(date +%Y%m%d).sql
```

### Restore

```bash
psql -U stocktrader -h localhost stocktrader < backup_20260312.sql
```
