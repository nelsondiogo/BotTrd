"""
Crypto Futures Trading Bot - Preservacao de Lucro
Versao: 4.1.0 - Multi-Par + Grafico Tempo Real
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
    "running":       False,
    "status":        "parado",
    "logs":          [],
    "config":        saved_config,
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
    "position":      None,
    "last_signal":   "---",
    "active_symbol": "---",
    "indicators": {
        "price":    0.0,
        "ema_fast": 0.0,
        "ema_slow": 0.0,
        "rsi":      0.0,
        "adx":      0.0,
        "trend":    "---",
    },
    "scanned_pairs": [],
    "chart_data":    [],
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
            return _raw_balance(exchange.fetch_balance())

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
            add_log("Portfolio Margin: alavancagem auto pela exchange.", "WARNING")
        elif "leverage not modified" in err.lower():
            add_log("Alavancagem ja configurada.")
        else:
            add_log("Aviso alavancagem: {}".format(err[:100]), "WARNING")


# ═══════════════════════════════════════════════════
# DADOS DO GRAFICO
# ═══════════════════════════════════════════════════
def update_chart_data(exchange, symbol, timeframe):
    """
    Busca os ultimos 60 candles e prepara dados
    para o grafico de velas (candlestick).
    """
    try:
        raw = exchange.fetch_ohlcv(symbol, timeframe, limit=60)
        if not raw:
            return

        candles = []
        for c in raw:
            candles.append({
                "t": c[0],           # timestamp ms
                "o": float(c[1]),    # open
                "h": float(c[2]),    # high
                "l": float(c[3]),    # low
                "c": float(c[4]),    # close
                "v": float(c[5]),    # volume
            })

        bot_state["chart_data"] = candles

    except Exception as e:
        add_log("Erro ao atualizar grafico: {}".format(e), "ERROR")


# ═══════════════════════════════════════════════════
# PARES CANDIDATOS
# ═══════════════════════════════════════════════════
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
        plus_di  = 100 * (plus_dm.ewm(span=period, adjust=False).mean()
                          / atr.replace(0, 1e-10))
        minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean()
                          / atr.replace(0, 1e-10))
        dx       = (100 * (plus_di - minus_di).abs()
                    / (plus_di + minus_di).replace(0, 1e-10))
        adx      = dx.ewm(span=period, adjust=False).mean()

        return float(adx.iloc[-1]), float(plus_di.iloc[-1]), float(minus_di.iloc[-1])
    except Exception:
        return 0.0, 0.0, 0.0


def quick_analyze(exchange, symbol, timeframe):
    """
    Analisa tendencia e retorna (signal, metrics, score).
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

        if e9 > e21 > e50:
            trend = "ALTA"
        elif e9 < e21 < e50:
            trend = "BAIXA"
        else:
            trend = "LATERAL"

        metrics = {
            "price":    round(p, 6),
            "ema_fast": round(e9,  6),
            "ema_slow": round(e21, 6),
            "ema50":    round(e50, 6),
            "rsi":      round(r, 2),
            "adx":      round(adx, 2),
            "plus_di":  round(plus_di,  2),
            "minus_di": round(minus_di, 2),
            "trend":    trend,
        }

        long_ok  = (trend == "ALTA"  and adx > 20
                    and plus_di  > minus_di and 40 < r < 72)
        short_ok = (trend == "BAIXA" and adx > 20
                    and minus_di > plus_di  and 28 < r < 60)

        if long_ok:
            rsi_score = (r - 40) / 32 * 30
            score = adx + rsi_score + (plus_di - minus_di)
            return "LONG", metrics, min(score, 100)

        if short_ok:
            rsi_score = (60 - r) / 32 * 30
            score = adx + rsi_score + (minus_di - plus_di)
            return "SHORT", metrics, min(score, 100)

        return "NONE", metrics, 0.0

    except Exception:
        return "NONE", {}, 0.0


