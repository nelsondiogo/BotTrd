import math
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

# =============================================================================
# INDICADORES TÉCNICOS NATIVOS (sem pandas/numpy)
# =============================================================================
class TechnicalAnalysis:
    @staticmethod
    def ema(data: List[float], period: int) -> List[float]:
        """Calcula EMA usando listas nativas."""
        if len(data) < period:
            return [0.0] * len(data)

        multiplier = 2.0 / (period + 1)
        ema_values = [sum(data[:period]) / period]

        for i in range(period, len(data)):
            ema_values.append((data[i] - ema_values[-1]) * multiplier + ema_values[-1])

        # Preenche início com zeros
        return [0.0] * (period - 1) + ema_values

    @staticmethod
    def sma(data: List[float], period: int) -> List[float]:
        """Calcula SMA usando listas nativas."""
        if len(data) < period:
            return [0.0] * len(data)

        result = [0.0] * (period - 1)
        for i in range(period - 1, len(data)):
            result.append(sum(data[i - period + 1:i + 1]) / period)
        return result

    @staticmethod
    def rsi(closes: List[float], period: int = 14) -> List[float]:
        """Calcula RSI usando listas nativas."""
        if len(closes) < period + 1:
            return [50.0] * len(closes)

        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))

        avg_gains = [sum(gains[:period]) / period]
        avg_losses = [sum(losses[:period]) / period]

        for i in range(period, len(gains)):
            avg_gains.append((avg_gains[-1] * (period - 1) + gains[i]) / period)
            avg_losses.append((avg_losses[-1] * (period - 1) + losses[i]) / period)

        rsi_values = []
        for i in range(len(avg_gains)):
            if avg_losses[i] == 0:
                rsi_values.append(100.0)
            else:
                rs = avg_gains[i] / avg_losses[i]
                rsi_values.append(100.0 - (100.0 / (1.0 + rs)))

        return [50.0] + [50.0] * (period - 1) + rsi_values

    @staticmethod
    def adx(ohlcv: List[List[float]], period: int = 14) -> List[float]:
        """Calcula ADX simplificado."""
        if len(ohlcv) < period * 2:
            return [25.0] * len(ohlcv)

        highs = [c[2] for c in ohlcv]
        lows = [c[3] for c in ohlcv]
        closes = [c[4] for c in ohlcv]

        tr_values = []
        for i in range(1, len(ohlcv)):
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i - 1])
            tr3 = abs(lows[i] - closes[i - 1])
            tr_values.append(max(tr1, tr2, tr3))

        if len(tr_values) < period:
            return [25.0] * len(ohlcv)

        atr = [sum(tr_values[:period]) / period]
        for i in range(period, len(tr_values)):
            atr.append((atr[-1] * (period - 1) + tr_values[i]) / period)

        # Simplificação: usa ATR como proxy de volatilidade
        adx_values = [25.0] * (period + 1)
        for i in range(len(atr)):
            adx_values.append(min(atr[i] / closes[i + period] * 1000, 100))

        return adx_values[:len(ohlcv)]

    @staticmethod
    def atr(ohlcv: List[List[float]], period: int = 14) -> List[float]:
        """Calcula ATR."""
        if len(ohlcv) < period + 1:
            return [0.0] * len(ohlcv)

        highs = [c[2] for c in ohlcv]
        lows = [c[3] for c in ohlcv]
        closes = [c[4] for c in ohlcv]

        tr_values = [0.0]
        for i in range(1, len(ohlcv)):
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i - 1])
            tr3 = abs(lows[i] - closes[i - 1])
            tr_values.append(max(tr1, tr2, tr3))

        atr_values = [0.0] * period
        atr_values.append(sum(tr_values[1:period + 1]) / period)

        for i in range(period + 1, len(tr_values)):
            atr_values.append((atr_values[-1] * (period - 1) + tr_values[i]) / period)

        return atr_values

    @staticmethod
    def volume_sma(volumes: List[float], period: int = 20) -> List[float]:
        """SMA de volume."""
        return TechnicalAnalysis.sma(volumes, period)


# =============================================================================
# SIGNAL
# =============================================================================
@dataclass
class SignalResult:
    side: Optional[str] = None
    symbol: str = ''
    score: float = 0.0
    price: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)
    confidence: str = 'low'


