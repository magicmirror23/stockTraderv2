import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute } from '@angular/router';
import { PriceStreamService } from '../services/price-stream.service';
import { LiveStreamService, FeedStatus } from '../services/live-stream.service';
import { LivePriceChartComponent, PriceTick } from '../components/live-price-chart.component';
import { MarketApiService, MarketStatus } from '../services/market-api.service';
import { Subscription } from 'rxjs';

interface LastClose {
  symbol: string;
  timestamp: string;
  price: number;
  volume: number;
}

@Component({
  selector: 'app-live-chart',
  standalone: true,
  imports: [CommonModule, FormsModule, LivePriceChartComponent],
  template: `
    <div class="page">
      <div class="flex justify-between items-center" style="margin-bottom:1rem">
        <h1 style="margin:0">Live Price Chart</h1>
        <span class="feed-badge" [ngClass]="feedMode === 'live' ? 'feed-live' : 'feed-replay'">
          {{ feedMode === 'live' ? '● LIVE' : '○ REPLAY' }}
        </span>
      </div>

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
          </div>
        </div>
      </div>

      <div class="card mb-2" [attr.title]="sectionHelp.controls">
        <div class="form-row">
          <div class="form-group">
            <label>Symbol</label>
            <input [(ngModel)]="symbol" placeholder="RELIANCE" />
          </div>
          <div class="form-group" style="justify-content:flex-end; gap:0.5rem; display:flex">
            <button class="btn-primary" (click)="startStream()" [disabled]="streaming">
              {{ streaming ? 'Connected' : 'Connect' }}
            </button>
            <button class="btn-live" (click)="connectLive()" [disabled]="connectingLive || feedMode === 'live'">
              {{ connectingLive ? '...' : '⚡ Live' }}
            </button>
            <button class="btn-danger" (click)="stopStream()" *ngIf="streaming">Disconnect</button>
            <button class="btn-primary" (click)="loadLastClose()" [disabled]="loadingClose" *ngIf="!isMarketOpen && !streaming">
              {{ loadingClose ? 'Loading...' : 'Show Last Close' }}
            </button>
          </div>
        </div>
        <div *ngIf="streaming" class="flex items-center" style="gap:0.5rem; margin-top:0.5rem;">
          <span class="status-dot status-online"></span>
          <span class="text-sm">Streaming {{ symbol }} &mdash; {{ ticks.length }} ticks received</span>
        </div>
        <div *ngIf="!isMarketOpen && !streaming" class="market-closed-hint">
          <span>⚠ Market is closed. You can view the last closing price.</span>
        </div>
      </div>

      <!-- Last Close Card (shown when market closed) -->
      <div *ngIf="lastClose && !streaming" class="card mb-2 last-close-card" [attr.title]="sectionHelp.lastClose">
        <div class="flex justify-between items-center">
          <div>
            <h2 style="margin:0;">{{ lastClose.symbol }} — Last Close</h2>
            <div class="text-sm text-muted">{{ lastClose.timestamp | date:'medium' }}</div>
          </div>
          <div class="last-close-price">
            ₹{{ lastClose.price | number:'1.2-2' }}
          </div>
        </div>
        <div class="text-sm text-muted" style="margin-top:0.5rem;">
          Volume: {{ lastClose.volume | number }}
        </div>
      </div>

      <div class="card" [attr.title]="sectionHelp.chart">
        <app-live-price-chart [data]="ticks" />
        <div *ngIf="!streaming && ticks.length === 0 && !lastClose" style="text-align:center; padding:2rem;">
          <p class="text-muted" *ngIf="isMarketOpen">Enter a symbol and click Connect to start streaming live prices.</p>
          <p class="text-muted" *ngIf="!isMarketOpen">Market is closed. Click "Show Last Close" to see the most recent closing price.</p>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
    .status-online { background: var(--color-success); box-shadow: 0 0 4px var(--color-success); }
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
    .market-closed-hint {
      margin-top: 0.5rem; padding: 8px 12px; border-radius: var(--radius-md);
      background: rgba(220, 38, 38, 0.06); color: #dc2626; font-size: 0.85rem;
    }
    .last-close-card {
      border-left: 4px solid #f59e0b; background: rgba(245, 158, 11, 0.04);
    }
    .last-close-price {
      font-size: 2rem; font-weight: 700; color: var(--color-primary);
    }
    .feed-badge {
      padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 700;
      letter-spacing: 0.5px; text-transform: uppercase;
    }
    .feed-live {
      background: rgba(22,163,74,0.15); color: #16a34a; border: 1px solid #16a34a;
    }
    .feed-replay {
      background: rgba(245,158,11,0.12); color: #d97706; border: 1px solid #d97706;
    }
    .btn-live {
      padding: 8px 12px; border-radius: var(--radius-sm); border: 2px solid #16a34a;
      background: rgba(22,163,74,0.08); color: #16a34a; cursor: pointer;
      font-weight: 700; font-size: 0.8rem;
    }
    .btn-live:hover:not(:disabled) { background: #16a34a; color: #fff; }
    .btn-live:disabled { opacity: 0.5; cursor: not-allowed; }
  `]
})
export class LiveChartComponent implements OnInit, OnDestroy {
  readonly sectionHelp = {
    marketStatus: 'What: current market session state for this symbol. How: use it to decide whether to stream live ticks or inspect last-close data.',
    controls: 'What: single-symbol live chart controls. How: enter a symbol, connect the stream, or switch to last-close mode when the market is closed.',
    lastClose: 'What: most recent closing-price snapshot. How: use this when the market is closed and no live ticks are available.',
    chart: 'What: live or replay price chart for the selected symbol. How: connect the stream to watch incoming ticks build the chart in real time.',
  };
  symbol = 'RELIANCE';
  ticks: PriceTick[] = [];
  streaming = false;
  feedMode = 'replay';
  connectingLive = false;
  market: MarketStatus | null = null;
  lastClose: LastClose | null = null;
  loadingClose = false;
  private sub: Subscription | null = null;
  private marketTimer: any;

