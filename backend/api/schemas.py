"""Pydantic request / response models for the StockTrader API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared / common
# ---------------------------------------------------------------------------


class ActionEnum(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class OptionStrategy(str, Enum):
    SINGLE = "single"
    VERTICAL_SPREAD = "vertical_spread"
    IRON_CONDOR = "iron_condor"
    COVERED_CALL = "covered_call"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorResponse(BaseModel):
    """Standard error envelope returned for 4xx / 5xx responses."""

    detail: str = Field(..., description="Human-readable error message.")
    code: str = Field(
        ...,
        description="Machine-readable error code (e.g. VALIDATION_ERROR).",
    )


# ---------------------------------------------------------------------------
# Option Greeks
# ---------------------------------------------------------------------------


class Greeks(BaseModel):
    """Option Greeks snapshot."""

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: Optional[float] = None
    iv: Optional[float] = Field(None, description="Implied volatility.")


# ---------------------------------------------------------------------------
# Streaming / live chart events
# ---------------------------------------------------------------------------


class PriceTickEvent(BaseModel):
    """Compact JSON event for live price stream."""

    symbol: str
    timestamp: datetime
    price: float
    volume: int
    bid: Optional[float] = None
    ask: Optional[float] = None


# ---------------------------------------------------------------------------
# Prediction entry (shared shape)
# ---------------------------------------------------------------------------


class PredictionThresholdContext(BaseModel):
    """Decision gates that the live signal had to clear."""

    buy_threshold: Optional[float] = None
    sell_threshold: Optional[float] = None
    min_signal_confidence: Optional[float] = None
    confidence_gap: Optional[float] = None
    edge_score: Optional[float] = None


class PredictionDriver(BaseModel):
    """Single human-readable model driver used in the explanation panel."""

    feature: str
    label: str
    value: float
    direction: str
    insight: str


class PredictionExplanation(BaseModel):
    """Human-readable explanation of why the model chose an action."""

    summary: str
    confidence_band: str
    market_regime: str
    news_regime: str
    decision_gate: str
    drivers: list[PredictionDriver] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    thresholds: PredictionThresholdContext = Field(default_factory=PredictionThresholdContext)


class PredictionEntry(BaseModel):
    """Single prediction record included in every predict response."""

    ticker: str
    action: ActionEnum
    confidence: float = Field(..., ge=0.0, le=1.0)
    expected_return: float = Field(
        ..., description="Expected percentage return over the horizon."
    )
    model_version: str = Field(
        ..., examples=["v2.3.1"],
        description="Semantic version of the model that produced this prediction.",
    )
    model_seed: Optional[int] = None
    feature_version: Optional[str] = None
    training_data_snapshot_id: Optional[str] = None
    calibration_score: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Calibration quality score for this prediction.",
    )
    shap_top_features: Optional[list[str]] = Field(
        None, description="Top-5 SHAP feature contributions.",
    )
    explanation: Optional[PredictionExplanation] = None
    timestamp: datetime = Field(
        ..., description="UTC timestamp when prediction was generated."
    )


# ---------------------------------------------------------------------------
# POST /api/v1/predict
# ---------------------------------------------------------------------------


class PredictRequest(BaseModel):
    """Request body for single stock-price prediction."""

    ticker: str = Field(..., min_length=1, max_length=10, examples=["AAPL"])
    horizon_days: int = Field(
        default=5,
        ge=1,
        le=365,
        description="Number of calendar days to predict ahead.",
    )


class PredictResponse(BaseModel):
    """Response body for single stock-price prediction."""

    ticker: str
    horizon_days: int
    predicted_price: float = Field(
        ..., description="Predicted closing price at the horizon."
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    model_version: str = Field(..., examples=["v2.3.1"])
    timestamp: datetime
    prediction: PredictionEntry


# ---------------------------------------------------------------------------
# POST /api/v1/batch_predict
# ---------------------------------------------------------------------------


class BatchPredictRequest(BaseModel):
    """Request body for batch prediction."""

    tickers: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of ticker symbols (max 50).",
    )
    horizon_days: int = Field(default=5, ge=1, le=365)


class BatchPredictResponse(BaseModel):
    """Response body for batch prediction."""

    predictions: list[PredictionEntry]
    model_version: str
    timestamp: datetime


# ---------------------------------------------------------------------------
# GET /api/v1/model/status
# ---------------------------------------------------------------------------


class ModelStatusResponse(BaseModel):
    """Current state of the loaded prediction model."""

    model_version: str = Field(..., examples=["v2.3.1"])
    status: str = Field(
        ...,
        examples=["loaded"],
        description="One of: loaded, loading, error.",
    )
    last_trained: Optional[datetime] = None
    accuracy: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Latest evaluation accuracy.",
    )


# ---------------------------------------------------------------------------
# POST /api/v1/model/reload
# ---------------------------------------------------------------------------


class ModelReloadRequest(BaseModel):
    """Optional body when triggering model reload."""

    version: Optional[str] = Field(
        None,
        description="Specific model version to load; latest if omitted.",
    )


class ModelReloadResponse(BaseModel):
    """Acknowledgement of a model reload request."""

    message: str = Field(..., examples=["Model reload initiated."])
    new_version: str
    status: str = Field(..., examples=["loading"])


# ---------------------------------------------------------------------------
# POST /api/v1/trade_intent
# ---------------------------------------------------------------------------


class TradeIntentRequest(BaseModel):
    """Declare an intent to trade (pre-validation, no execution)."""

    ticker: str = Field(..., min_length=1, max_length=10)
    side: OrderSide
    quantity: int = Field(..., gt=0, le=100_000)
    order_type: OrderType = Field(default=OrderType.MARKET)
    limit_price: Optional[float] = Field(
        None, gt=0,
        description="Required when order_type is 'limit'.",
    )
    # Option fields
    option_type: Optional[OptionType] = None
    strike: Optional[float] = Field(None, gt=0)
    expiry: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    strategy: Optional[OptionStrategy] = None


class TradeIntentResponse(BaseModel):
    """Validated trade intent ready for execution."""

    intent_id: UUID
    ticker: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    limit_price: Optional[float] = None
    estimated_cost: float = Field(
        ..., description="Estimated total cost / proceeds in INR."
    )
    status: str = Field(default="pending", examples=["pending"])
    option_type: Optional[OptionType] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None
    strategy: Optional[OptionStrategy] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# POST /api/v1/execute  (protected)
# ---------------------------------------------------------------------------


class ExecuteRequest(BaseModel):
    """Execute a previously validated trade intent."""

    intent_id: UUID


class ExecuteResponse(BaseModel):
    """Confirmation of trade execution."""

    execution_id: UUID
    intent_id: UUID
    ticker: str
    side: OrderSide
    quantity: int
    filled_price: float
    total_value: float
    slippage: float = 0.0
    latency_ms: float = 0.0
    status: str = Field(..., examples=["filled"])
    option_type: Optional[OptionType] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None
    strategy: Optional[OptionStrategy] = None
    executed_at: datetime


# ---------------------------------------------------------------------------
# POST /api/v1/backtest/run
# ---------------------------------------------------------------------------


class BacktestRunRequest(BaseModel):
    """Launch a back-test simulation."""

    tickers: list[str] = Field(..., min_length=1, max_length=50)
    start_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        examples=["2024-01-01"],
        description="ISO-8601 date string.",
    )
    end_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        examples=["2024-12-31"],
    )
    initial_capital: float = Field(default=100_000.0, gt=0)
    strategy: str = Field(
        default="momentum",
        description="Strategy identifier.",
    )


class BacktestRunResponse(BaseModel):
    """Acknowledgement that a back-test job has been queued."""

    job_id: UUID
    status: JobStatus = Field(default=JobStatus.PENDING)
    submitted_at: datetime


# ---------------------------------------------------------------------------
# GET /api/v1/backtest/{job_id}/results
# ---------------------------------------------------------------------------


class BacktestTrade(BaseModel):
    """Single simulated trade within a back-test."""

    date: str
    ticker: str
    side: OrderSide
    quantity: int
    price: float
    pnl: float


class BacktestResultsResponse(BaseModel):
    """Results of a completed back-test job."""

    job_id: UUID
    status: JobStatus
    tickers: list[str]
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float
    total_return_pct: float
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    trades: list[BacktestTrade]
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# POST /api/v1/predict/options
# ---------------------------------------------------------------------------


class OptionPredictRequest(BaseModel):
    """Request body for option signal prediction."""

    underlying: str = Field(..., min_length=1, max_length=10)
    strike: float = Field(..., gt=0)
    expiry: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    option_type: OptionType
    horizon_days: int = Field(default=5, ge=1, le=90)


class OptionSignal(BaseModel):
    """Option-specific prediction signal."""

    underlying: str
    strike: float
    expiry: str
    option_type: OptionType
    action: ActionEnum
    confidence: float = Field(..., ge=0.0, le=1.0)
    expected_return: float
    greeks: Greeks
    iv_percentile: Optional[float] = None
    model_version: str
    feature_version: Optional[str] = None
    calibration_score: Optional[float] = None
    shap_top_features: Optional[list[str]] = None
    explanation: Optional[PredictionExplanation] = None
    timestamp: datetime


class OptionPredictResponse(BaseModel):
    """Response body for option signal prediction."""

    signal: OptionSignal
    model_version: str
    timestamp: datetime


# ---------------------------------------------------------------------------
# Paper Trading Accounts
# ---------------------------------------------------------------------------


class PaperAccountCreateRequest(BaseModel):
    """Create a paper trading account."""

    initial_cash: float = Field(default=100_000.0, gt=0)
    label: Optional[str] = None


class PaperAccountResponse(BaseModel):
    """Paper account summary."""

    account_id: str
    cash: float
    equity: float
    positions: dict[str, int] = Field(default_factory=dict)
    created_at: datetime


class PaperOrderIntentRequest(BaseModel):
    """Order intent within a paper account."""

    ticker: str
    side: OrderSide
    quantity: int = Field(..., gt=0)
    order_type: OrderType = Field(default=OrderType.MARKET)
    limit_price: Optional[float] = None
    option_type: Optional[OptionType] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None
    strategy: Optional[OptionStrategy] = None


class PaperReplayRequest(BaseModel):
    """Replay a trading day on a paper account."""

    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    speed: float = Field(default=1.0, gt=0, le=100)


class EquityPoint(BaseModel):
    """Single equity curve data point."""

    date: str
    equity: float


# ---------------------------------------------------------------------------
# Model health / drift
# ---------------------------------------------------------------------------


class ModelHealthResponse(BaseModel):
    """Model health and drift indicators."""

    model_version: str
    prediction_drift_psi: Optional[float] = None
    feature_drift_detected: bool = False
    avg_latency_ms: Optional[float] = None
    p99_latency_ms: Optional[float] = None
    error_rate: Optional[float] = None
    status: str = Field(default="healthy")
