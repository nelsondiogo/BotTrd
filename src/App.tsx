import React, { useState, useEffect } from 'react';
import { Play, Square, Activity, Zap, LayoutDashboard, History, Settings, Search } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from './lib/utils';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [status, setStatus] = useState<any>(null);

  useEffect(() => {
    const fetchStatus = () => fetch('/api/status').then(r => r.json()).then(setStatus);
    fetchStatus();
    const int = setInterval(fetchStatus, 3000);
    return () => clearInterval(int);
  }, []);

  return (
    <div className="min-h-screen bg-[#0a0a0d] text-zinc-400 pb-24">
      {/* Header e Navegação conforme as imagens enviadas */}
      <nav className="fixed bottom-4 left-1/2 -translate-x-1/2 bg-black/80 p-2 rounded-2xl flex gap-2 border border-white/10">
        <NavButton active={activeTab === 'dashboard'} onClick={() => setActiveTab('dashboard')} icon={<LayoutDashboard size={18} />} label="painel" />
        <NavButton active={activeTab === 'history'} onClick={() => setActiveTab('history')} icon={<History size={18} />} label="histórico" />
      </nav>
    </div>
  );
}

function NavButton({ active, onClick, icon, label }: any) {
  return (
    <button onClick={onClick} className={cn("p-3 rounded-xl flex flex-col items-center", active ? "bg-emerald-500/20 text-emerald-400" : "text-zinc-600")}>
      {icon}
      <span className="text-[8px] uppercase font-bold mt-1">{label}</span>
    </button>
  );
}
