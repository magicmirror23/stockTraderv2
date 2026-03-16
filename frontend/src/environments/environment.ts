const browserProtocol = typeof window !== 'undefined' ? window.location.protocol : 'http:';
const browserHost = typeof window !== 'undefined' ? window.location.host : '';
const wsProtocol = browserProtocol === 'https:' ? 'wss:' : 'ws:';

export const environment = {
  production: false,
  appName: 'StockTrader',
  apiUrl: '/api/v1',
  wsBaseUrl: browserHost ? `${wsProtocol}//${browserHost}` : '',
};
