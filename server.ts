// Trecho da lógica de atualização contínua
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
    console.error("[MARKET] Erro ao atualizar pares:", e);
  }
}

// Início do servidor com suporte a SPA
const distPath = path.resolve(process.cwd(), "dist");
app.use(express.static(distPath));
app.get("*", (req, res) => {
  res.sendFile(path.resolve(distPath, "index.html"));
});
