import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PredictionApiService, PredictionResult } from '../services/prediction-api.service';
import { NotificationService } from '../services/notification.service';

@Component({
  selector: 'app-signal-explorer',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page">
      <h1>Predictions</h1>

      <div class="card mb-2" [attr.title]="sectionHelp.generator">
        <h2>Generate Prediction Signal</h2>
        <div class="form-row">
          <div class="form-group">
            <label>Ticker</label>
            <input [(ngModel)]="ticker" placeholder="RELIANCE" />
          </div>
          <div class="form-group">
            <label>Horizon</label>
            <select [(ngModel)]="horizon">
              <option value="1d">1 Day</option>
              <option value="5d">5 Days</option>
              <option value="1w">1 Week</option>
            </select>
          </div>
          <div class="form-group" style="justify-content:flex-end">
            <button class="btn-primary" (click)="fetchSignals()" [disabled]="loading">
              {{ loading ? 'Fetching...' : 'Get Signal' }}
            </button>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>Batch (comma separated)</label>
            <input [(ngModel)]="batchInput" placeholder="RELIANCE, TCS, INFY, HDFC" />
          </div>
          <div class="form-group" style="justify-content:flex-end">
            <button class="btn-primary" (click)="fetchBatch()" [disabled]="batchLoading">
              {{ batchLoading ? 'Fetching...' : 'Batch Predict' }}
            </button>
          </div>
        </div>
      </div>

      <div *ngIf="signals.length > 0" class="card" [attr.title]="sectionHelp.results">
        <h2>Results ({{ signals.length }})</h2>
        <table>
          <thead>
            <tr>
              <th>Ticker</th><th>Action</th><th>Confidence</th>
              <th>Expected Return</th><th>Model</th>
              <th>Calibration</th><th>SHAP Features</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let s of signals"
                class="signal-row"
                [class.signal-row-active]="selectedSignal?.ticker === s.ticker && selectedSignal?.timestamp === s.timestamp"
                (click)="selectSignal(s)">
              <td><strong>{{ s.ticker }}</strong></td>
              <td>
                <span class="badge" [ngClass]="s.action === 'buy' ? 'badge-buy' : s.action === 'sell' ? 'badge-sell' : 'badge-hold'">
                  {{ s.action | uppercase }}
                </span>
              </td>
              <td class="text-mono">{{ (s.confidence * 100) | number:'1.1-1' }}%</td>
              <td class="text-mono" [class.text-buy]="s.expected_return >= 0" [class.text-sell]="s.expected_return < 0">
                {{ s.expected_return >= 0 ? '+' : '' }}{{ (s.expected_return * 100) | number:'1.2-2' }}%
              </td>
              <td class="text-mono text-sm">{{ s.model_version }}</td>
              <td>{{ s.calibration_score !== undefined ? (s.calibration_score | number:'1.3-3') : 'N/A' }}</td>
              <td class="text-sm">{{ s.shap_top_features ? s.shap_top_features.join(', ') : 'N/A' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div *ngIf="selectedSignal?.explanation" class="card mt-2" [attr.title]="sectionHelp.explanation">
        <div class="flex justify-between items-center mb-1">
          <h2>Signal Explanation: {{ selectedSignal?.ticker }}</h2>
          <span class="badge badge-neutral">{{ selectedSignal?.explanation?.confidence_band }} confidence</span>
        </div>
        <p class="text-muted mb-2">{{ selectedSignal?.explanation?.summary }}</p>

        <div class="grid-3 mb-2">
          <div class="mini-card">
            <div class="stat-label">Decision Gate</div>
            <div class="text-sm">{{ selectedSignal?.explanation?.decision_gate }}</div>
          </div>
          <div class="mini-card">
            <div class="stat-label">Market Regime</div>
            <div class="stat-value text-sm">{{ selectedSignal?.explanation?.market_regime }}</div>
          </div>
          <div class="mini-card">
            <div class="stat-label">News Regime</div>
            <div class="stat-value text-sm">{{ selectedSignal?.explanation?.news_regime }}</div>
          </div>
        </div>

        <div class="grid-2 mb-2">
          <div class="mini-card">
            <h3>Top Drivers</h3>
            <div class="driver-list">
              <div *ngFor="let driver of selectedSignal?.explanation?.drivers" class="driver-item">
                <div class="flex justify-between items-center">
                  <strong>{{ driver.label }}</strong>
                  <span class="badge"
                        [ngClass]="driver.direction === 'bullish' ? 'badge-buy' : driver.direction === 'bearish' ? 'badge-sell' : 'badge-neutral'">
                    {{ driver.direction }}
                  </span>
                </div>
                <div class="text-mono text-sm">{{ driver.value | number:'1.2-2' }}</div>
                <p class="text-muted text-sm">{{ driver.insight }}</p>
              </div>
            </div>
          </div>

          <div class="mini-card">
            <h3>Threshold Context</h3>
            <table class="compact-table">
              <tbody>
                <tr><td>Buy Threshold</td><td>{{ formatPct(selectedSignal?.explanation?.thresholds?.buy_threshold) }}</td></tr>
                <tr><td>Sell Threshold</td><td>{{ formatPct(selectedSignal?.explanation?.thresholds?.sell_threshold) }}</td></tr>
                <tr><td>Min Confidence</td><td>{{ formatPct(selectedSignal?.explanation?.thresholds?.min_signal_confidence) }}</td></tr>
                <tr><td>Confidence Gap</td><td>{{ formatPct(selectedSignal?.explanation?.thresholds?.confidence_gap) }}</td></tr>
                <tr><td>Edge Score</td><td>{{ selectedSignal?.explanation?.thresholds?.edge_score != null ? (selectedSignal?.explanation?.thresholds?.edge_score | number:'1.2-2') : 'N/A' }}</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="mini-card" *ngIf="selectedSignal?.explanation?.risk_flags?.length">
          <h3>Risk Flags</h3>
          <ul class="risk-list">
            <li *ngFor="let flag of selectedSignal?.explanation?.risk_flags">{{ flag }}</li>
          </ul>
        </div>
      </div>

      <div *ngIf="signals.length === 0 && !loading && !batchLoading" class="card" style="text-align:center; padding: 3rem;" [attr.title]="sectionHelp.emptyState">
        <p class="text-muted">Enter a ticker above and click Get Signal to generate a prediction.</p>
      </div>
    </div>
  `,
  styles: [`
    .signal-row { cursor: pointer; transition: background 0.15s ease, transform 0.15s ease; }
    .signal-row:hover { background: rgba(0, 118, 255, 0.06); }
    .signal-row-active { background: rgba(0, 118, 255, 0.11); }
    .mini-card {
      border: 1px solid rgba(0, 0, 0, 0.08);
      border-radius: 12px;
      padding: 1rem;
      background: rgba(255, 255, 255, 0.7);
    }
    .driver-list { display: grid; gap: 0.75rem; }
    .driver-item {
      padding: 0.75rem;
      border-radius: 10px;
      background: rgba(15, 23, 42, 0.04);
    }
    .compact-table td {
      padding: 0.4rem 0.3rem;
      font-size: 0.92rem;
    }
    .risk-list {
      margin: 0;
      padding-left: 1.1rem;
      display: grid;
      gap: 0.35rem;
    }
    .badge-neutral {
      background: rgba(100, 116, 139, 0.14);
      color: #334155;
    }
  `]
})
export class SignalExplorerComponent {
  readonly sectionHelp = {
    generator: 'What: prediction request form for single or batch ticker analysis. How: choose a horizon, enter one or more tickers, and request signals from the model.',
    results: 'What: generated model signals with confidence and expected return. How: compare actions, calibration, and feature explanations before trading.',
    explanation: 'What: human-readable reason behind the selected signal. How: click any result row to inspect its decision gate, market regime, news regime, top drivers, and risk flags.',
    emptyState: 'What: getting-started area for predictions. How: enter a ticker or batch list above, then run the prediction request.',
  };
  ticker = 'RELIANCE';
  horizon = '1d';
  batchInput = '';
  signals: PredictionResult[] = [];
  selectedSignal: PredictionResult | null = null;
  loading = false;
  batchLoading = false;

  constructor(
    private predictionApi: PredictionApiService,
    private notify: NotificationService
  ) {}

  fetchSignals(): void {
    if (!this.ticker.trim()) { this.notify.warning('Enter a ticker.'); return; }
    this.loading = true;
    this.predictionApi.predict(this.ticker.trim(), this.horizon).subscribe({
      next: result => {
        this.signals = Array.isArray(result) ? result : [result];
        this.selectedSignal = this.signals[0] ?? null;
        this.loading = false;
      },
      error: () => { this.loading = false; }
    });
  }

  fetchBatch(): void {
    const tickers = this.batchInput.split(',').map(t => t.trim()).filter(t => t);
    if (tickers.length === 0) { this.notify.warning('Enter at least one ticker.'); return; }
    this.batchLoading = true;
    this.predictionApi.batchPredict(tickers).subscribe({
      next: results => {
        this.signals = results;
        this.selectedSignal = results[0] ?? null;
        this.batchLoading = false;
        this.notify.success(`Received ${results.length} predictions.`);
      },
      error: () => { this.batchLoading = false; }
    });
  }

  selectSignal(signal: PredictionResult): void {
    this.selectedSignal = signal;
  }

  formatPct(value: number | null | undefined): string {
    return value != null ? `${(value * 100).toFixed(1)}%` : 'N/A';
  }
}
