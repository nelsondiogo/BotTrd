import asyncio
import time
from typing import List, Dict, Any
from trading_engine import SignalGenerator

class MarketScanner:
    def __init__(self, exchange_manager, settings: Dict[str, Any]):
        self.ex = exchange_manager
        self.settings = settings
        self.signal_gen = SignalGenerator(adx_threshold=25.0)
        self._ohlcv_cache: Dict[str, Dict] = {}
        self._ohlcv_ttl = 25
        self._candidates_cache: List[Dict] = []
        self._candidates_cache_time = 0.0
        self._candidates_ttl = 45

    async def scan(self, balance: float, top_n: int = 7, timeframe: str = '15') -> Dict[str, Any]:
        t0 = time.perf_counter()

        try:
            tickers = await self.ex.fetch_tickers()
        except Exception as e:
            return {'pairs': [], 'count': 0, 'latency_ms': 0, 'error': str(e)}

        candidates = await self._filter_candidates(tickers, balance)
        if not candidates:
            return {'pairs': [], 'count': 0, 'latency_ms': 0, 'error': 'Nenhum candidato'}

        symbols = [c['symbol'] for c in candidates]

        try:
            ohlcv_m15_map, ohlcv_h1_map, ohlcv_h4_map = await asyncio.gather(
                self._fetch_ohlcv_cached(symbols, timeframe=timeframe, limit=60),
                self._fetch_ohlcv_cached(symbols, timeframe='60', limit=30),
                self._fetch_ohlcv_cached(symbols, timeframe='240', limit=20),
                return_exceptions=True
            )
            if isinstance(ohlcv_m15_map, Exception):
                raise ohlcv_m15_map
            if isinstance(ohlcv_h1_map, Exception):
                raise ohlcv_h1_map
            if isinstance(ohlcv_h4_map, Exception):
                ohlcv_h4_map = {}
        except Exception as e:
            return {'pairs': [], 'count': 0, 'latency_ms': 0, 'error': str(e)}

        results = []
        for c in candidates:
            sym = c['symbol']
            ohlcv_m15 = ohlcv_m15_map.get(sym)
            ohlcv_h1 = ohlcv_h1_map.get(sym)
            ohlcv_h4 = ohlcv_h4_map.get(sym) if isinstance(ohlcv_h4_map, dict) else None

            if not ohlcv_m15 or not ohlcv_h1:
                continue
            if len(ohlcv_m15) < 35 or len(ohlcv_h1) < 25:
                continue

            try:
                sig = self.signal_gen.generate(ohlcv_m15, ohlcv_h1, ohlcv_h4)
                if sig.side:
                    results.append({
                        'symbol': sym,
                        'price': c['price'],
                        'score': sig.score,
                        'side': sig.side,
                        'confidence': sig.confidence,
                        'expected_return_pct': sig.expected_return_pct,
                        'volume_24h': c['volume'],
                        'change_24h': round(c['change'], 2),
                        'adx': sig.meta.get('adx', 0),
                        'rsi': sig.meta.get('rsi', 0),
                        'mfi': sig.meta.get('mfi', 0),
                        'trend_h1': sig.meta.get('trend_h1', 'NEUTRO'),
                        'h1_adx': sig.meta.get('h1_adx', 0),
                        'atr': sig.meta.get('atr', 0),
                        'volume_ratio': sig.meta.get('volume_ratio', 1.0),
                    })
            except Exception:
                continue

        results.sort(key=lambda x: (x['score'], x['expected_return_pct']), reverse=True)
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
        now = time.time()
        if self._candidates_cache and (now - self._candidates_cache_time) < self._candidates_ttl:
            return self._candidates_cache

        candidates = []
        for symbol, ticker in tickers.items():
            if not symbol.endswith('/USDT:USDT'):
                continue

            last_price = float(ticker.get('last', 0) or 0)
            volume = float(ticker.get('quoteVolume', 0) or 0)

            if last_price <= 0 or volume <= 0:
                continue
            if volume < 500_000:  # Reduzido para permitir mais pares com saldo baixo
                continue

            min_cost = self.ex.get_min_cost(symbol, last_price)
            # Permite candidatos se o saldo for suficiente para pelo menos 1 ordem minima
            # ou se o saldo for > 0 (o risk manager decide o tamanho depois)
            if balance > 0 and min_cost > balance * 1.5:
                continue

            bid = float(ticker.get('bid', 0) or 0)
            ask = float(ticker.get('ask', 0) or 0)
            spread_pct = 0.0
            if bid > 0 and ask > 0:
                spread_pct = (ask - bid) / ((ask + bid) / 2) * 100
                if spread_pct > 0.15:
                    continue

            candidates.append({
                'symbol': symbol,
                'price': last_price,
                'volume': volume,
                'change': float(ticker.get('percentage', 0) or 0),
                'spread_pct': spread_pct,
            })

        candidates.sort(key=lambda x: x['volume'], reverse=True)
        top_candidates = candidates[:30]  # Top 30 para análise mais profunda

        self._candidates_cache = top_candidates
        self._candidates_cache_time = now
        return top_candidates

    async def _fetch_ohlcv_cached(self, symbols: List[str], timeframe: str, limit: int) -> Dict[str, Any]:
        now = time.time()
        result = {}
        symbols_to_fetch = []

        for sym in symbols:
            cache_key = f"{sym}_{timeframe}"
            if cache_key in self._ohlcv_cache:
                cached = self._ohlcv_cache[cache_key]
                if (now - cached['time']) < self._ohlcv_ttl:
                    result[sym] = cached['data']
                    continue
            symbols_to_fetch.append(sym)

        if symbols_to_fetch:
            fetched = await self.ex.fetch_ohlcv_batch(
                symbols_to_fetch,
                timeframe=timeframe,
                limit=limit,
                max_concurrent=8
            )
            for sym, data in fetched.items():
                if data:
                    cache_key = f"{sym}_{timeframe}"
                    self._ohlcv_cache[cache_key] = {'data': data, 'time': now}
                    result[sym] = data

        return result
