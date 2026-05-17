import React, { useState, useEffect, useMemo } from 'react';
import { Play, Square, Zap, TrendingUp, Activity, Terminal, LayoutDashboard, LineChart as ChartIcon, BarChart3, History, Settings, Search } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from './lib/utils';
// ... (restante das importações de Recharts e Lucide)

function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      setStatus(data);
      setLoading(false);
    } catch (e) { console.error("Error fetching status"); }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 2000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div className="min-h-screen bg-black flex items-center justify-center font-mono text-[10px] text-emerald-500 uppercase animate-pulse">Iniciando Motor...</div>;

  return (
    <div className="min-h-screen bg-[#0a0a0d] text-zinc-400 font-sans pb-28">
      {/* Header com botões de controlo e saldo real-time */}
      <header className="sticky top-0 z-50 bg-black/80 backdrop-blur-xl border-b border-zinc-800 p-4">
        {/* ... lógica de UI detalhada no arquivo original ... */}
      </header>

      <main className="max-w-[1600px] mx-auto p-4 md:p-6">
        <AnimatePresence mode="wait">
          {activeTab === 'dashboard' && <DashboardView status={status} onClosePosition={closePosition} />}
          {/* ... outras views delegadas ... */}
        </AnimatePresence>
      </main>

      {/* Menu de Navegação flutuante estilo bento */}
      <nav className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50">
        <div className="bg-black/90 border border-white/10 rounded-2xl p-1 flex items-center gap-1 shadow-2xl">
          <NavButton active={activeTab === 'dashboard'} onClick={() => setActiveTab('dashboard')} icon={<LayoutDashboard />} label="painel" />
          <NavButton active={activeTab === 'chart'} onClick={() => setActiveTab('chart')} icon={<ChartIcon />} label="gráfico" />
          <NavButton active={activeTab === 'market'} onClick={() => setActiveTab('market')} icon={<BarChart3 />} label="mercado" />
          <NavButton active={activeTab === 'scan'} onClick={() => setActiveTab('scan')} icon={<Search />} label="scan" />
          <NavButton active={activeTab === 'history'} onClick={() => setActiveTab('history')} icon={<History />} label="histórico" />
          <NavButton active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} icon={<Settings />} label="setup" />
        </div>
      </nav>
    </div>
  );
}
