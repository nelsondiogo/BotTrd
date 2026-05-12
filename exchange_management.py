import ccxt.async_support as ccxt_async
import asyncio
import time
from typing import Dict, List, Optional, Any

class ExchangeManager:
    """Gerenciador único de exchange — async apenas, com cache inteligente."""

    def __init__(self, api_key: str, api_secret: str, exchange_id: str = 'bybit', sandbox: bool = True):
        self.exchange_id = exchange_id.lower()
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.exchange = None
        self._build_exchange(sandbox)

        # Caches com TTL (Time To Live)
        self._leverage_cache: Dict[str, Any] = {}
        self._markets_cache: Optional[Dict] = None
        self._markets_cache_time: float = 0
        self._markets_ttl: float = 3600  # 1 hora

        self._tickers_cache: Optional[Dict] = None
        self._tickers_cache_time: float = 0
        self._tickers_ttl: float = 5  # 5 segundos

        self._min_cost_cache: Dict[str, float] = {}

    def _build_exchange(self, sandbox: bool):
        """Constrói instância CCXT com configurações otimizadas."""
        config = {
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',
                'adjustForTimeDifference': True,
            },
            'aiohttp_trust_env': True,
        }

        if self.exchange_id == 'binance':
            self.exchange = ccxt_async.binance(config)
        elif self.exchange_id == 'bybit':
            self.exchange = ccxt_async.bybit(config)
        else:
            raise ValueError(f"Exchange '{self.exchange_id}' não suportada.")

        if sandbox:
            self.exchange.set_sandbox_mode(True)

    async def load_markets(self, force: bool = False):
        """Carrega markets com cache persistente."""
        now = time.time()
        if not force and self._markets_cache and (now - self._markets_cache_time) < self._markets_ttl:
            self.exchange.markets = self._markets_cache
            return

        if not self.exchange.markets:
            await self.exchange.load_markets()
            self._markets_cache = self.exchange.markets
            self._markets_cache_time = now

    def _is_blocked_error(self, error_msg: str) -> bool:
        msg = str(error_msg).lower()
        return any(k in msg for k in ['403', 'forbidden', 'cloudfront', 'blocked'])

    async def validate_credentials(self) -> tuple:
        """Valida credenciais com detecção automática de ambiente."""
        last_error = "Erro desconhecido"
        try:
            await self.exchange.fetch_balance()
            detected = 'sandbox' if self.sandbox else 'mainnet'
            return True, "API conectada com sucesso.", detected
        except Exception as e1:
            last_error = str(e1)
            if self._is_blocked_error(last_error) and self.sandbox:
                return False, "TESTNET BLOQUEADA pelo servidor. Desmarque 'Modo Sandbox' e salve.", 'blocked'

        if self.sandbox:
            try:
                temp = ccxt_async.bybit({
                    'apiKey': self.api_key, 'secret': self.api_secret,
                    'enableRateLimit': True, 'options': {'defaultType': 'swap'}
                })
                await temp.fetch_balance()
                await temp.close()
                return False, "Suas chaves são da MAINNET. Desmarque 'Modo Sandbox' e salve.", 'mainnet'
            except Exception as e2:
                last_error = str(e2)
                if self._is_blocked_error(last_error):
                    return False, "TESTNET BLOQUEADA. Use Mainnet.", 'blocked'

        if not self.sandbox:
            try:
                temp = ccxt_async.bybit({
                    'apiKey': self.api_key, 'secret': self.api_secret,
                    'enableRateLimit': True, 'options': {'defaultType': 'swap'}
                })
                temp.set_sandbox_mode(True)
                await temp.fetch_balance()
                await temp.close()
                return False, "Suas chaves são da TESTNET. Marque 'Modo Sandbox' e salve.", 'sandbox'
            except Exception as e3:
                last_error = str(e3)

        if '10003' in last_error or 'invalid' in last_error.lower():
            return False, "API Key inválida. Verifique permissões.", 'unknown'
        return False, f"Erro: {last_error[:120]}", 'unknown'

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '15m', limit: int = 100, timeout_sec: float = 8.0):
        """Busca candles com timeout e validação."""
        try:
            data = await asyncio.wait_for(
                self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit),
                timeout=timeout_sec
            )
            if not data or len(data) == 0:
                raise ValueError("Candles vazios")
            return [c for c in data if c and len(c) == 6 and all(x is not None for x in c[1:6])]
        except asyncio.TimeoutError:
            raise ValueError(f"Timeout ao buscar OHLCV para {symbol}")

    async def fetch_ohlcv_batch(self, symbols: List[str], timeframe: str = '15m', limit: int = 100, max_concurrent: int = 5):
        """Busca candles em paralelo com semáforo otimizado."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _fetch(sym: str):
            async with semaphore:
                try:
                    return sym, await self.fetch_ohlcv(sym, timeframe, limit)
                except Exception:
                    return sym, None

        results = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
        out = {}
        for r in results:
            if isinstance(r, tuple) and r[1] is not None:
                out[r[0]] = r[1]
        return out

    async def fetch_tickers(self, symbols: Optional[List[str]] = None) -> Dict:
        """Busca tickers com cache e filtro opcional de símbolos."""
        now = time.time()

        # Usa cache se recente e não há filtro específico
        if symbols is None and self._tickers_cache and (now - self._tickers_cache_time) < self._tickers_ttl:
            return self._tickers_cache

        try:
            if symbols and len(symbols) <= 20:
                # Para poucos pares, busca individualmente (mais rápido)
                tickers = {}
                for sym in symbols:
                    try:
                        ticker = await self.exchange.fetch_ticker(sym)
                        tickers[sym] = ticker
                    except Exception:
                        pass
            else:
                # Para muitos pares, busca todos de uma vez
                tickers = await self.exchange.fetch_tickers()

            if symbols is None:
                self._tickers_cache = tickers
                self._tickers_cache_time = now

            return tickers
        except Exception:
            return self._tickers_cache or {}

    async def get_balance(self) -> Dict:
        """Busca saldo com tratamento de erro."""
        try:
            return await self.exchange.fetch_balance()
        except Exception:
            return {}

    async def get_position(self, symbol: str) -> Optional[Dict]:
        """Busca posição específica com parsing otimizado."""
        try:
            positions = await self.exchange.fetch_positions([symbol])
            for pos in positions:
                contracts = pos.get('contracts')
                if contracts is not None and float(contracts or 0) != 0:
                    return {
                        'side': 'long' if pos.get('side') == 'long' else 'short',
                        'entryPrice': float(pos.get('entryPrice') or 0),
                        'contracts': float(pos.get('contracts') or 0),
                        'unrealizedPnl': float(pos.get('unrealizedPnl') or 0),
                        'symbol': symbol,
                        'markPrice': float(pos.get('markPrice') or pos.get('lastPrice') or 0),
                        'liquidationPrice': float(pos.get('liquidationPrice') or 0),
                        'leverage': float(pos.get('leverage') or 1),
                    }
            return None
        except Exception:
            return None

    async def fetch_ticker(self, symbol: str) -> Dict:
        """Busca ticker único."""
        return await self.exchange.fetch_ticker(symbol)

    async def fetch_funding_rate(self, symbol: str) -> Optional[Dict]:
        """Busca taxa de funding."""
        try:
            return await self.exchange.fetch_funding_rate(symbol)
        except Exception:
            return None

    async def set_leverage(self, symbol: str, leverage: int) -> Dict:
        """Define alavancagem com cache."""
        try:
            cache_key = f"{symbol}_{leverage}"
            if self._leverage_cache.get(cache_key):
                return {"status": "cached"}

            res = await self.exchange.set_leverage(leverage, symbol)
            self._leverage_cache[cache_key] = True
            return res
        except Exception as e:
            err = str(e)
            if 'leverage not modified' in err.lower() or 'same leverage' in err.lower():
                self._leverage_cache[f"{symbol}_{leverage}"] = True
                return {"status": "already_set"}
            return {"error": err}

    async def create_market_order(self, symbol: str, side: str, amount: float, reduce_only: bool = False) -> Dict:
        """Cria ordem de mercado com timeout."""
        params = {'reduceOnly': True} if reduce_only else {}
        try:
            if side == 'buy':
                return await asyncio.wait_for(
                    self.exchange.create_market_buy_order(symbol, amount, params),
                    timeout=10.0
                )
            else:
                return await asyncio.wait_for(
                    self.exchange.create_market_sell_order(symbol, amount, params),
                    timeout=10.0
                )
        except asyncio.TimeoutError:
            raise ValueError(f"Timeout ao criar ordem {side} para {symbol}")

    async def close_position(self, symbol: str, side: str, amount: float) -> Dict:
        """Fecha posição com ordem reduce-only."""
        close_side = 'sell' if side == 'long' else 'buy'
        return await self.create_market_order(symbol, close_side, amount, reduce_only=True)

    def get_min_cost(self, symbol: str, price: float) -> float:
        """Retorna custo mínimo com cache."""
        if symbol in self._min_cost_cache:
            return self._min_cost_cache[symbol]

        try:
            market = self.exchange.market(symbol)
            limits = market.get('limits', {})
            amount_min = limits.get('amount', {}).get('min')
            cost_min = limits.get('cost', {}).get('min')

            if cost_min:
                result = float(cost_min)
            elif amount_min and price:
                result = float(amount_min) * float(price)
            else:
                result = 5.0

            self._min_cost_cache[symbol] = result
            return result
        except Exception:
            return 5.0

    async def close(self):
        """Fecha conexão e limpa caches."""
        try:
            await self.exchange.close()
        except Exception:
            pass
        finally:
            self._leverage_cache.clear()
            self._min_cost_cache.clear()
            self._tickers_cache = None
            self._tickers_cache_time = 0
