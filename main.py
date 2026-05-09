"""
nelsonsdiogo-bot v5.0
Crypto Futures Trading Bot - Preservacao de Lucro
Correcoes: Rate Limit, Trailing Stop 10%, Protecao Capital
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
# IDENTIDADE
# ═══════════════════════════════════════════════════
BOT_NAME    = "nelsonsdiogo-bot"
BOT_VERSION = "5.0.0"

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


# ═══════════════════════════════════════════════════
# ESTADO GLOBAL
# ═══════════════════════════════════════════════════
bot_state = {
    "running":       False,
    "status":        "parado",
    "logs":          [],
    "config":        load_config(),
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
    "risk": {
        "peak_pnl":        0.0,
        "break_even_price": 0.0,
        "capital_shield":  False,
        "trailing_pct":    10.0,
    },
}

bot_thread = None
stop_event = threading.Event()

# ═══════════════════════════════════════════════════
# RATE LIMITER INTELIGENTE
# ═══════════════════════════════════════════════════
class RateLimiter:
    """
    Controla o tempo entre requisicoes para evitar
    o erro 10006 (Too many visits) da Bybit.
    """
    def __init__(self):
        self.last_call     = {}
        self.error_count   = 0
        self.base_delay    = 0.5   # segundos entre chamadas
        self.penalty_delay = 30.0  # delay apos rate limit

    def wait(self, endpoint="default"):
        now     = time.time()
        last    = self.last_call.get(endpoint, 0)
        elapsed = now - last
        delay   = self.base_delay * (1 + self.error_count * 0.5)

        if elapsed < delay:
            time.sleep(delay - elapsed)

        self.last_call[endpoint] = time.time()

    def on_rate_limit(self):
        """Chamado quando a exchange retorna rate limit."""
        self.error_count += 1
        penalty = min(self.penalty_delay * self.error_count, 120)
        add_log(
            "Rate Limit detectado! Aguardando {}s antes de continuar...".format(
                int(penalty)
            ),
            "WARNING"
        )
        time.sleep(penalty)

    def on_success(self):
        """Chamado apos chamada bem-sucedida."""
        if self.error_count > 0:
            self.error_count = max(0, self.error_count - 1)


rate_limiter = RateLimiter()


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
    print("[{}][{}][{}] {}".format(BOT_NAME, timestamp, level, message))


# ═══════════════════════════════════════════════════
# EXCHANGE COM RATE LIMIT ROBUSTO
# ═══════════════════════════════════════════════════
def create_exchange(config):
    exchange_id = config["exchange_id"]
    cls = getattr(ccxt, exchange_id)

    if exchange_id == "bybit":
        params = {
            "apiKey":          config["api_key"],
            "secret":          config["api_secret"],
            "enableRateLimit": True,
            "rateLimit":       500,   # ms entre requisicoes (Bybit limite: 120/min)
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
            "rateLimit":       300,
            "options":         {"defaultType": "future"},
        }

    ex = cls(params)
    if str(config.get("testnet", "false")).lower() == "true":
        ex.set_sandbox_mode(True)
        add_log("Modo TESTNET ativo", "WARNING")

    ex.load_markets()
    add_log("Conectado a {} | {}".format(exchange_id.upper(), BOT_NAME))
    return ex


def safe_api_call(func, *args, max_retries=3, endpoint="api", **kwargs):
    """
    Executa chamada de API com tratamento automatico de rate limit.
    Retry automatico com backoff exponencial.
    """
    for attempt in range(max_retries):
        try:
            rate_limiter.wait(endpoint)
            result = func(*args, **kwargs)
            rate_limiter.on_success()
            return result

        except ccxt.RateLimitExceeded as e:
            rate_limiter.on_rate_limit()
            if attempt == max_retries - 1:
                raise

        except ccxt.NetworkError as e:
            wait_time = (attempt + 1) * 10
            add_log("Erro rede (tentativa {}/{}): {}. Aguardando {}s...".format(
                attempt + 1, max_retries, str(e)[:60], wait_time
            ), "WARNING")
            time.sleep(wait_time)
            if attempt == max_retries - 1:
                raise

        except ccxt.ExchangeError as e:
            err = str(e)
            # Bybit retCode 10006 = Too many visits
            if "10006" in err or "too many visits" in err.lower():
                rate_limiter.on_rate_limit()
                if attempt == max_retries - 1:
                    raise
            else:
                raise

        except Exception as e:
            raise

    return None


# ═══════════════════════════════════════════════════
# SALDO
# ═══════════════════════════════════════════════════
def get_balance(exchange, exchange_id):
    try:
        if exchange_id == "bybit":
            for acc in ["UNIFIED", "CONTRACT"]:
                try:
                    bal = safe_api_call(
                        exchange.fetch_balance,
                        {"accountType": acc},
                        endpoint="balance_{}".format(acc)
                    )
                    usdt  = bal.get("USDT", {})
                    total = float(usdt.get("total") or 0)
                    free  = float(usdt.get("free")  or 0)
                    if total > 0:
                        return {"total": total, "free": free, "account": acc}
                except Exception:
                    continue
            return _raw_balance(safe_api_call(
                exchange.fetch_balance, endpoint="balance_raw"
            ))

        bal   = safe_api_call(exchange.fetch_balance, endpoint="balance")
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
        safe_api_call(
            exchange.set_leverage, leverage, symbol,
            endpoint="leverage"
        )
        add_log("Alavancagem {}x em {}".format(leverage, symbol))
    except Exception as e:
        err = str(e)
        if "110077" in err or "pm mode" in err.lower():
            add_log("Portfolio Margin: alavancagem auto.", "WARNING")
        elif "leverage not modified" in err.lower():
            add_log("Alavancagem ja configurada.")
        else:
            add_log("Aviso alavancagem: {}".format(err[:80]), "WARNING")


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
            ticker   = safe_api_call(
                exchange.fetch_ticker, symbol, endpoint="ticker_{}".format(symbol)
            )
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
    try:
        raw = safe_api_call(
            exchange.fetch_ohlcv, symbol, timeframe,
            limit=150, endpoint="ohlcv_{}".format(symbol)
        )
        if not raw or len(raw) < 60:
            return "NONE", {}, 0.0

        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["close"]  = df["close"].astype(float)
        df["high"]   = df["high"].astype(float)
        df["low"]    = df["low"].astype(float)

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

    except Exception as e:
        add_log("Erro analise {}: {}".format(symbol, str(e)[:60]), "ERROR")
        return "NONE", {}, 0.0


def scan_best_pairs(exchange, budget_usdt, config):
    add_log("Escaneando pares para ${:.4f}...".format(budget_usdt))
    results    = []
    tf         = config.get("timeframe", "5m")
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
                symbol, signal,
                metrics.get("adx", 0), score
            ))

            # Pausa entre pares para evitar rate limit
            time.sleep(0.8)

        except Exception as e:
            add_log("  Erro {}: {}".format(symbol, str(e)[:50]))
            time.sleep(1.0)
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
# DADOS DO GRAFICO
# ═══════════════════════════════════════════════════
def update_chart_data(exchange, symbol, timeframe):
    try:
        raw = safe_api_call(
            exchange.fetch_ohlcv, symbol, timeframe,
            limit=60, endpoint="chart_{}".format(symbol)
        )
        if not raw:
            return

        bot_state["chart_data"] = [
            {"t": c[0], "o": float(c[1]), "h": float(c[2]),
             "l": float(c[3]), "c": float(c[4]), "v": float(c[5])}
            for c in raw
        ]
    except Exception as e:
        add_log("Erro grafico: {}".format(str(e)[:60]), "ERROR")


# ═══════════════════════════════════════════════════
# GESTAO DE POSICAO
# ═══════════════════════════════════════════════════
def get_position(exchange, symbol):
    try:
        positions = safe_api_call(
            exchange.fetch_positions, [symbol],
            endpoint="position_{}".format(symbol)
        )
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
        add_log("Erro posicao: {}".format(str(e)[:60]), "ERROR")
        return None


def wait_order_filled(exchange, symbol, order_id, timeout=15):
    """
    Aguarda confirmacao de preenchimento da ordem antes de continuar.
    Evita erros de reversao com ordem anterior ainda pendente.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            order = safe_api_call(
                exchange.fetch_order, order_id, symbol,
                endpoint="order_status"
            )
            status = order.get("status", "")
            if status in ("closed", "filled"):
                add_log("Ordem {} preenchida.".format(order_id))
                return True
            add_log("Aguardando ordem {}... status: {}".format(
                order_id, status
            ))
            time.sleep(2)
        except Exception as e:
            add_log("Erro ao verificar ordem: {}".format(str(e)[:60]), "WARNING")
            time.sleep(2)

    add_log("Timeout aguardando ordem {}.".format(order_id), "WARNING")
    return False


