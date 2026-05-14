import time
import math
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

# =============================================================================
# INDICADORES TÉCNICOS NATIVOS
# =============================================================================
class TechnicalAnalysis:
    @staticmethod
    def ema(data: List[float], period: int) -> List[float]:
        if len(data) < period:
            return [0.0] * len(data)
        multiplier = 2.0 / (period + 1)
        ema_values = [sum(data[:period]) / period]
        for i in range(period, len(data)):
            ema_values.append((data[i] - ema_values[-1]) * multiplier + ema_values[-1])
        return [0.0] * (period - 1) + ema_values

    @staticmethod
    def sma(data: List[float], period: int) -> List[float]:
        if len(data) < period:
            return [0.0] * len(data)
        result = [0.0] * (period - 1)
        for i in range(period - 1, len(data)):
            result.append(sum(data[i - period + 1:i + 1]) / period)
        return result

    @staticmethod
    def rsi(closes: List[float], period: int = 14) -> List[float]:
        if len(closes) < period + 1:
            return [50.0] * len(closes)
        gains, losses = [], []
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
    def mfi(ohlcv: List[List[float]], period: int = 14) -> List[float]:
        """Money Flow Index (MFI) usando volume nativo."""
        if len(ohlcv) < period + 1:
            return [50.0] * len(ohlcv)
        tp = [(c[2] + c[3] + c[4]) / 3.0 for c in ohlcv]  # typical price
        raw_mf = [tp[i] * ohlcv[i][5] for i in range(len(ohlcv))]
        pos_mf, neg_mf = [], []
        for i in range(1, len(tp)):
            if tp[i] > tp[i-1]:
                pos_mf.append(raw_mf[i])
                neg_mf.append(0.0)
            elif tp[i] < tp[i-1]:
                pos_mf.append(0.0)
                neg_mf.append(raw_mf[i])
            else:
                pos_mf.append(0.0)
                neg_mf.append(0.0)
        if len(pos_mf) < period:
            return [50.0] * len(ohlcv)
        avg_pos = [sum(pos_mf[:period]) / period]
        avg_neg = [sum(neg_mf[:period]) / period]
        for i in range(period, len(pos_mf)):
            avg_pos.append((avg_pos[-1] * (period - 1) + pos_mf[i]) / period)
            avg_neg.append((avg_neg[-1] * (period - 1) + neg_mf[i]) / period)
        mfi_values = [50.0] * (period + 1)
        for i in range(len(avg_pos)):
            if avg_neg[i] == 0:
                mfi_values.append(100.0)
            else:
                ratio = avg_pos[i] / avg_neg[i]
                mfi_values.append(100.0 - (100.0 / (1.0 + ratio)))
        return mfi_values[:len(ohlcv)]

    @staticmethod
    def adx(ohlcv: List[List[float]], period: int = 14) -> List[float]:
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
        adx_values = [25.0] * (period + 1)
        for i in range(len(atr)):
            adx_values.append(min(atr[i] / closes[i + period] * 1000, 100))
        return adx_values[:len(ohlcv)]

    @staticmethod
    def atr(ohlcv: List[List[float]], period: int = 14) -> List[float]:
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
        mfi_m15 = TechnicalAnalysis.mfi(ohlcv_m15, 14)

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
        c_mfi = mfi_m15[-1] if mfi_m15 else 50.0

        h1_ema9 = ema9_h1[-1]
        h1_ema21 = ema21_h1[-1]
        h1_adx = adx_h1[-1]

        # Validações rigorosas
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
            if c_mfi < 20 or c_mfi > 80:
                return SignalResult()
            side = 'long'
            score = self._calc_score(c_adx, h1_adx, c_rsi, c_mfi, side, c_vol / c_vol_sma)

        # SHORT
        elif c_ema9 < c_ema21 and c_rsi > 40 and h1_bear:
            if c_rsi > 80:
                return SignalResult()
            if c_vol < c_vol_sma * 0.8:
                return SignalResult()
            if c_mfi < 20 or c_mfi > 80:
                return SignalResult()
            side = 'short'
            score = self._calc_score(c_adx, h1_adx, c_rsi, c_mfi, side, c_vol / c_vol_sma)

        # Score mínimo rigoroso: 0.82
        if side and score >= 0.82:
            confidence = 'high' if score >= 0.90 else 'medium' if score >= 0.86 else 'low'
            # Rejeita confidence low
            if confidence == 'low':
                return SignalResult()

            # Filtro H4: confirmação macro
            if ohlcv_h4 and len(ohlcv_h4) >= 22:
                closes_h4 = [c[4] for c in ohlcv_h4]
                ema9_h4 = TechnicalAnalysis.ema(closes_h4, 9)
                ema21_h4 = TechnicalAnalysis.ema(closes_h4, 21)
                h4_ema9 = ema9_h4[-1]
                h4_ema21 = ema21_h4[-1]
                if side == 'long' and h4_ema9 <= h4_ema21:
                    return SignalResult()
                if side == 'short' and h4_ema9 >= h4_ema21:
                    return SignalResult()

            return SignalResult(
                side=side,
                price=round(c_close, 8),
                score=round(score, 3),
                confidence=confidence,
                meta={
                    'rsi': round(c_rsi, 2),
                    'mfi': round(c_mfi, 2),
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

    def _calc_score(self, adx: float, h1_adx: float, rsi: float, mfi: float, side: str, vol_ratio: float) -> float:
        score = 0.5
        adx_norm = min(adx / 50.0, 1.0)
        score += adx_norm * 0.25
        h1_adx_norm = min(h1_adx / 50.0, 1.0)
        score += h1_adx_norm * 0.20
        if side == 'long':
            rsi_score = max(0, (55 - rsi) / 55)
            mfi_score = max(0, (60 - mfi) / 60) if mfi < 60 else 0
        else:
            rsi_score = max(0, (rsi - 45) / 55)
            mfi_score = max(0, (mfi - 40) / 60) if mfi > 40 else 0
        score += rsi_score * 0.12
        score += mfi_score * 0.08
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
        """Lock profit agressivo conforme tabela do prompt."""
        if peak >= 5.0: return peak * 0.80
        elif peak >= 3.0: return peak * 0.80
        elif peak >= 2.0: return peak * 0.80
        elif peak >= 1.0: return peak * 0.70
        elif peak >= 0.5: return peak * 0.60
        elif peak >= 0.3: return peak * 0.50
        elif peak >= 0.15: return 0.10
        return 0.0

    def _get_drawdown_threshold(self, peak: float) -> float:
        """Drawdown de 30% do lucro de pico. Se pico=2%, fecha se cair para 1.4%."""
        if peak > 0:
            return peak * 0.70
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

        # 1. Lock profit triggered
        if self.locked and profit <= self.lock_profit_pct:
            return True, f"LOCK_PROFIT | peak={self.peak_profit_pct:.2f}% lock={self.lock_profit_pct:.2f}%"

        # 2. Drawdown 30% do pico
        if self.peak_profit_pct > 0:
            threshold = self._get_drawdown_threshold(self.peak_profit_pct)
            if profit <= threshold:
                return True, f"DRAWDOWN_30% | peak={self.peak_profit_pct:.2f}% current={profit:.2f}%"

        # 3. Time stop: 30min se lucro < 0.15%
        if self.entry_time and (time.time() - self.entry_time) > 1800:
            if profit < 0.15:
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

        # Não rotaciona se lucro está travado e positivo
        if tracker.locked and current_unrealized_pnl > 0:
            return False

        # Score mínimo do novo sinal: 0.88
        if new_signal.score < 0.88:
            return False

        # Diferença mínima de 0.12
        if tracker.entry_score > 0 and (new_signal.score - tracker.entry_score) < 0.12:
            return False

        # Potencial do novo sinal: score * ATR esperado (%)
        atr = new_signal.meta.get('atr', 0)
        price = new_signal.price
        potential_pct = (atr / price) * 100 if price > 0 and atr > 0 else 1.0
        new_potential = new_signal.score * potential_pct

        # PnL atual como % do balance
        current_pnl_pct = 0.0
        if tracker.session_start_balance > 0:
            current_pnl_pct = (current_unrealized_pnl / tracker.session_start_balance) * 100

        # Se já está ganhando > 0.5%, não rotaciona
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
