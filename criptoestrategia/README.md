# CriptoEstratégia — bot de paper trading nos Futuros da MEXC (5x)

Bot de criptomoedas com **entradas fictícias** (paper trading) nos **futuros perpétuos USDT da MEXC**, com **alavancagem de 5x** (margem isolada), long e short. Arranca com **100 USDT** e usa **só dados reais da MEXC Futuros**: contratos, livro de ofertas, velas, taxas e funding. A estratégia é a do vídeo: **gráfico de 1 minuto com EMA 9 e EMA 20**. Grava tudo em SQLite e inclui um **dashboard web completo** em **http://192.168.1.64:8050**.

> Não usa chaves de API e não envia ordens reais. Lê apenas dados públicos de `contract.mexc.com`.

## Arrancar com Docker (recomendado)

Precisas do Docker com o plugin Compose (Docker Desktop no Windows/Mac, ou Docker Engine no Linux).

```bash
cd criptoestrategia
docker compose up -d --build      # cria a imagem e arranca em segundo plano
docker compose logs -f            # ver o que o bot está a fazer
docker compose down               # parar
```

- Dashboard: **http://192.168.1.64:8050** (a partir de qualquer PC ou telemóvel na tua rede)
- A base de dados fica em `./data/criptoestrategia.db`, fora do contentor, e sobrevive a reinícios e atualizações.
- O contentor reinicia sozinho (`restart: unless-stopped`) depois de um reboot ou de uma falha.
- Para recomeçar do zero: `docker compose down`, apagar a pasta `data/` e voltar a fazer `docker compose up -d`.

**O IP está fixo no `docker-compose.yml`** (`"192.168.1.64:8050:8050"`). Se o IP do PC mudar, o contentor não arranca. Nesse caso troca para `"8050:8050"`, ou fixa o IP do PC no router (reserva DHCP).

> **Windows:** se outro PC da rede não conseguir abrir o dashboard, permite a porta 8050 na Firewall do Windows.

## Arrancar sem Docker

Precisas do Python 3.10 ou superior e não há dependências para instalar.

```bash
python main.py            # escuta em 0.0.0.0:8050 → http://192.168.1.64:8050
python main.py --reset    # apaga o histórico e recomeça com 100 USDT
python main.py --host 192.168.1.64 --port 8050
```

No Windows também podes dar duplo clique em `iniciar.bat`.

## Estratégia — EMA 9 / EMA 20 no 1 minuto (long e short)

| Etapa | Regra |
|---|---|
| **Universo** | De hora a hora: contratos perpétuos `*_USDT` ativos da MEXC, **só criptomoedas** (ações, ETFs, metais e forex ficam de fora), volume 24h ≥ 2M USDT, spread ≤ 0,10%, alavancagem máxima ≥ 5x. Do top 100 por volume escolhe os **50** com melhor score **60% rank de volume + 40% rank de volatilidade** |
| **LONG (vídeo)** | **EMA9 acima da EMA20** e EMA20 a subir · gatilho: **cruzamento para cima** (últimas 2 velas, vela fecha acima da EMA9) **ou pullback** à zona EMA9/EMA20 com vela verde |
| **SHORT (espelho)** | **EMA9 abaixo da EMA20** e EMA20 a descer · gatilho: **cruzamento para baixo** ou **pullback** com vela vermelha |
| **Filtros extra** | Volume ≥ 1,3× a média (cruzamento) / ≥ 0,8× (pullback) · RSI 50–75 (short 25–50) · ATR do 1m entre 0,08% e 1,5% · no máximo 2 ATR da EMA20 · tendência do 15m a favor (EMA50). `FILTRO_TENDENCIA = False` usa só o 1m, como no vídeo |
| **Score** | 0–100. Entra com ≥ 50, ou ≥ 65 contra a tendência do BTC (15m). Os melhores scores entram primeiro |
| **Alavancagem e margem** | **5x, margem isolada** · risco de 1% do equity por trade (0,5% contra o BTC) · margem máx. 20% do equity por posição e 80% no total · máx. 5 posições |
| **Contratos** | Quantidade arredondada a contratos inteiros com o **tamanho e mínimo reais** de cada contrato |
| **Stop loss** | Além do extremo das últimas 5 velas / EMA20 ± 0,5 ATR, sempre entre 0,4% e 1,5% |
| **TP1** | +1,5R (ordem limite): fecha **50%** e o SL passa para **breakeven** |
| **Trailing / TP2** | Depois do TP1: trailing a 2 ATR · TP2 a +3R (ordem limite) |
| **Saída técnica (vídeo)** | A vela de 1m fecha do outro lado da EMA20 ou a EMA9 cruza contra a posição |
| **Outras saídas** | Time stop aos 90 min · estagnação (30 min sem +0,5R) · **liquidação** (simulada se o preço chegar lá) · fecho manual |
| **Proteções** | Perda diária de 5% ⇒ pausa até às 00:00 UTC · drawdown de 30% ⇒ kill switch · cooldown de 10 min por contrato (30 min depois de uma perda) |
| **Custos reais** | Taxas taker/maker **de cada contrato** (lidas da MEXC) · compras ao **ask** e vendas ao **bid** (spread incluído) + 0,02% de slippage · **funding** real cobrado/recebido nas horas de liquidação de cada contrato |