def scan_best_pairs(exchange, budget_usdt, config):
    add_log("Escaneando pares para ${:.4f}...".format(budget_usdt))
    results  = []
    tf       = config.get("timeframe", "5m")
    configured = config.get("symbol", "DOGE/USDT:USDT")
    candidates = [configured] + [p for p in CANDIDATE_PAIRS if p != configured]

    for symbol in candidates:
        try:
            if symbol not in exchange.markets:
                continue
            min_cost = get_min_cost(exchange, symbol)
            if min_cost > budget_usdt * 0.95:
                continue

            signal, metrics, score = quick_analyze(exchange, symbol, tf)
            results.append({
                "symbol":   symbol,
                "signal":   signal,
                "score":    score,
                "metrics":  metrics,
                "min_cost": min_cost,
            })
            add_log("  {} | {} | ADX:{:.1f} | Score:{:.1f}".format(
                symbol, signal, metrics.get("adx", 0), score
            ))
            time.sleep(0.3)

        except Exception as e:
            add_log("  Erro {}: {}".format(symbol, str(e)[:50]))
            continue

    results.sort(key=lambda x: x["score"], reverse=True)

    bot_state["scanned_pairs"] = [
        {
            "symbol": r["symbol"],
            "signal": r["signal"],
            "adx":    round(r["metrics"].get("adx", 0), 1),
            "trend":  r["metrics"].get("trend", "---"),
            "score":  round(r["score"], 1),
            "rsi":    round(r["metrics"].get("rsi", 0), 1),
            "price":  r["metrics"].get("price", 0),
        }
        for r in results[:10]
    ]

    valid = [r for r in results if r["signal"] != "NONE"]

    if valid:
        add_log("Melhor: {} | {} | Score:{:.1f}".format(
            valid[0]["symbol"], valid[0]["signal"], valid[0]["score"]
        ), "SUCCESS")

    return valid


# ═══════════════════════════════════════════════════
# GESTAO DE POSICAO
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
        add_log("Erro posicao: {}".format(e), "ERROR")
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

        market     = exchange.market(symbol)
        min_amount = float(market.get("limits", {}).get("amount", {}).get("min") or 0)
        if min_amount > 0 and amount < min_amount:
            amount = min_amount

        if amount <= 0:
            add_log("Quantidade invalida: {}".format(amount), "ERROR")
            return False

        side = "buy" if signal == "LONG" else "sell"

        add_log("Abrindo {} {} | Preco:{:.6f} | Qtd:{} | ~${:.4f}".format(
            signal, symbol, price, amount, amount * price
        ))

        exchange.create_market_order(symbol, side, amount)
        bot_state["last_signal"]   = signal
        bot_state["active_symbol"] = symbol

        add_log("Posicao {} aberta em {}!".format(signal, symbol), "SUCCESS")
        return True

    except Exception as e:
        add_log("Erro ao abrir em {}: {}".format(symbol, e), "ERROR")
        return False


def close_position(exchange, position, config, reason=""):
    try:
        symbol     = position.get("symbol", config.get("symbol"))
        close_side = "sell" if position["side"] == "long" else "buy"

        add_log("Fechando {} {} | {} | PnL:${:.6f}".format(
            position["side"].upper(), symbol,
            reason, position["unrealized_pnl"]
        ))

        exchange.create_market_order(
            symbol, close_side, position["size"],
            params={"reduceOnly": True}
        )

        gross    = position["unrealized_pnl"]
        fee_rate = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
        fees     = position["notional"] * fee_rate * 2
        net      = gross - fees

        sess = bot_state["session"]
        sess["accumulated_profit"] += net
        sess["total_trades"]       += 1
        sess["total_fees"]         += fees

        if net >= 0:
            sess["winning_trades"] += 1
            add_log("GANHO | Liq:${:.6f} | Acum:${:.6f}".format(
                net, sess["accumulated_profit"]
            ), "SUCCESS")
        else:
            sess["losing_trades"] += 1
            add_log("PERDA | Liq:${:.6f} | Acum:${:.6f}".format(
                net, sess["accumulated_profit"]
            ), "WARNING")

        bot_state["active_symbol"] = "---"
        return net

    except Exception as e:
        add_log("Erro ao fechar: {}".format(e), "ERROR")
        return 0.0


# ═══════════════════════════════════════════════════
# TRAILING STOP
# ═══════════════════════════════════════════════════
class PositionTracker:
    def __init__(self, profit_stop_pct):
        self.peak_pnl            = 0.0
        self.profit_stop_pct     = profit_stop_pct
        self.min_profit_to_trail = 0.001

    def update(self, net_pnl):
        if net_pnl > self.peak_pnl:
            self.peak_pnl = net_pnl
        return self.peak_pnl

    def should_close(self, net_pnl):
        if self.peak_pnl < self.min_profit_to_trail:
            return False, ""

        drawdown = self.peak_pnl - net_pnl
        trigger  = self.peak_pnl * (self.profit_stop_pct / 100)

        if drawdown >= trigger:
            return True, (
                "Trailing Stop | Pico:${:.6f} "
                "Atual:${:.6f} Queda:${:.6f}".format(
                    self.peak_pnl, net_pnl, drawdown
                )
            )
        return False, ""


