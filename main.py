"""
Crypto Futures Trading Bot - Preservacao de Lucro
Versao: 4.0.0 - Multi-Par Automatico
"""

import threading
import time
import os
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import ccxt
import pandas as pd
import numpy as np

app = Flask(__name__)

CONFIG_FILE = "bot_config.json"


def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print("Erro ao salvar config: {}".format(e))


def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print("Erro ao carregar config: {}".format(e))
    return {}


saved_config = load_config()

bot_state = {
    "running":      False,
    "status":       "parado",
    "logs":         [],
    "config":       saved_config,
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
    "position":     None,
    "last_signal":  "---",
    "active_symbol": "---",
    "indicators":   {
        "price":    0.0,
        "ema_fast": 0.0,
        "ema_slow": 0.0,
        "rsi":      0.0,
        "adx":      0.0,
        "trend":    "---",
    },
    "scanned_pairs": [],
}

bot_thread = None
stop_event = threading.Event()


# ═══════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════
def add_log(message, level="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    bot_state["logs"].append({
        "time": timestamp, "level": level, "message": message
    })
    if len(bot_state["logs"]) > 300:
        bot_state["logs"] = bot_state["logs"][-300:]
    print("[{}][{}] {}".format(timestamp, level, message))


# ═══════════════════════════════════════════════════
# EXCHANGE
# ═══════════════════════════════════════════════════
def create_exchange(config):
    exchange_id = config["exchange_id"]
    cls = getattr(ccxt, exchange_id)

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
            "options":         {"defaultType": "future"},
        }

    ex = cls(params)
    if str(config.get("testnet", "false")).lower() == "true":
        ex.set_sandbox_mode(True)
        add_log("Modo TESTNET ativo", "WARNING")

    ex.load_markets()
    add_log("Conectado a {}".format(exchange_id.upper()))
    return ex


# ═══════════════════════════════════════════════════
# SALDO
# ═══════════════════════════════════════════════════
def get_balance(exchange, exchange_id):
    try:
        if exchange_id == "bybit":
            for acc in ["UNIFIED", "CONTRACT"]:
                try:
                    bal   = exchange.fetch_balance({"accountType": acc})
                    usdt  = bal.get("USDT", {})
                    total = float(usdt.get("total") or 0)
                    free  = float(usdt.get("free")  or 0)
                    if total > 0:
                        return {"total": total, "free": free, "account": acc}
                except Exception:
                    continue
            bal = exchange.fetch_balance()
            return _raw_balance(bal)

        bal   = exchange.fetch_balance()
        usdt  = bal.get("USDT", {})
        total = float(usdt.get("total") or 0)
        free  = float(usdt.get("free")  or 0)
        if total > 0:
            return {"total": total, "free": free, "account": "DEFAULT"}
        return _raw_balance(bal)

    except Exception as e:
        add_log("Erro saldo: {}".format(e), "ERROR")
        return {"total": 0.0, "free": 0.0, "account": "?"}


def _raw_balance(bal):
    try:
        for account in bal.get("info", {}).get("result", {}).get("list", []):
            for coin in account.get("coin", []):
                if coin.get("coin") == "USDT":
                    total = float(coin.get("walletBalance") or 0)
                    free  = float(
                        coin.get("availableToWithdraw") or
                        coin.get("availableBalance") or total
                    )
                    if total > 0:
                        return {"total": total, "free": free, "account": "RAW"}
    except Exception:
        pass
    return {"total": 0.0, "free": 0.0, "account": "?"}


# ═══════════════════════════════════════════════════
# ALAVANCAGEM
# ═══════════════════════════════════════════════════
def set_leverage_safe(exchange, leverage, symbol):
    try:
        exchange.set_leverage(leverage, symbol)
        add_log("Alavancagem {}x em {}".format(leverage, symbol))
    except Exception as e:
        err = str(e)
        if "110077" in err or "pm mode" in err.lower():
            add_log("Portfolio Margin: alavancagem gerenciada pela exchange.", "WARNING")
        elif "leverage not modified" in err.lower():
            add_log("Alavancagem ja configurada.")
        else:
            add_log("Aviso alavancagem: {}".format(err[:100]), "WARNING")


