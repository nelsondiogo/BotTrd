"""
Crypto Futures Trading Bot - Preservacao de Lucro
Versao: 3.0.0 - Producao
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

# ═══════════════════════════════════════════════════
# PERSISTENCIA DE CONFIGURACOES
# ═══════════════════════════════════════════════════
CONFIG_FILE = "bot_config.json"


def save_config(config):
    """Salva configuracoes em arquivo (persistente entre reinicializacoes)."""
    try:
        safe = {k: v for k, v in config.items()}
        with open(CONFIG_FILE, "w") as f:
            json.dump(safe, f, indent=2)
    except Exception as e:
        print("Erro ao salvar config: {}".format(e))


def load_config():
    """Carrega configuracoes salvas anteriormente."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print("Erro ao carregar config: {}".format(e))
    return {}


# ═══════════════════════════════════════════════════
# ESTADO GLOBAL
# ═══════════════════════════════════════════════════
saved_config = load_config()

bot_state = {
    "running":     False,
    "status":      "parado",
    "logs":        [],
    "config":      saved_config,
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
        "trend":    "---",
    },
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
            "apiKey": config["api_key"],
            "secret": config["api_secret"],
            "enableRateLimit": True,
            "options": {
                "defaultType": "linear",
                "recvWindow":  10000,
            },
        }
    else:
        params = {
            "apiKey": config["api_key"],
            "secret": config["api_secret"],
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
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
                        return {"total": total, "free": free,
                                "account_type": acc}
                except Exception:
                    continue
            # raw fallback
            bal = exchange.fetch_balance()
            return _raw_balance(bal)

        bal   = exchange.fetch_balance()
        usdt  = bal.get("USDT", {})
        total = float(usdt.get("total") or 0)
        free  = float(usdt.get("free")  or 0)
        if total > 0:
            return {"total": total, "free": free, "account_type": "DEFAULT"}
        return _raw_balance(bal)

    except Exception as e:
        add_log("Erro saldo: {}".format(e), "ERROR")
        return {"total": 0.0, "free": 0.0, "account_type": "?"}


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
                        return {"total": total, "free": free,
                                "account_type": "RAW"}
    except Exception:
        pass
    return {"total": 0.0, "free": 0.0, "account_type": "?"}


# ═══════════════════════════════════════════════════
# ALAVANCAGEM
# ═══════════════════════════════════════════════════
def set_leverage_safe(exchange, leverage, symbol):
    try:
        exchange.set_leverage(leverage, symbol)
        add_log("Alavancagem: {}x".format(leverage))
    except Exception as e:
        err = str(e)
        if "110077" in err or "pm mode" in err.lower():
            add_log("Portfolio Margin: alavancagem auto pela exchange.", "WARNING")
        elif "leverage not modified" in err.lower():
            add_log("Alavancagem ja configurada.")
        else:
            add_log("Aviso alavancagem: {}".format(err[:100]), "WARNING")


# ═══════════════════════════════════════════════════
# ANALISE TECNICA - TENDENCIA + MOMENTUM
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
    """Average Directional Index - forca da tendencia."""
    high  = df["high"].astype(float)
    low   = df["low"].astype(float)
    close = df["close"].astype(float)

    plus_dm  = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm  < 0] = 0
    minus_dm[minus_dm < 0] = 0
    mask = plus_dm < minus_dm
    plus_dm[mask]  = 0
    mask2 = minus_dm < plus_dm
    minus_dm[mask2] = 0

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low  - close.shift()).abs()
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr      = tr.ewm(span=period, adjust=False).mean()
    plus_di  = 100 * (plus_dm.ewm(span=period, adjust=False).mean()  / atr)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)
    dx       = (100 * (plus_di - minus_di).abs() /
                (plus_di + minus_di).replace(0, 1e-10))
    adx      = dx.ewm(span=period, adjust=False).mean()
    return adx.iloc[-1], plus_di.iloc[-1], minus_di.iloc[-1]


