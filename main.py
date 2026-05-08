"""
Crypto Futures Trading Bot - Preservacao de Lucro
Versao: 2.1.0
"""

import threading
import time
import os
from datetime import datetime

from flask import Flask, render_template, request, jsonify
import ccxt
import pandas as pd
import numpy as np

# ── Cria o app Flask ──────────────────────────────────
app = Flask(__name__)

# ═══════════════════════════════════════════════════════
# ESTADO GLOBAL
# ═══════════════════════════════════════════════════════
bot_state = {
    "running":     False,
    "status":      "parado",
    "logs":        [],
    "config":      {},
    "session": {
        "accumulated_profit": 0.0,
        "total_trades":       0,
        "winning_trades":     0,
        "losing_trades":      0,
        "total_fees":         0.0,
        "initial_balance":    0.0,
        "current_balance":    0.0,
        "start_time":         None,
    },
    "position":    None,
    "last_signal": "---",
    "indicators": {
        "price":    0.0,
        "ema_fast": 0.0,
        "ema_slow": 0.0,
        "rsi":      0.0,
    },
}

bot_thread    = None
stop_event    = threading.Event()


# ═══════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════
def add_log(message, level="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {"time": timestamp, "level": level, "message": message}
    bot_state["logs"].append(entry)
    if len(bot_state["logs"]) > 200:
        bot_state["logs"] = bot_state["logs"][-200:]
    print("[{}][{}] {}".format(timestamp, level, message))


# ═══════════════════════════════════════════════════════
# CONEXAO COM EXCHANGE
# ═══════════════════════════════════════════════════════
def create_exchange(config):
    exchange_id    = config["exchange_id"]
    exchange_class = getattr(ccxt, exchange_id)

    if exchange_id == "bybit":
        params = {
            "apiKey":          config["api_key"],
            "secret":          config["api_secret"],
            "enableRateLimit": True,
            "options": {
                "defaultType": "linear",
                "recvWindow":  10000,
            },
        }
    else:
        params = {
            "apiKey":          config["api_key"],
            "secret":          config["api_secret"],
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }

    exchange = exchange_class(params)

    testnet = str(config.get("testnet", "false")).lower()
    if testnet == "true":
        exchange.set_sandbox_mode(True)
        add_log("Modo TESTNET ativo", "WARNING")

    exchange.load_markets()
    add_log("Conectado a {}".format(exchange_id.upper()))
    return exchange


# ═══════════════════════════════════════════════════════
# SALDO — COMPATIVEL BYBIT UNIFIED + BINANCE
# ═══════════════════════════════════════════════════════
def get_balance(exchange, exchange_id):
    try:
        if exchange_id == "bybit":
            for acc_type in ["UNIFIED", "CONTRACT"]:
                try:
                    bal   = exchange.fetch_balance({"accountType": acc_type})
                    usdt  = bal.get("USDT", {})
                    total = float(usdt.get("total") or 0)
                    free  = float(usdt.get("free")  or 0)
                    if total > 0:
                        add_log(
                            "Saldo [{}] Total=${:.2f} | Livre=${:.2f}".format(
                                acc_type, total, free
                            )
                        )
                        return {"total": total, "free": free}
                except Exception:
                    continue

            # Fallback raw
            bal  = exchange.fetch_balance()
            res  = _parse_raw_balance(bal)
            return res

        # Binance
        bal   = exchange.fetch_balance()
        usdt  = bal.get("USDT", {})
        total = float(usdt.get("total") or 0)
        free  = float(usdt.get("free")  or 0)
        if total > 0:
            return {"total": total, "free": free}
        return _parse_raw_balance(bal)

    except Exception as e:
        add_log("Erro saldo: {}".format(e), "ERROR")
        return {"total": 0.0, "free": 0.0}


def _parse_raw_balance(bal):
    try:
        info   = bal.get("info", {})
        result = info.get("result", {})
        for account in result.get("list", []):
            for coin in account.get("coin", []):
                if coin.get("coin") == "USDT":
                    total = float(coin.get("walletBalance")       or 0)
                    free  = float(coin.get("availableToWithdraw") or
                                  coin.get("availableBalance")    or total)
                    if total > 0:
                        return {"total": total, "free": free}
    except Exception:
        pass
    add_log("Saldo USDT=$0 — verifique permissoes da API Key", "WARNING")
    return {"total": 0.0, "free": 0.0}


# ═══════════════════════════════════════════════════════
# ALAVANCAGEM
# ═══════════════════════════════════════════════════════
def set_leverage_safe(exchange, leverage, symbol):
    try:
        exchange.set_leverage(leverage, symbol)
        add_log("Alavancagem: {}x".format(leverage))
    except Exception as e:
        err = str(e)
        if "110077" in err or "pm mode" in err.lower():
            add_log(
                "Conta Portfolio Margin — alavancagem "
                "gerenciada pela exchange automaticamente.",
                "WARNING"
            )
        elif "leverage not modified" in err.lower():
            add_log("Alavancagem ja em {}x".format(leverage))
        else:
            add_log("Aviso alavancagem: {}".format(err[:80]), "WARNING")


# ═══════════════════════════════════════════════════════
# ANALISE TECNICA
# ═══════════════════════════════════════════════════════
def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series, period=14):
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def analyze_market(exchange, config):
    """
    Estrategia combinada:
    - EMA9/EMA21 Crossover (sinal principal)
    - RSI extremo + tendencia EMA50 (sinal alternativo)
    """
    try:
        raw = exchange.fetch_ohlcv(
            config["symbol"],
            config["timeframe"],
            limit=100
        )
        if not raw or len(raw) < 30:
            add_log("Dados OHLCV insuficientes", "WARNING")
            return "NONE"

        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["close"] = df["close"].astype(float)

        ema_fast  = calculate_ema(df["close"], 9)
        ema_slow  = calculate_ema(df["close"], 21)
        ema_trend = calculate_ema(df["close"], 50)
        rsi       = calculate_rsi(df["close"], 14)

        ef_now  = ema_fast.iloc[-1]
        ef_prev = ema_fast.iloc[-2]
        es_now  = ema_slow.iloc[-1]
        es_prev = ema_slow.iloc[-2]
        et_now  = ema_trend.iloc[-1]
        rsi_now = rsi.iloc[-1]
        price   = df["close"].iloc[-1]

        bot_state["indicators"] = {
            "price":    round(price, 2),
            "ema_fast": round(ef_now, 2),
            "ema_slow": round(es_now, 2),
            "rsi":      round(rsi_now, 2),
        }

        bullish_cross = (ef_prev <= es_prev) and (ef_now > es_now)
        bearish_cross = (ef_prev >= es_prev) and (ef_now < es_now)
        bullish_trend = ef_now > es_now
        bearish_trend = ef_now < es_now
        above_trend   = price > et_now
        below_trend   = price < et_now

        add_log(
            "Preco: {:.2f} | EMA9: {:.2f} | EMA21: {:.2f} | "
            "RSI: {:.2f} | {}".format(
                price, ef_now, es_now, rsi_now,
                "EMA UP" if bullish_trend else "EMA DOWN"
            )
        )

        # Sinal 1: Cruzamento de EMA
        if bullish_cross and rsi_now < 72:
            add_log("SINAL LONG — EMA Cross Up | RSI: {:.1f}".format(rsi_now),
                    "SUCCESS")
            return "LONG"

        if bearish_cross and rsi_now > 28:
            add_log("SINAL SHORT — EMA Cross Down | RSI: {:.1f}".format(rsi_now),
                    "SUCCESS")
            return "SHORT"

        # Sinal 2: RSI extremo com tendencia confirmada
        if bullish_trend and above_trend and rsi_now < 35:
            add_log("SINAL LONG — RSI Sobrevenda {:.1f} + Tendencia Alta".format(
                rsi_now), "SUCCESS")
            return "LONG"

        if bearish_trend and below_trend and rsi_now > 65:
            add_log("SINAL SHORT — RSI Sobrecompra {:.1f} + Tendencia Baixa".format(
                rsi_now), "SUCCESS")
            return "SHORT"

        add_log(
            "Aguardando sinal... RSI:{:.1f} | {}".format(
                rsi_now,
                "Tendencia Alta" if bullish_trend else "Tendencia Baixa"
            )
        )
        return "NONE"

    except Exception as e:
        add_log("Erro na analise: {}".format(e), "ERROR")
        return "NONE"


