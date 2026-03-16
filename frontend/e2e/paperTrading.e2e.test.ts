/**
 * E2E test: Create a paper account → run one-day replay → verify equity chart data.
 *
 * This test runs against the backend API (expects the server at localhost:8000).
 * Execute with: npx jest e2e/paperTrading.e2e.test.ts
 */

const BASE = 'http://localhost:8000/api/v1';

describe('Paper Trading E2E', () => {
  let accountId: string;

  it('should create a paper account with ₹100,000', async () => {
    const res = await fetch(`${BASE}/paper/accounts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initial_cash: 100000 })
    });
    const data = await res.json();
    expect(data.account_id).toBeDefined();
    expect(data.cash).toBe(100000);
    expect(data.equity).toBe(100000);
    accountId = data.account_id;
  });

  it('should list the created account', async () => {
    const res = await fetch(`${BASE}/paper/accounts`);
    const data = await res.json();
    const found = data.find((a: { account_id: string }) => a.account_id === accountId);
    expect(found).toBeDefined();
    expect(found.cash).toBe(100000);
  });

  it('should run a one-day replay', async () => {
    const res = await fetch(`${BASE}/paper/${accountId}/replay`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: '2025-01-02', speed: 100 })
    });
    const data = await res.json();
    expect(data.status).toBeDefined();
  });

  it('should return equity curve data after replay', async () => {
    const res = await fetch(`${BASE}/paper/${accountId}/equity`);
    const data = await res.json();
    expect(Array.isArray(data)).toBe(true);
    if (data.length > 0) {
      expect(data[0].date).toBeDefined();
      expect(data[0].equity).toBeDefined();
      expect(typeof data[0].equity).toBe('number');
    }
  });

  it('should return account metrics', async () => {
    const res = await fetch(`${BASE}/paper/${accountId}/metrics`);
    const data = await res.json();
    expect(data.total_trades).toBeDefined();
    expect(data.net_pnl).toBeDefined();
    expect(typeof data.net_pnl).toBe('number');
  });
});