def analyze_market(exchange, config):
    """
    Estrategia de Tendencia Profissional:

    ENTRADA LONG:
      - EMA9 > EMA21 > EMA50 (alinhamento de alta)
      - ADX > 20 (tendencia forte)
      - +DI > -DI (pressao compradora)
      - RSI entre 40-70 (momentum de alta sem sobrecompra)

    ENTRADA SHORT:
      - EMA9 < EMA21 < EMA50 (alinhamento de baixa)
      - ADX > 20 (tendencia forte)
      - -DI > +DI (pressao vendedora)
      - RSI entre 30-60 (momentum de baixa sem sobrevenda)

    SAIDA:
      - Reversao da tendencia (EMA cross oposto)
      - OU perda de 1% do lucro obtido na posicao
    """
    try:
        raw = exchange.fetch_ohlcv(
            config["symbol"],
            config["timeframe"],
            limit=150
        )
        if not raw or len(raw) < 60:
            add_log("Aguardando dados suficientes...", "WARNING")
            return "NONE", {}

        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["close"] = df["close"].astype(float)
        df["high"]  = df["high"].astype(float)
        df["low"]   = df["low"].astype(float)

        # Indicadores
        ema9  = calculate_ema(df["close"], 9)
        ema21 = calculate_ema(df["close"], 21)
        ema50 = calculate_ema(df["close"], 50)
        rsi   = calculate_rsi(df["close"], 14)

        e9  = ema9.iloc[-1]
        e21 = ema21.iloc[-1]
        e50 = ema50.iloc[-1]
        r   = rsi.iloc[-1]
        p   = df["close"].iloc[-1]

        # ADX para forca da tendencia
        adx, plus_di, minus_di = calculate_adx(df)

        # Determina tendencia macro
        if e9 > e21 > e50:
            trend_label = "ALTA"
        elif e9 < e21 < e50:
            trend_label = "BAIXA"
        else:
            trend_label = "LATERAL"

        # Atualiza dashboard
        bot_state["indicators"] = {
            "price":    round(p, 2),
            "ema_fast": round(e9, 2),
            "ema_slow": round(e21, 2),
            "rsi":      round(r, 2),
            "trend":    trend_label,
            "adx":      round(adx, 2),
        }

        add_log(
            "P:{:.2f} EMA9:{:.2f} EMA21:{:.2f} EMA50:{:.2f} "
            "RSI:{:.1f} ADX:{:.1f} [{}]".format(
                p, e9, e21, e50, r, adx, trend_label
            )
        )

        metrics = {
            "price": p, "ema9": e9, "ema21": e21, "ema50": e50,
            "rsi": r, "adx": adx, "plus_di": plus_di, "minus_di": minus_di,
            "trend": trend_label,
        }

        # ── SINAL LONG ──────────────────────────────────
        # Condicoes: alinhamento de alta + ADX forte + RSI ok
        long_ema   = e9 > e21 and e21 > e50
        long_adx   = adx > 20 and plus_di > minus_di
        long_rsi   = 40 < r < 72
        long_signal = long_ema and long_adx and long_rsi

        # ── SINAL SHORT ─────────────────────────────────
        short_ema   = e9 < e21 and e21 < e50
        short_adx   = adx > 20 and minus_di > plus_di
        short_rsi   = 28 < r < 60
        short_signal = short_ema and short_adx and short_rsi

        if long_signal:
            add_log(
                "SINAL LONG | EMA:{} ADX:{:.1f} +DI:{:.1f} RSI:{:.1f}".format(
                    trend_label, adx, plus_di, r
                ),
                "SUCCESS"
            )
            return "LONG", metrics

        if short_signal:
            add_log(
                "SINAL SHORT | EMA:{} ADX:{:.1f} -DI:{:.1f} RSI:{:.1f}".format(
                    trend_label, adx, minus_di, r
                ),
                "SUCCESS"
            )
            return "SHORT", metrics

        # Log detalhado do motivo de nao entrar
        reasons = []
        if trend_label == "LATERAL":
            reasons.append("mercado lateral")
        if adx <= 20:
            reasons.append("ADX fraco ({:.1f})".format(adx))
        if not (40 < r < 72) and not (28 < r < 60):
            reasons.append("RSI neutro ({:.1f})".format(r))

        add_log(
            "Sem sinal | {} | {}".format(
                trend_label,
                " | ".join(reasons) if reasons else "aguardando alinhamento"
            )
        )
        return "NONE", metrics

    except Exception as e:
        add_log("Erro analise: {}".format(e), "ERROR")
        return "NONE", {}


