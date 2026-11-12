"""
Configuração do CriptoEstratégia — bot de paper trading (entradas fictícias) nos FUTUROS da MEXC.
Todos os parâmetros da estratégia, risco e gestão de posição estão aqui.
Altera à vontade e reinicia o bot.
"""

# ───────────────────────── Conta (fictícia) — Futuros perpétuos USDT-M ─────────────────────────
CAPITAL_INICIAL = 100.0          # USDT
ALAVANCAGEM = 5                  # 5x, margem isolada
PERMITIR_SHORT = True            # futuros: abre shorts quando a tendência é de baixa
# As taxas reais de cada contrato são lidas da MEXC (takerFeeRate/makerFeeRate).
# Estes valores só são usados se a API não as devolver.
TAXA_TAKER = 0.0002              # 0,02% — ordens a mercado (entrada, stop, saídas técnicas)
TAXA_MAKER = 0.0                 # 0% — ordens limite (TP1/TP2)
SLIPPAGE = 0.0002                # 0,02% extra de derrapagem/latência nas ordens a mercado
# Ordens a mercado: compras ao ASK real e vendas ao BID real (livro de ofertas da MEXC),
# por isso o spread já está incluído no custo. O funding é cobrado/recebido nas horas reais de cada contrato.

# ───────────────────────── Universo de moedas ─────────────────────────
N_MOEDAS = 50                    # nº de pares no universo
VOLUME_MIN_24H = 2_000_000       # USDT mínimos de volume 24h no contrato de futuros
PRE_FILTRO_TOP_VOLUME = 100      # pré-seleção: top N por volume antes de pontuar volatilidade
SPREAD_MAX_PCT = 0.10            # exclui contratos com spread bid/ask > 0,10% (no 1m o spread come o lucro)
PESO_VOLUME = 0.6                # score = 0,6·rank(volume) + 0,4·rank(volatilidade)
PESO_VOLATILIDADE = 0.4
VOLATILIDADE_MAX_24H = 80.0      # % (high-low)/low — acima disto é pump/dump, excluir
ATUALIZAR_UNIVERSO_H = 1         # recalcular o top 50 a cada hora
EXCLUIR_BASES = {
    "USDC", "USDT", "FDUSD", "TUSD", "DAI", "USDE", "USD1", "PYUSD", "BUSD", "USDP",
    "EUR", "EURC", "EURT", "GBP", "BRL", "TRY", "XAUT", "PAXG", "USDD", "FRAX", "RLUSD",
    "GOLD", "SILVER", "XAG", "XAU", "USDQ", "USDR", "USTC", "BFUSD", "USDF", "USDS", "USDG", "USDX",
}
EXCLUIR_SUFIXOS = ("3L", "3S", "5L", "5S", "2L", "2S", "UP", "DOWN", "BULL", "BEAR")

# ───────────────────────── Timeframes ─────────────────────────
TF_ENTRADA = "1m"                # estratégia do vídeo: gráfico de 1 minuto
TF_TENDENCIA = "15m"             # filtro de tendência superior (pode ser desligado)
VELAS_ENTRADA = 120
VELAS_TENDENCIA = 100

