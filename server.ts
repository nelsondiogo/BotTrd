import express from "express";
import path from "path";
import { ExchangeManager } from "./src/lib/exchange-manager";
import { calculateIndicators, calculateScore } from "./src/lib/indicators";
import dotenv from "dotenv";
import cors from "cors";

dotenv.config();

const app = express();
const PORT = 3000;

const API_KEY = process.env.BYBIT_API_KEY || "";
const API_SECRET = process.env.BYBIT_API_SECRET || "";
const TESTNET = process.env.BYBIT_TESTNET === 'true';

let ex: ExchangeManager;
try {
  ex = new ExchangeManager(API_KEY, API_SECRET, TESTNET);
} catch (e) {
  console.error("[INIT] Falha ao inicializar ExchangeManager:", e);
  ex = new ExchangeManager("", "", TESTNET);
}

const botStatus = {
  isRunning: false,
  balance: 0,
  initialBalance: 0,
  currentPosition: null as any,
  lastScanLatency: 0,
  scanData: [] as any[],
  logs: [] as string[],
  peakProfit: 0,
  positionStartTime: 0
};

function addLog(msg: string) {
  const t = new Date().toLocaleTimeString();
  botStatus.logs.unshift(`[${t}] ${msg}`);
  if (botStatus.logs.length > 50) botStatus.logs.pop();
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
      if (pnlPct > botStatus.peakProfit) {
        botStatus.peakProfit = pnlPct;
      }

      if (botStatus.peakProfit > 0.5) { 
         const stopThreshold = botStatus.peakProfit * 0.85; 
         if (pnlPct < stopThreshold && pnlPct > 0) {
           addLog(`Trailing Stop Ativado! Pico: ${botStatus.peakProfit.toFixed(2)}%, Atual: ${pnlPct.toFixed(2)}%`);
           await ex.closePosition(activePos.symbol);
         }
      }

      const minutesActive = (Date.now() - botStatus.positionStartTime) / (1000 * 60);
      if (minutesActive > 30 && pnlPct < 0.15) {
        addLog(`Time Stop Ativado (30min). Fechando ${activePos.symbol}`);
        await ex.closePosition(activePos.symbol);
      }
    }

    if (!activePos) {
      const topPairs = tickers
        .sort((a, b) => (b.quoteVolume || 0) - (a.quoteVolume || 0))
        .slice(0, 15)
        .map(t => t.symbol);

      const scanResults = await Promise.all(topPairs.map(async (symbol) => {
        try {
          const [m5, h1] = await Promise.all([
            ex.fetchOHLCV(symbol, '5m', 100),
            ex.fetchOHLCV(symbol, '1h', 100)
          ]);

          const indM5 = calculateIndicators(m5);
          const indH1 = calculateIndicators(h1);
          const score = calculateScore(indM5, indH1);

          return { symbol, score, price: m5[m5.length - 1].close };
        } catch (e) { return null; }
      }));

      botStatus.scanData = scanResults.filter(Boolean);
      const validSignals = botStatus.scanData.filter(s => s.score >= 0.82).sort((a, b) => b.score - a.score);

      if (validSignals.length > 0) {
        const bestSignal = validSignals[0]!;
        addLog(`Sinal de Entrada: ${bestSignal.symbol} (Score: ${bestSignal.score.toFixed(2)})`);
        const amountUsdt = botStatus.balance * 0.1;
        const leverage = 10;
        const qty = (amountUsdt * leverage) / bestSignal.price;
        await ex.createOrder(bestSignal.symbol, 'buy', qty, leverage);
      }
    }

  } catch (error) {
    addLog(`Erro no Motor: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    botStatus.lastScanLatency = Date.now() - startTime;
    setTimeout(tradingLoop, 15000);
  }
}

async function startServer() {
  try {
    app.use(cors());
    app.use(express.json());

    app.get("/api/health", (req, res) => res.json({ ok: true }));
    app.get("/api/status", (req, res) => res.json(botStatus));
    app.post("/api/toggle", (req, res) => {
      botStatus.isRunning = !botStatus.isRunning;
      if (botStatus.isRunning) tradingLoop();
      res.json({ isRunning: botStatus.isRunning });
    });

    if (process.env.NODE_ENV !== "production") {
      const { createServer: createViteServer } = await import("vite");
      const vite = await createViteServer({
        server: { middlewareMode: true },
        appType: "spa",
      });
      app.use(vite.middlewares);
    } else {
      const distPath = path.join(process.cwd(), "dist");
      app.use(express.static(distPath));
      app.get("*", (req, res) => res.sendFile(path.join(distPath, "index.html")));
    }

    app.listen(PORT, "0.0.0.0", () => {
      console.log(`Server rodando em http://localhost:${PORT}`);
    });
  } catch (e) {
    console.error("Erro ao iniciar servidor:", e);
  }
}

startServer();
