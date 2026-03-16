import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TradeApiService, TradeIntentRequest, TradeIntent, Execution } from '../services/trade-api.service';
import { AuthService } from '../services/auth.service';
import { NotificationService } from '../services/notification.service';
import { MarketApiService, MarketStatus } from '../services/market-api.service';

@Component({
  selector: 'app-trading',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page">
      <h1>Trading</h1>

      <!-- Market Status Banner -->
      <div class="card mb-2 market-banner" [ngClass]="'market-' + (market?.phase || 'closed')">
        <div class="flex justify-between items-center">
          <div class="flex items-center gap-1">
            <span class="market-dot" [ngClass]="{'dot-open': market?.phase === 'open', 'dot-pre': market?.phase === 'pre_open', 'dot-closed': market?.phase !== 'open' && market?.phase !== 'pre_open'}"></span>
            <div>
              <strong>{{ market?.message || 'Loading market status...' }}</strong>
              <div class="text-sm text-muted">{{ market?.ist_now }}</div>
            </div>
          </div>
          <div class="text-right">
            <div class="text-sm">{{ market?.next_event }}</div>
            <strong>{{ market?.next_event_time }}</strong>
          </div>
        </div>
      </div>

      <!-- Auth Token -->
      <div class="card mb-2" *ngIf="!auth.isAuthenticated">
        <h3>Authentication Required</h3>
        <p class="text-muted text-sm">Set your API token to execute trades.</p>
        <div class="flex gap-1">
          <input type="password" [(ngModel)]="tokenInput" placeholder="Bearer token" style="flex:1" />
          <button class="btn-primary" (click)="setToken()">Set Token</button>
        </div>
      </div>
      <div class="card mb-2" *ngIf="auth.isAuthenticated">
        <div class="flex justify-between items-center">
          <span class="badge badge-success">Authenticated</span>
          <button class="btn-sm btn-danger" (click)="auth.clearToken()">Logout</button>
        </div>
      </div>

      <div class="flex gap-3" style="align-items: flex-start;">
        <!-- Order Form -->
        <div class="card" style="flex: 1; min-width: 320px;">
          <h2>Create Trade Intent</h2>

          <div *ngIf="!isMarketOpen" class="market-closed-overlay">
            <span>🔒 Market is closed — trading is disabled</span>
          </div>

          <fieldset [disabled]="!isMarketOpen">
            <div class="tab-bar">
              <button class="tab" [class.active]="orderTab === 'equity'" (click)="orderTab = 'equity'">Equity</button>
              <button class="tab" [class.active]="orderTab === 'options'" (click)="orderTab = 'options'">Options</button>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>Ticker</label>
                <input [(ngModel)]="form.ticker" placeholder="RELIANCE" required />
              </div>
              <div class="form-group">
                <label>Side</label>
                <select [(ngModel)]="form.side">
                  <option value="buy">Buy</option>
                  <option value="sell">Sell</option>
                </select>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>Quantity</label>
                <input type="number" [(ngModel)]="form.quantity" min="1" required />
              </div>
              <div class="form-group">
                <label>Order Type</label>
                <select [(ngModel)]="form.order_type">
                  <option value="market">Market</option>
                  <option value="limit">Limit</option>
                </select>
              </div>
            </div>

            <div *ngIf="form.order_type === 'limit'" class="form-group">
              <label>Limit Price (₹)</label>
              <input type="number" [(ngModel)]="form.limit_price" min="0.01" step="0.01" />
            </div>

            <!-- Options fields -->
            <div *ngIf="orderTab === 'options'">
              <div class="form-row">
                <div class="form-group">
                  <label>Option Type</label>
                  <select [(ngModel)]="form.option_type">
                    <option value="CE">Call (CE)</option>
                    <option value="PE">Put (PE)</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>Strike Price</label>
                  <input type="number" [(ngModel)]="form.strike" min="0" step="0.5" />
                </div>
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>Expiry</label>
                  <input type="date" [(ngModel)]="form.expiry" />
                </div>
                <div class="form-group">
                  <label>Strategy</label>
                  <select [(ngModel)]="form.strategy">
                    <option value="single">Single</option>
                    <option value="vertical_spread">Vertical Spread</option>
                    <option value="iron_condor">Iron Condor</option>
                    <option value="covered_call">Covered Call</option>
                  </select>
                </div>
              </div>
            </div>

            <button class="btn-primary btn-lg" style="width: 100%; margin-top: 0.5rem;" (click)="createIntent()" [disabled]="submitting || !isMarketOpen">
              {{ !isMarketOpen ? 'ðŸ”’ Market Closed' : submitting ? 'Submitting...' : 'Create Intent' }}
            </button>
          </fieldset>
        </div>

        <!-- Intents & Executions -->
        <div style="flex: 1.5; min-width: 400px;">
          <!-- Pending Intents -->
          <div class="card mb-2">
            <h2>Pending Intents</h2>
            <div *ngIf="intents.length === 0" class="text-muted text-sm">No pending intents.</div>
            <div *ngFor="let intent of intents" class="intent-row">
              <div class="flex justify-between items-center">
                <div>
                  <span class="badge" [ngClass]="intent.side === 'buy' ? 'badge-buy' : 'badge-sell'">{{ intent.side }}</span>
                  <strong style="margin-left: 8px;">{{ intent.ticker }}</strong>
                  <span class="text-muted" style="margin-left: 8px;">× {{ intent.quantity }}</span>
                  <span *ngIf="intent.option_type" class="badge badge-info" style="margin-left: 8px;">{{ intent.option_type }} {{ intent.strike }}</span>
                </div>
                <div class="flex items-center gap-1">
                  <span class="text-sm text-muted">Est: ₹{{ intent.estimated_cost | number:'1.2-2' }}</span>
                  <button class="btn-sm btn-success" (click)="executeIntent(intent)" [disabled]="!auth.isAuthenticated || executingId === intent.intent_id || !isMarketOpen">
                    {{ !isMarketOpen ? 'ðŸ”’' : executingId === intent.intent_id ? 'Executing...' : 'Execute' }}
                  </button>
                </div>
              </div>
              <div class="text-sm text-muted mt-1">
                {{ intent.order_type | uppercase }} · ID: <span class="text-mono">{{ intent.intent_id | slice:0:8 }}...</span>
                · {{ intent.created_at | date:'short' }}
              </div>
            </div>
          </div>

          <!-- Executions -->
          <div class="card">
            <h2>Executions</h2>
            <div *ngIf="executions.length === 0" class="text-muted text-sm">No executions yet.</div>
            <table *ngIf="executions.length > 0">
              <thead>
                <tr>
                  <th>Ticker</th><th>Side</th><th>Qty</th><th>Filled</th><th>Total</th><th>Slippage</th><th>Latency</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr *ngFor="let e of executions">
                  <td><strong>{{ e.ticker }}</strong></td>
                  <td><span class="badge" [ngClass]="e.side === 'buy' ? 'badge-buy' : 'badge-sell'">{{ e.side }}</span></td>
                  <td>{{ e.quantity }}</td>
                  <td>₹{{ e.filled_price | number:'1.2-2' }}</td>
                  <td>₹{{ e.total_value | number:'1.2-2' }}</td>
                  <td class="text-mono text-sm">{{ e.slippage | number:'1.4-4' }}</td>
                  <td class="text-mono text-sm">{{ e.latency_ms | number:'1.1-1' }}ms</td>
                  <td><span class="badge badge-success">{{ e.status }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .intent-row {
      padding: 12px;
      border: 1px solid var(--color-border);
      border-radius: var(--radius-md);
      margin-bottom: 8px;
      transition: background var(--transition);
    }
    .intent-row:hover { background: var(--color-surface-hover); }
    .market-banner { border-left: 4px solid var(--color-border); }
    .market-open { border-left-color: #16a34a; background: rgba(22, 163, 74, 0.04); }
    .market-pre_open { border-left-color: #f59e0b; background: rgba(245, 158, 11, 0.04); }
    .market-closed, .market-holiday, .market-weekend, .market-post_close {
      border-left-color: #dc2626; background: rgba(220, 38, 38, 0.04);
    }
    .market-dot {
      width: 12px; height: 12px; border-radius: 50%; display: inline-block; flex-shrink: 0;
    }
    .dot-open { background: #16a34a; box-shadow: 0 0 8px rgba(22, 163, 74, 0.5); }
    .dot-pre { background: #f59e0b; box-shadow: 0 0 8px rgba(245, 158, 11, 0.5); }
    .dot-closed { background: #dc2626; }
    .market-closed-overlay {
      padding: 10px 14px; border-radius: var(--radius-md); margin-bottom: 0.75rem;
      background: rgba(220, 38, 38, 0.06); color: #dc2626; font-weight: 600;
      text-align: center; font-size: 0.9rem;
    }
    fieldset { border: none; padding: 0; margin: 0; }
    fieldset:disabled { opacity: 0.5; pointer-events: none; }
    .btn-success {
      background: #16a34a; color: white; border: none; padding: 6px 14px;
      border-radius: var(--radius-md); cursor: pointer; font-weight: 600;
    }
    .btn-success:disabled { opacity: 0.5; cursor: not-allowed; }
    @media (max-width: 900px) {
      :host .flex.gap-3 { flex-direction: column; }
    }
  `]
})
export class TradingComponent implements OnInit, OnDestroy {
  tokenInput = '';
  orderTab: 'equity' | 'options' = 'equity';
  submitting = false;
  executingId: string | null = null;
  market: MarketStatus | null = null;
  private marketTimer: any;

  form: TradeIntentRequest = {
    ticker: 'RELIANCE',
    side: 'buy',
    quantity: 10,
    order_type: 'market'
  };

  intents: TradeIntent[] = [];
  executions: Execution[] = [];

  get isMarketOpen(): boolean {
    if (!this.market) return false;
    return this.market.phase === 'open' || this.market.phase === 'pre_open';
  }

  constructor(
    public auth: AuthService,
    private tradeApi: TradeApiService,
    private notify: NotificationService,
    private marketApi: MarketApiService
  ) {}

  ngOnInit(): void {
    this.loadMarket();
    this.marketTimer = setInterval(() => this.loadMarket(), 30_000);
  }

  ngOnDestroy(): void {
    clearInterval(this.marketTimer);
  }

  loadMarket(): void {
    this.marketApi.getMarketStatus().subscribe({
      next: m => { this.market = m; },
      error: () => {}
    });
  }

  setToken(): void {
    if (this.tokenInput.trim()) {
      this.auth.setToken(this.tokenInput.trim());
      this.tokenInput = '';
      this.notify.success('Token saved.');
    }
  }

  createIntent(): void {
    if (!this.form.ticker || this.form.quantity < 1) {
      this.notify.warning('Please fill ticker and quantity.');
      return;
    }

    this.submitting = true;
    const request: TradeIntentRequest = { ...this.form };
    if (this.orderTab === 'equity') {
      delete request.option_type;
      delete request.strike;
      delete request.expiry;
      delete request.strategy;
    }
    if (request.order_type !== 'limit') {
      delete request.limit_price;
    }

    this.tradeApi.createIntent(request).subscribe({
      next: intent => {
        this.intents = [intent, ...this.intents];
        this.submitting = false;
        this.notify.success(`Intent created for ${intent.ticker} — Est: ₹${intent.estimated_cost.toFixed(2)}`);
      },
      error: () => { this.submitting = false; }
    });
  }

  executeIntent(intent: TradeIntent): void {
    this.executingId = intent.intent_id;
    this.tradeApi.execute(intent.intent_id).subscribe({
      next: exec => {
        this.executions = [exec, ...this.executions];
        this.intents = this.intents.filter(i => i.intent_id !== intent.intent_id);
        this.executingId = null;
        this.notify.success(`Trade executed: ${exec.ticker} ${exec.side} × ${exec.quantity} @ ₹${exec.filled_price.toFixed(2)}`);
      },
      error: () => { this.executingId = null; }
    });
  }
}
