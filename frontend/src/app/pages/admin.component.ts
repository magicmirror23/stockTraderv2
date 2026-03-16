import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AdminApiService, ModelStatus, DriftResult, CanaryStatus, ModelVersion } from '../services/admin-api.service';
import { AuthService } from '../services/auth.service';
import { NotificationService } from '../services/notification.service';

@Component({
  selector: 'app-admin',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page">
      <h1>Admin & Monitoring</h1>

      <!-- Auth -->
      <div class="card mb-2" *ngIf="!auth.isAuthenticated">
        <div class="flex gap-1 items-center">
          <span class="text-muted text-sm">Admin token required for retrain/drift:</span>
          <input type="password" [(ngModel)]="tokenInput" placeholder="Bearer token" />
          <button class="btn-primary btn-sm" (click)="setToken()">Set Token</button>
        </div>
      </div>

      <!-- Tab bar -->
      <div class="tab-bar">
        <button class="tab" [class.active]="activeTab === 'model'" (click)="activeTab = 'model'">Model</button>
        <button class="tab" [class.active]="activeTab === 'drift'" (click)="activeTab = 'drift'; loadDrift()">Drift & Health</button>
        <button class="tab" [class.active]="activeTab === 'registry'" (click)="activeTab = 'registry'; loadVersions()">Registry</button>
        <button class="tab" [class.active]="activeTab === 'canary'" (click)="activeTab = 'canary'; loadCanary()">Canary</button>
      </div>

      <!-- Model Tab -->
      <div *ngIf="activeTab === 'model'">
        <div *ngIf="modelLoading" class="loading-container"><div class="spinner"></div> Loading model status...</div>
        <div *ngIf="!modelLoading && modelStatus">
          <div class="grid-4 mb-2">
            <div class="stat-card">
              <div class="stat-label">Model Version</div>
              <div class="stat-value text-mono">{{ modelStatus.model_version }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Status</div>
              <div class="stat-value">
                <span class="badge" [ngClass]="modelStatus.status === 'loaded' ? 'badge-success' : modelStatus.status === 'loading' ? 'badge-running' : 'badge-danger'">
                  {{ modelStatus.status }}
                </span>
              </div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Accuracy</div>
              <div class="stat-value">{{ modelStatus.accuracy !== null ? ((modelStatus.accuracy * 100) | number:'1.1-1') + '%' : 'N/A' }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Last Trained</div>
              <div class="stat-value text-sm">{{ modelStatus.last_trained ? (modelStatus.last_trained | date:'medium') : 'N/A' }}</div>
            </div>
          </div>

          <div class="card mb-2">
            <h3>Actions</h3>
            <div class="flex gap-2">
              <button class="btn-primary" (click)="reloadModel()" [disabled]="reloading">
                {{ reloading ? 'Reloading...' : 'Hot Reload Model' }}
              </button>
              <button class="btn-success" (click)="triggerRetrain()" [disabled]="retraining || !auth.isAuthenticated">
                {{ retraining ? 'Retraining...' : 'Trigger Retrain' }}
              </button>
              <button (click)="loadModelStatus()">Refresh Status</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Drift Tab -->
      <div *ngIf="activeTab === 'drift'">
        <div *ngIf="driftLoading" class="loading-container"><div class="spinner"></div> Loading drift data...</div>
        <div *ngIf="!driftLoading && drift">
          <div class="grid-3 mb-2">
            <div class="stat-card">
              <div class="stat-label">Overall Status</div>
              <div class="stat-value">
                <span class="badge" [ngClass]="drift.status === 'healthy' ? 'badge-success' : 'badge-danger'">{{ drift.status }}</span>
              </div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Prediction Drift (PSI)</div>
              <div class="stat-value" [class.text-sell]="drift.prediction_drift_psi !== null && drift.prediction_drift_psi > 0.2">
                {{ drift.prediction_drift_psi !== null ? (drift.prediction_drift_psi | number:'1.4-4') : 'N/A' }}
              </div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Feature Drift</div>
              <div class="stat-value">
                <span class="badge" [ngClass]="drift.feature_drift_detected ? 'badge-danger' : 'badge-success'">
                  {{ drift.feature_drift_detected ? 'DETECTED' : 'None' }}
                </span>
              </div>
            </div>
          </div>
          <div class="grid-3 mb-2">
            <div class="stat-card">
              <div class="stat-label">Avg Latency</div>
              <div class="stat-value">{{ drift.avg_latency_ms !== null ? (drift.avg_latency_ms | number:'1.1-1') + 'ms' : 'N/A' }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">P99 Latency</div>
              <div class="stat-value">{{ drift.p99_latency_ms !== null ? (drift.p99_latency_ms | number:'1.1-1') + 'ms' : 'N/A' }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Error Rate</div>
              <div class="stat-value" [class.text-sell]="drift.error_rate !== null && drift.error_rate > 0.05">
                {{ drift.error_rate !== null ? ((drift.error_rate * 100) | number:'1.2-2') + '%' : 'N/A' }}
              </div>
            </div>
          </div>
          <button class="btn-primary" (click)="runDriftCheck()" [disabled]="driftChecking || !auth.isAuthenticated">
            {{ driftChecking ? 'Checking...' : 'Run Drift Check' }}
          </button>
        </div>
        <div *ngIf="!driftLoading && !drift" class="card">
          <p class="text-muted">No drift data available.</p>
          <button class="btn-primary" (click)="runDriftCheck()" [disabled]="driftChecking || !auth.isAuthenticated">Run First Check</button>
        </div>
      </div>

      <!-- Registry Tab -->
      <div *ngIf="activeTab === 'registry'">
        <div *ngIf="versionsLoading" class="loading-container"><div class="spinner"></div> Loading versions...</div>
        <div *ngIf="!versionsLoading">
          <div class="card">
            <h3>Model Versions</h3>
            <table *ngIf="versions.length > 0">
              <thead>
                <tr><th>Version</th><th>Created</th><th>Accuracy</th><th>Status</th></tr>
              </thead>
              <tbody>
                <tr *ngFor="let v of versions">
                  <td class="text-mono"><strong>{{ v.version }}</strong></td>
                  <td>{{ v.created_at | date:'medium' }}</td>
                  <td>{{ v.accuracy !== undefined && v.accuracy !== null ? ((v.accuracy * 100) | number:'1.1-1') + '%' : 'N/A' }}</td>
                  <td>
                    <span class="badge" [ngClass]="v.status === 'active' ? 'badge-success' : 'badge-neutral'">{{ v.status || 'archived' }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <p *ngIf="versions.length === 0" class="text-muted">No versions found in registry.</p>
          </div>
        </div>
      </div>

      <!-- Canary Tab -->
      <div *ngIf="activeTab === 'canary'">
        <div *ngIf="canaryLoading" class="loading-container"><div class="spinner"></div> Loading canary status...</div>
        <div *ngIf="!canaryLoading && canary">
          <div class="grid-3 mb-2">
            <div class="stat-card">
              <div class="stat-label">Canary Enabled</div>
              <div class="stat-value">
                <span class="badge" [ngClass]="canary.enabled ? 'badge-success' : 'badge-neutral'">{{ canary.enabled ? 'YES' : 'NO' }}</span>
              </div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Stable Version</div>
              <div class="stat-value text-mono">{{ canary.stable_version || 'N/A' }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Canary Version</div>
              <div class="stat-value text-mono">{{ canary.canary_version || 'N/A' }}</div>
            </div>
          </div>
          <div *ngIf="canary.enabled" class="grid-3 mb-2">
            <div class="stat-card">
              <div class="stat-label">Canary Traffic</div>
              <div class="stat-value">{{ canary.canary_traffic_pct }}%</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Stable Accuracy</div>
              <div class="stat-value">{{ canary.stable_accuracy !== null ? ((canary.stable_accuracy * 100) | number:'1.1-1') + '%' : 'N/A' }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Canary Accuracy</div>
              <div class="stat-value">{{ canary.canary_accuracy !== null ? ((canary.canary_accuracy * 100) | number:'1.1-1') + '%' : 'N/A' }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    @media (max-width: 768px) {
      .grid-4 { grid-template-columns: repeat(2, 1fr); }
    }
  `]
})
export class AdminComponent implements OnInit {
  tokenInput = '';
  activeTab: 'model' | 'drift' | 'registry' | 'canary' = 'model';

  modelStatus: ModelStatus | null = null;
  modelLoading = false;
  reloading = false;
  retraining = false;

  drift: DriftResult | null = null;
  driftLoading = false;
  driftChecking = false;

  versions: ModelVersion[] = [];
  versionsLoading = false;

  canary: CanaryStatus | null = null;
  canaryLoading = false;

  constructor(
    public auth: AuthService,
    private adminApi: AdminApiService,
    private notify: NotificationService
  ) {}

  ngOnInit(): void {
    this.loadModelStatus();
  }

  setToken(): void {
    if (this.tokenInput.trim()) {
      this.auth.setToken(this.tokenInput.trim());
      this.tokenInput = '';
      this.notify.success('Admin token saved.');
    }
  }

  loadModelStatus(): void {
    this.modelLoading = true;
    this.adminApi.getModelStatus().subscribe({
      next: s => { this.modelStatus = s; this.modelLoading = false; },
      error: () => { this.modelLoading = false; }
    });
  }

  reloadModel(): void {
    this.reloading = true;
    this.adminApi.reloadModel().subscribe({
      next: res => {
        this.reloading = false;
        this.notify.success(res.message);
        this.loadModelStatus();
      },
      error: () => { this.reloading = false; }
    });
  }

  triggerRetrain(): void {
    this.retraining = true;
    this.adminApi.triggerRetrain().subscribe({
      next: () => {
        this.retraining = false;
        this.notify.success('Retrain triggered successfully.');
        this.loadModelStatus();
      },
      error: () => { this.retraining = false; }
    });
  }

  loadDrift(): void {
    if (this.drift) return;
    this.driftLoading = true;
    this.adminApi.checkDrift().subscribe({
      next: d => { this.drift = d; this.driftLoading = false; },
      error: () => { this.driftLoading = false; }
    });
  }

  runDriftCheck(): void {
    this.driftChecking = true;
    this.adminApi.checkDrift().subscribe({
      next: d => {
        this.drift = d;
        this.driftChecking = false;
        this.notify.success('Drift check completed.');
      },
      error: () => { this.driftChecking = false; }
    });
  }

  loadVersions(): void {
    if (this.versions.length > 0) return;
    this.versionsLoading = true;
    this.adminApi.getRegistryVersions().subscribe({
      next: v => {
        this.versions = Array.isArray(v) ? v : [];
        this.versionsLoading = false;
      },
      error: () => { this.versionsLoading = false; }
    });
  }

  loadCanary(): void {
    if (this.canary) return;
    this.canaryLoading = true;
    this.adminApi.getCanaryStatus().subscribe({
      next: c => { this.canary = c; this.canaryLoading = false; },
      error: () => { this.canaryLoading = false; }
    });
  }
}
