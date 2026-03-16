import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface MarketStatus {
  phase: 'pre_open' | 'open' | 'post_close' | 'closed' | 'holiday' | 'weekend';
  message: string;
  ist_now: string;
  next_event: string;
  next_event_time: string;
  seconds_to_next: number;
  is_trading_day: boolean;
}

export interface AccountProfile {
  status: string;
  message: string;
  name?: string;
  client_id?: string;
  email?: string;
  phone?: string;
  broker?: string;
  balance?: number;
  net?: number;
  available_margin?: number;
  utilized_margin?: number;
  credentials_set?: Record<string, boolean>;
}

export interface BotStatus {
  running: boolean;
  paused: boolean;
  consent_pending: boolean;
  auto_resume_in: number | null;
  watchlist: string[];
  min_confidence: number;
  max_positions: number;
  position_size: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  cycle_interval: number;
  cycle_count: number;
  last_cycle: string | null;
  active_positions: number;
  positions: Record<string, any>;
  trades_today: any[];
  total_pnl: number;
  errors: string[];
}

@Injectable({ providedIn: 'root' })
export class MarketApiService {
  private readonly base = environment.apiUrl;

  constructor(private http: HttpClient) {}

  getMarketStatus(): Observable<MarketStatus> {
    return this.http.get<MarketStatus>(`${this.base}/market/status`);
  }

  getAccountProfile(): Observable<AccountProfile> {
    return this.http.get<AccountProfile>(`${this.base}/account/profile`);
  }

  getBotStatus(): Observable<BotStatus> {
    return this.http.get<BotStatus>(`${this.base}/bot/status`);
  }

  startBot(config?: any): Observable<any> {
    return this.http.post(`${this.base}/bot/start`, config || {});
  }

  stopBot(): Observable<any> {
    return this.http.post(`${this.base}/bot/stop`, {});
  }

  updateBotConfig(config: any): Observable<any> {
    return this.http.put(`${this.base}/bot/config`, config);
  }

  botConsent(resume: boolean): Observable<any> {
    return this.http.post(`${this.base}/bot/consent`, { resume });
  }
}
