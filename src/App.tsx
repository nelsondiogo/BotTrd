import React, { useState, useEffect } from 'react';
import { Play, Square, TrendingUp, Activity, RefreshCw, Terminal, Zap, Lock, Settings, History, LayoutDashboard, Search, Clock, ShieldAlert } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      setStatus(data);
      setLoading(false);
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    fetchStatus();
    const inv = setInterval(fetchStatus, 3000);
    return () => clearInterval(inv);
  }, []);

  if (loading) return <div className="min-h-screen bg-black flex items-center justify-center text-emerald-500 font-mono">CARREGANDO MOTOR...</div>;

  return (
    <div className="min-h-screen bg-black text-white font-sans pb-24">
      <header className="border-b border-white/5 p-4 flex justify-between items-center sticky top-0 bg-black/80 backdrop-blur">
        <div className="flex gap-4">
          <div><p className="text-[10px] text-neutral-500 uppercase">Saldo</p><p className="font-mono text-emerald-500">${status.balance.toFixed(2)}</p></div>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${status.isRunning ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`} />
          <span className="text-[10px] uppercase font-bold">ND-BOT ULTRA</span>
        </div>
        <button onClick={() => fetch('/api/toggle', {method:'POST'})} className={`p-2 rounded-full ${status.isRunning ? 'bg-red-500/20 text-red-500' : 'bg-emerald-500 text-black'}`}>
          {status.isRunning ? <Square size={16}/> : <Play size={16}/>}
        </button>
      </header>

      <main className="p-6">
        <AnimatePresence mode="wait">
          {activeTab === 'dashboard' && <DashboardView status={status} />}
          {activeTab === 'scan' && <ScanView status={status} />}
          {activeTab === 'history' && <HistoryView history={status.history} />}
        </AnimatePresence>
      </main>

      <nav className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-neutral-900 border border-white/10 p-2 rounded-2xl flex gap-2">
        <NavBtn icon={<LayoutDashboard size={18}/>} active={activeTab === 'dashboard'} onClick={()=>setActiveTab('dashboard')} />
        <NavBtn icon={<Search size={18}/>} active={activeTab === 'scan'} onClick={()=>setActiveTab('scan')} />
        <NavBtn icon={<History size={18}/>} active={activeTab === 'history'} onClick={()=>setActiveTab('history')} />
      </nav>
    </div>
  );
}

function NavBtn({icon, active, onClick}: any) {
  return (
    <button onClick={onClick} className={`p-3 rounded-xl transition-all ${active ? 'bg-emerald-500 text-black' : 'text-neutral-500 hover:bg-white/5'}`}>
      {icon}
    </button>
  );
}

function DashboardView({status}: any) {
  return (
    <motion.div initial={{opacity:0}} animate={{opacity:1}} className="grid gap-6">
      <div className="bg-neutral-900 p-6 rounded-3xl border border-white/5">
        <h3 className="text-[10px] text-neutral-500 uppercase mb-4">Posição Atual</h3>
        {status.currentPosition ? (
          <div>
            <p className="text-2xl font-bold">{status.currentPosition.symbol}</p>
            <p className={`text-4xl font-mono font-bold mt-2 ${parseFloat(status.currentPosition.percentage) >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
              {status.currentPosition.percentage}%
            </p>
          </div>
        ) : <p className="text-neutral-600 italic">Nenhuma posição ativa</p>}
      </div>
      <div className="bg-neutral-900 p-4 rounded-2xl border border-white/5 overflow-hidden h-64 font-mono text-[10px] space-y-1">
        {status.logs.map((l:any, i:any) => <div key={i} className="text-neutral-500">{l}</div>)}
      </div>
    </motion.div>
  );
}

function ScanView({status}: any) {
  return (
    <div className="grid gap-4">
      {status.scanData.map((s:any, i:any) => (
        <div key={i} className="bg-neutral-900 p-4 rounded-xl border border-white/5 flex justify-between items-center">
          <div>
            <p className="font-bold">{s.symbol}</p>
            <p className="text-[10px] text-neutral-500">RSI: {s.rsi?.toFixed(0)} | Trend: {s.trend}</p>
          </div>
          <div className="text-emerald-500 font-bold">{s.score.toFixed(2)}</div>
        </div>
      ))}
    </div>
  );
}

function HistoryView({history}: any) {
  return (
    <div className="space-y-3">
      {history?.map((h:any, i:any) => (
        <div key={i} className="bg-neutral-900 p-4 rounded-xl border border-white/5 flex justify-between">
          <p className="text-xs">{h.symbol} - {h.type}</p>
          <p className={`text-xs ${h.pnlPct >=0 ? 'text-emerald-500' : 'text-red-500'}`}>{h.pnlPct?.toFixed(2)}%</p>
        </div>
      ))}
    </div>
  );
}
