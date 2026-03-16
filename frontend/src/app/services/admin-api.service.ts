import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface ModelStatus {
  model_version: string;
  status: string;
  last_trained: string | null;
  accuracy: number | null;
}

export interface ModelReloadResponse {
  message: string;
  new_version: string;
  status: string;
}

export interface ModelVersion {
  version: string;
  created_at: string;
  accuracy?: number;
  status?: string;
}

export interface DriftResult {
  model_version: string;
  prediction_drift_psi: number | null;
  feature_drift_detected: boolean;
  avg_latency_ms: number | null;
  p99_latency_ms: number | null;
  error_rate: number | null;
  status: string;
}

export interface CanaryStatus {
  enabled: boolean;
  canary_version: string | null;
  stable_version: string | null;
  canary_traffic_pct: number;
  canary_accuracy: number | null;
  stable_accuracy: number | null;
}

export interface RetrainStatus {
  running: boolean;
  progress: string | null;
  error: string | null;
  message?: string | null;
  model_version?: string | null;
  metrics?: Record<string, unknown> | null;
  data_refresh?: Record<string, unknown> | null;
  last_started_at?: string | null;
  last_finished_at?: string | null;
}

export interface RetrainLogEntry {
  id: number;
  timestamp: string;
  level: string;
  logger: string;
  message: string;
}

export interface RetrainLogsResponse {
  entries: RetrainLogEntry[];
  next_cursor: number;
  running: boolean;
  progress: string | null;
}

@Injectable({ providedIn: 'root' })
export class AdminApiService {
  private readonly base = environment.apiUrl;

  constructor(private http: HttpClient) {}

  getModelStatus(): Observable<ModelStatus> {
    return this.http.get<ModelStatus>(`${this.base}/model/status`);
  }

  reloadModel(version?: string): Observable<ModelReloadResponse> {
    return this.http.post<ModelReloadResponse>(`${this.base}/model/reload`, { version: version || null });
  }

  triggerRetrain(): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(`${this.base}/retrain`, {});
  }

  getRetrainStatus(): Observable<RetrainStatus> {
    return this.http.get<RetrainStatus>(`${this.base}/retrain/status`);
  }

  getRetrainLogs(after: number = 0): Observable<RetrainLogsResponse> {
    return this.http.get<RetrainLogsResponse>(`${this.base}/retrain/logs?after=${after}`);
  }

  getRegistryVersions(): Observable<ModelVersion[]> {
    return this.http.get<ModelVersion[]>(`${this.base}/registry/versions`);
  }

  getMLflowVersion(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(`${this.base}/registry/mlflow`);
  }

  checkDrift(): Observable<DriftResult> {
    return this.http.post<DriftResult>(`${this.base}/drift/check`, {});
  }

  getCanaryStatus(): Observable<CanaryStatus> {
    return this.http.get<CanaryStatus>(`${this.base}/canary/status`);
  }

  getMetrics(): Observable<string> {
    return this.http.get(`${this.base}/metrics`, { responseType: 'text' });
  }
}
