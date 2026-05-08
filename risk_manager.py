"""
Gerenciador de risco e preservação de lucro.
Implementa a lógica central de stop loss baseado no lucro acumulado.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import BotConfig
from logger_config import logger


@dataclass
class SessionStats:
    """
    Estatísticas da sessão de trading atual.
    Rastreia lucros, perdas e métricas de performance.
    """
    # Saldo inicial da sessão
    initial_balance: float = 0.0
    # Lucro acumulado líquido (após taxas)
    accumulated_profit: float = 0.0
    # Número de trades
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    # Taxas totais pagas
    total_fees_paid: float = 0.0
    # Maior lucro em um único trade
    best_trade: float = 0.0
    # Maior perda em um único trade
    worst_trade: float = 0.0
    # Timestamp de início
    start_time: datetime = field(default_factory=datetime.now)

    @property
    def win_rate(self) -> float:
        """Taxa de acerto em %."""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    @property
    def profit_percent(self) -> float:
        """Lucro acumulado em % do capital inicial."""
        if self.initial_balance == 0:
            return 0.0
        return (self.accumulated_profit / self.initial_balance) * 100

    def log_summary(self) -> None:
        """Exibe resumo completo da sessão no log."""
        elapsed = datetime.now() - self.start_time
        hours = int(elapsed.total_seconds() // 3600)
        minutes = int((elapsed.total_seconds() % 3600) // 60)

        logger.info("=" * 60)
        logger.info("📊 RESUMO DA SESSÃO")
        logger.info("=" * 60)
        logger.info(f"  Duração:           {hours}h {minutes}m")
        logger.info(f"  Capital inicial:   ${self.initial_balance:.2f}")
        logger.info(f"  Lucro acumulado:   ${self.accumulated_profit:.4f} "
                   f"({self.profit_percent:.2f}%)")
        logger.info(f"  Total de trades:   {self.total_trades}")
        logger.info(f"  Ganhos/Perdas:     {self.winning_trades}W / "
                   f"{self.losing_trades}L")
        logger.info(f"  Win Rate:          {self.win_rate:.1f}%")
        logger.info(f"  Taxas pagas:       ${self.total_fees_paid:.4f}")
        logger.info(f"  Melhor trade:      ${self.best_trade:.4f}")
        logger.info(f"  Pior trade:        ${self.worst_trade:.4f}")
        logger.info("=" * 60)


class RiskManager:
    """
    Gerencia o risco de cada posição baseado no lucro acumulado da sessão.
    
    Lógica principal:
    - Se lucro acumulado >= min_profit: Stop = 1% do lucro acumulado
    - Se lucro acumulado < min_profit: Stop = 0.5% do capital total
    """

    def __init__(self, config: BotConfig, initial_balance: float):
        self.config = config
        self.stats = SessionStats(initial_balance=initial_balance)
        logger.info(
            f"🛡️  Risk Manager iniciado | "
            f"Capital inicial: ${initial_balance:.2f}"
        )

    def calculate_stop_loss_amount(self, total_balance: float) -> float:
        """
        Calcula o valor máximo de perda permitido para a posição atual.
        
        Args:
            total_balance: Saldo atual da conta em USDT
            
        Returns:
            Valor máximo de perda em USDT (positivo)
        """
        accumulated = self.stats.accumulated_profit

        # Regra 1: Há lucro suficiente acumulado -> usa % do lucro
        if accumulated >= self.config.min_profit_to_use_rule:
            max_loss = accumulated * (self.config.profit_stop_percent / 100)
            rule_used = f"Regra do lucro ({self.config.profit_stop_percent}% de ${accumulated:.2f})"
        else:
            # Regra 2: Sem lucro suficiente -> usa % do capital como proteção
            max_loss = total_balance * (self.config.initial_stop_percent / 100)
            rule_used = f"Stop padrão ({self.config.initial_stop_percent}% de ${total_balance:.2f})"

        logger.debug(
            f"🛡️  Stop Loss calculado: ${max_loss:.4f} | {rule_used}"
        )
        return max_loss

    def calculate_position_size(self, balance: float) -> float:
        """
        Calcula o tamanho da posição baseado no capital disponível.
        
        Args:
            balance: Saldo livre em USDT
            
        Returns:
            Tamanho da posição em USDT
        """
        size = balance * (self.config.position_size_percent / 100)
        # Arredonda para 2 casas decimais
        size = round(size, 2)

        logger.info(
            f"💰 Tamanho da posição: ${size:.2f} "
            f"({self.config.position_size_percent}% de ${balance:.2f})"
        )
        return size

    def should_close_position(
        self,
        unrealized_pnl: float,
        fees_to_close: float,
        total_balance: float
    ) -> tuple[bool, str]:
        """
        Verifica se a posição deve ser fechada por stop loss.
        
        Args:
            unrealized_pnl: PnL não realizado atual (pode ser negativo)
            fees_to_close: Taxa estimada para fechar a posição
            total_balance: Saldo atual da conta
            
        Returns:
            Tupla (bool: deve fechar, str: motivo)
        """
        # PnL líquido considerando taxa de fechamento
        net_pnl = unrealized_pnl - fees_to_close
        max_loss = self.calculate_stop_loss_amount(total_balance)

        # Verifica se a perda (líquida) atingiu o limite
        if net_pnl < 0 and abs(net_pnl) >= max_loss:
            reason = (
                f"Stop Loss atingido | "
                f"Perda líquida: ${net_pnl:.4f} | "
                f"Limite: ${max_loss:.4f}"
            )
            return True, reason

        return False, ""

    def record_trade_result(
        self,
        gross_pnl: float,
        fees_paid: float
    ) -> None:
        """
        Registra o resultado de um trade finalizado.
        
        Args:
            gross_pnl: Lucro/prejuízo bruto do trade
            fees_paid: Taxas pagas (abertura + fechamento)
        """
        net_pnl = gross_pnl - fees_paid
        self.stats.accumulated_profit += net_pnl
        self.stats.total_trades += 1
        self.stats.total_fees_paid += fees_paid

        if net_pnl > 0:
            self.stats.winning_trades += 1
        else:
            self.stats.losing_trades += 1

        # Atualiza melhor/pior trade
        if net_pnl > self.stats.best_trade:
            self.stats.best_trade = net_pnl
        if net_pnl < self.stats.worst_trade:
            self.stats.worst_trade = net_pnl

        emoji = "✅" if net_pnl >= 0 else "❌"
        logger.info(
            f"{emoji} Trade finalizado | "
            f"PnL Bruto: ${gross_pnl:.4f} | "
            f"Taxas: ${fees_paid:.4f} | "
            f"PnL Líquido: ${net_pnl:.4f} | "
            f"Lucro acumulado: ${self.stats.accumulated_profit:.4f}"
        )

    def log_risk_status(self, total_balance: float) -> None:
        """Exibe o status atual do risco no log."""
        max_loss = self.calculate_stop_loss_amount(total_balance)
        accumulated = self.stats.accumulated_profit
        rule = "LUCRO" if accumulated >= self.config.min_profit_to_use_rule else "PADRÃO"

        logger.info(
            f"🛡️  Status de Risco | "
            f"Lucro acumulado: ${accumulated:.4f} | "
            f"Stop máx.: ${max_loss:.4f} | "
            f"Regra ativa: {rule}"
        )
