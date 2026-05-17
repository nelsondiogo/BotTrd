import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { 
  Zap, TrendingUp, LayoutDashboard, History, Settings, 
  Play, Square, Search, BarChart3, Activity, ArrowUpRight, ArrowDownRight 
} from 'lucide-react';
import { cn } from './lib/utils';

type Tab = 'dashboard' | 'chart' | 'market' | 'scan' | 'history' | 'settings';

function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [status, setStatus] = useState<any>(null);

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      setStatus(data);
    } catch (e) { console.error("Offline"); }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 2000);
    return () => clearInterval(interval);
  }, []);

  const toggleBot = () => fetch('/api/toggle', { method: 'POST' }).then(fetchStatus);

  return (
    <div className="min-h-screen bg-[#0a0a0d] text-zinc-400 font-sans pb-32">
      <header className="sticky top-0 z-50 bg-[#0a0a0d]/90 backdrop-blur-xl border-b border-zinc-800">
        <div className="max-w-[1600px] mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="text-emerald-500" size={18} />
            <span className="text-xs font-black uppercase text-white">ND-BOT ULTRA</span>
          </div>
          <button onClick={toggleBot} className={cn(
            "px-4 py-2 rounded-lg text-[10px] font-black uppercase",
            status?.isRunning ? "bg-red-500/10 text-red-500" : "bg-emerald-500 text-black"
          )}>
            {status?.isRunning ? "STOP" : "RUN"}
          </button>
        </div>
      </header>

      <main className="p-4">
        {activeTab === 'dashboard' && <DashboardView status={status} />}
        {/* Outras views aqui... */}
      </main>

      <nav className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 w-full px-4 md:w-auto">
        <div className="bg-black/80 backdrop-blur-2xl border border-white/10 rounded-2xl p-1 flex items-center justify-around md:justify-center gap-1">
          <NavButton active={activeTab === 'dashboard'} onClick={() => setActiveTab('dashboard')} icon={<LayoutDashboard size={20} />} label="Painel" />
          <NavButton active={activeTab === 'market'} onClick={() => setActiveTab('market')} icon={<BarChart3 size={20} />} label="Mercado" />
          <NavButton active={activeTab === 'history'} onClick={() => setActiveTab('history')} icon={<History size={20} />} label="Logs" />
          <NavButton active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} icon={<Settings size={20} />} label="Setup" />
        </div>
      </nav>
    </div>
  );
}

function NavButton({ active, onClick, icon, label }: any) {
  return (
    <button onClick={onClick} className={cn(
      "flex flex-col items-center justify-center min-w-[60px] p-2 rounded-xl transition-all",
      active ? "bg-emerald-500/20 text-emerald-400" : "text-zinc-500"
    )}>
      {icon}
      <span className="text-[7px] font-black uppercase mt-1">{label}</span>
    </button>
  );
}

function DashboardView({ status }: any) {
  return (
    <div className="space-y-4">
       <div className="bg-zinc-900/50 p-6 rounded-3xl border border-zinc-800">
         <p className="text-[10px] font-black text-zinc-500 uppercase tracking-widest">Saldo USDT</p>
         <h1 className="text-3xl font-mono font-bold text-white">${status?.balance?.toFixed(2) || '0.00'}</h1>
       </div>
       {/* Cards de posição ativa e sinais aqui */}
    </div>
  );
}

export default App;
