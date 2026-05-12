import os
import json
import time
import asyncio
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify

from exchange_management import ExchangeManager
from market_scanner import MarketScanner
from trading_engine import PositionTracker, OpportunityAnalyzer, RiskManager, SignalResult
from history_manager import add_trade, get_history, get_stats, save_bot_state, load_bot_state, get_recent_trades

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nd-bot-hft-secret')

SETTINGS_FILE = 'settings.json'

# =============================================================================
# ESTADO GLOBAL
# =============================================================================
class BotController:
    def __init__(self):
        self.running = False
        self.state = {
            'status': 'parado',
            'session_start_balance': 0.0,
            'current_balance': 0.0,
            'unrealized_pnl': 0.0,
            'realized_pnl': 0.0,
            'current_position': None,
            'last_signal': '-',
            'pnl_history': [],
            'price_history': [],
            'active_pairs': [],
            'scan_results': [],
            'pairs_24h': {},
            'last_scan': '-',
            'scan_latency_ms': 0,
            'api_valid': False,
            'api_message': '',
            'api_environment': '-',
            'chart_symbol': 'BTCUSDT.P',
            'entry_line': None,
            'logs': [],
            'peak_pnl_pct': 0.0,
            'lock_price': None,
            'lock_stage_pct': 0.0,
            'opened_at': None,
            'consecutive_losses': 0,
            'circuit_breaker_triggered': False,
            'total_trades_today': 0,
        }
        self.ex_global = None
        self.tracker_global = None
        self.scanner_global = None
        self._scan_task = None
        self._monitor_task = None
        self._executor_task = None
        self._health_task = None

controller = BotController()


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'api_key': '', 'api_secret': '', 'trailing_stop_pct': 0.7,
        'stop_loss_pct': 1.5, 'leverage': 3, 'timeframe': '15m',
        'exchange': 'bybit', 'sandbox': True, 'order_size_usdt': 0.9
    }

def save_settings(data):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def add_log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    controller.state['logs'].append(f"[{ts}] {msg}")
    if len(controller.state['logs']) > 500:
        controller.state['logs'].pop(0)

def safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

def get_total_balance(balance_obj):
    if not balance_obj or not isinstance(balance_obj, dict):
        return 0.0
    usdt = balance_obj.get('USDT', {})
    total = safe_float(usdt.get('total'), 0.0)
    if total <= 0:
        total = safe_float(usdt.get('equity'), 0.0)
    if total <= 0:
        total = safe_float(usdt.get('available'), 0.0)
    return total

def symbol_to_tv(symbol):
    if not symbol:
        return 'BTCUSDT.P'
    s = symbol.replace('/USDT:USDT', 'USDT').replace('/USDT', 'USDT').replace('/', '')
    return s + '.P' if not s.endswith('.P') else s

def _update_bot_state(**kwargs):
    controller.state.update(kwargs)

def _reset_position_state():
    controller.state.update(
        current_position=None,
        entry_line=None,
        unrealized_pnl=0.0,
        peak_pnl_pct=0.0,
        lock_price=None,
        lock_stage_pct=0.0,
        opened_at=None,
        price_history=[],
        chart_symbol='BTCUSDT.P',
    )

async def _close_and_record(ex, tracker, reason='MANUAL'):
    if not tracker or not tracker.symbol or tracker.size <= 0:
        return False
    try:
        pos = await ex.get_position(tracker.symbol)
        if pos and safe_float(pos.get('contracts'), 0) > 0:
            price = safe_float(pos.get('markPrice'), 0)
            unrealized = safe_float(pos.get('unrealizedPnl'), 0)
            await ex.close_position(tracker.symbol, tracker.side, tracker.size)

            add_log(f"CLOSE {reason} | {tracker.symbol} @ {price} | PnL: {unrealized:.5f}")
            await add_trade(
                tracker.symbol, tracker.side,
                tracker.entry_price, price, unrealized,
                reason, tracker.leverage
            )

            if unrealized < 0:
                controller.state['consecutive_losses'] += 1
            else:
                controller.state['consecutive_losses'] = 0

            realized = safe_float(controller.state.get('realized_pnl'), 0) + unrealized
            _update_bot_state(realized_pnl=round(realized, 8))
            controller.state['total_trades_today'] += 1
            return True
    except Exception as e:
        add_log(f"ERRO FECHAR {reason}: {e}")
    return False


