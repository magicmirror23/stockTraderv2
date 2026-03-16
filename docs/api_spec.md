# StockTrader API Specification

> **Version:** 0.2.0  
> **Base URL:** `http://localhost:8000`  
> **Prefix:** `/api/v1`  
> **Schemas:** [`backend/api/schemas.py`](../backend/api/schemas.py)

---

## Table of Contents

1. [General Conventions](#general-conventions)
2. [Error Handling](#error-handling)
3. [Rate Limiting](#rate-limiting)
4. [Endpoints](#endpoints)
   - [GET /api/v1/health](#get-apiv1health)
   - [POST /api/v1/predict](#post-apiv1predict)
   - [POST /api/v1/predict/options](#post-apiv1predictoptions)
   - [POST /api/v1/batch_predict](#post-apiv1batch_predict)
   - [GET /api/v1/model/status](#get-apiv1modelstatus)
   - [POST /api/v1/model/reload](#post-apiv1modelreload)
   - [POST /api/v1/trade_intent](#post-apiv1trade_intent)
   - [POST /api/v1/execute (protected)](#post-apiv1execute-protected)
   - [POST /api/v1/backtest/run](#post-apiv1backtestrun)
   - [GET /api/v1/backtest/{job_id}/results](#get-apiv1backtestjob_idresults)
   - [POST /api/v1/paper/accounts](#post-apiv1paperaccounts)
   - [GET /api/v1/paper/accounts](#get-apiv1paperaccounts)
   - [GET /api/v1/paper/{id}/equity](#get-apiv1paperidequity)
   - [GET /api/v1/paper/{id}/metrics](#get-apiv1paperidmetrics)
   - [POST /api/v1/paper/{id}/order_intent](#post-apiv1paperidorder_intent)
   - [POST /api/v1/paper/{id}/replay](#post-apiv1paperidreplay)
   - [WS /api/v1/stream/price/{symbol}](#ws-apiv1streampricesymbol)
   - [GET /api/v1/stream/price/{symbol} (SSE)](#get-apiv1streampricesymbol-sse)
   - [POST /api/v1/retrain (protected)](#post-apiv1retrain-protected)
   - [GET /api/v1/metrics](#get-apiv1metrics)
   - [POST /api/v1/drift/check (protected)](#post-apiv1driftcheck-protected)
   - [GET /api/v1/canary/status](#get-apiv1canarystatus)
5. [Prediction Entry Schema](#prediction-entry-schema)
6. [Option Signal Schema](#option-signal-schema)
7. [Greeks Schema](#greeks-schema)

---

## General Conventions

| Item | Convention |
|------|-----------|
| Content-Type | `application/json` |
| Date/time format | ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`) |
| Date-only fields | `YYYY-MM-DD` |
| IDs | UUID v4 |
| Authentication | Bearer token in `Authorization` header (required for protected endpoints) |
| Pagination | Not applicable in v1 (small result sets) |

---

## Error Handling

All errors return a JSON body conforming to `ErrorResponse`:

```json
{
  "detail": "Human-readable message",
  "code": "MACHINE_READABLE_CODE"
}
```

### Error Codes

| HTTP Status | Code | Description |
|-------------|------|-------------|
| 400 | `VALIDATION_ERROR` | Request body fails Pydantic validation |
| 401 | `UNAUTHORIZED` | Missing or invalid Bearer token |
| 403 | `FORBIDDEN` | Authenticated but insufficient permissions |
| 404 | `NOT_FOUND` | Resource does not exist |
| 409 | `CONFLICT` | Duplicate or conflicting operation |
| 422 | `UNPROCESSABLE_ENTITY` | Semantically invalid request (e.g. end_date < start_date) |
| 429 | `RATE_LIMIT_EXCEEDED` | Too many requests |
| 500 | `INTERNAL_ERROR` | Unexpected server error |
| 503 | `MODEL_UNAVAILABLE` | Model not loaded or currently reloading |

---

## Rate Limiting

| Endpoint Group | Limit | Window |
|----------------|-------|--------|
| `/predict`, `/batch_predict` | 60 requests | per minute per API key |
| `/execute` | 10 requests | per minute per API key |
| `/backtest/run` | 5 requests | per minute per API key |
| All other endpoints | 120 requests | per minute per API key |

Rate-limit headers returned on every response:

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 58
X-RateLimit-Reset: 1710286800
```

---

## Endpoints

---

### GET /api/v1/health

Health-check endpoint.

**Auth:** None  
**Tags:** `health`

#### Response `200 OK`

```json
{
  "status": "ok"
}
```

---

### POST /api/v1/predict

Generate a price prediction for a single ticker.

**Auth:** None  
**Tags:** `prediction`  
**Schema:** `PredictRequest` → `PredictResponse`

#### Request Body

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `ticker` | string | yes | 1–10 chars | Stock ticker symbol |
| `horizon_days` | integer | no (default 5) | 1–365 | Calendar days to predict ahead |

#### Example Request

```json
{
  "ticker": "AAPL",
  "horizon_days": 7
}
```

#### Response `200 OK`

| Field | Type | Description |
|-------|------|-------------|
| `ticker` | string | Echoed ticker |
| `horizon_days` | integer | Echoed horizon |
| `predicted_price` | float | Predicted closing price |
| `confidence` | float (0–1) | Model confidence score |
| `model_version` | string | Semantic version of the model |
| `timestamp` | datetime | UTC time of prediction |
| `prediction` | PredictionEntry | Full prediction record |

#### Example Response

```json
{
  "ticker": "AAPL",
  "horizon_days": 7,
  "predicted_price": 198.45,
  "confidence": 0.87,
  "model_version": "v2.3.1",
  "timestamp": "2026-03-12T14:30:00Z",
  "prediction": {
    "ticker": "AAPL",
    "action": "buy",
    "confidence": 0.87,
    "expected_return": 0.032,
    "model_version": "v2.3.1",
    "timestamp": "2026-03-12T14:30:00Z"
  }
}
```

#### Errors

| Status | Code | When |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | Ticker empty or > 10 chars; horizon out of range |
| 503 | `MODEL_UNAVAILABLE` | Model not loaded |

---

### POST /api/v1/batch_predict

Generate predictions for multiple tickers in a single request.

**Auth:** None  
**Tags:** `prediction`  
**Schema:** `BatchPredictRequest` → `BatchPredictResponse`

#### Request Body

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `tickers` | string[] | yes | 1–50 items | List of ticker symbols |
| `horizon_days` | integer | no (default 5) | 1–365 | Calendar days to predict ahead |

#### Example Request

```json
{
  "tickers": ["AAPL", "GOOGL", "MSFT"],
  "horizon_days": 14
}
```

#### Response `200 OK`

| Field | Type | Description |
|-------|------|-------------|
| `predictions` | PredictionEntry[] | One entry per ticker |
| `model_version` | string | Model version used |
| `timestamp` | datetime | UTC time of prediction batch |

#### Example Response

```json
{
  "predictions": [
    {
      "ticker": "AAPL",
      "action": "buy",
      "confidence": 0.87,
      "expected_return": 0.032,
      "model_version": "v2.3.1",
      "timestamp": "2026-03-12T14:30:00Z"
    },
    {
      "ticker": "GOOGL",
      "action": "hold",
      "confidence": 0.62,
      "expected_return": 0.005,
      "model_version": "v2.3.1",
      "timestamp": "2026-03-12T14:30:00Z"
    },
    {
      "ticker": "MSFT",
      "action": "sell",
      "confidence": 0.74,
      "expected_return": -0.018,
      "model_version": "v2.3.1",
      "timestamp": "2026-03-12T14:30:00Z"
    }
  ],
  "model_version": "v2.3.1",
  "timestamp": "2026-03-12T14:30:00Z"
}
```

#### Errors

| Status | Code | When |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | Empty list, > 50 tickers, or invalid ticker format |
| 503 | `MODEL_UNAVAILABLE` | Model not loaded |

---

### GET /api/v1/model/status

Retrieve the current model state.

**Auth:** None  
**Tags:** `model`  
**Schema:** → `ModelStatusResponse`

#### Response `200 OK`

| Field | Type | Description |
|-------|------|-------------|
| `model_version` | string | Currently loaded version |
| `status` | string | `loaded`, `loading`, or `error` |
| `last_trained` | datetime \| null | When the model was last trained |
| `accuracy` | float \| null | Latest evaluation accuracy (0–1) |

#### Example Response

```json
{
  "model_version": "v2.3.1",
  "status": "loaded",
  "last_trained": "2026-03-10T08:00:00Z",
  "accuracy": 0.91
}
```

---

### POST /api/v1/model/reload

Trigger a hot-reload of the prediction model.

**Auth:** None (consider protecting in production)  
**Tags:** `model`  
**Schema:** `ModelReloadRequest` → `ModelReloadResponse`

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | string \| null | no | Specific version to load; loads latest if omitted |

#### Example Request

```json
{
  "version": "v2.4.0"
}
```

#### Response `200 OK`

```json
{
  "message": "Model reload initiated.",
  "new_version": "v2.4.0",
  "status": "loading"
}
```

#### Errors

| Status | Code | When |
|--------|------|------|
| 404 | `NOT_FOUND` | Requested version does not exist |
| 409 | `CONFLICT` | A reload is already in progress |

---

### POST /api/v1/trade_intent

Declare an intent to trade. Validates parameters and returns an estimated cost but does **not** execute.

**Auth:** None  
**Tags:** `trading`  
**Schema:** `TradeIntentRequest` → `TradeIntentResponse`

#### Request Body

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `ticker` | string | yes | 1–10 chars | Ticker symbol |
| `side` | string | yes | `buy` \| `sell` | Order side |
| `quantity` | integer | yes | 1–100,000 | Number of shares |
| `order_type` | string | no (default `market`) | `market` \| `limit` | Order type |
| `limit_price` | float \| null | conditional | > 0 | Required when `order_type` is `limit` |

#### Validation Rules

- `limit_price` **must** be provided when `order_type` is `limit`.
- `limit_price` **must** be `null` or omitted when `order_type` is `market`.

#### Example Request

```json
{
  "ticker": "TSLA",
  "side": "buy",
  "quantity": 100,
  "order_type": "limit",
  "limit_price": 245.00
}
```

#### Response `201 Created`

```json
{
  "intent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "ticker": "TSLA",
  "side": "buy",
  "quantity": 100,
  "order_type": "limit",
  "limit_price": 245.00,
  "estimated_cost": 24500.00,
  "status": "pending",
  "created_at": "2026-03-12T14:35:00Z"
}
```

#### Errors

| Status | Code | When |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | Invalid ticker, quantity ≤ 0, missing limit_price for limit order |
| 404 | `NOT_FOUND` | Ticker not found in tradeable universe |

---

### POST /api/v1/execute (protected)

Execute a previously validated trade intent.

**Auth:** Bearer token required  
**Tags:** `trading`  
**Schema:** `ExecuteRequest` → `ExecuteResponse`

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `intent_id` | UUID | yes | ID returned by `/trade_intent` |

#### Example Request

```json
{
  "intent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

#### Response `200 OK`

```json
{
  "execution_id": "f9e8d7c6-b5a4-3210-fedc-ba0987654321",
  "intent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "ticker": "TSLA",
  "side": "buy",
  "quantity": 100,
  "filled_price": 244.80,
  "total_value": 24480.00,
  "status": "filled",
  "executed_at": "2026-03-12T14:36:00Z"
}
```

#### Errors

| Status | Code | When |
|--------|------|------|
| 401 | `UNAUTHORIZED` | Missing or invalid token |
| 404 | `NOT_FOUND` | `intent_id` does not exist |
| 409 | `CONFLICT` | Intent already executed |

---

### POST /api/v1/backtest/run

Submit a back-test simulation job (asynchronous).

**Auth:** None  
**Tags:** `backtest`  
**Schema:** `BacktestRunRequest` → `BacktestRunResponse`

#### Request Body

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `tickers` | string[] | yes | 1–50 items | Tickers to include in simulation |
| `start_date` | string | yes | `YYYY-MM-DD` | Simulation start |
| `end_date` | string | yes | `YYYY-MM-DD` | Simulation end |
| `initial_capital` | float | no (default 100000) | > 0 | Starting capital in USD |
| `strategy` | string | no (default `momentum`) | — | Strategy identifier |

#### Validation Rules

- `end_date` must be after `start_date`.
- `start_date` must not be in the future.

#### Example Request

```json
{
  "tickers": ["AAPL", "MSFT"],
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "initial_capital": 50000.0,
  "strategy": "momentum"
}
```

#### Response `202 Accepted`

```json
{
  "job_id": "11223344-5566-7788-99aa-bbccddeeff00",
  "status": "pending",
  "submitted_at": "2026-03-12T14:40:00Z"
}
```

#### Errors

| Status | Code | When |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | Invalid dates, empty tickers |
| 422 | `UNPROCESSABLE_ENTITY` | `end_date` < `start_date` |

---

### GET /api/v1/backtest/{job_id}/results

Retrieve results for a completed back-test.

**Auth:** None  
**Tags:** `backtest`  
**Schema:** → `BacktestResultsResponse`

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | UUID | Job ID returned by `/backtest/run` |

#### Response `200 OK`

```json
{
  "job_id": "11223344-5566-7788-99aa-bbccddeeff00",
  "status": "completed",
  "tickers": ["AAPL", "MSFT"],
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "initial_capital": 50000.0,
  "final_value": 58750.0,
  "total_return_pct": 17.5,
  "sharpe_ratio": 1.42,
  "max_drawdown_pct": -8.3,
  "trades": [
    {
      "date": "2024-01-15",
      "ticker": "AAPL",
      "side": "buy",
      "quantity": 50,
      "price": 185.20,
      "pnl": 0.0
    },
    {
      "date": "2024-06-10",
      "ticker": "AAPL",
      "side": "sell",
      "quantity": 50,
      "price": 210.40,
      "pnl": 1260.0
    }
  ],
  "completed_at": "2026-03-12T14:42:00Z"
}
```

#### Errors

| Status | Code | When |
|--------|------|------|
| 404 | `NOT_FOUND` | `job_id` does not exist |
| 202 | — | Job still running (body contains `{"job_id": "...", "status": "running"}`) |

---

## Prediction Entry Schema

Every prediction endpoint embeds `PredictionEntry` objects with this shape:

```json
{
  "ticker": "AAPL",
  "action": "buy",
  "confidence": 0.87,
  "expected_return": 0.032,
  "model_version": "v2.3.1",
  "timestamp": "2026-03-12T14:30:00Z"
}
```

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `ticker` | string | — | Stock ticker symbol |
| `action` | enum | `buy` \| `sell` \| `hold` | Recommended action |
| `confidence` | float | 0.0–1.0 | Model confidence |
| `expected_return` | float | — | Expected % return over horizon |
| `model_version` | string | semver | Model version that produced the prediction |
| `timestamp` | datetime | ISO-8601 UTC | When the prediction was generated |

> **Pydantic model:** `PredictionEntry` in [`backend/api/schemas.py`](../backend/api/schemas.py)
