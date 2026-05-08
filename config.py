"""
Carrega e valida todas as configurações do ambiente.
Centraliza os parâmetros do bot em um único lugar.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
from logger_config import logger

# Carrega variáveis do arquivo .env (se existir)
load_dotenv()


@dataclass
class BotConfig:
    """
    Dataclass com todas as configurações do bot.
    Os valores são carregados das variáveis de ambiente.
    """
    # --- Credenciais e Exchange ---
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("API_SECRET", ""))
    exchange_id: str = field(
        default_factory=lambda: os.getenv("EXCHANGE_ID", "binance").lower()
    )
    testnet: bool = field(
        default_factory=lambda: os.getenv("TESTNET", "false").lower() == "true"
    )

    # --- Parâmetros de Trading ---
    symbol: str = field(
        default_factory=lambda: os.getenv("SYMBOL", "BTC/USDT:USDT")
    )
    timeframe: str = field(
        default_factory=lambda: os.getenv("TIMEFRAME", "5m")
    )
    leverage: int = field(
        default_factory=lambda: int(os.getenv("LEVERAGE", "5"))
    )
    position_size_percent: float = field(
        default_factory=lambda: float(os.getenv("POSITION_SIZE_PERCENT", "2.0"))
    )

    # --- Gestão de Risco ---
    # Stop Loss padrão quando não há lucro acumulado (% do capital)
    initial_stop_percent: float = field(
        default_factory=lambda: float(os.getenv("INITIAL_STOP_PERCENT", "0.5"))
    )
    # Stop Loss quando há lucro (% do lucro acumulado)
    profit_stop_percent: float = field(
        default_factory=lambda: float(os.getenv("PROFIT_STOP_PERCENT", "1.0"))
    )
    # Lucro mínimo em USDT para ativar a regra de 1% do lucro
    min_profit_to_use_rule: float = field(
        default_factory=lambda: float(os.getenv("MIN_PROFIT_TO_USE_RULE", "5.0"))
    )

    # --- Timing ---
    cooldown_seconds: int = field(
        default_factory=lambda: int(os.getenv("COOLDOWN_SECONDS", "30"))
    )
    loop_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("LOOP_INTERVAL_SECONDS", "10"))
    )

    # --- Parâmetros Técnicos da Estratégia ---
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    # Número de candles para buscar na API
    candles_limit: int = 100

    def validate(self) -> bool:
        """
        Valida as configurações críticas antes de iniciar o bot.
        
        Returns:
            True se válido, levanta ValueError se inválido
        """
        errors = []

        if not self.api_key:
            errors.append("API_KEY não configurada")
        if not self.api_secret:
            errors.append("API_SECRET não configurada")
        if self.exchange_id not in ("binance", "bybit"):
            errors.append(f"EXCHANGE_ID inválido: {self.exchange_id}. Use 'binance' ou 'bybit'")
        if not (1 <= self.leverage <= 125):
            errors.append(f"LEVERAGE deve ser entre 1 e 125, recebido: {self.leverage}")
        if not (0.1 <= self.position_size_percent <= 100):
            errors.append(f"POSITION_SIZE_PERCENT inválido: {self.position_size_percent}")
        if self.initial_stop_percent <= 0:
            errors.append("INITIAL_STOP_PERCENT deve ser positivo")
        if self.profit_stop_percent <= 0:
            errors.append("PROFIT_STOP_PERCENT deve ser positivo")

        if errors:
            for error in errors:
                logger.error(f"Configuração inválida: {error}")
            raise ValueError(f"Erros de configuração: {'; '.join(errors)}")

        logger.info("✅ Configurações validadas com sucesso")
        self._log_config()
        return True

    def _log_config(self) -> None:
        """Exibe as configurações no log (sem dados sensíveis)."""
        logger.info("=" * 60)
        logger.info("📋 CONFIGURAÇÕES DO BOT")
        logger.info("=" * 60)
        logger.info(f"  Exchange:          {self.exchange_id.upper()}")
        logger.info(f"  Testnet:           {self.testnet}")
        logger.info(f"  Symbol:            {self.symbol}")
        logger.info(f"  Timeframe:         {self.timeframe}")
        logger.info(f"  Alavancagem:       {self.leverage}x")
        logger.info(f"  Tamanho posição:   {self.position_size_percent}% do capital")
        logger.info(f"  Stop inicial:      {self.initial_stop_percent}% do capital")
        logger.info(f"  Stop por lucro:    {self.profit_stop_percent}% do lucro acumulado")
        logger.info(f"  Lucro mín. regra:  ${self.min_profit_to_use_rule:.2f}")
        logger.info(f"  Cooldown:          {self.cooldown_seconds}s")
        logger.info("=" * 60)


# Instância global de configuração
config = BotConfig()
