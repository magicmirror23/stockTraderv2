import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { environment } from '../../environments/environment';

export interface AccountMetrics {
  sharpe: number | null;
  sortino: number | null;
  max_drawdown: number | null;
  win_rate: number | null;
  total_trades: number;
  net_pnl: number;
  profit_factor?: number | null;
  avg_win?: number | null;
  avg_loss?: number | null;
  best_trade?: number | null;
  worst_trade?: number | null;
  realized_pnl?: number;
  unrealized_pnl?: number;
  starting_cash?: number;
  current_cash?: number;
  current_equity?: number;
  total_return_pct?: number;
  cash_utilization_pct?: number;
  open_positions?: number;
  holdings?: PortfolioHolding[];
}

export interface PortfolioHolding {
  ticker: string;
  quantity: number;
  avg_price: number;
  last_price: number;
  cost_basis: number;
  market_value: number;
  unrealized_pnl: number;
  weight_pct: number;
}

export interface PaperAccount {
  account_id: string;
  cash: number;
  equity: number;
  created_at: string;
}

export interface EquityPoint {
  date: string;
  equity: number;
}

@Injectable({ providedIn: 'root' })
export class PaperApiService {
  private readonly base = environment.apiUrl;

  constructor(private http: HttpClient) {}

  createAccount(): Observable<PaperAccount> {
    return this.http.post<PaperAccount>(`${this.base}/paper/accounts`, { initial_cash: 100000 });
  }

  listAccounts(): Observable<PaperAccount[]> {
    return this.http.get<PaperAccount[]>(`${this.base}/paper/accounts`);
  }

  getEquity(accountId: string): Observable<EquityPoint[]> {
    return this.http.get<EquityPoint[]>(`${this.base}/paper/${accountId}/equity`);
  }

  getMetrics(accountId: string): Observable<AccountMetrics> {
    return this.http.get<AccountMetrics>(`${this.base}/paper/${accountId}/metrics`);
  }

  replay(accountId: string, date: string, speed: number = 1): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(`${this.base}/paper/${accountId}/replay`, { date, speed });
  }

  submitOrderIntent(accountId: string, intent: Record<string, unknown>): Observable<unknown> {
    return this.http.post(`${this.base}/paper/${accountId}/order_intent`, intent);
  }
}
