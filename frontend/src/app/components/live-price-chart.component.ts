import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface PriceTick {
  timestamp: string;
  price: number;
  volume: number;
}

@Component({
  selector: 'app-live-price-chart',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div *ngIf="data.length === 0"><p>Waiting for price data…</p></div>
    <div *ngIf="data.length > 0" class="chart-container">
      <!-- Current Price Badge -->
      <div class="current-price" [ngClass]="priceDirection">
        <span class="cp-label">Current</span>
        <span class="cp-value">₹{{ currentPrice | number:'1.2-2' }}</span>
        <span class="cp-change" *ngIf="priceChange !== 0">
          {{ priceChange >= 0 ? '▲' : '▼' }} {{ priceChangePct | number:'1.2-2' }}%
        </span>
      </div>

      <div class="chart-inner">
        <!-- Y-axis labels -->
        <div class="y-axis">
          <span *ngFor="let label of yLabels" class="y-label" [style.bottom.%]="label.pct">
            ₹{{ label.value | number:'1.0-0' }}
          </span>
        </div>

        <!-- SVG Chart Area -->
        <div class="svg-wrap">
          <svg [attr.viewBox]="viewBox" preserveAspectRatio="none" class="chart-svg">
            <!-- Grid lines -->
            <line *ngFor="let label of yLabels"
              [attr.x1]="0" [attr.y1]="label.svgY"
              [attr.x2]="chartW" [attr.y2]="label.svgY"
              stroke="#e5e7eb" stroke-width="0.5" stroke-dasharray="4,3"/>

            <!-- Area fill under line -->
            <polygon [attr.points]="areaPoints" [attr.fill]="areaFill" opacity="0.12"/>

            <!-- Price line -->
            <polyline [attr.points]="points" fill="none"
              [attr.stroke]="lineColor" stroke-width="1.8"
              stroke-linejoin="round" stroke-linecap="round"/>

            <!-- Current price horizontal line -->
            <line *ngIf="data.length > 1"
              [attr.x1]="0" [attr.y1]="currentPriceY"
              [attr.x2]="chartW" [attr.y2]="currentPriceY"
              [attr.stroke]="lineColor" stroke-width="0.8" stroke-dasharray="6,4" opacity="0.5"/>

            <!-- Last point dot -->
            <circle *ngIf="data.length > 1"
              [attr.cx]="lastPointX" [attr.cy]="lastPointY"
              r="3.5" [attr.fill]="lineColor" stroke="white" stroke-width="1.5"/>
          </svg>

          <!-- X-axis labels (overlaid at bottom) -->
          <div class="x-axis">
            <span *ngFor="let label of xLabels" class="x-label" [style.left.%]="label.pct">
              {{ label.text }}
            </span>
          </div>
        </div>
      </div>

      <!-- Price range info -->
      <div class="price-range">
        <span>Low: ₹{{ minPrice | number:'1.2-2' }}</span>
        <span>{{ data.length }} ticks</span>
        <span>High: ₹{{ maxPrice | number:'1.2-2' }}</span>
      </div>
    </div>
  `,
  styles: [`
    .chart-container { width: 100%; }

    .current-price {
      display: flex; align-items: center; gap: 0.75rem;
      padding: 6px 12px; margin-bottom: 8px;
      border-radius: 6px; font-size: 0.85rem;
    }
    .current-price.up { background: rgba(22,163,74,0.06); }
    .current-price.down { background: rgba(220,38,38,0.06); }
    .current-price.flat { background: rgba(100,116,139,0.06); }
    .cp-label { color: var(--color-text-secondary); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; }
    .cp-value { font-size: 1.3rem; font-weight: 700; }
    .cp-change { font-weight: 600; font-size: 0.85rem; }
    .up .cp-value, .up .cp-change { color: #16a34a; }
    .down .cp-value, .down .cp-change { color: #dc2626; }
    .flat .cp-value { color: var(--color-text); }

    .chart-inner { display: flex; gap: 0; }

    .y-axis {
      width: 60px; position: relative; flex-shrink: 0;
    }
    .y-label {
      position: absolute; right: 6px; transform: translateY(50%);
      font-size: 0.7rem; color: var(--color-text-secondary);
      white-space: nowrap;
    }

    .svg-wrap { flex: 1; position: relative; overflow: hidden; }

    .chart-svg {
      width: 100%; height: 280px; display: block;
      border-left: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb;
    }

    .x-axis {
      position: relative; height: 22px; width: 100%;
    }
    .x-label {
      position: absolute; transform: translateX(-50%);
      font-size: 0.65rem; color: var(--color-text-secondary);
      white-space: nowrap; top: 4px;
    }

    .price-range {
      display: flex; justify-content: space-between;
      font-size: 0.72rem; color: var(--color-text-secondary);
      padding: 4px 60px 0 60px;
    }
  `]
})
export class LivePriceChartComponent implements OnChanges {
  @Input() data: PriceTick[] = [];

  chartW = 800;
  chartH = 280;
  viewBox = '0 0 800 280';
  points = '';
  areaPoints = '';
  minPrice = 0;
  maxPrice = 0;
  currentPrice = 0;
  priceChange = 0;
  priceChangePct = 0;
  priceDirection = 'flat';
  lineColor = '#16a34a';
  areaFill = '#16a34a';
  currentPriceY = 0;
  lastPointX = 0;
  lastPointY = 0;
  yLabels: { value: number; pct: number; svgY: number }[] = [];
  xLabels: { text: string; pct: number }[] = [];

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['data'] && this.data.length > 0) {
      this.buildChart();
    }
  }

  private buildChart(): void {
    const prices = this.data.map(d => d.price);
    this.minPrice = Math.min(...prices);
    this.maxPrice = Math.max(...prices);

    // Add 2% padding to Y range
    const rawRange = this.maxPrice - this.minPrice || 1;
    const padding = rawRange * 0.04;
    const yMin = this.minPrice - padding;
    const yMax = this.maxPrice + padding;
    const range = yMax - yMin;

    // Current price info
    this.currentPrice = prices[prices.length - 1];
    const firstPrice = prices[0];
    this.priceChange = this.currentPrice - firstPrice;
    this.priceChangePct = firstPrice ? (this.priceChange / firstPrice) * 100 : 0;
    this.priceDirection = this.priceChange > 0.01 ? 'up' : this.priceChange < -0.01 ? 'down' : 'flat';
    this.lineColor = this.priceDirection === 'down' ? '#dc2626' : '#16a34a';
    this.areaFill = this.lineColor;

    // Build polyline points
    const pointPairs: string[] = [];
    const n = this.data.length;
    for (let i = 0; i < n; i++) {
      const x = n > 1 ? (i / (n - 1)) * this.chartW : this.chartW / 2;
      const y = this.chartH - ((prices[i] - yMin) / range) * this.chartH;
      pointPairs.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    }
    this.points = pointPairs.join(' ');

    // Area fill (polygon under the line)
    const lastX = n > 1 ? this.chartW : this.chartW / 2;
    this.areaPoints = `0,${this.chartH} ${pointPairs.join(' ')} ${lastX.toFixed(1)},${this.chartH}`;

    // Last point (for dot indicator)
    if (n > 1) {
      this.lastPointX = this.chartW;
      this.lastPointY = this.chartH - ((this.currentPrice - yMin) / range) * this.chartH;
      this.currentPriceY = this.lastPointY;
    }

    // Y-axis labels (5 labels)
    this.yLabels = [];
    const nLabels = 5;
    for (let i = 0; i <= nLabels; i++) {
      const value = this.minPrice + (rawRange * i) / nLabels;
      const pct = ((value - yMin) / range) * 100;
      const svgY = this.chartH - (pct / 100) * this.chartH;
      this.yLabels.push({ value, pct, svgY });
    }

    // X-axis labels (up to 6 time labels)
    this.xLabels = [];
    if (n > 1) {
      const nXLabels = Math.min(6, n);
      for (let i = 0; i < nXLabels; i++) {
        const idx = Math.round((i / (nXLabels - 1)) * (n - 1));
        const ts = this.data[idx].timestamp;
        const text = this.formatTime(ts);
        this.xLabels.push({ text, pct: (idx / (n - 1)) * 100 });
      }
    }
  }

  private formatTime(ts: string): string {
    try {
      const d = new Date(ts);
      const h = d.getHours();
      const m = d.getMinutes();
      if (h === 0 && m === 0) {
        // Daily data — show date
        return `${d.getDate()}/${d.getMonth() + 1}`;
      }
      return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
    } catch {
      return '';
    }
  }
}