# =============================================================================
# TASKS ASYNC
# =============================================================================
async def scanner_task(ex, settings, tracker):
    scanner = MarketScanner(ex, settings)
    scanner_interval = 15
    last_balance = 0.0
    last_balance_time = 0

    while controller.running:
        start_time = time.time()
        try:
            now = time.time()
            if now - last_balance_time > 20 or last_balance <= 0:
                try:
                    bal = await ex.get_balance()
                    last_balance = get_total_balance(bal)
                    last_balance_time = now
                except Exception:
                    pass

            total_bal = last_balance if last_balance > 0 else (tracker.session_start_balance or 1.0)

            tf_map = {'5m': '5', '15m': '15', '1h': '60'}
            tf = tf_map.get(settings.get('timeframe', '15m'), '15')

            res = await asyncio.wait_for(
                scanner.scan(balance=total_bal, top_n=10, timeframe=tf),
                timeout=12.0
            )

            latency = int((time.time() - start_time) * 1000)
            pairs = res.get('pairs', [])
            error = res.get('error')

            if error:
                add_log(f"SCAN ERRO [{latency}ms]: {error}")
            else:
                top_sym = pairs[0]['symbol'] if pairs else 'nenhuma'
                top_score = pairs[0]['score'] if pairs else 0
                add_log(f"SCAN [{latency}ms] | {len(pairs)} ops | TOP: {top_sym} ({top_score:.2f})")

            pairs_24h = {}
            for p in pairs:
                pairs_24h[p['symbol']] = {
                    'last': p['price'],
                    'high': p['price'] * 1.02,
                    'low': p['price'] * 0.98,
                    'change': p.get('change_24h', 0)
                }

            _update_bot_state(
                scan_results=pairs,
                active_pairs=[p['symbol'] for p in pairs],
                pairs_24h=pairs_24h,
                last_scan=datetime.now().strftime('%H:%M:%S'),
                scan_latency_ms=latency,
                current_balance=round(total_bal, 8),
            )

            if int(now) % 20 < 2:
                await save_bot_state({
                    'session_start_balance': controller.state.get('session_start_balance', 0),
                    'scan_results': pairs,
                    'last_scan': datetime.now().isoformat(),
                    'scan_latency_ms': latency,
                })

        except asyncio.TimeoutError:
            add_log("SCAN TIMEOUT | Scan > 12s")
        except Exception as e:
            add_log(f"SCANNER TASK: {e}")

        elapsed = time.time() - start_time
        sleep_time = max(0.5, scanner_interval - elapsed)
        await asyncio.sleep(sleep_time)