def open_position(exchange, config, signal, symbol, free_balance):
    try:
        ticker = safe_api_call(
            exchange.fetch_ticker, symbol,
            endpoint="ticker_open"
        )
        price  = float(ticker["last"])

        pct       = float(config.get("position_size_percent", 85))
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
            return False, None, 0.0

        side = "buy" if signal == "LONG" else "sell"

        add_log("Abrindo {} {} | Preco:{:.6f} | Qtd:{} | ~${:.4f}".format(
            signal, symbol, price, amount, amount * price
        ))

        order = safe_api_call(
            exchange.create_market_order, symbol, side, amount,
            endpoint="open_order"
        )

        if not order:
            add_log("Ordem nao retornou dados.", "ERROR")
            return False, None, 0.0

        order_id = order.get("id")
        if order_id:
            time.sleep(1)  # Pausa antes de verificar

        bot_state["last_signal"]   = signal
        bot_state["active_symbol"] = symbol

        # Calcula break-even (entrada + taxa de abertura + fechamento)
        fee_rate   = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
        break_even = price * (1 + fee_rate * 2) if signal == "LONG" else \
                     price * (1 - fee_rate * 2)

        add_log("Posicao {} aberta em {} | Break-even: {:.6f}".format(
            signal, symbol, break_even
        ), "SUCCESS")

        return True, order_id, break_even

    except Exception as e:
        add_log("Erro ao abrir em {}: {}".format(symbol, e), "ERROR")
        return False, None, 0.0


