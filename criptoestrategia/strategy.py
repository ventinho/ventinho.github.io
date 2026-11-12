"""
Estratégia: tendência no 1h + gatilho de pullback/cruzamento no 15m, com confirmação de
momentum (RSI, MACD), força de tendência (ADX) e volume. Long-only (spot).
"""
import config as C
from indicators import adx, atr, ema, macd, rsi, sma


def closed_only(candles, now_ms):
    return [c for c in candles if c["ct"] < now_ms]


def trend_1h(k1h):
    """Devolve dict com a tendência do 1h ou None se não houver velas suficientes."""
    if len(k1h) < C.EMA_TENDENCIA_LENTA + 5:
        return None
    closes = [c["c"] for c in k1h]
    e50, e200 = ema(closes, C.EMA_TENDENCIA_RAPIDA), ema(closes, C.EMA_TENDENCIA_LENTA)
    up = e50[-1] > e200[-1] and closes[-1] > e50[-1]
    return {"up": up, "close": closes[-1], "ema50": e50[-1], "ema200": e200[-1],
            "strength": (e50[-1] / e200[-1] - 1) * 100, "above_ema50": closes[-1] > e50[-1]}


def evaluate(k15, k1h):
    """Avalia um par. Devolve (sinal|None, motivo_rejeição, indicadores)."""
    if len(k15) < 60:
        return None, "velas 15m insuficientes", {}
    t1 = trend_1h(k1h)
    if t1 is None:
        return None, "histórico 1h insuficiente", {}

    o = [c["o"] for c in k15]
    h = [c["h"] for c in k15]
    l = [c["l"] for c in k15]
    c = [c["c"] for c in k15]
    v = [x["v"] for x in k15]
    e9, e21, e50 = ema(c, C.EMA_RAPIDA), ema(c, C.EMA_MEDIA), ema(c, C.EMA_LENTA)
    r = rsi(c, C.RSI_PERIODO)
    _, _, hist = macd(c)
    a = atr(h, l, c, C.ATR_PERIODO)
    dx = adx(h, l, c, C.ADX_PERIODO)
    vavg = sma(v, 20)

    price, atr_v = c[-1], a[-1]
    ind = {
        "price": price, "ema9": e9[-1], "ema21": e21[-1], "ema50": e50[-1], "rsi": r[-1],
        "macd_hist": hist[-1], "adx": dx[-1], "atr": atr_v, "atr_pct": atr_v / price * 100 if atr_v else None,
        "vol_ratio": v[-1] / vavg[-2] if vavg[-2] else None,  # vela atual vs média 20 anteriores
        "trend_1h": t1["up"], "trend_1h_strength": t1["strength"],
    }
    if None in (e9[-1], e21[-1], e50[-1], r[-1], hist[-1], hist[-2], dx[-1], atr_v, vavg[-2]):
        return None, "indicadores incompletos", ind

    # ── filtros ──
    if not t1["up"]:
        return None, "1h sem tendência de alta", ind
    if not (e9[-1] > e21[-1] > e50[-1]):
        return None, "EMAs 15m não alinhadas", ind
    cross = any(e9[-i - 1] <= e21[-i - 1] and e9[-i] > e21[-i] for i in range(1, 4))
    pullback = l[-1] <= e21[-1] * 1.003 and c[-1] > e21[-1] and c[-1] > o[-1]
    if not (cross or pullback):
        return None, "sem gatilho (cruzamento/pullback)", ind
    if not (C.RSI_MIN <= r[-1] <= C.RSI_MAX):
        return None, f"RSI fora de {C.RSI_MIN}-{C.RSI_MAX}", ind
    # momentum: no cruzamento exige histograma > 0 e a subir; no pullback basta virar para cima
    if not (hist[-1] > hist[-2] and (hist[-1] > 0 or pullback)):
        return None, "MACD sem momentum", ind
    if dx[-1] < C.ADX_MIN:
        return None, "ADX fraco", ind
    # volume: cruzamento precisa de participação forte; a vela de pullback é naturalmente mais calma
    vmin = C.VOLUME_MULT_PULLBACK if pullback else C.VOLUME_MULT
    if ind["vol_ratio"] < vmin:
        return None, "volume fraco", ind
    if not (C.ATR_PCT_MIN <= ind["atr_pct"] <= C.ATR_PCT_MAX):
        return None, "ATR% fora do intervalo", ind
    if (price - e21[-1]) / atr_v > C.EXTENSAO_MAX_ATR:
        return None, "preço esticado vs EMA21", ind

    # ── score 0–100 ──
    s_adx = min(max((dx[-1] - 20) / 25, 0), 1) * 25                 # força da tendência
    s_vol = min(max((ind["vol_ratio"] - 0.8) / 1.7, 0), 1) * 20       # participação
    s_rsi = (1 - abs(r[-1] - 60) / 10) * 15                           # RSI ideal ~60
    s_tr = min(max(t1["strength"] / 3, 0), 1) * 15                    # tendência 1h
    s_mac = min(max((hist[-1] - hist[-2]) / (atr_v * 0.05), 0), 1) * 10  # aceleração do momentum
    s_trig = 15 if (cross and pullback) else 10 if pullback else 8    # qualidade do gatilho
    score = round(s_adx + s_vol + max(s_rsi, 0) + s_tr + max(s_mac, 0) + s_trig, 1)
    ind["score"] = score

    swing_low = min(l[-5:])
    trig = "cruzamento EMA9/21 + pullback" if cross and pullback else "pullback EMA21" if pullback else "cruzamento EMA9/21"
    return {
        "price": price, "atr": atr_v, "swing_low": swing_low, "score": score,
        "reason": f"{trig} | RSI {r[-1]:.0f} | ADX {dx[-1]:.0f} | Vol {ind['vol_ratio']:.1f}x",
    }, None, ind
