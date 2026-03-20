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

export interface BotRuntimeHealth {
  bot_type: string;
  bot_label: string;
  service_mode: string;
  run_mode: string;
  paper_mode: boolean;
  live_broker_enabled: boolean;
  market_phase: string;
  market_message: string;
  account_mode: string;
  paper_only: boolean;
  live_execution_supported: boolean;
  current_mode_supported: boolean;
  last_signal_scan: string | null;
  last_trade_at: string | null;
  last_account_refresh_error: string | null;
  last_cycle_error: string | null;
}

export interface BotStatus {
  bot_type: string;
  bot_label: string;
  running: boolean;
  paused: boolean;
  consent_pending: boolean;
  auto_resume_in: number | null;
  watchlist: string[];
  watchlist_count: number;
  min_confidence: number;
  max_positions: number;
  position_size_pct: number;
  position_budget: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  cycle_interval: number;
  cycle_count: number;
  last_cycle: string | null;
  available_balance: number;
  total_equity: number;
  account_state_updated_at: string | null;
  active_positions: number;
  positions: Record<string, any>;
  trades_today: any[];
  total_pnl: number;
  total_charges: number;
  net_pnl: number;
  risk: Record<string, any>;
  errors: string[];
  runtime_health: BotRuntimeHealth;
  option_bias?: string;
  expiry_days?: number;
  strike_steps_from_atm?: number;
  min_days_to_expiry?: number;
  strategy?: string;
}

export interface RuntimeHealthSummary {
  service_mode: string;
  run_mode: string;
  paper_mode: boolean;
  live_broker_enabled: boolean;
  market: {
    phase: string;
    message: string;
    next_event: string;
    next_event_time: string;
  };
  bots: {
    equity: {
      running: boolean;
      paused: boolean;
      active_positions: number;
      last_cycle: string | null;
      errors: number;
      runtime_health: BotRuntimeHealth;
    };
    options: {
      running: boolean;
      paused: boolean;
      active_positions: number;
      last_cycle: string | null;
      errors: number;
      runtime_health: BotRuntimeHealth;
    };
  };
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

  getOptionsBotStatus(): Observable<BotStatus> {
    return this.http.get<BotStatus>(`${this.base}/bot/options/status`);
  }

  getRuntimeHealth(): Observable<RuntimeHealthSummary> {
    return this.http.get<RuntimeHealthSummary>(`${this.base}/bot/runtime-health`);
  }

  startBot(config?: Record<string, any>): Observable<any> {
    return this.http.post(`${this.base}/bot/start`, config || {});
  }

  startOptionsBot(config?: Record<string, any>): Observable<any> {
    return this.http.post(`${this.base}/bot/options/start`, config || {});
  }

  stopBot(): Observable<any> {
    return this.http.post(`${this.base}/bot/stop`, {});
  }

  stopOptionsBot(): Observable<any> {
    return this.http.post(`${this.base}/bot/options/stop`, {});
  }

  updateBotConfig(config: Record<string, any>): Observable<any> {
    return this.http.put(`${this.base}/bot/config`, config);
  }

  updateOptionsBotConfig(config: Record<string, any>): Observable<any> {
    return this.http.put(`${this.base}/bot/options/config`, config);
  }

  botConsent(resume: boolean): Observable<any> {
    return this.http.post(`${this.base}/bot/consent`, { resume });
  }

  optionsBotConsent(resume: boolean): Observable<any> {
    return this.http.post(`${this.base}/bot/options/consent`, { resume });
  }
}
