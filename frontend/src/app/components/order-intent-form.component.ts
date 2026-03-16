import { Component, EventEmitter, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

export interface OrderIntentData {
  ticker: string;
  side: 'buy' | 'sell';
  quantity: number;
  order_type: 'market' | 'limit';
  limit_price?: number;
  option_type?: 'CE' | 'PE' | '';
  strike?: number;
  expiry?: string;
  strategy?: 'single' | 'vertical_spread' | 'iron_condor' | 'covered_call';
}

@Component({
  selector: 'app-order-intent-form',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="form-card">
      <h3>Order Intent</h3>
      <div class="grid">
        <label>Ticker <input [(ngModel)]="form.ticker" /></label>
        <label>Side
          <select [(ngModel)]="form.side">
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </label>
        <label>Quantity <input type="number" [(ngModel)]="form.quantity" /></label>
        <label>Order Type
          <select [(ngModel)]="form.order_type">
            <option value="market">Market</option>
            <option value="limit">Limit</option>
          </select>
        </label>
        <label>Strategy
          <select [(ngModel)]="form.strategy">
            <option value="single">Single Leg</option>
            <option value="vertical_spread">Vertical Spread</option>
            <option value="iron_condor">Iron Condor</option>
            <option value="covered_call">Covered Call</option>
          </select>
        </label>
        <label>Option Type
          <select [(ngModel)]="form.option_type">
            <option value="">Equity</option>
            <option value="CE">CE</option>
            <option value="PE">PE</option>
          </select>
        </label>
        <label>Strike <input type="number" [(ngModel)]="form.strike" /></label>
        <label>Expiry <input type="date" [(ngModel)]="form.expiry" /></label>
      </div>
      <button (click)="submit()">Submit Intent</button>
    </div>
  `,
  styles: [`
    .form-card { border: 1px solid #ddd; padding: 1rem; border-radius: 8px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin-bottom: 0.5rem; }
    label { display: flex; flex-direction: column; gap: 2px; }
    input, select { padding: 4px; }
  `]
})
export class OrderIntentFormComponent {
  @Output() intentSubmit = new EventEmitter<OrderIntentData>();

  form: OrderIntentData = {
    ticker: '',
    side: 'buy',
    quantity: 1,
    order_type: 'market',
    strategy: 'single',
    option_type: '',
  };

  submit(): void {
    this.intentSubmit.emit({ ...this.form });
  }
}
