const RENDER_BACKEND_URL = 'https://stocktraderv2.onrender.com';

export const environment = {
  production: true,
  appName: 'StockTrader',
  apiUrl: `${RENDER_BACKEND_URL}/api/v1`,
  wsBaseUrl: RENDER_BACKEND_URL.replace(/^http/, 'ws'),
};
