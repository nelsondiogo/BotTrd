"""
Estratégia de trading baseada em EMA Crossover + RSI.
Determina a direção do trade (Long, Short ou Neutro).
"""

from enum import Enum
from typing import Optional
import pandas as pd
import numpy as np

from config import BotConfig
from logger_config import logger


class Signal(Enum):
    """Sinais possíveis da análise técnica."""
    LONG  = "LONG"
    SHORT = "SHORT"
    NONE  = "NONE"


class TechnicalStrategy:
    """
    Estratégia combinada de EMA Crossover e RSI.
    
    Regras de entrada:
    - LONG:  EMA rápida cruza acima da EMA lenta E RSI < oversold threshold
    - SHORT: EMA rápida cruza abaixo da EMA lenta E RSI > overbought threshold
    
    Para confirmação mais conservadora, ambos os indicadores devem alinhar.
    """

    def __init__(self, config: BotConfig):
        self.config = config

    def calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        """
        Calcula a Média Móvel Exponencial.
        
        Args:
            series: Série de preços
            period: Período da EMA
            
        Returns:
            Série com valores da EMA
        """
        return series.ewm(span=period, adjust=False).mean()

    def calculate_rsi(self, series: pd.Series, period: int) -> pd.Series:
        """
        Calcula o Índice de Força Relativa (RSI).
        
        Args:
            series: Série de preços de fechamento
            period: Período do RSI
            
        Returns:
            Série com valores do RSI (0-100)
        """
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=period - 1, adjust=False).mean()

        # Evita divisão por zero
        rs = avg_gain / avg_loss.replace(0, np.finfo(float).eps)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def analyze(self, df: pd.DataFrame) -> tuple[Signal, dict]:
        """
        Analisa o mercado e retorna o sinal de trading.
        
        Args:
            df: DataFrame com dados OHLCV
            
        Returns:
            Tupla (Signal, dict com métricas dos indicadores)
        """
        if len(df) < max(self.config.ema_slow_period, self.config.rsi_period) + 5:
            logger.warning("Dados insuficientes para análise")
            return Signal.NONE, {}

        close = df["close"]

        # Calcula indicadores
        ema_fast = self.calculate_ema(close, self.config.ema_fast_period)
        ema_slow = self.calculate_ema(close, self.config.ema_slow_period)
        rsi = self.calculate_rsi(close, self.config.rsi_period)

        # Valores atuais e anteriores (para detectar cruzamento)
        ema_fast_now  = ema_fast.iloc[-1]
        ema_fast_prev = ema_fast.iloc[-2]
        ema_slow_now  = ema_slow.iloc[-1]
        ema_slow_prev = ema_slow.iloc[-2]
        rsi_now       = rsi.iloc[-1]
        current_price = close.iloc[-1]

        # Detecta cruzamento de EMAs
        # Cruzamento de alta: fast estava abaixo e agora está acima
        bullish_cross = (ema_fast_prev < ema_slow_prev) and (ema_fast_now > ema_slow_now)
        # Cruzamento de baixa: fast estava acima e agora está abaixo
        bearish_cross = (ema_fast_prev > ema_slow_prev) and (ema_fast_now < ema_slow_now)

        # Tendência das EMAs (para contexto adicional)
        bullish_trend = ema_fast_now > ema_slow_now
        bearish_trend = ema_fast_now < ema_slow_now

        metrics = {
            "price":          current_price,
            "ema_fast":       round(ema_fast_now, 4),
            "ema_slow":       round(ema_slow_now, 4),
            "rsi":            round(rsi_now, 2),
            "bullish_cross":  bullish_cross,
            "bearish_cross":  bearish_cross,
            "bullish_trend":  bullish_trend,
            "bearish_trend":  bearish_trend,
        }

        self._log_indicators(metrics)

        # --- Lógica de Sinal ---
        # LONG: Cruzamento de alta E RSI não em sobrecompra
        if bullish_cross and rsi_now < self.config.rsi_overbought:
            logger.info(
                f"🟢 Sinal LONG detectado | "
                f"EMA Cross Up | RSI: {rsi_now:.1f}"
            )
            return Signal.LONG, metrics

        # SHORT: Cruzamento de baixa E RSI não em sobrevenda
        if bearish_cross and rsi_now > self.config.rsi_oversold:
            logger.info(
                f"🔴 Sinal SHORT detectado | "
                f"EMA Cross Down | RSI: {rsi_now:.1f}"
            )
            return Signal.SHORT, metrics

        logger.debug(
            f"⏸️  Sem sinal | RSI: {rsi_now:.1f} | "
            f"Trend: {'BULL' if bullish_trend else 'BEAR'}"
        )
        return Signal.NONE, metrics

    def _log_indicators(self, metrics: dict) -> None:
        """Exibe os indicadores técnicos no log."""
        logger.debug(
            f"📈 Indicadores | "
            f"Preço: {metrics['price']:.4f} | "
            f"EMA{self.config.ema_fast_period}: {metrics['ema_fast']:.4f} | "
            f"EMA{self.config.ema_slow_period}: {metrics['ema_slow']:.4f} | "
            f"RSI: {metrics['rsi']:.2f}"
        )
