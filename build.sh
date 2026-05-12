#!/bin/bash
set -e

# Instala dependências com cache
pip install --upgrade pip setuptools wheel

# Instala pandas de forma otimizada (evita compilação)
pip install --only-binary :all: pandas==2.2.3

# Instala restante das dependências
pip install -r requirements.txt

# Configuração do Gunicorn para async
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# Executa com worker otimizado para async
exec gunicorn app:app \
    --bind 0.0.0.0:$PORT \
    --workers 1 \
    --threads 2 \
    --timeout 120 \
    --preload \
    --worker-class aiohttp.GunicornWebWorker \
    --access-logfile - \
    --error-logfile - \
    --log-level info