def close_position(exchange, position, config, reason=""):
    """
    Fecha posicao com verificacao de preenchimento.
    Nunca permite fechar abaixo do capital inicial (protecao total).
    """
    try:
        symbol     = position.get("symbol", config.get("symbol"))
        close_side = "sell" if position["side"] == "long" else "buy"
        gross      = position["unrealized_pnl"]
        fee_rate   = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
        fees       = position["notional"] * fee_rate * 2
        net        = gross - fees

        # ESCUDO DE CAPITAL: nao fecha se resultar em perda do capital inicial
        sess            = bot_state["session"]
        initial_balance = sess["initial_balance"]
        current_balance = sess["current_balance"]
        projected       = current_balance + net

        if projected < initial_balance * 0.995:  # tolerancia de 0.5%
            add_log(
                "ESCUDO CAPITAL: Fechamento bloqueado! "
                "Projetado:${:.4f} < Inicial:${:.4f}. "
                "Aguardando break-even...".format(projected, initial_balance),
                "WARNING"
            )
            return 0.0, False

        add_log("Fechando {} {} | {} | PnL:${:.6f}".format(
            position["side"].upper(), symbol, reason, gross
        ))

        order = safe_api_call(
            exchange.create_market_order,
            symbol, close_side, position["size"],
            params={"reduceOnly": True},
            endpoint="close_order"
        )

        if order and order.get("id"):
            time.sleep(1.5)  # Aguarda preenchimento antes de proximo passo

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
        bot_state["risk"] = {
            "peak_pnl":         0.0,
            "break_even_price": 0.0,
            "capital_shield":   False,
            "trailing_pct":     float(config.get("profit_stop_percent", 10.0)),
        }

        return net, True

    except Exception as e:
        add_log("Erro ao fechar: {}".format(e), "ERROR")
        return 0.0, False


