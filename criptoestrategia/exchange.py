"""
Fontes de dados de mercado.
 - MexcClient: API pública spot v3 da MEXC (sem chaves; só leitura de preços/velas).
 - SimMarket : mercado sintético acelerado para testar o bot/dashboard sem internet (--demo).
Velas devolvidas como dicts: {t, o, h, l, c, v, ct} (t/ct em ms).
"""
import json
import math
import random
import time
import urllib.error
import urllib.parse
import urllib.request

import config

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
               "60m": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


class MexcClient:
    name = "MEXC (dados reais)"
    demo = False

    def __init__(self, base=config.MEXC_BASE):
        self.base = base

    def now_ms(self):
        return int(time.time() * 1000)

    def sleep(self, seconds):
        time.sleep(seconds)

    def _get(self, path, params=None, retries=3):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        last = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "criptoestrategia-paperbot/1.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (400, 404):
                    break
                time.sleep(1.5 * (attempt + 1))
            except Exception as e:  # rede
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"MEXC {path} falhou: {last}")

    def tickers_24h(self):
        data = self._get("/api/v3/ticker/24hr")
        out = []
        for d in data:
            try:
                out.append({
                    "symbol": d["symbol"],
                    "last": float(d["lastPrice"]),
                    "high": float(d["highPrice"]),
                    "low": float(d["lowPrice"]),
                    "change_pct": (float(d["lastPrice"]) / float(d["openPrice"]) - 1) * 100
                    if float(d.get("openPrice") or 0) > 0 else 0.0,
                    "quote_volume": float(d.get("quoteVolume") or 0),
                })
            except (TypeError, ValueError, KeyError):
                continue
        return out

    def prices(self):
        data = self._get("/api/v3/ticker/price")
        return {d["symbol"]: float(d["price"]) for d in data if d.get("price")}

    def klines(self, symbol, interval, limit):
        data = self._get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        step = INTERVAL_MS[interval]
        return [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
                 "c": float(k[4]), "v": float(k[5]),
                 "ct": int(k[6]) if len(k) > 6 and k[6] else int(k[0]) + step - 1} for k in data]


