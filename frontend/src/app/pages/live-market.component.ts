import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { Subscription } from 'rxjs';
import { LiveStreamService, LiveTick, WatchlistItem, MarketOverview, CategoryInfo, FeedStatus } from '../services/live-stream.service';
import { MarketApiService, MarketStatus } from '../services/market-api.service';
import { TickerTapeComponent } from '../components/ticker-tape.component';
import { SparklineComponent } from '../components/sparkline.component';
import { LivePriceChartComponent, PriceTick } from '../components/live-price-chart.component';

@Component({
  selector: 'app-live-market',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TickerTapeComponent, SparklineComponent, LivePriceChartComponent],
  template: `
    <!-- Ticker Tape -->
    <app-ticker-tape [items]="watchlistArray"></app-ticker-tape>

    <div class="page">
      <div class="page-header">
        <h1>Live Market Stream</h1>
        <div class="flex items-center gap-1">
          <span class="feed-badge" [ngClass]="feedMode === 'live' ? 'feed-live' : 'feed-replay'">
            {{ feedMode === 'live' ? '● LIVE' : '○ REPLAY' }}
          </span>
          <span class="conn-dot" [ngClass]="connected ? 'dot-on' : 'dot-off'"></span>
          <span class="text-sm">{{ connected ? 'Streaming' : 'Disconnected' }}</span>
          <span class="text-sm text-muted" *ngIf="connected"> &mdash; {{ tickCount | number }} ticks</span>
          <span class="text-sm text-muted"> &middot; {{ totalSymbols }} symbols</span>
        </div>
      </div>

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

      <!-- ── Indices Cards ───────────────────────────────────────── -->
      <div class="indices-row mb-2">
        <div *ngFor="let idx of indicesData" class="index-card card"
             (click)="selectSymbol(idx.symbol)"
             [ngClass]="{'idx-selected': selectedSymbol === idx.symbol}">
          <div class="idx-name">{{ indexDisplayName(idx.symbol) }}</div>
          <div class="idx-price" [ngClass]="(idx.change_pct ?? 0) >= 0 ? 'up' : 'down'">
            {{ idx.price | number:'1.2-2' }}
          </div>
          <div class="idx-change" [ngClass]="(idx.change_pct ?? 0) >= 0 ? 'up' : 'down'">
            {{ (idx.change_pct ?? 0) >= 0 ? '▲' : '▼' }}
            {{ idx.change | number:'1.2-2' }}
            ({{ idx.change_pct | number:'1.2-2' }}%)
          </div>
        </div>
        <div *ngIf="indicesData.length === 0" class="index-card card idx-placeholder">
          <div class="text-muted text-sm">Loading indices...</div>
        </div>
      </div>

      <!-- ── Category Tabs ───────────────────────────────────────── -->
      <div class="card mb-2 category-bar">
        <div class="cat-chips">
          <button class="cat-chip" [ngClass]="{'cat-active': activeCategory === 'All'}"
                  (click)="filterCategory('All')">All ({{ totalSymbols }})</button>
          <button *ngFor="let cat of categoryNames" class="cat-chip"
                  [ngClass]="{'cat-active': activeCategory === cat}"
                  (click)="filterCategory(cat)">
            {{ cat }} ({{ categorySymbolCounts[cat] || 0 }})
          </button>
        </div>
      </div>

      <!-- Controls -->
      <div class="card mb-2">
        <div class="form-row">
          <div class="form-group" style="flex:2">
            <label>Symbols (comma-separated)</label>
            <input [(ngModel)]="symbolInput" [placeholder]="placeholderSymbols" style="width:100%" />
          </div>
          <div class="form-group" style="justify-content:flex-end; gap:0.5rem; display:flex; align-items:flex-end; flex-wrap:wrap">
            <button class="btn-live" (click)="connectLiveFeed()" [disabled]="connectingLive || feedMode === 'live'">
              {{ connectingLive ? 'Connecting...' : (feedMode === 'live' ? '● AngelOne Live' : '⚡ Connect AngelOne') }}
            </button>
            <button class="btn-replay" (click)="disconnectLiveFeed()" *ngIf="feedMode === 'live'">Switch to Replay</button>
            <button class="btn-primary" (click)="startStream()" [disabled]="connected">
              {{ connected ? '● Streaming' : '▶ Start Stream' }}
            </button>
            <button class="btn-danger" (click)="stopStream()" *ngIf="connected">■ Stop</button>
            <button class="btn-secondary" (click)="loadSnapshot()" [disabled]="connected">Snapshot</button>
            <button class="btn-secondary" (click)="streamAllSymbols()" [disabled]="connected"
                    title="Stream all available symbols">All Stocks</button>
          </div>
        </div>
      </div>

      <!-- Main Grid -->
      <div class="grid-layout">

        <!-- Watchlist Table -->
        <div class="card grid-watchlist">
          <h2 style="margin-top:0">Live Watchlist</h2>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Price</th>
                  <th>Change</th>
                  <th>%</th>
                  <th>Bid</th>
                  <th>Ask</th>
                  <th>Volume</th>
                  <th>Trend</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr *ngFor="let item of watchlistArray" [ngClass]="{'row-selected': selectedSymbol === item.symbol}"
                    (click)="selectSymbol(item.symbol)">
                  <td><strong>{{ item.symbol }}</strong></td>
                  <td class="price-cell" [ngClass]="(item.change ?? 0) >= 0 ? 'up' : 'down'">
                    ₹{{ item.price | number:'1.2-2' }}
                  </td>
                  <td [ngClass]="(item.change ?? 0) >= 0 ? 'up' : 'down'">
                    {{ (item.change ?? 0) >= 0 ? '+' : '' }}{{ item.change | number:'1.2-2' }}
                  </td>
                  <td [ngClass]="(item.change_pct ?? 0) >= 0 ? 'up' : 'down'">
                    {{ (item.change_pct ?? 0) >= 0 ? '▲' : '▼' }}
                    {{ item.change_pct | number:'1.2-2' }}%
                  </td>
                  <td class="text-muted">{{ item.bid | number:'1.2-2' }}</td>
                  <td class="text-muted">{{ item.ask | number:'1.2-2' }}</td>
                  <td>{{ item.volume | number }}</td>
                  <td>
                    <app-sparkline [data]="item.sparkline"
                      [color]="(item.change_pct ?? 0) >= 0 ? '#16a34a' : '#dc2626'"
                      [width]="80" [height]="24"></app-sparkline>
                  </td>
                  <td>
                    <button class="btn-sm" (click)="selectSymbol(item.symbol); $event.stopPropagation()">Chart</button>
                  </td>
                </tr>
                <tr *ngIf="watchlistArray.length === 0">
                  <td colspan="9" class="text-center text-muted" style="padding:2rem">
                    Start streaming or load a snapshot to see live prices
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Selected Symbol Chart -->
        <div class="card grid-chart">
          <div class="flex justify-between items-center" style="margin-bottom:0.5rem">
            <h2 style="margin:0">{{ selectedSymbol || 'Select a symbol' }}</h2>
            <div *ngIf="selectedTick" class="selected-price" [ngClass]="(selectedTick.change ?? 0) >= 0 ? 'up' : 'down'">
              ₹{{ selectedTick.price | number:'1.2-2' }}
              <span class="text-sm">
                {{ (selectedTick.change_pct ?? 0) >= 0 ? '▲' : '▼' }}{{ selectedTick.change_pct | number:'1.2-2' }}%
              </span>
            </div>
          </div>
          <app-live-price-chart [data]="selectedChartData"></app-live-price-chart>
          <div *ngIf="selectedChartData.length === 0" style="text-align:center; padding:3rem 0">
            <p class="text-muted">Click a symbol in the watchlist to see its live chart</p>
          </div>
        </div>

        <!-- Market Overview: Gainers -->
        <div class="card grid-gainers">
          <h3 class="panel-title gainer-title">▲ Top Gainers</h3>
          <div *ngFor="let g of overview?.gainers || []" class="overview-row">
            <span class="ov-sym" (click)="selectSymbol(g.symbol)">{{ g.symbol }}</span>
            <span class="up">₹{{ g.price | number:'1.2-2' }}</span>
            <span class="up badge-up">+{{ g.change_pct | number:'1.2-2' }}%</span>
          </div>
          <div *ngIf="!overview?.gainers?.length" class="text-muted text-sm" style="padding:1rem 0; text-align:center">
            No data yet
          </div>
        </div>

        <!-- Market Overview: Losers -->
        <div class="card grid-losers">
          <h3 class="panel-title loser-title">▼ Top Losers</h3>
          <div *ngFor="let l of overview?.losers || []" class="overview-row">
            <span class="ov-sym" (click)="selectSymbol(l.symbol)">{{ l.symbol }}</span>
            <span class="down">₹{{ l.price | number:'1.2-2' }}</span>
            <span class="down badge-down">{{ l.change_pct | number:'1.2-2' }}%</span>
          </div>
          <div *ngIf="!overview?.losers?.length" class="text-muted text-sm" style="padding:1rem 0; text-align:center">
            No data yet
          </div>
        </div>

        <!-- Volume Leaders -->
        <div class="card grid-volume">
          <h3 class="panel-title">ðŸ“Š Volume Leaders</h3>
          <div *ngFor="let v of overview?.volume_leaders || []" class="overview-row">
            <span class="ov-sym" (click)="selectSymbol(v.symbol)">{{ v.symbol }}</span>
            <span>{{ v.volume | number }}</span>
            <span [ngClass]="(v.change_pct ?? 0) >= 0 ? 'up' : 'down'">
              {{ (v.change_pct ?? 0) >= 0 ? '▲' : '▼' }}{{ v.change_pct | number:'1.2-2' }}%
            </span>
          </div>
        </div>

        <!-- Live Trade Feed -->
        <div class="card grid-feed">
          <h3 class="panel-title">⚡ Live Trade Feed</h3>
          <div class="feed-scroll">
            <div *ngFor="let f of tradeFeed" class="feed-item" [ngClass]="(f.change_pct ?? 0) >= 0 ? 'feed-up' : 'feed-down'">
              <span class="feed-time">{{ f.timestamp | date:'HH:mm:ss' }}</span>
              <strong>{{ f.symbol }}</strong>
              <span>₹{{ f.price | number:'1.2-2' }}</span>
              <span class="feed-vol">Vol: {{ f.volume | number }}</span>
            </div>
            <div *ngIf="tradeFeed.length === 0" class="text-muted text-sm" style="padding:1rem; text-align:center">
              Trade feed appears when streaming starts
            </div>
          </div>
        </div>

        <!-- OHLC Panel for selected symbol -->
        <div class="card grid-ohlc" *ngIf="selectedTick">
          <h3 class="panel-title">ðŸ“‹ {{ selectedSymbol }} Details</h3>
          <div class="ohlc-grid">
            <div class="ohlc-item">
              <span class="ohlc-label">Open</span>
              <span class="ohlc-value">₹{{ selectedTick.open | number:'1.2-2' }}</span>
            </div>
            <div class="ohlc-item">
              <span class="ohlc-label">High</span>
              <span class="ohlc-value up">₹{{ selectedTick.high | number:'1.2-2' }}</span>
            </div>
            <div class="ohlc-item">
              <span class="ohlc-label">Low</span>
              <span class="ohlc-value down">₹{{ selectedTick.low | number:'1.2-2' }}</span>
            </div>
            <div class="ohlc-item">
              <span class="ohlc-label">Close</span>
              <span class="ohlc-value">₹{{ selectedTick.close | number:'1.2-2' }}</span>
            </div>
            <div class="ohlc-item">
              <span class="ohlc-label">Prev Close</span>
              <span class="ohlc-value">₹{{ selectedTick.prev_close | number:'1.2-2' }}</span>
            </div>
            <div class="ohlc-item">
              <span class="ohlc-label">Bid</span>
              <span class="ohlc-value">₹{{ selectedTick.bid | number:'1.2-2' }}</span>
            </div>
            <div class="ohlc-item">
              <span class="ohlc-label">Ask</span>
              <span class="ohlc-value">₹{{ selectedTick.ask | number:'1.2-2' }}</span>
            </div>
            <div class="ohlc-item">
              <span class="ohlc-label">Volume</span>
              <span class="ohlc-value">{{ selectedTick.volume | number }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .page-header {
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 1rem;
    }
    .page-header h1 { margin: 0; }
    .conn-dot {
      width: 10px; height: 10px; border-radius: 50%; display: inline-block;
    }
    .dot-on { background: #16a34a; box-shadow: 0 0 6px rgba(22,163,74,0.6); animation: pulse 1.5s infinite; }
    .dot-off { background: #9ca3af; }
    @keyframes pulse {
      0%, 100% { box-shadow: 0 0 4px rgba(22,163,74,0.4); }
      50% { box-shadow: 0 0 12px rgba(22,163,74,0.8); }
    }

    .market-banner { border-left: 4px solid var(--color-border); }
    .market-open { border-left-color: #16a34a; background: rgba(22,163,74,0.04); }
    .market-pre_open { border-left-color: #f59e0b; background: rgba(245,158,11,0.04); }
    .market-closed, .market-holiday, .market-weekend, .market-post_close {
      border-left-color: #dc2626; background: rgba(220,38,38,0.04);
    }
    .market-dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
    .dot-open { background: #16a34a; box-shadow: 0 0 8px rgba(22,163,74,0.5); }
    .dot-pre { background: #f59e0b; }
    .dot-closed { background: #dc2626; }

    .grid-layout {
      display: grid;
      grid-template-columns: 1fr 1fr;
      grid-template-areas:
        "watchlist watchlist"
        "chart chart"
        "gainers losers"
        "volume feed"
        "ohlc ohlc";
      gap: 1rem;
    }
    @media (min-width: 1200px) {
      .grid-layout {
        grid-template-columns: 2fr 1fr;
        grid-template-areas:
          "watchlist gainers"
          "watchlist losers"
          "chart volume"
          "chart feed"
          "ohlc ohlc";
      }
    }
    .grid-watchlist { grid-area: watchlist; }
    .grid-chart { grid-area: chart; }
    .grid-gainers { grid-area: gainers; }
    .grid-losers { grid-area: losers; }
    .grid-volume { grid-area: volume; }
    .grid-feed { grid-area: feed; }
    .grid-ohlc { grid-area: ohlc; }

    /* Watchlist Table */
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
    thead th {
      text-align: left; padding: 8px 10px; border-bottom: 2px solid var(--color-border);
      font-weight: 600; color: var(--color-text-secondary); white-space: nowrap;
    }
    tbody td {
      padding: 8px 10px; border-bottom: 1px solid var(--color-border);
      white-space: nowrap; transition: background 0.15s;
    }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: var(--color-bg); }
    .row-selected { background: var(--color-primary-light) !important; }
    .price-cell { font-weight: 700; font-size: 0.95rem; }
    .up { color: #16a34a; }
    .down { color: #dc2626; }
    .btn-sm {
      padding: 2px 8px; font-size: 0.75rem; border-radius: 4px;
      border: 1px solid var(--color-border); background: var(--color-bg);
      cursor: pointer; color: var(--color-text-secondary);
    }
    .btn-sm:hover { background: var(--color-primary-light); color: var(--color-primary); }
    .btn-secondary {
      padding: 8px 16px; border-radius: var(--radius-sm); border: 1px solid var(--color-border);
      background: var(--color-surface); cursor: pointer; font-weight: 500;
    }
    .btn-secondary:hover { background: var(--color-bg); }

    .selected-price { font-size: 1.5rem; font-weight: 700; }

    /* Overview panels */
    .panel-title { margin: 0 0 0.75rem 0; font-size: 0.95rem; }
    .gainer-title { color: #16a34a; }
    .loser-title { color: #dc2626; }
    .overview-row {
      display: flex; justify-content: space-between; align-items: center;
      padding: 6px 0; border-bottom: 1px solid var(--color-border); font-size: 0.85rem;
    }
    .overview-row:last-child { border-bottom: none; }
    .ov-sym { font-weight: 600; cursor: pointer; }
    .ov-sym:hover { color: var(--color-primary); text-decoration: underline; }
    .badge-up {
      background: rgba(22,163,74,0.1); padding: 2px 6px; border-radius: 4px; font-weight: 600;
    }
    .badge-down {
      background: rgba(220,38,38,0.1); padding: 2px 6px; border-radius: 4px; font-weight: 600;
    }

    /* Trade Feed */
    .feed-scroll { max-height: 200px; overflow-y: auto; }
    .feed-item {
      display: flex; gap: 8px; align-items: center; padding: 4px 0;
      border-bottom: 1px solid var(--color-border); font-size: 0.8rem;
      animation: fadeIn 0.3s ease;
    }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
    .feed-up { border-left: 3px solid #16a34a; padding-left: 6px; }
    .feed-down { border-left: 3px solid #dc2626; padding-left: 6px; }
    .feed-time { color: var(--color-text-secondary); font-family: monospace; }
    .feed-vol { color: var(--color-text-secondary); }

    /* OHLC Details */
    .ohlc-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 12px;
    }
    .ohlc-item {
      display: flex; flex-direction: column; padding: 8px 12px;
      background: var(--color-bg); border-radius: var(--radius-sm);
    }
    .ohlc-label { font-size: 0.75rem; color: var(--color-text-secondary); text-transform: uppercase; }
    .ohlc-value { font-size: 1.1rem; font-weight: 600; margin-top: 2px; }

    /* ── Indices Row ────────────────────────────── */
    .indices-row {
      display: flex; gap: 1rem; flex-wrap: wrap;
    }
    .index-card {
      flex: 1 1 180px; min-width: 160px; text-align: center;
      cursor: pointer; transition: box-shadow 0.2s, border-color 0.2s;
      border: 2px solid transparent;
    }
    .index-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
    .idx-selected { border-color: var(--color-primary) !important; }
    .idx-name { font-size: 0.8rem; font-weight: 700; letter-spacing: 0.5px; color: var(--color-text-secondary); margin-bottom: 4px; text-transform: uppercase; }
    .idx-price { font-size: 1.35rem; font-weight: 700; }
    .idx-change { font-size: 0.85rem; font-weight: 600; margin-top: 2px; }
    .idx-placeholder { display: flex; align-items: center; justify-content: center; min-height: 80px; }

    /* ── Category Tabs ─────────────────────────── */
    .category-bar { padding: 0.5rem 1rem; }
    .cat-chips { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .cat-chip {
      padding: 4px 14px; border-radius: 20px; font-size: 0.8rem; font-weight: 500;
      border: 1px solid var(--color-border); background: var(--color-surface);
      cursor: pointer; white-space: nowrap; transition: all 0.15s;
    }
    .cat-chip:hover { background: var(--color-bg); border-color: var(--color-primary); }
    .cat-active {
      background: var(--color-primary) !important; color: #fff !important;
      border-color: var(--color-primary) !important;
    }

    /* Feed mode badge */
    .feed-badge {
      padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 700;
      letter-spacing: 0.5px; text-transform: uppercase;
    }
    .feed-live {
      background: rgba(22,163,74,0.15); color: #16a34a; border: 1px solid #16a34a;
      animation: pulse 1.5s infinite;
    }
    .feed-replay {
      background: rgba(245,158,11,0.12); color: #d97706; border: 1px solid #d97706;
    }
    .btn-live {
      padding: 8px 16px; border-radius: var(--radius-sm); border: 2px solid #16a34a;
      background: rgba(22,163,74,0.08); color: #16a34a; cursor: pointer;
      font-weight: 700; font-size: 0.85rem; transition: all 0.2s;
    }
    .btn-live:hover:not(:disabled) { background: #16a34a; color: #fff; }
    .btn-live:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-replay {
      padding: 8px 16px; border-radius: var(--radius-sm); border: 1px solid #d97706;
      background: rgba(245,158,11,0.08); color: #d97706; cursor: pointer;
      font-weight: 500; font-size: 0.85rem;
    }
    .btn-replay:hover { background: #d97706; color: #fff; }
  `]
})
export class LiveMarketComponent implements OnInit, OnDestroy {
  private readonly defaultStreamSymbols = [
    'RELIANCE',
    'TCS',
    'HDFCBANK',
    'INFY',
    'ICICIBANK',
    'SBIN',
    'BHARTIARTL',
    'LT',
    'AXISBANK',
    'ITC',
    'BAJFINANCE',
    'MARUTI',
    'SUNPHARMA',
    'TATAMOTORS',
    'ADANIPORTS',
    'TATASTEEL',
    'ADANIENT',
    'HAL',
    'INDIGO',
    'TATAPOWER',
  ];
  symbolInput = this.defaultStreamSymbols.join(',');
  placeholderSymbols = this.defaultStreamSymbols.join(',');
  connected = false;
  tickCount = 0;
  feedMode = 'replay';
  connectingLive = false;
  market: MarketStatus | null = null;
  selectedSymbol = '';
  selectedChartData: PriceTick[] = [];
  selectedTick: LiveTick | null = null;
  overview: MarketOverview | null = null;
  tradeFeed: LiveTick[] = [];
  watchlistArray: WatchlistItem[] = [];

