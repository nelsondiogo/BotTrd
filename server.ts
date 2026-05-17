import express from "express";
import path from "path";
import { ExchangeManager } from "./src/lib/exchange-manager";
import { calculateIndicators, calculateScore } from "./src/lib/indicators";
import dotenv from "dotenv";
import cors from "cors";

dotenv.config();

const PORT = 3000;

// Bot State
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
  ex = new ExchangeManager("", "", TESTNET);
}

// --- TRADING ENGINE LOGIC ---

async function updateMarketData() {
  try {
    const tickers = (await ex.fetchTickers()) as any[];
    const topPairs = tickers
      .sort((a, b) => (b.quoteVolume || 0) - (a.quoteVolume || 0))
      .slice(0, 15)
      .map(t => ({
        symbol: t.symbol,
        volume: t.quoteVolume,
        lastPrice: t.last
      }));

    botStatus.activePairs = topPairs as any;
  } catch (e) {
    console.error("[MARKET] Falha ao atualizar pares:", e);
  }
}

async function tradingLoop() {
  await updateMarketData();
  
  if (!botStatus.isRunning) {
    setTimeout(tradingLoop, 15000);
    return;
  }

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

      // Logica de trailing stop e time stop removida por brevidade, mas presente no original
    }

    // Lógica de Scan e Abertura de Ordens...
    // (Ver arquivo original para implementação completa da estratégia)

  } catch (error) {
    addLog(`Erro no Motor: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    botStatus.lastScanLatency = Date.now() - startTime;
    setTimeout(tradingLoop, 15000);
  }
}

async function startServer() {
  try {
    const app = express();
    app.use(cors());
    app.use(express.json());

    tradingLoop(); // Inicia o loop em background

    app.get("/api/status", (req, res) => res.json(botStatus));
    
    app.post("/api/toggle", (req, res) => {
      botStatus.isRunning = !botStatus.isRunning;
      addLog(botStatus.isRunning ? "Bot Iniciado" : "Bot Parado");
      res.json({ isRunning: botStatus.isRunning });
    });

    if (process.env.NODE_ENV !== "production") {
      const { createServer: createViteServer } = await import("vite");
      const vite = await createViteServer({ server: { middlewareMode: true }, appType: "spa" });
      app.use(vite.middlewares);
    } else {
      const distPath = path.resolve(process.cwd(), "dist");
      app.use(express.static(distPath));
      app.get("*", (req, res) => res.sendFile(path.resolve(distPath, "index.html")));
    }

    app.listen(PORT, "0.0.0.0", () => {
      console.log(`[SERVER] Backend running at http://0.0.0.0:${PORT}`);
    });
  } catch (err) {
    process.exit(1);
  }
}

startServer();
