import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { PaperApiService, PaperAccount, EquityPoint, AccountMetrics } from '../services/paper-api.service';
import { EquityChartComponent } from '../components/equity-chart.component';

@Component({
  selector: 'app-paper-dashboard',
  standalone: true,
  imports: [CommonModule, EquityChartComponent],
  template: `
    <div class="page">
      <div class="flex justify-between items-center mb-2">
        <h1>Paper Trading Dashboard</h1>
        <button class="btn-primary" (click)="createAccount()">+ Create Account (₹100,000)</button>
      </div>

      <div *ngIf="loading" class="loading-container"><div class="spinner"></div> Loading accounts...</div>

      <div *ngIf="!loading && accounts.length === 0" class="card" style="text-align:center; padding: 3rem;" [attr.title]="sectionHelp.emptyState">
        <p class="text-muted">No paper trading accounts yet. Create one to get started.</p>
      </div>

      <div *ngIf="!loading && accounts.length > 0">
        <div class="grid-3 mb-2">
          <div *ngFor="let a of accounts" class="card account-card"
               [attr.title]="sectionHelp.accountCard"
               [class.account-active]="selectedAccount === a.account_id"
               (click)="selectAccount(a.account_id)">
            <div class="flex justify-between items-center">
              <span class="text-mono text-sm">{{ a.account_id | slice:0:8 }}...</span>
              <button class="btn-sm btn-primary" (click)="goToDetail(a.account_id); $event.stopPropagation()">Detail &rarr;</button>
            </div>
            <div class="grid-2 mt-1">
              <div>
                <div class="stat-label">Cash</div>
                <div class="stat-value" style="font-size:1.1rem">₹{{ a.cash | number:'1.0-0' }}</div>
              </div>
              <div>
                <div class="stat-label">Equity</div>
                <div class="stat-value" style="font-size:1.1rem">₹{{ a.equity | number:'1.0-0' }}</div>
              </div>
            </div>
          </div>
        </div>

        <div *ngIf="selectedAccount">
          <div class="grid-3 mb-2" [attr.title]="sectionHelp.analytics">
            <div class="mini-card">
              <div class="stat-label">Current Equity</div>
              <div class="stat-value">₹{{ metrics?.current_equity ?? 0 | number:'1.0-0' }}</div>
              <div class="text-muted text-sm">Return {{ formatPct(metrics?.total_return_pct) }}</div>
            </div>
            <div class="mini-card">
              <div class="stat-label">Net / Realized P&L</div>
              <div class="stat-value" [ngClass]="(metrics?.net_pnl ?? 0) >= 0 ? 'text-success' : 'text-danger'">
                ₹{{ metrics?.net_pnl ?? 0 | number:'1.0-0' }}
              </div>
              <div class="text-muted text-sm">Realized ₹{{ metrics?.realized_pnl ?? 0 | number:'1.0-0' }}</div>
            </div>
            <div class="mini-card">
              <div class="stat-label">Open Positions</div>
              <div class="stat-value">{{ metrics?.open_positions ?? 0 }}</div>
              <div class="text-muted text-sm">Capital deployed {{ formatPct(metrics?.cash_utilization_pct) }}</div>
            </div>
            <div class="mini-card">
              <div class="stat-label">Win Rate</div>
              <div class="stat-value">{{ formatPct(metrics?.win_rate) }}</div>
              <div class="text-muted text-sm">{{ metrics?.total_trades ?? 0 }} closed trades</div>
            </div>
            <div class="mini-card">
              <div class="stat-label">Profit Factor</div>
              <div class="stat-value">{{ metrics?.profit_factor != null ? (metrics?.profit_factor | number:'1.2-2') : 'N/A' }}</div>
              <div class="text-muted text-sm">Avg win {{ formatCurrency(metrics?.avg_win) }} / avg loss {{ formatCurrency(metrics?.avg_loss) }}</div>
            </div>
            <div class="mini-card">
              <div class="stat-label">Risk Quality</div>
              <div class="stat-value">{{ metrics?.sharpe != null ? (metrics?.sharpe | number:'1.2-2') : 'N/A' }}</div>
              <div class="text-muted text-sm">Max DD {{ formatPct(metrics?.max_drawdown) }}</div>
            </div>
          </div>

          <div class="grid-2 mb-2">
            <div class="card" [attr.title]="sectionHelp.equityCurve">
            <app-equity-chart [data]="equityData" />
            </div>

            <div class="card" [attr.title]="sectionHelp.holdings">
              <h2>Current Holdings</h2>
              <table *ngIf="metrics?.holdings?.length; else noHoldings" class="compact-table">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Qty</th>
                    <th>Avg</th>
                    <th>Last</th>
                    <th>Weight</th>
                    <th>UPnL</th>
                  </tr>
                </thead>
                <tbody>
                  <tr *ngFor="let holding of metrics?.holdings">
                    <td><strong>{{ holding.ticker }}</strong></td>
                    <td>{{ holding.quantity }}</td>
                    <td class="text-mono">₹{{ holding.avg_price | number:'1.2-2' }}</td>
                    <td class="text-mono">₹{{ holding.last_price | number:'1.2-2' }}</td>
                    <td class="text-mono">{{ formatPct(holding.weight_pct) }}</td>
                    <td class="text-mono" [ngClass]="holding.unrealized_pnl >= 0 ? 'text-success' : 'text-danger'">
                      ₹{{ holding.unrealized_pnl | number:'1.0-0' }}
                    </td>
                  </tr>
                </tbody>
              </table>
              <ng-template #noHoldings>
                <p class="text-muted">No open paper positions in this account yet.</p>
              </ng-template>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .account-card {
      cursor: pointer;
      transition: all var(--transition);
      border: 2px solid transparent;
    }
    .account-card:hover { border-color: var(--color-primary-light); }
    .account-active { border-color: var(--color-primary) !important; background: var(--color-primary-light); }
    .mini-card {
      border: 1px solid rgba(0, 0, 0, 0.08);
      border-radius: 12px;
      padding: 1rem;
      background: rgba(255, 255, 255, 0.72);
    }
    .compact-table td, .compact-table th { padding: 0.45rem 0.35rem; }
  `]
})
export class PaperDashboardComponent implements OnInit {
  readonly sectionHelp = {
    emptyState: 'What: paper trading account onboarding area. How: create a paper account here before testing strategies or replay trading.',
    accountCard: 'What: summary card for a paper account. How: click a card to load its equity curve and drill into detailed paper-trading activity.',
    equityCurve: 'What: selected paper account equity history. How: use it to judge whether your paper strategy is growing smoothly or taking large drawdowns.',
    analytics: 'What: portfolio analytics for the selected paper account. How: use these cards to judge return quality, risk, deployment, and trade efficiency instead of only watching cash and equity.',
    holdings: 'What: current open paper positions. How: review size, last price, weight, and unrealized PnL to see where capital is concentrated.',
  };
  accounts: PaperAccount[] = [];
  selectedAccount: string | null = null;
  equityData: EquityPoint[] = [];
  metrics: AccountMetrics | null = null;
  loading = true;

  constructor(private paperApi: PaperApiService, private router: Router) {}

  ngOnInit(): void {
    this.paperApi.listAccounts().subscribe({
      next: data => { this.accounts = data; this.loading = false; },
      error: () => { this.loading = false; }
    });
  }

  createAccount(): void {
    this.paperApi.createAccount().subscribe(acc => {
      this.accounts = [...this.accounts, acc];
    });
  }

  selectAccount(id: string): void {
    this.selectedAccount = id;
    this.paperApi.getEquity(id).subscribe({
      next: data => this.equityData = data,
      error: () => {}
    });
    this.paperApi.getMetrics(id).subscribe({
      next: data => this.metrics = data,
      error: () => { this.metrics = null; }
    });
  }

  goToDetail(id: string): void {
    this.router.navigate(['/account', id]);
  }

  formatPct(value: number | null | undefined): string {
    return value != null ? `${(value * 100).toFixed(1)}%` : 'N/A';
  }

  formatCurrency(value: number | null | undefined): string {
    return value != null ? `₹${value.toFixed(0)}` : 'N/A';
  }
}