async def monitor_task(ex, settings, tracker):
    sl_pct = safe_float(settings.get('stop_loss_pct'), 1.5)
    monitor_interval = 0.8

    while controller.running:
        try:
            if not tracker.symbol:
                await asyncio.sleep(monitor_interval)
                continue

            pos = await ex.get_position(tracker.symbol)
            if not pos or safe_float(pos.get('contracts'), 0) == 0:
                tracker.reset()
                _reset_position_state()
                await asyncio.sleep(monitor_interval)
                continue

            current_price = safe_float(pos.get('markPrice'), 0)
            if current_price <= 0:
                await asyncio.sleep(monitor_interval)
                continue

            unrealized = safe_float(pos.get('unrealizedPnl'), 0)
            tracker.update_peak(current_price)

            controller.state['price_history'].append({
                't': datetime.now().strftime('%H:%M:%S'),
                'p': round(current_price, 8)
            })
            if len(controller.state['price_history']) > 300:
                controller.state['price_history'].pop(0)

            lock_price = None
            if tracker.locked and tracker.entry_price > 0:
                if tracker.side == 'long':
                    lock_price = tracker.entry_price * (1 + tracker.lock_profit_pct / 100)
                else:
                    lock_price = tracker.entry_price * (1 - tracker.lock_profit_pct / 100)

            session_start = safe_float(controller.state.get('session_start_balance'), 0)
            realized = safe_float(controller.state.get('realized_pnl'), 0)
            current_bal = session_start + realized + unrealized

            total_pnl = realized + unrealized
            controller.state['pnl_history'].append({
                'time': datetime.now().strftime('%H:%M:%S'),
                'pnl': round(total_pnl, 8)
            })
            if len(controller.state['pnl_history']) > 120:
                controller.state['pnl_history'].pop(0)

            _update_bot_state(
                current_position={
                    'side': pos['side'], 'entry': pos['entryPrice'],
                    'size': pos['contracts'], 'unrealized_pnl': round(unrealized, 8),
                    'symbol': tracker.symbol, 'price': round(current_price, 8),
                    'leverage': pos.get('leverage', tracker.leverage),
                    'liqPrice': pos.get('liqPrice', 0),
                },
                unrealized_pnl=round(unrealized, 8),
                current_balance=round(current_bal, 8),
                peak_pnl_pct=round(tracker.peak_profit_pct, 3) if tracker.peak_profit_pct > -900 else 0.0,
                lock_price=round(lock_price, 8) if lock_price else None,
                lock_stage_pct=round(tracker.lock_stage_pct, 3) if tracker.lock_stage_pct else 0.0,
                chart_symbol=symbol_to_tv(tracker.symbol),
            )

            if tracker.check_stop_loss(current_price, sl_pct):
                try:
                    await ex.close_position(tracker.symbol, tracker.side, tracker.size)
                    add_log(f"STOP LOSS | {tracker.symbol} @ {current_price} | PnL: {unrealized:.5f}")
                    await add_trade(tracker.symbol, tracker.side, tracker.entry_price, current_price, unrealized, 'STOP LOSS', tracker.leverage)
                    if unrealized < 0:
                        controller.state['consecutive_losses'] += 1
                    else:
                        controller.state['consecutive_losses'] = 0
                    _update_bot_state(realized_pnl=round(realized + unrealized, 8))
                    _reset_position_state()
                    tracker.reset()
                except Exception as e:
                    add_log(f"ERRO SL: {e}")
                await asyncio.sleep(1)
                continue

            should_close, reason = tracker.check_trailing_stop(current_price)
            if should_close:
                add_log(f"TRAIL | {tracker.symbol} | {reason} | price:{current_price:.6f} peak:{tracker.peak_profit_pct:.3f}%")
                try:
                    await ex.close_position(tracker.symbol, tracker.side, tracker.size)
                    add_log(f"CLOSE {reason} | {tracker.symbol} @ {current_price} | PnL: {unrealized:.5f}")
                    await add_trade(tracker.symbol, tracker.side, tracker.entry_price, current_price, unrealized, reason, tracker.leverage)
                    if unrealized < 0:
                        controller.state['consecutive_losses'] += 1
                    else:
                        controller.state['consecutive_losses'] = 0
                    _update_bot_state(realized_pnl=round(realized + unrealized, 8))
                    _reset_position_state()
                    tracker.reset()
                except Exception as e:
                    add_log(f"ERRO TRAIL: {e}")
                await asyncio.sleep(1)
                continue

            await asyncio.sleep(monitor_interval)
        except Exception as e:
            add_log(f"MONITOR TASK: {e}")
            await asyncio.sleep(2)


