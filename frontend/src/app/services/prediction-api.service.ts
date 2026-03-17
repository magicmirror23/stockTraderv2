import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { environment } from '../../environments/environment';

export interface PredictionThresholdContext {
  buy_threshold?: number;
  sell_threshold?: number;
  min_signal_confidence?: number;
  confidence_gap?: number;
  edge_score?: number;
}

export interface PredictionDriver {
  feature: string;
  label: string;
  value: number;
  direction: 'bullish' | 'bearish' | 'neutral' | string;
  insight: string;
}

export interface PredictionExplanation {
  summary: string;
  confidence_band: string;
  market_regime: string;
  news_regime: string;
  decision_gate: string;
  drivers: PredictionDriver[];
  risk_flags: string[];
  thresholds: PredictionThresholdContext;
}

export interface PredictionResult {
  ticker: string;
  action: 'buy' | 'sell' | 'hold';
  confidence: number;
  expected_return: number;
  model_version: string;
  calibration_score?: number;
  shap_top_features?: string[];
  explanation?: PredictionExplanation;
  timestamp: string;
}

export interface Greeks {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho?: number;
  iv?: number;
}

export interface OptionSignal {
  underlying: string;
  strike: number;
  expiry: string;
  option_type: 'CE' | 'PE';
  action: 'buy' | 'sell' | 'hold';
  confidence: number;
  expected_return: number;
  greeks: Greeks;
  iv_percentile?: number;
  model_version: string;
  calibration_score?: number;
  shap_top_features?: string[];
  explanation?: PredictionExplanation;
  timestamp: string;
}

@Injectable({ providedIn: 'root' })
export class PredictionApiService {
  private readonly base = environment.apiUrl;

  constructor(private http: HttpClient) {}

  predict(ticker: string, horizon: string = '1d'): Observable<PredictionResult> {
    const horizonDays = Number.parseInt(horizon, 10) || 1;
    return this.http
      .post<{ prediction: PredictionResult }>(`${this.base}/predict`, { ticker, horizon_days: horizonDays })
      .pipe(map(res => res.prediction));
  }

  predictOptions(underlying: string, strike: number, expiry: string, optionType: 'CE' | 'PE'): Observable<{ signal: OptionSignal }> {
    return this.http.post<{ signal: OptionSignal }>(`${this.base}/predict/options`, {
      underlying, strike, expiry, option_type: optionType,
    });
  }

  batchPredict(tickers: string[]): Observable<PredictionResult[]> {
    return this.http.post<{ predictions: PredictionResult[] }>(`${this.base}/batch_predict`, { tickers })
      .pipe(map(res => res.predictions));
  }

  modelStatus(): Observable<unknown> {
    return this.http.get(`${this.base}/model/status`);
  }
}
