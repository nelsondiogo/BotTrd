#!/bin/bash
set -e

# Atualiza pip
pip install --upgrade pip setuptools wheel

# Instala dependências SEM compilação (usa wheels pré-compilados)
pip install flask==3.0.3 ccxt==4.3.78 pandas==2.2.3 numpy==1.26.4 gunicorn==23.0.0 aiohttp==3.9.5 aiofiles==23.2.1

# Configuração
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# Executa
exec gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 --preload
