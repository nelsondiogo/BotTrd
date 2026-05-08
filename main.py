"""
Crypto Futures Trading Bot — Preservação de Lucro
Versão: 2.0.0 — Produção
Exchange: Bybit / Binance Futures
"""

import threading
import time
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import ccxt
import pandas as pd
import numpy as np

app = Flask(__name__)

# ═══════════════════════════════════════════════════
# ESTADO GLOBAL
# ═══════════════════════════════════════════════════
bot_state = {
    "running":  False,
    "status":   "parado",
    "logs":     [],
    "config":   {},
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
    "position":   None,
    "last_signal": "---",
    "indicators": {
        "price":    0.0,
        "ema_fast": 0.0,
        "ema_slow": 0.0,
        "rsi":      0.0,
    },
}

bot_thread = None
stop_event  = threading.Event()
exchange_global = None  # instância reutilizável


# ═══════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════
def add_log(message: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {"time": timestamp, "level": level, "message": message}
    bot_state["logs"].append(entry)
    if len(bot_state["logs"]) > 200:
        bot_state["logs"] = bot_state["logs"][-200:]
    print(f"[{timestamp}][{level}] {message}")


# ═══════════════════════════════════════════════════
# CONEXÃO COM A EXCHANGE
# ═══════════════════════════════════════════════════
def create_exchange(config: dict):
    """
    Cria instância da exchange com configurações
    específicas para Bybit e Binance.
    """
    exchange_id = config["exchange_id"]
    exchange_class = getattr(ccxt, exchange_id)

    params = {
        "apiKey":          config["api_key"],
        "secret":          config["api_secret"],
        "enableRateLimit": True,
    }

    if exchange_id == "bybit":
        params["options"] = {
            "defaultType": "linear",
            "recvWindow":  10000,
        }
    else:
        params["options"] = {"defaultType": "future"}

    exchange = exchange_class(params)

    if str(config.get("testnet", "false")).lower() == "true":
        exchange.set_sandbox_mode(True)
        add_log("⚠️ Modo TESTNET ativo", "WARNING")

    exchange.load_markets()
    add_log(f"✅ Conectado à {exchange_id.upper()}")
    return exchange


# ═══════════════════════════════════════════════════
# SALDO — COMPATÍVEL BYBIT UNIFIED + BINANCE
# ═══════════════════════════════════════════════════
def get_balance(exchange, exchange_id: str) -> dict:
    """
    Leitura de saldo compatível com:
    - Bybit Unified Account
    - Bybit Standard Account
    - Binance Futures
    """
    try:
        # ── Bybit: testa tipos de conta em ordem ──
        if exchange_id == "bybit":
            for acc_type in ["UNIFIED", "CONTRACT"]:
                try:
                    bal   = exchange.fetch_balance(
                        {"accountType": acc_type}
                    )
                    usdt  = bal.get("USDT", {})
                    total = float(usdt.get("total") or 0)
                    free  = float(usdt.get("free")  or 0)

                    if total > 0:
                        add_log(
                            f"💵 Saldo [{acc_type}] "
                            f"Total=${total:.2f} | Livre=${free:.2f}"
                        )
                        return {"total": total, "free": free}
                except Exception:
                    continue

            # Fallback: fetch padrão Bybit
            bal   = exchange.fetch_balance()
            usdt  = bal.get("USDT", {})
            total = float(usdt.get("total") or 0)
            free  = float(usdt.get("free")  or 0)
            if total > 0:
                return {"total": total, "free": free}

            # Último recurso: varre info raw
            return _parse_raw_balance(bal)

        # ── Binance ──
        bal   = exchange.fetch_balance()
        usdt  = bal.get("USDT", {})
        total = float(usdt.get("total") or 0)
        free  = float(usdt.get("free")  or 0)

        if total > 0:
            add_log(f"💵 Saldo Total=${total:.2f} | Livre=${free:.2f}")
            return {"total": total, "free": free}

        return _parse_raw_balance(bal)

    except Exception as e:
        add_log(f"Erro ao buscar saldo: {e}", "ERROR")
        return {"total": 0.0, "free": 0.0}


def _parse_raw_balance(bal: dict) -> dict:
    """Varre estrutura raw da exchange em busca do saldo USDT."""
    try:
        info = bal.get("info", {})
        result = info.get("result", {})
        account_list = result.get("list", [])

        for account in account_list:
            coins = account.get("coin", [])
            for coin in coins:
                if coin.get("coin") == "USDT":
                    total = float(coin.get("walletBalance")        or 0)
                    free  = float(coin.get("availableToWithdraw")  or
                                  coin.get("availableBalance")     or
                                  total)
                    if total > 0:
                        add_log(
                            f"💵 Saldo (raw) "
                            f"Total=${total:.2f} | Livre=${free:.2f}"
                        )
                        return {"total": total, "free": free}
    except Exception:
        pass

    add_log("⚠️ Saldo USDT=$0 — verifique permissões da API Key", "WARNING")
    return {"total": 0.0, "free": 0.0}


# ═══════════════════════════════════════════════════
# ALAVANCAGEM
# ═══════════════════════════════════════════════════
def set_leverage_safe(exchange, leverage: int, symbol: str):
    """Configura alavancagem sem travar o bot se falhar."""
    try:
        exchange.set_leverage(leverage, symbol)
        add_log(f"⚡ Alavancagem: {leverage}x")
    except Exception as e:
        err = str(e)
        if "110077" in err or "pm mode" in err.lower():
            add_log(
                "ℹ️ Conta Portfolio Margin — alavancagem "
                "gerenciada pela exchange automaticamente.",
                "WARNING"
            )
        elif "leverage not modified" in err.lower():
            add_log(f"ℹ️ Alavancagem já em {leverage}x")
        else:
            add_log(f"⚠️ Alavancagem: {err[:80]}", "WARNING")


# ═══════════════════════════════════════════════════
# ANÁLISE TÉCNICA — EMA CROSSOVER + RSI
# ═══════════════════════════════════════════════════
def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def analyze_market(exchange, config: dict) -> str:
    """
    Analisa mercado via EMA9/EMA21 crossover + RSI.
    Retorna: 'LONG', 'SHORT' ou 'NONE'
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

        ema_fast = calculate_ema(df["close"], 9)
        ema_slow = calculate_ema(df["close"], 21)
        rsi      = calculate_rsi(df["close"], 14)

        ef_now  = ema_fast.iloc[-1]
        ef_prev = ema_fast.iloc[-2]
        es_now  = ema_slow.iloc[-1]
        es_prev = ema_slow.iloc[-2]
        rsi_now = rsi.iloc[-1]
        price   = df["close"].iloc[-1]

        # Atualiza indicadores no dashboard
        bot_state["indicators"] = {
            "price":    round(price, 2),
            "ema_fast": round(ef_now, 2),
            "ema_slow": round(es_now, 2),
            "rsi":      round(rsi_now, 2),
        }

        bullish_cross = (ef_prev < es_prev) and (ef_now > es_now)
        bearish_cross = (ef_prev > es_prev) and (ef_now < es_now)

        add_log(
            f"📊 Preço: {price:.2f} | "
            f"EMA9: {ef_now:.2f} | "
            f"EMA21: {es_now:.2f} | "
            f"RSI: {rsi_now:.2f}"
        )

        if bullish_cross and rsi_now < 70:
            add_log("🟢 Cruzamento de alta detectado!", "SUCCESS")
            return "LONG"
        if bearish_cross and rsi_now > 30:
            add_log("🔴 Cruzamento de baixa detectado!", "SUCCESS")
            return "SHORT"

        return "NONE"

    except Exception as e:
        add_log(f"Erro na análise: {e}", "ERROR")
        return "NONE"


# ═══════════════════════════════════════════════════
# GESTÃO DE POSIÇÃO
# ═══════════════════════════════════════════════════
def get_position(exchange, symbol: str) -> dict | None:
    """Busca posição aberta atual."""
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
        add_log(f"Erro ao buscar posição: {e}", "ERROR")
        return None


def open_position(exchange, config: dict, signal: str, free: float) -> bool:
    """Abre posição a mercado."""
    try:
        ticker = exchange.fetch_ticker(config["symbol"])
        price  = float(ticker["last"])

        size_usdt   = free * (float(config["position_size_percent"]) / 100)
        amount_base = size_usdt / price
        amount      = float(
            exchange.amount_to_precision(config["symbol"], amount_base)
        )

        if amount <= 0:
            add_log("❌ Quantidade inválida calculada!", "ERROR")
            return False

        side = "buy" if signal == "LONG" else "sell"

        add_log(
            f"🔄 Abrindo {signal} | "
            f"Preço: {price:.2f} | "
            f"Qtd: {amount} | "
            f"~${size_usdt:.2f}"
        )

        exchange.create_market_order(config["symbol"], side, amount)
        bot_state["last_signal"] = signal
        add_log(f"✅ Posição {signal} aberta com sucesso!", "SUCCESS")
        return True

    except Exception as e:
        add_log(f"Erro ao abrir posição: {e}", "ERROR")
        return False


def close_position(exchange, position: dict, config: dict) -> float:
    """Fecha posição e registra resultado."""
    try:
        close_side = "sell" if position["side"] == "long" else "buy"

        add_log(
            f"🔄 Fechando {position['side'].upper()} | "
            f"PnL: ${position['unrealized_pnl']:.4f}"
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
                f"✅ GANHO! Bruto: ${gross_pnl:.4f} | "
                f"Taxa: ${fees:.4f} | Líquido: ${net_pnl:.4f}",
                "SUCCESS"
            )
        else:
            sess["losing_trades"] += 1
            add_log(
                f"❌ PERDA. Bruto: ${gross_pnl:.4f} | "
                f"Taxa: ${fees:.4f} | Líquido: ${net_pnl:.4f}",
                "WARNING"
            )

        add_log(
            f"💰 Acumulado: ${sess['accumulated_profit']:.4f} | "
            f"Trades: {sess['total_trades']} | "
            f"W:{sess['winning_trades']} L:{sess['losing_trades']}"
        )
        return net_pnl

    except Exception as e:
        add_log(f"Erro ao fechar posição: {e}", "ERROR")
        return 0.0


# ═══════════════════════════════════════════════════
# GESTÃO DE RISCO — PRESERVAÇÃO DE LUCRO
# ═══════════════════════════════════════════════════
def calculate_stop_loss(config: dict, total_balance: float) -> float:
    """
    Regra central de stop loss:
    - Com lucro >= mínimo: stop = % do lucro acumulado
    - Sem lucro suficiente: stop = % do capital total
    """
    accumulated = bot_state["session"]["accumulated_profit"]
    min_profit  = float(config.get("min_profit_to_use_rule", 5.0))

    if accumulated >= min_profit:
        stop = accumulated * (float(config["profit_stop_percent"]) / 100)
        add_log(
            f"🛡️ Regra LUCRO | "
            f"Stop=${stop:.4f} "
            f"({config['profit_stop_percent']}% de ${accumulated:.4f})"
        )
    else:
        stop = total_balance * (float(config["initial_stop_percent"]) / 100)
        add_log(
            f"🛡️ Stop PADRÃO | "
            f"Stop=${stop:.4f} "
            f"({config['initial_stop_percent']}% de ${total_balance:.2f})"
        )
    return max(stop, 0.01)


# ═══════════════════════════════════════════════════
# LOOP PRINCIPAL DO BOT
# ═══════════════════════════════════════════════════
def bot_loop(config: dict):
    global exchange_global

    add_log("🚀 Iniciando bot...", "SUCCESS")
    bot_state["status"] = "conectando"

    try:
        # ── Conecta ──
        exchange = create_exchange(config)
        exchange_global = exchange

        # ── Alavancagem ──
        set_leverage_safe(
            exchange,
            int(config.get("leverage", 3)),
            config["symbol"]
        )

        # ── Saldo inicial ──
        bal  = get_balance(exchange, config["exchange_id"])
        sess = bot_state["session"]
        sess["initial_balance"] = bal["total"]
        sess["current_balance"] = bal["total"]
        sess["start_time"]      = datetime.now().strftime("%d/%m/%Y %H:%M")

        add_log(
            f"💵 Capital inicial: ${bal['total']:.2f} USDT | "
            f"Livre: ${bal['free']:.2f}"
        )

        if bal["total"] == 0:
            add_log(
                "⚠️ Saldo $0.00 — verifique permissões da API Key "
                "(Read + Unified Trading + Derivatives)",
                "WARNING"
            )

        state        = "ANALYZING"
        cooldown_end = 0.0

        # ════════════════════════════════════════
        # LOOP PRINCIPAL
        # ════════════════════════════════════════
        while not stop_event.is_set():
            try:
                # Atualiza saldo a cada ciclo
                bal  = get_balance(exchange, config["exchange_id"])
                sess["current_balance"] = bal["total"]

                # ── ANALISANDO ──────────────────
                if state == "ANALYZING":
                    bot_state["status"] = "analisando"
                    signal = analyze_market(exchange, config)

                    if signal != "NONE":
                        add_log(f"🎯 Sinal detectado: {signal}", "SUCCESS")

                        if bal["free"] < 1.0:
                            add_log(
                                f"⚠️ Saldo livre insuficiente: "
                                f"${bal['free']:.2f}",
                                "WARNING"
                            )
                        else:
                            ok = open_position(
                                exchange, config, signal, bal["free"]
                            )
                            if ok:
                                state = "IN_POSITION"
                                bot_state["status"] = "em posição"

                # ── EM POSIÇÃO ──────────────────
                elif state == "IN_POSITION":
                    bot_state["status"] = "em posição"
                    position = get_position(exchange, config["symbol"])

                    if not position:
                        add_log(
                            "⚠️ Posição encerrada externamente.",
                            "WARNING"
                        )
                        bot_state["position"] = None
                        state = "ANALYZING"
                        continue

                    bot_state["position"] = position

                    upnl      = position["unrealized_pnl"]
                    taker_fee = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
                    fee_est   = position["notional"] * taker_fee
                    net_pnl   = upnl - fee_est
                    max_loss  = calculate_stop_loss(config, bal["total"])

                    icon = "🟢" if upnl >= 0 else "🔴"
                    add_log(
                        f"{icon} PnL: ${upnl:.4f} | "
                        f"Líquido: ${net_pnl:.4f} | "
                        f"Limite: ${max_loss:.4f}"
                    )

                    # Verifica stop loss
                    if net_pnl < 0 and abs(net_pnl) >= max_loss:
                        add_log(
                            f"🛑 STOP LOSS ATIVADO | "
                            f"Perda ${abs(net_pnl):.4f} >= "
                            f"Limite ${max_loss:.4f}",
                            "WARNING"
                        )
                        close_position(exchange, position, config)
                        bot_state["position"] = None
                        cooldown_end = (
                            time.time() + int(config.get("cooldown_seconds", 30))
                        )
                        state = "COOLDOWN"

                # ── COOLDOWN ────────────────────
                elif state == "COOLDOWN":
                    remaining = max(0.0, cooldown_end - time.time())
                    bot_state["status"] = f"cooldown ({int(remaining)}s)"
                    if remaining <= 0:
                        add_log("✅ Cooldown encerrado. Retomando análise...")
                        state = "ANALYZING"

            except ccxt.NetworkError as e:
                add_log(f"Erro de rede: {e}", "ERROR")
                time.sleep(20)
            except ccxt.ExchangeError as e:
                add_log(f"Erro exchange: {e}", "ERROR")
                time.sleep(15)
            except Exception as e:
                add_log(f"Erro no loop: {e}", "ERROR")
                time.sleep(10)

            time.sleep(int(config.get("loop_interval", 10)))

    except Exception as e:
        add_log(f"❌ Erro crítico: {e}", "ERROR")
    finally:
        exchange_global        = None
        bot_state["running"]   = False
        bot_state["status"]    = "parado"
        bot_state["position"]  = None
        add_log("⛔ Bot encerrado.")


# ═══════════════════════════════════════════════════
# ROTAS FLASK
# ═══════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_bot():
    global bot_thread, stop_event

    if bot_state["running"]:
        return jsonify({"error": "Bot já está rodando!"}), 400

    data = request.json or {}
    for campo in ["api_key", "api_secret", "exchange_id", "symbol"]:
        if not data.get(campo):
            return jsonify({"error": f"Campo obrigatório: {campo}"}), 400

    # Reset completo da sessão
    bot_state.update({
        "running":     True,
        "logs":        [],
        "position":    None,
        "last_signal": "---",
        "indicators":  {"price": 0.0, "ema_fast": 0.0, "ema_slow": 0.0, "rsi": 0.0},
        "config":      data,
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
        return jsonify({"error": "Bot não está rodando"}), 400

    stop_event.set()
    bot_state["running"] = False
    bot_state["status"]  = "parando..."
    add_log("⛔ Encerrando bot...", "WARNING")
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


@app.route("/api/debug-balance")
def debug_balance():
    """Diagnóstico de saldo — útil para novos setups."""
    config = bot_state.get("config", {})
    if not config.get("api_key"):
        return jsonify({"erro": "Inicie o bot primeiro para carregar config"}), 400

    resultado = {}
    try:
        exchange_class = getattr(ccxt, config["exchange_id"])
        ex = exchange_class({
            "apiKey":          config["api_key"],
            "secret":          config["api_secret"],
            "enableRateLimit": True,
            "options":         {"defaultType": "linear"},
        })
        ex.load_markets()

        for acc in ["UNIFIED", "CONTRACT", "SPOT"]:
            try:
                b     = ex.fetch_balance({"accountType": acc})
                usdt  = b.get("USDT", {})
                resultado[acc] = {
                    "total": float(usdt.get("total") or 0),
                    "free":  float(usdt.get("free")  or 0),
                }
            except Exception as e:
                resultado[acc] = {"erro": str(e)[:120]}

    except Exception as e:
        resultado["erro_critico"] = str(e)

    return jsonify(resultado)


# ═══════════════════════════════════════════════════
# INICIALIZAÇÃO
# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
