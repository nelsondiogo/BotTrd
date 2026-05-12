#!/bin/bash
set -e

# Força Python 3.12 (compatível com pandas 2.2.3)
export PYTHON_VERSION=3.12.6

# Instala dependências
pip install --upgrade pip setuptools wheel

# Instala pandas com wheel pré-compilado
pip install --only-binary :all: pandas==2.2.3

# Instala restante das dependências
pip install -r requirements.txt

# Configuração do Gunicorn
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# Executa com worker otimizado
exec gunicorn app:app \
    --bind 0.0.0.0:$PORT \
    --workers 1 \
    --threads 2 \
    --timeout 120 \
    --preload \
    --access-logfile - \
    --error-logfile - \
    --log-level info
