import express from "express";
import path from "path";
import cors from "cors";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI } from "@google/genai";

// Configuração do Mock Exchange ou Real (Adaptado para Bybit se necessário)
const ex = {
  client: {
    fetchBalance: async () => ({ total: { USDT: 1540.25 } }),
    fetchPositions: async () => [],
  },
  fetchTickers: async () => [],
  fetchOHLCV: async (s: string, i: string, l: number) => [],
  createOrder: async (s: string, t: string, side: string, a: number) => ({ id: '123' }),
  closePosition: async (s: string) => ({ status: 'closed' })
};

const botStatus = {
  isRunning: false,
  balance: 1540.25,
  currentPosition: null as any,
  logs: [] as string[],
  trades: [] as any[],
  activePairs: [] as any[],
  scanData: [] as any[],
  peakProfit: 0,
  positionStartTime: 0
};

function addLog(msg: string) {
  const time = new Date().toLocaleTimeString();
  botStatus.logs.unshift(`[${time}] ${msg}`);
  if (botStatus.logs.length > 50) botStatus.logs.pop();
  console.log(`[BOT] ${msg}`);
}

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
    setTimeout(tradingLoop, 15000); // Continua monitorando mercado mesmo parado
    return;
  }

  try {
    // Lógica de Trading aqui...
    // Scalping, Trailing Stop, etc.
  } catch (e) {
    addLog(`Erro Loop: ${String(e)}`);
  }
  
  setTimeout(tradingLoop, 15000);
}

const app = express();
app.use(cors());
app.use(express.json());

// Inicia o motor do bot imediatamente
tradingLoop();

app.get("/api/status", (req, res) => res.json(botStatus));

app.post("/api/toggle", (req, res) => {
  botStatus.isRunning = !botStatus.isRunning;
  addLog(botStatus.isRunning ? "Bot Iniciado" : "Bot Parado");
  res.json({ isRunning: botStatus.isRunning });
});

app.post("/api/close", async (req, res) => {
  try {
    // Lógica para fechar posição ativa via API da corretora
    botStatus.currentPosition = null;
    addLog("Fecho Manual executado com sucesso");
    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ error: "Falha ao fechar" });
  }
});

// Configuração para Produção (Render)
if (process.env.NODE_ENV === "production") {
  const distPath = path.resolve(process.cwd(), "dist");
  app.use(express.static(distPath));
  app.get("*", (req, res) => {
    res.sendFile(path.resolve(distPath, "index.html"));
  });
} else {
  // Configuração Vite Dev Server...
}

app.listen(3000, "0.0.0.0", () => console.log("Servidor rodando na porta 3000"));
