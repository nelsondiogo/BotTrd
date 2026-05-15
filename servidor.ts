import express from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { ExchangeManager } from "./src/lib/exchange-manager";
import { calculateIndicators, calculateScore } from "./src/lib/indicators";
import dotenv from "dotenv";
import cors from "cors";

dotenv.config();

const app = express();
app.use(cors());
app.use(express.json());

const PORT = 3000;
const API_KEY = process.env.BYBIT_API_KEY || "";
const API_SECRET = process.env.BYBIT_API_SECRET || "";
const TESTNET = process.env.BYBIT_USE_TESTNET === "true";

const botStatus = {
  isRunning: false,
  lastScanLatency: 0,
  balance: 0,
  initialBalance: 0,
  currentPosition: null as any,
  logs: [] as string[],
  activePairs: [] as string[],
  scanData: [] as any[],
  peakProfit: 0,
  positionStartTime: 0,
  history: [] as any[],
};

function addLog(msg: string) {
  const timestamp = new Date().toLocaleTimeString('pt-PT');
  botStatus.logs.unshift(`[${timestamp}] ${msg}`);
  if (botStatus.logs.length > 50) botStatus.logs.pop();
}

async function recordTrade(symbol: string, side: string, type: 'ABERTURA' | 'FECHO', price: number, pnlPct?: number) {
  botStatus.history.unshift({
    timestamp: new Date().toISOString(),
    symbol, side, type, price, pnlPct
  });
}

let ex: ExchangeManager;
try {
  ex = new ExchangeManager(API_KEY, API_SECRET, TESTNET);
} catch (e) {
  ex = new ExchangeManager("", "", TESTNET);
}

async function tradingLoop() {
  if (!botStatus.isRunning) return;
  const startTime = Date.now();

  try {
    botStatus.balance = await ex.getBalance();
    if (botStatus.initialBalance === 0) botStatus.initialBalance = botStatus.balance;

    const positions = (await ex.client.fetchPositions()) as any[];
    const activePos = positions.find(p => parseFloat(p.contracts || '0') > 0);
    const tickers = (await ex.fetchTickers()) as any[];
    
    if (activePos && !botStatus.currentPosition) {
      botStatus.positionStartTime = Date.now();
      botStatus.peakProfit = 0;
    }
    botStatus.currentPosition = activePos || null;

    if (activePos) {
      const pnlPct = parseFloat(activePos.percentage || '0');
      if (pnlPct > botStatus.peakProfit) botStatus.peakProfit = pnlPct;

      if (botStatus.peakProfit > 0.5) { 
         const stopThreshold = botStatus.peakProfit * 0.85;
         if (pnlPct < stopThreshold && pnlPct > 0) {
           addLog(`Trailing Stop Ativado! Pico: ${botStatus.peakProfit.toFixed(2)}%, Atual: ${pnlPct.toFixed(2)}%`);
           const lastPrice = tickers.find((t: any) => t.symbol === activePos.symbol)?.last || 0;
           await ex.closePosition(activePos.symbol);
           recordTrade(activePos.symbol, activePos.side, 'FECHO', lastPrice, pnlPct);
           botStatus.peakProfit = 0;
         }
      }

      const minutesActive = (Date.now() - botStatus.positionStartTime) / (1000 * 60);
      if (minutesActive > 30 && pnlPct < 0.15) {
        addLog(`Time Stop Ativado (30min). Fechando ${activePos.symbol}`);
        const lastPrice = tickers.find((t: any) => t.symbol === activePos.symbol)?.last || 0;
        await ex.closePosition(activePos.symbol);
        recordTrade(activePos.symbol, activePos.side, 'FECHO', lastPrice, pnlPct);
      }
    }

    const topPairs = tickers.sort((a, b) => (b.quoteVolume || 0) - (a.quoteVolume || 0)).slice(0, 15).map(t => t.symbol);
    botStatus.activePairs = topPairs;

    const scanResults = await Promise.all(topPairs.map(async (symbol) => {
       try {
         const [m5, h1] = await Promise.all([ex.fetchOHLCV(symbol, '5m', 100), ex.fetchOHLCV(symbol, '1h', 100)]);
         const m5Ind = calculateIndicators(m5.map(d => d[4]));
         const h1Ind = calculateIndicators(h1.map(d => d[4]));
         const h1Trend = h1Ind.ema9 > h1Ind.ema21 ? 'bull' : 'bear';
         const signal = calculateScore(m5Ind, h1Trend);
         return { symbol, score: signal.score, rsi: m5Ind.rsi, mfi: m5Ind.mfi, adx: m5Ind.adx, trend: h1Trend };
       } catch (e) { return null; }
    }));

    botStatus.scanData = scanResults.filter(Boolean) as any[];
    const validSignals = botStatus.scanData.filter(s => s.score >= 0.82).sort((a,b) => b.score - a.score);

    if (validSignals.length > 0) {
      const bestSignal = validSignals[0];
      if (!activePos) {
        addLog(`Sinal de Entrada: ${bestSignal.symbol} (${bestSignal.score.toFixed(2)})`);
        const ticker = tickers.find((t: any) => t.symbol === bestSignal.symbol);
        if (ticker?.last) {
          const qty = (botStatus.balance * 0.1 * 10) / ticker.last;
          await ex.createOrder(bestSignal.symbol, 'buy', qty, 10);
          recordTrade(bestSignal.symbol, 'buy', 'ABERTURA', ticker.last);
        }
      }
    }
  } catch (error) {
    addLog(`Erro: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    botStatus.lastScanLatency = Date.now() - startTime;
    if (botStatus.isRunning) setTimeout(tradingLoop, 15000);
  }
}

// Rotas API
app.get("/api/status", (req, res) => res.json(botStatus));
app.post("/api/toggle", (req, res) => {
  botStatus.isRunning = !botStatus.isRunning;
  if (botStatus.isRunning) { addLog("Bot Iniciado"); tradingLoop(); }
  else { addLog("Bot Parado"); }
  res.json({ isRunning: botStatus.isRunning });
});

app.post("/api/config", (req, res) => {
  const { apiKey, apiSecret } = req.body;
  const newEx = new ExchangeManager(apiKey, apiSecret, TESTNET);
  newEx.getBalance().then(() => {
     ex.client = newEx.client;
     addLog("API atualizada com sucesso.");
     res.json({ success: true });
  }).catch(() => res.status(400).json({ error: "Chaves inválidas." }));
});

// Setup Vite/Static
if (process.env.NODE_ENV !== "production") {
  const vite = await createViteServer({ server: { middlewareMode: true }, appType: "spa" });
  app.use(vite.middlewares);
} else {
  app.use(express.static(path.join(process.cwd(), 'dist')));
  app.get('*', (req, res) => res.sendFile(path.join(process.cwd(), 'dist', 'index.html')));
}

app.listen(PORT, "0.0.0.0", () => console.log(`[SERVER] Ativo na porta ${PORT}`));