# ═══════════════════════════════════════════════════
# DETECTA REVERSAO DE TENDENCIA
# ═══════════════════════════════════════════════════
def detect_reversal(exchange, config, current_side):
    """
    Verifica se a tendencia reverteu contra a posicao atual.
    Retorna True se deve fechar a posicao por reversao.
    """
    try:
        raw = exchange.fetch_ohlcv(
            config["symbol"],
            config["timeframe"],
            limit=60
        )
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

        # Reversao para LONG: EMA9 cruzou abaixo da EMA21
        if current_side == "long":
            if e9 < e21 and r < 50:
                add_log(
                    "REVERSAO DETECTADA: Tendencia virou BAIXA "
                    "(EMA9 < EMA21, RSI:{:.1f})".format(r),
                    "WARNING"
                )
                return True

        # Reversao para SHORT: EMA9 cruzou acima da EMA21
        elif current_side == "short":
            if e9 > e21 and r > 50:
                add_log(
                    "REVERSAO DETECTADA: Tendencia virou ALTA "
                    "(EMA9 > EMA21, RSI:{:.1f})".format(r),
                    "WARNING"
                )
                return True

        return False

    except Exception as e:
        add_log("Erro deteccao reversao: {}".format(e), "ERROR")
        return False


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
                }
        return None
    except Exception as e:
        add_log("Erro posicao: {}".format(e), "ERROR")
        return None


def open_position(exchange, config, signal, free_balance):
    try:
        ticker = exchange.fetch_ticker(config["symbol"])
        price  = float(ticker["last"])

        pct       = float(config.get("position_size_percent", 50))
        size_usdt = free_balance * (pct / 100)

        # Garante tamanho minimo
        if size_usdt < 1.0:
            size_usdt = free_balance * 0.90  # usa 90% do disponivel

        amount_base = size_usdt / price
        amount = float(
            exchange.amount_to_precision(config["symbol"], amount_base)
        )

        if amount <= 0:
            add_log("Quantidade invalida: {}".format(amount), "ERROR")
            return False

        side = "buy" if signal == "LONG" else "sell"

        add_log(
            "Abrindo {} | Preco:{:.2f} | Qtd:{} | Valor:${:.4f}".format(
                signal, price, amount, size_usdt
            )
        )

        exchange.create_market_order(config["symbol"], side, amount)
        bot_state["last_signal"] = signal
        add_log("Posicao {} aberta!".format(signal), "SUCCESS")
        return True

    except Exception as e:
        add_log("Erro ao abrir posicao: {}".format(e), "ERROR")
        return False


def close_position(exchange, position, config, reason=""):
    try:
        close_side = "sell" if position["side"] == "long" else "buy"

        add_log(
            "Fechando {} | Motivo: {} | PnL:${:.4f}".format(
                position["side"].upper(),
                reason,
                position["unrealized_pnl"]
            )
        )

        exchange.create_market_order(
            config["symbol"],
            close_side,
            position["size"],
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
                "GANHO | Liquido:${:.4f} | Acumulado:${:.4f}".format(
                    net, sess["accumulated_profit"]
                ),
                "SUCCESS"
            )
        else:
            sess["losing_trades"] += 1
            add_log(
                "PERDA | Liquido:${:.4f} | Acumulado:${:.4f}".format(
                    net, sess["accumulated_profit"]
                ),
                "WARNING"
            )

        return net

    except Exception as e:
        add_log("Erro ao fechar posicao: {}".format(e), "ERROR")
        return 0.0