# =============================================================================
# GERADOR DE SINAIS
# =============================================================================
class SignalGenerator:
    def __init__(self, adx_threshold: float = 25.0):
        self.adx_threshold = adx_threshold

    def generate(self, ohlcv_m15: List[List[float]], ohlcv_h1: List[List[float]], ohlcv_h4: Optional[List[List[float]]] = None) -> SignalResult:
        if len(ohlcv_m15) < 30 or len(ohlcv_h1) < 22:
            return SignalResult()

        closes_m15 = [c[4] for c in ohlcv_m15]
        volumes_m15 = [c[5] for c in ohlcv_m15]

        closes_h1 = [c[4] for c in ohlcv_h1]

        # Indicadores M15
        ema9_m15 = TechnicalAnalysis.ema(closes_m15, 9)
        ema21_m15 = TechnicalAnalysis.ema(closes_m15, 21)
        rsi_m15 = TechnicalAnalysis.rsi(closes_m15, 14)
        adx_m15 = TechnicalAnalysis.adx(ohlcv_m15, 14)
        atr_m15 = TechnicalAnalysis.atr(ohlcv_m15, 14)
        vol_sma_m15 = TechnicalAnalysis.volume_sma(volumes_m15, 20)

        # Indicadores H1
        ema9_h1 = TechnicalAnalysis.ema(closes_h1, 9)
        ema21_h1 = TechnicalAnalysis.ema(closes_h1, 21)
        adx_h1 = TechnicalAnalysis.adx(ohlcv_h1, 14)

        # Valores atuais
        c_close = closes_m15[-1]
        c_ema9 = ema9_m15[-1]
        c_ema21 = ema21_m15[-1]
        c_rsi = rsi_m15[-1]
        c_adx = adx_m15[-1]
        c_vol = volumes_m15[-1]
        c_vol_sma = vol_sma_m15[-1] if vol_sma_m15[-1] > 0 else 1
        c_atr = atr_m15[-1]

        h1_ema9 = ema9_h1[-1]
        h1_ema21 = ema21_h1[-1]
        h1_adx = adx_h1[-1]

        # Validações
        if c_adx < self.adx_threshold or c_rsi == 0:
            return SignalResult()

        # Tendência H1
        h1_bull = h1_ema9 > h1_ema21 if h1_ema9 > 0 and h1_ema21 > 0 else False
        h1_bear = h1_ema9 < h1_ema21 if h1_ema9 > 0 and h1_ema21 > 0 else False

        side = None
        score = 0.0

        # LONG
        if c_ema9 > c_ema21 and c_rsi < 60 and h1_bull:
            if c_rsi < 20:
                return SignalResult()
            if c_vol < c_vol_sma * 0.8:
                return SignalResult()
            side = 'long'
            score = self._calc_score(c_adx, h1_adx, c_rsi, side, c_vol / c_vol_sma)

        # SHORT
        elif c_ema9 < c_ema21 and c_rsi > 40 and h1_bear:
            if c_rsi > 80:
                return SignalResult()
            if c_vol < c_vol_sma * 0.8:
                return SignalResult()
            side = 'short'
            score = self._calc_score(c_adx, h1_adx, c_rsi, side, c_vol / c_vol_sma)

        if side and score >= 0.72:
            confidence = 'high' if score >= 0.85 else 'medium' if score >= 0.78 else 'low'

            return SignalResult(
                side=side,
                price=round(c_close, 8),
                score=round(score, 3),
                confidence=confidence,
                meta={
                    'rsi': round(c_rsi, 2),
                    'adx': round(c_adx, 2),
                    'atr': round(c_atr, 6),
                    'ema9': round(c_ema9, 6),
                    'ema21': round(c_ema21, 6),
                    'trend_h1': 'ALTA' if h1_bull else 'BAIXA' if h1_bear else 'NEUTRO',
                    'h1_adx': round(h1_adx, 2),
                    'volume_ratio': round(c_vol / c_vol_sma, 2),
                }
            )
        return SignalResult()

    def _calc_score(self, adx: float, h1_adx: float, rsi: float, side: str, vol_ratio: float) -> float:
        score = 0.5

        adx_norm = min(adx / 50.0, 1.0)
        score += adx_norm * 0.25

        h1_adx_norm = min(h1_adx / 50.0, 1.0)
        score += h1_adx_norm * 0.20

        if side == 'long':
            rsi_score = max(0, (55 - rsi) / 55)
        else:
            rsi_score = max(0, (rsi - 45) / 55)
        score += rsi_score * 0.15

        if vol_ratio > 1.5:
            score += 0.05
        elif vol_ratio < 0.5:
            score -= 0.05

        return min(max(score, 0.0), 1.0)


