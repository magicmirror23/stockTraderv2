import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { BacktestApiService, BacktestRunRequest, BacktestResults, BacktestTrade } from '../services/backtest-api.service';
import { NotificationService } from '../services/notification.service';

@Component({
  selector: 'app-backtest',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page">
      <h1>Backtesting</h1>

      <!-- Configuration Form -->
      <div class="card mb-2">
        <h2>Run Backtest</h2>
        <div class="form-row">
          <div class="form-group">
            <label>Tickers (comma separated)</label>
            <input [(ngModel)]="tickersInput" placeholder="RELIANCE, TCS, INFY" />
          </div>
          <div class="form-group">
            <label>Strategy</label>
            <select [(ngModel)]="strategy">
              <option value="momentum">Momentum</option>
              <option value="mean_reversion">Mean Reversion</option>
              <option value="ml_signal">ML Signal</option>
            </select>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>Start Date</label>
            <input type="date" [(ngModel)]="startDate" />
          </div>
          <div class="form-group">
            <label>End Date</label>
            <input type="date" [(ngModel)]="endDate" />
          </div>
          <div class="form-group">
            <label>Initial Capital (₹)</label>
            <input type="number" [(ngModel)]="initialCapital" min="1000" />
          </div>
        </div>
        <button class="btn-primary" (click)="submitBacktest()" [disabled]="loading">
          {{ loading ? 'Submitting...' : 'Run Backtest' }}
        </button>
      </div>

      <!-- Pending Job -->
      <div *ngIf="jobId && !results" class="card mb-2">
        <div class="flex items-center gap-2">
          <div class="spinner"></div>
          <div>
            <p><strong>Job ID:</strong> <span class="text-mono">{{ jobId }}</span></p>
            <p class="text-muted text-sm">Status: <span class="badge badge-running">{{ jobStatus }}</span></p>
          </div>
        </div>
        <button class="btn-primary btn-sm mt-2" (click)="pollResults()" [disabled]="polling">
          {{ polling ? 'Checking...' : 'Check Results' }}
        </button>
      </div>

      <!-- Results -->
      <div *ngIf="results">
        <h2>Results — {{ results.tickers.join(', ') }}</h2>
        <div class="grid-4 mb-2">
          <div class="stat-card">
            <div class="stat-label">Final Value</div>
            <div class="stat-value">₹{{ results.final_value | number:'1.0-0' }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Total Return</div>
            <div class="stat-value" [class.text-buy]="results.total_return_pct >= 0" [class.text-sell]="results.total_return_pct < 0">
              {{ results.total_return_pct | number:'1.2-2' }}%
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Sharpe Ratio</div>
            <div class="stat-value">{{ results.sharpe_ratio !== null ? (results.sharpe_ratio | number:'1.2-2') : 'N/A' }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Max Drawdown</div>
            <div class="stat-value text-sell">{{ results.max_drawdown_pct !== null ? (results.max_drawdown_pct | number:'1.2-2') + '%' : 'N/A' }}</div>
          </div>
        </div>

        <div class="card mb-2">
          <h3>Performance Summary</h3>
          <div class="grid-3">
            <div><span class="text-muted text-sm">Period:</span> {{ results.start_date }} → {{ results.end_date }}</div>
            <div><span class="text-muted text-sm">Initial Capital:</span> ₹{{ results.initial_capital | number:'1.0-0' }}</div>
            <div><span class="text-muted text-sm">Total Trades:</span> {{ results.trades.length }}</div>
          </div>
        </div>

        <!-- Trade Log -->
        <div class="card">
          <h3>Trade Log</h3>
          <table *ngIf="results.trades.length > 0">
            <thead>
              <tr>
                <th>Date</th><th>Ticker</th><th>Side</th><th>Qty</th><th>Price</th><th>P&L</th>
              </tr>
            </thead>
            <tbody>
              <tr *ngFor="let t of displayedTrades">
                <td class="text-mono text-sm">{{ t.date }}</td>
                <td><strong>{{ t.ticker }}</strong></td>
                <td><span class="badge" [ngClass]="t.side === 'buy' ? 'badge-buy' : 'badge-sell'">{{ t.side }}</span></td>
                <td>{{ t.quantity }}</td>
                <td>₹{{ t.price | number:'1.2-2' }}</td>
                <td [class.text-buy]="t.pnl >= 0" [class.text-sell]="t.pnl < 0">
                  {{ t.pnl >= 0 ? '+' : '' }}₹{{ t.pnl | number:'1.2-2' }}
                </td>
              </tr>
            </tbody>
          </table>
          <div *ngIf="results.trades.length > tradesPerPage" class="flex justify-between items-center mt-2">
            <span class="text-muted text-sm">Showing {{ tradesStart + 1 }}–{{ tradesEnd }} of {{ results.trades.length }}</span>
            <div class="flex gap-1">
              <button class="btn-sm" (click)="prevPage()" [disabled]="currentPage === 0">← Prev</button>
              <button class="btn-sm" (click)="nextPage()" [disabled]="tradesEnd >= results.trades.length">Next →</button>
            </div>
          </div>
          <p *ngIf="results.trades.length === 0" class="text-muted">No trades executed during this period.</p>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .form-row { margin-bottom: 0; }
  `]
})
export class BacktestComponent {
  tickersInput = 'RELIANCE, TCS';
  strategy = 'momentum';
  startDate = '2024-01-01';
  endDate = '2024-12-31';
  initialCapital = 100000;

  loading = false;
  jobId: string | null = null;
  jobStatus = 'pending';
  polling = false;
  results: BacktestResults | null = null;

  currentPage = 0;
  tradesPerPage = 20;

  constructor(
    private backtestApi: BacktestApiService,
    private notify: NotificationService
  ) {}

  get tradesStart(): number { return this.currentPage * this.tradesPerPage; }
  get tradesEnd(): number { return Math.min(this.tradesStart + this.tradesPerPage, this.results?.trades.length ?? 0); }

  get displayedTrades(): BacktestTrade[] {
    return this.results?.trades.slice(this.tradesStart, this.tradesEnd) ?? [];
  }

  submitBacktest(): void {
    const tickers = this.tickersInput.split(',').map(t => t.trim()).filter(t => t);
    if (tickers.length === 0) {
      this.notify.warning('Please enter at least one ticker.');
      return;
    }

    this.loading = true;
    this.results = null;
    this.jobId = null;

    const request: BacktestRunRequest = {
      tickers,
      start_date: this.startDate,
      end_date: this.endDate,
      initial_capital: this.initialCapital,
      strategy: this.strategy
    };

    this.backtestApi.runBacktest(request).subscribe({
      next: res => {
        this.jobId = res.job_id;
        this.jobStatus = res.status;
        this.loading = false;
        this.notify.success('Backtest job submitted successfully.');
        // Auto-poll after a short delay
        setTimeout(() => this.pollResults(), 2000);
      },
      error: () => { this.loading = false; }
    });
  }

  pollResults(): void {
    if (!this.jobId) return;
    this.polling = true;
    this.backtestApi.getResults(this.jobId).subscribe({
      next: res => {
        this.polling = false;
        if (res.status === 'completed') {
          this.results = res;
          this.currentPage = 0;
          this.notify.success('Backtest completed!');
        } else if (res.status === 'failed') {
          this.jobStatus = 'failed';
          this.notify.error('Backtest job failed.');
        } else {
          this.jobStatus = res.status;
          this.notify.info('Backtest still running. Try again shortly.');
        }
      },
      error: () => { this.polling = false; }
    });
  }

  prevPage(): void { if (this.currentPage > 0) this.currentPage--; }
  nextPage(): void { if (this.tradesEnd < (this.results?.trades.length ?? 0)) this.currentPage++; }
}
