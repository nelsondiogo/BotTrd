def analyze_market(exchange, config: dict) -> str:
    """
    Estratégia combinada:
    - Primário:  EMA9/EMA21 Crossover (sinal de entrada)
    - Secundário: Tendência EMA (confirmação de direção)
    - Filtro:    RSI (evita sobrecompra/sobrevenda)
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
            columns=["timestamp","open","high","low","close","volume"]
        )
        df["close"] = df["close"].astype(float)

        # Indicadores
        ema_fast = calculate_ema(df["close"], 9)
        ema_slow = calculate_ema(df["close"], 21)
        ema_trend= calculate_ema(df["close"], 50)  # tendência maior
        rsi      = calculate_rsi(df["close"], 14)

        ef_now  = ema_fast.iloc[-1]
        ef_prev = ema_fast.iloc[-2]
        es_now  = ema_slow.iloc[-1]
        es_prev = ema_slow.iloc[-2]
        et_now  = ema_trend.iloc[-1]
        rsi_now = rsi.iloc[-1]
        price   = df["close"].iloc[-1]

        # Atualiza dashboard
        bot_state["indicators"] = {
            "price":    round(price, 2),
            "ema_fast": round(ef_now, 2),
            "ema_slow": round(es_now, 2),
            "rsi":      round(rsi_now, 2),
        }

        # Cruzamentos
        bullish_cross = (ef_prev <= es_prev) and (ef_now > es_now)
        bearish_cross = (ef_prev >= es_prev) and (ef_now < es_now)

        # Tendência atual das EMAs
        bullish_trend = ef_now > es_now
        bearish_trend = ef_now < es_now

        # Tendência maior (EMA50)
        above_trend = price > et_now
        below_trend = price < et_now

        add_log(
            f"📊 Preço: {price:.2f} | "
            f"EMA9: {ef_now:.2f} | "
            f"EMA21: {es_now:.2f} | "
            f"RSI: {rsi_now:.2f} | "
            f"Tendência: {'↑' if bullish_trend else '↓'}"
        )

        # ── MODO 1: Cruzamento (sinal forte) ──────────────
        if bullish_cross and rsi_now < 72:
            add_log("🟢 SINAL: Cruzamento de ALTA (EMA Cross Up)", "SUCCESS")
            return "LONG"

        if bearish_cross and rsi_now > 28:
            add_log("🔴 SINAL: Cruzamento de BAIXA (EMA Cross Down)", "SUCCESS")
            return "SHORT"

        # ── MODO 2: Tendência + RSI extremo (sinal alternativo) ──
        # Compra em sobrevenda com tendência de alta
        if bullish_trend and above_trend and rsi_now < 35:
            add_log("🟢 SINAL: RSI Sobrevenda em tendência de ALTA", "SUCCESS")
            return "LONG"

        # Venda em sobrecompra com tendência de baixa
        if bearish_trend and below_trend and rsi_now > 65:
            add_log("🔴 SINAL: RSI Sobrecompra em tendência de BAIXA", "SUCCESS")
            return "SHORT"

        add_log(
            f"⏸ Aguardando sinal | "
            f"RSI:{rsi_now:.1f} | "
            f"{'EMA Bull' if bullish_trend else 'EMA Bear'} | "
            f"{'Acima' if above_trend else 'Abaixo'} EMA50"
        )
        return "NONE"

    except Exception as e:
        add_log(f"Erro na análise: {e}", "ERROR")
        return "NONE"