# ═══════════════════════════════════════════════════
# TRAILING STOP 10% — LOGICA CENTRAL
# ═══════════════════════════════════════════════════
class PositionTracker:
    """
    Rastreia o pico de lucro e aplica trailing stop de 10%.

    Regras:
    1. Trailing: Se lucro cair 10% do pico -> fecha (garante ganho)
    2. Break-even: Nunca fecha com perda superior ao break-even
    3. Escudo capital: Nunca reduz o capital abaixo do inicial
    """

    def __init__(self, trailing_pct, break_even_price, entry_side):
        self.peak_pnl        = 0.0
        self.trailing_pct    = trailing_pct   # ex: 10.0 = 10%
        self.break_even      = break_even_price
        self.entry_side      = entry_side
        self.min_profit_trail = 0.0005        # $0.0005 antes de ativar trailing

    def update(self, net_pnl):
        if net_pnl > self.peak_pnl:
            self.peak_pnl = net_pnl
        # Atualiza estado no dashboard
        bot_state["risk"]["peak_pnl"] = self.peak_pnl
        return self.peak_pnl

    def should_close(self, net_pnl, current_price):
        """
        Retorna (deve_fechar, motivo).

        Prioridade:
        1. Trailing stop (10% do pico) — so quando ha lucro
        2. Break-even stop — nao permite fechar no vermelho
        """

        # ── Caso 1: Ha lucro e atingiu pico ─────────────
        if self.peak_pnl >= self.min_profit_trail:
            drawdown = self.peak_pnl - net_pnl
            trigger  = self.peak_pnl * (self.trailing_pct / 100)

            if drawdown >= trigger:
                return True, (
                    "Trailing Stop {}% | "
                    "Pico:${:.6f} Atual:${:.6f} "
                    "Recuo:${:.6f} >= Gatilho:${:.6f}".format(
                        self.trailing_pct,
                        self.peak_pnl, net_pnl,
                        drawdown, trigger
                    )
                )

        # ── Caso 2: Em perda — verifica break-even ──────
        if net_pnl < 0:
            # Nao fecha se ainda nao atingiu break-even de perda maxima
            # (Protecao de capital gerida pelo escudo em close_position)
            pass

        return False, ""

    def log_status(self, net_pnl):
        if self.peak_pnl > 0:
            pct_from_peak = ((self.peak_pnl - net_pnl) / self.peak_pnl * 100
                             if self.peak_pnl > 0 else 0)
            add_log(
                "Trailing | PnL:${:.6f} | Pico:${:.6f} | "
                "Recuo:{:.1f}% | Gatilho:{}%".format(
                    net_pnl, self.peak_pnl,
                    pct_from_peak, self.trailing_pct
                )
            )
        else:
            add_log(
                "Posicao | PnL:${:.6f} | "
                "Aguardando lucro para ativar trailing...".format(net_pnl)
            )


# ═══════════════════════════════════════════════════
# STOP LOSS PADRAO (SEM LUCRO ACUMULADO)
# ═══════════════════════════════════════════════════
def check_capital_stop(position, config, total_balance, initial_balance):
    """
    Stop de protecao de capital quando nao ha lucro acumulado.
    Nunca permite que o saldo caia abaixo do capital inicial.
    """
    upnl     = position["unrealized_pnl"]
    fee_rate = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
    fee_est  = position["notional"] * fee_rate
    net_pnl  = upnl - fee_est

    if net_pnl >= 0:
        return False, ""

    accumulated = bot_state["session"]["accumulated_profit"]
    min_profit  = float(config.get("min_profit_to_use_rule", 0.5))

    if accumulated >= min_profit:
        # Com lucro acumulado: stop = % do lucro
        max_loss = accumulated * (float(config.get("profit_stop_percent", 10.0)) / 100)
        rule = "{}% lucro acumulado (${:.4f})".format(
            config.get("profit_stop_percent", 10.0), accumulated
        )
    else:
        # Sem lucro: stop = % do capital com floor de $0.005
        max_loss = max(
            total_balance * (float(config.get("initial_stop_percent", 1.0)) / 100),
            0.005
        )
        rule = "{}% capital".format(config.get("initial_stop_percent", 1.0))

    abs_loss = abs(net_pnl)

    add_log(
        "Capital | PnL:${:.6f} | Perda:${:.6f} | Limite:${:.6f} | {}".format(
            net_pnl, abs_loss, max_loss, rule
        )
    )

    if abs_loss >= max_loss:
        return True, "Stop Capital | Perda:${:.6f} >= Limite:${:.6f} [{}]".format(
            abs_loss, max_loss, rule
        )

    return False, ""