# ═══════════════════════════════════════════════════
# GESTAO DE RISCO - NUCLEO DO BOT
# ═══════════════════════════════════════════════════
def check_stop_loss(position, config, session_balance):
    """
    Logica central de preservacao de lucro:

    1. Se posicao esta no LUCRO:
       - Stop = 1% do lucro atual nesta posicao
       - Ex: PnL=$5.00 -> fecha se cair para $4.95

    2. Se posicao esta em PERDA (sem lucro previo):
       - Stop = % do capital configurado (padrao 0.5%)

    Retorna: (deve_fechar: bool, motivo: str)
    """
    upnl      = position["unrealized_pnl"]
    notional  = position["notional"]
    fee_rate  = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
    fee_close = notional * fee_rate
    net_pnl   = upnl - fee_close

    # ── Caso 1: Posicao esta no lucro ──────────────────
    if net_pnl > 0:
        # Stop = 1% abaixo do lucro atual
        stop_value = net_pnl * (float(config.get("profit_stop_percent", 1.0)) / 100)
        # Nao vamos fechar enquanto estiver lucrando
        # So fecha se PnL liquido cair X% do pico
        # (Implementacao simples: fecha se perder 1% do PnL atual)
        add_log(
            "EM LUCRO | PnL Liq:${:.4f} | Protegendo ${:.4f} ({}% do lucro)".format(
                net_pnl,
                net_pnl * (1 - float(config.get("profit_stop_percent", 1.0)) / 100),
                config.get("profit_stop_percent", 1.0)
            )
        )
        # Nao fecha aqui - so fecha por reversao de tendencia
        return False, ""

    # ── Caso 2: Posicao em perda ────────────────────────
    accumulated = bot_state["session"]["accumulated_profit"]
    min_profit  = float(config.get("min_profit_to_use_rule", 5.0))

    if accumulated >= min_profit:
        # Stop = 1% do lucro acumulado da sessao
        max_loss = accumulated * (float(config.get("profit_stop_percent", 1.0)) / 100)
        rule = "1% do lucro acumulado (${:.4f})".format(accumulated)
    else:
        # Stop padrao por capital
        max_loss = session_balance * (
            float(config.get("initial_stop_percent", 0.5)) / 100
        )
        rule = "{}% do capital (${:.2f})".format(
            config.get("initial_stop_percent", 0.5), session_balance
        )

    if abs(net_pnl) >= max_loss:
        motivo = "Stop Loss | Perda ${:.4f} >= Limite ${:.4f} [{}]".format(
            abs(net_pnl), max_loss, rule
        )
        return True, motivo

    add_log(
        "EM PERDA | Liq:${:.4f} | Limite:${:.4f} | {}".format(
            net_pnl, max_loss, rule
        )
    )
    return False, ""


# ═══════════════════════════════════════════════════
# RASTREADOR DE PICO DE LUCRO (TRAILING STOP)
# ═══════════════════════════════════════════════════
class PositionTracker:
    """Rastreia o pico de lucro para aplicar trailing stop."""

    def __init__(self, profit_stop_pct):
        self.peak_pnl       = 0.0
        self.profit_stop_pct = profit_stop_pct  # ex: 1.0 = 1%

    def update(self, current_net_pnl):
        if current_net_pnl > self.peak_pnl:
            self.peak_pnl = current_net_pnl
        return self.peak_pnl

    def should_close(self, current_net_pnl):
        """
        Fecha se:
        - Ja teve lucro (peak > 0)
        - E o lucro atual caiu 1% do pico
        """
        if self.peak_pnl <= 0:
            return False, ""

        drawdown = self.peak_pnl - current_net_pnl
        trigger  = self.peak_pnl * (self.profit_stop_pct / 100)

        if drawdown >= trigger:
            motivo = (
                "Trailing Stop | Pico:${:.4f} Atual:${:.4f} "
                "Queda:${:.4f} >= Limite:${:.4f} ({}%)".format(
                    self.peak_pnl, current_net_pnl,
                    drawdown, trigger, self.profit_stop_pct
                )
            )
            return True, motivo

        return False, ""


