import express from "express";
import path from "path";
import { ExchangeManager } from "./src/lib/exchange-manager";
import { calculateIndicators, calculateScore } from "./src/lib/indicators";
import dotenv from "dotenv";
import cors from "cors";

dotenv.config();
const PORT = 3000;

let botStatus = {
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

// ... (lógica de logs e trade record igual)

async function updateMarketData() {
  try {
    const tickers = (await ex.fetchTickers()) as any[];
    botStatus.activePairs = tickers
      .sort((a, b) => (b.quoteVolume || 0) - (a.quoteVolume || 0))
      .slice(0, 15)
      .map(t => ({ symbol: t.symbol, volume: t.quoteVolume, lastPrice: t.last }));
  } catch (e) { console.error("Erro mercado:", e); }
}

async function tradingLoop() {
  await updateMarketData();
  if (!botStatus.isRunning) {
    setTimeout(tradingLoop, 15000);
    return;
  }
  // ... (restante da lógica do motor quant)
}

async function startServer() {
  const app = express();
  app.use(cors());
  app.use(express.json());
  
  tradingLoop(); // Inicia logo para ter dados

  // Rotas API...
  app.get("/api/status", (req, res) => res.json(botStatus));
  // ... (outras rotas API)

  // CORREÇÃO PARA RENDER: Caminhos absolutos e fallback SPA
  const distPath = path.resolve(process.cwd(), "dist");
  if (process.env.NODE_ENV === "production") {
    app.use(express.static(distPath));
    app.get("*", (req, res) => res.sendFile(path.resolve(distPath, "index.html")));
  } else {
    // Vite middleware para dev
  }

  app.listen(PORT, "0.0.0.0", () => console.log(`Rodando na porta ${PORT}`));
}
startServer();
