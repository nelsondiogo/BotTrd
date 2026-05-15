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
    const balance = await this.client.fetchBalance();
    return balance.total['USDT'] || 0;
  }

  async fetchOHLCV(symbol: string, timeframe: string, limit: number = 50) {
    return await this.client.fetchOHLCV(symbol, timeframe, undefined, limit);
  }

  async createOrder(symbol: string, side: 'buy' | 'sell', amount: number, leverage: number = 10) {
    await this.client.setLeverage(leverage, symbol);
    return await this.client.createMarketOrder(symbol, side, amount);
  }

  async closePosition(symbol: string) {
    const positions = await this.client.fetchPositions([symbol]);
    const pos = positions.find(p => p.symbol === symbol && parseFloat(p.contracts || '0') !== 0);
    if (pos) {
      const side = pos.side === 'long' ? 'sell' : 'buy';
      return await this.client.createMarketOrder(symbol, side, pos.contracts);
    }
    return null;
  }

  async fetchTickers() {
    const tickers = await this.client.fetchTickers();
    return Object.values(tickers).filter((t: any) => t.symbol.endsWith('/USDT:USDT'));
  }
}
