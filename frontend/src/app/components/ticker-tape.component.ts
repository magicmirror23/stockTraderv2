import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { WatchlistItem } from '../services/live-stream.service';

@Component({
  selector: 'app-ticker-tape',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="ticker-wrap">
      <div class="ticker-track" [style.animationDuration]="(items.length * 3) + 's'">
        <ng-container *ngFor="let item of doubledItems">
          <span class="ticker-item" [ngClass]="{'up': (item.change_pct ?? 0) >= 0, 'down': (item.change_pct ?? 0) < 0}">
            <strong>{{ item.symbol }}</strong>
            ₹{{ item.price | number:'1.2-2' }}
            <span class="change">
              {{ (item.change_pct ?? 0) >= 0 ? '▲' : '▼' }}
              {{ item.change_pct | number:'1.2-2' }}%
            </span>
          </span>
        </ng-container>
      </div>
    </div>
  `,
  styles: [`
    .ticker-wrap {
      overflow: hidden;
      background: var(--color-surface);
      border-bottom: 1px solid var(--color-border);
      padding: 8px 0;
      white-space: nowrap;
    }
    .ticker-track {
      display: inline-flex;
      animation: scroll linear infinite;
    }
    @keyframes scroll {
      0%   { transform: translateX(0); }
      100% { transform: translateX(-50%); }
    }
    .ticker-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 20px;
      font-size: 0.85rem;
      border-right: 1px solid var(--color-border);
    }
    .ticker-item strong {
      color: var(--color-text);
      font-weight: 600;
    }
    .ticker-item.up { color: #16a34a; }
    .ticker-item.down { color: #dc2626; }
    .change { font-weight: 600; font-size: 0.8rem; }
  `]
})
export class TickerTapeComponent {
  @Input() items: WatchlistItem[] = [];

  get doubledItems(): WatchlistItem[] {
    // Duplicate for seamless infinite scroll
    return [...this.items, ...this.items];
  }
}