# ═══════════════════════════════════════════════════════
# GESTAO DE POSICAO
# ═══════════════════════════════════════════════════════
def get_position(exchange, symbol):
    try:
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            contracts = float(pos.get("contracts") or 0)
            if contracts > 0:
                return {
                    "side":           pos.get("side"),
                    "size":           contracts,
                    "entry_price":    float(pos.get("entryPrice")    or 0),
                    "unrealized_pnl": float(pos.get("unrealizedPnl") or 0),
                    "notional":       abs(float(pos.get("notional")  or 0)),
                }
        return None
    except Exception as e:
        add_log("Erro ao buscar posicao: {}".format(e), "ERROR")
        return None


def open_position(exchange, config, signal, free_balance):
    try:
        ticker = exchange.fetch_ticker(config["symbol"])
        price  = float(ticker["last"])

        size_usdt   = free_balance * (float(config["position_size_percent"]) / 100)
        amount_base = size_usdt / price
        amount      = float(
            exchange.amount_to_precision(config["symbol"], amount_base)
        )

        if amount <= 0:
            add_log("Quantidade invalida calculada!", "ERROR")
            return False

        side = "buy" if signal == "LONG" else "sell"

        add_log(
            "Abrindo {} | Preco: {:.2f} | Qtd: {} | ~${:.2f}".format(
                signal, price, amount, size_usdt
            )
        )

        exchange.create_market_order(config["symbol"], side, amount)
        bot_state["last_signal"] = signal
        add_log("Posicao {} aberta com sucesso!".format(signal), "SUCCESS")
        return True

    except Exception as e:
        add_log("Erro ao abrir posicao: {}".format(e), "ERROR")
        return False


