#!/bin/bash
set -e

# APENAS instala dependências (NÃO inicia o servidor!)
pip install --upgrade pip
pip install flask==3.0.3 requests==2.31.0 gunicorn==23.0.0
