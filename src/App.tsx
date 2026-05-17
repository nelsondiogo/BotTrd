import React, { useState, useEffect, useMemo } from 'react';
import { Play, Square, TrendingUp, Activity, Wallet, RefreshCw, Terminal, Zap, Lock, LayoutDashboard, LineChart as ChartIcon, BarChart3, History, Settings, ArrowUpRight, ArrowDownRight, Clock, Search } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [status, setStatus] = useState<any>(null);
  const [chartData, setChartData] = useState<any[]>([]);

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      setStatus(data);
    } catch {}
  };

  const closePosition = async () => {
    if (!confirm("Fechar posição manualmente?")) return;
    await fetch('/api/close', { method: 'POST' });
    fetchStatus();
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-[#0a0a0d] text-zinc-400 font-sans pb-28">
      <header className="sticky top-0 z-50 bg-[#0a0a0d]/90 backdrop-blur-xl border-b border-zinc-800 p-4">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="text-emerald-500 fill-emerald-500/20" size={20} />
            <span className="text-sm font-black uppercase text-white tracking-widest">ND-BOT ULTRA</span>
          </div>
          <div className="flex flex-col items-end">
            <span className="text-[10px] font-black text-zinc-600 uppercase">Saldo</span>
            <span className="text-sm font-mono font-bold text-emerald-500">${status?.balance?.toFixed(2)}</span>
          </div>
        </div>
      </header>

      <main className="max-w-[1600px] mx-auto p-4 md:p-6">
        <AnimatePresence mode="wait">
          {activeTab === 'dashboard' && <DashboardView status={status} onClose={closePosition} />}
          {activeTab === 'market' && <MarketView status={status} />}
          {activeTab === 'history' && <HistoryView history={status?.history} />}
        </AnimatePresence>
      </main>

      <nav className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 w-full px-4 md:w-auto">
        <div className="max-w-full overflow-x-auto bg-neutral-900/90 backdrop-blur-xl border border-white/5 rounded-2xl p-1.5 flex items-center gap-1 scrollbar-hide shadow-2xl">
          <div className="flex items-center gap-1 min-w-max">
            <NavButton active={activeTab === 'dashboard'} onClick={() => setActiveTab('dashboard')} icon={<LayoutDashboard size={18} />} label="painel" />
            <NavButton active={activeTab === 'market'} onClick={() => setActiveTab('market')} icon={<BarChart3 size={18} />} label="mercado" />
            <NavButton active={activeTab === 'history'} onClick={() => setActiveTab('history')} icon={<History size={18} />} label="histórico" />
          </div>
        </div>
      </nav>
    </div>
  );
}

function NavButton({ active, onClick, icon, label }: any) {
  return (
    <button onClick={onClick} className={cn("flex flex-col items-center justify-center w-20 h-14 rounded-xl transition-all", active ? "bg-emerald-500/10 text-emerald-500" : "text-zinc-500")}>
      {icon}
      <span className="text-[8px] font-bold uppercase mt-1">{label}</span>
    </button>
  );
}

function DashboardView({ status, onClose }: any) {
  const pnl = status?.currentPosition ? parseFloat(status.currentPosition.percentage || '0') : 0;
  return (
    <div className="space-y-6">
       {status?.currentPosition ? (
         <div className="bg-zinc-900/50 border border-zinc-800 rounded-3xl p-6">
            <div className="flex justify-between items-start mb-6">
               <div>
                 <h2 className="text-2xl font-bold text-white leading-none mb-1">{status.currentPosition.symbol}</h2>
                 <p className="text-[10px] font-black text-zinc-600 uppercase">10x Leverage</p>
               </div>
               <button onClick={onClose} className="px-4 py-2 bg-red-500 text-white rounded-full text-[10px] font-black uppercase">Fecho Manual</button>
            </div>
            <div className={cn("text-6xl font-black font-mono tracking-tighter", pnl >= 0 ? "text-emerald-500" : "text-red-500")}>
               {pnl > 0 ? "+" : ""}{pnl.toFixed(2)}%
            </div>
         </div>
       ) : (
         <div className="p-12 text-center bg-zinc-900/20 border-2 border-dashed border-zinc-800 rounded-3xl">
            <Activity className="mx-auto mb-4 text-zinc-700 animate-pulse" />
            <p className="text-[10px] font-black uppercase text-zinc-600 tracking-widest">A aguardar sinal de entrada...</p>
         </div>
       )}
    </div>
  );
}

function MarketView({ status }: any) {
  return (
    <div className="bg-zinc-900/50 border border-zinc-800 rounded-3xl overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[10px]">
          <thead className="bg-zinc-800/50 text-zinc-500 font-bold uppercase tracking-widest">
            <tr>
              <th className="px-6 py-4">PAR</th>
              <th className="px-6 py-4">PREÇO</th>
              <th className="px-6 py-4 text-right">VOL 24H</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/50">
            {status?.activePairs?.map((pair: any) => (
              <tr key={pair.symbol} className="hover:bg-emerald-500/5">
                <td className="px-6 py-4 font-bold text-white">{pair.symbol.split(':')[0]}</td>
                <td className="px-6 py-4 font-mono text-zinc-400">${parseFloat(pair.lastPrice).toFixed(4)}</td>
                <td className="px-6 py-4 text-right font-mono text-zinc-500">${new Intl.NumberFormat('en-US', { notation: 'compact' }).format(pair.volume)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HistoryView({ history }: any) {
  return (
    <div className="space-y-3">
       {history?.map((h: any, i: number) => (
         <div key={i} className="bg-zinc-900/40 border border-zinc-800 p-4 rounded-2xl flex justify-between items-center">
            <div>
               <p className="text-white font-bold">{h.symbol}</p>
               <p className="text-[8px] text-zinc-600 uppercase">{h.type} | {new Date(h.timestamp).toLocaleTimeString()}</p>
            </div>
            <div className="text-right">
               <p className={cn("font-black", h.pnlPct >= 0 ? "text-emerald-500" : "text-red-500")}>
                  {h.pnlPct ? `${h.pnlPct > 0 ? "+" : ""}${h.pnlPct.toFixed(2)}%` : "-"}
               </p>
            </div>
         </div>
       ))}
    </div>
  );
}