def close_position(exchange, position, config):
    try:
        close_side = "sell" if position["side"] == "long" else "buy"

        add_log(
            "Fechando {} | PnL: ${:.4f}".format(
                position["side"].upper(),
                position["unrealized_pnl"]
            )
        )

        exchange.create_market_order(
            config["symbol"],
            close_side,
            position["size"],
            params={"reduceOnly": True}
        )

        gross_pnl = position["unrealized_pnl"]
        taker_fee = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
        fees      = position["notional"] * taker_fee * 2
        net_pnl   = gross_pnl - fees

        sess = bot_state["session"]
        sess["accumulated_profit"] += net_pnl
        sess["total_trades"]       += 1
        sess["total_fees"]         += fees

        if net_pnl >= 0:
            sess["winning_trades"] += 1
            add_log(
                "GANHO! Bruto:${:.4f} Taxa:${:.4f} Liquido:${:.4f}".format(
                    gross_pnl, fees, net_pnl
                ),
                "SUCCESS"
            )
        else:
            sess["losing_trades"] += 1
            add_log(
                "PERDA. Bruto:${:.4f} Taxa:${:.4f} Liquido:${:.4f}".format(
                    gross_pnl, fees, net_pnl
                ),
                "WARNING"
            )

        add_log(
            "Acumulado: ${:.4f} | Trades: {} | W:{} L:{}".format(
                sess["accumulated_profit"],
                sess["total_trades"],
                sess["winning_trades"],
                sess["losing_trades"]
            )
        )
        return net_pnl

    except Exception as e:
        add_log("Erro ao fechar posicao: {}".format(e), "ERROR")
        return 0.0


# ═══════════════════════════════════════════════════════
# GESTAO DE RISCO
# ═══════════════════════════════════════════════════════
def calculate_stop_loss(config, total_balance):
    accumulated = bot_state["session"]["accumulated_profit"]
    min_profit  = float(config.get("min_profit_to_use_rule", 5.0))

    if accumulated >= min_profit:
        stop = accumulated * (float(config["profit_stop_percent"]) / 100)
        add_log(
            "Stop LUCRO: ${:.4f} ({}% de ${:.4f})".format(
                stop, config["profit_stop_percent"], accumulated
            )
        )
    else:
        stop = total_balance * (float(config["initial_stop_percent"]) / 100)
        add_log(
            "Stop PADRAO: ${:.4f} ({}% de ${:.2f})".format(
                stop, config["initial_stop_percent"], total_balance
            )
        )
    return max(stop, 0.01)


