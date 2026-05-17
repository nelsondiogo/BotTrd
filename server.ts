import express from "express";
import path from "path";
import { ExchangeManager } from "./src/lib/exchange-manager";
import { calculateIndicators, calculateScore } from "./src/lib/indicators";
import dotenv from "dotenv";
import cors from "cors";

dotenv.config();

const PORT = 3000;

// Bot State
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

let ex: ExchangeManager;
try {
  ex = new ExchangeManager(API_KEY, API_SECRET, TESTNET);
} catch (e) {
  console.error("[INIT] Falha ao inicializar ExchangeManager:", e);
  ex = new ExchangeManager("", "", TESTNET);
}

// --- TRADING ENGINE ---
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

    // Lógica de Saída (Trailing Stop & Time Stop)
    if (activePos) {
      const pnlPct = parseFloat(activePos.percentage || '0');
      if (pnlPct > botStatus.peakProfit) botStatus.peakProfit = pnlPct;

      if (botStatus.peakProfit > 0.5) { 
         const stopThreshold = botStatus.peakProfit * 0.85; // Drop 15% from profit peak
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
        addLog(`Time Stop: 30min sem lucro expressivo. Fechando em ${pnlPct.toFixed(2)}%`);
        const lastPrice = tickers.find((t: any) => t.symbol === activePos.symbol)?.last || 0;
        await ex.closePosition(activePos.symbol);
        recordTrade(activePos.symbol, activePos.side, 'FECHO', lastPrice, pnlPct);
      }
    }

    // Market Scan
    const topPairs = tickers
      .sort((a, b) => (b.quoteVolume || 0) - (a.quoteVolume || 0))
      .slice(0, 15)
      .map(t => ({ symbol: t.symbol, volume: t.quoteVolume, lastPrice: t.last }));

    botStatus.activePairs = topPairs as any;

    const scanResults = await Promise.all(topPairs.map(async (p: any) => {
       try {
         const symbol = p.symbol;
         const [m5, h1] = await Promise.all([ex.fetchOHLCV(symbol, '5m', 100), ex.fetchOHLCV(symbol, '1h', 100)]);
         const parse = (data: any[]) => ({ close: data.map(d => d[4]), high: data.map(d => d[2]), low: data.map(d => d[3]), volume: data.map(d => d[5]) });
         const m5Data = parse(m5);
         const h1Data = parse(h1);
         const m5Ind = calculateIndicators(m5Data.close, m5Data.volume, m5Data.high, m5Data.low, m5Data.close);
         const h1Ind = calculateIndicators(h1Data.close, h1Data.volume, h1Data.high, h1Data.low, h1Data.close);
         const h1Trend = h1Ind.ema9 > h1Ind.ema21 ? 'bull' : 'bear';
         const signal = calculateScore(m5Ind, h1Trend);
         return { symbol, score: signal.score, rsi: m5Ind.rsi, mfi: m5Ind.mfi, adx: m5Ind.adx, trend: h1Trend };
       } catch { return null; }
    }));

    botStatus.scanData = scanResults.filter(Boolean);
    const validSignals = botStatus.scanData.filter(s => s.score >= 0.82).sort((a, b) => b.score - a.score);

    // Entrada de Trade
    if (validSignals.length > 0) {
      const bestSignal = validSignals[0]!;
      if (!activePos) {
        addLog(`Sinal de Entrada: ${bestSignal.symbol} (Score: ${bestSignal.score.toFixed(2)})`);
        const amountUsdt = botStatus.balance * 0.1;
        const ticker = (tickers as any[]).find((t: any) => t.symbol === bestSignal.symbol);
        if (ticker && ticker.last) {
          const qty = (amountUsdt * 10) / ticker.last;
          await ex.createOrder(bestSignal.symbol, 'buy', qty, 10);
          recordTrade(bestSignal.symbol, 'buy', 'ABERTURA', ticker.last);
        }
      }
    }

  } catch (error) {
    addLog(`Erro no Motor: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    botStatus.lastScanLatency = Date.now() - startTime;
    setTimeout(tradingLoop, 15000);
  }
}

// Server Setup
async function startServer() {
  const app = express();
  app.use(cors());
  app.use(express.json());

  app.get("/api/status", (req, res) => res.json(botStatus));
  app.post("/api/toggle", (req, res) => {
    botStatus.isRunning = !botStatus.isRunning;
    if (botStatus.isRunning) tradingLoop();
    res.json({ isRunning: botStatus.isRunning });
  });

  app.post("/api/close", async (req, res) => {
    try {
      const positions = (await ex.client.fetchPositions()) as any[];
      const activePos = positions.find(p => parseFloat(p.contracts || '0') > 0);
      if (activePos) {
        const lastPrice = (await ex.fetchTickers() as any[]).find((t: any) => t.symbol === activePos.symbol)?.last || 0;
        await ex.closePosition(activePos.symbol);
        recordTrade(activePos.symbol, activePos.side, 'FECHO', lastPrice, parseFloat(activePos.percentage || '0'));
        addLog(`Fecho Manual: ${activePos.symbol}`);
        botStatus.currentPosition = null;
        res.json({ success: true });
      } else res.status(400).json({ error: "Nenhuma posição ativa." });
    } catch { res.status(500).json({ error: "Falha ao fechar." }); }
  });

  // Proxy Vite ou Static Files
  if (process.env.NODE_ENV !== "production") {
    const { createServer: createViteServer } = await import("vite");
    const vite = await createViteServer({ server: { middlewareMode: true }, appType: "spa" });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => res.sendFile(path.join(distPath, "index.html")));
  }

  app.listen(PORT, "0.0.0.0", () => console.log(`[SERVER] Rodando em http://0.0.0.0:${PORT}`));
}

startServer();
