"""
Estratégia do vídeo: EMA 9 / EMA 20 no gráfico de 1 minuto — LONG e SHORT (futuros).

LONG  quando a EMA9 está acima da EMA20 e:
   A) cruzamento — a EMA9 acabou de cruzar para cima da EMA20 e a vela fecha acima da EMA9; ou
   B) pullback   — o preço recua à zona EMA9/EMA20, toca-a e fecha verde acima da EMA9.
SHORT é o espelho: EMA9 abaixo da EMA20, cruzamento para baixo ou pullback com vela vermelha.
Saída técnica: vela de 1m fecha do outro lado da EMA20 ou a EMA9 cruza contra a posição.
Filtros extra: inclinação da EMA20, RSI, volume, ATR mínimo (pagar taxas), preço não esticado
e (opcional) tendência do 15m a favor.
"""
import config as C
from indicators import atr, ema, rsi, sma

LONG, SHORT = "LONG", "SHORT"


def closed_only(candles, now_ms):
    return [c for c in candles if c["ct"] < now_ms]


def trend_filter(ktf):
    """Tendência do 15m: preço vs EMA50 e inclinação da EMA50."""
    if not ktf or len(ktf) < C.EMA_FILTRO + 5:
        return None
    closes = [c["c"] for c in ktf]
    e = ema(closes, C.EMA_FILTRO)
    return {"up": closes[-1] > e[-1] and e[-1] >= e[-4],
            "down": closes[-1] < e[-1] and e[-1] <= e[-4],
            "above_ema": closes[-1] > e[-1], "close": closes[-1], "ema": e[-1],
            "strength": (closes[-1] / e[-1] - 1) * 100}


def exit_signal(k1m, side):
    """Saída técnica do vídeo para a posição. Devolve motivo ou None."""
    if len(k1m) < C.EMA_LENTA + 3:
        return None
    c = [x["c"] for x in k1m]
    e9, e20 = ema(c, C.EMA_RAPIDA), ema(c, C.EMA_LENTA)
    if side == LONG:
        if e9[-2] >= e20[-2] and e9[-1] < e20[-1]:
            return "EMA9 CRUZOU ABAIXO EMA20"
        if c[-1] < e20[-1]:
            return "FECHO ABAIXO EMA20"
    else:
        if e9[-2] <= e20[-2] and e9[-1] > e20[-1]:
            return "EMA9 CRUZOU ACIMA EMA20"
        if c[-1] > e20[-1]:
            return "FECHO ACIMA EMA20"
    return None


