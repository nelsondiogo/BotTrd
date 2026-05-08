"""
Bot de Trading com Dashboard Web
Configure tudo pelo navegador - sem variáveis de ambiente
"""

import threading
import time
import json
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import ccxt
import pandas as pd
import numpy as np

app = Flask(__name__)

# ─────────────────────────────────────────
# ESTADO GLOBAL DO BOT
# ─────────────────────────────────────────
bot_state = {
    "running": False,
    "status": "parado",
    "logs": [],
    "config": {},
    "session": {
        "accumulated_profit": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "total_fees": 0.0,
        "initial_balance": 0.0,
        "current_balance": 0.0,
        "start_time": None,
    },
    "position": None,
    "last_signal": "---",
    "indicators": {
        "price": 0.0,
        "ema_fast": 0.0,
        "ema_slow": 0.0,
        "rsi": 0.0,
    }
}

bot_thread = None
stop_event = threading.Event()


# ─────────────────────────────────────────
# FUNÇÕES DE LOG
# ─────────────────────────────────────────
def add_log(message: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {
        "time": timestamp,
        "level": level,
        "message": message
    }
    bot_state["logs"].append(entry)
    # Mantém apenas os últimos 100 logs
    if len(bot_state["logs"]) > 100:
        bot_state["logs"] = bot_state["logs"][-100:]
    print(f"[{timestamp}] [{level}] {message}")


# ─────────────────────────────────────────
# FUNÇÕES TÉCNICAS
# ─────────────────────────────────────────
def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def analyze_market(exchange, config: dict) -> str:
    """
    Analisa o mercado e retorna: 'LONG', 'SHORT' ou 'NONE'
    """
    try:
        raw = exchange.fetch_ohlcv(
            config["symbol"],
            config["timeframe"],
            limit=100
        )
        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["close"] = df["close"].astype(float)

        ema_fast = calculate_ema(df["close"], 9)
        ema_slow = calculate_ema(df["close"], 21)
        rsi = calculate_rsi(df["close"], 14)

        ef_now  = ema_fast.iloc[-1]
        ef_prev = ema_fast.iloc[-2]
        es_now  = ema_slow.iloc[-1]
        es_prev = ema_slow.iloc[-2]
        rsi_now = rsi.iloc[-1]
        price   = df["close"].iloc[-1]

        # Atualiza indicadores no estado
        bot_state["indicators"] = {
            "price":    round(price, 4),
            "ema_fast": round(ef_now, 4),
            "ema_slow": round(es_now, 4),
            "rsi":      round(rsi_now, 2),
        }

        bullish_cross = (ef_prev < es_prev) and (ef_now > es_now)
        bearish_cross = (ef_prev > es_prev) and (ef_now < es_now)

        add_log(
            f"Preço: {price:.4f} | "
            f"EMA9: {ef_now:.4f} | "
            f"EMA21: {es_now:.4f} | "
            f"RSI: {rsi_now:.2f}"
        )

        if bullish_cross and rsi_now < 70:
            return "LONG"
        if bearish_cross and rsi_now > 30:
            return "SHORT"
        return "NONE"

    except Exception as e:
        add_log(f"Erro na análise: {e}", "ERROR")
        return "NONE"


# ─────────────────────────────────────────
# FUNÇÕES DE TRADING
# ─────────────────────────────────────────
def get_balance(exchange) -> dict:
    balance = exchange.fetch_balance()
    usdt = balance.get("USDT", {})
    return {
        "total": float(usdt.get("total", 0) or 0),
        "free":  float(usdt.get("free", 0) or 0),
    }


def get_position(exchange, symbol: str):
    try:
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            contracts = float(pos.get("contracts", 0) or 0)
            if contracts > 0:
                return {
                    "side":           pos.get("side"),
                    "size":           contracts,
                    "entry_price":    float(pos.get("entryPrice", 0) or 0),
                    "unrealized_pnl": float(pos.get("unrealizedPnl", 0) or 0),
                    "notional":       abs(float(pos.get("notional", 0) or 0)),
                }
        return None
    except Exception as e:
        add_log(f"Erro ao buscar posição: {e}", "ERROR")
        return None


def open_position(exchange, config: dict, signal: str) -> bool:
    try:
        ticker = exchange.fetch_ticker(config["symbol"])
        price  = float(ticker["last"])

        balance      = get_balance(exchange)
        size_usdt    = balance["free"] * (float(config["position_size_percent"]) / 100)
        amount_base  = size_usdt / price
        amount       = float(
            exchange.amount_to_precision(config["symbol"], amount_base)
        )

        if amount <= 0:
            add_log("Quantidade calculada inválida!", "ERROR")
            return False

        side = "buy" if signal == "LONG" else "sell"

        add_log(
            f"Abrindo {signal} | "
            f"Preço: {price:.4f} | "
            f"Qtd: {amount} | "
            f"Valor: ~${size_usdt:.2f}"
        )

        exchange.create_market_order(config["symbol"], side, amount)
        bot_state["last_signal"] = signal
        add_log(f"✅ Posição {signal} aberta com sucesso!", "SUCCESS")
        return True

    except Exception as e:
        add_log(f"Erro ao abrir posição: {e}", "ERROR")
        return False


def close_position(exchange, position: dict, config: dict) -> float:
    try:
        close_side = "sell" if position["side"] == "long" else "buy"

        add_log(
            f"Fechando {position['side'].upper()} | "
            f"PnL: ${position['unrealized_pnl']:.4f}"
        )

        exchange.create_market_order(
            config["symbol"],
            close_side,
            position["size"],
            params={"reduceOnly": True}
        )

        gross_pnl  = position["unrealized_pnl"]
        taker_fee  = 0.0004 if config["exchange_id"] == "binance" else 0.0006
        fees       = position["notional"] * taker_fee * 2
        net_pnl    = gross_pnl - fees

        # Atualiza sessão
        sess = bot_state["session"]
        sess["accumulated_profit"] += net_pnl
        sess["total_trades"]       += 1
        sess["total_fees"]         += fees

        if net_pnl >= 0:
            sess["winning_trades"] += 1
            add_log(f"✅ Trade ganho! PnL líquido: ${net_pnl:.4f}", "SUCCESS")
        else:
            sess["losing_trades"] += 1
            add_log(f"❌ Trade perdido. PnL líquido: ${net_pnl:.4f}", "WARNING")

        add_log(
            f"💰 Lucro acumulado da sessão: "
            f"${sess['accumulated_profit']:.4f}"
        )
        return net_pnl

    except Exception as e:
        add_log(f"Erro ao fechar posição: {e}", "ERROR")
        return 0.0


def calculate_stop_loss(config: dict, total_balance: float) -> float:
    """Calcula o stop loss baseado no lucro acumulado."""
    accumulated = bot_state["session"]["accumulated_profit"]
    min_profit  = float(config.get("min_profit_to_use_rule", 5.0))

    if accumulated >= min_profit:
        stop = accumulated * (float(config["profit_stop_percent"]) / 100)
        add_log(
            f"🛡️ Regra do LUCRO ativa | "
            f"Stop: ${stop:.4f} "
            f"({config['profit_stop_percent']}% de ${accumulated:.4f})"
        )
    else:
        stop = total_balance * (float(config["initial_stop_percent"]) / 100)
        add_log(
            f"🛡️ Stop PADRÃO ativo | "
            f"Stop: ${stop:.4f} "
            f"({config['initial_stop_percent']}% de ${total_balance:.4f})"
        )
    return stop


# ─────────────────────────────────────────
# LOOP PRINCIPAL DO BOT
# ─────────────────────────────────────────
def bot_loop(config: dict):
    add_log("🚀 Bot iniciado!", "SUCCESS")
    bot_state["status"] = "analisando"

    try:
        # Conecta à exchange
        exchange_class = getattr(ccxt, config["exchange_id"])
        exchange = exchange_class({
            "apiKey":          config["api_key"],
            "secret":          config["api_secret"],
            "enableRateLimit": True,
            "options":         {"defaultType": "future"},
        })

        if config.get("testnet"):
            exchange.set_sandbox_mode(True)
            add_log("⚠️ Modo TESTNET ativo", "WARNING")

        exchange.load_markets()
        add_log(f"✅ Conectado à {config['exchange_id'].upper()}")

        # Configura alavancagem
        try:
            exchange.set_leverage(int(config["leverage"]), config["symbol"])
            add_log(f"⚡ Alavancagem: {config['leverage']}x")
        except Exception as e:
            add_log(f"Aviso alavancagem: {e}", "WARNING")

        # Saldo inicial
        balance = get_balance(exchange)
        bot_state["session"]["initial_balance"] = balance["total"]
        bot_state["session"]["current_balance"] = balance["total"]
        bot_state["session"]["start_time"]      = datetime.now().strftime(
            "%d/%m/%Y %H:%M"
        )
        add_log(f"💵 Saldo inicial: ${balance['total']:.2f} USDT")

        state        = "ANALYZING"
        cooldown_end = 0

        # ── Loop ──────────────────────────────
        while not stop_event.is_set():

            try:
                # Atualiza saldo atual
                bal = get_balance(exchange)
                bot_state["session"]["current_balance"] = bal["total"]

                # ── ANALYZING ──────────────────
                if state == "ANALYZING":
                    bot_state["status"] = "analisando"
                    signal = analyze_market(exchange, config)

                    if signal != "NONE":
                        add_log(f"🎯 Sinal detectado: {signal}", "SUCCESS")
                        success = open_position(exchange, config, signal)
                        if success:
                            state = "IN_POSITION"
                            bot_state["status"] = "em posição"

                # ── IN_POSITION ─────────────────
                elif state == "IN_POSITION":
                    bot_state["status"] = "em posição"
                    position = get_position(exchange, config["symbol"])

                    if not position:
                        add_log(
                            "Posição não encontrada, voltando a analisar...",
                            "WARNING"
                        )
                        state = "ANALYZING"
                        continue

                    bot_state["position"] = position

                    upnl       = position["unrealized_pnl"]
                    taker_fee  = 0.0004 if config["exchange_id"] == "binance" else 0.0006
                    fees_close = position["notional"] * taker_fee
                    net_pnl    = upnl - fees_close
                    max_loss   = calculate_stop_loss(config, bal["total"])

                    add_log(
                        f"📊 PnL: ${upnl:.4f} | "
                        f"PnL Líq: ${net_pnl:.4f} | "
                        f"Stop: ${max_loss:.4f}"
                    )

                    if net_pnl < 0 and abs(net_pnl) >= max_loss:
                        add_log(
                            f"🛑 STOP LOSS atingido! "
                            f"Perda: ${net_pnl:.4f} >= Limite: ${max_loss:.4f}",
                            "WARNING"
                        )
                        close_position(exchange, position, config)
                        bot_state["position"] = None
                        cooldown_end = time.time() + int(config["cooldown_seconds"])
                        state = "COOLDOWN"

                # ── COOLDOWN ──────────────────
                elif state == "COOLDOWN":
                    remaining = cooldown_end - time.time()
                    bot_state["status"] = f"cooldown ({int(remaining)}s)"

                    if remaining <= 0:
                        add_log("✅ Cooldown finalizado, retomando análise...")
                        state = "ANALYZING"

            except ccxt.NetworkError as e:
                add_log(f"Erro de rede: {e}", "ERROR")
                time.sleep(15)

            except ccxt.ExchangeError as e:
                add_log(f"Erro da exchange: {e}", "ERROR")
                time.sleep(15)

            except Exception as e:
                add_log(f"Erro no loop: {e}", "ERROR")
                time.sleep(10)

            time.sleep(int(config.get("loop_interval", 10)))

    except Exception as e:
        add_log(f"❌ Erro crítico: {e}", "ERROR")
    finally:
        bot_state["running"] = False
        bot_state["status"]  = "parado"
        add_log("⛔ Bot encerrado.")


# ─────────────────────────────────────────
# ROTAS FLASK
# ─────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_bot():
    global bot_thread, stop_event

    if bot_state["running"]:
        return jsonify({"error": "Bot já está rodando!"}), 400

    data = request.json

    # Validação básica
    required = ["api_key", "api_secret", "exchange_id", "symbol"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Campo obrigatório: {field}"}), 400

    # Reseta sessão
    bot_state["session"] = {
        "accumulated_profit": 0.0,
        "total_trades":       0,
        "winning_trades":     0,
        "losing_trades":      0,
        "total_fees":         0.0,
        "initial_balance":    0.0,
        "current_balance":    0.0,
        "start_time":         None,
    }
    bot_state["logs"]     = []
    bot_state["position"] = None
    bot_state["running"]  = True

    stop_event = threading.Event()

    bot_thread = threading.Thread(
        target=bot_loop,
        args=(data,),
        daemon=True
    )
    bot_thread.start()

    return jsonify({"success": True, "message": "Bot iniciado!"})


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    if not bot_state["running"]:
        return jsonify({"error": "Bot não está rodando"}), 400

    stop_event.set()
    bot_state["running"] = False
    bot_state["status"]  = "parando..."
    add_log("⛔ Solicitação de parada recebida...", "WARNING")

    return jsonify({"success": True, "message": "Bot sendo encerrado..."})


@app.route("/api/status")
def get_status():
    return jsonify({
        "running":    bot_state["running"],
        "status":     bot_state["status"],
        "session":    bot_state["session"],
        "position":   bot_state["position"],
        "signal":     bot_state["last_signal"],
        "indicators": bot_state["indicators"],
        "logs":       bot_state["logs"][-30:],
    })


# ─────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