# ═══════════════════════════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════════════════════════
def bot_loop(config):
    add_log("=== BOT INICIADO v3.0 ===", "SUCCESS")
    bot_state["status"] = "conectando"
    tracker = None

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
            "Saldo: Total=${:.4f} | Livre=${:.4f} [{}]".format(
                bal["total"], bal["free"], bal.get("account_type", "?")
            )
        )

        # Aviso de saldo baixo
        if bal["total"] < 5.0:
            add_log(
                "Saldo baixo: ${:.4f}. "
                "Bot operara com tamanho minimo disponivel.".format(
                    bal["total"]
                ),
                "WARNING"
            )

        state        = "ANALYZING"
        cooldown_end = 0.0
        analysis_count = 0

        # ════ LOOP ═══════════════════════════════════════
        while not stop_event.is_set():
            try:
                bal = get_balance(exchange, config["exchange_id"])
                sess["current_balance"] = bal["total"]

                # ─── ANALYZING ──────────────────────────
                if state == "ANALYZING":
                    bot_state["status"] = "analisando"
                    analysis_count += 1

                    signal, metrics = analyze_market(exchange, config)

                    if signal != "NONE":
                        add_log(
                            ">>> SINAL {} DETECTADO <<<".format(signal),
                            "SUCCESS"
                        )

                        effective_free = bal["free"]

                        # Bybit Unified: free pode ser 0 mesmo com saldo
                        # Usa total como fallback com margem de seguranca
                        if effective_free < 0.5 and bal["total"] > 0.5:
                            effective_free = bal["total"] * 0.95
                            add_log(
                                "Usando saldo total como referencia: "
                                "${:.4f}".format(effective_free),
                                "WARNING"
                            )

                        if effective_free < 0.5:
                            add_log(
                                "Saldo insuficiente: ${:.4f}".format(
                                    effective_free
                                ),
                                "WARNING"
                            )
                        else:
                            ok = open_position(
                                exchange, config, signal, effective_free
                            )
                            if ok:
                                profit_stop_pct = float(
                                    config.get("profit_stop_percent", 1.0)
                                )
                                tracker = PositionTracker(profit_stop_pct)
                                state   = "IN_POSITION"
                                bot_state["status"] = "em posicao"

                # ─── IN_POSITION ─────────────────────────
                elif state == "IN_POSITION":
                    bot_state["status"] = "em posicao"
                    position = get_position(exchange, config["symbol"])

                    if not position:
                        add_log(
                            "Posicao nao encontrada (fechada externamente).",
                            "WARNING"
                        )
                        bot_state["position"] = None
                        tracker = None
                        state   = "ANALYZING"
                        continue

                    bot_state["position"] = position

                    # PnL liquido
                    upnl     = position["unrealized_pnl"]
                    fee_rate = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
                    fee_est  = position["notional"] * fee_rate
                    net_pnl  = upnl - fee_est

                    # Atualiza pico
                    peak = tracker.update(net_pnl)

                    icon = "+" if net_pnl >= 0 else ""
                    add_log(
                        "{} PnL:${:.4f} | Pico:${:.4f} | "
                        "Side:{} | Tamanho:{}".format(
                            icon, net_pnl, peak,
                            position["side"].upper(),
                            position["size"]
                        )
                    )

                    fechou = False
                    motivo = ""

                    # 1. Verifica trailing stop (1% do lucro)
                    close_trail, motivo_trail = tracker.should_close(net_pnl)
                    if close_trail:
                        fechou = True
                        motivo = motivo_trail

                    # 2. Verifica stop loss padrao (sem lucro)
                    if not fechou:
                        close_stop, motivo_stop = check_stop_loss(
                            position, config, bal["total"]
                        )
                        if close_stop:
                            fechou = True
                            motivo = motivo_stop

                    # 3. Verifica reversao de tendencia
                    if not fechou:
                        if detect_reversal(exchange, config, position["side"]):
                            fechou = True
                            motivo = "Reversao de tendencia"

                    if fechou:
                        add_log("FECHANDO POSICAO | {}".format(motivo), "WARNING")
                        close_position(exchange, position, config, motivo)
                        bot_state["position"] = None
                        tracker       = None
                        cooldown_end  = time.time() + int(
                            config.get("cooldown_seconds", 30)
                        )
                        state = "COOLDOWN"

                # ─── COOLDOWN ────────────────────────────
                elif state == "COOLDOWN":
                    remaining = max(0.0, cooldown_end - time.time())
                    bot_state["status"] = "cooldown ({}s)".format(int(remaining))
                    if remaining <= 0:
                        add_log("Cooldown encerrado. Retomando analise...")
                        bot_state["last_signal"] = "---"
                        state = "ANALYZING"

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
        bot_state["running"]  = False
        bot_state["status"]   = "parado"
        bot_state["position"] = None
        add_log("=== BOT ENCERRADO ===")