# ═══════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════════════════════════════
def bot_loop(config):
    add_log("Iniciando bot...", "SUCCESS")
    bot_state["status"] = "conectando"

    try:
        exchange = create_exchange(config)

        set_leverage_safe(
            exchange,
            int(config.get("leverage", 3)),
            config["symbol"]
        )

        bal  = get_balance(exchange, config["exchange_id"])
        sess = bot_state["session"]
        sess["initial_balance"] = bal["total"]
        sess["current_balance"] = bal["total"]
        sess["start_time"]      = datetime.now().strftime("%d/%m/%Y %H:%M")

        add_log(
            "Capital inicial: ${:.2f} USDT | Livre: ${:.2f}".format(
                bal["total"], bal["free"]
            )
        )

        if bal["total"] < 1.0:
            add_log(
                "ATENCAO: Saldo ${:.2f} insuficiente para operar. "
                "Deposite USDT na conta Futuros da Bybit.".format(bal["total"]),
                "WARNING"
            )

        state        = "ANALYZING"
        cooldown_end = 0.0

        # ── Loop ─────────────────────────────────────────
        while not stop_event.is_set():
            try:
                bal = get_balance(exchange, config["exchange_id"])
                sess["current_balance"] = bal["total"]

                # ANALYZING
                if state == "ANALYZING":
                    bot_state["status"] = "analisando"
                    signal = analyze_market(exchange, config)

                    if signal != "NONE":
                        add_log("Sinal detectado: {}".format(signal), "SUCCESS")
                        if bal["free"] < 1.0:
                            add_log(
                                "Saldo livre insuficiente: ${:.2f} "
                                "— Deposite USDT para operar.".format(bal["free"]),
                                "WARNING"
                            )
                        else:
                            ok = open_position(
                                exchange, config, signal, bal["free"]
                            )
                            if ok:
                                state = "IN_POSITION"
                                bot_state["status"] = "em posicao"

                # IN_POSITION
                elif state == "IN_POSITION":
                    bot_state["status"] = "em posicao"
                    position = get_position(exchange, config["symbol"])

                    if not position:
                        add_log("Posicao encerrada externamente.", "WARNING")
                        bot_state["position"] = None
                        state = "ANALYZING"
                        continue

                    bot_state["position"] = position

                    upnl      = position["unrealized_pnl"]
                    taker_fee = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
                    fee_est   = position["notional"] * taker_fee
                    net_pnl   = upnl - fee_est
                    max_loss  = calculate_stop_loss(config, bal["total"])

                    icon = "+" if upnl >= 0 else "-"
                    add_log(
                        "{} PnL: ${:.4f} | Liq: ${:.4f} | Limite: ${:.4f}".format(
                            icon, upnl, net_pnl, max_loss
                        )
                    )

                    if net_pnl < 0 and abs(net_pnl) >= max_loss:
                        add_log(
                            "STOP LOSS! Perda ${:.4f} >= Limite ${:.4f}".format(
                                abs(net_pnl), max_loss
                            ),
                            "WARNING"
                        )
                        close_position(exchange, position, config)
                        bot_state["position"] = None
                        cooldown_end = time.time() + int(
                            config.get("cooldown_seconds", 30)
                        )
                        state = "COOLDOWN"

                # COOLDOWN
                elif state == "COOLDOWN":
                    remaining = max(0.0, cooldown_end - time.time())
                    bot_state["status"] = "cooldown ({}s)".format(int(remaining))
                    if remaining <= 0:
                        add_log("Cooldown encerrado. Retomando analise...")
                        state = "ANALYZING"

            except ccxt.NetworkError as e:
                add_log("Erro de rede: {}".format(e), "ERROR")
                time.sleep(20)
            except ccxt.ExchangeError as e:
                add_log("Erro exchange: {}".format(e), "ERROR")
                time.sleep(15)
            except Exception as e:
                add_log("Erro no loop: {}".format(e), "ERROR")
                time.sleep(10)

            time.sleep(int(config.get("loop_interval", 10)))

    except Exception as e:
        add_log("Erro critico: {}".format(e), "ERROR")
    finally:
        bot_state["running"]  = False
        bot_state["status"]   = "parado"
        bot_state["position"] = None
        add_log("Bot encerrado.")


# ═══════════════════════════════════════════════════════
# ROTAS FLASK
# ═══════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_bot():
    global bot_thread, stop_event

    if bot_state["running"]:
        return jsonify({"error": "Bot ja esta rodando!"}), 400

    data = request.json or {}
    for campo in ["api_key", "api_secret", "exchange_id", "symbol"]:
        if not data.get(campo):
            return jsonify({"error": "Campo obrigatorio: {}".format(campo)}), 400

    bot_state.update({
        "running":     True,
        "logs":        [],
        "position":    None,
        "last_signal": "---",
        "config":      data,
        "indicators":  {"price": 0.0, "ema_fast": 0.0,
                        "ema_slow": 0.0, "rsi": 0.0},
        "session": {
            "accumulated_profit": 0.0,
            "total_trades":       0,
            "winning_trades":     0,
            "losing_trades":      0,
            "total_fees":         0.0,
            "initial_balance":    0.0,
            "current_balance":    0.0,
            "start_time":         None,
        },
    })

    stop_event = threading.Event()
    bot_thread = threading.Thread(
        target=bot_loop, args=(data,), daemon=True
    )
    bot_thread.start()
    return jsonify({"success": True, "message": "Bot iniciado!"})


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    if not bot_state["running"]:
        return jsonify({"error": "Bot nao esta rodando"}), 400
    stop_event.set()
    bot_state["running"] = False
    bot_state["status"]  = "parando..."
    add_log("Encerrando bot...", "WARNING")
    return jsonify({"success": True, "message": "Bot encerrado."})


@app.route("/api/status")
def get_status():
    return jsonify({
        "running":    bot_state["running"],
        "status":     bot_state["status"],
        "session":    bot_state["session"],
        "position":   bot_state["position"],
        "signal":     bot_state["last_signal"],
        "indicators": bot_state["indicators"],
        "logs":       bot_state["logs"][-50:],
    })


# ═══════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
