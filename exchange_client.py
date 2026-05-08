"""
Gerencia a conexão com a exchange via CCXT.
Abstrai todas as chamadas de API com tratamento de erros robusto.
"""

import time
from typing import Optional
import ccxt
import pandas as pd

from config import BotConfig
from logger_config import logger


class ExchangeClient:
    """
    Cliente de exchange com reconexão automática e tratamento de erros.
    Suporta Binance Futures e Bybit.
    """

    # Taxa padrão de taker para futuros (usada no cálculo de lucro líquido)
    TAKER_FEES = {
        "binance": 0.0004,  # 0.04%
        "bybit":   0.0006,  # 0.06%
    }
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # segundos

    def __init__(self, config: BotConfig):
        self.config = config
        self.exchange: Optional[ccxt.Exchange] = None
        self.taker_fee: float = self.TAKER_FEES.get(config.exchange_id, 0.0006)
        self._connect()

    def _connect(self) -> None:
        """Inicializa a conexão com a exchange e configura alavancagem."""
        logger.info(f"🔌 Conectando à {self.config.exchange_id.upper()}...")

        exchange_class = getattr(ccxt, self.config.exchange_id)

        params = {
            "apiKey": self.config.api_key,
            "secret": self.config.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }

        # Configurações específicas por exchange
        if self.config.exchange_id == "bybit":
            params["options"]["defaultType"] = "linear"

        self.exchange = exchange_class(params)

        # Ativa testnet se configurado
        if self.config.testnet:
            logger.warning("⚠️  MODO TESTNET ATIVO - Usando dados simulados")
            self.exchange.set_sandbox_mode(True)

        # Carrega mercados disponíveis
        self.exchange.load_markets()
        logger.info(f"✅ Conectado! Mercados carregados.")

        # Configura alavancagem
        self._set_leverage()

    def _set_leverage(self) -> None:
        """Define a alavancagem para o símbolo configurado."""
        try:
            self.exchange.set_leverage(
                self.config.leverage,
                self.config.symbol
            )
            logger.info(
                f"⚡ Alavancagem configurada: {self.config.leverage}x "
                f"para {self.config.symbol}"
            )
        except Exception as e:
            logger.warning(f"Não foi possível configurar alavancagem: {e}")

    def _retry(self, func, *args, **kwargs):
        """
        Executa uma função com retry automático em caso de falha de rede.
        
        Args:
            func: Função a executar
            *args, **kwargs: Argumentos da função
            
        Returns:
            Resultado da função
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except ccxt.NetworkError as e:
                logger.warning(
                    f"Erro de rede (tentativa {attempt}/{self.MAX_RETRIES}): {e}"
                )
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY * attempt)
                else:
                    raise
            except ccxt.ExchangeError as e:
                logger.error(f"Erro da exchange: {e}")
                raise
            except Exception as e:
                logger.error(f"Erro inesperado: {e}")
                raise

    def fetch_balance(self) -> dict:
        """
        Busca o saldo atual da conta.
        
        Returns:
            Dicionário com informações de saldo
        """
        balance = self._retry(self.exchange.fetch_balance)
        usdt_balance = balance.get("USDT", {})
        return {
            "total": float(usdt_balance.get("total", 0)),
            "free": float(usdt_balance.get("free", 0)),
            "used": float(usdt_balance.get("used", 0)),
        }

    def fetch_ohlcv(self, limit: int = 100) -> pd.DataFrame:
        """
        Busca dados OHLCV (velas) da exchange.
        
        Args:
            limit: Número de velas a buscar
            
        Returns:
            DataFrame com colunas: timestamp, open, high, low, close, volume
        """
        raw = self._retry(
            self.exchange.fetch_ohlcv,
            self.config.symbol,
            self.config.timeframe,
            limit=limit
        )

        if not raw:
            raise ValueError("Sem dados OHLCV retornados pela exchange")

        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.astype({
            "open": float, "high": float,
            "low": float, "close": float, "volume": float
        })

        logger.debug(
            f"📊 {len(df)} candles carregados | "
            f"Último fechamento: {df['close'].iloc[-1]:.4f}"
        )
        return df

    def fetch_ticker(self) -> dict:
        """
        Busca o ticker atual (preço em tempo real).
        
        Returns:
            Dicionário com dados do ticker
        """
        ticker = self._retry(self.exchange.fetch_ticker, self.config.symbol)
        return {
            "last": float(ticker.get("last", 0)),
            "bid": float(ticker.get("bid", 0)),
            "ask": float(ticker.get("ask", 0)),
        }

    def fetch_position(self) -> Optional[dict]:
        """
        Busca a posição aberta atual para o símbolo configurado.
        
        Returns:
            Dicionário com dados da posição ou None se não houver posição
        """
        positions = self._retry(
            self.exchange.fetch_positions,
            [self.config.symbol]
        )

        for pos in positions:
            contracts = float(pos.get("contracts", 0) or 0)
            if contracts > 0:
                return {
                    "side": pos.get("side"),           # "long" ou "short"
                    "size": contracts,                  # Quantidade em contratos
                    "entry_price": float(pos.get("entryPrice", 0) or 0),
                    "unrealized_pnl": float(pos.get("unrealizedPnl", 0) or 0),
                    "notional": float(pos.get("notional", 0) or 0),
                    "leverage": float(pos.get("leverage", 1) or 1),
                    "liquidation_price": float(
                        pos.get("liquidationPrice", 0) or 0
                    ),
                }
        return None

    def create_market_order(
        self,
        side: str,
        size_usdt: float
    ) -> Optional[dict]:
        """
        Cria uma ordem a mercado.
        
        Args:
            side: "buy" para Long, "sell" para Short
            size_usdt: Tamanho da posição em USDT
            
        Returns:
            Dados da ordem criada ou None em caso de erro
        """
        try:
            ticker = self.fetch_ticker()
            current_price = ticker["last"]

            if current_price <= 0:
                raise ValueError("Preço inválido retornado pela exchange")

            # Calcula quantidade de contratos
            market = self.exchange.market(self.config.symbol)
            amount_base = size_usdt / current_price

            # Arredonda conforme precision da exchange
            amount = self.exchange.amount_to_precision(
                self.config.symbol,
                amount_base
            )
            amount = float(amount)

            if amount <= 0:
                raise ValueError(f"Quantidade calculada inválida: {amount}")

            logger.info(
                f"📤 Enviando ordem | Side: {side.upper()} | "
                f"Quantidade: {amount} | Preço aprox: {current_price:.4f} | "
                f"Valor: ~${size_usdt:.2f}"
            )

            order = self._retry(
                self.exchange.create_market_order,
                self.config.symbol,
                side,
                amount
            )

            logger.info(
                f"✅ Ordem executada | ID: {order.get('id')} | "
                f"Status: {order.get('status')}"
            )
            return order

        except Exception as e:
            logger.error(f"❌ Falha ao criar ordem: {e}")
            return None

    def close_position(self, position: dict) -> Optional[dict]:
        """
        Fecha a posição atual com ordem a mercado.
        
        Args:
            position: Dados da posição a fechar
            
        Returns:
            Dados da ordem de fechamento ou None em caso de erro
        """
        try:
            # Para fechar: se Long -> vende; se Short -> compra
            close_side = "sell" if position["side"] == "long" else "buy"
            size = position["size"]

            logger.info(
                f"🔴 Fechando posição | Side: {position['side'].upper()} | "
                f"Tamanho: {size} | PnL não realizado: "
                f"${position['unrealized_pnl']:.4f}"
            )

            order = self._retry(
                self.exchange.create_market_order,
                self.config.symbol,
                close_side,
                size,
                params={"reduceOnly": True}
            )

            logger.info(f"✅ Posição fechada | ID: {order.get('id')}")
            return order

        except Exception as e:
            logger.error(f"❌ Falha ao fechar posição: {e}")
            return None

    def calculate_fee(self, notional_value: float) -> float:
        """
        Calcula a taxa de transação (abertura + fechamento).
        
        Args:
            notional_value: Valor nocional da posição em USDT
            
        Returns:
            Taxa total estimada em USDT
        """
        # Taxa de abertura + Taxa de fechamento
        return notional_value * self.taker_fee * 2
