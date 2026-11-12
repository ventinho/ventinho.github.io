@echo off
cd /d "%~dp0"
echo A iniciar o CriptoEstrategia (MEXC Futuros 5x, dados reais, entradas ficticias)...
echo Dashboard: http://192.168.1.64:8050
python main.py %*
if errorlevel 1 py main.py %*
pause
