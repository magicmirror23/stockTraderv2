const browserProtocol = typeof window !== 'undefined' ? window.location.protocol : 'http:';
const browserHost = typeof window !== 'undefined' ? window.location.host : '';
const browserHostname = typeof window !== 'undefined' ? window.location.hostname : '';
const wsProtocol = browserProtocol === 'https:' ? 'wss:' : 'ws:';
const isLocalAngularDev =
  browserHostname === 'localhost' || browserHostname === '127.0.0.1';

export const environment = {
  production: false,
  appName: 'StockTrader',
  apiUrl: '/api/v1',
  wsBaseUrl: isLocalAngularDev ? `${wsProtocol}//localhost:8000` : (browserHost ? `${wsProtocol}//${browserHost}` : ''),
};
