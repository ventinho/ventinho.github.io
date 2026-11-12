"""
Dados de mercado reais dos FUTUROS perpétuos USDT-M da MEXC (API pública contract.mexc.com).
Sem chaves de API: só leitura de contratos, tickers (bid/ask), velas e funding.
Símbolos no formato da MEXC Futuros: BTC_USDT. Velas devolvidas como dicts {t, o, h, l, c, v, ct} (ms).
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import config

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
               "60m": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
INTERVAL_MEXC = {"1m": "Min1", "5m": "Min5", "15m": "Min15", "30m": "Min30",
                 "60m": "Min60", "4h": "Hour4", "1d": "Day1"}


class MexcFutures:
    name = "MEXC Futuros (dados reais)"
    demo = False

    def __init__(self, base=config.MEXC_FUTUROS_BASE):
        self.base = base
        self._lock = threading.Lock()
        self._next = 0.0
        self._gap = 1.0 / config.PEDIDOS_POR_SEGUNDO

    def now_ms(self):
        return int(time.time() * 1000)

    def sleep(self, seconds):
        time.sleep(seconds)

    def _throttle(self):
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            self._next = max(now, self._next) + self._gap
        if wait > 0:
            time.sleep(wait)

    def _get(self, path, params=None, retries=3):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        last = None
        for attempt in range(retries):
            self._throttle()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "criptoestrategia-paperbot/2.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read().decode())
                if isinstance(data, dict) and data.get("success") is False:
                    raise RuntimeError(f"code {data.get('code')}: {data.get('message')}")
                return data.get("data") if isinstance(data, dict) and "data" in data else data
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (400, 404):
                    break
                time.sleep(1.5 * (attempt + 1))
            except Exception as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"MEXC {path} falhou: {last}")

    def ping(self):
        return self._get("/api/v1/contract/ping", retries=2)

    def contracts(self):
        """Especificações de todos os contratos: tamanho, mínimo, alavancagem, taxas, margem de manutenção."""
        out = {}
        for d in self._get("/api/v1/contract/detail"):
            try:
                out[d["symbol"]] = {
                    "symbol": d["symbol"], "base": d.get("baseCoin", ""), "quote": d.get("quoteCoin", ""),
                    "contract_size": float(d["contractSize"]), "min_vol": float(d.get("minVol") or 1),
                    "vol_unit": float(d.get("volUnit") or 1), "price_unit": float(d.get("priceUnit") or 0),
                    "max_leverage": float(d.get("maxLeverage") or 0),
                    "taker": float(d["takerFeeRate"]) if d.get("takerFeeRate") is not None else config.TAXA_TAKER,
                    "maker": float(d["makerFeeRate"]) if d.get("makerFeeRate") is not None else config.TAXA_MAKER,
                    "mmr": float(d.get("maintenanceMarginRate") or 0.005),
                    "active": d.get("state") == 0 and d.get("apiAllowed", True) and not d.get("isHidden", False),
                    "type": d.get("futureType", 1),
                    # ações, ETFs, índices, metais, forex (tradfi) ficam de fora — só criptomoedas
                    "tradfi": any(p.lower().endswith(("tradfi", "stock", "metals", "commodities", "forex", "etf"))
                                  for p in d.get("conceptPlate") or []),
                }
            except (TypeError, ValueError, KeyError):
                continue
        return out

    def tickers(self):
        """Tickers de todos os contratos: último preço, bid/ask, volume 24h em USDT, máx/mín, funding."""
        out = {}
        for d in self._get("/api/v1/contract/ticker"):
            try:
                out[d["symbol"]] = {
                    "symbol": d["symbol"], "last": float(d["lastPrice"]),
                    "bid": float(d.get("bid1") or 0), "ask": float(d.get("ask1") or 0),
                    "high": float(d.get("high24Price") or 0), "low": float(d.get("lower24Price") or 0),
                    "change_pct": float(d.get("riseFallRate") or 0) * 100,
                    "quote_volume": float(d.get("amount24") or 0),
                    "funding_rate": float(d.get("fundingRate") or 0),
                    "fair": float(d.get("fairPrice") or d["lastPrice"]),
                }
            except (TypeError, ValueError, KeyError):
                continue
        return out

    def klines(self, symbol, interval, limit):
        step = INTERVAL_MS[interval]
        end = int(time.time())
        start = end - (limit + 1) * step // 1000
        d = self._get(f"/api/v1/contract/kline/{symbol}",
                      {"interval": INTERVAL_MEXC[interval], "start": start, "end": end})
        out = []
        for i, t in enumerate(d.get("time", [])):
            ts = int(t) * 1000
            out.append({"t": ts, "o": float(d["open"][i]), "h": float(d["high"][i]), "l": float(d["low"][i]),
                        "c": float(d["close"][i]), "v": float(d["vol"][i]), "ct": ts + step - 1})
        return out[-limit:]

    def funding(self, symbol):
        d = self._get(f"/api/v1/contract/funding_rate/{symbol}")
        return {"rate": float(d.get("fundingRate") or 0), "next": int(d.get("nextSettleTime") or 0),
                "cycle_h": float(d.get("collectCycle") or 8)}