Com 5x e SL entre 0,4% e 1,5%, a liquidação fica a cerca de 19% da entrada. O stop é sempre atingido muito antes.

Todos os parâmetros estão em `config.py`, comentados. Depois de os alterares, faz `docker compose up -d --build`.

## Dashboard

- **Visão geral:** equity, PnL total, realizado e flutuante, margem usada e disponível, exposição e alavancagem efetiva, win rate, profit factor, expectativa, drawdown, Sharpe/Sortino, curva de equity, drawdown, PnL diário e o motivo de rejeição de cada contrato no último scan
- **Posições:** lado, alavancagem, contratos, margem, PnL flutuante, **ROE**, R atual, SL/TP1/TP2, **preço de liquidação** e distância até ele, funding e botão de fecho
- **Histórico:** todos os trades (notional, margem, PnL, ROE, R, MFE/MAE, taxas, funding) e execuções, com exportação em CSV
- **Análise:** mais de 45 estatísticas, **long vs short**, R-múltiplos, motivos de saída, PnL por contrato, por hora e por dia da semana
- **Universo:** os 50 contratos com volume, volatilidade, spread, funding e taxas
- **Sinais**, **Registo** e **Estratégia**

> Não há login: os botões Pausar e Fechar ficam acessíveis a quem estiver na tua rede local. Não abras a porta 8050 no router para a internet.

## Base de dados (`data/criptoestrategia.db`)

| Tabela | Conteúdo |
|---|---|
| `trades` | Cada trade: lado, alavancagem, contratos, notional, margem, entrada, SL/TP, liquidação, risco (1R), **PnL flutuante**, PnL realizado, taxas, funding, saída, PnL final, %, **ROE**, R, MFE/MAE e duração |
| `fills` | Cada execução (ENTRADA, TP1, TP2, STOP LOSS, TRAILING, FECHO ABAIXO/ACIMA EMA20, FUNDING, LIQUIDAÇÃO…) com preço, quantidade, taxa, PnL e saldo depois |
| `equity` | Curva a cada 30 s: saldo, equity, margem usada, PnL flutuante e realizado, exposição e drawdown |
| `universe` | Os 50 contratos atuais, com spread, funding e taxas |
| `signals` | Sinais (long/short) e decisões, com os indicadores em JSON |
| `events` | Registo de eventos |
| `state` | Estado da conta |

## Ficheiros

```
Dockerfile, docker-compose.yml   execução em Docker
main.py        arranque (bot + dashboard)
config.py      todos os parâmetros
engine.py      motor de futuros: margem, contratos, long/short, liquidação, funding, saídas
strategy.py    regras EMA 9/20 (long e short) e score
indicators.py  EMA, RSI, ATR, MACD, ADX (Python puro)
exchange.py    API pública da MEXC Futuros (dados reais)
database.py    SQLite
stats.py       estatísticas
server.py      API do dashboard
static/        dashboard (HTML/CSS/JS + Chart.js)
```

## Avisos

- **A alavancagem amplifica ganhos e perdas.** No 1 minuto, taxas, spread e funding pesam muito: acompanha no dashboard as taxas pagas, o funding e a expectativa por trade.
- Avalia a estratégia com pelo menos 2–4 semanas de paper trading (mínimo de 100–200 trades) antes de pensar em capital real.
- O bot verifica preços a cada 3 s. Em movimentos bruscos, o preço de saída simulado pode ser pior do que o SL, tal como numa ordem real a mercado.
- Isto não é aconselhamento financeiro.