def _side(side, o, h, l, c, v, e9, e20, r, atr_v, vavg, tf, ind):
    d = 1 if side == LONG else -1
    if C.FILTRO_TENDENCIA:
        if tf is None:
            return None, "histórico 15m insuficiente"
        if not (tf["up"] if side == LONG else tf["down"]):
            return None, "15m sem tendência a favor"
    if not d * (e9[-1] - e20[-1]) > 0:
        return None, "EMA9 do lado errado da EMA20"
    if not d * (e20[-1] - e20[-1 - C.INCLINACAO_VELAS]) > 0:
        return None, "EMA20 sem inclinação"
    cross = any(d * (e9[-i - 1] - e20[-i - 1]) <= 0 < d * (e9[-i] - e20[-i]) for i in (1, 2)) and d * (c[-1] - e9[-1]) > 0
    if side == LONG:
        zone = max(e9[-1], e20[-1]) * 1.0005
        pullback = min(l[-1], l[-2]) <= zone and c[-1] > e9[-1] and c[-1] > o[-1] and min(c[-4:-1]) > e20[-1] * 0.999
        rsi_ok = C.RSI_MIN <= r[-1] <= C.RSI_MAX
    else:
        zone = min(e9[-1], e20[-1]) * 0.9995
        pullback = max(h[-1], h[-2]) >= zone and c[-1] < e9[-1] and c[-1] < o[-1] and max(c[-4:-1]) < e20[-1] * 1.001
        rsi_ok = 100 - C.RSI_MAX <= r[-1] <= 100 - C.RSI_MIN
    if not (cross or pullback):
        return None, "sem gatilho (cruzamento/pullback)"
    if not rsi_ok:
        return None, "RSI fora do intervalo"
    vmin = C.VOLUME_MULT if cross and not pullback else C.VOLUME_MULT_PULLBACK
    if ind["vol_ratio"] < vmin:
        return None, "volume fraco"
    if not (C.ATR_PCT_MIN <= ind["atr_pct"] <= C.ATR_PCT_MAX):
        return None, "ATR% fora do intervalo (taxas/ruído)"
    if d * (c[-1] - e20[-1]) / atr_v > C.EXTENSAO_MAX_ATR:
        return None, "preço esticado vs EMA20"

    slope = d * (e20[-1] / e20[-1 - C.INCLINACAO_VELAS] - 1) * 100 / max(ind["atr_pct"], 1e-9)
    s_slope = min(max(slope / 0.6, 0), 1) * 25
    s_vol = min(max((ind["vol_ratio"] - 0.8) / 1.7, 0), 1) * 20
    s_rsi = max(1 - abs(r[-1] - (60 if side == LONG else 40)) / 15, 0) * 15
    s_tf = (min(max(d * tf["strength"] / 1.5, 0), 1) * 15) if tf else 7.5
    s_atr = min(max((ind["atr_pct"] - C.ATR_PCT_MIN) / 0.25, 0), 1) * 10
    s_trig = 15 if (cross and pullback) else 12 if pullback else 9
    score = round(s_slope + s_vol + s_rsi + s_tf + s_atr + s_trig, 1)
    trig = "cruzamento + pullback" if cross and pullback else "pullback EMA9/20" if pullback else "cruzamento EMA9/20"
    return {
        "side": side, "price": c[-1], "atr": atr_v, "score": score, "ema20": e20[-1],
        "swing": min(l[-5:]) if side == LONG else max(h[-5:]),
        "reason": f"{side} {trig} | RSI {r[-1]:.0f} | Vol {ind['vol_ratio']:.1f}x | ATR {ind['atr_pct']:.2f}%",
    }, None


def evaluate(k1m, ktf, allow_short=True):
    """Avalia um contrato nos dois sentidos. Devolve (sinal|None, motivo_rejeição, indicadores)."""
    if len(k1m) < 60:
        return None, "velas 1m insuficientes", {}
    o = [x["o"] for x in k1m]
    h = [x["h"] for x in k1m]
    l = [x["l"] for x in k1m]
    c = [x["c"] for x in k1m]
    v = [x["v"] for x in k1m]
    e9, e20 = ema(c, C.EMA_RAPIDA), ema(c, C.EMA_LENTA)
    r = rsi(c, C.RSI_PERIODO)
    a = atr(h, l, c, C.ATR_PERIODO)
    vavg = sma(v, 20)
    atr_v = a[-1]
    tf = trend_filter(ktf)
    ind = {
        "price": c[-1], "ema9": e9[-1], "ema20": e20[-1], "rsi": r[-1], "atr": atr_v,
        "atr_pct": atr_v / c[-1] * 100 if atr_v else None,
        "vol_ratio": v[-1] / vavg[-2] if vavg[-2] else None,
        "ema_spread_pct": (e9[-1] / e20[-1] - 1) * 100 if e20[-1] else None,
        "trend_15m": ("ALTA" if tf["up"] else "BAIXA" if tf["down"] else "LATERAL") if tf else None,
    }
    if None in (e9[-1], e20[-1], e20[-1 - C.INCLINACAO_VELAS], r[-1], atr_v, vavg[-2]) or not atr_v:
        return None, "indicadores incompletos", ind
    sides = [LONG, SHORT] if allow_short else [LONG]
    if tf and allow_short and tf["down"]:
        sides = [SHORT, LONG]
    best, why_first = None, None
    for s in sides:
        sig, why = _side(s, o, h, l, c, v, e9, e20, r, atr_v, vavg, tf, ind)
        if sig and (best is None or sig["score"] > best["score"]):
            best = sig
        if why_first is None:
            why_first = why
    if best:
        ind["score"] = best["score"]
        return best, None, ind
    return None, why_first, ind
