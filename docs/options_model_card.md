# Options Model Card

## Model Overview

**Name:** StockTrader Options Ensemble  
**Version:** 1.0.0  
**Type:** Stacked Ensemble (LightGBM + XGBoost + LSTM) with isotonic calibration  
**Target:** Binary classification — predict whether an option will be profitable within the given horizon.

## Intended Use

- Generate directional signals for NSE/BSE equity options (CE and PE).
- Provide calibrated confidence scores for position sizing in paper trading.
- Power the option strategy builder (single-leg, vertical spreads, iron condors, covered calls).

## Training Data

| Property | Value |
|---|---|
| Source | Yahoo Finance OHLCV + option chains |
| Period | Rolling 2-year window |
| Symbols | NIFTY, BANKNIFTY, top-50 F&O stocks |
| Features | ~60 equity + ~19 option-specific |
| Label | 1 if option P&L > 0 at expiry, else 0 |

### Key Features

- **Equity:** RSI, MACD, Bollinger Bands, ATR, volume z-score, moving averages, momentum
- **Options:** Implied volatility rank, OI change, put-call ratio, estimated Greeks (delta, gamma, theta, vega)
- **Sentiment:** Keyword-based news sentiment scores
- **Macro:** (placeholder for VIX, bond yields, etc.)

## Architecture

```
┌──────────┐  ┌──────────┐  ┌──────────┐
│ LightGBM │  │ XGBoost  │  │  LSTM    │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │              │              │
     └──── OOF predictions ───────┘
                    │
            ┌───────┴───────┐
            │ Meta-Learner  │
            │ (LogisticReg) │
            └───────┬───────┘
                    │
          ┌─────────┴─────────┐
          │ Isotonic           │
          │ Calibration        │
          └────────────────────┘
```

## Evaluation

| Metric | Value |
|---|---|
| Accuracy | ~58-62% (backtest) |
| F1 Score | ~0.55-0.60 |
| Brier Score | ~0.22-0.25 |
| Calibration | Isotonic (CalibratedClassifierCV) |

### Backtesting

- Backtested with realistic slippage (0.1% equity, 0.3% options) and commission.
- Walk-forward validation with nested time-series cross-validation (5 splits).
- Execution slippage logged per-trade for ongoing evaluation.

## Limitations

1. **Liquidity assumption:** Model assumes sufficient liquidity for option fills. Deep OTM options may have wide bid-ask spreads not captured by the slippage model.
2. **Event risk:** Model does not account for earnings announcements, RBI policy events, or corporate actions that cause regime shifts.
3. **IV surface simplification:** Greeks are estimated using Black-Scholes approximation with constant risk-free rate. Real IV surfaces have skew and term structure that are not fully modelled.
4. **News sentiment:** The keyword-based sentiment model is simplistic. No NLP or LLM-based sentiment analysis is currently used.
5. **Sample size:** Option chain data history is limited compared to equity OHLCV. Models may be less reliable for newly listed or illiquid options.
6. **Market regime:** Model performance degrades during regime changes (e.g., risk-off events, election volatility).

## Calibration Guidance

- **Confidence > 0.70:** Strong signal. Position sizing factor ≈ 0.84 (√0.70).
- **Confidence 0.55–0.70:** Moderate signal. Reduce position sizing proportionally.
- **Confidence < 0.55:** Below threshold. Signal is ignored by the order manager.
- **Calibration score** is reported per prediction. A score closer to 1.0 indicates better-calibrated probabilities.

### Position Sizing

Position sizes are determined by the calibrated confidence via a concave (square-root) mapping:

$$\text{size\_factor} = \sqrt{\text{confidence}}$$

This ensures marginal confidence gains produce diminishing position size increases.

## Drift Detection

- **KS test** on each feature (p-value threshold: 0.1).
- **PSI** on prediction distribution (threshold: 0.2).
- Alerts fire via Grafana when drift is detected.
- Automated nightly retrain via Celery resets drift.

## Reproducibility

Each prediction includes:
- `model_version`: Semantic version of the ensemble
- `model_seed`: Random seed used during training
- `feature_version`: Feature pipeline version
- `training_data_snapshot_id`: SHA-256 hash of training data
- `shap_top_features`: Top-5 SHAP feature contributors

## Responsible Use

- **Paper trading only** by default. Live execution requires explicit enablement.
- No financial advice is provided. Use at your own risk.
- The model is not audited for regulatory compliance.
- Users should verify signals with their own analysis before trading.

## Change Log

| Date | Version | Changes |
|---|---|---|
| 2025-01-01 | 1.0.0 | Initial release with LightGBM + XGBoost + LSTM ensemble |
