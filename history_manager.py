import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List

HISTORY_FILE = 'history.json'
STATE_FILE = 'state.json'

class AsyncHistoryManager:
    """Gerenciador de histórico otimizado para async com cache em memória."""

    def __init__(self):
        self._history_cache: Optional[Dict[str, Any]] = None
        self._state_cache: Optional[Dict[str, Any]] = None
        self._lock = asyncio.Lock()
        self._dirty = False
        self._last_save = 0
        self._save_interval = 10  # Salva a cada 10 segundos no máximo

    async def _load_history(self) -> Dict[str, Any]:
        """Carrega histórico do disco ou cache."""
        if self._history_cache is not None:
            return self._history_cache

        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self._history_cache = json.load(f)
                    return self._history_cache
            except Exception:
                pass

        self._history_cache = {'trades': [], 'total_pnl': 0.0, 'wins': 0, 'losses': 0}
        return self._history_cache

    async def _save_history(self, force: bool = False):
        """Salva histórico no disco com throttling."""
        if not force and not self._dirty:
            return

        now = asyncio.get_event_loop().time()
        if not force and (now - self._last_save) < self._save_interval:
            return

        async with self._lock:
            try:
                with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self._history_cache, f, indent=2, ensure_ascii=False)
                self._dirty = False
                self._last_save = now
            except Exception:
                pass

    async def add_trade(self, symbol: str, side: str, entry: float, exit_price: float, 
                       pnl: float, reason: str, leverage: int = 1, fees: float = 0.0, 
                       duration_sec: int = 0):
        """Adiciona trade ao histórico com cache."""
        async with self._lock:
            h = await self._load_history()

            h['trades'].append({
                'symbol': symbol,
                'side': side,
                'entry': round(entry, 8),
                'exit': round(exit_price, 8),
                'pnl': round(pnl, 8),
                'fees': round(fees, 8),
                'net_pnl': round(pnl - fees, 8),
                'reason': reason,
                'leverage': leverage,
                'duration_sec': duration_sec,
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })

            h['total_pnl'] = round(h['total_pnl'] + pnl - fees, 8)
            if (pnl - fees) >= 0:
                h['wins'] += 1
            else:
                h['losses'] += 1

            # Mantém apenas últimos 500 trades
            if len(h['trades']) > 500:
                h['trades'] = h['trades'][-500:]

            self._dirty = True

        # Salva em background (não bloqueia)
        asyncio.create_task(self._save_history())

    async def get_history(self, limit: int = 100) -> Dict[str, Any]:
        """Retorna histórico com limite opcional."""
        h = await self._load_history()
        if limit and len(h['trades']) > limit:
            h_copy = h.copy()
            h_copy['trades'] = h['trades'][-limit:]
            return h_copy
        return h

    async def get_recent_trades(self, n: int = 5) -> List[Dict[str, Any]]:
        """Retorna os N trades mais recentes."""
        h = await self._load_history()
        return h['trades'][-n:] if h['trades'] else []

    async def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do histórico."""
        h = await self._load_history()
        total = h['wins'] + h['losses']
        win_rate = (h['wins'] / total * 100) if total > 0 else 0

        # Calcula streak atual
        streak = 0
        streak_type = None
        for trade in reversed(h['trades']):
            is_win = trade.get('net_pnl', 0) >= 0
            if streak_type is None:
                streak_type = is_win
                streak = 1
            elif streak_type == is_win:
                streak += 1
            else:
                break

        return {
            'total_trades': total,
            'wins': h['wins'],
            'losses': h['losses'],
            'win_rate': round(win_rate, 1),
            'total_pnl': h['total_pnl'],
            'current_streak': streak,
            'streak_type': 'win' if streak_type else 'loss' if streak_type is not None else None,
        }

    # =============================================================================
    # PERSISTÊNCIA DE ESTADO (sobrevive a reinícios)
    # =============================================================================
    async def save_bot_state(self, state: Dict[str, Any]):
        """Salva estado do bot com throttling."""
        try:
            async with self._lock:
                self._state_cache = state
                with open(STATE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(state, f, indent=2, ensure_ascii=False, default=str)
        except Exception:
            pass

    async def load_bot_state(self) -> Optional[Dict[str, Any]]:
        """Carrega estado do bot."""
        if self._state_cache is not None:
            return self._state_cache

        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    self._state_cache = json.load(f)
                    return self._state_cache
            except Exception:
                pass
        return None

    async def clear_bot_state(self):
        """Limpa estado do bot."""
        self._state_cache = None
        if os.path.exists(STATE_FILE):
            try:
                os.remove(STATE_FILE)
            except Exception:
                pass

    async def flush(self):
        """Força salvamento imediato."""
        await self._save_history(force=True)


# Instância global
history_mgr = AsyncHistoryManager()

# Funções de compatibilidade (para não quebrar código existente)
async def add_trade(symbol, side, entry, exit_price, pnl, reason, leverage=1, fees=0.0, duration_sec=0):
    await history_mgr.add_trade(symbol, side, entry, exit_price, pnl, reason, leverage, fees, duration_sec)

async def get_history(limit=100):
    return await history_mgr.get_history(limit)

async def get_recent_trades(n=5):
    return await history_mgr.get_recent_trades(n)

async def get_stats():
    return await history_mgr.get_stats()

async def save_bot_state(state):
    await history_mgr.save_bot_state(state)

async def load_bot_state():
    return await history_mgr.load_bot_state()

async def clear_bot_state():
    await history_mgr.clear_bot_state()
