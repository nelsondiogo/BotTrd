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
const PORT = process.env.PORT || 3000;

app.use(express.json());

let botStatus = {
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
  console.log(`[BOT] ${msg}`);
}

async function recordTrade(symbol: string, side: string, type: 'ABERTURA' | 'FECHO', price: number, pnlPct?: number) {
  botStatus.history.unshift({
    timestamp: new Date().toISOString(),
    symbol,
    side,
    type,
    price,
    pnlPct
  });
}

const API_KEY = process.env.BYBIT_API_KEY || "";
const API_SECRET = process.env.BYBIT_API_SECRET || "";
const TESTNET = process.env.BYBIT_USE_TESTNET === "true";

let ex = new ExchangeManager(API_KEY, API_SECRET, TESTNET);

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
            addLog(`Trailing Stop: Fechando ${activePos.symbol} em ${pnlPct.toFixed(2)}%`);
            await ex.closePosition(activePos.symbol);
            recordTrade(activePos.symbol, activePos.side, 'FECHO', 0, pnlPct);
         }
      }
    }

    const tickersSorted = tickers.sort((a, b) => (b.quoteVolume || 0) - (a.quoteVolume || 0)).slice(0, 15);
    botStatus.activePairs = tickersSorted.map(t => t.symbol);

    const scanResults = await Promise.all(botStatus.activePairs.map(async (symbol) => {
       try {
         const [m5, h1] = await Promise.all([ex.fetchOHLCV(symbol, '5m', 100), ex.fetchOHLCV(symbol, '1h', 100)]);
         const m5Ind = calculateIndicators(m5.map(d => d[4]), m5.map(d => d[5]), m5.map(d => d[2]), m5.map(d => d[3]), m5.map(d => d[4]));
         const h1Ind = calculateIndicators(h1.map(d => d[4]), h1.map(d => d[5]), h1.map(d => d[2]), h1.map(d => d[3]), h1.map(d => d[4]));
         const h1Trend = h1Ind.ema9 > h1Ind.ema21 ? 'bull' : 'bear';
         const signal = calculateScore(m5Ind, h1Trend);
         return { symbol, score: signal.score, rsi: m5Ind.rsi, mfi: m5Ind.mfi, adx: m5Ind.adx, trend: h1Trend };
       } catch { return null; }
    }));

    botStatus.scanData = scanResults.filter(Boolean);
    const bestSignal = botStatus.scanData.filter(s => s.score >= 0.82).sort((a, b) => b.score - a.score)[0];

    if (bestSignal && !activePos) {
      addLog(`Entrada: ${bestSignal.symbol} Score: ${bestSignal.score.toFixed(2)}`);
      await ex.createOrder(bestSignal.symbol, 'buy', (botStatus.balance * 0.1 * 10) / (tickers.find(t => t.symbol === bestSignal.symbol)?.last || 1), 10);
      recordTrade(bestSignal.symbol, 'buy', 'ABERTURA', 0);
    }

  } catch (e) { console.error(e); }
  finally {
    botStatus.lastScanLatency = Date.now() - startTime;
    setTimeout(tradingLoop, 15000);
  }
}

app.get("/api/status", (req, res) => res.json(botStatus));
app.post("/api/toggle", (req, res) => {
  botStatus.isRunning = !botStatus.isRunning;
  if (botStatus.isRunning) tradingLoop();
  res.json({ isRunning: botStatus.isRunning });
});

async function start() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({ server: { middlewareMode: true }, appType: "spa" });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => res.sendFile(path.join(distPath, "index.html")));
  }
  app.listen(PORT, "0.0.0.0", () => console.log(`Rodando na porta ${PORT}`));
}
start();
