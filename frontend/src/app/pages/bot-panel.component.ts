import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  AccountProfile,
  BotStatus,
  MarketApiService,
  MarketStatus,
  RuntimeHealthSummary,
} from '../services/market-api.service';
import { NotificationService } from '../services/notification.service';

type BotTab = 'equity' | 'options' | 'health';

@Component({
  selector: 'app-bot-panel',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './bot-panel.component.html',
  styleUrl: './bot-panel.component.css',
})
export class BotPanelComponent implements OnInit, OnDestroy {
  readonly sectionHelp = {
    marketStatus: 'What: current market phase and countdown to the next session event. How: the automation layer uses this to start, pause, and request consent safely.',
    accountVerification: 'What: broker or paper account connectivity and balances. How: verify this before starting any bot so the system knows the account it will trade against.',
    equityBot: 'What: automated equity trading controls. How: choose symbols, confidence, position sizing, and exit rules before starting the equity bot.',
    optionsBot: 'What: automated options trading controls. How: choose liquid underlyings and option contract rules. This bot currently runs safely in paper mode when live option contracts are unavailable.',
    runtimeHealth: 'What: operational readiness of the automation system. How: use it to check service mode, market session, bot health, and whether the current environment supports execution.',
    positions: 'What: open positions managed by the selected bot. How: monitor entry price, quantity, contract details, and running PnL while the bot is active.',
    tradeLog: 'What: chronological trade history for the selected bot. How: review entries, exits, and reasons to understand current behavior.',
    errors: 'What: recent bot errors and execution issues. How: check here first if a bot pauses, rejects trades, or stops cycling.',
  };

  activeTab: BotTab = 'equity';
  market: MarketStatus | null = null;
  account: AccountProfile | null = null;
  runtimeHealth: RuntimeHealthSummary | null = null;
  accountLoading = false;
  countdownStr = '';

  equityBotStatus: BotStatus | null = null;
  optionsBotStatus: BotStatus | null = null;
  equityWatchlistStr = 'RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK';
  optionsWatchlistStr = 'NIFTY50, BANKNIFTY, RELIANCE, TCS, INFY, HDFCBANK';

  equityConfig = {
    min_confidence: 0.7,
    max_positions: 5,
    position_size_pct: 0.1,
    stop_loss_pct: 0.02,
    take_profit_pct: 0.05,
    cycle_interval: 60,
  };

  optionsConfig = {
    min_confidence: 0.72,
    max_positions: 3,
    position_size_pct: 0.05,
    stop_loss_pct: 0.25,
    take_profit_pct: 0.4,
    cycle_interval: 90,
    option_bias: 'both',
    expiry_days: 7,
    strike_steps_from_atm: 0,
    min_days_to_expiry: 2,
  };

  credentialsList: { key: string; set: boolean }[] = [];
  equityStarting = false;
  equityStopping = false;
  optionsStarting = false;
  optionsStopping = false;

  private marketTimer: any;
  private statusTimer: any;
  private countdownTimer: any;
  private secondsLeft = 0;
  private equityHydrated = false;
  private optionsHydrated = false;

  constructor(
    private marketApi: MarketApiService,
    private notify: NotificationService,
  ) {}

  get isMarketOpen(): boolean {
    if (!this.market) return false;
    return this.market.phase === 'open' || this.market.phase === 'pre_open';
  }

  get equityPositions(): { key: string; value: any }[] {
    return Object.entries(this.equityBotStatus?.positions || {}).map(([key, value]) => ({ key, value }));
  }

  get optionsPositions(): { key: string; value: any }[] {
    return Object.entries(this.optionsBotStatus?.positions || {}).map(([key, value]) => ({ key, value }));
  }

  ngOnInit(): void {
    this.loadMarket();
    this.loadRuntimeHealth();
    this.loadEquityBotStatus();
    this.loadOptionsBotStatus();
    this.marketTimer = setInterval(() => this.loadMarket(), 30000);
    this.statusTimer = setInterval(() => {
      this.loadRuntimeHealth();
      this.loadEquityBotStatus();
      this.loadOptionsBotStatus();
    }, 5000);
    this.countdownTimer = setInterval(() => this.tickCountdown(), 1000);
  }

  ngOnDestroy(): void {
    clearInterval(this.marketTimer);
    clearInterval(this.statusTimer);
    clearInterval(this.countdownTimer);
  }

  setTab(tab: BotTab): void {
    this.activeTab = tab;
  }

  loadMarket(): void {
    this.marketApi.getMarketStatus().subscribe({
      next: market => {
        this.market = market;
        this.secondsLeft = market.seconds_to_next;
      },
      error: () => {},
    });
  }

  loadRuntimeHealth(): void {
    this.marketApi.getRuntimeHealth().subscribe({
      next: summary => {
        this.runtimeHealth = summary;
      },
      error: () => {},
    });
  }

  tickCountdown(): void {
    if (this.secondsLeft <= 0) {
      this.countdownStr = '0s';
      return;
    }
    this.secondsLeft -= 1;
    const h = Math.floor(this.secondsLeft / 3600);
    const m = Math.floor((this.secondsLeft % 3600) / 60);
    const s = this.secondsLeft % 60;
    this.countdownStr = h > 0 ? `${h}h ${m}m ${s}s` : m > 0 ? `${m}m ${s}s` : `${s}s`;
  }