# ═══════════════════════════════════════════════════
# SELECAO AUTOMATICA DE PARES
# ═══════════════════════════════════════════════════
# Pares candidatos ordenados por liquidez e preco acessivel
CANDIDATE_PAIRS = [
    "DOGE/USDT:USDT",
    "XRP/USDT:USDT",
    "TRX/USDT:USDT",
    "ADA/USDT:USDT",
    "MATIC/USDT:USDT",
    "DOT/USDT:USDT",
    "LINK/USDT:USDT",
    "LTC/USDT:USDT",
    "SOL/USDT:USDT",
    "AVAX/USDT:USDT",
    "BNB/USDT:USDT",
    "ETH/USDT:USDT",
    "BTC/USDT:USDT",
]


def get_min_cost(exchange, symbol):
    """Retorna custo minimo em USDT para abrir posicao neste par."""
    try:
        market     = exchange.market(symbol)
        limits     = market.get("limits", {})
        min_amount = float(limits.get("amount", {}).get("min") or 0)
        min_cost   = float(limits.get("cost",   {}).get("min") or 0)

        if min_amount > 0:
            ticker   = exchange.fetch_ticker(symbol)
            price    = float(ticker["last"])
            min_cost = max(min_cost, min_amount * price)

        return min_cost
    except Exception:
        return 999999.0


def scan_best_pairs(exchange, budget_usdt, config):
    """
    Escaneia os pares candidatos e retorna lista com:
    - Pares compativeis com o saldo
    - Ordenados por forca de tendencia (ADX)
    """
    add_log("Escaneando melhores pares para ${:.4f} disponivel...".format(budget_usdt))
    results = []
    tf      = config.get("timeframe", "5m")

    # Inclui o par configurado como prioridade
    configured = config.get("symbol", "BTC/USDT:USDT")
    candidates = [configured] + [p for p in CANDIDATE_PAIRS if p != configured]

    for symbol in candidates:
        try:
            # Verifica se o par existe na exchange
            if symbol not in exchange.markets:
                continue

            # Verifica custo minimo
            min_cost = get_min_cost(exchange, symbol)
            if min_cost > budget_usdt * 0.95:
                add_log(
                    "  {} requer ~${:.2f} (insuficiente)".format(symbol, min_cost)
                )
                continue

            # Analisa tendencia rapida
            signal, metrics, score = quick_analyze(exchange, symbol, tf)

            results.append({
                "symbol":  symbol,
                "signal":  signal,
                "score":   score,
                "metrics": metrics,
                "min_cost": min_cost,
            })

            add_log(
                "  {} | Sinal:{} | ADX:{:.1f} | Score:{:.1f}".format(
                    symbol, signal,
                    metrics.get("adx", 0),
                    score
                )
            )

            # Pequena pausa para nao sobrecarregar API
            time.sleep(0.3)

        except Exception as e:
            add_log("  Erro ao escanear {}: {}".format(symbol, str(e)[:60]))
            continue

    # Ordena por score (tendencia mais forte primeiro)
    results.sort(key=lambda x: x["score"], reverse=True)

    # Atualiza estado para o dashboard
    bot_state["scanned_pairs"] = [
        {
            "symbol":  r["symbol"],
            "signal":  r["signal"],
            "adx":     round(r["metrics"].get("adx", 0), 1),
            "trend":   r["metrics"].get("trend", "---"),
            "score":   round(r["score"], 1),
        }
        for r in results[:8]
    ]

    # Retorna apenas pares com sinal valido
    valid = [r for r in results if r["signal"] != "NONE"]

    if valid:
        add_log(
            "Melhor oportunidade: {} | Sinal: {} | Score: {:.1f}".format(
                valid[0]["symbol"],
                valid[0]["signal"],
                valid[0]["score"]
            ),
            "SUCCESS"
        )
    else:
        add_log("Nenhum par com sinal forte no momento. Aguardando...")

    return valid


