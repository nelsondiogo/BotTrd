#!/bin/bash
set -e

# Instala dependências
pip install --upgrade pip setuptools wheel

# Instala pandas (wheel pré-compilado para evitar compilação)
pip install --only-binary :all: pandas==2.2.3 || pip install pandas==2.2.3

# Instala restante das dependências
pip install -r requirements.txt

# Configuração do Gunicorn
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# Executa com configuração padrão (sem worker-class especial)
exec gunicorn app:app \
    --bind 0.0.0.0:$PORT \
    --workers 1 \
    --threads 4 \
    --timeout 120 \
    --preload \
    --access-logfile - \
    --error-logfile - \
    --log-level info
