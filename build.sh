#!/bin/bash
set -e

# Instalação rápida sem compilação
pip install --no-cache-dir --upgrade pip
pip install --no-cache-dir flask ccxt pandas numpy gunicorn aiohttp aiofiles

# Executa
exec gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
