import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { PaperApiService, PaperAccount, EquityPoint } from '../services/paper-api.service';
import { EquityChartComponent } from '../components/equity-chart.component';
import { SimulationSummaryCardComponent } from '../components/simulation-summary-card.component';

@Component({
  selector: 'app-paper-dashboard',
  standalone: true,
  imports: [CommonModule, EquityChartComponent, SimulationSummaryCardComponent],
  template: `
    <div class="page">
      <div class="flex justify-between items-center mb-2">
        <h1>Paper Trading Dashboard</h1>
        <button class="btn-primary" (click)="createAccount()">+ Create Account (₹100,000)</button>
      </div>

      <div *ngIf="loading" class="loading-container"><div class="spinner"></div> Loading accounts...</div>

      <div *ngIf="!loading && accounts.length === 0" class="card" style="text-align:center; padding: 3rem;">
        <p class="text-muted">No paper trading accounts yet. Create one to get started.</p>
      </div>

      <div *ngIf="!loading && accounts.length > 0">
        <div class="grid-3 mb-2">
          <div *ngFor="let a of accounts" class="card account-card"
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
          <app-simulation-summary-card [accountId]="selectedAccount" />
          <div class="card mt-2">
            <app-equity-chart [data]="equityData" />
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
  `]
})
export class PaperDashboardComponent implements OnInit {
  accounts: PaperAccount[] = [];
  selectedAccount: string | null = null;
  equityData: EquityPoint[] = [];
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
  }

  goToDetail(id: string): void {
    this.router.navigate(['/account', id]);
  }
}