# ═══════════════════════════════════════════════════
# STOP LOSS
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
        max_loss = max(
            total_balance * (float(config.get("initial_stop_percent", 0.5)) / 100),
            0.003
        )
        rule = "{}% capital".format(config.get("initial_stop_percent", 0.5))

    abs_loss = abs(net_pnl)

    add_log("PnL:${:.6f} | Perda:${:.6f} | Limite:${:.6f} | {}".format(
        net_pnl, abs_loss, max_loss, rule
    ))

    if abs_loss >= max_loss:
        return True, "Stop Loss | Perda:${:.6f} >= Limite:${:.6f} [{}]".format(
            abs_loss, max_loss, rule
        )
    return False, ""


# ═══════════════════════════════════════════════════
# REVERSAO
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

        e9  = ema9.iloc[-1]
        e21 = ema21.iloc[-1]
        r   = rsi.iloc[-1]

        if current_side == "long" and e9 < e21 and r < 50:
            add_log("Reversao BAIXA em {} | RSI:{:.1f}".format(
                active_symbol, r), "WARNING")
            return True

        if current_side == "short" and e9 > e21 and r > 50:
            add_log("Reversao ALTA em {} | RSI:{:.1f}".format(
                active_symbol, r), "WARNING")
            return True

        return False

    except Exception as e:
        add_log("Erro reversao: {}".format(e), "ERROR")
        return False


