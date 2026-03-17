import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MarketApiService, MarketStatus, AccountProfile, BotStatus } from '../services/market-api.service';
import { NotificationService } from '../services/notification.service';

@Component({
  selector: 'app-bot-panel',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page">
      <h1>Auto-Trading Bot</h1>

      <!-- Market Status Banner -->
      <div class="card mb-2 market-banner" [ngClass]="'market-' + (market?.phase || 'closed')" [attr.title]="sectionHelp.marketStatus">
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
            <div class="countdown text-mono">{{ countdownStr }}</div>
          </div>
        </div>
      </div>

      <!-- Account Verification -->
      <div class="card mb-2" [attr.title]="sectionHelp.accountVerification">
        <div class="flex justify-between items-center mb-1">
          <h2>Account Verification</h2>
          <button class="btn-primary btn-sm" (click)="loadAccount()" [disabled]="accountLoading">
            {{ accountLoading ? 'Verifying...' : 'Verify Credentials' }}
          </button>
        </div>

        <div *ngIf="!account" class="text-muted text-sm">Click "Verify Credentials" to check your AngelOne connection.</div>

        <div *ngIf="account">
          <div class="flex items-center gap-1 mb-1">
            <span class="badge" [ngClass]="{
              'badge-success': account.status === 'connected' || account.status === 'paper_mode',
              'badge-warning': account.status === 'not_configured',
              'badge-danger': account.status === 'login_failed' || account.status === 'error'
            }">{{ account.status | uppercase }}</span>
            <span class="text-sm">{{ account.message }}</span>
          </div>

          <div *ngIf="account.name" class="grid-3">
            <div class="stat-card">
              <div class="stat-label">Account Name</div>
              <div class="stat-value">{{ account.name }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Client ID</div>
              <div class="stat-value">{{ account.client_id }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Available Balance</div>
              <div class="stat-value text-success">₹{{ account.balance | number:'1.2-2' }}</div>
            </div>
          </div>

          <div *ngIf="account.name" class="grid-3 mt-1">
            <div class="stat-card">
              <div class="stat-label">Net Value</div>
              <div class="stat-value">₹{{ account.net | number:'1.2-2' }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Available Margin</div>
              <div class="stat-value">₹{{ account.available_margin | number:'1.2-2' }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Email</div>
              <div class="stat-value text-sm">{{ account.email || '—' }}</div>
            </div>
          </div>

          <!-- Credentials checklist -->
          <div *ngIf="account.credentials_set" class="mt-1">
            <div class="text-sm text-muted mb-05">Credentials Status:</div>
            <div class="flex gap-1 flex-wrap">
              <span *ngFor="let cred of credentialsList" class="badge" [ngClass]="cred.set ? 'badge-success' : 'badge-danger'">
                {{ cred.set ? '✓' : '✗' }} {{ cred.key }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div class="flex gap-3" style="align-items: flex-start;">
        <!-- Bot Controls -->
        <div class="card" style="flex: 1; min-width: 340px;" [attr.title]="sectionHelp.botConfig">
          <h2>Bot Configuration</h2>

          <div class="form-group">
            <label>Watchlist (comma-separated)</label>
            <input [(ngModel)]="watchlistStr" placeholder="RELIANCE, TCS, INFY, HDFCBANK" />
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>Min Confidence</label>
              <input type="number" [(ngModel)]="botConfig.min_confidence" min="0.1" max="1" step="0.05" />
            </div>
            <div class="form-group">
              <label>Max Positions</label>
              <input type="number" [(ngModel)]="botConfig.max_positions" min="1" max="20" />
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>Position Size (₹)</label>
              <input type="number" [(ngModel)]="botConfig.position_size" min="1000" step="1000" />
            </div>
            <div class="form-group">
              <label>Cycle Interval (sec)</label>
              <input type="number" [(ngModel)]="botConfig.cycle_interval" min="10" max="600" />
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>Stop Loss %</label>
              <input type="number" [(ngModel)]="botConfig.stop_loss_pct" min="0.005" max="0.1" step="0.005" />
            </div>
            <div class="form-group">
              <label>Take Profit %</label>
              <input type="number" [(ngModel)]="botConfig.take_profit_pct" min="0.01" max="0.2" step="0.01" />
            </div>
          </div>

          <div *ngIf="!isMarketOpen && !botRunning" class="market-closed-hint">
            🔒 Market is closed — bot cannot be started
          </div>

          <!-- Consent Prompt -->
          <div *ngIf="botStatus?.consent_pending" class="consent-banner">
            <div style="margin-bottom: 0.5rem">
              <strong>ðŸ”” Market has reopened!</strong>
              <div class="text-sm">Do you want to resume trading?</div>
              <div class="text-sm text-mono" *ngIf="botStatus?.auto_resume_in != null">
                Auto-resuming in {{ botStatus!.auto_resume_in }}s
              </div>
            </div>
            <div class="flex gap-1">
              <button class="btn-success" (click)="grantConsent()">✓ Resume Trading</button>
              <button class="btn-danger" (click)="declineConsent()">✗ Stop Bot</button>
            </div>
          </div>

          <!-- Paused Indicator -->
          <div *ngIf="botStatus?.paused && !botStatus?.consent_pending && botRunning" class="paused-indicator">
            ⏸ Bot is paused — waiting for market to reopen
          </div>

          <div class="flex gap-1 mt-1">
            <button class="btn-success btn-lg" style="flex:1" (click)="startBot()" [disabled]="botRunning || starting">
              {{ starting ? 'Starting...' : '▶ Start Bot' }}
            </button>
            <button class="btn-danger btn-lg" style="flex:1" (click)="stopBot()" [disabled]="!botRunning || stopping">
              {{ stopping ? 'Stopping...' : '■ Stop Bot' }}
            </button>
          </div>

          <div *ngIf="botRunning" class="bot-running-indicator mt-1">
            <span class="pulse-dot"></span> Bot is running – Cycle #{{ botStatus?.cycle_count || 0 }}
          </div>
        </div>

        <!-- Bot Status & Trades -->
        <div style="flex: 1.5; min-width: 400px;">
          <!-- Active Positions -->
          <div class="card mb-2" [attr.title]="sectionHelp.positions">
            <div class="flex justify-between items-center">
              <h2>Active Positions</h2>
              <span class="badge badge-info">{{ positionEntries.length }} open</span>
            </div>
            <div *ngIf="positionEntries.length === 0" class="text-muted text-sm">No active positions.</div>
            <div *ngFor="let p of positionEntries" class="intent-row">
              <div class="flex justify-between items-center">
                <div>
                  <span class="badge" [ngClass]="p.value.side === 'buy' ? 'badge-buy' : 'badge-sell'">{{ p.value.side }}</span>
                  <strong style="margin-left: 8px;">{{ p.key }}</strong>
                  <span class="text-muted" style="margin-left: 8px;">× {{ p.value.quantity }}</span>
                </div>
                <div class="text-right">
                  <div>Entry: ₹{{ p.value.entry_price | number:'1.2-2' }}</div>
                  <div [ngClass]="p.value.pnl >= 0 ? 'text-success' : 'text-danger'">
                    P&L: ₹{{ p.value.pnl | number:'1.2-2' }}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- PnL Summary -->
          <div class="card mb-2" [attr.title]="sectionHelp.pnlSummary">
            <div class="grid-4">
              <div class="stat-card">
                <div class="stat-label">Total P&L</div>
                <div class="stat-value" [ngClass]="(botStatus?.total_pnl || 0) >= 0 ? 'text-success' : 'text-danger'">
                  ₹{{ botStatus?.total_pnl || 0 | number:'1.2-2' }}
                </div>
              </div>
              <div class="stat-card">
                <div class="stat-label">Trades Today</div>
                <div class="stat-value">{{ botStatus?.trades_today?.length || 0 }}</div>
              </div>
              <div class="stat-card">
                <div class="stat-label">Cycles Run</div>
                <div class="stat-value">{{ botStatus?.cycle_count || 0 }}</div>
              </div>
              <div class="stat-card">
                <div class="stat-label">Last Cycle</div>
                <div class="stat-value text-sm">{{ botStatus?.last_cycle ? (botStatus!.last_cycle | date:'shortTime') : '—' }}</div>
              </div>
            </div>
          </div>

          <!-- Trade Log -->
          <div class="card" [attr.title]="sectionHelp.tradeLog">
            <h2>Trade Log</h2>
            <div *ngIf="!botStatus?.trades_today?.length" class="text-muted text-sm">No trades yet.</div>
            <table *ngIf="botStatus?.trades_today?.length">
              <thead>
                <tr>
                  <th>Time</th><th>Ticker</th><th>Action</th><th>Side</th><th>Qty</th><th>Price</th><th>P&L</th>
                </tr>
              </thead>
              <tbody>
                <tr *ngFor="let t of botStatus!.trades_today">
                  <td class="text-mono text-sm">{{ t.timestamp | date:'shortTime' }}</td>
                  <td><strong>{{ t.ticker }}</strong></td>
                  <td>
                    <span class="badge" [ngClass]="{
                      'badge-info': t.action === 'ENTRY',
                      'badge-danger': t.action === 'STOP_LOSS',
                      'badge-success': t.action === 'TAKE_PROFIT'
                    }">{{ t.action }}</span>
                  </td>
                  <td><span class="badge" [ngClass]="t.side === 'buy' ? 'badge-buy' : 'badge-sell'">{{ t.side }}</span></td>
                  <td>{{ t.quantity }}</td>
                  <td>₹{{ t.price | number:'1.2-2' }}</td>
                  <td [ngClass]="(t.pnl || 0) >= 0 ? 'text-success' : 'text-danger'">
                    {{ t.pnl ? '₹' + (t.pnl | number:'1.2-2') : '—' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Errors -->
          <div class="card mt-2" *ngIf="botStatus?.errors?.length" [attr.title]="sectionHelp.errors">
            <h2>Bot Errors</h2>
            <div *ngFor="let e of botStatus!.errors" class="text-sm text-danger" style="margin-bottom: 4px;">
              ⚠ {{ e }}
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
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
    .countdown { font-size: 1.1rem; font-weight: 600; color: var(--color-primary); }
    .bot-running-indicator {
      display: flex; align-items: center; gap: 8px;
      padding: 8px 12px; border-radius: var(--radius-md);
      background: rgba(22, 163, 74, 0.08); color: #16a34a;
      font-weight: 600; font-size: 0.9rem;
    }
    .pulse-dot {
      width: 10px; height: 10px; border-radius: 50%;
      background: #16a34a; animation: pulse 1.5s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.5; transform: scale(1.3); }
    }
    .intent-row {
      padding: 12px; border: 1px solid var(--color-border);
      border-radius: var(--radius-md); margin-bottom: 8px;
      transition: background var(--transition);
    }
    .intent-row:hover { background: var(--color-surface-hover); }
    .text-success { color: #16a34a; }
    .text-danger { color: #dc2626; }
    .btn-success {
      background: #16a34a; color: white; border: none; padding: 10px 20px;
      border-radius: var(--radius-md); cursor: pointer; font-weight: 600; font-size: 1rem;
    }
    .btn-success:hover { background: #15803d; }
    .btn-success:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-danger {
      background: #dc2626; color: white; border: none; padding: 10px 20px;
      border-radius: var(--radius-md); cursor: pointer; font-weight: 600; font-size: 1rem;
    }
    .btn-danger:hover { background: #b91c1c; }
    .btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }
    .market-closed-hint {
      padding: 10px 14px; border-radius: var(--radius-md); margin-bottom: 0.5rem;
      background: rgba(220, 38, 38, 0.06); color: #dc2626; font-weight: 600;
      text-align: center; font-size: 0.9rem;
    }
    .consent-banner {
      padding: 14px; border-radius: var(--radius-md); margin-bottom: 0.75rem;
      background: rgba(245, 158, 11, 0.1); border: 2px solid #f59e0b;
      text-align: center;
    }
    .paused-indicator {
      padding: 10px 14px; border-radius: var(--radius-md); margin-bottom: 0.5rem;
      background: rgba(99, 102, 241, 0.08); color: #6366f1; font-weight: 600;
      text-align: center; font-size: 0.9rem;
    }
    .badge-warning { background: #fef3c7; color: #92400e; }
    .badge-danger { background: #fee2e2; color: #991b1b; }
    .badge-info { background: #dbeafe; color: #1e40af; }
    .mt-1 { margin-top: 0.75rem; }
    .mb-05 { margin-bottom: 0.375rem; }
    .flex-wrap { flex-wrap: wrap; }
    @media (max-width: 900px) {
      :host .flex.gap-3 { flex-direction: column; }
    }
  `]
})
export class BotPanelComponent implements OnInit, OnDestroy {
  readonly sectionHelp = {
    marketStatus: 'What: current market phase and countdown to the next session event. How: the bot uses this to decide whether it can trade, pause, or wait for consent.',
    accountVerification: 'What: broker or paper account connectivity and balances. How: verify this before starting the bot so you know credentials and capital are available.',
    botConfig: 'What: bot risk and execution settings. How: set watchlist, confidence, size, cycle interval, stop loss, and take profit before pressing Start.',
    positions: 'What: open bot-managed positions. How: monitor entries, quantity, and running PnL while the bot is active.',
    pnlSummary: 'What: session-level bot performance summary. How: use it to track overall PnL, cycles, and how many trades have been taken today.',
    tradeLog: 'What: chronological bot trade activity. How: review entries, exits, and realized PnL to understand what the bot is doing.',
    errors: 'What: recent bot errors and execution issues. How: check here first if the bot pauses unexpectedly or stops taking trades.',
  };
  market: MarketStatus | null = null;
  account: AccountProfile | null = null;
  accountLoading = false;
  botStatus: BotStatus | null = null;
  botRunning = false;
  starting = false;
  stopping = false;
  countdownStr = '';
  watchlistStr = 'RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK';

  botConfig = {
    min_confidence: 0.7,
    max_positions: 5,
    position_size: 10000,
    stop_loss_pct: 0.02,
    take_profit_pct: 0.05,
    cycle_interval: 60,
  };

  credentialsList: { key: string; set: boolean }[] = [];
  positionEntries: { key: string; value: any }[] = [];

  get isMarketOpen(): boolean {
    if (!this.market) return false;
    return this.market.phase === 'open' || this.market.phase === 'pre_open';
  }

  private marketTimer: any;
  private statusTimer: any;
  private countdownTimer: any;
  private secondsLeft = 0;

  constructor(
    private marketApi: MarketApiService,
    private notify: NotificationService
  ) {}

  ngOnInit(): void {
    this.loadMarket();
    this.loadBotStatus();
    // Refresh market status every 30s
    this.marketTimer = setInterval(() => this.loadMarket(), 30_000);
    // Refresh bot status every 5s (always, since bot can be paused)
    this.statusTimer = setInterval(() => {
      this.loadBotStatus();
    }, 5_000);
    // Countdown tick
    this.countdownTimer = setInterval(() => this.tickCountdown(), 1000);
  }

  ngOnDestroy(): void {
    clearInterval(this.marketTimer);
    clearInterval(this.statusTimer);
    clearInterval(this.countdownTimer);
  }

  loadMarket(): void {
    this.marketApi.getMarketStatus().subscribe({
      next: m => {
        this.market = m;
        this.secondsLeft = m.seconds_to_next;
      },
      error: () => {}
    });
  }

  tickCountdown(): void {
    if (this.secondsLeft > 0) {
      this.secondsLeft--;
      const h = Math.floor(this.secondsLeft / 3600);
      const m = Math.floor((this.secondsLeft % 3600) / 60);
      const s = this.secondsLeft % 60;
      this.countdownStr = h > 0
        ? `${h}h ${m}m ${s}s`
        : m > 0 ? `${m}m ${s}s` : `${s}s`;
    }
  }

  loadAccount(): void {
    this.accountLoading = true;
    this.marketApi.getAccountProfile().subscribe({
      next: a => {
        this.account = a;
        this.accountLoading = false;
        this.credentialsList = a.credentials_set
          ? Object.entries(a.credentials_set).map(([key, set]) => ({ key, set }))
          : [];
        if (a.status === 'connected' || a.status === 'paper_mode') {
          this.notify.success(`Account verified: ${a.name}`);
        } else {
          this.notify.error(a.message || 'Verification failed');
        }
      },
      error: () => {
        this.accountLoading = false;
        this.notify.error('Failed to verify account');
      }
    });
  }

  loadBotStatus(): void {
    this.marketApi.getBotStatus().subscribe({
      next: s => {
        this.botStatus = s;
        this.botRunning = s.running;
        this.positionEntries = Object.entries(s.positions || {}).map(([key, value]) => ({ key, value }));
      },
      error: () => {}
    });
  }

  startBot(): void {
    this.starting = true;
    const config = {
      ...this.botConfig,
      watchlist: this.watchlistStr.split(',').map(t => t.trim()).filter(t => t),
    };
    this.marketApi.startBot(config).subscribe({
      next: res => {
        this.starting = false;
        this.botRunning = true;
        this.notify.success(res.message || 'Bot started');
        this.loadBotStatus();
      },
      error: () => {
        this.starting = false;
        this.notify.error('Failed to start bot');
      }
    });
  }

  stopBot(): void {
    this.stopping = true;
    this.marketApi.stopBot().subscribe({
      next: res => {
        this.stopping = false;
        this.botRunning = false;
        this.notify.success(res.message || 'Bot stopped');
        this.loadBotStatus();
      },
      error: () => {
        this.stopping = false;
        this.notify.error('Failed to stop bot');
      }
    });
  }

  grantConsent(): void {
    this.marketApi.botConsent(true).subscribe({
      next: (res: any) => {
        this.notify.success(res.message || 'Trading resumed');
        this.loadBotStatus();
      },
      error: () => this.notify.error('Failed to grant consent')
    });
  }

  declineConsent(): void {
    this.marketApi.botConsent(false).subscribe({
      next: (res: any) => {
        this.botRunning = false;
        this.notify.success(res.message || 'Bot stopped');
        this.loadBotStatus();
      },
      error: () => this.notify.error('Failed to decline consent')
    });
  }
}
