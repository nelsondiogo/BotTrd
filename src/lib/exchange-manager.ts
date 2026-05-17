import ccxt from 'ccxt';

export class ExchangeManager {
  public client: any;
  
  constructor(apiKey: string, apiSecret: string, testnet: boolean = true) {
    const ExchangeClass = (ccxt as any).bybit || ccxt.bybit;
    this.client = new ExchangeClass({
      apiKey,
      secret: apiSecret,
      enableRateLimit: true,
      options: { defaultType: 'future' }
    });
    if (testnet) this.client.setSandboxMode(true);
  }

  async getBalance() {
    try {
      const balance = await this.client.fetchBalance();
      return balance.total['USDT'] || 0;
    } catch (e) { return 0; }
  }

  async fetchOHLCV(symbol: string, timeframe: string, limit: number = 50) {
    return await this.client.fetchOHLCV(symbol, timeframe, undefined, limit);
  }

  async fetchTickers() {
    try {
      const tickers = await this.client.fetchTickers();
      return Object.values(tickers).filter((t: any) => t.symbol.includes('/USDT'));
    } catch (e) { return []; }
  }

  async getActivePosition() {
    try {
      const positions = await this.client.fetchPositions();
      return positions.find((p: any) => parseFloat(p.contracts || '0') > 0);
    } catch (e) { return null; }
  }
}
