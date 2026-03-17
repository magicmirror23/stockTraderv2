import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PredictionApiService, Greeks, OptionSignal } from '../services/prediction-api.service';
import { LivePriceChartComponent, PriceTick } from '../components/live-price-chart.component';
import { PriceStreamService } from '../services/price-stream.service';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-signal-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, LivePriceChartComponent],
  template: `
    <div class="page">
      <h1>Options Signal</h1>

      <div class="card mb-2" [attr.title]="sectionHelp.parameters">
        <h2>Option Parameters</h2>
        <div class="form-row">
          <div class="form-group">
            <label>Underlying</label>
            <input [(ngModel)]="underlying" placeholder="NIFTY" />
          </div>
          <div class="form-group">
            <label>Strike</label>
            <input type="number" [(ngModel)]="strike" />
          </div>
          <div class="form-group">
            <label>Expiry</label>
            <input type="date" [(ngModel)]="expiry" />
          </div>
          <div class="form-group">
            <label>Type</label>
            <select [(ngModel)]="optionType">
              <option value="CE">CE (Call)</option>
              <option value="PE">PE (Put)</option>
            </select>
          </div>
          <div class="form-group" style="justify-content:flex-end">
            <button class="btn-primary" (click)="fetchSignal()" [disabled]="loading">
              {{ loading ? 'Fetching...' : 'Get Signal' }}
            </button>
          </div>
        </div>
        <p *ngIf="error" style="color: var(--color-danger); margin-top: 0.5rem;">{{ error }}</p>
      </div>

      <div *ngIf="signal" class="grid-2 mb-2">
        <div class="card" [attr.title]="sectionHelp.signal">
          <h2>Signal</h2>
          <table>
            <tbody>
              <tr><td><strong>Action</strong></td>
                <td>
                  <span class="badge" [ngClass]="signal.action === 'buy' ? 'badge-buy' : signal.action === 'sell' ? 'badge-sell' : 'badge-hold'">
                    {{ signal.action | uppercase }}
                  </span>
                </td></tr>
              <tr><td><strong>Confidence</strong></td><td class="text-mono">{{ (signal.confidence * 100) | number:'1.1-1' }}%</td></tr>
              <tr><td><strong>Expected Return</strong></td>
                <td class="text-mono" [class.text-buy]="signal.expected_return >= 0" [class.text-sell]="signal.expected_return < 0">
                  {{ signal.expected_return >= 0 ? '+' : '' }}{{ (signal.expected_return * 100) | number:'1.2-2' }}%
                </td></tr>
              <tr><td><strong>IV Percentile</strong></td>
                <td class="text-mono">{{ signal.iv_percentile != null ? ((signal.iv_percentile * 100) | number:'1.1-1') + '%' : 'N/A' }}</td></tr>
              <tr><td><strong>Model</strong></td><td class="text-mono text-sm">{{ signal.model_version }}</td></tr>
              <tr><td><strong>Calibration</strong></td><td class="text-mono">{{ signal.calibration_score !== undefined ? (signal.calibration_score | number:'1.3-3') : 'N/A' }}</td></tr>
              <tr><td><strong>SHAP Features</strong></td><td class="text-sm">{{ signal.shap_top_features ? signal.shap_top_features.join(', ') : 'N/A' }}</td></tr>
            </tbody>
          </table>
        </div>

        <div class="card" [attr.title]="sectionHelp.greeks">
          <h2>Greeks</h2>
          <div class="greeks-grid">
            <div class="greek-cell"><span class="stat-label">Delta</span><span class="stat-value">{{ signal.greeks.delta | number:'1.4-4' }}</span></div>
            <div class="greek-cell"><span class="stat-label">Gamma</span><span class="stat-value">{{ signal.greeks.gamma | number:'1.4-4' }}</span></div>
            <div class="greek-cell"><span class="stat-label">Theta</span><span class="stat-value">{{ signal.greeks.theta | number:'1.4-4' }}</span></div>
            <div class="greek-cell"><span class="stat-label">Vega</span><span class="stat-value">{{ signal.greeks.vega | number:'1.4-4' }}</span></div>
            <div class="greek-cell"><span class="stat-label">Rho</span><span class="stat-value">{{ signal.greeks.rho != null ? (signal.greeks.rho | number:'1.4-4') : 'N/A' }}</span></div>
            <div class="greek-cell"><span class="stat-label">IV</span><span class="stat-value">{{ signal.greeks.iv != null ? ((signal.greeks.iv * 100) | number:'1.1-1') + '%' : 'N/A' }}</span></div>
          </div>
        </div>
      </div>

      <div *ngIf="signal?.explanation" class="card mb-2" [attr.title]="sectionHelp.explanation">
        <h2>Why This Signal</h2>
        <p class="text-muted mb-1">{{ signal?.explanation?.summary }}</p>
        <div class="grid-3">
          <div class="greek-cell">
            <span class="stat-label">Market Regime</span>
            <span class="stat-value text-sm">{{ signal?.explanation?.market_regime }}</span>
          </div>
          <div class="greek-cell">
            <span class="stat-label">News Regime</span>
            <span class="stat-value text-sm">{{ signal?.explanation?.news_regime }}</span>
          </div>
          <div class="greek-cell">
            <span class="stat-label">Decision Gate</span>
            <span class="stat-value text-sm">{{ signal?.explanation?.confidence_band }}</span>
          </div>
        </div>
      </div>

      <div class="card" [attr.title]="sectionHelp.chart">
        <div class="flex justify-between items-center">
          <h2>Live Chart: {{ underlying }}</h2>
          <div style="display:flex; gap:0.5rem;">
            <button class="btn-primary" (click)="startStream()" [disabled]="!!streamSub">
              {{ streamSub ? 'Connected' : 'Connect Live Feed' }}
            </button>
            <button class="btn-danger" *ngIf="streamSub" (click)="stopStream()">Disconnect</button>
          </div>
        </div>
        <app-live-price-chart [data]="ticks" />
      </div>
    </div>
  `,
  styles: [`
    .greeks-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-top: 1rem; }
    .greek-cell { text-align: center; padding: 1rem; background: var(--color-bg); border-radius: var(--radius); }
    .greek-cell .stat-label { display: block; font-size: 0.75rem; text-transform: uppercase; color: var(--color-text-secondary); margin-bottom: 0.25rem; }
    .greek-cell .stat-value { display: block; font-size: 1.1rem; font-weight: 600; font-family: var(--font-mono); }
  `]
})
export class SignalDetailComponent {
  readonly sectionHelp = {
    parameters: 'What: option signal request form. How: choose underlying, strike, expiry, and call/put type before fetching the model output.',
    signal: 'What: option model recommendation. How: review action, confidence, expected return, and model metadata before acting.',
    explanation: 'What: human-readable explanation of the option signal. How: use it to quickly understand the market regime and news backdrop behind the recommendation.',
    greeks: 'What: option sensitivity measures. How: use delta, gamma, theta, vega, and IV to understand risk around the option signal.',
    chart: 'What: live price chart for the underlying instrument. How: connect the feed to watch the underlying move while evaluating the options signal.',
  };
  underlying = 'NIFTY';
  strike = 22000;
  expiry = '2025-02-27';
  optionType: 'CE' | 'PE' = 'CE';
  signal: OptionSignal | null = null;
  error: string | null = null;
  loading = false;
  ticks: PriceTick[] = [];
  streamSub: Subscription | null = null;

  constructor(
    private predictionApi: PredictionApiService,
    private priceStream: PriceStreamService
  ) {}

  fetchSignal(): void {
    this.error = null;
    this.loading = true;
    this.predictionApi.predictOptions(this.underlying, this.strike, this.expiry, this.optionType).subscribe({
      next: res => { this.signal = res.signal ?? (res as any); this.loading = false; },
      error: () => { this.error = 'Failed to fetch signal'; this.loading = false; }
    });
  }

  startStream(): void {
    this.stopStream();
    this.ticks = [];
    this.streamSub = this.priceStream.connect(this.underlying).subscribe(tick => {
      this.ticks = [...this.ticks.slice(-200), tick];
    });
  }

  stopStream(): void {
    this.streamSub?.unsubscribe();
    this.streamSub = null;
  }

  ngOnDestroy(): void {
    this.stopStream();
  }
}
