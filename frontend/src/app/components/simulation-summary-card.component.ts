import { Component, Input, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { PaperApiService, AccountMetrics } from '../services/paper-api.service';

@Component({
  selector: 'app-simulation-summary-card',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card" *ngIf="metrics; else loading">
      <h3>Performance Summary</h3>
      <table>
        <tbody>
          <tr><td>Sharpe Ratio</td><td>{{ metrics.sharpe !== null ? (metrics.sharpe | number:'1.2-2') : 'N/A' }}</td></tr>
          <tr><td>Sortino Ratio</td><td>{{ metrics.sortino !== null ? (metrics.sortino | number:'1.2-2') : 'N/A' }}</td></tr>
          <tr><td>Max Drawdown</td><td>{{ metrics.max_drawdown !== null ? ((metrics.max_drawdown * 100) | number:'1.1-1') + '%' : 'N/A' }}</td></tr>
          <tr><td>Win Rate</td><td>{{ metrics.win_rate !== null ? ((metrics.win_rate * 100) | number:'1.1-1') + '%' : 'N/A' }}</td></tr>
          <tr><td>Total Trades</td><td>{{ metrics.total_trades }}</td></tr>
          <tr><td>Net P&amp;L</td><td>₹{{ metrics.net_pnl | number:'1.0-0' }}</td></tr>
        </tbody>
      </table>
    </div>
    <ng-template #loading><p>Loading metrics…</p></ng-template>
  `,
  styles: [`
    .card {
      border: 1px solid #ccc;
      border-radius: 8px;
      padding: 1rem;
      margin: 1rem 0;
    }
    table { width: 100%; }
    td { padding: 4px 8px; }
    td:first-child { font-weight: bold; }
  `]
})
export class SimulationSummaryCardComponent implements OnInit {
  @Input() accountId!: string;
  metrics: AccountMetrics | null = null;

  constructor(private paperApi: PaperApiService) {}

  ngOnInit(): void {
    this.paperApi.getMetrics(this.accountId).subscribe({
      next: m => this.metrics = m,
      error: () => {}
    });
  }
}
