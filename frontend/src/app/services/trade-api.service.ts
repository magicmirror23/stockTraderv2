import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface TradeIntentRequest {
  ticker: string;
  side: 'buy' | 'sell';
  quantity: number;
  order_type: 'market' | 'limit';
  limit_price?: number;
  option_type?: 'CE' | 'PE';
  strike?: number;
  expiry?: string;
  strategy?: string;
}

export interface TradeIntent {
  intent_id: string;
  ticker: string;
  side: 'buy' | 'sell';
  quantity: number;
  order_type: 'market' | 'limit';
  limit_price: number | null;
  estimated_cost: number;
  status: string;
  option_type: string | null;
  strike: number | null;
  expiry: string | null;
  strategy: string | null;
  created_at: string;
}

export interface Execution {
  execution_id: string;
  intent_id: string;
  ticker: string;
  side: 'buy' | 'sell';
  quantity: number;
  filled_price: number;
  total_value: number;
  slippage: number;
  latency_ms: number;
  status: string;
  option_type: string | null;
  strike: number | null;
  expiry: string | null;
  strategy: string | null;
  executed_at: string;
}

@Injectable({ providedIn: 'root' })
export class TradeApiService {
  private readonly base = environment.apiUrl;

  constructor(private http: HttpClient) {}

  createIntent(request: TradeIntentRequest): Observable<TradeIntent> {
    return this.http.post<TradeIntent>(`${this.base}/trade_intent`, request);
  }

  execute(intentId: string): Observable<Execution> {
    return this.http.post<Execution>(`${this.base}/execute`, { intent_id: intentId });
  }
}
