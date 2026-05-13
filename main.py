import os
import json
import time
import asyncio
import threading
from datetime import datetime
from flask import Flask, request, jsonify

from exchange_management import ExchangeManager
from market_scanner import MarketScanner
from trading_engine import PositionTracker, OpportunityAnalyzer, RiskManager, SignalResult
from history_manager import add_trade, get_history, get_stats, save_bot_state, load_bot_state, get_recent_trades

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nd-bot-hft-secret')

SETTINGS_FILE = 'settings.json'

INDEX_HTML = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>nd-bot HFT v9.0</title>
<style>
  :root{--bg:#07090f;--surface:#12141c;--elevated:#1a1d28;--border:#1f2230;--accent:#00d084;--danger:#ff4757;--gold:#ffd600;--text:#f0f2f5;--muted:#555b75;}
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent;margin:0;padding:0;}
  html,body{height:100%;margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);}
  #app{max-width:480px;margin:0 auto;height:100%;display:flex;flex-direction:column;position:relative;}

  /* Header */
  .header-premium{display:flex;justify-content:space-between;align-items:center;padding:14px 14px 8px;gap:8px;}
  .balance-cards{display:flex;gap:8px;flex:1;min-width:0;}
  .bal-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:8px 10px;flex:1;min-width:0;text-align:center;}
  .bal-card .lbl{font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;font-weight:700;}
  .bal-card .val{font-size:.82rem;font-weight:800;color:var(--accent);margin-top:2px;font-variant-numeric:tabular-nums;}
  .brand-right{font-size:.8rem;font-weight:800;letter-spacing:-.2px;color:var(--text);text-shadow:0 0 10px rgba(0,208,132,0.2);white-space:nowrap;}
  .brand-right span{color:var(--accent);}

  main{flex:1;overflow-y:auto;padding:0 12px 80px;}

  /* Cards */
  .card{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:14px;margin-bottom:10px;position:relative;overflow:hidden;}
  .card::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;}
  .card.up::before{background:var(--accent);}.card.down::before{background:var(--danger);}.card.neutral::before{background:var(--muted);}
  .label{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.7px;font-weight:700;}
  .value{font-size:1.25rem;font-weight:800;margin-top:4px;font-variant-numeric:tabular-nums;}
  .positive{color:var(--accent);}.negative{color:var(--danger);}

  /* Position Control Card */
  .position-control{background:linear-gradient(145deg,#11131c 0%,#1a1d28 100%);border-color:rgba(0,208,132,0.08);padding:16px;}
  .pos-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;}
  .pos-title{font-size:1.1rem;font-weight:800;}
  .pos-badge{font-size:.7rem;padding:4px 10px;border-radius:6px;font-weight:700;}
  .pos-badge.long{background:rgba(0,208,132,0.15);color:var(--accent);}
  .pos-badge.short{background:rgba(255,71,87,0.15);color:var(--danger);}
  .pos-badge.waiting{background:rgba(85,91,117,0.15);color:var(--muted);}
  .pos-profit{font-size:1.6rem;font-weight:900;margin:8px 0;font-variant-numeric:tabular-nums;}
  .pos-details{display:flex;justify-content:space-between;font-size:.72rem;color:var(--muted);margin-top:8px;}
  .pos-detail{text-align:center;flex:1;}
  .pos-detail .num{font-size:.9rem;font-weight:700;color:var(--text);margin-top:2px;}

  /* Chart Canvas */
  .chart-wrap{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:12px;margin-bottom:10px;position:relative;}
  .chart-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}
  .chart-symbol{font-size:.85rem;font-weight:700;}
  .chart-timeframe{font-size:.65rem;color:var(--muted);background:var(--elevated);padding:2px 8px;border-radius:4px;}
  .chart-canvas{width:100%;height:200px;border-radius:10px;background:#0a0c14;}
  .chart-legend{display:flex;justify-content:center;gap:16px;margin-top:8px;font-size:.65rem;color:var(--muted);}
  .chart-legend span{display:flex;align-items:center;gap:4px;}
  .legend-dot{width:8px;height:8px;border-radius:50%;display:inline-block;}
  .legend-dot.entry{background:var(--gold);}
  .legend-dot.current{background:var(--accent);}
  .legend-dot.stop{background:var(--danger);}

  /* Grid Stats */
  .stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}

  /* Logs */
  .logs{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:12px;height:160px;overflow-y:auto;font-family:'SF Mono',monospace;font-size:.7rem;line-height:1.5;color:#6b7280;}
  .logs div{padding:2px 0;}

  /* Bottom Nav */
  .bottom-nav{position:fixed;bottom:0;left:0;right:0;height:60px;background:rgba(7,9,15,.93);backdrop-filter:blur(16px);border-top:1px solid var(--border);display:flex;justify-content:space-around;align-items:center;z-index:40;padding-bottom:env(safe-area-inset-bottom);}
  .nav-btn{background:none;border:none;color:var(--muted);font-size:.58rem;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;width:48px;padding:4px 0;}
  .nav-btn svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}
  .nav-btn.active{color:var(--accent);}

  .hidden{display:none !important;}
  .spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;margin-right:6px;vertical-align:middle;}
  @keyframes spin{to{transform:rotate(360deg);}}

  /* Form */
  .form-group{margin-bottom:14px;}
  label{display:block;font-size:.78rem;color:var(--muted);margin-bottom:6px;font-weight:600;}
  input,select{width:100%;background:#07090f;border:1px solid var(--border);color:var(--text);padding:12px;border-radius:10px;font-size:.95rem;}
  input:focus,select:focus{outline:none;border-color:var(--accent);}
  .btn{width:100%;padding:14px;border:none;border-radius:12px;font-weight:800;font-size:.95rem;cursor:pointer;}
  .btn-save{background:var(--accent);color:#000;}
  .btn-validate{background:var(--elevated);color:var(--text);border:1px solid var(--border);margin-top:8px;}
  .btn-action{width:100%;padding:14px;border:none;border-radius:14px;font-weight:900;font-size:1rem;cursor:pointer;margin-top:10px;transition:all .2s;}
  .btn-action.start{background:var(--accent);color:#000;box-shadow:0 4px 20px rgba(0,208,132,0.22);}
  .btn-action.stop{background:var(--danger);color:#fff;box-shadow:0 4px 20px rgba(255,71,87,0.22);}
  .btn-action:disabled{opacity:.6;transform:scale(.98);}

  /* Pairs list */
  .pair-item{display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid var(--border);}
  .pair-item:last-child{border:none;}
  .pair-info{flex:1;min-width:0;}
  .pair-name{font-weight:700;font-size:.85rem;}
  .pair-meta{font-size:.72rem;color:var(--muted);font-variant-numeric:tabular-nums;}
  .pair-score{font-size:.78rem;font-weight:700;min-width:56px;text-align:right;}
  .pair-side{font-size:.65rem;padding:2px 6px;border-radius:4px;font-weight:700;margin-right:6px;}
  .side-long{background:rgba(0,208,132,0.15);color:var(--accent);}
  .side-short{background:rgba(255,71,87,0.15);color:var(--danger);}

  /* Toast */
  .debug-toast{position:fixed;top:10px;left:10px;right:10px;background:var(--danger);color:#fff;padding:10px 14px;border-radius:10px;font-size:.75rem;z-index:100;display:none;word-break:break-word;}
</style>
</head>
<body>
<div id="debugToast" class="debug-toast"></div>
<div id="app">
  <div class="header-premium">
    <div class="balance-cards">
      <div class="bal-card"><div class="lbl">Inicial</div><div class="val" id="hdrInitial">-</div></div>
      <div class="bal-card"><div class="lbl">Atual</div><div class="val" id="hdrCurrent">-</div></div>
    </div>
    <div class="brand-right"><span>nd</span>-bot <span style="font-size:.6rem;color:var(--muted);">v9.0 HFT</span></div>
  </div>

  <main>
    <!-- DASHBOARD -->
    <section id="view-dashboard">
      <!-- Posição / Controle -->
      <div id="posControl" class="card position-control">
        <div class="pos-header">
          <div>
            <div class="pos-title" id="posSymbol">Aguardando sinal...</div>
            <div style="font-size:.7rem;color:var(--muted);margin-top:2px;" id="posSideText">-</div>
          </div>
          <span class="pos-badge waiting" id="posBadge">AGUARDANDO</span>
        </div>
        <div class="pos-profit" id="posProfit">+0,00000</div>
        <div style="display:flex;justify-content:space-between;font-size:.7rem;color:var(--muted);">
          <span>Entrada: <b id="posEntry" style="color:var(--gold);">-</b></span>
          <span>Atual: <b id="posCurrent">-</b></span>
          <span>Peak: <b id="posPeak">-</b></span>
        </div>
        <div class="pos-details">
          <div class="pos-detail"><div>Alav.</div><div class="num" id="posLev">-</div></div>
          <div class="pos-detail"><div>Tamanho</div><div class="num" id="posSize">-</div></div>
          <div class="pos-detail"><div>Lock</div><div class="num" id="posLock" style="color:var(--gold);">-</div></div>
        </div>
      </div>

      <!-- Gráfico Canvas -->
      <div class="chart-wrap">
        <div class="chart-header">
          <span class="chart-symbol" id="chartSymbol">BTCUSDT</span>
          <span class="chart-timeframe" id="chartTf">M15</span>
        </div>
        <canvas id="tradeChart" class="chart-canvas" width="400" height="200"></canvas>
        <div class="chart-legend">
          <span><span class="legend-dot entry"></span> Entrada</span>
          <span><span class="legend-dot current"></span> Preço</span>
          <span><span class="legend-dot stop"></span> Stop</span>
        </div>
      </div>

      <!-- Stats Grid -->
      <div class="stats-grid">
        <div class="card neutral"><div class="label">Status</div><div class="value" id="txtStatus">PARADO</div></div>
        <div class="card neutral"><div class="label">PnL Realizado</div><div class="value" id="txtReal">-</div></div>
        <div class="card neutral"><div class="label">Ultimo Sinal</div><div class="value" style="font-size:1.05rem" id="txtSignalDash">-</div></div>
        <div class="card neutral"><div class="label">Latencia</div><div class="value" style="font-size:1.05rem" id="txtLatency">-</div></div>
      </div>

      <!-- Logs -->
      <div style="margin-top:10px;">
        <div class="label" style="margin:0 0 8px 4px;">Logs</div>
        <div class="logs" id="logBox"></div>
      </div>
    </section>

    <!-- MERCADO -->
    <section id="view-market" class="hidden">
      <div class="card neutral">
        <div class="label" style="margin-bottom:12px;">Pares (<span id="pairCount">-</span>) | Scan: <span id="marketScan">-</span> | <span id="marketLatency">-</span></div>
        <div id="pairList"><div class="pair-item"><span class="pair-meta">Aguardando scan...</span></div></div>
      </div>
    </section>

    <!-- GRÁFICO TV -->
    <section id="view-chart" class="hidden">
      <div class="card neutral" style="padding:12px;">
        <div class="label" style="margin-bottom:10px;">TradingView</div>
        <div style="height:260px;border-radius:14px;overflow:hidden;border:1px solid var(--border);background:#000;">
          <iframe id="tvFrame" src="https://www.tradingview.com/widgetembed/?frameElementId=tvFrame&symbol=BYBIT:BTCUSDT.P&interval=15&theme=dark&style=1&locale=pt&hide_top_toolbar=false&hide_legend=false&allow_symbol_change=true&save_image=false&details=true&studies=[]" style="width:100%;height:100%;border:none;"></iframe>
        </div>
      </div>
    </section>

    <!-- HISTÓRICO -->
    <section id="view-history" class="hidden">
      <div class="card neutral" style="margin-bottom:10px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div><div class="label">Lucro Total</div><div class="value" id="histTotal">-</div></div>
          <div style="text-align:right;"><div class="label">Win Rate</div><div class="value" id="histWinRate">-</div></div>
        </div>
      </div>
      <div class="card neutral">
        <div class="label" style="margin-bottom:12px;">Trades (<span id="histCount">-</span>)</div>
        <div id="histList"><div class="pair-item"><span class="pair-meta">Nenhum trade.</span></div></div>
      </div>
    </section>

    <!-- CONFIG -->
    <section id="view-config" class="hidden">
      <div class="card neutral">
        <h3 style="margin-top:0;font-size:1rem;">Ajustes</h3>
        <div class="form-group">
          <label>Exchange</label>
          <select id="fExchange"><option value="bybit">Bybit</option></select>
        </div>
        <div class="form-group"><label>API Key</label><input type="password" id="fApiKey" placeholder="API Key"></div>
        <div class="form-group"><label>API Secret</label><input type="password" id="fApiSecret" placeholder="API Secret"></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div class="form-group"><label>SL Hard (%)</label><input type="number" step="0.1" id="fStopLoss" value="1.5"></div>
          <div class="form-group"><label>Alav. Base (x)</label><input type="number" id="fLeverage" value="3"></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div class="form-group"><label>Ordem ($)</label><input type="number" id="fSize" value="0.9"></div>
          <div class="form-group"><label>Timeframe</label>
            <select id="fTimeframe"><option value="5m">5m</option><option value="15m" selected>15m</option><option value="1h">1h</option></select>
          </div>
        </div>
        <div class="form-group">
          <label style="display:flex;align-items:center;gap:10px;cursor:pointer;padding:4px 0;">
            <input type="checkbox" id="fSandbox" checked style="width:18px;height:18px;"> <span>Testnet</span>
          </label>
        </div>
        <button class="btn btn-save" onclick="saveConfig()">SALVAR</button>
        <button class="btn btn-validate" onclick="validateApi()">VALIDAR API</button>
        <div id="valResult" style="margin-top:10px;font-size:.8rem;"></div>
        <div style="margin-top:18px;border-top:1px solid var(--border);padding-top:14px;">
          <div class="label" style="margin-bottom:10px;">Controle</div>
          <button id="ctrlBtn" class="btn-action start" onclick="toggleBot()">INICIAR</button>
        </div>
      </div>
    </section>
  </main>

  <nav class="bottom-nav">
    <button class="nav-btn active" onclick="switchTab('dashboard', this)"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>Dashboard</button>
    <button class="nav-btn" onclick="switchTab('market', this)"><svg viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>Mercado</button>
    <button class="nav-btn" onclick="switchTab('chart', this)"><svg viewBox="0 0 24 24"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg>Grafico</button>
    <button class="nav-btn" onclick="switchTab('history', this)"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>Historico</button>
    <button class="nav-btn" onclick="switchTab('config', this)"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>Ajustes</button>
  </nav>
</div>

<script>
  let isRunning=false;
  let priceHistory=[];
  let entryPrice=0;
  let posSide='';
  let slPrice=0;

  function showDebug(msg){
    const el=document.getElementById('debugToast');
    el.innerText=msg; el.style.display='block';
    setTimeout(()=>{el.style.display='none';},8000);
  }

  function fmtMoney(v){
    v=parseFloat(v)||0;
    if(Math.abs(v)>=1000) return v.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
    if(Math.abs(v)>=1) return v.toLocaleString('pt-BR',{minimumFractionDigits:3,maximumFractionDigits:5});
    return v.toLocaleString('pt-BR',{minimumFractionDigits:5,maximumFractionDigits:5});
  }
  function fmt5(v){return(v>=0?'+':'')+(parseFloat(v)||0).toLocaleString('pt-BR',{minimumFractionDigits:5,maximumFractionDigits:5});}
  function fmt2(v){return(parseFloat(v)||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});}

  function switchTab(tab,btn){
    document.querySelectorAll('main>section').forEach(s=>s.classList.add('hidden'));
    document.getElementById('view-'+tab).classList.remove('hidden');
    document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
    if(btn&&btn.classList.contains('nav-btn'))btn.classList.add('active');
    if(tab==='chart')updateTradingView();
    if(tab==='history')loadHistory();
    if(tab==='market')loadMarket();
  }

  function updateTradingView(){
    const sym=window.lastChartSymbol||'BTCUSDT.P';
    document.getElementById('tvFrame').src='https://www.tradingview.com/widgetembed/?frameElementId=tvFrame&symbol=BYBIT:'+sym+'&interval=15&theme=dark&style=1&locale=pt&hide_top_toolbar=false&hide_legend=false&allow_symbol_change=true&save_image=false&details=true&studies=[]';
  }

  // =============================================================================
  // CANVAS CHART - Desenha evolucao da posicao com linha de entrada
  // =============================================================================
  function drawTradeChart(){
    const canvas=document.getElementById('tradeChart');
    const ctx=canvas.getContext('2d');
    const W=canvas.width, H=canvas.height;
    const pad=30;

    // Fundo
    ctx.fillStyle='#0a0c14';
    ctx.fillRect(0,0,W,H);

    if(priceHistory.length<2){
      ctx.fillStyle='#555b75';
      ctx.font='12px sans-serif';
      ctx.textAlign='center';
      ctx.fillText('Aguardando dados da posicao...', W/2, H/2);
      return;
    }

    const prices=priceHistory.map(p=>p.p);
    const minP=Math.min(...prices, entryPrice||Infinity, slPrice||Infinity);
    const maxP=Math.max(...prices, entryPrice||-Infinity, slPrice||-Infinity);
    const range=maxP-minP||1;

    function y(p){ return H-pad-((p-minP)/range)*(H-pad*2); }
    function x(i){ return pad+(i/(prices.length-1))*(W-pad*2); }

    // Grid
    ctx.strokeStyle='#1f2230';
    ctx.lineWidth=0.5;
    for(let i=0;i<5;i++){
      const gy=pad+(i/4)*(H-pad*2);
      ctx.beginPath(); ctx.moveTo(pad,gy); ctx.lineTo(W-pad,gy); ctx.stroke();
    }

    // Linha de preço
    ctx.strokeStyle='#00d084';
    ctx.lineWidth=2;
    ctx.beginPath();
    prices.forEach((p,i)=>{
      if(i===0) ctx.moveTo(x(i),y(p));
      else ctx.lineTo(x(i),y(p));
    });
    ctx.stroke();

    // Area sob a linha
    ctx.fillStyle='rgba(0,208,132,0.08)';
    ctx.beginPath();
    ctx.moveTo(x(0),y(prices[0]));
    prices.forEach((p,i)=>ctx.lineTo(x(i),y(p)));
    ctx.lineTo(x(prices.length-1),H-pad);
    ctx.lineTo(x(0),H-pad);
    ctx.closePath();
    ctx.fill();

    // Linha de ENTRADA (dourada)
    if(entryPrice>0){
      const ey=y(entryPrice);
      ctx.strokeStyle='#ffd600';
      ctx.lineWidth=1.5;
      ctx.setLineDash([6,4]);
      ctx.beginPath(); ctx.moveTo(pad,ey); ctx.lineTo(W-pad,ey); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle='#ffd600';
      ctx.font='bold 10px sans-serif';
      ctx.textAlign='right';
      ctx.fillText('ENTRADA '+fmtMoney(entryPrice), W-pad-4, ey-4);
    }

    // Linha de STOP (vermelha)
    if(slPrice>0){
      const sy=y(slPrice);
      ctx.strokeStyle='#ff4757';
      ctx.lineWidth=1.5;
      ctx.setLineDash([4,4]);
      ctx.beginPath(); ctx.moveTo(pad,sy); ctx.lineTo(W-pad,sy); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle='#ff4757';
      ctx.font='bold 10px sans-serif';
      ctx.textAlign='right';
      ctx.fillText('STOP '+fmtMoney(slPrice), W-pad-4, sy-4);
    }

    // Ponto atual (piscante)
    const lastIdx=prices.length-1;
    const lastPrice=prices[lastIdx];
    const lx=x(lastIdx), ly=y(lastPrice);

    // Circulo externo
    ctx.beginPath();
    ctx.arc(lx,ly,8,0,Math.PI*2);
    ctx.fillStyle='rgba(0,208,132,0.2)';
    ctx.fill();

    // Circulo interno
    ctx.beginPath();
    ctx.arc(lx,ly,4,0,Math.PI*2);
    ctx.fillStyle='#00d084';
    ctx.fill();

    // Label do preço atual
    ctx.fillStyle='#fff';
    ctx.font='bold 11px sans-serif';
    ctx.textAlign='left';
    ctx.fillText(fmtMoney(lastPrice), lx+12, ly+4);

    // Seta de direcao
    if(posSide){
      ctx.font='bold 14px sans-serif';
      ctx.textAlign='center';
      if(posSide==='long'){
        ctx.fillStyle='#00d084';
        ctx.fillText('▲ LONG', W/2, 18);
      }else{
        ctx.fillStyle='#ff4757';
        ctx.fillText('▼ SHORT', W/2, 18);
      }
    }
  }

  async function toggleBot(){
    const btn=document.getElementById('ctrlBtn');
    btn.disabled=true;
    if(!isRunning){
      btn.innerHTML='<span class="spinner"></span>INICIANDO...';
      btn.className='btn-action start';
      try{
        const r=await fetch('/api/bot/start',{method:'POST'});
        if(!r.ok) throw new Error('HTTP '+r.status);
        const j=await r.json();
        if(j.status==='erro_api'||j.status==='erro'){
          alert(j.message||'Erro ao iniciar.');
          btn.innerText='INICIAR';btn.className='btn-action start';isRunning=false;
        }else{
          btn.innerText='PARAR';btn.className='btn-action stop';isRunning=true;
          switchTab('dashboard',document.querySelector('.nav-btn'));
        }
      }catch(e){
        showDebug('ERRO REDE: '+e.message);
        btn.innerText='INICIAR';btn.className='btn-action start';isRunning=false;
      }
    }else{
      btn.innerHTML='<span class="spinner"></span>PARANDO...';
      btn.className='btn-action stop';
      try{
        const r=await fetch('/api/bot/stop',{method:'POST'});
        if(!r.ok) throw new Error('HTTP '+r.status);
        await r.json();
        btn.innerText='INICIAR';btn.className='btn-action start';isRunning=false;
        priceHistory=[]; entryPrice=0; posSide=''; slPrice=0;
        drawTradeChart();
      }catch(e){
        showDebug('ERRO REDE: '+e.message);
        btn.innerText='PARAR';btn.className='btn-action stop';isRunning=true;
      }
    }
    btn.disabled=false;
  }

  async function saveConfig(){
    const payload={
      api_key:document.getElementById('fApiKey').value.trim(),
      api_secret:document.getElementById('fApiSecret').value.trim(),
      stop_loss_pct:parseFloat(document.getElementById('fStopLoss').value),
      leverage:parseInt(document.getElementById('fLeverage').value),
      timeframe:document.getElementById('fTimeframe').value,
      exchange:document.getElementById('fExchange').value,
      order_size_usdt:parseFloat(document.getElementById('fSize').value),
      sandbox:document.getElementById('fSandbox').checked
    };
    try{
      const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if(!r.ok) throw new Error('HTTP '+r.status);
      const j=await r.json();
      alert(j.status==='saved'?'Salvo!':'Erro.');
    }catch(e){ showDebug('ERRO: '+e.message); }
  }

  async function validateApi(){
    try{
      const r=await fetch('/api/validate',{method:'POST'});
      if(!r.ok) throw new Error('HTTP '+r.status);
      const j=await r.json();
      const el=document.getElementById('valResult');
      if(j.valid){el.innerText='✅ '+j.message;el.style.color='var(--accent)';}
      else{el.innerText='❌ '+j.message;el.style.color='var(--danger)';}
    }catch(e){ showDebug('ERRO: '+e.message); }
  }

  async function loadConfig(){
    try{
      const r=await fetch('/api/settings');
      if(!r.ok) throw new Error('HTTP '+r.status);
      const c=await r.json();
      document.getElementById('fApiKey').value=c.api_key||'';
      document.getElementById('fApiSecret').value=c.api_secret||'';
      document.getElementById('fStopLoss').value=c.stop_loss_pct??1.5;
      document.getElementById('fLeverage').value=c.leverage??3;
      document.getElementById('fTimeframe').value=c.timeframe||'15m';
      document.getElementById('fExchange').value=c.exchange||'bybit';
      document.getElementById('fSize').value=c.order_size_usdt??0.9;
      document.getElementById('fSandbox').checked=c.sandbox??true;
    }catch(e){ showDebug('ERRO config: '+e.message); }
  }

  async function loadMarket(){
    try{
      const r=await fetch('/api/state');
      if(!r.ok) throw new Error('HTTP '+r.status);
      const s=await r.json();
      document.getElementById('pairCount').innerText=s.active_pairs?s.active_pairs.length:'-';
      document.getElementById('marketScan').innerText=s.last_scan||'-';
      const lat=s.scan_latency_ms||0;
      document.getElementById('marketLatency').innerText=lat+'ms';
      const list=document.getElementById('pairList');
      if(!s.scan_results||s.scan_results.length===0){
        list.innerHTML='<div class="pair-item"><span class="pair-meta">Aguardando scan...</span></div>';
        return;
      }
      list.innerHTML=s.scan_results.map(p=>`<div class="pair-item"><div class="pair-info"><div class="pair-name"><span class="pair-side ${p.side==='long'?'side-long':'side-short'}">${p.side.toUpperCase()}</span>${p.symbol}</div><div class="pair-meta">ADX:${p.adx} RSI:${p.rsi} MFI:${p.mfi||'-'} H1:${p.trend_h1}</div></div><div class="pair-score ${p.side==='long'?'positive':'negative'}">${(p.score*100).toFixed(0)}%</div></div>`).join('');
    }catch(e){ showDebug('ERRO mercado: '+e.message); }
  }

  async function loadHistory(){
    try{
      const r=await fetch('/api/history');
      if(!r.ok) throw new Error('HTTP '+r.status);
      const h=await r.json();
      document.getElementById('histCount').innerText=h.trades?h.trades.length:'-';
      document.getElementById('histTotal').innerText=fmt5(h.total_pnl||0);
      const total=(h.wins||0)+(h.losses||0);
      document.getElementById('histWinRate').innerText=total>0?((h.wins/total)*100).toFixed(0)+'%':'-';
      const list=document.getElementById('histList');
      if(!h.trades||h.trades.length===0){
        list.innerHTML='<div class="pair-item"><span class="pair-meta">Nenhum trade.</span></div>';
        return;
      }
      list.innerHTML=h.trades.slice().reverse().map(t=>`<div class="pair-item"><div class="pair-info"><div class="pair-name"><span class="pair-side ${t.side==='long'?'side-long':'side-short'}">${t.side.toUpperCase()}</span>${t.symbol}</div><div class="pair-meta">${t.reason} | ${t.time}</div></div><div class="pair-score ${(t.pnl||0)>=0?'positive':'negative'}">${fmt5(t.pnl)}</div></div>`).join('');
    }catch(e){ showDebug('ERRO historico: '+e.message); }
  }

  async function updateDashboard(){
    try{
      const r=await fetch('/api/state');
      if(!r.ok){ showDebug('API '+r.status); return; }
      const s=await r.json();

      // Header
      document.getElementById('hdrInitial').innerText=fmtMoney(s.session_start_balance||0);
      document.getElementById('hdrCurrent').innerText=fmtMoney(s.current_balance||0);

      // Position Control
      const pos=s.current_position;
      if(pos&&pos.symbol){
        document.getElementById('posSymbol').innerText=pos.symbol;
        document.getElementById('posSideText').innerText=pos.side.toUpperCase()+' | '+pos.leverage+'x';
        document.getElementById('posBadge').innerText=pos.side.toUpperCase();
        document.getElementById('posBadge').className='pos-badge '+(pos.side==='long'?'long':'short');
        document.getElementById('posProfit').innerText=fmt5(s.unrealized_pnl||0);
        document.getElementById('posProfit').className='pos-profit '+(s.unrealized_pnl>=0?'positive':'negative');
        document.getElementById('posEntry').innerText=fmtMoney(pos.entry||0);
        document.getElementById('posCurrent').innerText=fmtMoney(pos.price||0);
        document.getElementById('posPeak').innerText=fmt2(s.peak_pnl_pct||0)+'%';
        document.getElementById('posLev').innerText=pos.leverage+'x';
        document.getElementById('posSize').innerText=fmtMoney(pos.size||0);
        document.getElementById('posLock').innerText=fmt2(s.lock_stage_pct||0)+'%';

        // Atualiza dados do chart
        entryPrice=pos.entry||0;
        posSide=pos.side||'';
        // Calcula stop price baseado no SL config
        const slPct=parseFloat(document.getElementById('fStopLoss').value)||1.5;
        if(posSide==='long') slPrice=entryPrice*(1-slPct/100);
        else if(posSide==='short') slPrice=entryPrice*(1+slPct/100);

        // Adiciona ao historico de precos
        priceHistory.push({t:Date.now(), p:pos.price||0});
        if(priceHistory.length>100) priceHistory.shift();

        document.getElementById('chartSymbol').innerText=pos.symbol.replace('/USDT:USDT','');
      }else{
        document.getElementById('posSymbol').innerText='Aguardando sinal...';
        document.getElementById('posSideText').innerText='-';
        document.getElementById('posBadge').innerText='AGUARDANDO';
        document.getElementById('posBadge').className='pos-badge waiting';
        document.getElementById('posProfit').innerText='+0,00000';
        document.getElementById('posProfit').className='pos-profit';
        document.getElementById('posEntry').innerText='-';
        document.getElementById('posCurrent').innerText='-';
        document.getElementById('posPeak').innerText='-';
        document.getElementById('posLev').innerText='-';
        document.getElementById('posSize').innerText='-';
        document.getElementById('posLock').innerText='-';
        priceHistory=[]; entryPrice=0; posSide=''; slPrice=0;
      }

      // Stats
      document.getElementById('txtStatus').innerText=s.status?s.status.toUpperCase():'PARADO';
      document.getElementById('txtStatus').className='value '+(s.status==='operando'?'positive':s.status==='parado'?'':s.status==='CIRCUIT_BREAKER'?'negative':'');
      document.getElementById('txtReal').innerText=fmt5(s.realized_pnl||0);
      document.getElementById('txtReal').className='value '+(s.realized_pnl>=0?'positive':'negative');
      document.getElementById('txtSignalDash').innerText=s.last_signal||'-';
      const lat=s.scan_latency_ms||0;
      document.getElementById('txtLatency').innerText=lat>0?lat+'ms':'-';

      // Logs
      const logBox=document.getElementById('logBox');
      const logs=s.logs||[];
      if(logs.length>0){
        logBox.innerHTML=logs.slice(-20).map(l=>`<div>${l}</div>`).join('');
        logBox.scrollTop=logBox.scrollHeight;
      }

      // Button
      isRunning=s.status==='operando'||s.status==='iniciando';
      const btn=document.getElementById('ctrlBtn');
      if(isRunning){btn.innerText='PARAR';btn.className='btn-action stop';}
      else{btn.innerText='INICIAR';btn.className='btn-action start';}

      // Redesenha chart
      drawTradeChart();
    }catch(e){ showDebug('FETCH: '+e.message); }
  }

  loadConfig();
  updateDashboard();
  setInterval(updateDashboard, 1500);
  setInterval(()=>{if(document.getElementById('view-market').classList.contains('hidden')===false)loadMarket();}, 5000);
</script>
</body>
</html>
'''

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
        'api_key': '', 'api_secret': '', 'stop_loss_pct': 1.5,
        'leverage': 3, 'timeframe': '15m', 'exchange': 'bybit',
        'sandbox': True, 'order_size_usdt': 0.9
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
    try: return float(v)
    except: return default

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
        total = safe_float(usdt.get('total_equity'), 0.0)
    if total <= 0:
        total = safe_float(usdt.get('total_wallet'), 0.0)
    return total

def symbol_to_tv(symbol):
    if not symbol: return 'BTCUSDT.P'
    s = symbol.replace('/USDT:USDT', 'USDT').replace('/USDT', 'USDT').replace('/', '')
    return s + '.P' if not s.endswith('.P') else s

def _update_bot_state(**kwargs):
    controller.state.update(kwargs)

def _reset_dashboard():
    controller.state.update(
        current_position=None, entry_line=None,
        unrealized_pnl=0.0, realized_pnl=0.0,
        peak_pnl_pct=0.0, lock_price=None, lock_stage_pct=0.0,
        opened_at=None, price_history=[], pnl_history=[],
        chart_symbol='BTCUSDT.P', last_signal='-',
        scan_results=[], active_pairs=[], scan_latency_ms=0,
        consecutive_losses=0, circuit_breaker_triggered=False,
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
            await add_trade(tracker.symbol, tracker.side, tracker.entry_price, price, unrealized, reason, tracker.leverage)
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


async def scanner_task(ex, settings, tracker):
    scanner = MarketScanner(ex, settings)
    scanner_interval = 15
    last_balance = 0.0
    last_balance_time = 0

    while controller.running:
        start_time = time.time()
        try:
            now = time.time()
            if now - last_balance_time > 15 or last_balance <= 0:
                try:
                    bal = await ex.get_balance()
                    last_balance = get_total_balance(bal)
                    usdt_data = bal.get('USDT', {})
                    last_balance_time = now
                    if last_balance > 0:
                        add_log(f"BALANCE | {last_balance:.5f} | w={usdt_data.get('wallet',0):.5f} e={usdt_data.get('equity',0):.5f}")
                        _update_bot_state(current_balance=round(last_balance, 8))
                    else:
                        add_log(f"BALANCE ZERO | w={usdt_data.get('wallet',0)} e={usdt_data.get('equity',0)} tw={usdt_data.get('total_wallet',0)} te={usdt_data.get('total_equity',0)}")
                except Exception as e:
                    add_log(f"BALANCE ERRO: {e}")

            total_bal = last_balance if last_balance > 0 else tracker.session_start_balance
            if total_bal <= 0:
                total_bal = 1.0

            tf_map = {'5m': '5', '15m': '15', '1h': '60'}
            tf = tf_map.get(settings.get('timeframe', '15m'), '15')

            res = await asyncio.wait_for(
                scanner.scan(balance=total_bal, top_n=10, timeframe=tf),
                timeout=12.0
            )

            latency = int((time.time() - start_time) * 1000)
            pairs = res.get('pairs', [])
            error = res.get('error')
            scanned = res.get('scanned', 0)

            if error:
                add_log(f"SCAN ERRO [{latency}ms]: {error}")
            else:
                top_sym = pairs[0]['symbol'] if pairs else 'nenhum'
                top_score = pairs[0]['score'] if pairs else 0
                add_log(f"SCAN [{latency}ms] | {len(pairs)} ops | {scanned} cand | TOP: {top_sym} ({top_score:.2f})")

            pairs_24h = {}
            for p in pairs:
                pairs_24h[p['symbol']] = {'last': p['price'], 'high': p['price']*1.02, 'low': p['price']*0.98, 'change': p.get('change_24h', 0)}

            _update_bot_state(
                scan_results=pairs, active_pairs=[p['symbol'] for p in pairs],
                pairs_24h=pairs_24h, last_scan=datetime.now().strftime('%H:%M:%S'),
                scan_latency_ms=latency,
            )

        except asyncio.TimeoutError:
            add_log("SCAN TIMEOUT")
        except Exception as e:
            add_log(f"SCANNER: {e}")

        elapsed = time.time() - start_time
        await asyncio.sleep(max(0.5, scanner_interval - elapsed))


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
                _reset_dashboard()
                await asyncio.sleep(monitor_interval)
                continue

            current_price = safe_float(pos.get('markPrice'), 0)
            if current_price <= 0:
                await asyncio.sleep(monitor_interval)
                continue

            unrealized = safe_float(pos.get('unrealizedPnl'), 0)
            tracker.update_peak(current_price)

            controller.state['price_history'].append({'t': datetime.now().strftime('%H:%M:%S'), 'p': round(current_price, 8)})
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
            controller.state['pnl_history'].append({'time': datetime.now().strftime('%H:%M:%S'), 'pnl': round(total_pnl, 8)})
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
                    if unrealized < 0: controller.state['consecutive_losses'] += 1
                    else: controller.state['consecutive_losses'] = 0
                    _update_bot_state(realized_pnl=round(realized + unrealized, 8))
                    _reset_dashboard()
                    tracker.reset()
                except Exception as e:
                    add_log(f"ERRO SL: {e}")
                await asyncio.sleep(1)
                continue

            should_close, reason = tracker.check_trailing_stop(current_price)
            if should_close:
                add_log(f"TRAIL | {tracker.symbol} | {reason}")
                try:
                    await ex.close_position(tracker.symbol, tracker.side, tracker.size)
                    add_log(f"CLOSE {reason} | {tracker.symbol} @ {current_price} | PnL: {unrealized:.5f}")
                    await add_trade(tracker.symbol, tracker.side, tracker.entry_price, current_price, unrealized, reason, tracker.leverage)
                    if unrealized < 0: controller.state['consecutive_losses'] += 1
                    else: controller.state['consecutive_losses'] = 0
                    _update_bot_state(realized_pnl=round(realized + unrealized, 8))
                    _reset_dashboard()
                    tracker.reset()
                except Exception as e:
                    add_log(f"ERRO TRAIL: {e}")
                await asyncio.sleep(1)
                continue

            await asyncio.sleep(monitor_interval)
        except Exception as e:
            add_log(f"MONITOR: {e}")
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
            if not scan_results: continue

            best = scan_results[0]
            best_signal = SignalResult(
                side=best.get('side'), symbol=best.get('symbol'),
                score=best.get('score', 0), price=best.get('price', 0),
                expected_return_pct=best.get('expected_return_pct', 0), meta=best,
            )

            if not tracker.symbol:
                if best_signal.score < 0.72:
                    continue

                bal = await ex.get_balance()
                total_bal = get_total_balance(bal)
                if total_bal <= 0:
                    total_bal = tracker.session_start_balance or 1.0

                session_start = controller.state.get('session_start_balance', total_bal)
                if total_bal < session_start * 0.85:
                    add_log("STOP GLOBAL | Saldo < 85% do inicial")
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
                        add_log(f"BLOQUEIO | Slippage {slip_pct:.2f}%")
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

                    add_log(f"ENTRY {best_signal.side.upper()} {sym} @ {price} | Score:{best_signal.score:.2f} ADX:{adx:.1f} LEV:{lev}x")

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
                    add_log(f"ROTATE | {tracker.symbol} -> {best_signal.symbol}")
                    try:
                        await ex.close_position(tracker.symbol, tracker.side, tracker.size)
                        await add_trade(tracker.symbol, tracker.side, tracker.entry_price, current_price, unrealized, 'ROTATE_OPP_COST', tracker.leverage)
                        if unrealized < 0: controller.state['consecutive_losses'] += 1
                        else: controller.state['consecutive_losses'] = 0
                        _update_bot_state(realized_pnl=round(safe_float(controller.state.get('realized_pnl'), 0) + unrealized, 8))
                        _reset_dashboard()
                        tracker.reset()
                        await asyncio.sleep(1.5)
                    except Exception as e:
                        add_log(f"ERRO ROTATE: {e}")
        except Exception as e:
            add_log(f"EXECUTOR: {e}")


async def health_check_task(ex):
    while controller.running:
        try:
            await asyncio.sleep(45)
            await ex.fetch_ticker('BTCUSDT:USDT')
        except Exception as e:
            add_log(f"HEALTH: {e}")


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
        usdt_data = bal.get('USDT', {})

        add_log(f"BALANCE DEBUG | w={usdt_data.get('wallet',0):.5f} e={usdt_data.get('equity',0):.5f} tw={usdt_data.get('total_wallet',0):.5f} te={usdt_data.get('total_equity',0):.5f}")

        if total_bal <= 0:
            add_log("BALANCE ZERO - usando fallback 1.0")
            total_bal = 1.0

        tracker = PositionTracker()
        tracker.session_start_balance = total_bal
        controller.tracker_global = tracker

        _update_bot_state(
            status='operando',
            session_start_balance=round(total_bal, 8),
            current_balance=round(total_bal, 8),
            realized_pnl=0.0, unrealized_pnl=0.0,
            consecutive_losses=0, circuit_breaker_triggered=False,
            total_trades_today=0,
        )
        add_log(f"START HFT | Balance: {total_bal:.5f} USDT | SL: {settings.get('stop_loss_pct', 1.5)}% | ScoreMin: 0.72")

        controller._scan_task = asyncio.create_task(scanner_task(ex, settings, tracker))
        controller._monitor_task = asyncio.create_task(monitor_task(ex, settings, tracker))
        controller._executor_task = asyncio.create_task(executor_task(ex, settings, tracker))
        controller._health_task = asyncio.create_task(health_check_task(ex))

        await asyncio.gather(
            controller._scan_task, controller._monitor_task,
            controller._executor_task, controller._health_task,
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


@app.route('/')
def index():
    return INDEX_HTML

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

    _reset_dashboard()
    controller.state['status'] = 'parado'
    add_log("BOT PARADO | Dashboard zerado")
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
