import asyncio
import aiohttp
import json
import time
import hmac
import hashlib
from typing import Dict, Optional, Any, List

class ExchangeManager:
    def __init__(self, api_key: str, api_secret: str, exchange_id: str = 'bybit', sandbox: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.base_url = 'https://api-testnet.bybit.com' if sandbox else 'https://api.bybit.com'
        self.session: Optional[aiohttp.ClientSession] = None
        self._leverage_cache: set = set()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={'Content-Type': 'application/json'},
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self.session

    def _headers(self, payload: str = "") -> Dict[str, str]:
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

    async def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, signed: bool = False, payload: str = "") -> Dict:
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"
        headers = self._headers(payload) if signed else {}
        try:
            if method.upper() == 'GET':
                async with session.get(url, headers=headers, params=params) as resp:
                    return await resp.json()
            else:
                async with session.post(url, headers=headers, data=payload) as resp:
                    return await resp.json()
        except asyncio.TimeoutError:
            return {'retCode': -1, 'retMsg': 'timeout'}
        except Exception as e:
            return {'retCode': -1, 'retMsg': str(e)}

    async def validate_credentials(self) -> tuple:
        data = await self._request('GET', '/v5/user/query-api', signed=True)
        if data.get('retCode') == 0:
            return True, "API conectada", 'sandbox' if self.sandbox else 'mainnet'
        return False, f"Erro {data.get('retCode')}: {data.get('retMsg', 'unknown')}", 'unknown'

    async def get_balance(self) -> Dict:
        """
        Bybit v5 UNIFIED wallet-balance.
        Estrutura real (availableToWithdraw é "" vazio para UNIFIED):
        result.list[0].coin[0].walletBalance = "1.19"
        result.list[0].coin[0].equity = "1.19"
        result.list[0].totalWalletBalance = "1.19"
        result.list[0].totalEquity = "1.19"
        """
        data = await self._request('GET', '/v5/account/wallet-balance?accountType=UNIFIED', signed=True)

        if data.get('retCode') == 0:
            result = data.get('result', {})
            accounts = result.get('list', [])

            for acc in accounts:
                # Nível da conta
                total_wallet_str = acc.get('totalWalletBalance', '')
                total_equity_str = acc.get('totalEquity', '')

                total_wallet = float(total_wallet_str) if total_wallet_str else 0.0
                total_equity = float(total_equity_str) if total_equity_str else 0.0

                # Nível do coin
                coins = acc.get('coin', [])
                usdt_wallet = 0.0
                usdt_equity = 0.0

                for coin in coins:
                    if coin.get('coin') == 'USDT':
                        wb = coin.get('walletBalance', '')
                        eq = coin.get('equity', '')
                        usdt_wallet = float(wb) if wb and wb != '' else 0.0
                        usdt_equity = float(eq) if eq and eq != '' else 0.0
                        break

                # Usa o MAIOR valor encontrado (walletBalance do coin é mais preciso)
                final_total = max(usdt_wallet, usdt_equity, total_wallet, total_equity)

                return {
                    'USDT': {
                        'total': final_total,
                        'wallet': usdt_wallet,
                        'equity': usdt_equity,
                        'total_wallet': total_wallet,
                        'total_equity': total_equity,
                    }
                }

        return {'USDT': {'total': 0.0, 'wallet': 0.0, 'equity': 0.0, 'total_wallet': 0.0, 'total_equity': 0.0}}

    async def fetch_tickers(self) -> Dict:
        data = await self._request('GET', '/v5/market/tickers?category=linear')
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
                        'high24h': float(item.get('highPrice24h', 0)),
                        'low24h': float(item.get('lowPrice24h', 0)),
                    }
            return tickers
        return {}

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '15', limit: int = 60) -> List[List[float]]:
        clean_sym = symbol.replace('/USDT:USDT', 'USDT')
        data = await self._request('GET', f'/v5/market/kline?category=linear&symbol={clean_sym}&interval={timeframe}&limit={limit}')
        if data.get('retCode') == 0:
            candles = []
            for item in data.get('result', {}).get('list', []):
                candles.append([
                    int(item[0]), float(item[1]), float(item[2]),
                    float(item[3]), float(item[4]), float(item[5]),
                ])
            return candles[::-1]
        return []

    async def fetch_ohlcv_batch(self, symbols: List[str], timeframe: str = '15', limit: int = 60, max_concurrent: int = 8) -> Dict[str, List[List[float]]]:
        sem = asyncio.Semaphore(max_concurrent)
        async def _fetch_one(sym: str) -> tuple:
            async with sem:
                data = await self.fetch_ohlcv(sym, timeframe, limit)
                return sym, data
        tasks = [_fetch_one(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = {}
        for res in results:
            if isinstance(res, tuple) and res[1]:
                out[res[0]] = res[1]
        return out

    async def get_position(self, symbol: str) -> Optional[Dict]:
        clean_sym = symbol.replace('/USDT:USDT', 'USDT')
        data = await self._request('GET', f'/v5/position/list?category=linear&symbol={clean_sym}', signed=True)
        if data.get('retCode') == 0:
            positions = data.get('result', {}).get('list', [])
            for pos in positions:
                size = float(pos.get('size', 0))
                if size != 0:
                    side = 'long' if pos.get('side') == 'Buy' else 'short'
                    entry = float(pos.get('avgPrice', 0))
                    mark = float(pos.get('markPrice', 0))
                    unrealized = float(pos.get('unrealisedPnl', 0))
                    return {
                        'side': side,
                        'entryPrice': entry,
                        'contracts': size,
                        'unrealizedPnl': unrealized,
                        'markPrice': mark,
                        'symbol': symbol,
                        'leverage': int(pos.get('leverage', 1)),
                        'liqPrice': float(pos.get('liqPrice', 0)),
                    }
        return None

    async def fetch_ticker(self, symbol: str) -> Dict:
        clean_sym = symbol.replace('/USDT:USDT', 'USDT')
        data = await self._request('GET', f'/v5/market/tickers?category=linear&symbol={clean_sym}')
        if data.get('retCode') == 0:
            item = data.get('result', {}).get('list', [{}])[0]
            return {'last': float(item.get('lastPrice', 0))}
        return {'last': 0}

    async def set_leverage(self, symbol: str, leverage: int) -> Dict:
        cache_key = f"{symbol}_{leverage}"
        if cache_key in self._leverage_cache:
            return {"status": "cached"}
        clean_sym = symbol.replace('/USDT:USDT', 'USDT')
        payload = json.dumps({
            'category': 'linear',
            'symbol': clean_sym,
            'buyLeverage': str(leverage),
            'sellLeverage': str(leverage),
        })
        data = await self._request('POST', '/v5/position/set-leverage', signed=True, payload=payload)
        if data.get('retCode') == 0 or 'leverage not modified' in str(data.get('retMsg', '')).lower():
            self._leverage_cache.add(cache_key)
            return {"status": "ok"}
        return {"status": "error", "msg": data.get('retMsg')}

    async def create_market_order(self, symbol: str, side: str, amount: float, reduce_only: bool = False) -> Dict:
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
        return await self._request('POST', '/v5/order/create', signed=True, payload=payload)

    async def close_position(self, symbol: str, side: str, amount: float) -> Dict:
        close_side = 'sell' if side == 'long' else 'buy'
        return await self.create_market_order(symbol, close_side, amount, reduce_only=True)

    def get_min_cost(self, symbol: str, price: float) -> float:
        return 5.0

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
