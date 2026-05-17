import ccxt from 'ccxt';

export class ExchangeManager {
  public client: any;
  constructor(apiKey: string, apiSecret: string, testnet: boolean = true) {
    const ExchangeClass = (ccxt as any).bybit || ccxt.bybit;
    this.client = new ExchangeClass({
      apiKey, secret: apiSecret, enableRateLimit: true,
      options: { defaultType: 'future' }
    });
    if (testnet) this.client.setSandboxMode(true);
  }
  async getBalance() {
    const balance = await this.client.fetchBalance();
    return balance.total['USDT'] || 0;
  }
  async fetchTickers() {
    const tickers = await this.client.fetchTickers();
    return Object.values(tickers).filter((t: any) => t.symbol.endsWith('/USDT:USDT'));
  }
  async fetchOHLCV(symbol: string, timeframe: string, limit: number = 50) {
    return await this.client.fetchOHLCV(symbol, timeframe, undefined, limit);
  }
}
