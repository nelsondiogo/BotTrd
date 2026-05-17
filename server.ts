import express from "express";
import path from "path";
import { ExchangeManager } from "./src/lib/exchange-manager";
import { calculateIndicators, calculateScore } from "./src/lib/indicators";
import dotenv from "dotenv";
import cors from "cors";

dotenv.config();

const PORT = 3000;

// Estado do Bot
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

// ... (resto da lógica de logs e histórico)

async function startServer() {
  try {
    const app = express();
    app.use(cors());
    app.use(express.json());

    // Inicia o loop de trading imediatamente para tarefas de fundo
    tradingLoop();

    // API Routes
    app.get("/api/status", (req, res) => res.json(botStatus));
    
    // Configuração do Vite/Static Files
    if (process.env.NODE_ENV !== "production") {
      const { createServer: createViteServer } = await import("vite");
      const vite = await createViteServer({
        server: { middlewareMode: true },
        appType: "spa",
      });
      app.use(vite.middlewares);
    } else {
      const distPath = path.resolve(process.cwd(), "dist");
      app.use(express.static(distPath));
      app.get("*", (req, res) => {
        res.sendFile(path.resolve(distPath, "index.html"));
      });
    }

    app.listen(PORT, "0.0.0.0", () => {
      console.log(`[SERVER] Backend running at http://0.0.0.0:${PORT}`);
    });
  } catch (err) {
    console.error("[CRITICAL] Failed to start server:", err);
    process.exit(1);
  }
}

startServer();