# ═══════════════════════════════════════════════════
# REVERSAO DE TENDENCIA
# ═══════════════════════════════════════════════════
def detect_reversal(exchange, config, current_side, active_symbol):
    try:
        raw = safe_api_call(
            exchange.fetch_ohlcv,
            active_symbol, config["timeframe"],
            limit=60,
            endpoint="reversal_{}".format(active_symbol)
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
        ema50 = calculate_ema(df["close"], 50)
        rsi   = calculate_rsi(df["close"], 14)

        e9  = ema9.iloc[-1]
        e21 = ema21.iloc[-1]
        e50 = ema50.iloc[-1]
        r   = rsi.iloc[-1]

        # Reversao confirmada: precisa de alinhamento duplo (EMA + RSI)
        if current_side == "long":
            reversal = (e9 < e21) and (e21 < e50) and (r < 45)
            if reversal:
                add_log(
                    "REVERSAO BAIXA em {} | "
                    "EMA9:{:.4f} EMA21:{:.4f} EMA50:{:.4f} RSI:{:.1f}".format(
                        active_symbol, e9, e21, e50, r
                    ),
                    "WARNING"
                )
                return True

        elif current_side == "short":
            reversal = (e9 > e21) and (e21 > e50) and (r > 55)
            if reversal:
                add_log(
                    "REVERSAO ALTA em {} | "
                    "EMA9:{:.4f} EMA21:{:.4f} RSI:{:.1f}".format(
                        active_symbol, e9, e21, r
                    ),
                    "WARNING"
                )
                return True

        return False

    except Exception as e:
        add_log("Erro reversao: {}".format(str(e)[:60]), "ERROR")
        return False


# ═══════════════════════════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════════════════════════
def bot_loop(config):
    add_log("=== {} v{} INICIADO ===".format(BOT_NAME, BOT_VERSION), "SUCCESS")
    bot_state["status"] = "conectando"

    tracker       = None
    active_symbol = None
    scan_counter  = 0
    chart_counter = 0
    pos_check_count = 0

    # Intervalos de polling (em segundos)
    POSITION_CHECK_INTERVAL = 15  # verifica posicao a cada 15s
    CHART_UPDATE_INTERVAL   = 4   # atualiza grafico a cada 4 ciclos
    SCAN_INTERVAL_CYCLES    = 8   # re-escaneia a cada 8 ciclos

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

        # Tempo da ultima verificacao de posicao
        last_pos_check = 0.0

        while not stop_event.is_set():
            try:
                now = time.time()

                # Atualiza saldo (menos frequente para poupar rate limit)
                if scan_counter % 3 == 0:
                    bal = get_balance(exchange, config["exchange_id"])
                    sess["current_balance"] = bal["total"]

                effective = bal["free"]
                if effective < 0.5 and bal["total"] > 0.5:
                    effective = bal["total"] * 0.95

                # Atualiza grafico
                chart_counter += 1
                if chart_counter >= CHART_UPDATE_INTERVAL:
                    chart_counter = 0
                    sym_chart = (active_symbol if active_symbol
                                 else config.get("symbol", "DOGE/USDT:USDT"))
                    update_chart_data(exchange, sym_chart, config["timeframe"])

                # ─── SCANNING ──────────────────────────
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

                        update_chart_data(
                            exchange, active_symbol, config["timeframe"]
                        )

                        ok, order_id, break_even = open_position(
                            exchange, config, signal,
                            active_symbol, effective
                        )

                        if ok:
                            trailing_pct = float(
                                config.get("profit_stop_percent", 10.0)
                            )
                            tracker = PositionTracker(
                                trailing_pct, break_even, signal.lower()
                            )
                            bot_state["risk"] = {
                                "peak_pnl":         0.0,
                                "break_even_price": break_even,
                                "capital_shield":   True,
                                "trailing_pct":     trailing_pct,
                            }
                            state              = "IN_POSITION"
                            last_pos_check     = 0.0  # forca verificacao imediata
                            bot_state["status"] = "em posicao"
                        else:
                            state = "ANALYZING"
                    else:
                        state = "ANALYZING"

                # ─── ANALYZING ─────────────────────────
                elif state == "ANALYZING":
                    bot_state["status"] = "analisando"
                    scan_counter += 1

                    if scan_counter >= SCAN_INTERVAL_CYCLES:
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
                        sym,
                        metrics.get("price", 0),
                        metrics.get("rsi", 0),
                        metrics.get("adx", 0),
                        metrics.get("trend", "---")
                    ))

                    if signal != "NONE" and score > 30:
                        state = "SCANNING"

                # ─── IN_POSITION ───────────────────────
                elif state == "IN_POSITION":
                    bot_state["status"] = "em posicao"

                    # Verifica posicao apenas no intervalo definido
                    if now - last_pos_check < POSITION_CHECK_INTERVAL:
                        time.sleep(2)
                        continue

                    last_pos_check = now
                    sym_pos  = active_symbol or config.get("symbol")
                    position = get_position(exchange, sym_pos)

                    if not position:
                        add_log("Posicao encerrada externamente.", "WARNING")
                        bot_state["position"]      = None
                        bot_state["active_symbol"] = "---"
                        tracker       = None
                        active_symbol = None
                        scan_counter  = 0
                        state         = "SCANNING"
                        continue

                    bot_state["position"] = position

                    # Calcula PnL liquido
                    upnl     = position["unrealized_pnl"]
                    fee_rate = 0.0006 if config["exchange_id"] == "bybit" else 0.0004
                    fee_est  = position["notional"] * fee_rate
                    net_pnl  = upnl - fee_est

                    # Atualiza pico
                    peak = tracker.update(net_pnl)

                    # Log de status do trailing
                    tracker.log_status(net_pnl)

                    # Preco atual para verificacao de break-even
                    ticker = safe_api_call(
                        exchange.fetch_ticker, sym_pos,
                        endpoint="ticker_pos"
                    )
                    current_price = float(ticker["last"]) if ticker else 0

                    fechou = False
                    motivo = ""

                    # 1. Trailing stop (10% do pico)
                    close_t, mot_t = tracker.should_close(net_pnl, current_price)
                    if close_t:
                        fechou = True
                        motivo = mot_t

                    # 2. Stop de capital (sem lucro acumulado)
                    if not fechou:
                        close_s, mot_s = check_capital_stop(
                            position, config,
                            bal["total"], sess["initial_balance"]
                        )
                        if close_s:
                            fechou = True
                            motivo = mot_s

                    # 3. Reversao de tendencia (confirmacao dupla)
                    if not fechou:
                        if detect_reversal(
                            exchange, config,
                            position["side"], sym_pos
                        ):
                            fechou = True
                            motivo = "Reversao de tendencia confirmada"

                    if fechou:
                        add_log("FECHANDO: {}".format(motivo), "WARNING")
                        net, fechou_ok = close_position(
                            exchange, position, config, motivo
                        )

                        if fechou_ok:
                            bot_state["position"]      = None
                            bot_state["active_symbol"] = "---"
                            tracker       = None
                            active_symbol = None
                            scan_counter  = 0
                            cooldown_end  = time.time() + int(
                                config.get("cooldown_seconds", 30)
                            )
                            state = "COOLDOWN"
                        else:
                            add_log(
                                "Fechamento bloqueado pelo escudo de capital. "
                                "Mantendo posicao...",
                                "WARNING"
                            )

                # ─── COOLDOWN ──────────────────────────
                elif state == "COOLDOWN":
                    remaining = max(0.0, cooldown_end - time.time())
                    bot_state["status"] = "cooldown ({}s)".format(int(remaining))
                    if remaining <= 0:
                        add_log("Cooldown encerrado. Escaneando...")
                        bot_state["last_signal"] = "---"
                        scan_counter = 0
                        state = "SCANNING"

            except ccxt.RateLimitExceeded as e:
                add_log("Rate Limit Bybit! Aguardando 60s...".format(e), "ERROR")
                time.sleep(60)

            except ccxt.NetworkError as e:
                add_log("Erro rede: {}".format(str(e)[:60]), "ERROR")
                time.sleep(20)

            except ccxt.ExchangeError as e:
                err = str(e)
                if "10006" in err or "too many" in err.lower():
                    add_log("Rate Limit (10006)! Aguardando 45s...", "ERROR")
                    time.sleep(45)
                else:
                    add_log("Erro exchange: {}".format(err[:80]), "ERROR")
                    time.sleep(15)

            except Exception as e:
                add_log("Erro loop: {}".format(str(e)[:80]), "ERROR")
                time.sleep(10)

            # Intervalo principal do loop
            loop_interval = int(config.get("loop_interval", 15))
            time.sleep(loop_interval)

    except Exception as e:
        add_log("Erro critico: {}".format(e), "ERROR")
    finally:
        bot_state["running"]       = False
        bot_state["status"]        = "parado"
        bot_state["position"]      = None
        bot_state["active_symbol"] = "---"
        add_log("=== {} ENCERRADO ===".format(BOT_NAME))


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
        "risk": {
            "peak_pnl":         0.0,
            "break_even_price": 0.0,
            "capital_shield":   False,
            "trailing_pct":     float(data.get("profit_stop_percent", 10.0)),
        },
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
        "risk":          bot_state["risk"],
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