  get isMarketOpen(): boolean {
    if (!this.market) return false;
    return this.market.phase === 'open' || this.market.phase === 'pre_open';
  }

  constructor(
    private priceStream: PriceStreamService,
    private liveStream: LiveStreamService,
    private marketApi: MarketApiService,
    private http: HttpClient,
    private route: ActivatedRoute
  ) {}

  ngOnInit(): void {
    this.loadMarket();
    this.loadFeedStatus();
    this.marketTimer = setInterval(() => this.loadMarket(), 30_000);
    // Auto-connect if symbol is in URL (e.g. /chart/RELIANCE)
    const urlSymbol = this.route.snapshot.paramMap.get('symbol');
    if (urlSymbol) {
      this.symbol = urlSymbol.toUpperCase();
      setTimeout(() => this.startStream(), 500);
    }
  }

  loadFeedStatus(): void {
    this.liveStream.getFeedStatus().subscribe({
      next: s => this.feedMode = s.feed_mode || s.mode || 'replay',
      error: () => {}
    });
  }

  connectLive(): void {
    this.connectingLive = true;
    this.liveStream.connectLive([this.symbol.trim().toUpperCase()]).subscribe({
      next: res => {
        this.feedMode = res.feed_mode || res.mode || (res.connected ? 'live' : 'replay');
        this.connectingLive = false;
        if (res.mode !== 'unavailable') {
          this.startStream();
        }
      },
      error: () => { this.connectingLive = false; }
    });
  }

  loadMarket(): void {
    this.marketApi.getMarketStatus().subscribe({
      next: m => { this.market = m; },
      error: () => {}
    });
  }

  loadLastClose(): void {
    if (!this.symbol.trim()) return;
    this.loadingClose = true;
    this.http.get<LastClose>(`/api/v1/stream/last_close/${encodeURIComponent(this.symbol.trim())}`)
      .subscribe({
        next: data => {
          this.lastClose = data;
          this.loadingClose = false;
          // Show as single tick on the chart
          this.ticks = [{
            timestamp: data.timestamp,
            price: data.price,
            volume: data.volume
          }];
        },
        error: () => { this.loadingClose = false; }
      });
  }

  startStream(): void {
    this.stopStream();
    this.ticks = [];
    this.lastClose = null;
    this.streaming = true;
    this.sub = this.priceStream.connect(this.symbol).subscribe(tick => {
      this.ticks = [...this.ticks.slice(-500), tick];
    });
  }

  stopStream(): void {
    this.sub?.unsubscribe();
    this.sub = null;
    this.streaming = false;
  }

  ngOnDestroy(): void {
    this.stopStream();
    clearInterval(this.marketTimer);
  }
}