async def executor_task(ex, settings, tracker):
    risk_mgr = RiskManager(base_leverage=int(settings.get('leverage', 3)))
    opp_analyzer = OpportunityAnalyzer(rotation_threshold=1.15)
    max_consecutive_losses = 3
    executor_interval = 2.0

    while controller.running:
        try:
            await asyncio.sleep(executor_interval)

            if controller.state['consecutive_losses'] >= max_consecutive_losses:
                if not controller.state['circuit_breaker_triggered']:
                    add_log(f"CIRCUIT BREAKER | {controller.state['consecutive_losses']} perdas. PAUSADO.")
                    controller.state['circuit_breaker_triggered'] = True
                    controller.state['status'] = 'CIRCUIT_BREAKER'
                await asyncio.sleep(5)
                continue

            scan_results = list(controller.state.get('scan_results', []))
            current_pos = controller.state.get('current_position')

            if not scan_results:
                continue

            best = scan_results[0]
            best_signal = SignalResult(
                side=best.get('side'), symbol=best.get('symbol'),
                score=best.get('score', 0), price=best.get('price', 0),
                expected_return_pct=best.get('expected_return_pct', 0),
                meta=best,
            )

            if not tracker.symbol:
                if best_signal.score < 0.82:
                    continue
                if best_signal.confidence == 'low':
                    continue

                bal = await ex.get_balance()
                total_bal = get_total_balance(bal)
                if total_bal <= 0:
                    total_bal = tracker.session_start_balance or 1.0

                if total_bal < tracker.session_start_balance * 0.90:
                    add_log("STOP GLOBAL | Saldo < 90%% do inicial")
                    controller.state['status'] = 'STOP_GLOBAL'
                    controller.running = False
                    continue

                sym = best_signal.symbol
                price = best_signal.price

                recent_trades = await get_recent_trades(5)
                recent_losses = sum(1 for t in recent_trades if t.get('net_pnl', 0) < 0)
                if recent_losses >= 2 and any(t.get('symbol') == sym for t in recent_trades[-2:]):
                    add_log(f"BLOQUEIO | {sym} em sequencia perdedora")
                    continue

                adx = best_signal.meta.get('adx', 25)
                lev = risk_mgr.dynamic_leverage(adx, int(settings.get('leverage', 3)))
                lev = min(lev, 5)

                try:
                    await ex.set_leverage(sym, lev)
                except Exception as e:
                    add_log(f"Leverage warn: {e}")

                min_cost = ex.get_min_cost(sym, price)
                qty = risk_mgr.calculate_position_size(total_bal, price, lev, risk_pct=0.015, min_cost=min_cost)
                if qty <= 0 or (qty * price) < min_cost:
                    add_log(f"BLOQUEIO | Qty insuficiente {sym}")
                    continue

                try:
                    ticker_now = await ex.fetch_ticker(sym)
                    current_price = safe_float(ticker_now.get('last'), price)
                    slip_pct = abs(current_price - price) / price * 100
                    if slip_pct > 0.25:
                        add_log(f"BLOQUEIO | Slippage {slip_pct:.2f}% > 0.25% em {sym}")
                        continue
                    price = current_price
                except Exception:
                    pass

                try:
                    side_order = 'buy' if best_signal.side == 'long' else 'sell'
                    order_res = await ex.create_market_order(sym, side_order, qty)
                    if order_res.get('retCode') != 0:
                        add_log(f"ERRO ORDEM | {order_res.get('retMsg')}")
                        continue

                    add_log(f"ENTRY {best_signal.side.upper()} {sym} @ {price} | Score:{best_signal.score:.2f} ADX:{adx:.1f} LEV:{lev}x MFI:{best_signal.meta.get('mfi', 0):.1f} ExpRet:{best_signal.expected_return_pct:.2f}%")

                    tracker.side = best_signal.side
                    tracker.symbol = sym
                    tracker.entry_price = price
                    tracker.entry_score = best_signal.score
                    tracker.size = qty
                    tracker.leverage = lev
                    tracker.peak_profit_pct = -999.0
                    tracker.peak_price = price
                    tracker.locked = False
                    tracker.lock_profit_pct = 0.0
                    tracker.lock_stage_pct = 0.0
                    tracker.entry_time = time.time()
                    tracker.max_drawdown_pct = 0.0

                    _update_bot_state(
                        last_signal=f"{best_signal.side.upper()} {sym}",
                        chart_symbol=symbol_to_tv(sym),
                        entry_line=price,
                        opened_at=datetime.now().isoformat(),
                        circuit_breaker_triggered=False,
                    )
                    await save_bot_state({
                        'session_start_balance': controller.state.get('session_start_balance', 0),
                        'tracker': tracker.get_state(),
                        'last_signal': f"{best_signal.side.upper()} {sym}",
                        'entry_line': price,
                    })
                except Exception as e:
                    add_log(f"ERRO ENTRY: {e}")
                continue

            if tracker.symbol and best_signal.symbol and best_signal.symbol != tracker.symbol:
                unrealized = safe_float(current_pos.get('unrealized_pnl'), 0) if current_pos else 0
                current_price = safe_float(current_pos.get('price'), 0) if current_pos else 0

                if opp_analyzer.should_rotate(tracker, best_signal, unrealized, current_price):
                    add_log(f"ROTATE | {tracker.symbol} -> {best_signal.symbol} | Score novo: {best_signal.score:.2f} vs atual: {tracker.entry_score:.2f}")
                    try:
                        await ex.close_position(tracker.symbol, tracker.side, tracker.size)
                        await add_trade(tracker.symbol, tracker.side, tracker.entry_price, current_price, unrealized, 'ROTATE_OPP_COST', tracker.leverage)
                        if unrealized < 0:
                            controller.state['consecutive_losses'] += 1
                        else:
                            controller.state['consecutive_losses'] = 0
                        _update_bot_state(realized_pnl=round(safe_float(controller.state.get('realized_pnl'), 0) + unrealized, 8))
                        _reset_position_state()
                        tracker.reset()
                        await asyncio.sleep(1.5)
                    except Exception as e:
                        add_log(f"ERRO ROTATE: {e}")
        except Exception as e:
            add_log(f"EXECUTOR TASK: {e}")


async def health_check_task(ex):
    while controller.running:
        try:
            await asyncio.sleep(45)
            await ex.fetch_ticker('BTCUSDT:USDT')
        except Exception as e:
            add_log(f"HEALTH: {e}")


