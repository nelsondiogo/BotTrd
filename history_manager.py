import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List

HISTORY_FILE = 'history.json'
STATE_FILE = 'state.json'

class AsyncHistoryManager:
    def __init__(self):
        self._history_cache = None
        self._state_cache = None
        self._lock = asyncio.Lock()
        self._dirty = False
        self._last_save = 0
        self._save_interval = 10

    async def _load_history(self):
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

    async def _save_history(self, force=False):
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

    async def add_trade(self, symbol, side, entry, exit_price, pnl, reason, leverage=1, fees=0.0, duration_sec=0):
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
            if len(h['trades']) > 500:
                h['trades'] = h['trades'][-500:]
            self._dirty = True
        asyncio.create_task(self._save_history())

    async def get_history(self, limit=100):
        h = await self._load_history()
        if limit and len(h['trades']) > limit:
            h_copy = h.copy()
            h_copy['trades'] = h['trades'][-limit:]
            return h_copy
        return h

    async def get_recent_trades(self, n=5):
        h = await self._load_history()
        return h['trades'][-n:] if h['trades'] else []

    async def get_stats(self):
        h = await self._load_history()
        total = h['wins'] + h['losses']
        win_rate = (h['wins'] / total * 100) if total > 0 else 0
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

    async def save_bot_state(self, state):
        try:
            async with self._lock:
                self._state_cache = state
                with open(STATE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(state, f, indent=2, ensure_ascii=False, default=str)
        except Exception:
            pass

    async def load_bot_state(self):
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
        self._state_cache = None
        if os.path.exists(STATE_FILE):
            try:
                os.remove(STATE_FILE)
            except Exception:
                pass

    async def flush(self):
        await self._save_history(force=True)

history_mgr = AsyncHistoryManager()

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
