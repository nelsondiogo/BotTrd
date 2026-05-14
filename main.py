import os
import sys
import json
import time
import asyncio
import threading
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify

from exchange_management import ExchangeManager
from market_scanner import MarketScanner
from trading_engine import PositionTracker, OpportunityAnalyzer, RiskManager, SignalResult
from history_manager import add_trade, get_history, get_stats, save_bot_state, load_bot_state, get_recent_trades

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'hft-bot-secret-v9')

SETTINGS_FILE = 'settings.json'

INDEX_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HFT Scalping Bot</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',monospace;}
  body{background:#0b0e11;color:#e0e0e0;padding:20px;}
  .container{max-width:1400px;margin:0 auto;}
  h1{color:#00d4aa;margin-bottom:20px;font-size:1.8rem;}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:15px;margin-bottom:20px;}
  .card{background:#151a21;border:1px solid #232a33;border-radius:8px;padding:15px;}
  .card h3{color:#00d4aa;font-size:0.9rem;margin-bottom:10px;text-transform:uppercase;}
  .metric{font-size:1.6rem;font-weight:bold;color:#fff;}
  .metric.positive{color:#00d4aa;}
  .metric.negative{color:#ff4757;}
  .label{font-size:0.75rem;color:#8892a0;margin-top:4px;}
  .btn{background:#00d4aa;color:#0b0e11;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-weight:bold;margin-right:10px;margin-top:5px;}
  .btn.stop{background:#ff4757;color:#fff;}
  .btn.save{background:#3742fa;color:#fff;}
  .btn:disabled{opacity:0.5;cursor:not-allowed;}
  input, select{background:#0f1318;border:1px solid #232a33;color:#e0e0e0;padding:8px 12px;border-radius:4px;width:100%;margin-bottom:8px;font-size:0.85rem;}
  input:focus, select:focus{outline:none;border-color:#00d4aa;}
  .logs{height:300px;overflow-y:auto;background:#0f1318;border:1px solid #232a33;border-radius:6px;padding:10px;font-size:0.8rem;color:#a0aab5;line-height:1.4;}
  .log-entry{margin-bottom:2px;}
  .log-time{color:#5a6578;}
  .status-badge{display:inline-block;padding:4px 10px;border-radius:4px;font-size:0.75rem;font-weight:bold;}
  .status-running{background:#00d4aa;color:#0b0e11;}
  .status-stopped{background:#ff4757;color:#fff;}
  .status-circuit{background:#ffa502;color:#0b0e11;}
  table{width:100%;border-collapse:collapse;font-size:0.8rem;margin-top:10px;}
  th,td{text-align:left;padding:6px;border-bottom:1px solid #232a33;}
  th{color:#00d4aa;font-weight:600;}
  .pair-row:hover{background:#1a2029;}
  .config-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
  .toast{position:fixed;top:20px;right:20px;padding:12px 20px;border-radius:6px;color:#fff;font-weight:bold;z-index:1000;opacity:0;transition:opacity 0.3s;}
  .toast.show{opacity:1;}
  .toast.ok{background:#00d4aa;}
  .toast.err{background:#ff4757;}
</style>
</head>
<body>
<div class="container">
  <h1>⚡ HFT Scalping Bot</h1>

  <div style="margin-bottom:20px;">
    <span id="status-badge" class="status-badge status-stopped">PARADO</span>
    <span style="margin-left:15px;color:#8892a0;font-size:0.85rem;">Ambiente: <span id="api-env">-</span></span>
    <span style="margin-left:15px;color:#8892a0;font-size:0.85rem;">Latência: <span id="latency">-</span>ms</span>
  </div>

  <div class="grid">
    <div class="card" style="grid-column:span 2;">
      <h3>🔐 Configuração da API (Bybit)</h3>
      <div class="config-grid">
        <div>
          <label style="font-size:0.75rem;color:#8892a0;">API Key</label>
          <input type="text" id="cfg-api-key" placeholder="Cole sua API Key da Bybit">
        </div>
        <div>
          <label style="font-size:0.75rem;color:#8892a0;">API Secret</label>
          <input type="password" id="cfg-api-secret" placeholder="Cole sua API Secret da Bybit">
        </div>
        <div>
          <label style="font-size:0.75rem;color:#8892a0;">Ambiente</label>
          <select id="cfg-sandbox">
            <option value="true">Testnet (Sandbox)</option>
            <option value="false">Mainnet (Real)</option>
          </select>
        </div>
        <div>
          <label style="font-size:0.75rem;color:#8892a0;">Timeframe</label>
          <select id="cfg-timeframe">
            <option value="5m">M5 (Mais agressivo)</option>
            <option value="15m" selected>M15 (Padrão)</option>
            <option value="1h">H1 (Conservador)</option>
          </select>
        </div>
        <div>
          <label style="font-size:0.75rem;color:#8892a0;">Alavancagem Base</label>
          <input type="number" id="cfg-leverage" value="3" min="1" max="5">
        </div>
        <div>
          <label style="font-size:0.75rem;color:#8892a0;">Stop Loss (%)</label>
          <input type="number" id="cfg-sl" value="1.5" min="0.5" max="5" step="0.1">
        </div>
      </div>
      <button class="btn save" onclick="saveConfig()">💾 SALVAR CONFIGURAÇÃO</button>
      <button id="btn-start" class="btn" onclick="startBot()">▶️ INICIAR BOT</button>
      <button id="btn-stop" class="btn stop" onclick="stopBot()" disabled>⏹️ PARAR BOT</button>
      <button class="btn" onclick="closePosition()" style="background:#ffa502;" id="btn-close" disabled>🔒 FECHAR POSIÇÃO</button>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>Saldo Inicial</h3>
      <div class="metric" id="balance-inicial">-</div>
      <div class="label">USDT</div>
    </div>
    <div class="card">
      <h3>Saldo Atual</h3>
      <div class="metric" id="balance-atual">-</div>
      <div class="label">USDT</div>
    </div>
    <div class="card">
      <h3>PnL Realizado</h3>
      <div class="metric" id="pnl-realized">-</div>
      <div class="label">USDT</div>
    </div>
    <div class="card">
      <h3>PnL Não Realizado</h3>
      <div class="metric" id="pnl-unrealized">-</div>
      <div class="label">USDT</div>
    </div>
    <div class="card">
      <h3>PnL Total</h3>
      <div class="metric" id="pnl-total">-</div>
      <div class="label">USDT</div>
    </div>
    <div class="card">
      <h3>Posição Atual</h3>
      <div class="metric" id="position-info" style="font-size:1.1rem;">-</div>
      <div class="label" id="position-detail">-</div>
    </div>
  </div>

  <div class="grid">
    <div class="card" style="grid-column:span 2;">
      <h3>Top Oportunidades (Scan)</h3>
      <table>
        <thead><tr><th>Par</th><th>Lado</th><th>Score</th><th>Preço</th><th>ADX</th><th>RSI</th><th>MFI</th><th>Vol 24h</th></tr></thead>
        <tbody id="pairs-tbody"><tr><td colspan="8" style="text-align:center;color:#5a6578;">Aguardando scan...</td></tr></tbody>
      </table>
      <div class="label" style="margin-top:8px;">Último scan: <span id="last-scan">-</span> | Pares ativos: <span id="active-count">0</span></div>
    </div>
    <div class="card">
      <h3>Último Sinal</h3>
      <div class="metric" id="last-signal" style="font-size:1.1rem;">-</div>
      <div class="label" id="last-signal-detail">-</div>
    </div>
    <div class="card">
      <h3>Estatísticas</h3>
      <div style="font-size:0.85rem;color:#a0aab5;line-height:1.6;">
        <div>Trades: <span id="stat-trades">0</span></div>
        <div>Win Rate: <span id="stat-winrate">0</span>%</div>
        <div>Sequência: <span id="streak">-</span></div>
        <div>Perdas consecutivas: <span id="consecutive-losses">0</span>/3</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h3>Logs em Tempo Real</h3>
    <div class="logs" id="logs-box"><div class="log-entry">Aguardando inicialização. Configure a API e clique em INICIAR.</div></div>
  </div>
</div>

<div id="toast" class="toast"></div>

<script>
let polling = null;

function fmt(num, d=4) {
  return parseFloat(num || 0).toFixed(d);
}
function fmtPct(num) {
  let v = parseFloat(num || 0);
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}
function showToast(msg, ok=true) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + (ok ? 'ok' : 'err');
  setTimeout(() => t.className = 'toast', 3000);
}

async function fetchState() {
  try {
    const r = await fetch('/api/state');
    const s = await r.json();
    updateUI(s);
  } catch(e) {}
}

function updateUI(s) {
  const badge = document.getElementById('status-badge');
  badge.textContent = s.status || 'PARADO';
  badge.className = 'status-badge ' + (s.status === 'RODANDO' ? 'status-running' : s.status === 'CIRCUIT_BREAKER' ? 'status-circuit' : 'status-stopped');

  document.getElementById('api-env').textContent = s.api_environment || '-';
  document.getElementById('latency').textContent = s.scan_latency_ms || '0';
  document.getElementById('balance-inicial').textContent = fmt(s.session_start_balance, 4);
  document.getElementById('balance-atual').textContent = fmt(s.current_balance, 4);
  document.getElementById('pnl-realized').textContent = fmt(s.realized_pnl, 6);
  document.getElementById('pnl-unrealized').textContent = fmt(s.unrealized_pnl, 6);

  const total = (parseFloat(s.realized_pnl||0) + parseFloat(s.unrealized_pnl||0));
  const elTotal = document.getElementById('pnl-total');
  elTotal.textContent = fmt(total, 6);
  elTotal.className = 'metric ' + (total >= 0 ? 'positive' : 'negative');

  const pos = s.current_position;
  document.getElementById('position-info').textContent = pos && pos.symbol ? pos.side.toUpperCase() + ' ' + pos.symbol : 'NENHUMA';
  document.getElementById('position-detail').textContent = pos && pos.symbol ? 'Entry: ' + fmt(pos.entry, 6) + ' | Size: ' + fmt(pos.size, 4) + ' | PnL: ' + fmt(pos.unrealized_pnl, 6) + ' USDT' : '-';

  document.getElementById('last-signal').textContent = s.last_signal || '-';
  document.getElementById('last-signal-detail').textContent = 'Peak: ' + fmt(s.peak_pnl_pct, 2) + '% | Lock: ' + (s.lock_price ? fmt(s.lock_price, 6) : '-');
  document.getElementById('last-scan').textContent = s.last_scan || '-';
  document.getElementById('active-count').textContent = (s.active_pairs || []).length;
  document.getElementById('consecutive-losses').textContent = s.consecutive_losses || 0;

  const tbody = document.getElementById('pairs-tbody');
  const pairs = s.scan_results || [];
  if (pairs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#5a6578;">Nenhuma oportunidade</td></tr>';
  } else {
    tbody.innerHTML = pairs.map(p => `<tr class="pair-row">
      <td>${p.symbol}</td><td>${p.side.toUpperCase()}</td><td>${p.score.toFixed(3)}</td>
      <td>${fmt(p.price, 6)}</td><td>${p.adx}</td><td>${p.rsi}</td><td>${p.mfi || '-'}</td><td>${(p.volume_24h/1e6).toFixed(2)}M</td>
    </tr>`).join('');
  }

  const logs = s.logs || [];
  const logBox = document.getElementById('logs-box');
  if (logs.length > 0) {
    logBox.innerHTML = logs.slice(-100).map(l => {
      return '<div class="log-entry"><span class="log-time">' + l.substring(0,8) + '</span>' + l.substring(8) + '</div>';
    }).join('');
    logBox.scrollTop = logBox.scrollHeight;
  }

  document.getElementById('stat-trades').textContent = s.stats_total || 0;
  document.getElementById('stat-winrate').textContent = s.stats_winrate || 0;
  document.getElementById('streak').textContent = (s.stats_streak_type || '-') + ' ' + (s.stats_streak || 0);

  const running = s.status === 'RODANDO';
  document.getElementById('btn-start').disabled = running;
  document.getElementById('btn-stop').disabled = !running;
  document.getElementById('btn-close').disabled = !(pos && pos.symbol);
}

async function saveConfig() {
  const payload = {
    api_key: document.getElementById('cfg-api-key').value.trim(),
    api_secret: document.getElementById('cfg-api-secret').value.trim(),
    sandbox: document.getElementById('cfg-sandbox').value === 'true',
    timeframe: document.getElementById('cfg-timeframe').value,
    leverage: parseInt(document.getElementById('cfg-leverage').value),
    stop_loss_pct: parseFloat(document.getElementById('cfg-sl').value),
    trailing_stop_pct: 0.7,
    exchange: 'bybit',
    order_size_usdt: 0.9
  };
  if (!payload.api_key || !payload.api_secret) {
    showToast('Preencha API Key e Secret!', false);
    return;
  }
  const r = await fetch('/api/credentials', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });
  const j = await r.json();
  showToast(j.ok ? 'Configuração salva! Pode iniciar o bot.' : j.msg || 'Erro ao salvar', j.ok);
}

async function startBot() {
  const r = await fetch('/api/start', {method:'POST'});
  const j = await r.json();
  showToast(j.ok ? 'Bot iniciado!' : (j.msg || 'Erro'), j.ok);
  fetchState();
}
async function stopBot() {
  await fetch('/api/stop', {method:'POST'});
  showToast('Bot parado.');
  fetchState();
}
async function closePosition() {
  const r = await fetch('/api/close', {method:'POST'});
  const j = await r.json();
  showToast(j.ok ? 'Posição fechada!' : (j.msg || 'Erro'), j.ok);
  fetchState();
}

async function loadConfig() {
  try {
    const r = await fetch('/api/settings');
    const s = await r.json();
    if (s.api_key) document.getElementById('cfg-api-key').value = s.api_key;
    if (s.api_secret) document.getElementById('cfg-api-secret').value = s.api_secret;
    document.getElementById('cfg-sandbox').value = s.sandbox === false ? 'false' : 'true';
    if (s.timeframe) document.getElementById('cfg-timeframe').value = s.timeframe;
    if (s.leverage) document.getElementById('cfg-leverage').value = s.leverage;
    if (s.stop_loss_pct) document.getElementById('cfg-sl').value = s.stop_loss_pct;
  } catch(e) {}
}

polling = setInterval(fetchState, 1500);
fetchState();
loadConfig();
</script>
</body>
</html>
"""

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
            'opened_at': None,
            'consecutive_losses': 0,
            'circuit_breaker_triggered': False,
            'stats_total': 0,
            'stats_winrate': 0,
            'stats_streak': 0,
            'stats_streak_type': None,
        }
        self.ex_global = None
        self.tracker_global = None
        self.tasks = []

controller = BotController()

def load_settings():
    defaults = {
        'api_key': '',
        'api_secret': '',
        'trailing_stop_pct': 0.7,
        'stop_loss_pct': 1.5,
        'leverage': 3,
        'timeframe': '15m',
        'exchange': 'bybit',
        'sandbox': True,
        'order_size_usdt': 0.9
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                defaults.update(loaded)
        except Exception:
            pass
    return defaults

def save_settings(data):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def add_log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    controller.state['logs'].append(f"[{ts}] {msg}")
    if len(controller.state['logs']) > 400:
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
        total = safe_float(usdt.get('wallet'), 0.0)
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
            add_log(f"{reason} | {tracker.symbol} @ {price} | PnL: {unrealized:.5f}")
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
            return True
    except Exception as e:
        add_log(f"ERRO FECHAR {reason}: {e}")
    return False

async def scanner_task(ex, settings, tracker):
    scanner = MarketScanner(ex, settings)
    scanner_interval = 15
    last_balance = 0.0
    last_balance_time = 0
    while controller.running:
        start_time = time.time()
        try:
            now = time.time()
            if now - last_balance_time > 30 or last_balance <= 0:
                try:
                    bal = await ex.get_balance()
                    last_balance = get_total_balance(bal)
                    usdt = bal.get('USDT', {})
                    last_balance_time = now
                    add_log(f"BALANCE | total={last_balance:.5f} wallet={usdt.get('wallet',0):.5f} equity={usdt.get('equity',0):.5f}")
                except Exception as e:
                    add_log(f"BALANCE ERRO: {e}")
            total_bal = last_balance if last_balance > 0 else (tracker.session_start_balance or 1.0)
            tf_map = {'5m': '5', '15m': '15', '1h': '60'}
            tf = tf_map.get(settings.get('timeframe', '15m'), '15')
            res = await asyncio.wait_for(
                scanner.scan(balance=total_bal, top_n=7, timeframe=tf),
                timeout=20.0
            )
            latency = int((time.time() - start_time) * 1000)
            pairs = res.get('pairs', [])
            error = res.get('error')
            if error:
                add_log(f"SCAN ERRO: {error}")
            else:
                top_sym = pairs[0]['symbol'] if pairs else 'nenhuma'
                add_log(f"SCAN {latency}ms | {len(pairs)} ops | top: {top_sym}")
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
            if int(now) % 15 < 3:
                await save_bot_state({
                    'session_start_balance': controller.state.get('session_start_balance', 0),
                    'scan_results': pairs,
                    'last_scan': datetime.now().isoformat(),
                    'scan_latency_ms': latency,
                })
        except asyncio.TimeoutError:
            add_log("SCAN TIMEOUT | Scan demorou mais de 20s")
        except Exception as e:
            add_log(f"SCANNER TASK: {e}")
        elapsed = time.time() - start_time
        sleep_time = max(0.5, scanner_interval - elapsed)
        await asyncio.sleep(sleep_time)

async def monitor_task(ex, settings, tracker):
    sl_pct = safe_float(settings.get('stop_loss_pct'), 1.5)
    while controller.running:
        try:
            if not tracker.symbol:
                await asyncio.sleep(1)
                continue
            pos = await ex.get_position(tracker.symbol)
            if not pos or safe_float(pos.get('contracts'), 0) == 0:
                tracker.reset()
                _reset_position_state()
                await asyncio.sleep(1)
                continue
            current_price = safe_float(pos.get('markPrice'), 0)
            if current_price <= 0:
                await asyncio.sleep(1)
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
                pos_side = pos.get('side', tracker.side or 'long')
                if pos_side == 'long':
                    lock_price = tracker.entry_price * (1 + tracker.lock_profit_pct / 100)
                else:
                    lock_price = tracker.entry_price * (1 - tracker.lock_profit_pct / 100)
            session_start = safe_float(controller.state.get('session_start_balance'), 0)
            realized = safe_float(controller.state.get('realized_pnl'), 0)
            current_bal = session_start + realized + unrealized
            _update_bot_state(
                current_position={
                    'side': pos['side'], 'entry': pos['entryPrice'],
                    'size': pos['contracts'], 'unrealized_pnl': round(unrealized, 8),
                    'symbol': tracker.symbol, 'price': round(current_price, 8),
                },
                unrealized_pnl=round(unrealized, 8),
                current_balance=round(current_bal, 8),
                peak_pnl_pct=round(tracker.peak_profit_pct, 3) if tracker.peak_profit_pct > -900 else 0.0,
                lock_price=round(lock_price, 8) if lock_price else None,
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
                    add_log(f"ERRO FECHAR SL: {e}")
                await asyncio.sleep(2)
                continue
            should_close, reason = tracker.check_trailing_stop(current_price)
            if should_close:
                add_log(f"TRAIL_TRIGGER | {tracker.symbol} | {reason} | price:{current_price} entry:{tracker.entry_price} peak:{tracker.peak_profit_pct:.3f}%")
                try:
                    await ex.close_position(tracker.symbol, tracker.side, tracker.size)
                    add_log(f"{reason} | {tracker.symbol} @ {current_price} | PnL: {unrealized:.5f}")
                    await add_trade(tracker.symbol, tracker.side, tracker.entry_price, current_price, unrealized, reason, tracker.leverage)
                    if unrealized < 0:
                        controller.state['consecutive_losses'] += 1
                    else:
                        controller.state['consecutive_losses'] = 0
                    _update_bot_state(realized_pnl=round(realized + unrealized, 8))
                    _reset_position_state()
                    tracker.reset()
                except Exception as e:
                    add_log(f"ERRO FECHAR TRAIL: {e}")
                await asyncio.sleep(2)
                continue
            total_pnl = realized + unrealized
            controller.state['pnl_history'].append({
                'time': datetime.now().strftime('%H:%M:%S'),
                'pnl': round(total_pnl, 8)
            })
            if len(controller.state['pnl_history']) > 600:
                controller.state['pnl_history'].pop(0)
            await asyncio.sleep(1)
        except Exception as e:
            add_log(f"MONITOR TASK: {e}")
            await asyncio.sleep(3)

async def executor_task(ex, settings, tracker):
    risk_mgr = RiskManager(base_leverage=int(settings.get('leverage', 3)))
    opp_analyzer = OpportunityAnalyzer(rotation_threshold=1.20)
    order_size_usdt = safe_float(settings.get('order_size_usdt'), 0.9)
    max_consecutive_losses = 3
    while controller.running:
        try:
            await asyncio.sleep(3)
            if controller.state['consecutive_losses'] >= max_consecutive_losses:
                if not controller.state['circuit_breaker_triggered']:
                    add_log(f"CIRCUIT BREAKER | {controller.state['consecutive_losses']} perdas consecutivas. Bot pausado.")
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
                score=best.get('score', 0), price=best.get('price', 0), meta=best,
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
                    add_log("STOP GLOBAL | Saldo < 90% capital inicial")
                    controller.state['status'] = 'STOP_GLOBAL'
                    controller.running = False
                    continue
                sym = best_signal.symbol
                price = best_signal.price
                recent_trades = await get_recent_trades(5)
                recent_losses = sum(1 for t in recent_trades if t.get('net_pnl', 0) < 0)
                if recent_losses >= 2 and any(t.get('symbol') == sym for t in recent_trades[-2:]):
                    add_log(f"BLOQUEIO | Par {sym} em sequência perdedora")
                    continue
                adx = best_signal.meta.get('adx', 25)
                lev = risk_mgr.dynamic_leverage(adx, int(settings.get('leverage', 3)))
                lev = min(lev, 5)
                try:
                    await ex.set_leverage(sym, lev)
                except Exception as e:
                    add_log(f"Leverage: {e}")
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
                    await ex.create_market_order(sym, side_order, qty)
                    add_log(f"ENTRADA {best_signal.side.upper()} {sym} @ {price} | Score:{best_signal.score:.2f} ADX:{adx:.1f} LEV:{lev}x Conf:{best_signal.confidence}")
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
                    add_log(f"ERRO ABERTURA: {e}")
                continue
            if tracker.symbol and best_signal.symbol and best_signal.symbol != tracker.symbol:
                unrealized = safe_float(current_pos.get('unrealized_pnl'), 0) if current_pos else 0
                current_price = safe_float(current_pos.get('price'), 0) if current_pos else 0
                if opp_analyzer.should_rotate(tracker, best_signal, unrealized, current_price):
                    add_log(f"ROTACAO | Fechando {tracker.symbol} -> {best_signal.symbol} | Score novo: {best_signal.score:.2f}")
                    try:
                        await ex.close_position(tracker.symbol, tracker.side, tracker.size)
                        await add_trade(tracker.symbol, tracker.side, tracker.entry_price, current_price, unrealized, 'ROTACAO', tracker.leverage)
                        if unrealized < 0:
                            controller.state['consecutive_losses'] += 1
                        else:
                            controller.state['consecutive_losses'] = 0
                        _update_bot_state(realized_pnl=round(safe_float(controller.state.get('realized_pnl'), 0) + unrealized, 8))
                        _reset_position_state()
                        tracker.reset()
                        await asyncio.sleep(2)
                    except Exception as e:
                        add_log(f"ERRO ROTACAO: {e}")
        except Exception as e:
            add_log(f"EXECUTOR TASK: {e}")

async def health_check_task(ex):
    while controller.running:
        try:
            await asyncio.sleep(60)
            await ex.fetch_ticker('BTCUSDT:USDT')
        except Exception:
            pass

async def stats_refresh_task():
    while controller.running:
        try:
            await asyncio.sleep(10)
            stats = await get_stats()
            controller.state.update({
                'stats_total': stats.get('total_trades', 0),
                'stats_winrate': stats.get('win_rate', 0),
                'stats_streak': stats.get('current_streak', 0),
                'stats_streak_type': stats.get('streak_type', None),
            })
        except Exception:
            pass

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/api/state')
def api_state():
    return jsonify(controller.state)

@app.route('/api/credentials', methods=['POST'])
def api_credentials():
    data = request.get_json(force=True)
    if not data.get('api_key') or not data.get('api_secret'):
        return jsonify({'ok': False, 'msg': 'API Key e Secret são obrigatórios'})
    settings = load_settings()
    settings['api_key'] = data.get('api_key', '').strip()
    settings['api_secret'] = data.get('api_secret', '').strip()
    settings['sandbox'] = data.get('sandbox', True)
    settings['timeframe'] = data.get('timeframe', '15m')
    settings['leverage'] = int(data.get('leverage', 3))
    settings['stop_loss_pct'] = float(data.get('stop_loss_pct', 1.5))
    settings['trailing_stop_pct'] = float(data.get('trailing_stop_pct', 0.7))
    settings['exchange'] = data.get('exchange', 'bybit')
    settings['order_size_usdt'] = float(data.get('order_size_usdt', 0.9))
    save_settings(settings)
    add_log("CONFIG | Credenciais e parâmetros salvos via Dashboard")
    return jsonify({'ok': True, 'msg': 'Configuração salva com sucesso'})

@app.route('/api/start', methods=['POST'])
def api_start():
    if controller.running:
        return jsonify({'ok': False, 'msg': 'Já está rodando'})
    settings = load_settings()
    if not settings.get('api_key') or not settings.get('api_secret'):
        return jsonify({'ok': False, 'msg': 'Configure API Key e Secret no Dashboard primeiro'})
    ex = ExchangeManager(
        api_key=settings['api_key'],
        api_secret=settings['api_secret'],
        sandbox=settings.get('sandbox', True)
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async def _start():
        valid, msg, env = await ex.validate_credentials()
        controller.state['api_valid'] = valid
        controller.state['api_message'] = msg
        controller.state['api_environment'] = env
        add_log(f"API | {msg} | Env: {env}")
        if not valid:
            return False
        bal = await ex.get_balance()
        total = get_total_balance(bal)
        if total <= 0:
            add_log("ERRO: Saldo zero ou API sem permissão")
            return False
        controller.state['session_start_balance'] = round(total, 8)
        controller.state['current_balance'] = round(total, 8)
        controller.state['status'] = 'RODANDO'
        controller.state['consecutive_losses'] = 0
        controller.state['circuit_breaker_triggered'] = False
        controller.running = True
        controller.ex_global = ex
        controller.tracker_global = PositionTracker()
        controller.tracker_global.session_start_balance = total
        controller.tasks = [
            asyncio.create_task(scanner_task(ex, settings, controller.tracker_global)),
            asyncio.create_task(monitor_task(ex, settings, controller.tracker_global)),
            asyncio.create_task(executor_task(ex, settings, controller.tracker_global)),
            asyncio.create_task(health_check_task(ex)),
            asyncio.create_task(stats_refresh_task()),
        ]
        return True
    try:
        ok = loop.run_until_complete(_start())
        if ok:
            threading.Thread(target=_run_loop, args=(loop,), daemon=True).start()
            return jsonify({'ok': True})
        else:
            return jsonify({'ok': False, 'msg': 'Falha na inicialização. Verifique logs.'})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

def _run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

@app.route('/api/stop', methods=['POST'])
def api_stop():
    controller.running = False
    controller.state['status'] = 'parado'
    add_log("BOT PARADO pelo usuário")
    if controller.ex_global:
        try:
            asyncio.run(controller.ex_global.close())
        except Exception:
            pass
    return jsonify({'ok': True})

@app.route('/api/close', methods=['POST'])
def api_close():
    if not controller.ex_global or not controller.tracker_global:
        return jsonify({'ok': False, 'msg': 'Bot não inicializado'})
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        ok = loop.run_until_complete(_close_and_record(controller.ex_global, controller.tracker_global, 'MANUAL'))
        return jsonify({'ok': ok})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        return jsonify(load_settings())
    data = request.get_json(force=True)
    save_settings(data)
    return jsonify({'ok': True})

@app.route('/api/history')
def api_history():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        h = loop.run_until_complete(get_history(100))
        return jsonify(h)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/stats')
def api_stats():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        s = loop.run_until_complete(get_stats())
        return jsonify(s)
    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
