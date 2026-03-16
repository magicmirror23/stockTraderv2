import { Injectable, NgZone } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, Subject } from 'rxjs';
import { environment } from '../../environments/environment';
import { BackendStatusService } from './backend-status.service';

export type StreamUiState = 'connected' | 'reconnecting' | 'replay mode' | 'unavailable' | 'waking backend';

export interface LiveTick {
  symbol: string;
  timestamp: string;
  price: number;
  volume: number;
  bid: number | null;
  ask: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  feed_mode?: string;
}

export interface FeedStatus {
  mode: 'live' | 'replay' | 'unavailable' | 'waking';
  feed_mode?: 'live' | 'replay' | 'unavailable' | 'waking';
  connected: boolean;
  reconnecting?: boolean;
  available: boolean;
  last_error?: string | null;
  watchlist?: string[];
}

export interface WatchlistItem extends LiveTick {
  sparkline: number[];
}

export interface MarketOverview {
  mode?: string;
  gainers: LiveTick[];
  losers: LiveTick[];
  volume_leaders: LiveTick[];
  indices: LiveTick[];
  categories: { [key: string]: LiveTick[] };
  total_symbols: number;
}

export interface CategoryInfo {
  [category: string]: { symbol: string; available: boolean }[];
}

@Injectable({ providedIn: 'root' })
export class LiveStreamService {
  private ws: WebSocket | null = null;
  private sse: EventSource | null = null;
  private readonly base = environment.apiUrl;

  readonly tick$ = new Subject<LiveTick>();
  readonly watchlist$ = new BehaviorSubject<Map<string, WatchlistItem>>(new Map());
  readonly connected$ = new BehaviorSubject<boolean>(false);
  readonly state$ = new BehaviorSubject<StreamUiState>('waking backend');

  private sparklineMax = 30;
  private reconnectDelay = 1000;
  private readonly maxReconnectDelay = 30000;
  private reconnectTimer: any = null;
  private lastSymbols: string[] = [];

  constructor(
    private ngZone: NgZone,
    private http: HttpClient,
    private backendStatus: BackendStatusService,
  ) {}

  getWatchlistSnapshot(symbols?: string[]): Observable<{ data: LiveTick[] }> {
    const q = symbols?.join(',') || '';
    return this.http.get<{ data: LiveTick[] }>(`${this.base}/stream/watchlist?symbols=${q}`);
  }

  getMarketOverview(): Observable<MarketOverview> {
    return this.http.get<MarketOverview>(`${this.base}/stream/market-overview`);
  }

  getFeedStatus(): Observable<FeedStatus> {
    return this.http.get<FeedStatus>(`${this.base}/stream/feed-status`);
  }

  getCategories(): Observable<CategoryInfo> {
    return this.http.get<CategoryInfo>(`${this.base}/stream/categories`);
  }

  connectLive(symbols?: string[]): Observable<FeedStatus> {
    const q = symbols?.join(',') || '';
    return this.http.post<FeedStatus>(`${this.base}/stream/connect-live?symbols=${q}`, {});
  }

  disconnectLive(): Observable<FeedStatus> {
    return this.http.post<FeedStatus>(`${this.base}/stream/disconnect-live`, {});
  }

  connectMulti(symbols: string[]): void {
    this.disconnect();
    this.lastSymbols = symbols;
    this.state$.next('waking backend');
    this.backendStatus.setWaking();

    const wsUrl = `${environment.wsBaseUrl}/api/v1/stream/multi`;
    if (!environment.wsBaseUrl) {
      this.connectSSE(symbols);
      return;
    }

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.connected$.next(true);
        this.reconnectDelay = 1000;
        this.state$.next('connected');
        this.backendStatus.setOnline();
        this.ws!.send(JSON.stringify({ action: 'subscribe', symbols }));
      };

      this.ws.onmessage = (event) => {
        this.ngZone.run(() => {
          const payload = JSON.parse(event.data);
          if (payload.type === 'ping') return;
          if (payload.type === 'status') {
            this.applyFeedStatus(payload);
            return;
          }
          const tick: LiveTick = payload.type === 'tick' ? payload : payload;
          this.tick$.next(tick);
          this.updateWatchlist(tick);
        });
      };

      this.ws.onerror = () => this.ws?.close();
      this.ws.onclose = () => this.scheduleReconnect();
    } catch {
      this.connectSSE(symbols);
    }
  }

  private connectSSE(symbols: string[]): void {
    const url = `${this.base}/stream/multi?symbols=${symbols.join(',')}`;
    this.sse = new EventSource(url);
    this.state$.next('waking backend');

    this.sse.onmessage = (event) => {
      this.ngZone.run(() => {
        const payload = JSON.parse(event.data);
        if (payload.type === 'status') {
          this.applyFeedStatus(payload);
          return;
        }
        const tick: LiveTick = payload.type === 'tick' ? payload : payload;
        this.connected$.next(true);
        this.tick$.next(tick);
        this.updateWatchlist(tick);
      });
    };

    this.sse.onerror = () => {
      this.connected$.next(false);
      this.state$.next('reconnecting');
      this.backendStatus.setWaking();
      this.sse?.close();
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    this.connected$.next(false);
    this.state$.next('reconnecting');
    this.backendStatus.setWaking();
    if (!this.lastSymbols.length) return;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
      this.connectMulti(this.lastSymbols);
    }, this.reconnectDelay);
  }

  private applyFeedStatus(status: FeedStatus): void {
    status.feed_mode = status.feed_mode || status.mode;
    const nextState =
      status.mode === 'live'
        ? 'connected'
        : status.mode === 'replay'
          ? 'replay mode'
          : status.mode === 'waking'
            ? 'waking backend'
            : 'unavailable';
    this.state$.next(nextState);
    if (nextState === 'connected' || nextState === 'replay mode') {
      this.backendStatus.setOnline();
    } else if (nextState === 'waking backend') {
      this.backendStatus.setWaking();
    } else {
      this.backendStatus.setOffline();
    }
  }

  private updateWatchlist(tick: LiveTick): void {
    const map = new Map(this.watchlist$.value);
    const existing = map.get(tick.symbol);
    const sparkline = existing?.sparkline || [];
    sparkline.push(tick.price);
    if (sparkline.length > this.sparklineMax) {
      sparkline.shift();
    }
    map.set(tick.symbol, { ...tick, sparkline });
    this.watchlist$.next(map);
  }

  disconnect(): void {
    this.lastSymbols = [];
    clearTimeout(this.reconnectTimer);
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    if (this.sse) {
      this.sse.close();
      this.sse = null;
    }
    this.connected$.next(false);
  }
}
