import { EMA, RSI, BollingerBands } from 'technicalindicators';

export function analyzeMarket(ohlcv: any[]) {
  const closes = ohlcv.map(d => d[4]);
  
  const rsi = RSI.calculate({ values: closes, period: 14 });
  const bb = BollingerBands.calculate({ values: closes, period: 20, stdDev: 2 });
  const ema20 = EMA.calculate({ values: closes, period: 20 });
  const lastClose = closes[closes.length - 1];
  
  const lastRSI = rsi[rsi.length - 1];
  const lastBB = bb[bb.length - 1];
  const lastEMA = ema20[ema20.length - 1];

  let trend = lastClose > lastEMA ? 'bull' : 'bear';
  let score = 0.5;

  if (lastRSI < 30) score += 0.2;
  if (lastRSI > 70) score -= 0.2;
  if (lastClose < lastBB.lower) score += 0.2;
  if (lastClose > lastBB.upper) score -= 0.2;

  return {
    trend,
    score: Math.min(Math.max(score, 0), 1),
    close: lastClose,
    rsi: lastRSI
  };
}
