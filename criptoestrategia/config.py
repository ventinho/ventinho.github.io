"""
Configuração do CriptoEstratégia — bot de paper trading (entradas fictícias) na MEXC.
Todos os parâmetros da estratégia, risco e gestão de posição estão aqui.
Altera à vontade e reinicia o bot.
"""

# ───────────────────────── Conta (fictícia) ─────────────────────────
CAPITAL_INICIAL = 100.0          # USDT
TAXA_TAKER = 0.0005              # 0,05% por lado (taxa spot taker MEXC; maker = 0%)
SLIPPAGE = 0.0005                # 0,05% de derrapagem simulada em ordens a mercado

# ───────────────────────── Universo de moedas ─────────────────────────
N_MOEDAS = 50                    # nº de pares no universo
VOLUME_MIN_24H = 2_000_000       # USDT mínimos de volume 24h para entrar no universo
PRE_FILTRO_TOP_VOLUME = 150      # pré-seleção: top N por volume antes de pontuar volatilidade
PESO_VOLUME = 0.6                # score = 0,6·rank(volume) + 0,4·rank(volatilidade)
PESO_VOLATILIDADE = 0.4
VOLATILIDADE_MAX_24H = 80.0      # % (high-low)/low — acima disto é pump/dump, excluir
ATUALIZAR_UNIVERSO_H = 4         # recalcular o top 50 a cada X horas
EXCLUIR_BASES = {
    "USDC", "USDT", "FDUSD", "TUSD", "DAI", "USDE", "USD1", "PYUSD", "BUSD", "USDP",
    "EUR", "EURC", "EURT", "GBP", "BRL", "TRY", "XAUT", "PAXG", "USDD", "FRAX", "RLUSD",
}
EXCLUIR_SUFIXOS = ("3L", "3S", "5L", "5S", "2L", "2S", "UP", "DOWN", "BULL", "BEAR")

# ───────────────────────── Timeframes ─────────────────────────
TF_ENTRADA = "15m"               # gatilho de entrada
TF_TENDENCIA = "60m"             # filtro de tendência (na MEXC o 1h chama-se "60m")
VELAS_ENTRADA = 200
VELAS_TENDENCIA = 250

# ───────────────────────── Estratégia (long-only, spot) ─────────────────────────
# Seguidor de tendência com entrada em pullback/cruzamento:
#  1h: EMA50 > EMA200 e preço > EMA50 (tendência de alta)
#  15m: EMA9 > EMA21 > EMA50, cruzamento recente EMA9/21 OU pullback à EMA21 com vela verde,
#       RSI entre 50 e 70, ADX >= 20, histograma MACD a subir (e > 0 no cruzamento),
#       volume >= 1,2× média no cruzamento / >= 0,8× no pullback.
EMA_RAPIDA, EMA_MEDIA, EMA_LENTA = 9, 21, 50
EMA_TENDENCIA_RAPIDA, EMA_TENDENCIA_LENTA = 50, 200
RSI_PERIODO, RSI_MIN, RSI_MAX = 14, 50, 70
ADX_PERIODO, ADX_MIN = 14, 20
ATR_PERIODO = 14
VOLUME_MULT = 1.2                # volume mínimo (× média 20) no gatilho de cruzamento
VOLUME_MULT_PULLBACK = 0.8       # ... e no gatilho de pullback (vela de recuo é mais calma)
ATR_PCT_MIN, ATR_PCT_MAX = 0.25, 6.0   # ATR% do preço (fora disto: moeda morta ou louca)
EXTENSAO_MAX_ATR = 1.5           # não comprar se o preço estiver > 1,5 ATR acima da EMA21
SCORE_MIN = 55                   # score mínimo do sinal (0–100)
SCORE_MIN_MERCADO_BAIXA = 70     # score mínimo quando o BTC está em baixa no 1h

# ───────────────────────── Gestão de risco ─────────────────────────
RISCO_POR_TRADE = 0.01           # arrisca 1% do equity por trade (distância até ao SL)
RISCO_MERCADO_BAIXA = 0.005      # metade do risco quando o BTC está abaixo da EMA50 1h
MAX_POSICAO_PCT = 0.25           # máx. 25% do equity numa única posição
MAX_POSICOES = 5                 # máx. de posições abertas em simultâneo
NOTIONAL_MIN = 5.0               # USDT mínimos por ordem
PERDA_DIARIA_MAX = 0.05          # -5% no dia (UTC) => pausa novas entradas até amanhã
DRAWDOWN_MAX = 0.30              # -30% desde o pico => kill switch (deixa de abrir trades)
COOLDOWN_MIN = 60                # minutos sem voltar a entrar na mesma moeda após sair
COOLDOWN_PERDA_MIN = 180         # ... ou após uma perda

# ───────────────────────── Saídas ─────────────────────────
SL_ATR_MULT = 1.5                # SL = entrada − 1,5·ATR (ou abaixo do mínimo das últimas 5 velas)
SL_PCT_MIN, SL_PCT_MAX = 0.010, 0.06   # SL sempre entre 1% e 6% da entrada
TP1_R = 1.5                      # TP1 a 1,5R: vende 50% e passa o SL para breakeven
TP1_FRACAO = 0.5
TP2_R = 3.0                      # TP2 a 3R: vende o resto
TRAILING_ATR_MULT = 2.0          # depois do TP1: trailing stop = máximo − 2·ATR
TIME_STOP_H = 48                 # fecha qualquer trade aberto há mais de 48h
ESTAGNACAO_H = 12                # após 12h sem atingir +0,5R e sem TP1 => fecha
ESTAGNACAO_R = 0.5

# ───────────────────────── Ciclo do bot ─────────────────────────
INTERVALO_LOOP_S = 10            # verificação de preços/SL/TP a cada 10s
SNAPSHOT_EQUITY_S = 60           # gravar a curva de equity a cada 60s
WORKERS_HTTP = 8                 # pedidos paralelos à API da MEXC

MEXC_BASE = "https://api.mexc.com"
DB_PATH = "criptoestrategia.db"
PORTA_DASHBOARD = 8050