  loadAccount(): void {
    this.accountLoading = true;
    this.marketApi.getAccountProfile().subscribe({
      next: account => {
        this.account = account;
        this.accountLoading = false;
        this.credentialsList = account.credentials_set
          ? Object.entries(account.credentials_set).map(([key, set]) => ({ key, set }))
          : [];
        if (account.status === 'connected' || account.status === 'paper_mode') {
          this.notify.success(`Account verified: ${account.name}`);
        } else {
          this.notify.error(account.message || 'Verification failed');
        }
      },
      error: () => {
        this.accountLoading = false;
        this.notify.error('Failed to verify account');
      },
    });
  }

  loadEquityBotStatus(): void {
    this.marketApi.getBotStatus().subscribe({
      next: status => {
        this.equityBotStatus = status;
        if (!this.equityHydrated) {
          this.equityHydrated = true;
          this.equityWatchlistStr = status.watchlist.join(', ');
          this.equityConfig = {
            min_confidence: status.min_confidence,
            max_positions: status.max_positions,
            position_size_pct: status.position_size_pct,
            stop_loss_pct: status.stop_loss_pct,
            take_profit_pct: status.take_profit_pct,
            cycle_interval: status.cycle_interval,
          };
        }
      },
      error: () => {},
    });
  }

  loadOptionsBotStatus(): void {
    this.marketApi.getOptionsBotStatus().subscribe({
      next: status => {
        this.optionsBotStatus = status;
        if (!this.optionsHydrated) {
          this.optionsHydrated = true;
          this.optionsWatchlistStr = status.watchlist.join(', ');
          this.optionsConfig = {
            min_confidence: status.min_confidence,
            max_positions: status.max_positions,
            position_size_pct: status.position_size_pct,
            stop_loss_pct: status.stop_loss_pct,
            take_profit_pct: status.take_profit_pct,
            cycle_interval: status.cycle_interval,
            option_bias: status.option_bias || 'both',
            expiry_days: status.expiry_days || 7,
            strike_steps_from_atm: status.strike_steps_from_atm || 0,
            min_days_to_expiry: status.min_days_to_expiry || 2,
          };
        }
      },
      error: () => {},
    });
  }

  startEquityBot(): void {
    this.equityStarting = true;
    const payload = {
      ...this.equityConfig,
      watchlist: this.parseWatchlist(this.equityWatchlistStr),
    };
    this.marketApi.startBot(payload).subscribe({
      next: result => {
        this.equityStarting = false;
        this.notify.success(result.message || 'Equity bot started');
        this.loadEquityBotStatus();
        this.loadRuntimeHealth();
      },
      error: error => {
        this.equityStarting = false;
        this.notify.error(error?.error?.message || 'Failed to start equity bot');
      },
    });
  }

  stopEquityBot(): void {
    this.equityStopping = true;
    this.marketApi.stopBot().subscribe({
      next: result => {
        this.equityStopping = false;
        this.notify.success(result.message || 'Equity bot stopped');
        this.loadEquityBotStatus();
        this.loadRuntimeHealth();
      },
      error: () => {
        this.equityStopping = false;
        this.notify.error('Failed to stop equity bot');
      },
    });
  }

  startOptionsBot(): void {
    this.optionsStarting = true;
    const payload = {
      ...this.optionsConfig,
      watchlist: this.parseWatchlist(this.optionsWatchlistStr),
    };
    this.marketApi.startOptionsBot(payload).subscribe({
      next: result => {
        this.optionsStarting = false;
        this.notify.success(result.message || 'Options bot started');
        this.loadOptionsBotStatus();
        this.loadRuntimeHealth();
      },
      error: error => {
        this.optionsStarting = false;
        this.notify.error(error?.error?.message || 'Failed to start options bot');
      },
    });
  }

  stopOptionsBot(): void {
    this.optionsStopping = true;
    this.marketApi.stopOptionsBot().subscribe({
      next: result => {
        this.optionsStopping = false;
        this.notify.success(result.message || 'Options bot stopped');
        this.loadOptionsBotStatus();
        this.loadRuntimeHealth();
      },
      error: () => {
        this.optionsStopping = false;
        this.notify.error('Failed to stop options bot');
      },
    });
  }

  grantEquityConsent(): void {
    this.marketApi.botConsent(true).subscribe({
      next: result => {
        this.notify.success(result.message || 'Equity bot resumed');
        this.loadEquityBotStatus();
      },
      error: () => this.notify.error('Failed to grant equity bot consent'),
    });
  }

  declineEquityConsent(): void {
    this.marketApi.botConsent(false).subscribe({
      next: result => {
        this.notify.success(result.message || 'Equity bot stopped');
        this.loadEquityBotStatus();
      },
      error: () => this.notify.error('Failed to decline equity bot consent'),
    });
  }

  grantOptionsConsent(): void {
    this.marketApi.optionsBotConsent(true).subscribe({
      next: result => {
        this.notify.success(result.message || 'Options bot resumed');
        this.loadOptionsBotStatus();
      },
      error: () => this.notify.error('Failed to grant options bot consent'),
    });
  }

  declineOptionsConsent(): void {
    this.marketApi.optionsBotConsent(false).subscribe({
      next: result => {
        this.notify.success(result.message || 'Options bot stopped');
        this.loadOptionsBotStatus();
      },
      error: () => this.notify.error('Failed to decline options bot consent'),
    });
  }

  asPercent(value: number | undefined | null): number {
    return (value || 0) * 100;
  }

  private parseWatchlist(value: string): string[] {
    return value
      .split(',')
      .map(symbol => symbol.trim().toUpperCase())
      .filter(symbol => !!symbol);
  }
}
