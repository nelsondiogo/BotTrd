import express from "express";
import path from "path";
import cors from "cors";
import dotenv from "dotenv";
import { createServer as createViteServer } from "vite";
import { ExchangeManager } from "./src/lib/exchange-manager.js";
import { analyzeMarket } from "./src/lib/indicators.js";

dotenv.config();

const PORT = 3000;
const TESTNET = true;

// Estado Global do Bot
let botStatus = {
  isRunning: false,
  currentPosition: null,
  lastScanLatency: 0,
  activePairs: ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT"],
  logs: [] as string[],
  peakProfit: 0,
  positionStartTime: 0,
  scanData: [] as any[]
};

const addLog = (msg: string) => {
  const time = new Date().toLocaleTimeString();
  botStatus.logs.unshift(`[${time}] ${msg}`);
  if (botStatus.logs.length > 50) botStatus.logs.pop();
};

// Inicialização da Exchange (Bybit)
let ex = new ExchangeManager("", "", TESTNET);

async function tradingLoop() {
  if (!botStatus.isRunning) return;

  const startTime = Date.now();
  try {
    const results = [];
    for (const symbol of botStatus.activePairs) {
      const ohlcv = await ex.fetchOHLCV(symbol, '15m', 100);
      const analysis = analyzeMarket(ohlcv);
      results.push({ symbol, ...analysis });
    }
    
    botStatus.scanData = results;
    botStatus.lastScanLatency = Date.now() - startTime;

    // Lógica simplificada de entrada
    if (!botStatus.currentPosition) {
      const bestSignal = results.sort((a,b) => b.score - a.score)[0];
      if (bestSignal && bestSignal.score > 0.85) {
        botStatus.currentPosition = {
          symbol: bestSignal.symbol,
          entryPrice: bestSignal.close,
          markPrice: bestSignal.close,
          contracts: "10",
          side: bestSignal.trend === 'bull' ? 'buy' : 'sell'
        };
        botStatus.positionStartTime = Date.now();
        addLog(`SINAL FORTE: Entrando em ${bestSignal.symbol} (${bestSignal.trend})`);
      }
    } else {
      // Simulação de Mark Price
      botStatus.currentPosition.markPrice = results.find(r => r.symbol === botStatus.currentPosition.symbol)?.close || botStatus.currentPosition.markPrice;
    }

  } catch (e: any) {
    addLog(`Erro loop: ${e.message}`);
  }

  setTimeout(tradingLoop, 15000);
}

const app = express();
app.use(cors());
app.use(express.json());

// API Routes
app.get("/api/status", (req, res) => res.json(botStatus));

app.post("/api/toggle", (req, res) => {
  botStatus.isRunning = !botStatus.isRunning;
  addLog(botStatus.isRunning ? "Bot Iniciado" : "Bot Parado");
  if (botStatus.isRunning) tradingLoop();
  res.json({ isRunning: botStatus.isRunning });
});

app.post("/api/config", async (req, res) => {
  const { apiKey, apiSecret } = req.body;
  try {
    const tester = new ExchangeManager(apiKey, apiSecret, TESTNET);
    await tester.getBalance();
    ex = tester;
    addLog("Credenciais validadas com sucesso.");
    res.json({ success: true });
  } catch (e) {
    res.status(400).json({ error: "Credenciais inválidas." });
  }
});

async function startServer() {
  if (process.env.NODE_ENV !== "production") {
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
    console.log(`Server running at http://0.0.0.0:${PORT}`);
  });
}

startServer();