# ═══════════════════════════════════════════════════
# ROTAS FLASK
# ═══════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    """Retorna config salva (sem expor secrets completos)."""
    cfg = load_config()
    safe = {}
    for k, v in cfg.items():
        if k in ("api_key", "api_secret"):
            # Mostra apenas primeiros/ultimos 4 chars
            safe[k] = v[:4] + "***" + v[-4:] if len(v) > 8 else "***"
        else:
            safe[k] = v
    return jsonify(safe)


@app.route("/api/config/full", methods=["GET"])
def get_config_full():
    """Retorna config completa para preencher formulario."""
    return jsonify(load_config())


@app.route("/api/start", methods=["POST"])
def start_bot():
    global bot_thread, stop_event

    if bot_state["running"]:
        return jsonify({"error": "Bot ja esta rodando!"}), 400

    data = request.json or {}

    # Mescla com config salva se campos ausentes
    saved = load_config()
    for k, v in saved.items():
        if not data.get(k):
            data[k] = v

    for campo in ["api_key", "api_secret", "exchange_id", "symbol"]:
        if not data.get(campo):
            return jsonify({
                "error": "Campo obrigatorio ausente: {}. "
                         "Configure na aba Configuracoes.".format(campo)
            }), 400

    # Salva config para persistencia
    save_config(data)

    bot_state.update({
        "running":     True,
        "logs":        [],
        "position":    None,
        "last_signal": "---",
        "config":      data,
        "indicators":  {
            "price": 0.0, "ema_fast": 0.0,
            "ema_slow": 0.0, "rsi": 0.0,
            "trend": "---", "adx": 0.0,
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
    return jsonify({"success": True})


@app.route("/api/status")
def get_status():
    return jsonify({
        "running":       bot_state["running"],
        "status":        bot_state["status"],
        "session":       bot_state["session"],
        "position":      bot_state["position"],
        "signal":        bot_state["last_signal"],
        "indicators":    bot_state["indicators"],
        "logs":          bot_state["logs"][-60:],
        "has_config":    bool(load_config().get("api_key")),
    })


@app.route("/api/save-config", methods=["POST"])
def save_config_route():
    data = request.json or {}
    if not data.get("api_key") or not data.get("api_secret"):
        return jsonify({"error": "API Key e Secret sao obrigatorios"}), 400
    save_config(data)
    bot_state["config"] = data
    return jsonify({"success": True, "message": "Configuracoes salvas!"})


# ═══════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