# =============================================================================
# TRADING LOOP
# =============================================================================
async def trading_loop_async():
    settings = load_settings()

    ex = ExchangeManager(
        settings['api_key'], settings['api_secret'],
        settings.get('exchange', 'bybit'), settings.get('sandbox', True)
    )
    controller.ex_global = ex

    try:
        ok, msg, env = await ex.validate_credentials()
        if not ok:
            add_log(f"API INVALID: {msg}")
            _update_bot_state(api_valid=False, api_message=msg, status='ERRO_API')
            return

        _update_bot_state(api_valid=True, api_message=msg, api_environment=env)
        add_log(f"API OK | {env}")

        bal = await ex.get_balance()
        total_bal = get_total_balance(bal)
        if total_bal <= 0:
            add_log("BALANCE ZERO - usando 1.0 como referencia")
            total_bal = 1.0

        tracker = PositionTracker()
        tracker.session_start_balance = total_bal
        controller.tracker_global = tracker

        _update_bot_state(
            status='operando',
            session_start_balance=round(total_bal, 8),
            current_balance=round(total_bal, 8),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            consecutive_losses=0,
            circuit_breaker_triggered=False,
            total_trades_today=0,
        )
        add_log(f"START HFT | Balance: {total_bal:.5f} USDT")

        controller._scan_task = asyncio.create_task(scanner_task(ex, settings, tracker))
        controller._monitor_task = asyncio.create_task(monitor_task(ex, settings, tracker))
        controller._executor_task = asyncio.create_task(executor_task(ex, settings, tracker))
        controller._health_task = asyncio.create_task(health_check_task(ex))

        await asyncio.gather(
            controller._scan_task,
            controller._monitor_task,
            controller._executor_task,
            controller._health_task,
            return_exceptions=True
        )

    except Exception as e:
        add_log(f"TRADING LOOP: {e}")
    finally:
        controller.running = False
        _update_bot_state(status='parado')
        try:
            await ex.close()
        except Exception:
            pass


# =============================================================================
# ROTAS FLASK
# =============================================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/state')
def api_state():
    return jsonify(controller.state)

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        data = request.get_json() or {}
        save_settings(data)
        return jsonify({'status': 'saved'})
    return jsonify(load_settings())

@app.route('/api/validate', methods=['POST'])
def api_validate():
    settings = load_settings()
    ex = ExchangeManager(
        settings['api_key'], settings['api_secret'],
        settings.get('exchange', 'bybit'), settings.get('sandbox', True)
    )

    async def _validate():
        try:
            ok, msg, env = await ex.validate_credentials()
            await ex.close()
            return ok, msg, env
        except Exception as e:
            await ex.close()
            return False, str(e), 'unknown'

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        ok, msg, env = loop.run_until_complete(_validate())
        loop.close()
        return jsonify({'valid': ok, 'message': msg, 'environment': env})
    except Exception as e:
        return jsonify({'valid': False, 'message': str(e), 'environment': 'unknown'})

@app.route('/api/bot/start', methods=['POST'])
def api_bot_start():
    if controller.running:
        return jsonify({'status': 'ja_rodando'})

    controller.running = True
    controller.state['status'] = 'iniciando'
    controller.state['logs'] = []
    controller.state['consecutive_losses'] = 0
    controller.state['circuit_breaker_triggered'] = False

    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(trading_loop_async())
        loop.close()

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()

    return jsonify({'status': 'iniciado'})

@app.route('/api/bot/stop', methods=['POST'])
def api_bot_stop():
    controller.running = False
    controller.state['status'] = 'parando'

    for task_attr in ['_scan_task', '_monitor_task', '_executor_task', '_health_task']:
        task = getattr(controller, task_attr, None)
        if task and not task.done():
            task.cancel()

    if controller.tracker_global and controller.tracker_global.symbol:
        async def _close():
            await _close_and_record(controller.ex_global, controller.tracker_global, 'MANUAL_STOP')
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_close())
            loop.close()
        except Exception as e:
            add_log(f"ERRO STOP: {e}")

    controller.state['status'] = 'parado'
    return jsonify({'status': 'parado'})

@app.route('/api/history')
def api_history():
    async def _get():
        return await get_history()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        h = loop.run_until_complete(_get())
        loop.close()
        return jsonify(h)
    except Exception:
        return jsonify({'trades': [], 'total_pnl': 0, 'wins': 0, 'losses': 0})

@app.route('/api/stats')
def api_stats():
    async def _get():
        return await get_stats()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        s = loop.run_until_complete(_get())
        loop.close()
        return jsonify(s)
    except Exception:
        return jsonify({'total_trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0, 'total_pnl': 0})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
