import { Routes } from '@angular/router';
import { PaperDashboardComponent } from './pages/paper-dashboard.component';
import { PaperAccountDetailComponent } from './pages/paper-account-detail.component';
import { SignalExplorerComponent } from './pages/signal-explorer.component';
import { SignalDetailComponent } from './pages/signal-detail.component';
import { LiveChartComponent } from './pages/live-chart.component';
import { LiveMarketComponent } from './pages/live-market.component';
import { BacktestComponent } from './pages/backtest.component';
import { TradingComponent } from './pages/trading.component';
import { AdminComponent } from './pages/admin.component';
import { BotPanelComponent } from './pages/bot-panel.component';

export const routes: Routes = [
  { path: '', component: PaperDashboardComponent },
  { path: 'account/:accountId', component: PaperAccountDetailComponent },
  { path: 'signals', component: SignalExplorerComponent },
  { path: 'signal-detail', component: SignalDetailComponent },
  { path: 'live', component: LiveMarketComponent },
  { path: 'chart', component: LiveChartComponent },
  { path: 'chart/:symbol', component: LiveChartComponent },
  { path: 'backtest', component: BacktestComponent },
  { path: 'trading', component: TradingComponent },
  { path: 'bot', component: BotPanelComponent },
  { path: 'admin', component: AdminComponent },
  { path: '**', redirectTo: '' }
];
