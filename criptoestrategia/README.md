# CriptoEstratégia — bot de paper trading na MEXC

Bot de criptomoedas com **entradas fictícias** (paper trading). Arranca com **100 USDT**, usa **preços reais da MEXC** e grava tudo numa base de dados SQLite. Inclui um **dashboard web completo**.

> Não usa chaves de API e não envia ordens reais. Lê apenas dados públicos de mercado.

## Instalação no ambiente de trabalho

1. Instala o **Python 3.10 ou superior** (https://www.python.org/downloads/). No Windows, marca *"Add Python to PATH"*.
2. Copia esta pasta `criptoestrategia` para o ambiente de trabalho.
3. Arranca o bot:
   - **Windows:** duplo clique em `iniciar.bat`
   - **Mac/Linux:** `./iniciar.sh` ou `python3 main.py`
4. O dashboard abre sozinho em **http://localhost:8050**.

Não há dependências para instalar: o bot usa só a biblioteca padrão do Python, e o Chart.js já vem incluído em `static/`.

```
python main.py            # dados reais da MEXC (deixa o PC ligado)
python main.py --demo     # mercado simulado e acelerado, para ver o bot e o dashboard em ação
python main.py --reset    # apaga o histórico e recomeça com 100 USDT
python main.py --port 9000
```

O modo real grava em `criptoestrategia.db` e o modo demo em `demo_criptoestrategia.db`. As duas bases de dados nunca se misturam.

## Estratégia

| Etapa | Regra |
|---|---|
| **Universo** | De 4 em 4 horas: pares USDT com volume 24h ≥ 2M, sem stablecoins, tokens alavancados nem moedas com variação > 80%. Do top 150 por volume escolhe os **50** com melhor score **60% rank de volume + 40% rank de volatilidade** |
| **Tendência (1h)** | EMA50 > EMA200 e preço > EMA50 |
| **Gatilho (15m, vela fechada)** | EMA9 > EMA21 > EMA50 e (cruzamento EMA9/21 nas últimas 3 velas **ou** pullback à EMA21 com vela verde) |
| **Confirmações** | RSI 50–70 · ADX ≥ 20 · MACD a acelerar (> 0 no cruzamento) · volume ≥ 1,2× a média (cruzamento) ou ≥ 0,8× (pullback) · ATR entre 0,25% e 6% · preço no máximo 1,5 ATR acima da EMA21 |
| **Score** | 0–100 (ADX, volume, RSI, tendência 1h, momentum, gatilho). Entra com score ≥ 55, ou ≥ 70 se o BTC estiver abaixo da EMA50 1h. Os melhores scores entram primeiro |
| **Tamanho da posição** | Risco de **1% do equity** por trade (0,5% com o BTC em baixa). Máximo de 25% do equity por posição e de **5 posições** em simultâneo. Mínimo de 5 USDT por ordem |
| **Stop loss** | Entrada − 1,5 ATR (ou abaixo do mínimo das últimas 5 velas), sempre entre 1% e 6% |
| **TP1** | +1,5R: vende **50%** e o SL passa para **breakeven** |
| **Trailing** | Depois do TP1: máximo − 2 ATR |
| **TP2** | +3R: vende o resto |
| **Outras saídas** | Time stop às 48h · estagnação (12h sem chegar a +0,5R) · tendência 1h quebrou antes do TP1 · fecho manual no dashboard |
| **Proteções** | Perda diária de 5% ⇒ sem novas entradas até às 00:00 UTC · drawdown de 30% ⇒ kill switch · cooldown de 60 min por moeda (180 min depois de uma perda) |
| **Custos** | Taxa taker de 0,05% por lado + slippage de 0,05% |

Todos os parâmetros estão em `config.py`, comentados.

## Dashboard

- **Visão geral:** equity, PnL total, realizado e flutuante, win rate, profit factor, expectativa, drawdown, Sharpe/Sortino, sequências, curva de equity, drawdown, PnL diário e o último scan (com o motivo de rejeição de cada par)
- **Posições:** PnL flutuante em tempo real, R atual, SL/TP1/TP2, barra SL↔alvo e botão de fecho manual
- **Histórico:** todos os trades com MFE/MAE, taxas e motivo de entrada/saída, todas as execuções e exportação em CSV
- **Análise:** mais de 35 estatísticas, distribuição de R-múltiplos, motivos de saída, PnL por moeda, por hora e por dia da semana
- **Universo:** o top 50 atual com volume, volatilidade e variação 24h
- **Sinais:** cada sinal detetado e a decisão tomada (entrou ou foi ignorado, e porquê)
- **Registo / Estratégia:** eventos do bot e parâmetros ativos
- **Controlos:** Pausar, Retomar (também limpa o kill switch) e Fechar tudo

## Base de dados (`criptoestrategia.db`)

| Tabela | Conteúdo |
|---|---|
| `trades` | Cada trade: entrada, SL/TP, risco (1R), score, regime, máximo/mínimo, **PnL flutuante**, PnL realizado, taxas, saída, PnL final, %, R, MFE/MAE e duração |
| `fills` | Cada execução (ENTRADA, TP1, TP2, STOP LOSS, TRAILING…) com preço, quantidade, taxa, PnL e cash depois |
| `equity` | Curva de equity de minuto a minuto: cash, equity, PnL flutuante e realizado, exposição e drawdown |
| `universe` | O top 50 atual |
| `signals` | Sinais e decisões, com os indicadores em JSON |
| `events` | Registo de eventos |
| `state` | Estado da conta (cash, pico, pausa, kill switch…) |

Podes abrir a base de dados com o [DB Browser for SQLite](https://sqlitebrowser.org/) ou exportar CSV no dashboard.

## Ficheiros

```
main.py        arranque (bot + dashboard)
config.py      todos os parâmetros
engine.py      motor: universo, scan, entradas, gestão de posições e proteções
strategy.py    regras de entrada e score
indicators.py  EMA, RSI, ATR, MACD, ADX (Python puro)
exchange.py    API pública da MEXC + mercado simulado (--demo)
database.py    SQLite
stats.py       estatísticas
server.py      API do dashboard
static/        dashboard (HTML/CSS/JS + Chart.js)
```

## Avisos

- Os resultados do modo `--demo` vêm de um mercado **sintético** e não dizem nada sobre o desempenho real. Avalia a estratégia com pelo menos 2–4 semanas de paper trading em dados reais (mínimo de 50–100 trades) antes de pensar em capital real.
- O bot verifica preços a cada 10 s. Em movimentos bruscos, o preço de saída simulado pode ser pior do que o SL, tal como numa ordem real a mercado.
- Isto não é aconselhamento financeiro.
