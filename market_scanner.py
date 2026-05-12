import asyncio
import time
import pandas as pd
from typing import List, Dict, Any, Optional
from trading_engine import SignalGenerator, TechnicalAnalysis

class MarketScanner:
    def __init__(self, exchange_manager, settings: Dict[str, Any]):
        self.ex = exchange_manager
        self.settings = settings
        self.signal_gen = SignalGenerator(adx_threshold=25.0)

        # Cache de OHLCV para evitar rebusca
        self._ohlcv_cache: Dict[str, Dict[str, Any]] = {}
        self._ohlcv_ttl: float = 30  # 30 segundos

        # Cache de candidatos (evita refiltrar tickers a cada scan)
        self._candidates_cache: Optional[List[Dict]] = None
        self._candidates_cache_time: float = 0
        self._candidates_ttl: float = 60  # 1 minuto

    async def scan(self, balance: float, top_n: int = 7, timeframe: str = '15m') -> Dict[str, Any]:
        """Scan otimizado com cache e filtros rigorosos."""
        t0 = time.perf_counter()
        results = []

        try:
            await self.ex.load_markets()

            # Busca tickers com cache
            tickers = await self.ex.fetch_tickers()
        except Exception as e:
            return {'pairs': [], 'count': 0, 'latency_ms': 0, 'error': str(e)}

        # Filtra candidatos com critérios rigorosos
        candidates = await self._filter_candidates(tickers, balance)

        if not candidates:
            return {'pairs': [], 'count': 0, 'latency_ms': 0, 'error': 'Nenhum candidato'}

        symbols = [c['symbol'] for c in candidates]

        try:
            # Busca OHLCV com cache e paralelismo controlado
            ohlcv_m15_map = await self._fetch_ohlcv_cached(symbols, timeframe=timeframe, limit=60)
            ohlcv_h1_map = await self._fetch_ohlcv_cached(symbols, timeframe='1h', limit=30)

            # Opcional: busca H4 para confirmação de tendência
            ohlcv_h4_map = await self._fetch_ohlcv_cached(symbols, timeframe='4h', limit=20)
        except Exception as e:
            return {'pairs': [], 'count': 0, 'latency_ms': 0, 'error': str(e)}

        for c in candidates:
            sym = c['symbol']
            ohlcv_m15 = ohlcv_m15_map.get(sym)
            ohlcv_h1 = ohlcv_h1_map.get(sym)
            ohlcv_h4 = ohlcv_h4_map.get(sym)

            if not ohlcv_m15 or not ohlcv_h1:
                continue
            if len(ohlcv_m15) < 30 or len(ohlcv_h1) < 22:
                continue

            try:
                df_m15 = pd.DataFrame(ohlcv_m15, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df_h1 = pd.DataFrame(ohlcv_h1, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df_h4 = pd.DataFrame(ohlcv_h4, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']) if ohlcv_h4 and len(ohlcv_h4) >= 22 else None

                sig = self.signal_gen.generate(df_m15, df_h1, df_h4)
                if sig.side:
                    results.append({
                        'symbol': sym,
                        'price': c['price'],
                        'score': sig.score,
                        'side': sig.side,
                        'confidence': sig.confidence,
                        'volume_24h': c['volume'],
                        'change_24h': round(c['change'], 2),
                        'adx': sig.meta.get('adx', 0),
                        'rsi': sig.meta.get('rsi', 0),
                        'mfi': sig.meta.get('mfi', 0),
                        'trend_h1': sig.meta.get('trend_h1', 'NEUTRO'),
                        'h1_adx': sig.meta.get('h1_adx', 0),
                        'h4_trend': sig.meta.get('h4_trend', 'NEUTRO'),
                        'atr': sig.meta.get('atr', 0),
                        'volume_ratio': sig.meta.get('volume_ratio', 1.0),
                        'bb_position': sig.meta.get('bb_position', 0.5),
                    })
            except Exception:
                continue

        # Ordena por score e confiança
        results.sort(key=lambda x: (x['score'], x['confidence'] == 'high'), reverse=True)
        top = results[:top_n]

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            'pairs': top,
            'count': len(top),
            'latency_ms': latency_ms,
            'scanned': len(candidates),
            'error': None,
        }

    async def _filter_candidates(self, tickers: Dict, balance: float) -> List[Dict]:
        """Filtra candidatos com critérios rigorosos de liquidez."""
        now = time.time()

        # Usa cache se recente
        if self._candidates_cache and (now - self._candidates_cache_time) < self._candidates_ttl:
            return self._candidates_cache

        candidates = []
        for symbol, ticker in tickers.items():
            # Filtro 1: Apenas perpétuos USDT
            if not symbol.endswith('/USDT:USDT'):
                continue

            try:
                market = self.ex.exchange.market(symbol)
            except Exception:
                continue

            # Filtro 2: Mercado ativo e swap linear
            if not market or not market.get('active', False):
                continue
            if market.get('type') != 'swap' or market.get('linear') not in (True, 1, 'true'):
                continue

            last_price = float(ticker.get('last', 0) or 0)
            volume = float(ticker.get('quoteVolume', 0) or 0)

            # Filtro 3: Preço e volume válidos
            if last_price <= 0 or volume <= 0:
                continue

            # Filtro 4: Volume mínimo de $1M (liquidez)
            if volume < 1_000_000:
                continue

            # Filtro 5: Custo mínimo acessível
            min_cost = self.ex.get_min_cost(symbol, last_price)
            if min_cost > balance * 0.8:
                continue

            # Filtro 6: Spread máximo de 0.1%
            bid = float(ticker.get('bid', 0) or 0)
            ask = float(ticker.get('ask', 0) or 0)
            if bid > 0 and ask > 0:
                spread_pct = (ask - bid) / ((ask + bid) / 2) * 100
                if spread_pct > 0.1:
                    continue

            candidates.append({
                'symbol': symbol,
                'price': last_price,
                'volume': volume,
                'change': float(ticker.get('percentage', 0) or 0),
                'spread_pct': spread_pct if bid > 0 and ask > 0 else 0,
            })

        # Ordena por volume (liquidez) e pega top 20
        candidates.sort(key=lambda x: x['volume'], reverse=True)
        top_candidates = candidates[:20]

        # Atualiza cache
        self._candidates_cache = top_candidates
        self._candidates_cache_time = now

        return top_candidates

    async def _fetch_ohlcv_cached(self, symbols: List[str], timeframe: str, limit: int) -> Dict[str, Any]:
        """Busca OHLCV com cache inteligente."""
        now = time.time()
        result = {}
        symbols_to_fetch = []

        # Verifica cache
        for sym in symbols:
            cache_key = f"{sym}_{timeframe}"
            if cache_key in self._ohlcv_cache:
                cached = self._ohlcv_cache[cache_key]
                if (now - cached['time']) < self._ohlcv_ttl:
                    result[sym] = cached['data']
                    continue
            symbols_to_fetch.append(sym)

        # Busca os que não estão em cache
        if symbols_to_fetch:
            fetched = await self.ex.fetch_ohlcv_batch(
                symbols_to_fetch, 
                timeframe=timeframe, 
                limit=limit, 
                max_concurrent=5  # Reduzido para evitar rate limits
            )

            for sym, data in fetched.items():
                if data:
                    cache_key = f"{sym}_{timeframe}"
                    self._ohlcv_cache[cache_key] = {
                        'data': data,
                        'time': now
                    }
                    result[sym] = data

        return result
