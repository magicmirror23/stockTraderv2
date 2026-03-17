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
  private readonly wsOpenTimeoutMs = 2500;

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
      let sse: EventSource | null = null;
      let delay = INITIAL_RECONNECT_DELAY;
      let reconnectTimer: any = null;
      let stopped = false;
      let opened = false;
      let fallbackTriggered = false;
      let openTimer: any = null;

      const fallbackToSse = () => {
        if (stopped || fallbackTriggered) return;
        fallbackTriggered = true;
        clearTimeout(openTimer);
        if (ws) {
          ws.onopen = null;
          ws.onmessage = null;
          ws.onerror = null;
          ws.onclose = null;
          try {
            if (ws.readyState === WebSocket.OPEN) {
              ws.close();
            }
          } catch {}
          ws = null;
        }
        connectSse();
      };

      const connectWs = () => {
        if (stopped || !wsUrl) {
          connectSse();
          return;
        }
        this.state$.next('waking backend');
        this.backendStatus.setWaking();
        try {
          opened = false;
          fallbackTriggered = false;
          ws = new WebSocket(wsUrl);
          openTimer = setTimeout(() => {
            if (!opened) {
              fallbackToSse();
            }
          }, this.wsOpenTimeoutMs);
          ws.onopen = () => {
            opened = true;
            clearTimeout(openTimer);
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
          ws.onerror = () => {
            if (!opened) {
              fallbackToSse();
              return;
            }
            ws?.close();
          };
          ws.onclose = () => {
            clearTimeout(openTimer);
            if (stopped) return;
            if (!opened && !fallbackTriggered) {
              fallbackToSse();
              return;
            }
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
        sse?.close();
        sse = new EventSource(sseUrl);
        this.state$.next('waking backend');
        sse.onmessage = (event) => {
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
        sse.onerror = () => {
          sse?.close();
          sse = null;
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
        clearTimeout(openTimer);
        if (ws?.readyState === WebSocket.OPEN) {
          ws.close();
        }
        sse?.close();
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