# ───────────────────────── Estratégia EMA 9 / EMA 20 no 1m (long-only, spot) ─────────────────────────
# Núcleo (vídeo): EMA9 acima da EMA20 = tendência de alta (LONG); EMA9 abaixo da EMA20 = baixa (SHORT).
#   Gatilho A — cruzamento: a EMA9 cruza a EMA20 (últimas 2 velas) e a vela fecha do lado certo da EMA9.
#   Gatilho B — pullback: o preço volta à zona EMA9/EMA20, toca-a e fecha a favor (vela verde/vermelha).
# Saída técnica (vídeo): vela de 1m fecha do outro lado da EMA20 ou a EMA9 cruza contra a posição.
# Filtros extra (trader): inclinação da EMA20, RSI, volume, volatilidade suficiente para pagar as taxas,
#   preço não esticado e tendência do 15m a favor. Regras espelhadas para os shorts.
EMA_RAPIDA, EMA_LENTA = 9, 20
INCLINACAO_VELAS = 3             # EMA20 tem de estar acima de há 3 velas (a subir)
RSI_PERIODO, RSI_MIN, RSI_MAX = 14, 50, 75   # LONG; no SHORT usa o espelho (25–50)
ATR_PERIODO = 14
VOLUME_MULT = 1.3                # volume mínimo (× média 20) no gatilho de cruzamento
VOLUME_MULT_PULLBACK = 0.8       # ... e no gatilho de pullback
ATR_PCT_MIN, ATR_PCT_MAX = 0.08, 1.5   # ATR% do 1m: abaixo disto o movimento não paga as taxas
EXTENSAO_MAX_ATR = 2.0           # não comprar se o preço estiver > 2 ATR acima da EMA20
FILTRO_TENDENCIA = True          # LONG só com 15m acima da EMA50 (SHORT só abaixo). False = só o 1m, como no vídeo
EMA_FILTRO = 50
SCORE_MIN = 50                   # score mínimo do sinal (0–100)
SCORE_MIN_CONTRA_BTC = 65        # score mínimo quando o trade vai contra a tendência do BTC (15m vs EMA50)

# ───────────────────────── Gestão de risco ─────────────────────────
RISCO_POR_TRADE = 0.01           # arrisca 1% do equity por trade (distância até ao SL)
RISCO_CONTRA_BTC = 0.005         # metade do risco quando o trade vai contra a tendência do BTC
MAX_MARGEM_POSICAO_PCT = 0.20    # máx. 20% do equity como margem por posição (= 100% de notional a 5x)
MAX_MARGEM_TOTAL_PCT = 0.80      # máx. 80% do equity usado como margem no total
MAX_POSICOES = 5                 # máx. de posições abertas em simultâneo
NOTIONAL_MIN = 5.0               # USDT mínimos por ordem
PERDA_DIARIA_MAX = 0.05          # -5% no dia (UTC) => pausa novas entradas até amanhã
DRAWDOWN_MAX = 0.30              # -30% desde o pico => kill switch (deixa de abrir trades)
COOLDOWN_MIN = 10                # minutos sem voltar a entrar na mesma moeda após sair
COOLDOWN_PERDA_MIN = 30          # ... ou após uma perda

# ───────────────────────── Saídas ─────────────────────────
SL_ATR_BUFFER = 0.5              # SL = mínimo(últimas 5 velas, EMA20) − 0,5·ATR  (short: máximo + 0,5·ATR)
SL_PCT_MIN, SL_PCT_MAX = 0.004, 0.015  # SL sempre entre 0,4% e 1,5% (tem de ficar longe das taxas)
TP1_R = 1.5                      # TP1 a 1,5R: vende 50% (ordem limite) e passa o SL para breakeven
TP1_FRACAO = 0.5
TP2_R = 3.0                      # TP2 a 3R: vende o resto (ordem limite)
TRAILING_ATR_MULT = 2.0          # depois do TP1: trailing stop = máximo − 2·ATR
SAIDA_EMA = True                 # fecha se a vela de 1m fechar abaixo da EMA20 ou a EMA9 cruzar para baixo
TIME_STOP_MIN = 90               # fecha qualquer trade aberto há mais de 90 minutos
ESTAGNACAO_MIN = 30              # após 30 min sem atingir +0,5R e sem TP1 => fecha
ESTAGNACAO_R = 0.5

# ───────────────────────── Ciclo do bot ─────────────────────────
INTERVALO_LOOP_S = 3             # verificação de preços/SL/TP a cada 3s
ATRASO_SCAN_S = 2                # espera 2s após o fecho da vela de 1m antes de pedir as velas
SNAPSHOT_EQUITY_S = 30           # gravar a curva de equity a cada 30s
WORKERS_HTTP = 6                 # pedidos paralelos à API da MEXC

MEXC_FUTUROS_BASE = "https://contract.mexc.com"
PEDIDOS_POR_SEGUNDO = 8          # limite da API pública de futuros: 20 pedidos / 2 s
DB_PATH = "criptoestrategia.db"
HOST_DASHBOARD = "0.0.0.0"       # todas as interfaces: abre em http://192.168.1.64:8050 na tua rede
PORTA_DASHBOARD = 8050
