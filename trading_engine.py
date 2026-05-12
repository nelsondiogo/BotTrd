import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

# =============================================================================
# INDICADORES TÉCNICOS NATIVOS (sem pandas/numpy)
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

    @staticmethod
    def mfi(ohlcv: List[List[float]], period: int = 14) -> List[float]:
        """Money Flow Index nativo sem pandas."""
        if len(ohlcv) < period + 1:
            return [50.0] * len(ohlcv)

        tp_values = []
        raw_mf = []
        for c in ohlcv:
            tp = (c[2] + c[3] + c[4]) / 3.0  # typical price
            tp_values.append(tp)
            raw_mf.append(tp * c[5])  # volume

        pos_mf = []
        neg_mf = []
        for i in range(1, len(tp_values)):
            if tp_values[i] >= tp_values[i-1]:
                pos_mf.append(raw_mf[i])
                neg_mf.append(0.0)
            else:
                pos_mf.append(0.0)
                neg_mf.append(raw_mf[i])

        mfi_values = [50.0]  # primeiro valor neutro
        for i in range(period - 1, len(pos_mf)):
            sum_pos = sum(pos_mf[i - period + 1:i + 1])
            sum_neg = sum(neg_mf[i - period + 1:i + 1])
            if sum_neg == 0:
                mfi_values.append(100.0)
            else:
                mr = sum_pos / sum_neg
                mfi_values.append(100.0 - (100.0 / (1.0 + mr)))

        # Preenche início
        padding = len(ohlcv) - len(mfi_values)
        return [50.0] * padding + mfi_values

    @staticmethod
    def ema_cross_bullish(ema_fast: List[float], ema_slow: List[float], lookback: int = 3) -> bool:
        """Verifica se houve cruzamento bullish recente."""
        if len(ema_fast) < lookback + 1 or len(ema_slow) < lookback + 1:
            return False
        for i in range(1, lookback + 1):
            curr_fast = ema_fast[-i]
            curr_slow = ema_slow[-i]
            prev_fast = ema_fast[-i - 1]
            prev_slow = ema_slow[-i - 1]
            if prev_fast <= prev_slow and curr_fast > curr_slow:
                return True
        return False

    @staticmethod
    def ema_cross_bearish(ema_fast: List[float], ema_slow: List[float], lookback: int = 3) -> bool:
        if len(ema_fast) < lookback + 1 or len(ema_slow) < lookback + 1:
            return False
        for i in range(1, lookback + 1):
            curr_fast = ema_fast[-i]
            curr_slow = ema_slow[-i]
            prev_fast = ema_fast[-i - 1]
            prev_slow = ema_slow[-i - 1]
            if prev_fast >= prev_slow and curr_fast < curr_slow:
                return True
        return False


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
    expected_return_pct: float = 0.0  # potencial estimado de retorno