# ═══════════════════════════════════════════════════
# ANALISE TECNICA
# ═══════════════════════════════════════════════════
def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    ag    = gain.ewm(com=period - 1, adjust=False).mean()
    al    = loss.ewm(com=period - 1, adjust=False).mean()
    rs    = ag / al.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def calculate_adx(df, period=14):
    try:
        high  = df["high"].astype(float)
        low   = df["low"].astype(float)
        close = df["close"].astype(float)

        plus_dm  = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm   < 0] = 0
        minus_dm[minus_dm < 0] = 0
        plus_dm[plus_dm   < minus_dm] = 0
        minus_dm[minus_dm < plus_dm]  = 0

        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low  - close.shift()).abs()
        tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr      = tr.ewm(span=period, adjust=False).mean()
        plus_di  = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, 1e-10))
        minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, 1e-10))
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
        adx      = dx.ewm(span=period, adjust=False).mean()

        return float(adx.iloc[-1]), float(plus_di.iloc[-1]), float(minus_di.iloc[-1])
    except Exception:
        return 0.0, 0.0, 0.0


def quick_analyze(exchange, symbol, timeframe):
    """
    Analisa um par e retorna (signal, metrics, score).
    Score representa a forca da oportunidade (0-100).
    """
    try:
        raw = exchange.fetch_ohlcv(symbol, timeframe, limit=150)
        if not raw or len(raw) < 60:
            return "NONE", {}, 0.0

        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["close"]  = df["close"].astype(float)
        df["high"]   = df["high"].astype(float)
        df["low"]    = df["low"].astype(float)
        df["volume"] = df["volume"].astype(float)

        ema9  = calculate_ema(df["close"], 9)
        ema21 = calculate_ema(df["close"], 21)
        ema50 = calculate_ema(df["close"], 50)
        rsi   = calculate_rsi(df["close"], 14)

        e9  = ema9.iloc[-1]
        e21 = ema21.iloc[-1]
        e50 = ema50.iloc[-1]
        r   = rsi.iloc[-1]
        p   = df["close"].iloc[-1]

        adx, plus_di, minus_di = calculate_adx(df)

        # Tendencia
        if e9 > e21 > e50:
            trend = "ALTA"
        elif e9 < e21 < e50:
            trend = "BAIXA"
        else:
            trend = "LATERAL"

        metrics = {
            "price":    round(p, 6),
            "ema_fast": round(e9, 6),
            "ema_slow": round(e21, 6),
            "rsi":      round(r, 2),
            "adx":      round(adx, 2),
            "plus_di":  round(plus_di, 2),
            "minus_di": round(minus_di, 2),
            "trend":    trend,
        }

        # Condicoes de entrada
        long_ok  = (trend == "ALTA"  and adx > 20 and plus_di  > minus_di and 40 < r < 72)
        short_ok = (trend == "BAIXA" and adx > 20 and minus_di > plus_di  and 28 < r < 60)

        if long_ok:
            # Score: quanto mais forte o ADX e melhor o RSI, maior o score
            rsi_score = (r - 40) / 32 * 30  # 0-30 pontos
            score = adx + rsi_score + (plus_di - minus_di)
            return "LONG", metrics, min(score, 100)

        if short_ok:
            rsi_score = (60 - r) / 32 * 30
            score = adx + rsi_score + (minus_di - plus_di)
            return "SHORT", metrics, min(score, 100)

        return "NONE", metrics, 0.0

    except Exception as e:
        return "NONE", {}, 0.0


# ═══════════════════════════════════════════════════
# POSICAO
# ═══════════════════════════════════════════════════
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
                    "symbol":         symbol,
                }
        return None
    except Exception as e:
        add_log("Erro ao buscar posicao: {}".format(e), "ERROR")
        return None


