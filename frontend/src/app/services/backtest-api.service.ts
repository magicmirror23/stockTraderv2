import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface BacktestRunRequest {
  tickers: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  strategy: string;
}

export interface BacktestRunResponse {
  job_id: string;
  status: string;
  submitted_at: string;
}

export interface BacktestTrade {
  date: string;
  ticker: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  pnl: number;
}

export interface BacktestResults {
  job_id: string;
  status: string;
  tickers: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_value: number;
  total_return_pct: number;
  sharpe_ratio: number | null;
  max_drawdown_pct: number | null;
  trades: BacktestTrade[];
  completed_at: string | null;
}

@Injectable({ providedIn: 'root' })
export class BacktestApiService {
  private readonly base = environment.apiUrl;

  constructor(private http: HttpClient) {}

  runBacktest(request: BacktestRunRequest): Observable<BacktestRunResponse> {
    return this.http.post<BacktestRunResponse>(`${this.base}/backtest/run`, request);
  }

  getResults(jobId: string): Observable<BacktestResults> {
    return this.http.get<BacktestResults>(`${this.base}/backtest/${encodeURIComponent(jobId)}/results`);
  }
}
