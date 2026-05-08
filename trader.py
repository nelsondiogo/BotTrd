"""
Orquestrador principal do bot de trading.
Integra exchange, estratégia e gestão de risco em um fluxo coeso.
"""

import time
from enum import Enum
from typing import Optional
from datetime import datetime

from config import BotConfig
from exchange_client import ExchangeClient
from strategy import TechnicalStrategy, Signal
from risk_manager import RiskManager
from logger_config import logger


class BotState(Enum):
    """Estados possíveis do bot."""
    ANALYZING   = "ANALYZING"    # Analisando mercado
    IN_POSITION = "IN_POSITION"  # Com posição aberta
    COOLDOWN    = "COOLDOWN"     # Aguardando após fechar posição


class TradingBot:
    """
    Bot de trading com foco em preservação de lucro.
    
    Fluxo:
    1. ANALYZING: Analisa mercado e aguarda sinal
    2. IN_POSITION: Monitora posição e aplica stop loss dinâmico
    3. COOLDOWN: Aguarda período de resfriamento após fechar posição
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self.state = BotState.ANALYZING
        self.exchange: Optional[ExchangeClient] = None
        self.strategy: Optional[TechnicalStrategy] = None
        self.risk_manager: Optional[RiskManager] = None

        # Dados da posição atual
        self.current_signal: Optional[Signal] = None
        self.entry_time: Optional[datetime] = None
        self.entry_price: float = 0.0
        self.position_size_usdt: float = 0.0
        self.cooldown_until: float = 0.0

        # Contador de ciclos para logs periódicos
        self.cycle_count: int = 0

    def initialize(self) -> bool:
        """
        Inicializa todos os componentes do bot.
        
        Returns:
            True se inicializado com sucesso
        """
        try:
            logger.info("🚀 Iniciando Trading Bot...")

            # Conecta à exchange
            self.exchange = ExchangeClient(self.config)

            # Obtém saldo inicial
            balance = self.exchange.fetch_balance()
            initial_balance = balance["total"]

            if initial_balance < 10:
                raise ValueError(
                    f"Saldo insuficiente: ${initial_balance:.2f}. "
                    f"Mínimo recomendado: $10.00"
                )

            logger.info(f"💵 Saldo inicial: ${initial_balance:.2f} USDT")

            # Inicializa estratégia e gerenciador de risco
            self.strategy = TechnicalStrategy(self.config)
            self.risk_manager = RiskManager(self.config, initial_balance)

            logger.info("✅ Bot inicializado com sucesso!")
            return True

        except Exception as e:
            logger.critical(f"❌ Falha na inicialização: {e}")
            return False

    def run(self) -> None:
        """Loop principal do bot."""
        if not self.initialize():
            return

        logger.info("🔄 Iniciando loop principal...")
        logger.info(
            f"Verificando {self.config.symbol} a cada "
            f"{self.config.loop_interval_seconds}s"
        )

        while True:
            try:
                self.cycle_count += 1
                self._execute_cycle()
                time.sleep(self.config.loop_interval_seconds)

            except KeyboardInterrupt:
                logger.info("\n⛔ Bot interrompido pelo usuário")
                self._emergency_close()
                self.risk_manager.stats.log_summary()
                break

            except ccxt_exception_handler() as e:
                logger.error(f"Erro de exchange no loop: {e}")
                time.sleep(30)  # Aguarda mais tempo em caso de erro

            except Exception as e:
                logger.error(f"Erro inesperado no loop: {e}", exc_info=True)
                time.sleep(self.config.loop_interval_seconds * 2)

    def _execute_cycle(self) -> None:
        """Executa um ciclo completo do bot baseado no estado atual."""

        # Log de status a cada 10 ciclos
        if self.cycle_count % 10 == 0:
            self._log_status()

        if self.state == BotState.ANALYZING:
            self._handle_analyzing()

        elif self.state == BotState.IN_POSITION:
            self._handle_in_position()

        elif self.state == BotState.COOLDOWN:
            self._handle_cooldown()

    def _handle_analyzing(self) -> None:
        """
        Estado ANALYZING: busca dados e analisa mercado.
        Abre posição se encontrar sinal válido.
        """
        try:
            # Busca candles para análise
            df = self.exchange.fetch_ohlcv(self.config.candles_limit)
            signal, metrics = self.strategy.analyze(df)

            if signal == Signal.NONE:
                return  # Aguarda próximo ciclo

            # Sinal encontrado! Verifica se há posição aberta (segurança)
            existing_position = self.exchange.fetch_position()
            if existing_position:
                logger.warning(
                    "⚠️  Posição existente detectada sem estar em IN_POSITION. "
                    "Sincronizando estado..."
                )
                self.state = BotState.IN_POSITION
                self.current_signal = signal
                return

            # Obtém saldo e calcula tamanho da posição
            balance = self.exchange.fetch_balance()
            position_size = self.risk_manager.calculate_position_size(
                balance["free"]
            )

            # Define side da ordem
            order_side = "buy" if signal == Signal.LONG else "sell"
            signal_emoji = "🟢" if signal == Signal.LONG else "🔴"

            logger.info(
                f"{signal_emoji} Abrindo posição {signal.value} | "
                f"Preço: {metrics.get('price', 0):.4f} | "
                f"Tamanho: ${position_size:.2f}"
            )

            # Executa ordem a mercado
            order = self.exchange.create_market_order(order_side, position_size)

            if order:
                self.current_signal = signal
                self.entry_time = datetime.now()
                self.position_size_usdt = position_size
                self.state = BotState.IN_POSITION

                # Log de risco
                self.risk_manager.log_risk_status(balance["total"])
            else:
                logger.error("Falha ao abrir posição, permanecendo em ANALYZING")

        except Exception as e:
            logger.error(f"Erro em ANALYZING: {e}", exc_info=True)

    def _handle_in_position(self) -> None:
        """
        Estado IN_POSITION: monitora posição aberta e aplica stop loss.
        """
        try:
            position = self.exchange.fetch_position()

            # Verifica se posição ainda existe
            if not position:
                logger.warning(
                    "⚠️  Posição não encontrada (pode ter sido fechada externamente). "
                    "Voltando para ANALYZING..."
                )
                self.state = BotState.ANALYZING
                return

            # Dados da posição atual
            unrealized_pnl = position["unrealized_pnl"]
            notional = position.get("notional", self.position_size_usdt)
            entry_price = position["entry_price"]

            # Calcula taxa estimada para fechar posição
            fees_to_close = self.exchange.calculate_fee(abs(notional))

            # Obtém saldo atual para cálculo do stop
            balance = self.exchange.fetch_balance()
            total_balance = balance["total"]

            # Verifica condição de stop loss
            should_close, reason = self.risk_manager.should_close_position(
                unrealized_pnl,
                fees_to_close,
                total_balance
            )

            # Log de monitoramento
            pnl_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
            net_pnl = unrealized_pnl - fees_to_close
            logger.info(
                f"{pnl_emoji} Monitorando | "
                f"Entrada: {entry_price:.4f} | "
                f"PnL: ${unrealized_pnl:.4f} | "
                f"PnL Líq.: ${net_pnl:.4f} | "
                f"Taxa est.: ${fees_to_close:.4f}"
            )

            if should_close:
                logger.warning(f"🛑 {reason}")
                self._close_and_record(position, fees_to_close)

        except Exception as e:
            logger.error(f"Erro em IN_POSITION: {e}", exc_info=True)

    def _handle_cooldown(self) -> None:
        """
        Estado COOLDOWN: aguarda período definido antes de nova análise.
        """
        remaining = self.cooldown_until - time.time()

        if remaining > 0:
            logger.debug(f"⏳ Cooldown: {remaining:.0f}s restantes")
        else:
            logger.info("✅ Cooldown finalizado. Retomando análise...")
            self.state = BotState.ANALYZING

    def _close_and_record(
        self,
        position: dict,
        fees_to_close: float
    ) -> None:
        """
        Fecha a posição e registra o resultado no risk manager.
        
        Args:
            position: Dados da posição a fechar
            fees_to_close: Taxa estimada de fechamento
        """
        # Calcula PnL bruto antes de fechar
        gross_pnl = position["unrealized_pnl"]

        # Fecha a posição
        close_order = self.exchange.close_position(position)

        if close_order:
            # Calcula taxas totais (abertura já foi paga, agora fechamento)
            # Estimamos como metade do calculate_fee (que já inclui abertura+fechamento)
            total_fees = fees_to_close

            # Registra resultado
            self.risk_manager.record_trade_result(gross_pnl, total_fees)

            # Exibe resumo da sessão a cada trade
            self.risk_manager.stats.log_summary()

            # Inicia cooldown
            self.cooldown_until = time.time() + self.config.cooldown_seconds
            self.state = BotState.COOLDOWN

            logger.info(
                f"⏳ Iniciando cooldown de {self.config.cooldown_seconds}s..."
            )
        else:
            logger.error(
                "❌ Falha ao fechar posição! "
                "Tentará novamente no próximo ciclo."
            )

    def _emergency_close(self) -> None:
        """Tenta fechar posição aberta em caso de shutdown do bot."""
        if self.state != BotState.IN_POSITION:
            return

        logger.warning("🚨 Tentando fechar posição por shutdown de emergência...")
        try:
            position = self.exchange.fetch_position()
            if position:
                self.exchange.close_position(position)
                logger.info("✅ Posição fechada com sucesso")
        except Exception as e:
            logger.error(f"❌ Falha ao fechar posição de emergência: {e}")

    def _log_status(self) -> None:
        """Log periódico do status do bot."""
        state_emojis = {
            BotState.ANALYZING:   "🔍",
            BotState.IN_POSITION: "📈",
            BotState.COOLDOWN:    "⏳",
        }

        try:
            balance = self.exchange.fetch_balance()
            accumulated = self.risk_manager.stats.accumulated_profit

            logger.info(
                f"{state_emojis[self.state]} Status | "
                f"Estado: {self.state.value} | "
                f"Saldo: ${balance['total']:.2f} | "
                f"Lucro sessão: ${accumulated:.4f} | "
                f"Trades: {self.risk_manager.stats.total_trades}"
            )
        except Exception:
            pass  # Log de status não é crítico


def ccxt_exception_handler():
    """Retorna as exceções CCXT para tratamento no loop."""
    import ccxt
    return (ccxt.NetworkError, ccxt.ExchangeError, ccxt.ExchangeNotAvailable)