def open_position(exchange, config, signal, symbol, free_balance):
    try:
        ticker = exchange.fetch_ticker(symbol)
        price  = float(ticker["last"])

        pct       = float(config.get("position_size_percent", 80))
        size_usdt = free_balance * (pct / 100)

        if size_usdt < 0.5:
            size_usdt = free_balance * 0.90

        amount_base = size_usdt / price
        amount = float(exchange.amount_to_precision(symbol, amount_base))

        # Verifica minimo
        min_cost = get_min_cost(exchange, symbol)
        if amount * price < min_cost:
            market     = exchange.market(symbol)
            min_amount = float(market.get("limits", {}).get("amount", {}).get("min") or 0)
            if min_amount > 0:
                amount = min_amount

        if amount <= 0:
            add_log("Quantidade invalida: {}".format(amount), "ERROR")
            return False

        side = "buy" if signal == "LONG" else "sell"

        add_log(
            "Abrindo {} {} | Preco:{:.6f} | Qtd:{} | ~${:.4f}".format(
                signal, symbol, price, amount, amount * price
            )
        )

        exchange.create_market_order(symbol, side, amount)
        bot_state["last_signal"]  = signal
        bot_state["active_symbol"] = symbol

        add_log("Posicao {} aberta em {}!".format(signal, symbol), "SUCCESS")
        return True

    except Exception as e:
        add_log("Erro ao abrir posicao em {}: {}".format(symbol, e), "ERROR")
        return False


def close_position(exchange, position, config, reason=""):
    try:
        symbol     = position.get("symbol", config.get("_active_symbol", config["symbol"]))
        close_side = "sell" if position["side"] == "long" else "buy"

        add_log(
            "Fechando {} {} | Motivo: {} | PnL:${:.4f}".format(
                position["side"].upper(), symbol,
                reason, position["unrealized_pnl"]
            )
        )

        exchange.create_market_order(
            symbol, close_side, position["size"],
            params={"reduceOnly": True}
        )

        gross = position["unrealized_pnl"]
        fee   = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
        fees  = position["notional"] * fee * 2
        net   = gross - fees

        sess = bot_state["session"]
        sess["accumulated_profit"] += net
        sess["total_trades"]       += 1
        sess["total_fees"]         += fees

        if net >= 0:
            sess["winning_trades"] += 1
            add_log(
                "GANHO | Liq:${:.4f} | Acumulado:${:.4f}".format(
                    net, sess["accumulated_profit"]
                ),
                "SUCCESS"
            )
        else:
            sess["losing_trades"] += 1
            add_log(
                "PERDA | Liq:${:.4f} | Acumulado:${:.4f}".format(
                    net, sess["accumulated_profit"]
                ),
                "WARNING"
            )

        bot_state["active_symbol"] = "---"
        return net

    except Exception as e:
        add_log("Erro ao fechar posicao: {}".format(e), "ERROR")
        return 0.0


# ═══════════════════════════════════════════════════
# TRAILING STOP
# ═══════════════════════════════════════════════════
class PositionTracker:
    def __init__(self, profit_stop_pct):
        self.peak_pnl        = 0.0
        self.profit_stop_pct = profit_stop_pct

    def update(self, net_pnl):
        if net_pnl > self.peak_pnl:
            self.peak_pnl = net_pnl
        return self.peak_pnl

    def should_close(self, net_pnl):
        if self.peak_pnl <= 0:
            return False, ""
        drawdown = self.peak_pnl - net_pnl
        trigger  = self.peak_pnl * (self.profit_stop_pct / 100)
        if drawdown >= trigger:
            return True, "Trailing Stop | Pico:${:.4f} Atual:${:.4f} Queda:${:.4f}".format(
                self.peak_pnl, net_pnl, drawdown
            )
        return False, ""


# ═══════════════════════════════════════════════════
# STOP LOSS PADRAO
# ═══════════════════════════════════════════════════
def check_stop_loss(position, config, total_balance):
    upnl     = position["unrealized_pnl"]
    fee_rate = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
    fee_est  = position["notional"] * fee_rate
    net_pnl  = upnl - fee_est

    if net_pnl >= 0:
        return False, ""

    accumulated = bot_state["session"]["accumulated_profit"]
    min_profit  = float(config.get("min_profit_to_use_rule", 2.0))

    if accumulated >= min_profit:
        max_loss = accumulated * (float(config.get("profit_stop_percent", 1.0)) / 100)
        rule = "1% lucro acumulado"
    else:
        max_loss = total_balance * (float(config.get("initial_stop_percent", 0.5)) / 100)
        rule = "{}% capital".format(config.get("initial_stop_percent", 0.5))

    if abs(net_pnl) >= max_loss:
        return True, "Stop Loss | Perda:${:.4f} Limite:${:.4f} [{}]".format(
            abs(net_pnl), max_loss, rule
        )

    add_log(
        "Perda:${:.4f} | Limite:${:.4f} | {}".format(
            abs(net_pnl), max_loss, rule
        )
    )
    return False, ""


