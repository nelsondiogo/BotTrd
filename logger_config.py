"""
Configuração centralizada de logging com cores e formatação detalhada.
"""

import logging
import sys
from datetime import datetime

try:
    import colorlog
    HAS_COLORLOG = True
except ImportError:
    HAS_COLORLOG = False


def setup_logger(name: str = "TradingBot") -> logging.Logger:
    """
    Configura e retorna o logger principal do bot.
    
    Args:
        name: Nome do logger
        
    Returns:
        Logger configurado com handlers de console e arquivo
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Evita duplicação de handlers se chamado múltiplas vezes
    if logger.handlers:
        return logger

    # --- Formato das mensagens ---
    detailed_format = (
        "%(asctime)s | %(levelname)-8s | %(module)-15s | %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"

    # --- Handler de Console com cores (se colorlog disponível) ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    if HAS_COLORLOG:
        color_formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s | %(levelname)-8s%(reset)s | "
            "%(cyan)s%(module)-15s%(reset)s | %(message)s",
            datefmt=date_format,
            log_colors={
                "DEBUG":    "white",
                "INFO":     "green",
                "WARNING":  "yellow",
                "ERROR":    "red",
                "CRITICAL": "bold_red",
            }
        )
        console_handler.setFormatter(color_formatter)
    else:
        console_handler.setFormatter(
            logging.Formatter(detailed_format, datefmt=date_format)
        )

    # --- Handler de Arquivo para histórico completo ---
    log_filename = f"bot_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(detailed_format, datefmt=date_format)
    )

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


# Logger global do projeto
logger = setup_logger()
