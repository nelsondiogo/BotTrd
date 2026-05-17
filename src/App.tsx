// ... (imports)

function NavButton({ active, onClick, icon, label }: any) {
  return (
    <button 
      onClick={onClick}
      className={cn(
        "relative flex flex-col items-center justify-center min-w-[52px] h-11 md:w-20 md:h-14 rounded-xl transition-all",
        active ? "bg-emerald-500/20 text-emerald-400" : "text-neutral-500 active:bg-white/5"
      )}
    >
      <div className={cn("transition-transform", active && "scale-110")}>{icon}</div>
      <span className="text-[7px] md:text-[8px] font-black uppercase tracking-widest mt-0.5 hidden sm:block">{label}</span>
      {active && <motion.div layoutId="nav-glow" className="absolute bottom-1 w-1 h-1 bg-emerald-500 rounded-full shadow-[0_0_8px_#10b981]" />}
    </button>
  );
}

// ... (Dashboard View com cards responsivos)

function MarketView({ status }: { status: any }) {
  return (
    <div className="bg-zinc-900/50 border border-zinc-800 rounded-3xl overflow-hidden">
      <div className="overflow-x-auto scrollbar-hide">
        <table className="w-full text-left min-w-[380px]">
          <thead>
            <tr className="bg-zinc-800/50 text-zinc-500 font-black uppercase text-[8px] tracking-[0.2em] border-b border-zinc-700/50">
              <th className="px-5 py-4">par</th>
              <th className="px-5 py-4">preço</th>
              <th className="px-5 py-4 text-right">vol 24h</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/50 font-mono">
            {status?.activePairs?.map((pair: any, i: number) => (
              <tr key={pair.symbol} className="active:bg-emerald-500/10 transition-colors">
                <td className="px-5 py-3 text-[11px] font-bold text-zinc-300 uppercase">{pair.symbol.split(':')[0]}</td>
                <td className="px-5 py-3 text-[11px] text-zinc-400">$ {parseFloat(pair.lastPrice).toFixed(4)}</td>
                <td className="px-5 py-3 text-right text-[10px] text-zinc-500 font-bold">
                  $ {new Intl.NumberFormat('en-US', { notation: 'compact' }).format(pair.volume)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