# ═══════════════════════════════════════════════════
# DETECTA REVERSAO DE TENDENCIA
# ═══════════════════════════════════════════════════
def detect_reversal(exchange, config, current_side, active_symbol):
    try:
        raw = exchange.fetch_ohlcv(active_symbol, config["timeframe"], limit=60)
        if not raw or len(raw) < 30:
            return False

        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["close"] = df["close"].astype(float)

        ema9  = calculate_ema(df["close"], 9)
        ema21 = calculate_ema(df["close"], 21)
        rsi   = calculate_rsi(df["close"], 14)

        e9 = ema9.iloc[-1]
        e21 = ema21.iloc[-1]
        r   = rsi.iloc[-1]

        if current_side == "long" and e9 < e21 and r < 50:
            add_log(
                "Reversao BAIXA detectada em {} | EMA9:{:.4f} < EMA21:{:.4f} RSI:{:.1f}".format(
                    active_symbol, e9, e21, r
                ),
                "WARNING"
            )
            return True

        if current_side == "short" and e9 > e21 and r > 50:
            add_log(
                "Reversao ALTA detectada em {} | EMA9:{:.4f} > EMA21:{:.4f} RSI:{:.1f}".format(
                    active_symbol, e9, e21, r
                ),
                "WARNING"
            )
            return True

        return False

    except Exception as e:
        add_log("Erro deteccao reversao: {}".format(e), "ERROR")
        return False


