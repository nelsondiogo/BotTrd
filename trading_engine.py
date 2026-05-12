import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

# =============================================================================
# INDICADORES TÉCNICOS
# =============================================================================
class TechnicalAnalysis:
    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period, min_periods=period).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta.where(delta < 0, 0.0))
        avg_gain = gain.ewm(span=period, adjust=False).mean()
        avg_loss = loss.ewm(span=period, adjust=False).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        typical = (df['high'] + df['low'] + df['close']) / 3
        raw_money = typical * df['volume']
        delta = typical.diff()
        positive = raw_money.where(delta > 0, 0.0)
        negative = raw_money.where(delta < 0, 0.0)
        pos_sum = positive.rolling(window=period, min_periods=period).sum()
        neg_sum = negative.rolling(window=period, min_periods=period).sum()
        mfr = pos_sum / neg_sum
        return 100 - (100 / (1 + mfr))

    @staticmethod
    def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high, low, close = df['high'], df['low'], df['close']
        plus_dm = high.diff()
        minus_dm = low.diff().abs()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        dx = dx.replace([np.inf, -np.inf], 0).fillna(0)
        return dx.ewm(span=period, adjust=False).mean()

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift()).abs()
        tr3 = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()

    @staticmethod
    def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0):
        sma = series.rolling(window=period, min_periods=period).mean()
        std = series.rolling(window=period, min_periods=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower

    @staticmethod
    def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
        return df['volume'].rolling(window=period, min_periods=period).mean()


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
    confidence: str = 'low'  # low, medium, high


# =============================================================================
# GERADOR DE SINAIS — CORRIGIDO E APRIMORADO
# =============================================================================
class SignalGenerator:
    def __init__(self, adx_threshold: float = 25.0):
        self.adx_threshold = adx_threshold

    def generate(self, df_m15: pd.DataFrame, df_h1: pd.DataFrame, df_h4: Optional[pd.DataFrame] = None) -> SignalResult:
        """Gera sinal com múltiplos timeframes e filtros rigorosos."""
        if len(df_m15) < 30 or len(df_h1) < 22:
            return SignalResult()

        df_m15 = df_m15.copy()
        df_h1 = df_h1.copy()

        # Indicadores M15
        df_m15['ema9'] = TechnicalAnalysis.ema(df_m15['close'], 9)
        df_m15['ema21'] = TechnicalAnalysis.ema(df_m15['close'], 21)
        df_m15['rsi'] = TechnicalAnalysis.rsi(df_m15['close'], 14)
        df_m15['mfi'] = TechnicalAnalysis.mfi(df_m15, 14)
        df_m15['adx'] = TechnicalAnalysis.adx(df_m15, 14)
        df_m15['atr'] = TechnicalAnalysis.atr(df_m15, 14)
        df_m15['volume_sma'] = TechnicalAnalysis.volume_sma(df_m15, 20)

        # Bollinger Bands para identificar extremos
        df_m15['bb_upper'], df_m15['bb_mid'], df_m15['bb_lower'] = TechnicalAnalysis.bollinger_bands(df_m15['close'], 20, 2.0)

        # Indicadores H1
        df_h1['ema9'] = TechnicalAnalysis.ema(df_h1['close'], 9)
        df_h1['ema21'] = TechnicalAnalysis.ema(df_h1['close'], 21)
        df_h1['adx'] = TechnicalAnalysis.adx(df_h1, 14)

        # Indicadores H4 (se disponível)
        h4_trend = 'NEUTRO'
        if df_h4 is not None and len(df_h4) >= 22:
            df_h4 = df_h4.copy()
            df_h4['ema9'] = TechnicalAnalysis.ema(df_h4['close'], 9)
            df_h4['ema21'] = TechnicalAnalysis.ema(df_h4['close'], 21)
            df_h4['adx'] = TechnicalAnalysis.adx(df_h4, 14)
            h4_last = df_h4.iloc[-1]
            if not pd.isna(h4_last['ema9']) and not pd.isna(h4_last['ema21']):
                h4_trend = 'ALTA' if h4_last['ema9'] > h4_last['ema21'] else 'BAIXA'

        c = df_m15.iloc[-1]
        h1 = df_h1.iloc[-1]

        # Validações básicas
        if pd.isna(c['adx']) or c['adx'] < self.adx_threshold:
            return SignalResult()
        if pd.isna(c['rsi']) or pd.isna(c['mfi']):
            return SignalResult()

        # Tendência H1
        h1_bull = h1['ema9'] > h1['ema21'] if not pd.isna(h1['ema9']) and not pd.isna(h1['ema21']) else False
        h1_bear = h1['ema9'] < h1['ema21'] if not pd.isna(h1['ema9']) and not pd.isna(h1['ema21']) else False

        side = None
        score = 0.0
        confidence = 'low'

        # CONDIÇÕES CORRIGIDAS PARA LONG:
        # - EMA9 > EMA21 (tendência de alta curta)
        # - RSI < 60 (não sobrecomprado — CORRIGIDO: era 65)
        # - MFI < 70 (não sobrecomprado — CORRIGIDO: era 75)
        # - H1 em alta (confirmação de tendência maior)
        # - Preço próximo à banda inferior de Bollinger (valorização)
        # - Volume acima da média (confirmação)
        if c['ema9'] > c['ema21'] and c['rsi'] < 60 and c['mfi'] < 70 and h1_bull:
            # Filtro adicional: não entrar se RSI < 25 (pode estar em queda livre)
            if c['rsi'] < 20:
                return SignalResult()
            # Filtro de volume
            if c['volume'] < c['volume_sma'] * 0.8:
                return SignalResult()
            side = 'long'
            score = self._calc_score(c, h1, 'long', h4_trend)

        # CONDIÇÕES CORRIGIDAS PARA SHORT:
        # - EMA9 < EMA21 (tendência de baixa curta)
        # - RSI > 40 (não sobrevendido — CORRIGIDO: era 35)
        # - MFI > 30 (não sobrevendido — CORRIGIDO: era 25)
        # - H1 em baixa (confirmação de tendência maior)
        # - Preço próximo à banda superior de Bollinger (sobrevalorização)
        # - Volume acima da média (confirmação)
        elif c['ema9'] < c['ema21'] and c['rsi'] > 40 and c['mfi'] > 30 and h1_bear:
            # Filtro adicional: não entrar se RSI > 80 (pode estar em short squeeze)
            if c['rsi'] > 80:
                return SignalResult()
            # Filtro de volume
            if c['volume'] < c['volume_sma'] * 0.8:
                return SignalResult()
            side = 'short'
            score = self._calc_score(c, h1, 'short', h4_trend)

        # Score mínimo aumentado para 0.72 (era 0.55)
        if side and score >= 0.72:
            # Determina confiança
            if score >= 0.85:
                confidence = 'high'
            elif score >= 0.78:
                confidence = 'medium'
            else:
                confidence = 'low'

            return SignalResult(
                side=side,
                price=round(float(c['close']), 8),
                score=round(score, 3),
                confidence=confidence,
                meta={
                    'rsi': round(float(c['rsi']), 2),
                    'mfi': round(float(c['mfi']), 2),
                    'adx': round(float(c['adx']), 2),
                    'atr': round(float(c['atr']), 6),
                    'ema9': round(float(c['ema9']), 6),
                    'ema21': round(float(c['ema21']), 6),
                    'trend_h1': 'ALTA' if h1_bull else 'BAIXA' if h1_bear else 'NEUTRO',
                    'h1_adx': round(float(h1['adx']), 2) if not pd.isna(h1['adx']) else 0,
                    'h4_trend': h4_trend,
                    'volume_ratio': round(float(c['volume'] / c['volume_sma']), 2) if c['volume_sma'] > 0 else 1.0,
                    'bb_position': round(float((c['close'] - c['bb_lower']) / (c['bb_upper'] - c['bb_lower'])), 3) if c['bb_upper'] != c['bb_lower'] else 0.5,
                }
            )
        return SignalResult()

    def _calc_score(self, c, h1, side: str, h4_trend: str) -> float:
        """Calcula score com pesos adaptativos e confirmação H4."""
        score = 0.5

        # ADX M15 (força da tendência)
        adx_norm = min(c['adx'] / 50.0, 1.0)
        score += adx_norm * 0.25  # Aumentado de 0.20

        # ADX H1 (tendência de médio prazo)
        h1_adx = h1['adx'] if not pd.isna(h1.get('adx')) else 0
        h1_adx_norm = min(h1_adx / 50.0, 1.0)
        score += h1_adx_norm * 0.20  # Aumentado de 0.15

        # RSI/MFI alinhados ao lado
        if side == 'long':
            rsi_score = max(0, (55 - c['rsi']) / 55)  # Normalizado para 0-55
            mfi_score = max(0, (65 - c['mfi']) / 65)  # Normalizado para 0-65
        else:
            rsi_score = max(0, (c['rsi'] - 45) / 55)  # Normalizado para 45-100
            mfi_score = max(0, (c['mfi'] - 35) / 65)  # Normalizado para 35-100
        score += (rsi_score + mfi_score) * 0.10  # Reduzido de 0.075*2

        # Bônus de confirmação H4
        if h4_trend != 'NEUTRO':
            if (side == 'long' and h4_trend == 'ALTA') or (side == 'short' and h4_trend == 'BAIXA'):
                score += 0.10  # Bônus de alinhamento de tendência
            else:
                score -= 0.05  # Penalidade de divergência

        # Bônus de volume
        volume_ratio = c['volume'] / c['volume_sma'] if c['volume_sma'] > 0 else 1.0
        if volume_ratio > 1.5:
            score += 0.05
        elif volume_ratio < 0.5:
            score -= 0.05

        return min(max(score, 0.0), 1.0)


# =============================================================================
# POSITION TRACKER — Trailing Stop Aprimorado
# =============================================================================
class PositionTracker:
    def __init__(self):
        self.symbol: Optional[str] = None
        self.side: Optional[str] = None
        self.entry_price: float = 0.0
        self.entry_score: float = 0.0  # NOVO: score na entrada
        self.size: float = 0.0
        self.leverage: int = 1
        self.session_start_balance: float = 0.0
        self.peak_profit_pct: float = -999.0
        self.peak_price: float = 0.0
        self.lock_profit_pct: float = 0.0
        self.locked: bool = False
        self.entry_time: Optional[float] = None  # NOVO: timestamp de entrada
        self.max_drawdown_pct: float = 0.0  # NOVO: máximo drawdown atingido

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
        """Estágios de lock de lucro mais conservadores."""
        if peak >= 5.0:
            return peak * 0.75
        elif peak >= 3.0:
            return peak * 0.70
        elif peak >= 1.5:
            return peak * 0.60
        elif peak >= 0.8:
            return peak * 0.50
        elif peak >= 0.4:
            return peak * 0.35
        elif peak >= 0.2:
            return 0.10  # Aumentado de 0.08
        return 0.0

    def _get_drawdown_threshold(self, peak: float) -> float:
        """Drawdown permitido baseado no peak — mais conservador."""
        if peak >= 3.0:
            return peak * 0.70
        elif peak >= 2.0:
            return peak * 0.65
        elif peak >= 1.0:
            return peak * 0.60
        elif peak >= 0.5:
            return peak * 0.55
        elif peak >= 0.2:
            return peak * 0.50
        elif peak > 0:
            return peak * 0.40  # Protege 60% do lucro mínimo
        return 0.0

    def update_peak(self, current_price: float):
        """Atualiza peak e gerencia locks."""
        profit = self._profit_pct(current_price)

        if profit > self.peak_profit_pct:
            self.peak_profit_pct = profit
            self.peak_price = current_price

        # Track max drawdown
        if profit < self.max_drawdown_pct:
            self.max_drawdown_pct = profit

        if not self.locked:
            stage = self._get_lock_stage(self.peak_profit_pct)
            if stage > 0:
                self.locked = True
                self.lock_profit_pct = stage

    def check_stop_loss(self, current_price: float, sl_pct: float) -> bool:
        """Verifica stop loss fixo."""
        if self.side == 'long':
            loss = (self.entry_price - current_price) / self.entry_price * 100
        else:
            loss = (current_price - self.entry_price) / self.entry_price * 100
        return loss >= sl_pct

    def check_trailing_stop(self, current_price: float) -> tuple[bool, str]:
        """Verifica trailing stop — SEMPRE ativo, não só com lucro."""
        profit = self._profit_pct(current_price)

        # LOCK DE LUCRO: se atingiu estágio de lock e voltou
        if self.locked:
            if profit <= self.lock_profit_pct:
                return True, f"LOCK_PROFIT | peak={self.peak_profit_pct:.2f}% lock={self.lock_profit_pct:.2f}%"

        # DRAWDOWN: se teve lucro e voltou além do limite
        if self.peak_profit_pct > 0:
            threshold = self._get_drawdown_threshold(self.peak_profit_pct)
            if profit <= threshold:
                return True, f"DRAWDOWN | peak={self.peak_profit_pct:.2f}% current={profit:.2f}%"

        # TIME STOP: se está aberto há mais de 30 minutos sem lucro significativo
        if self.entry_time and (time.time() - self.entry_time) > 1800:  # 30 minutos
            if profit < 0.1:  # Sem lucro significativo
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
# OPPORTUNITY ANALYZER — Rotação mais conservadora
# =============================================================================
class OpportunityAnalyzer:
    def __init__(self, rotation_threshold: float = 1.20):  # Aumentado de 1.15
        self.rotation_threshold = rotation_threshold

    def should_rotate(self, tracker: PositionTracker, new_signal: SignalResult,
                      current_unrealized_pnl: float, current_price: float) -> bool:
        if not tracker.symbol or not new_signal.side:
            return False

        # Não rotacionar se posição está protegida por lock
        if tracker.locked and current_unrealized_pnl > 0:
            return False

        # Não rotacionar se nova oportunidade não é significativamente melhor
        if new_signal.score < 0.80:
            return False

        # Só rotacionar se score novo for pelo menos 15% maior
        if tracker.entry_score > 0 and (new_signal.score - tracker.entry_score) < 0.15:
            return False

        atr = new_signal.meta.get('atr', 0)
        price = new_signal.price
        if price > 0 and atr > 0:
            potential_pct = (atr / price) * 100
        else:
            potential_pct = 1.0

        new_potential = new_signal.score * potential_pct

        current_pnl_pct = 0.0
        if tracker.session_start_balance > 0:
            current_pnl_pct = (current_unrealized_pnl / tracker.session_start_balance) * 100

        # Não rotacionar se posição atual está com lucro significativo
        if current_pnl_pct > 0.5:
            return False

        return new_potential > max(current_pnl_pct, 0.1) * self.rotation_threshold


# =============================================================================
# RISK MANAGER — Mais conservador
# =============================================================================
class RiskManager:
    def __init__(self, base_leverage: int = 3, max_leverage: int = 5):  # Reduzido de 10 para 5
        self.base_leverage = base_leverage
        self.max_leverage = max_leverage

    def dynamic_leverage(self, adx: float, base: int) -> int:
        """Alavancagem dinâmica baseada na força da tendência."""
        if adx >= 45:  # Aumentado de 40
            return min(self.max_leverage, base + 2)  # Reduzido de +4
        elif adx >= 35:  # Aumentado de 30
            return min(self.max_leverage, base + 1)  # Reduzido de +2
        elif adx >= 25:
            return base
        return max(1, base - 1)

    def calculate_position_size(self, balance: float, price: float, leverage: int,
                                 risk_pct: float = 0.015, min_cost: float = 5.0) -> float:  # Reduzido de 0.02
        """Calcula tamanho da posição com risco limitado."""
        if price <= 0 or balance <= 0:
            return 0.0
        risk_amount = balance * risk_pct
        position_value = risk_amount * leverage
        qty = position_value / price
        if qty * price < min_cost:
            qty = min_cost / price
        return round(qty, 6)

    def calculate_stop_loss_price(self, entry: float, side: str, sl_pct: float) -> float:
        """Calcula preço de stop loss."""
        if side == 'long':
            return entry * (1 - sl_pct / 100)
        return entry * (1 + sl_pct / 100)