# =============================================================================
# POSITION TRACKER
# =============================================================================
class PositionTracker:
    def __init__(self):
        self.symbol: Optional[str] = None
        self.side: Optional[str] = None
        self.entry_price: float = 0.0
        self.entry_score: float = 0.0
        self.size: float = 0.0
        self.leverage: int = 1
        self.session_start_balance: float = 0.0
        self.peak_profit_pct: float = -999.0
        self.peak_price: float = 0.0
        self.lock_profit_pct: float = 0.0
        self.locked: bool = False
        self.entry_time: Optional[float] = None
        self.max_drawdown_pct: float = 0.0

    def reset(self):
        self.symbol = None
        self.side = None
        self.entry_price = 0.0
        self.entry_score = 0.0
        self.size = 0.0
        self.leverage = 1
        self.peak_profit_pct = -999.0
        self.peak_price = 0.0
        self.lock_profit_pct = 0.0
        self.locked = False
        self.entry_time = None
        self.max_drawdown_pct = 0.0

    def _profit_pct(self, current_price: float) -> float:
        if self.entry_price == 0:
            return 0.0
        if self.side == 'long':
            return (current_price - self.entry_price) / self.entry_price * 100
        return (self.entry_price - current_price) / self.entry_price * 100

    def _get_lock_stage(self, peak: float) -> float:
        if peak >= 5.0: return peak * 0.75
        elif peak >= 3.0: return peak * 0.70
        elif peak >= 1.5: return peak * 0.60
        elif peak >= 0.8: return peak * 0.50
        elif peak >= 0.4: return peak * 0.35
        elif peak >= 0.2: return 0.10
        return 0.0

    def _get_drawdown_threshold(self, peak: float) -> float:
        if peak >= 3.0: return peak * 0.70
        elif peak >= 2.0: return peak * 0.65
        elif peak >= 1.0: return peak * 0.60
        elif peak >= 0.5: return peak * 0.55
        elif peak >= 0.2: return peak * 0.50
        elif peak > 0: return peak * 0.40
        return 0.0

    def update_peak(self, current_price: float):
        profit = self._profit_pct(current_price)
        if profit > self.peak_profit_pct:
            self.peak_profit_pct = profit
            self.peak_price = current_price
        if profit < self.max_drawdown_pct:
            self.max_drawdown_pct = profit
        if not self.locked:
            stage = self._get_lock_stage(self.peak_profit_pct)
            if stage > 0:
                self.locked = True
                self.lock_profit_pct = stage

    def check_stop_loss(self, current_price: float, sl_pct: float) -> bool:
        if self.side == 'long':
            loss = (self.entry_price - current_price) / self.entry_price * 100
        else:
            loss = (current_price - self.entry_price) / self.entry_price * 100
        return loss >= sl_pct

    def check_trailing_stop(self, current_price: float) -> tuple[bool, str]:
        profit = self._profit_pct(current_price)

        if self.locked and profit <= self.lock_profit_pct:
            return True, f"LOCK_PROFIT | peak={self.peak_profit_pct:.2f}% lock={self.lock_profit_pct:.2f}%"

        if self.peak_profit_pct > 0:
            threshold = self._get_drawdown_threshold(self.peak_profit_pct)
            if profit <= threshold:
                return True, f"DRAWDOWN | peak={self.peak_profit_pct:.2f}% current={profit:.2f}%"

        if self.entry_time and (time.time() - self.entry_time) > 1800:
            if profit < 0.1:
                return True, f"TIME_STOP | tempo=30min profit={profit:.2f}%"

        return False, ""

    def get_state(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'entry_score': self.entry_score,
            'size': self.size,
            'leverage': self.leverage,
            'peak_profit_pct': round(self.peak_profit_pct, 3) if self.peak_profit_pct > -900 else 0.0,
            'peak_price': round(self.peak_price, 8),
            'locked': self.locked,
            'lock_profit_pct': self.lock_profit_pct,
            'entry_time': self.entry_time,
            'max_drawdown_pct': round(self.max_drawdown_pct, 3),
        }


# =============================================================================
# OPPORTUNITY ANALYZER
# =============================================================================
class OpportunityAnalyzer:
    def __init__(self, rotation_threshold: float = 1.20):
        self.rotation_threshold = rotation_threshold

    def should_rotate(self, tracker: PositionTracker, new_signal: SignalResult,
                      current_unrealized_pnl: float, current_price: float) -> bool:
        if not tracker.symbol or not new_signal.side:
            return False

        if tracker.locked and current_unrealized_pnl > 0:
            return False

        if new_signal.score < 0.80:
            return False

        if tracker.entry_score > 0 and (new_signal.score - tracker.entry_score) < 0.15:
            return False

        atr = new_signal.meta.get('atr', 0)
        price = new_signal.price
        potential_pct = (atr / price) * 100 if price > 0 and atr > 0 else 1.0
        new_potential = new_signal.score * potential_pct

        current_pnl_pct = 0.0
        if tracker.session_start_balance > 0:
            current_pnl_pct = (current_unrealized_pnl / tracker.session_start_balance) * 100

        if current_pnl_pct > 0.5:
            return False

        return new_potential > max(current_pnl_pct, 0.1) * self.rotation_threshold


# =============================================================================
# RISK MANAGER
# =============================================================================
class RiskManager:
    def __init__(self, base_leverage: int = 3, max_leverage: int = 5):
        self.base_leverage = base_leverage
        self.max_leverage = max_leverage

    def dynamic_leverage(self, adx: float, base: int) -> int:
        if adx >= 45:
            return min(self.max_leverage, base + 2)
        elif adx >= 35:
            return min(self.max_leverage, base + 1)
        elif adx >= 25:
            return base
        return max(1, base - 1)

    def calculate_position_size(self, balance: float, price: float, leverage: int,
                                 risk_pct: float = 0.015, min_cost: float = 5.0) -> float:
        if price <= 0 or balance <= 0:
            return 0.0
        risk_amount = balance * risk_pct
        position_value = risk_amount * leverage
        qty = position_value / price
        if qty * price < min_cost:
            qty = min_cost / price
        return round(qty, 6)

    def calculate_stop_loss_price(self, entry: float, side: str, sl_pct: float) -> float:
        if side == 'long':
            return entry * (1 - sl_pct / 100)
        return entry * (1 + sl_pct / 100)
