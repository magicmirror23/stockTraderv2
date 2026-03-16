import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { NotificationService, Toast } from './services/notification.service';
import { BackendStatusService, HealthInfo } from './services/backend-status.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterModule],
  template: `
    <!-- Status banner -->
    <div class="status-banner status-offline" *ngIf="!(backendOnline)">
      &#9888; Backend unavailable &mdash; some features may not work.
    </div>
    <div class="status-banner status-demo" *ngIf="backendOnline && healthInfo?.demo_mode">
      &#9881; Demo mode &mdash; prices are replayed from CSV data. Connect AngelOne credentials for live data.
    </div>

    <!-- Top Navigation -->
    <nav class="topnav">
      <div class="topnav-inner">
        <a routerLink="/" class="brand">
          <span class="brand-icon">&#9651;</span> StockTrader
        </a>
        <div class="nav-links">
          <a routerLink="/" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: true }">Dashboard</a>
          <a routerLink="/signals" routerLinkActive="active">Predictions</a>
          <a routerLink="/signal-detail" routerLinkActive="active">Options</a>
          <a routerLink="/live" routerLinkActive="active">Live Market</a>
          <a routerLink="/chart" routerLinkActive="active">Live Chart</a>
          <a routerLink="/backtest" routerLinkActive="active">Backtest</a>
          <a routerLink="/trading" routerLinkActive="active">Trading</a>
          <a routerLink="/bot" routerLinkActive="active">Bot</a>
          <a routerLink="/admin" routerLinkActive="active">Admin</a>
        </div>
        <button class="mobile-toggle" (click)="mobileOpen = !mobileOpen">&#9776;</button>
      </div>
      <div class="mobile-menu" *ngIf="mobileOpen" (click)="mobileOpen = false">
        <a routerLink="/" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: true }">Dashboard</a>
        <a routerLink="/signals" routerLinkActive="active">Predictions</a>
        <a routerLink="/signal-detail" routerLinkActive="active">Options</a>
        <a routerLink="/live" routerLinkActive="active">Live Market</a>
        <a routerLink="/chart" routerLinkActive="active">Live Chart</a>
        <a routerLink="/backtest" routerLinkActive="active">Backtest</a>
        <a routerLink="/trading" routerLinkActive="active">Trading</a>
        <a routerLink="/bot" routerLinkActive="active">Bot</a>
        <a routerLink="/admin" routerLinkActive="active">Admin</a>
      </div>
    </nav>

    <!-- Main content -->
    <main>
      <router-outlet />
    </main>

    <!-- Toast notifications -->
    <div class="toast-container">
      <div *ngFor="let t of toasts" class="toast" [ngClass]="'toast-' + t.type" (click)="notify.remove(t.id)">
        {{ t.message }}
      </div>
    </div>
  `,
  styles: [`
    .topnav {
      background: var(--color-surface);
      border-bottom: 1px solid var(--color-border);
      box-shadow: var(--shadow-sm);
      position: sticky;
      top: 0;
      z-index: 1000;
    }
    .topnav-inner {
      max-width: 1400px;
      margin: 0 auto;
      padding: 0 1.5rem;
      display: flex;
      align-items: center;
      height: 56px;
    }
    .brand {
      font-size: 1.15rem;
      font-weight: 700;
      color: var(--color-primary);
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 6px;
      margin-right: 2rem;
      white-space: nowrap;
    }
    .brand-icon { font-size: 1.3rem; }
    .nav-links {
      display: flex;
      gap: 4px;
    }
    .nav-links a {
      text-decoration: none;
      color: var(--color-text-secondary);
      font-size: 0.875rem;
      font-weight: 500;
      padding: 6px 14px;
      border-radius: var(--radius-sm);
      transition: all var(--transition);
    }
    .nav-links a:hover {
      background: var(--color-bg);
      color: var(--color-text);
    }
    .nav-links a.active {
      background: var(--color-primary-light);
      color: var(--color-primary);
      font-weight: 600;
    }
    .mobile-toggle {
      display: none;
      margin-left: auto;
      background: none;
      border: none;
      font-size: 1.5rem;
      cursor: pointer;
      color: var(--color-text);
    }
    .mobile-menu {
      display: none;
      flex-direction: column;
      padding: 0.5rem 1.5rem 1rem;
      border-top: 1px solid var(--color-border);
    }
    .mobile-menu a {
      text-decoration: none;
      color: var(--color-text-secondary);
      padding: 10px 14px;
      border-radius: var(--radius-sm);
      font-weight: 500;
    }
    .mobile-menu a.active {
      background: var(--color-primary-light);
      color: var(--color-primary);
    }
    main {
      min-height: calc(100vh - 56px);
    }
    .status-banner {
      padding: 8px 1.5rem;
      font-size: 0.85rem;
      font-weight: 500;
      text-align: center;
    }
    .status-offline {
      background: #fef2f2;
      color: #991b1b;
      border-bottom: 1px solid #fecaca;
    }
    .status-demo {
      background: #fefce8;
      color: #854d0e;
      border-bottom: 1px solid #fef08a;
    }
    @media (max-width: 840px) {
      .nav-links { display: none; }
      .mobile-toggle { display: block; }
      .mobile-menu { display: flex; }
    }
  `]
})
export class AppComponent {
  title = 'StockTrader';
  mobileOpen = false;
  toasts: Toast[] = [];
  backendOnline = true;
  healthInfo: HealthInfo | null = null;

  constructor(public notify: NotificationService, private backend: BackendStatusService) {
    this.notify.toasts$.subscribe(t => this.toasts = t);
    this.backend.online$.subscribe(v => this.backendOnline = v);
    this.backend.info$.subscribe(v => this.healthInfo = v);
  }
}