  // Indices & Category data
  indicesData: LiveTick[] = [];
  categoryNames: string[] = [];
  categorySymbolCounts: { [key: string]: number } = {};
  activeCategory = 'All';
  totalSymbols = 0;
  private allCategorySymbols: { [key: string]: string[] } = {};
  private allSymbolsList: string[] = [];

  private subs: Subscription[] = [];
  private marketTimer: any;
  private overviewTimer: any;
  private chartDataMap = new Map<string, PriceTick[]>();
  private readonly coreIndices = ['NIFTY50', 'BANKNIFTY', 'SENSEX'];

  constructor(
    private liveStream: LiveStreamService,
    private marketApi: MarketApiService,
  ) {}

  ngOnInit(): void {
    this.loadMarket();
    this.loadOverview();
    this.loadCategories();
    this.loadFeedStatus();
    this.marketTimer = setInterval(() => this.loadMarket(), 30_000);
    this.overviewTimer = setInterval(() => this.loadOverview(), 15_000);

    this.subs.push(
      this.liveStream.connected$.subscribe(c => this.connected = c),
      this.liveStream.watchlist$.subscribe(map => {
        this.watchlistArray = Array.from(map.values());
      }),
      this.liveStream.tick$.subscribe(tick => {
        this.tickCount++;
        // Track feed mode from incoming ticks
        if (tick.feed_mode) this.feedMode = tick.feed_mode;
        if (this.coreIndices.includes(tick.symbol)) {
          const nextIndices = this.indicesData.filter(item => item.symbol !== tick.symbol);
          this.indicesData = [...nextIndices, tick].sort(
            (a, b) => this.coreIndices.indexOf(a.symbol) - this.coreIndices.indexOf(b.symbol)
          );
        }
        // Update trade feed (newest first, max 50)
        this.tradeFeed = [tick, ...this.tradeFeed.slice(0, 49)];
        // Update per-symbol chart data
        const arr = this.chartDataMap.get(tick.symbol) || [];
        arr.push({ timestamp: tick.timestamp, price: tick.price, volume: tick.volume });
        if (arr.length > 500) arr.shift();
        this.chartDataMap.set(tick.symbol, arr);
        // Update selected chart
        if (tick.symbol === this.selectedSymbol) {
          this.selectedChartData = [...arr];
          this.selectedTick = tick;
        }
        // Periodically refresh overview from live data
        if (this.tickCount % 20 === 0) {
          this.refreshOverviewFromLive();
        }
      }),
    );

    // Auto-load snapshot on init
    this.loadSnapshot();
  }

