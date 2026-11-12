#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "A iniciar o CriptoEstratégia (dados reais da MEXC, entradas fictícias)..."
exec python3 main.py "$@"
