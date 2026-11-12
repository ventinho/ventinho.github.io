"""Indicadores técnicos em Python puro (sem dependências)."""


def sma(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    s = sum(values[:period])
    out[period - 1] = s / period
    for i in range(period, len(values)):
        s += values[i] - values[i - period]
        out[i] = s / period
    return out


def ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _wilder(values, period):
    """Média de Wilder; values pode ter None no início."""
    out = [None] * len(values)
    start = next((i for i, v in enumerate(values) if v is not None), None)
    if start is None or len(values) - start < period:
        return out
    prev = sum(values[start:start + period]) / period
    out[start + period - 1] = prev
    for i in range(start + period, len(values)):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def rsi(closes, period=14):
    if len(closes) <= period:
        return [None] * len(closes)
    gains, losses = [None], [None]
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = _wilder(gains, period), _wilder(losses, period)
    out = []
    for g, l in zip(ag, al):
        if g is None or l is None:
            out.append(None)
        elif l == 0:
            out.append(100.0)
        else:
            out.append(100 - 100 / (1 + g / l))
    return out


def true_range(highs, lows, closes):
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return tr


def atr(highs, lows, closes, period=14):
    return _wilder(true_range(highs, lows, closes), period)


def macd(closes, fast=12, slow=26, signal=9):
    ef, es = ema(closes, fast), ema(closes, slow)
    line = [a - b if a is not None and b is not None else None for a, b in zip(ef, es)]
    first = next((i for i, v in enumerate(line) if v is not None), None)
    sig = [None] * len(closes)
    if first is not None:
        s = ema(line[first:], signal)
        sig[first:] = s
    hist = [a - b if a is not None and b is not None else None for a, b in zip(line, sig)]
    return line, sig, hist


def adx(highs, lows, closes, period=14):
    n = len(closes)
    if n < period * 2 + 1:
        return [None] * n
    pdm, mdm = [None], [None]
    for i in range(1, n):
        up, dn = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
    tr = [None] + true_range(highs, lows, closes)[1:]
    str_, spdm, smdm = _wilder(tr, period), _wilder(pdm, period), _wilder(mdm, period)
    dx = []
    for t, p, m in zip(str_, spdm, smdm):
        if t is None or p is None or m is None or t == 0:
            dx.append(None)
            continue
        pdi, mdi = 100 * p / t, 100 * m / t
        dx.append(0.0 if pdi + mdi == 0 else 100 * abs(pdi - mdi) / (pdi + mdi))
    return _wilder(dx, period)
