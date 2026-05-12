import requests
import json
import time
from typing import Dict, Optional, Any

class ExchangeManager:
    """Exchange manager ultra-leve usando requests direto (sem ccxt)."""

    def __init__(self, api_key: str, api_secret: str, exchange_id: str = 'bybit', sandbox: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.base_url = 'https://api-testnet.bybit.com' if sandbox else 'https://api.bybit.com'
        self.session = requests.Session()
        self.session.headers.update({
            'X-BAPI-API-KEY': api_key,
            'Content-Type': 'application/json'
        })
        self._leverage_cache = {}

    def _sign(self, payload: str) -> str:
        import hmac, hashlib
        timestamp = str(int(time.time() * 1000))
        recv_window = '5000'
        param_str = timestamp + self.api_key + recv_window + payload
        sign = hmac.new(
            self.api_secret.encode('utf-8'),
            param_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return timestamp, recv_window, sign

    async def validate_credentials(self) -> tuple:
        try:
            r = self.session.get(f'{self.base_url}/v5/user/query-api')
            if r.status_code == 200:
                return True, "API conectada", 'sandbox' if self.sandbox else 'mainnet'
            return False, f"Erro {r.status_code}", 'unknown'
        except Exception as e:
            return False, str(e), 'unknown'

    async def get_balance(self) -> Dict:
        try:
            r = self.session.get(f'{self.base_url}/v5/account/wallet-balance?accountType=UNIFIED')
            data = r.json()
            if data.get('retCode') == 0:
                result = data.get('result', {})
                return {'USDT': {'total': float(result.get('list', [{}])[0].get('coin', [{}])[0].get('walletBalance', 0))}}
            return {}
        except:
            return {}

    async def fetch_tickers(self) -> Dict:
        try:
            r = self.session.get(f'{self.base_url}/v5/market/tickers?category=linear')
            data = r.json()
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
        except:
            return {}

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '15', limit: int = 60) -> list:
        try:
            clean_sym = symbol.replace('/USDT:USDT', 'USDT')
            r = self.session.get(
                f'{self.base_url}/v5/market/kline?category=linear&symbol={clean_sym}&interval={timeframe}&limit={limit}'
            )
            data = r.json()
            if data.get('retCode') == 0:
                candles = []
                for item in data.get('result', {}).get('list', []):
                    candles.append([
                        int(item[0]),  # timestamp
                        float(item[1]),  # open
                        float(item[2]),  # high
                        float(item[3]),  # low
                        float(item[4]),  # close
                        float(item[5]),  # volume
                    ])
                return candles[::-1]  # Ordena do mais antigo para o mais recente
            return []
        except:
            return []

    async def fetch_ohlcv_batch(self, symbols: list, timeframe: str = '15', limit: int = 60, max_concurrent: int = 5) -> Dict:
        import concurrent.futures
        result = {}
        for sym in symbols[:max_concurrent]:
            data = await self.fetch_ohlcv(sym, timeframe, limit)
            if data:
                result[sym] = data
        return result

    async def get_position(self, symbol: str) -> Optional[Dict]:
        try:
            clean_sym = symbol.replace('/USDT:USDT', 'USDT')
            r = self.session.get(f'{self.base_url}/v5/position/list?category=linear&symbol={clean_sym}')
            data = r.json()
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
        except:
            return None

    async def fetch_ticker(self, symbol: str) -> Dict:
        try:
            clean_sym = symbol.replace('/USDT:USDT', 'USDT')
            r = self.session.get(f'{self.base_url}/v5/market/tickers?category=linear&symbol={clean_sym}')
            data = r.json()
            if data.get('retCode') == 0:
                item = data.get('result', {}).get('list', [{}])[0]
                return {'last': float(item.get('lastPrice', 0))}
            return {'last': 0}
        except:
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
            timestamp, recv_window, sign = self._sign(payload)
            headers = {
                'X-BAPI-TIMESTAMP': timestamp,
                'X-BAPI-RECV-WINDOW': recv_window,
                'X-BAPI-SIGN': sign,
            }
            r = self.session.post(
                f'{self.base_url}/v5/position/set-leverage',
                data=payload,
                headers=headers
            )
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
            timestamp, recv_window, sign = self._sign(payload)
            headers = {
                'X-BAPI-TIMESTAMP': timestamp,
                'X-BAPI-RECV-WINDOW': recv_window,
                'X-BAPI-SIGN': sign,
            }
            r = self.session.post(
                f'{self.base_url}/v5/order/create',
                data=payload,
                headers=headers
            )
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    async def close_position(self, symbol: str, side: str, amount: float) -> Dict:
        close_side = 'sell' if side == 'long' else 'buy'
        return await self.create_market_order(symbol, close_side, amount, reduce_only=True)

    def get_min_cost(self, symbol: str, price: float) -> float:
        return 5.0

    async def close(self):
        self.session.close()
