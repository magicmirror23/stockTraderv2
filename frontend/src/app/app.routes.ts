import { Routes } from '@angular/router';

const loadPaperDashboard = () =>
  import('./pages/paper-dashboard.component').then((m) => m.PaperDashboardComponent);

const loadPaperAccountDetail = () =>
  import('./pages/paper-account-detail.component').then((m) => m.PaperAccountDetailComponent);

const loadSignalExplorer = () =>
  import('./pages/signal-explorer.component').then((m) => m.SignalExplorerComponent);

const loadSignalDetail = () =>
  import('./pages/signal-detail.component').then((m) => m.SignalDetailComponent);

const loadLiveChart = () =>
  import('./pages/live-chart.component').then((m) => m.LiveChartComponent);

const loadLiveMarket = () =>
  import('./pages/live-market.component').then((m) => m.LiveMarketComponent);

const loadBacktest = () =>
  import('./pages/backtest.component').then((m) => m.BacktestComponent);

const loadTrading = () =>
  import('./pages/trading.component').then((m) => m.TradingComponent);

const loadAdmin = () =>
  import('./pages/admin.component').then((m) => m.AdminComponent);

const loadBotPanel = () =>
  import('./pages/bot-panel.component').then((m) => m.BotPanelComponent);

export const routes: Routes = [
  { path: '', loadComponent: loadPaperDashboard },
  { path: 'account/:accountId', loadComponent: loadPaperAccountDetail },
  { path: 'signals', loadComponent: loadSignalExplorer },
  { path: 'signal-detail', loadComponent: loadSignalDetail },
  { path: 'live', loadComponent: loadLiveMarket },
  { path: 'chart', loadComponent: loadLiveChart },
  { path: 'chart/:symbol', loadComponent: loadLiveChart },
  { path: 'backtest', loadComponent: loadBacktest },
  { path: 'trading', loadComponent: loadTrading },
  { path: 'bot', loadComponent: loadBotPanel },
  { path: 'admin', loadComponent: loadAdmin },
  { path: '**', redirectTo: '' },
];