# ═══════════════════════════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════════════════════════
def bot_loop(config):
    add_log("=== BOT v4.0 INICIADO ===", "SUCCESS")
    bot_state["status"] = "conectando"
    tracker       = None
    active_symbol = None
    scan_counter  = 0

    try:
        exchange = create_exchange(config)

        # Saldo inicial
        bal  = get_balance(exchange, config["exchange_id"])
        sess = bot_state["session"]
        sess["initial_balance"] = bal["total"]
        sess["current_balance"] = bal["total"]
        sess["start_time"]      = datetime.now().strftime("%d/%m/%Y %H:%M")

        add_log(
            "Saldo: Total=${:.4f} | Livre=${:.4f} [{}]".format(
                bal["total"], bal["free"], bal.get("account", "?")
            )
        )

        if bal["total"] < 0.5:
            add_log(
                "ATENCAO: Saldo ${:.4f} muito baixo. "
                "Deposite USDT na conta Futuros.".format(bal["total"]),
                "WARNING"
            )

        state        = "SCANNING"
        cooldown_end = 0.0
        best_pairs   = []

        # ════════ LOOP ════════════════════════════════════
        while not stop_event.is_set():
            try:
                bal = get_balance(exchange, config["exchange_id"])
                sess["current_balance"] = bal["total"]

                # Saldo efetivo (considera Bybit Unified)
                effective = bal["free"]
                if effective < 0.5 and bal["total"] > 0.5:
                    effective = bal["total"] * 0.95

                # ─── SCANNING: busca melhores pares ────────
                if state == "SCANNING":
                    bot_state["status"] = "escaneando pares"
                    scan_counter += 1

                    best_pairs = scan_best_pairs(exchange, effective, config)

                    if best_pairs:
                        # Pega o melhor par
                        best       = best_pairs[0]
                        active_symbol = best["symbol"]
                        signal     = best["signal"]
                        metrics    = best["metrics"]

                        # Atualiza indicadores no dashboard
                        bot_state["indicators"] = {
                            "price":    metrics.get("price", 0),
                            "ema_fast": metrics.get("ema_fast", 0),
                            "ema_slow": metrics.get("ema_slow", 0),
                            "rsi":      metrics.get("rsi", 0),
                            "adx":      metrics.get("adx", 0),
                            "trend":    metrics.get("trend", "---"),
                        }

                        # Configura alavancagem para o par escolhido
                        set_leverage_safe(
                            exchange,
                            int(config.get("leverage", 3)),
                            active_symbol
                        )

                        add_log(
                            "Abrindo {} em {} | Score:{:.1f}".format(
                                signal, active_symbol, best["score"]
                            ),
                            "SUCCESS"
                        )

                        ok = open_position(
                            exchange, config, signal,
                            active_symbol, effective
                        )

                        if ok:
                            profit_stop_pct = float(
                                config.get("profit_stop_percent", 1.0)
                            )
                            tracker = PositionTracker(profit_stop_pct)
                            state   = "IN_POSITION"
                            bot_state["status"] = "em posicao"
                        else:
                            # Falhou: espera e tenta proximo ciclo
                            add_log("Aguardando proximo sinal...", "WARNING")
                            state = "ANALYZING"
                    else:
                        state = "ANALYZING"

                # ─── ANALYZING: analisa sem escanear todos ──
                elif state == "ANALYZING":
                    bot_state["status"] = "analisando"

                    # Re-escaneia a cada 6 ciclos (~1 min com 10s de intervalo)
                    scan_counter += 1
                    if scan_counter >= 6:
                        scan_counter = 0
                        state = "SCANNING"
                        continue

                    # Enquanto isso, analisa o par configurado
                    sym    = config.get("symbol", "BTC/USDT:USDT")
                    signal, metrics, score = quick_analyze(
                        exchange, sym, config["timeframe"]
                    )

                    bot_state["indicators"] = {
                        "price":    metrics.get("price", 0),
                        "ema_fast": metrics.get("ema_fast", 0),
                        "ema_slow": metrics.get("ema_slow", 0),
                        "rsi":      metrics.get("rsi", 0),
                        "adx":      metrics.get("adx", 0),
                        "trend":    metrics.get("trend", "---"),
                    }

                    add_log(
                        "{} P:{:.4f} EMA9:{:.4f} EMA21:{:.4f} "
                        "RSI:{:.1f} ADX:{:.1f} [{}]".format(
                            sym,
                            metrics.get("price", 0),
                            metrics.get("ema_fast", 0),
                            metrics.get("ema_slow", 0),
                            metrics.get("rsi", 0),
                            metrics.get("adx", 0),
                            metrics.get("trend", "---")
                        )
                    )

                    if signal != "NONE" and score > 30:
                        state = "SCANNING"

                # ─── IN_POSITION: monitora posicao ──────────
                elif state == "IN_POSITION":
                    bot_state["status"] = "em posicao"
                    sym_pos  = active_symbol or config.get("symbol")
                    position = get_position(exchange, sym_pos)

                    if not position:
                        add_log("Posicao encerrada externamente.", "WARNING")
                        bot_state["position"]    = None
                        bot_state["active_symbol"] = "---"
                        tracker       = None
                        active_symbol = None
                        scan_counter  = 0
                        state         = "SCANNING"
                        continue

                    bot_state["position"] = position

                    # PnL liquido
                    upnl     = position["unrealized_pnl"]
                    fee_rate = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
                    fee_est  = position["notional"] * fee_rate
                    net_pnl  = upnl - fee_est

                    # Atualiza pico
                    peak = tracker.update(net_pnl)

                    add_log(
                        "PnL:${:.4f} | Pico:${:.4f} | "
                        "{} | {}".format(
                            net_pnl, peak,
                            sym_pos,
                            position["side"].upper()
                        )
                    )

                    fechou = False
                    motivo = ""

                    # 1. Trailing stop
                    close_t, mot_t = tracker.should_close(net_pnl)
                    if close_t:
                        fechou = True
                        motivo = mot_t

                    # 2. Stop loss padrao
                    if not fechou:
                        close_s, mot_s = check_stop_loss(
                            position, config, bal["total"]
                        )
                        if close_s:
                            fechou = True
                            motivo = mot_s

                    # 3. Reversao de tendencia
                    if not fechou:
                        if detect_reversal(
                            exchange, config,
                            position["side"], sym_pos
                        ):
                            fechou = True
                            motivo = "Reversao de tendencia"

                    if fechou:
                        add_log("FECHANDO: {}".format(motivo), "WARNING")
                        close_position(exchange, position, config, motivo)
                        bot_state["position"]    = None
                        bot_state["active_symbol"] = "---"
                        tracker       = None
                        active_symbol = None
                        scan_counter  = 0
                        cooldown_end  = time.time() + int(
                            config.get("cooldown_seconds", 30)
                        )
                        state = "COOLDOWN"

                # ─── COOLDOWN ────────────────────────────────
                elif state == "COOLDOWN":
                    remaining = max(0.0, cooldown_end - time.time())
                    bot_state["status"] = "cooldown ({}s)".format(int(remaining))
                    if remaining <= 0:
                        add_log("Cooldown encerrado. Escaneando mercado...")
                        bot_state["last_signal"] = "---"
                        scan_counter = 0
                        state = "SCANNING"

            except ccxt.NetworkError as e:
                add_log("Erro de rede: {}".format(e), "ERROR")
                time.sleep(20)
            except ccxt.ExchangeError as e:
                add_log("Erro exchange: {}".format(e), "ERROR")
                time.sleep(15)
            except Exception as e:
                add_log("Erro loop: {}".format(e), "ERROR")
                time.sleep(10)

            time.sleep(int(config.get("loop_interval", 10)))

    except Exception as e:
        add_log("Erro critico: {}".format(e), "ERROR")
    finally:
        bot_state["running"]       = False
        bot_state["status"]        = "parado"
        bot_state["position"]      = None
        bot_state["active_symbol"] = "---"
        add_log("=== BOT ENCERRADO ===")