# ═══════════════════════════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════════════════════════
def bot_loop(config):
    add_log("=== BOT v4.1 INICIADO ===", "SUCCESS")
    bot_state["status"] = "conectando"
    tracker       = None
    active_symbol = None
    scan_counter  = 0
    chart_counter = 0

    try:
        exchange = create_exchange(config)

        bal  = get_balance(exchange, config["exchange_id"])
        sess = bot_state["session"]
        sess["initial_balance"] = bal["total"]
        sess["current_balance"] = bal["total"]
        sess["start_time"]      = datetime.now().strftime("%d/%m/%Y %H:%M")

        add_log("Saldo: ${:.4f} | Livre:${:.4f} [{}]".format(
            bal["total"], bal["free"], bal.get("account", "?")
        ))

        if bal["total"] < 0.5:
            add_log("Saldo baixo: ${:.4f}. Deposite USDT.".format(
                bal["total"]), "WARNING")

        state        = "SCANNING"
        cooldown_end = 0.0
        best_pairs   = []

        while not stop_event.is_set():
            try:
                bal = get_balance(exchange, config["exchange_id"])
                sess["current_balance"] = bal["total"]

                effective = bal["free"]
                if effective < 0.5 and bal["total"] > 0.5:
                    effective = bal["total"] * 0.95

                # Atualiza grafico a cada 3 ciclos (~30s)
                chart_counter += 1
                sym_for_chart = (
                    active_symbol if active_symbol
                    else config.get("symbol", "DOGE/USDT:USDT")
                )
                if chart_counter >= 3:
                    chart_counter = 0
                    update_chart_data(exchange, sym_for_chart, config["timeframe"])

                # ─── SCANNING ───────────────────────────
                if state == "SCANNING":
                    bot_state["status"] = "escaneando pares"
                    scan_counter += 1
                    best_pairs = scan_best_pairs(exchange, effective, config)

                    if best_pairs:
                        best          = best_pairs[0]
                        active_symbol = best["symbol"]
                        signal        = best["signal"]
                        metrics       = best["metrics"]

                        bot_state["indicators"] = {
                            "price":    metrics.get("price", 0),
                            "ema_fast": metrics.get("ema_fast", 0),
                            "ema_slow": metrics.get("ema_slow", 0),
                            "rsi":      metrics.get("rsi", 0),
                            "adx":      metrics.get("adx", 0),
                            "trend":    metrics.get("trend", "---"),
                        }

                        set_leverage_safe(
                            exchange,
                            int(config.get("leverage", 3)),
                            active_symbol
                        )

                        # Atualiza grafico do par escolhido
                        update_chart_data(
                            exchange, active_symbol, config["timeframe"]
                        )

                        ok = open_position(
                            exchange, config, signal,
                            active_symbol, effective
                        )

                        if ok:
                            tracker = PositionTracker(
                                float(config.get("profit_stop_percent", 1.0))
                            )
                            state = "IN_POSITION"
                            bot_state["status"] = "em posicao"
                        else:
                            state = "ANALYZING"
                    else:
                        state = "ANALYZING"

                # ─── ANALYZING ───────────────────────────
                elif state == "ANALYZING":
                    bot_state["status"] = "analisando"
                    scan_counter += 1

                    if scan_counter >= 6:
                        scan_counter = 0
                        state = "SCANNING"
                        continue

                    sym    = config.get("symbol", "DOGE/USDT:USDT")
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

                    add_log("{} P:{:.6f} RSI:{:.1f} ADX:{:.1f} [{}]".format(
                        sym, metrics.get("price", 0),
                        metrics.get("rsi", 0),
                        metrics.get("adx", 0),
                        metrics.get("trend", "---")
                    ))

                    if signal != "NONE" and score > 30:
                        state = "SCANNING"

                # ─── IN_POSITION ─────────────────────────
                elif state == "IN_POSITION":
                    bot_state["status"] = "em posicao"
                    sym_pos  = active_symbol or config.get("symbol")
                    position = get_position(exchange, sym_pos)

                    # Atualiza grafico do par em posicao
                    update_chart_data(exchange, sym_pos, config["timeframe"])

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

                    upnl     = position["unrealized_pnl"]
                    fee_rate = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
                    fee_est  = position["notional"] * fee_rate
                    net_pnl  = upnl - fee_est
                    peak     = tracker.update(net_pnl)

                    add_log("PnL:${:.6f} | Pico:${:.6f} | {} {}".format(
                        net_pnl, peak, sym_pos,
                        position["side"].upper()
                    ))

                    fechou = False
                    motivo = ""

                    close_t, mot_t = tracker.should_close(net_pnl)
                    if close_t:
                        fechou = True
                        motivo = mot_t

                    if not fechou:
                        close_s, mot_s = check_stop_loss(
                            position, config, bal["total"]
                        )
                        if close_s:
                            fechou = True
                            motivo = mot_s

                    if not fechou:
                        if detect_reversal(
                            exchange, config, position["side"], sym_pos
                        ):
                            fechou = True
                            motivo = "Reversao de tendencia"

                    if fechou:
                        add_log("FECHANDO: {}".format(motivo), "WARNING")
                        close_position(exchange, position, config, motivo)
                        bot_state["position"]      = None
                        bot_state["active_symbol"] = "---"
                        tracker       = None
                        active_symbol = None
                        scan_counter  = 0
                        cooldown_end  = time.time() + int(
                            config.get("cooldown_seconds", 30)
                        )
                        state = "COOLDOWN"

                # ─── COOLDOWN ────────────────────────────
                elif state == "COOLDOWN":
                    remaining = max(0.0, cooldown_end - time.time())
                    bot_state["status"] = "cooldown ({}s)".format(int(remaining))
                    if remaining <= 0:
                        add_log("Cooldown encerrado. Escaneando...")
                        bot_state["last_signal"] = "---"
                        scan_counter = 0
                        state = "SCANNING"

            except ccxt.NetworkError as e:
                add_log("Erro rede: {}".format(e), "ERROR")
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

    data  = request.json or {}
    saved = load_config()
    for k, v in saved.items():
        if not data.get(k):
            data[k] = v

    for campo in ["api_key", "api_secret", "exchange_id", "symbol"]:
        if not data.get(campo):
            return jsonify({
                "error": "Configure e salve as credenciais primeiro."
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
        "chart_data":    [],
        "indicators": {
            "price": 0.0, "ema_fast": 0.0, "ema_slow": 0.0,
            "rsi": 0.0, "adx": 0.0, "trend": "---",
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
        "running":       bot_state["running"],
        "status":        bot_state["status"],
        "session":       bot_state["session"],
        "position":      bot_state["position"],
        "last_signal":   bot_state["last_signal"],
        "active_symbol": bot_state["active_symbol"],
        "indicators":    bot_state["indicators"],
        "logs":          bot_state["logs"][-60:],
        "scanned_pairs": bot_state["scanned_pairs"],
        "chart_data":    bot_state["chart_data"],
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