  loadMarket(): void {
    this.marketApi.getMarketStatus().subscribe({
      next: m => this.market = m,
      error: () => {}
    });
  }

  loadOverview(): void {
    this.liveStream.getMarketOverview().subscribe({
      next: o => {
        this.overview = o;
        if (o.indices && o.indices.length > 0) {
          this.indicesData = o.indices;
        }
      },
      error: () => {}
    });
  }

  refreshOverviewFromLive(): void {
    const items = this.watchlistArray;
    if (items.length === 0) return;
    const sorted = [...items].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));
    const indices = items.filter(i => ['NIFTY50', 'BANKNIFTY', 'SENSEX'].includes(i.symbol));
    if (indices.length > 0) this.indicesData = indices as any;
    this.overview = {
      gainers: sorted.filter(s => (s.change_pct ?? 0) > 0).slice(0, 10),
      losers: sorted.filter(s => (s.change_pct ?? 0) < 0).reverse().slice(0, 10),
      volume_leaders: [...items].sort((a, b) => b.volume - a.volume).slice(0, 10),
      total_symbols: items.length,
      indices: indices as any,
      categories: {},
    };
  }

  startStream(): void {
    const symbols = this.requestedSymbols();
    if (symbols.length === 0) return;
    this.tickCount = 0;
    this.tradeFeed = [];
    this.chartDataMap.clear();
    this.liveStream.connectMulti(symbols);
    if (!this.selectedSymbol && symbols.length > 0) {
      this.selectedSymbol = symbols[0];
    }
  }

  stopStream(): void {
    this.liveStream.disconnect();
  }

  loadSnapshot(): void {
    const symbols = this.requestedSymbols();
    this.liveStream.getWatchlistSnapshot(symbols.length ? symbols : undefined).subscribe({
      next: res => {
        const map = new Map<string, WatchlistItem>();
        for (const item of res.data) {
          map.set(item.symbol, { ...item, sparkline: [item.price] });
        }
        this.liveStream.watchlist$.next(map);
        if (!this.selectedSymbol && res.data.length > 0) {
          this.selectSymbol(res.data[0].symbol);
        }
        // Build overview from snapshot
        if (res.data.length > 0) {
          const sorted = [...res.data].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));
          const indices = res.data.filter((s: any) => ['NIFTY50', 'BANKNIFTY', 'SENSEX'].includes(s.symbol));
          if (indices.length > 0) this.indicesData = indices as any;
          this.overview = {
            gainers: sorted.filter(s => (s.change_pct ?? 0) > 0).slice(0, 10),
            losers: sorted.filter(s => (s.change_pct ?? 0) < 0).reverse().slice(0, 10),
            volume_leaders: [...res.data].sort((a, b) => b.volume - a.volume).slice(0, 10),
            total_symbols: res.data.length,
            indices: indices as any,
            categories: {},
          };
        }
      },
      error: () => {}
    });
  }

  selectSymbol(symbol: string): void {
    this.selectedSymbol = symbol;
    this.selectedChartData = this.chartDataMap.get(symbol) || [];
    const wl = this.liveStream.watchlist$.value.get(symbol);
    this.selectedTick = wl || null;
  }

  loadCategories(): void {
    this.liveStream.getCategories().subscribe({
      next: (cats: CategoryInfo) => {
        this.categoryNames = Object.keys(cats);
        this.allCategorySymbols = {};
        this.allSymbolsList = [];
        let total = 0;
        for (const catName of this.categoryNames) {
          const syms = cats[catName].map((s: { symbol: string }) => s.symbol);
          this.allCategorySymbols[catName] = syms;
          this.categorySymbolCounts[catName] = syms.length;
          total += syms.length;
          this.allSymbolsList.push(...syms);
        }
        // Deduplicate
        this.allSymbolsList = [...new Set(this.allSymbolsList)];
        this.totalSymbols = this.allSymbolsList.length;
      },
      error: () => {}
    });
  }

  filterCategory(cat: string): void {
    this.activeCategory = cat;
    if (cat === 'All') {
      this.symbolInput = this.allSymbolsList.slice(0, 20).join(',');
    } else {
      const syms = this.allCategorySymbols[cat] || [];
      this.symbolInput = syms.join(',');
    }
  }

  streamAllSymbols(): void {
    this.symbolInput = this.allSymbolsList.join(',');
    this.startStream();
  }

  indexDisplayName(symbol: string): string {
    const map: { [k: string]: string } = {
      'NIFTY50': 'NIFTY 50',
      'BANKNIFTY': 'BANK NIFTY',
      'SENSEX': 'SENSEX',
    };
    return map[symbol] || symbol;
  }

  // ── Live Feed Controls ──────────────────────────────────────────────

  loadFeedStatus(): void {
    this.liveStream.getFeedStatus().subscribe({
      next: s => this.feedMode = s.feed_mode || s.mode || 'replay',
      error: () => {}
    });
  }

  connectLiveFeed(): void {
    this.connectingLive = true;
    const symbols = this.requestedSymbols();
    this.liveStream.connectLive(symbols.length ? symbols : undefined).subscribe({
      next: res => {
        this.feedMode = res.feed_mode || res.mode || (res.connected ? 'live' : 'replay');
        this.connectingLive = false;
        if (res.connected) {
          this.startStream();
        }
      },
      error: () => { this.connectingLive = false; }
    });
  }

  disconnectLiveFeed(): void {
    this.liveStream.disconnectLive().subscribe({
      next: res => { this.feedMode = res.feed_mode || 'replay'; },
      error: () => {}
    });
  }

  private requestedSymbols(): string[] {
    const requested = this.symbolInput.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
    return [...new Set([...this.coreIndices, ...requested])];
  }

  ngOnDestroy(): void {
    this.liveStream.disconnect();
    this.subs.forEach(s => s.unsubscribe());
    clearInterval(this.marketTimer);
    clearInterval(this.overviewTimer);
  }
}
