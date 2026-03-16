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

      <div class="card mb-2">
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

      <div *ngIf="signals.length > 0" class="card">
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
            <tr *ngFor="let s of signals">
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

      <div *ngIf="signals.length === 0 && !loading && !batchLoading" class="card" style="text-align:center; padding: 3rem;">
        <p class="text-muted">Enter a ticker above and click Get Signal to generate a prediction.</p>
      </div>
    </div>
  `
})
export class SignalExplorerComponent {
  ticker = 'RELIANCE';
  horizon = '1d';
  batchInput = '';
  signals: PredictionResult[] = [];
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
        this.batchLoading = false;
        this.notify.success(`Received ${results.length} predictions.`);
      },
      error: () => { this.batchLoading = false; }
    });
  }
}
