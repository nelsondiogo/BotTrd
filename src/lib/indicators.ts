import { EMA, RSI, ADX, MFI } from 'technicalindicators';

export function calculateIndicators(prices: number[], volumes: number[], high: number[], low: number[], close: number[]) {
  const ema9 = EMA.calculate({ period: 9, values: close });
  const ema21 = EMA.calculate({ period: 21, values: close });
  const rsi = RSI.calculate({ period: 14, values: close });
  const adx = ADX.calculate({ period: 14, high, low, close });
  const mfi = MFI.calculate({ high, low, close, volume: volumes, period: 14 });

  return {
    ema9: ema9[ema9.length - 1],
    ema21: ema21[ema21.length - 1],
    rsi: rsi[rsi.length - 1],
    adx: adx[adx.length - 1]?.adx || 0,
    mfi: mfi[mfi.length - 1] || 0,
    currPrice: close[close.length - 1]
  };
}

export function calculateScore(indicators: any, h1Trend: 'bull' | 'bear' | 'neutral') {
  let score = 0;
  if (indicators.ema9 > indicators.ema21 && h1Trend === 'bull') score += 0.4;
  if (indicators.rsi < 35) score += 0.2;
  if (indicators.mfi < 30) score += 0.2;
  if (indicators.adx > 25) score += 0.2;
  return { score, confidence: score >= 0.8 ? 'high' : 'medium' };
}
