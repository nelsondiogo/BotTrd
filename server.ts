import express from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { ExchangeManager } from "./src/lib/exchange-manager";
import { calculateIndicators, calculateScore } from "./src/lib/indicators";
import dotenv from "dotenv";
import cors from "cors";

dotenv.config();

const app = express();
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
    symbol, side, type, price, pnlPct
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
    
    botStatus.currentPosition = activePos || null;

    // Lógica de Trailing Stop e Execução omitida aqui por brevidade, 
    // mas presente no arquivo original completo.
    
  } catch (error) {
    addLog(`Erro no Motor: ${error}`);
  } finally {
    botStatus.lastScanLatency = Date.now() - startTime;
    setTimeout(tradingLoop, 15000);
  }
}

app.use(cors());
app.use(express.json());

app.get("/api/status", (req, res) => res.json(botStatus));
app.post("/api/toggle", (req, res) => {
  botStatus.isRunning = !botStatus.isRunning;
  if (botStatus.isRunning) tradingLoop();
  res.json({ isRunning: botStatus.isRunning });
});

if (process.env.NODE_ENV !== "production") {
  const vite = await createViteServer({ server: { middlewareMode: true }, appType: "spa" });
  app.use(vite.middlewares);
} else {
  const distPath = path.join(process.cwd(), "dist");
  app.use(express.static(distPath));
  app.get("*", (req, res) => res.sendFile(path.join(distPath, "index.html")));
}

app.listen(PORT, "0.0.0.0", () => console.log(`Server running on port ${PORT}`));
