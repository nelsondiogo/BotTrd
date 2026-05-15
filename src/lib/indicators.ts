import ccxt from 'ccxt';

export class ExchangeManager {
  public client: any;

  constructor(apiKey: string, apiSecret: string, testnet: boolean = true) {
    const ExchangeClass = (ccxt as any).bybit || ccxt.bybit;
    this.client = new ExchangeClass({
      apiKey: apiKey,
      secret: apiSecret,
      enableRateLimit: true,
      options: { defaultType: 'future' }
    });
    if (testnet) this.client.setSandboxMode(true);
  }

  async fetchOHLCV(symbol: string, timeframe: string = '1h', limit: number = 100) {
    return await this.client.fetchOHLCV(symbol, timeframe, undefined, limit);
  }

  async getBalance() {
    return await this.client.fetchBalance();
  }
}
