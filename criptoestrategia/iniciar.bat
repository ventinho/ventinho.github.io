@echo off
cd /d "%~dp0"
echo A iniciar o CriptoEstrategia (dados reais da MEXC, entradas ficticias)...
python main.py %*
if errorlevel 1 py main.py %*
pause
