#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "A iniciar o CriptoEstratégia (MEXC Futuros 5x, dados reais, entradas fictícias)..."
echo "Dashboard: http://192.168.1.64:8050"
exec python3 main.py "$@"