# =============================================================================
# GERADOR DE SINAIS
# =============================================================================
class SignalGenerator:
    def __init__(self, adx_threshold: float = 25.0):
        self.adx_threshold = adx_threshold

    def generate(self, ohlcv_m15: List[List[float]], ohlcv_h1: List[List[float]], 
                 ohlcv_h4: Optional[List[List[float]]] = None) -> SignalResult:
        if len(ohlcv_m15) < 35 or len(ohlcv_h1) < 25:
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
        if c_adx < self.adx_threshold:
            return SignalResult()
        if c_rsi == 0:
            return SignalResult()

        # Tendência H1
        h1_bull = h1_ema9 > h1_ema21 if h1_ema9 > 0 and h1_ema21 > 0 else False
        h1_bear = h1_ema9 < h1_ema21 if h1_ema9 > 0 and h1_ema21 > 0 else False

        side = None
        score = 0.0

        # LONG
        if c_ema9 > c_ema21 and c_rsi < 60 and h1_bull:
            if c_rsi < 25:
                return SignalResult()
            if c_mfi < 20:
                return SignalResult()  # MFI muito baixo = falta fluxo de compra
            if c_vol < c_vol_sma * 0.8:
                return SignalResult()
            # Confirmação de cruzamento recente ou alinhamento forte
            if not TechnicalAnalysis.ema_cross_bullish(ema9_m15, ema21_m15, lookback=3) and (c_ema9 - c_ema21) / c_close < 0.001:
                return SignalResult()
            side = 'long'
            score = self._calc_score(c_adx, h1_adx, c_rsi, c_mfi, side, c_vol / c_vol_sma)

        # SHORT
        elif c_ema9 < c_ema21 and c_rsi > 40 and h1_bear:
            if c_rsi > 75:
                return SignalResult()
            if c_mfi > 80:
                return SignalResult()  # MFI muito alto = falta fluxo de venda
            if c_vol < c_vol_sma * 0.8:
                return SignalResult()
            if not TechnicalAnalysis.ema_cross_bearish(ema9_m15, ema21_m15, lookback=3) and (c_ema21 - c_ema9) / c_close < 0.001:
                return SignalResult()
            side = 'short'
            score = self._calc_score(c_adx, h1_adx, c_rsi, c_mfi, side, c_vol / c_vol_sma)

        # Rigor HFT: score mínimo 0.82
        if side and score >= 0.82:
            confidence = 'high' if score >= 0.90 else 'medium' if score >= 0.86 else 'low'

            # Filtro H4 de tendência macro
            if ohlcv_h4 and len(ohlcv_h4) >= 25:
                closes_h4 = [c[4] for c in ohlcv_h4]
                ema9_h4 = TechnicalAnalysis.ema(closes_h4, 9)
                ema21_h4 = TechnicalAnalysis.ema(closes_h4, 21)
                h4_ema9 = ema9_h4[-1]
                h4_ema21 = ema21_h4[-1]
                if side == 'long' and h4_ema9 <= h4_ema21:
                    return SignalResult()
                if side == 'short' and h4_ema9 >= h4_ema21:
                    return SignalResult()

            # Potencial de retorno estimado (ATR-based)
            expected_return = (c_atr / c_close) * 100 * 2.0 if c_close > 0 else 0.0

            return SignalResult(
                side=side,
                price=round(c_close, 8),
                score=round(score, 3),
                confidence=confidence,
                expected_return_pct=round(expected_return, 4),
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
        score += adx_norm * 0.22
        h1_adx_norm = min(h1_adx / 50.0, 1.0)
        score += h1_adx_norm * 0.18
        if side == 'long':
            rsi_score = max(0, (55 - rsi) / 55)
            mfi_score = max(0, (50 - mfi) / 50) if mfi < 50 else 0
        else:
            rsi_score = max(0, (rsi - 45) / 55)
            mfi_score = max(0, (mfi - 50) / 50) if mfi > 50 else 0
        score += rsi_score * 0.12
        score += mfi_score * 0.10
        if vol_ratio > 1.5:
            score += 0.06
        elif vol_ratio < 0.5:
            score -= 0.08
        return min(max(score, 0.0), 1.0)


# =============================================================================
# POSITION TRACKER - Trailing Stop Agressivo
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
        self.lock_stage_pct: float = 0.0  # % travada de lucro

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
        self.lock_stage_pct = 0.0

    def _profit_pct(self, current_price: float) -> float:
        if self.entry_price == 0:
            return 0.0
        if self.side == 'long':
            return (current_price - self.entry_price) / self.entry_price * 100
        return (self.entry_price - current_price) / self.entry_price * 100

    def _get_lock_stage(self, peak: float) -> float:
        """
        Aggressive Profit Lock:
        +1%% -> lock +0.7%%
        +2%% -> lock +1.6%%
        +3%% -> lock +2.4%%
        +5%% -> lock +4.0%%
        """
        if peak >= 5.0: return peak * 0.80
        elif peak >= 3.0: return peak * 0.80
        elif peak >= 2.0: return peak * 0.80
        elif peak >= 1.0: return peak * 0.70
        elif peak >= 0.5: return peak * 0.60
        elif peak >= 0.2: return 0.10
        return 0.0

    def _get_drawdown_threshold(self, peak: float) -> float:
        """
        Se lucro recuar 30%% do pico máximo atingido, fecha imediatamente.
        Ex: pico +2%%, threshold = +1.4%%. Se cair abaixo de 1.4%%, fecha.
        """
        if peak > 0:
            return peak * 0.70  # deixa escapar no máximo 30%% do lucro de pico
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
                self.lock_stage_pct = stage

    def check_stop_loss(self, current_price: float, sl_pct: float) -> bool:
        if self.side == 'long':
            loss = (self.entry_price - current_price) / self.entry_price * 100
        else:
            loss = (current_price - self.entry_price) / self.entry_price * 100
        return loss >= sl_pct

    def check_trailing_stop(self, current_price: float) -> tuple[bool, str]:
        profit = self._profit_pct(current_price)

        # Lock profit já travado
        if self.locked and profit <= self.lock_profit_pct:
            return True, f"LOCK_PROFIT | peak={self.peak_profit_pct:.2f}% lock={self.lock_profit_pct:.2f}%"

        # Drawdown de 30%% do pico
        if self.peak_profit_pct > 0:
            threshold = self._get_drawdown_threshold(self.peak_profit_pct)
            if profit <= threshold:
                return True, f"DD_30%% | peak={self.peak_profit_pct:.2f}% current={profit:.2f}%"

        # Time stop: se após 30min não tem lucro significativo
        if self.entry_time and (time.time() - self.entry_time) > 1800:
            if profit < 0.15:
                return True, f"TIME_STOP | 30min profit={profit:.2f}%"

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
            'lock_stage_pct': self.lock_stage_pct,
            'entry_time': self.entry_time,
            'max_drawdown_pct': round(self.max_drawdown_pct, 3),
        }


# =============================================================================
# OPPORTUNITY ANALYZER - Dynamic Opportunity Cost
# =============================================================================
class OpportunityAnalyzer:
    def __init__(self, rotation_threshold: float = 1.15):
        self.rotation_threshold = rotation_threshold

    def should_rotate(self, tracker: PositionTracker, new_signal: SignalResult,
                      current_unrealized_pnl: float, current_price: float) -> bool:
        if not tracker.symbol or not new_signal.side:
            return False

        # Não rotaciona se já travou lucro positivo
        if tracker.locked and current_unrealized_pnl > 0:
            return False

        # Só rotaciona para sinais de alta confiança
        if new_signal.score < 0.88:
            return False

        # Deve ser significativamente melhor que a entrada atual
        if tracker.entry_score > 0 and (new_signal.score - tracker.entry_score) < 0.12:
            return False

        # Potencial do novo sinal
        atr = new_signal.meta.get('atr', 0)
        price = new_signal.price
        potential_pct = (atr / price) * 100 * new_signal.score if price > 0 and atr > 0 else 0.5
        new_potential = potential_pct

        # PnL atual como oportunidade custo
        current_pnl_pct = 0.0
        if tracker.session_start_balance > 0:
            current_pnl_pct = (current_unrealized_pnl / tracker.session_start_balance) * 100

        # Se já está com lucro razoável, não rotaciona
        if current_pnl_pct > 0.8:
            return False

        # Rotaciona se o novo potencial é superior ao atual * threshold
        return new_potential > max(current_pnl_pct, 0.05) * self.rotation_threshold


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
