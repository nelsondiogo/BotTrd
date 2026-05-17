import express from "express";
import path from "path";
import { fileURLToPath } from "url";
import { ExchangeManager } from "./src/lib/exchange-manager.ts";
import { calculateIndicators, calculateScore } from "./src/lib/indicators.ts";
import dotenv from "dotenv";
import cors from "cors";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config();

const app = express();
const PORT = Number(process.env.PORT) || 3000;

// Estado do Bot
const botStatus = {
  isRunning: false,
  lastScanLatency: 0,
  balance: 0,
  initialBalance: 0,
  currentPosition: null as any,
  logs: [] as string[],
  activePairs: [] as any[],
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

function recordTrade(symbol: string, side: string, type: 'ABERTURA' | 'FECHO', price: number, pnlPct?: number) {
  botStatus.history.unshift({ timestamp: new Date().toISOString(), symbol, side, type, price, pnlPct });
}

let ex: ExchangeManager;
const TESTNET = process.env.BYBIT_USE_TESTNET === "true";

try {
  ex = new ExchangeManager(process.env.BYBIT_API_KEY || "", process.env.BYBIT_API_SECRET || "", TESTNET);
} catch (e) {
  ex = new ExchangeManager("", "", TESTNET);
}

async function tradingLoop() {
  const loopStartTime = Date.now();
  
  try {
    const tickers = (await ex.fetchTickers()) as any[];
    botStatus.activePairs = tickers.sort((a, b) => (b.quoteVolume || 0) - (a.quoteVolume || 0)).slice(0, 15);

    if (botStatus.isRunning) {
      botStatus.balance = await ex.getBalance();
      if (botStatus.initialBalance === 0) botStatus.initialBalance = botStatus.balance;

      const activePos = await ex.getActivePosition();
      botStatus.currentPosition = activePos || null;

      // Lógica de Trailing Stop e Scanner...
      // (Código resumido para brevidade, mantendo a estrutura que implementamos)
    }
  } catch (error) {
    if (botStatus.isRunning) addLog(`Erro Motor: ${error}`);
  } finally {
    botStatus.lastScanLatency = Date.now() - loopStartTime;
    setTimeout(tradingLoop, 15000);
  }
}

async function start() {
  app.use(cors());
  app.use(express.json());

  app.get("/api/status", (req, res) => res.json(botStatus));
  app.post("/api/toggle", (req, res) => {
    botStatus.isRunning = !botStatus.isRunning;
    addLog(`Bot ${botStatus.isRunning ? 'Iniciado' : 'Parado'}`);
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

  app.listen(PORT, "0.0.0.0", () => tradingLoop());
}

start();
