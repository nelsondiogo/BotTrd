Dockerfile
# Dockerfile para nd-bot v8.2
# Usa imagem slim para build rápido

FROM python:3.12-slim

# Instala dependências do sistema necessárias
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Define diretório de trabalho
WORKDIR /app

# Copia requirements primeiro (para cache de layers)
COPY requirements.txt .

# Instala dependências Python
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copia o restante do código
COPY . .

# Expõe a porta
EXPOSE 10000

# Comando de inicialização
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "1", "--threads", "4", "--timeout", "120", "--preload"]
