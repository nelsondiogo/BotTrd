import aiohttp
import asyncio
import json
import time
from typing import Dict, Optional, Any

class ExchangeManager:
    """Exchange manager 100% async usando aiohttp + Bybit V5 API."""

    def __init__(self, api_key: str, api_secret: str, exchange_id: str = 'bybit', sandbox: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.base_url = 'https://api-testnet.bybit.com' if sandbox else 'https://api.bybit.com'
        self.session: Optional[aiohttp.ClientSession] = None
        self._leverage_cache: Dict[str, int] = {}
        self._market_cache: Dict[str, Any] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _sign(self, payload: str) -> Dict[str, str]:
        import hmac, hashlib
        timestamp = str(int(time.time() * 1000))
        recv_window = '5000'
        param_str = timestamp + self.api_key + recv_window + payload
        sign = hmac.new(
            self.api_secret.encode('utf-8'),
            param_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return {
            'X-BAPI-API-KEY': self.api_key,
            'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': recv_window,
            'X-BAPI-SIGN': sign,
            'Content-Type': 'application/json'
        }

    async def validate_credentials(self) -> tuple:
        try:
            headers = self._sign("")
            session = await self._get_session()
            async with session.get(f'{self.base_url}/v5/user/query-api', headers=headers) as r:
                if r.status == 200:
                    return True, "API conectada", 'sandbox' if self.sandbox else 'mainnet'
                text = await r.text()
                return False, f"Erro {r.status}: {text}", 'unknown'
        except Exception as e:
            return False, str(e), 'unknown'

    async def get_balance(self) -> Dict:
        try:
            headers = self._sign("")
            session = await self._get_session()
            async with session.get(
                f'{self.base_url}/v5/account/wallet-balance?accountType=UNIFIED',
                headers=headers
            ) as r:
                data = await r.json()
                if data.get('retCode') == 0:
                    result = data.get('result', {})
                    coins = result.get('list', [{}])[0].get('coin', [])
                    for coin in coins:
                        if coin.get('coin') == 'USDT':
                            wb = coin.get('walletBalance', '')
                            eq = coin.get('equity', '')
                            avail = coin.get('availableToWithdraw', '')
                            wallet = float(wb) if wb and wb != '' else 0.0
                            equity = float(eq) if eq and eq != '' else 0.0
                            available = float(avail) if avail and avail != '' else 0.0
                            return {
                                'USDT': {
                                    'total': max(wallet, equity, available),
                                    'wallet': wallet,
                                    'equity': equity,
                                    'available': available
                                }
                            }
                    total_wb = result.get('list', [{}])[0].get('totalWalletBalance', '')
                    total_eq = result.get('list', [{}])[0].get('totalEquity', '')
                    tw = float(total_wb) if total_wb and total_wb != '' else 0.0
                    te = float(total_eq) if total_eq and total_eq != '' else 0.0
                    return {'USDT': {'total': max(tw, te), 'wallet': tw, 'equity': te, 'available': 0.0}}
                return {'USDT': {'total': 0.0, 'wallet': 0.0, 'equity': 0.0, 'available': 0.0}}
        except Exception:
            return {'USDT': {'total': 0.0, 'wallet': 0.0, 'equity': 0.0, 'available': 0.0}}

    async def fetch_tickers(self) -> Dict:
        try:
            session = await self._get_session()
            async with session.get(f'{self.base_url}/v5/market/tickers?category=linear') as r:
                data = await r.json()
                if data.get('retCode') == 0:
                    tickers = {}
                    for item in data.get('result', {}).get('list', []):
                        sym = item.get('symbol', '')
                        if sym.endswith('USDT'):
                            tickers[sym.replace('USDT', '/USDT:USDT')] = {
                                'last': float(item.get('lastPrice', 0)),
                                'bid': float(item.get('bid1Price', 0)),
                                'ask': float(item.get('ask1Price', 0)),
                                'quoteVolume': float(item.get('turnover24h', 0)),
                                'percentage': float(item.get('price24hPcnt', 0)) * 100,
                            }
                    return tickers
                return {}
        except Exception:
            return {}

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '15', limit: int = 60) -> list:
        try:
            clean_sym = symbol.replace('/USDT:USDT', 'USDT')
            session = await self._get_session()
            url = f'{self.base_url}/v5/market/kline?category=linear&symbol={clean_sym}&interval={timeframe}&limit={limit}'
            async with session.get(url) as r:
                data = await r.json()
                if data.get('retCode') == 0:
                    candles = []
                    for item in data.get('result', {}).get('list', []):
                        candles.append([
                            int(item[0]), float(item[1]), float(item[2]),
                            float(item[3]), float(item[4]), float(item[5]),
                        ])
                    return candles[::-1]
                return []
        except Exception:
            return []

    async def fetch_ohlcv_batch(self, symbols: list, timeframe: str = '15', limit: int = 60, max_concurrent: int = 8) -> Dict:
        sem = asyncio.Semaphore(max_concurrent)
        async def _fetch(sym):
            async with sem:
                return sym, await self.fetch_ohlcv(sym, timeframe, limit)
        tasks = [asyncio.create_task(_fetch(sym)) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        result = {}
        for res in results:
            if isinstance(res, tuple) and res[1]:
                result[res[0]] = res[1]
        return result

    async def get_position(self, symbol: str) -> Optional[Dict]:
        try:
            clean_sym = symbol.replace('/USDT:USDT', 'USDT')
            headers = self._sign("")
            session = await self._get_session()
            url = f'{self.base_url}/v5/position/list?category=linear&symbol={clean_sym}'
            async with session.get(url, headers=headers) as r:
                data = await r.json()
                if data.get('retCode') == 0:
                    positions = data.get('result', {}).get('list', [])
                    for pos in positions:
                        if float(pos.get('size', 0)) != 0:
                            return {
                                'side': 'long' if pos.get('side') == 'Buy' else 'short',
                                'entryPrice': float(pos.get('avgPrice', 0)),
                                'contracts': float(pos.get('size', 0)),
                                'unrealizedPnl': float(pos.get('unrealisedPnl', 0)),
                                'markPrice': float(pos.get('markPrice', 0)),
                                'symbol': symbol,
                            }
                    return None
                return None
        except Exception:
            return None

    async def fetch_ticker(self, symbol: str) -> Dict:
        try:
            clean_sym = symbol.replace('/USDT:USDT', 'USDT')
            session = await self._get_session()
            url = f'{self.base_url}/v5/market/tickers?category=linear&symbol={clean_sym}'
            async with session.get(url) as r:
                data = await r.json()
                if data.get('retCode') == 0:
                    item = data.get('result', {}).get('list', [{}])[0]
                    return {'last': float(item.get('lastPrice', 0))}
                return {'last': 0}
        except Exception:
            return {'last': 0}

    async def set_leverage(self, symbol: str, leverage: int) -> Dict:
        try:
            cache_key = f"{symbol}_{leverage}"
            if self._leverage_cache.get(cache_key):
                return {"status": "cached"}
            clean_sym = symbol.replace('/USDT:USDT', 'USDT')
            payload = json.dumps({
                'category': 'linear',
                'symbol': clean_sym,
                'buyLeverage': str(leverage),
                'sellLeverage': str(leverage),
            })
            headers = self._sign(payload)
            session = await self._get_session()
            async with session.post(
                f'{self.base_url}/v5/position/set-leverage',
                data=payload,
                headers=headers
            ) as r:
                self._leverage_cache[cache_key] = True
                return {"status": "ok"}
        except Exception as e:
            return {"error": str(e)}

    async def create_market_order(self, symbol: str, side: str, amount: float, reduce_only: bool = False) -> Dict:
        try:
            clean_sym = symbol.replace('/USDT:USDT', 'USDT')
            side_map = {'buy': 'Buy', 'sell': 'Sell'}
            payload = json.dumps({
                'category': 'linear',
                'symbol': clean_sym,
                'side': side_map.get(side, side),
                'orderType': 'Market',
                'qty': str(amount),
                'reduceOnly': reduce_only,
            })
            headers = self._sign(payload)
            session = await self._get_session()
            async with session.post(
                f'{self.base_url}/v5/order/create',
                data=payload,
                headers=headers
            ) as r:
                return await r.json()
        except Exception as e:
            return {"error": str(e)}

    async def close_position(self, symbol: str, side: str, amount: float) -> Dict:
        close_side = 'sell' if side == 'long' else 'buy'
        return await self.create_market_order(symbol, close_side, amount, reduce_only=True)

    def get_min_cost(self, symbol: str, price: float) -> float:
        return 5.0

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
