"""
Ponto de entrada principal do Trading Bot.
Valida configurações e inicializa o bot.

Deploy: Render.com
  - Build Command: pip install -r requirements.txt
  - Start Command: python main.py
"""

import sys
import signal
from config import config
from trader import TradingBot
from logger_config import logger


def print_banner() -> None:
    """Exibe o banner de inicialização do bot."""
    banner = """
╔══════════════════════════════════════════════════════╗
║          🤖 CRYPTO FUTURES TRADING BOT 🤖           ║
║           Preservação de Lucro | v1.0.0              ║
║        Binance Futures / Bybit Linear                ║
╚══════════════════════════════════════════════════════╝
    """
    print(banner)


def handle_signal(signum, frame):
    """Handler para sinais de sistema (SIGTERM no Render)."""
    logger.info(f"Sinal {signum} recebido. Encerrando bot graciosamente...")
    sys.exit(0)


def main() -> None:
    """Função principal de entrada."""
    print_banner()

    # Registra handlers para shutdown gracioso
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        # Valida configurações antes de iniciar
        config.validate()

        # Cria e executa o bot
        bot = TradingBot(config)
        bot.run()

    except ValueError as e:
        logger.critical(f"❌ Erro de configuração: {e}")
        logger.critical("Verifique as variáveis de ambiente e tente novamente.")
        sys.exit(1)

    except Exception as e:
        logger.critical(f"❌ Erro crítico: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