class SimMarket:
    """Mercado sintético: 70 pares com passeio aleatório + regimes de tendência.
    Cada chamada a sleep() avança o relógio simulado SIM_MIN_POR_PASSO minutos."""
    name = "DEMO (mercado simulado)"
    demo = True
    SIM_MIN_POR_PASSO = 1
    PAUSA_REAL_S = 0.02

    def __init__(self, seed=42, n=70):
        self.rng = random.Random(seed)
        start = int(time.time() // 900 * 900 * 1000) - 1100 * 900_000
        self.t = start
        self.sym = {}
        bases = ["BTC", "ETH", "SOL", "XRP", "DOGE", "PEPE", "SUI", "WIF", "TON", "ADA", "AVAX", "LINK", "TRX",
                 "DOT", "NEAR", "APT", "ARB", "OP", "INJ", "TIA", "SEI", "FET", "RNDR", "BONK", "FLOKI", "SHIB",
                 "LTC", "BCH", "ATOM", "FIL", "ICP", "HBAR", "ENA", "JUP", "PYTH", "STRK", "WLD", "ORDI", "AAVE",
                 "UNI", "MKR", "LDO", "CRV", "GALA", "SAND", "MANA", "AXS", "IMX", "BLUR", "MEME", "NOT", "PEOPLE",
                 "TAO", "KAS", "ONDO", "ETHFI", "ZRO", "BOME", "POPCAT", "MEW", "TURBO", "BRETT", "MOG", "AERO",
                 "VIRTUAL", "AI16Z", "TRUMP", "HYPE", "MOVE", "PENGU"][:n]
        for i, b in enumerate(bases):
            price = 10 ** self.rng.uniform(-5, 4.8) if b != "BTC" else 90000.0
            vol = self.rng.uniform(0.0012, 0.0045) if b != "BTC" else 0.0010   # vol por minuto
            self.sym[b + "USDT"] = {"p": price, "vol": vol, "drift": 0.0, "regime_left": 0,
                                    "liq": 10 ** self.rng.uniform(6.3, 9.5), "c15": [], "cur": None}
        # pré-história de 1100 velas de 15m
        for s in self.sym:
            for _ in range(1100):
                self._candle_15m(s, self.t + len(self.sym[s]["c15"]) * 900_000)
        self.t = start + 1100 * 900_000
        for s in self.sym:
            self._open_cur(s)

    def _step_price(self, d):
        if d["regime_left"] <= 0:
            d["drift"] = self.rng.choice([-1, 0, 0, 1, 1]) * self.rng.uniform(0.0, 0.06) * d["vol"]
            d["regime_left"] = self.rng.randint(240, 2400)
        d["regime_left"] -= 1
        shock = self.rng.gauss(0, d["vol"])
        if self.rng.random() < 0.0008:
            shock += self.rng.choice([-1, 1]) * d["vol"] * self.rng.uniform(5, 15)
        d["p"] *= math.exp(d["drift"] + shock)
        return d["p"]

    def _candle_15m(self, s, t):
        d = self.sym[s]
        o = d["p"]
        h = l = o
        for _ in range(15):
            p = self._step_price(d)
            h, l = max(h, p), min(l, p)
        v = d["liq"] / 96 / o * self.rng.lognormvariate(0, 0.45) * (0.7 + 0.3 * abs(d["p"] / o - 1) / (d["vol"] * 4))
        d["c15"].append({"t": t, "o": o, "h": h, "l": l, "c": d["p"], "v": v, "ct": t + 899_999})

    def _open_cur(self, s):
        d = self.sym[s]
        d["cur"] = {"t": self.t, "o": d["p"], "h": d["p"], "l": d["p"], "c": d["p"],
                    "v": 0.0, "ct": self.t + 899_999, "n": 0, "m": self.rng.lognormvariate(0, 0.45)}

    def now_ms(self):
        return self.t

    def sleep(self, seconds):
        time.sleep(self.PAUSA_REAL_S)
        for _ in range(self.SIM_MIN_POR_PASSO):
            self.t += 60_000
            for s, d in self.sym.items():
                cur = d["cur"]
                prev = d["p"]
                p = self._step_price(d)
                cur["h"], cur["l"], cur["c"] = max(cur["h"], p), min(cur["l"], p), p
                ret = abs(p / prev - 1) / d["vol"]
                cur["v"] += d["liq"] / 1440 / p * cur["m"] * (0.6 + 0.4 * ret * ret)
                cur["n"] += 1
                if cur["n"] >= 15:
                    cur.pop("n"); cur.pop("m")
                    d["c15"].append(cur)
                    if len(d["c15"]) > 1300:
                        del d["c15"][:100]
                    self._open_cur(s)

    def prices(self):
        return {s: d["p"] for s, d in self.sym.items()}

    def tickers_24h(self):
        out = []
        for s, d in self.sym.items():
            last = d["c15"][-96:]
            hi, lo = max(c["h"] for c in last), min(c["l"] for c in last)
            out.append({"symbol": s, "last": d["p"], "high": hi, "low": lo,
                        "change_pct": (d["p"] / last[0]["o"] - 1) * 100,
                        "quote_volume": sum(c["v"] * c["c"] for c in last)})
        return out

    def klines(self, symbol, interval, limit):
        d = self.sym[symbol]
        c15 = d["c15"] + [dict(d["cur"])]
        if interval == "15m":
            return [dict(c) for c in c15[-limit:]]
        if interval == "60m":
            hours = {}
            for c in c15:
                ht = c["t"] // 3_600_000 * 3_600_000
                h = hours.get(ht)
                if h is None:
                    hours[ht] = {"t": ht, "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"],
                                 "v": c["v"], "ct": ht + 3_599_999}
                else:
                    h["h"], h["l"], h["c"], h["v"] = max(h["h"], c["h"]), min(h["l"], c["l"]), c["c"], h["v"] + c["v"]
            return list(hours.values())[-limit:]
        raise ValueError(interval)