# ═══════════════════════════════════════════════════
# ROTAS FLASK
# ═══════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config/full")
def get_config_full():
    return jsonify(load_config())


@app.route("/api/save-config", methods=["POST"])
def save_config_route():
    data = request.json or {}
    if not data.get("api_key") or not data.get("api_secret"):
        return jsonify({"error": "API Key e Secret sao obrigatorios"}), 400
    save_config(data)
    bot_state["config"] = data
    return jsonify({"success": True, "message": "Configuracoes salvas!"})


@app.route("/api/start", methods=["POST"])
def start_bot():
    global bot_thread, stop_event

    if bot_state["running"]:
        return jsonify({"error": "Bot ja esta rodando!"}), 400

    data = request.json or {}
    saved = load_config()
    for k, v in saved.items():
        if not data.get(k):
            data[k] = v

    for campo in ["api_key", "api_secret", "exchange_id", "symbol"]:
        if not data.get(campo):
            return jsonify({
                "error": "Configure e salve as credenciais na aba Configuracoes."
            }), 400

    save_config(data)

    bot_state.update({
        "running":       True,
        "logs":          [],
        "position":      None,
        "last_signal":   "---",
        "active_symbol": "---",
        "config":        data,
        "scanned_pairs": [],
        "indicators": {
            "price": 0.0, "ema_fast": 0.0,
            "ema_slow": 0.0, "rsi": 0.0,
            "adx": 0.0, "trend": "---",
        },
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
    bot_thread = threading.Thread(target=bot_loop, args=(data,), daemon=True)
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
    return jsonify({"success": True})


@app.route("/api/status")
def get_status():
    return jsonify({
        "running":        bot_state["running"],
        "status":         bot_state["status"],
        "session":        bot_state["session"],
        "position":       bot_state["position"],
        "last_signal":    bot_state["last_signal"],
        "active_symbol":  bot_state["active_symbol"],
        "indicators":     bot_state["indicators"],
        "logs":           bot_state["logs"][-60:],
        "scanned_pairs":  bot_state["scanned_pairs"],
        "has_config":     bool(load_config().get("api_key")),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
