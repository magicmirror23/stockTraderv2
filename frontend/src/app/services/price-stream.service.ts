import { Injectable, NgZone } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { BackendStatusService } from './backend-status.service';

export type PriceStreamState = 'connected' | 'reconnecting' | 'replay mode' | 'unavailable' | 'waking backend';

export interface PriceTick {
  timestamp: string;
  price: number;
  volume: number;
}

const MAX_RECONNECT_DELAY = 30000;
const INITIAL_RECONNECT_DELAY = 1000;

@Injectable({ providedIn: 'root' })
export class PriceStreamService {
  readonly state$ = new BehaviorSubject<PriceStreamState>('waking backend');

  constructor(
    private ngZone: NgZone,
    private backendStatus: BackendStatusService,
  ) {}

  connect(symbol: string): Observable<PriceTick> {
    return new Observable<PriceTick>(subscriber => {
      const wsUrl = environment.wsBaseUrl
        ? `${environment.wsBaseUrl}/api/v1/stream/price/${encodeURIComponent(symbol)}`
        : '';
      const sseUrl = `${environment.apiUrl}/stream/price/${encodeURIComponent(symbol)}`;
      let ws: WebSocket | null = null;
      let delay = INITIAL_RECONNECT_DELAY;
      let reconnectTimer: any = null;
      let stopped = false;

      const connectWs = () => {
        if (stopped || !wsUrl) {
          connectSse();
          return;
        }
        this.state$.next('waking backend');
        this.backendStatus.setWaking();
        try {
          ws = new WebSocket(wsUrl);
          ws.onopen = () => {
            delay = INITIAL_RECONNECT_DELAY;
            this.state$.next('connected');
            this.backendStatus.setOnline();
          };
          ws.onmessage = (event) => {
            this.ngZone.run(() => {
              const payload = JSON.parse(event.data);
              if (payload.type === 'ping') return;
              if (payload.type === 'status') {
                this.applyStatus(payload.mode);
                return;
              }
              subscriber.next(payload.type === 'tick' ? payload : payload);
            });
          };
          ws.onerror = () => ws?.close();
          ws.onclose = () => {
            if (stopped) return;
            this.state$.next('reconnecting');
            reconnectTimer = setTimeout(() => {
              delay = Math.min(delay * 2, MAX_RECONNECT_DELAY);
              connectWs();
            }, delay);
          };
        } catch {
          connectSse();
        }
      };

      const connectSse = () => {
        const source = new EventSource(sseUrl);
        this.state$.next('waking backend');
        source.onmessage = (event) => {
          this.ngZone.run(() => {
            const payload = JSON.parse(event.data);
            if (payload.type === 'status') {
              this.applyStatus(payload.mode);
              return;
            }
            this.state$.next('connected');
            this.backendStatus.setOnline();
            subscriber.next(payload.type === 'tick' ? payload : payload);
          });
        };
        source.onerror = () => {
          source.close();
          if (stopped) return;
          this.state$.next('reconnecting');
          this.backendStatus.setWaking();
          reconnectTimer = setTimeout(() => {
            delay = Math.min(delay * 2, MAX_RECONNECT_DELAY);
            connectSse();
          }, delay);
        };
      };

      connectWs();

      return () => {
        stopped = true;
        clearTimeout(reconnectTimer);
        ws?.close();
      };
    });
  }

  private applyStatus(mode: string): void {
    if (mode === 'live') {
      this.state$.next('connected');
      this.backendStatus.setOnline();
    } else if (mode === 'replay') {
      this.state$.next('replay mode');
      this.backendStatus.setOnline();
    } else if (mode === 'waking') {
      this.state$.next('waking backend');
      this.backendStatus.setWaking();
    } else {
      this.state$.next('unavailable');
      this.backendStatus.setOffline();
    }
  }
}
