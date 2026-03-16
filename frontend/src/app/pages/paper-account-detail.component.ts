import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { PaperApiService, EquityPoint } from '../services/paper-api.service';
import { EquityChartComponent } from '../components/equity-chart.component';
import { SimulationSummaryCardComponent } from '../components/simulation-summary-card.component';
import { OrderIntentFormComponent, OrderIntentData } from '../components/order-intent-form.component';

@Component({
  selector: 'app-paper-account-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, EquityChartComponent, SimulationSummaryCardComponent, OrderIntentFormComponent],
  template: `
    <div class="page" *ngIf="accountId">
      <div class="flex justify-between items-center mb-2">
        <h1>Paper Account</h1>
        <span class="badge">{{ accountId }}</span>
      </div>

      <app-simulation-summary-card [accountId]="accountId" />

      <div class="card mt-2">
        <h2>Equity Curve</h2>
        <app-equity-chart [data]="equity" />
      </div>

      <div class="card mt-2">
        <h2>Replay Simulation</h2>
        <div class="form-row">
          <div class="form-group">
            <label>Date</label>
            <input type="date" [(ngModel)]="replayDate" />
          </div>
          <div class="form-group">
            <label>Speed (1-100x)</label>
            <input type="number" [(ngModel)]="replaySpeed" min="1" max="100" />
          </div>
          <div class="form-group" style="justify-content:flex-end">
            <button class="btn-primary" (click)="runReplay()" [disabled]="replaying">
              {{ replaying ? 'Running...' : 'Run Replay' }}
            </button>
          </div>
        </div>
        <pre *ngIf="replayResult" class="replay-result">{{ replayResult | json }}</pre>
      </div>

      <div class="card mt-2">
        <h2>Submit Order Intent</h2>
        <app-order-intent-form (intentSubmit)="submitOrder($event)" />
      </div>
    </div>
    <div *ngIf="!accountId" class="page">
      <div class="card" style="text-align:center; padding: 3rem;">
        <p class="text-muted">No account selected. Go back to the dashboard.</p>
      </div>
    </div>
  `,
  styles: [`
    .replay-result { background: var(--color-bg); padding: 1rem; margin-top: 1rem; border-radius: var(--radius); font-size: 0.85rem; overflow-x: auto; border: 1px solid var(--color-border); }
  `]
})
export class PaperAccountDetailComponent implements OnInit {
  accountId: string | null = null;
  equity: EquityPoint[] = [];
  replayDate = '2025-01-02';
  replaySpeed = 10;
  replayResult: Record<string, unknown> | null = null;
  replaying = false;

  constructor(private route: ActivatedRoute, private paperApi: PaperApiService) {}

  ngOnInit(): void {
    this.accountId = this.route.snapshot.paramMap.get('accountId');
    if (this.accountId) {
      this.paperApi.getEquity(this.accountId).subscribe({
        next: data => this.equity = data,
        error: () => {}
      });
    }
  }

  runReplay(): void {
    if (!this.accountId) return;
    this.replaying = true;
    this.paperApi.replay(this.accountId, this.replayDate, this.replaySpeed).subscribe({
      next: result => {
        this.replayResult = result;
        this.replaying = false;
        this.paperApi.getEquity(this.accountId!).subscribe({
          next: data => this.equity = data,
          error: () => {}
        });
      },
      error: () => { this.replaying = false; }
    });
  }

  submitOrder(intent: OrderIntentData): void {
    if (!this.accountId) return;
    this.paperApi.submitOrderIntent(this.accountId, intent as unknown as Record<string, unknown>).subscribe({
      next: () => {
        this.paperApi.getEquity(this.accountId!).subscribe({
          next: data => this.equity = data,
          error: () => {}
        });
      },
      error: () => {}
    });
  }
}
