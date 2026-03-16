import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, EMPTY, timer } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { environment } from '../../environments/environment';

export type BackendReachability = 'connected' | 'waking backend' | 'unavailable';

export interface HealthInfo {
  status: string;
  environment?: string;
  paper_mode?: boolean;
  demo_mode?: boolean;
  run_mode?: string;
  feed_mode?: string;
  model_status?: string;
}

@Injectable({ providedIn: 'root' })
export class BackendStatusService {
  private readonly onlineSubject = new BehaviorSubject<boolean>(true);
  private readonly infoSubject = new BehaviorSubject<HealthInfo | null>(null);
  private readonly stateSubject = new BehaviorSubject<BackendReachability>('waking backend');

  readonly online$ = this.onlineSubject.asObservable();
  readonly info$ = this.infoSubject.asObservable();
  readonly state$ = this.stateSubject.asObservable();

  constructor(private http: HttpClient) {
    timer(0, 30_000)
      .pipe(
        switchMap(() =>
          this.http.get<HealthInfo>(`${environment.apiUrl}/health/info`).pipe(
            catchError(() => {
              this.setWaking();
              return EMPTY;
            })
          )
        )
      )
      .subscribe(info => {
        this.onlineSubject.next(true);
        this.infoSubject.next(info);
        this.stateSubject.next('connected');
      });
  }

  setOffline(): void {
    this.onlineSubject.next(false);
    this.stateSubject.next('unavailable');
  }

  setOnline(): void {
    this.onlineSubject.next(true);
    this.stateSubject.next('connected');
  }

  setWaking(): void {
    this.onlineSubject.next(false);
    this.stateSubject.next('waking backend');
  }
}
