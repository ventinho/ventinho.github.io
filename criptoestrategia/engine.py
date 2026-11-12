"""
Motor do bot: escolhe o universo, procura sinais, abre posições fictícias e gere-as
(TP1 parcial, breakeven, trailing, TP2, stop loss, time stop, estagnação, quebra de tendência).
"""
import json
import queue
import threading
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import config as C
import strategy

M15 = 900_000
H1 = 3_600_000


def utc_day(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


class Engine:
    def __init__(self, db, market):
        self.db, self.mx = db, market
        self.lock = threading.RLock()
        self.commands = queue.Queue()
        self.prices = {}
        self.k1h_cache = {}
        self.last_error = None
        self.started_at = market.now_ms()
        self.running = True
        if self.db.get_state("cash") is None:
            self.db.set_state("cash", C.CAPITAL_INICIAL)
            self.db.set_state("peak", C.CAPITAL_INICIAL)
            self.db.set_state("capital_inicial", C.CAPITAL_INICIAL)
            self.db.set_state("created_at", market.now_ms())
            self.db.event(market.now_ms(), "INFO", f"Conta fictícia criada com {C.CAPITAL_INICIAL:.2f} USDT")
        self.cash = self.db.get_state("cash")
        self.peak = self.db.get_state("peak", self.cash)
        self.paused = self.db.get_state("paused", False)
        self.kill = self.db.get_state("kill", False)
        self.day = self.db.get_state("day")
        self.day_start_equity = self.db.get_state("day_start_equity", self.cash)
        self.cooldown = self.db.get_state("cooldown", {})
        self.last_scan_bucket = None
        self.last_universe = self.db.get_state("universe_at", 0)
        self.last_snapshot = 0
        self.universe = [r["symbol"] for r in self.db.q("SELECT symbol FROM universe ORDER BY rank")]
        self.snapshot_every_ms = (15 * 60 if market.demo else C.SNAPSHOT_EQUITY_S) * 1000

    # ───────────────────────── contabilidade ─────────────────────────
    def equity(self, trades=None):
        trades = trades if trades is not None else self.db.open_trades()
        pos_val = sum(t["qty_open"] * self.prices.get(t["symbol"], t["current_price"] or t["entry_price"]) for t in trades)
        return self.cash + pos_val, pos_val

    def _save_cash(self):
        self.db.set_state("cash", self.cash)

    def _buy(self, symbol, sig, now, equity, risk_frac, regime):
        last = self.prices.get(symbol, sig["price"])
        entry = last * (1 + C.SLIPPAGE)
        atr = sig["atr"]
        sl_raw = min(entry - C.SL_ATR_MULT * atr, sig["swing_low"] - 0.1 * atr)
        dist = min(max((entry - sl_raw) / entry, C.SL_PCT_MIN), C.SL_PCT_MAX)
        sl = entry * (1 - dist)
        R = entry - sl
        qty = equity * risk_frac / R
        notional = qty * entry
        cap = min(equity * C.MAX_POSICAO_PCT, self.cash / (1 + C.TAXA_TAKER) * 0.995)
        if notional > cap:
            notional, qty = cap, cap / entry
        if notional < C.NOTIONAL_MIN:
            return None, f"notional {notional:.2f} < mínimo {C.NOTIONAL_MIN}"
        fee = notional * C.TAXA_TAKER
        self.cash -= notional + fee
        self._save_cash()
        tid = self.db.insert("trades", {
            "symbol": symbol, "entry_time": now, "entry_price": entry, "qty": qty, "qty_open": qty,
            "notional": notional, "entry_fee": fee, "initial_sl": sl, "sl": sl,
            "tp1": entry + C.TP1_R * R, "tp2": entry + C.TP2_R * R, "risk_usdt": qty * R, "atr": atr,
            "score": sig["score"], "entry_reason": sig["reason"], "market_regime": regime,
            "highest": entry, "lowest": entry, "current_price": last, "unrealized_pnl": 0,
            "realized_pnl": 0, "fees_total": fee, "updated_at": now,
        })
        self.db.insert("fills", {"trade_id": tid, "time": now, "symbol": symbol, "action": "BUY", "kind": "ENTRADA",
                                 "price": entry, "qty": qty, "notional": notional, "fee": fee, "pnl": -fee,
                                 "cash_after": self.cash})
        self.db.event(now, "TRADE", f"COMPRA {symbol} @ {entry:.6g} | {notional:.2f} USDT | SL {sl:.6g} "
                                    f"(-{dist*100:.2f}%) | TP1 {entry + C.TP1_R*R:.6g} | TP2 {entry + C.TP2_R*R:.6g} | score {sig['score']}")
        return tid, None

    def _sell(self, t, qty, price, kind, now):
        qty = min(qty, t["qty_open"])
        notional = qty * price
        fee = notional * C.TAXA_TAKER
        entry_fee_part = t["entry_fee"] * qty / t["qty"]
        pnl = (price - t["entry_price"]) * qty - fee - entry_fee_part
        self.cash += notional - fee
        self._save_cash()
        t["qty_open"] -= qty
        t["realized_pnl"] += pnl
        t["fees_total"] += fee
        self.db.insert("fills", {"trade_id": t["id"], "time": now, "symbol": t["symbol"], "action": "SELL", "kind": kind,
                                 "price": price, "qty": qty, "notional": notional, "fee": fee, "pnl": pnl,
                                 "cash_after": self.cash})
        fields = {"qty_open": t["qty_open"], "realized_pnl": t["realized_pnl"], "fees_total": t["fees_total"],
                  "sl": t["sl"], "tp1_hit": t["tp1_hit"], "highest": t["highest"], "lowest": t["lowest"],
                  "current_price": price, "updated_at": now}
        closed = t["qty_open"] <= t["qty"] * 1e-9
        if closed:
            sells = self.db.q("SELECT price, qty FROM fills WHERE trade_id=? AND action='SELL'", (t["id"],))
            sq = sum(s["qty"] for s in sells)
            exit_px = sum(s["price"] * s["qty"] for s in sells) / sq
            fields.update({
                "status": "CLOSED", "qty_open": 0, "exit_time": now, "exit_price": exit_px, "exit_reason": kind,
                "pnl": t["realized_pnl"], "pnl_pct": t["realized_pnl"] / t["notional"] * 100,
                "r_multiple": t["realized_pnl"] / t["risk_usdt"] if t["risk_usdt"] else 0,
                "mfe_pct": (t["highest"] / t["entry_price"] - 1) * 100,
                "mae_pct": (t["lowest"] / t["entry_price"] - 1) * 100,
                "duration_min": (now - t["entry_time"]) / 60000, "unrealized_pnl": 0,
            })
            cd = C.COOLDOWN_PERDA_MIN if t["realized_pnl"] < 0 else C.COOLDOWN_MIN
            self.cooldown[t["symbol"]] = now + cd * 60_000
            self.db.set_state("cooldown", self.cooldown)
        self.db.update("trades", t["id"], fields)
        tag = "FECHO" if closed else "PARCIAL"
        self.db.event(now, "TRADE", f"{tag} {kind} {t['symbol']} @ {price:.6g} | qty {qty:.6g} | PnL {pnl:+.4f} USDT"
                      + (f" | total trade {t['realized_pnl']:+.4f} USDT ({fields['r_multiple']:+.2f}R)" if closed else ""))
        return closed

    # ───────────────────────── gestão de posições (cada tick) ─────────────────────────
    def manage_positions(self, now):
        updates = []
        for t in self.db.open_trades():
            p = self.prices.get(t["symbol"])
            if p is None:
                continue
            t["highest"], t["lowest"] = max(t["highest"], p), min(t["lowest"], p)
            be = t["entry_price"] * (1 + 2 * C.TAXA_TAKER)
            if not t["tp1_hit"] and p >= t["tp1"]:
                t["tp1_hit"] = 1
                t["sl"] = max(t["sl"], be)
                self._sell(t, t["qty"] * C.TP1_FRACAO, t["tp1"], "TP1", now)
            if t["tp1_hit"]:
                t["sl"] = max(t["sl"], t["highest"] - C.TRAILING_ATR_MULT * t["atr"])
            if p >= t["tp2"]:
                self._sell(t, t["qty_open"], t["tp2"], "TP2", now)
                continue
            if p <= t["sl"]:
                fill = min(p, t["sl"]) * (1 - C.SLIPPAGE)
                if not t["tp1_hit"]:
                    kind = "STOP LOSS"
                elif t["sl"] > be * 1.0005:
                    kind = "TRAILING STOP"
                else:
                    kind = "BREAKEVEN"
                self._sell(t, t["qty_open"], fill, kind, now)
                continue
            upnl = (p - t["entry_price"]) * t["qty_open"]
            updates.append((t["sl"], t["tp1_hit"], t["highest"], t["lowest"], p, upnl, now, t["id"]))
        if updates:
            self.db.xmany("UPDATE trades SET sl=?, tp1_hit=?, highest=?, lowest=?, current_price=?, "
                          "unrealized_pnl=?, updated_at=? WHERE id=?", updates)

    def close_trade(self, trade_id, now, kind="MANUAL"):
        t = self.db.one("SELECT * FROM trades WHERE id=? AND status='OPEN'", (trade_id,))
        if not t:
            return False
        p = self.prices.get(t["symbol"], t["current_price"] or t["entry_price"])
        self._sell(t, t["qty_open"], p * (1 - C.SLIPPAGE), kind, now)
        return True

    # ───────────────────────── universo ─────────────────────────
    def refresh_universe(self, now):
        tick = self.mx.tickers_24h()
        cands = []
        for d in tick:
            s = d["symbol"]
            if not s.endswith("USDT"):
                continue
            base = s[:-4]
            if base in C.EXCLUIR_BASES or base.endswith(C.EXCLUIR_SUFIXOS) or d["last"] <= 0 or d["low"] <= 0:
                continue
            if d["quote_volume"] < C.VOLUME_MIN_24H:
                continue
            d["volatility"] = (d["high"] - d["low"]) / d["low"] * 100
            if d["volatility"] > C.VOLATILIDADE_MAX_24H:
                continue
            cands.append(d)
        cands.sort(key=lambda d: d["quote_volume"], reverse=True)
        cands = cands[:C.PRE_FILTRO_TOP_VOLUME]
        n = len(cands)
        if n == 0:
            raise RuntimeError("nenhum par passou os filtros do universo")
        for i, d in enumerate(cands):
            d["r_vol"] = 1 - i / n
        for i, d in enumerate(sorted(cands, key=lambda d: d["volatility"], reverse=True)):
            d["r_volat"] = 1 - i / n
        for d in cands:
            d["score"] = C.PESO_VOLUME * d["r_vol"] + C.PESO_VOLATILIDADE * d["r_volat"]
        top = sorted(cands, key=lambda d: d["score"], reverse=True)[:C.N_MOEDAS]
        self.db.x("DELETE FROM universe")
        self.db.xmany("INSERT INTO universe VALUES (?,?,?,?,?,?,?,?)",
                      [(d["symbol"], i + 1, round(d["score"] * 100, 1), d["quote_volume"], d["volatility"],
                        d["change_pct"], d["last"], now) for i, d in enumerate(top)])
        self.universe = [d["symbol"] for d in top]
        self.last_universe = now
        self.db.set_state("universe_at", now)
        self.db.event(now, "INFO", f"Universo atualizado: {len(top)} pares (de {len(tick)} tickers). "
                                   f"Top 5: {', '.join(self.universe[:5])}")

    # ───────────────────────── scan de sinais (cada vela de 15m) ─────────────────────────
    def _k1h(self, sym, now):
        hb = now // H1
        cached = self.k1h_cache.get(sym)
        if cached and cached[0] == hb:
            return cached[1]
        k = strategy.closed_only(self.mx.klines(sym, C.TF_TENDENCIA, C.VELAS_TENDENCIA), now)
        self.k1h_cache[sym] = (hb, k)
        return k

    def _fetch(self, sym, now):
        try:
            k15 = strategy.closed_only(self.mx.klines(sym, C.TF_ENTRADA, C.VELAS_ENTRADA), now)
            return sym, k15, self._k1h(sym, now), None
        except Exception as e:
            return sym, None, None, str(e)

    def scan(self, now):
        t0 = time.time()
        open_tr = self.db.open_trades()
        open_syms = {t["symbol"] for t in open_tr}
        symbols = list(dict.fromkeys(["BTCUSDT"] + self.universe + list(open_syms)))
        with ThreadPoolExecutor(C.WORKERS_HTTP) as ex:
            data = {s: (k15, k1h, err) for s, k15, k1h, err in ex.map(lambda s: self._fetch(s, now), symbols)}

        # regime de mercado pelo BTC
        btc = data.get("BTCUSDT")
        bt = strategy.trend_1h(btc[1]) if btc and btc[1] else None
        bearish = bool(bt and not bt["above_ema50"])
        regime = "BAIXA" if bearish else "ALTA/NEUTRO"

        # saídas por tempo / estagnação / tendência
        for t in open_tr:
            hours = (now - t["entry_time"]) / H1
            R = t["entry_price"] - t["initial_sl"]
            k1h = data.get(t["symbol"], (None, None, None))[1]
            tr = strategy.trend_1h(k1h) if k1h else None
            if hours >= C.TIME_STOP_H:
                self.close_trade(t["id"], now, "TIME STOP")
            elif not t["tp1_hit"] and hours >= C.ESTAGNACAO_H and t["highest"] < t["entry_price"] + C.ESTAGNACAO_R * R:
                self.close_trade(t["id"], now, "ESTAGNAÇÃO")
            elif not t["tp1_hit"] and tr and not tr["above_ema50"] and hours >= 1:
                self.close_trade(t["id"], now, "TENDÊNCIA 1H QUEBROU")

        # sinais de entrada
        rejections, signals, errors = Counter(), [], 0
        for s in self.universe:
            k15, k1h, err = data.get(s, (None, None, "sem dados"))
            if err:
                errors += 1
                rejections["erro de dados"] += 1
                continue
            if s in open_syms:
                rejections["posição já aberta"] += 1
                continue
            if self.cooldown.get(s, 0) > now:
                rejections["cooldown"] += 1
                continue
            sig, why, ind = strategy.evaluate(k15, k1h)
            if sig is None:
                rejections[why] += 1
                continue
            signals.append((s, sig, ind))
        signals.sort(key=lambda x: x[1]["score"], reverse=True)

        equity, _ = self.equity()
        min_score = C.SCORE_MIN_MERCADO_BAIXA if bearish else C.SCORE_MIN
        risk = C.RISCO_MERCADO_BAIXA if bearish else C.RISCO_POR_TRADE
        n_open = len(self.db.open_trades())
        taken = 0
        for s, sig, ind in signals:
            decision, detail = "IGNORADO", ""
            if sig["score"] < min_score:
                detail = f"score {sig['score']} < {min_score}" + (" (BTC em baixa)" if bearish else "")
            elif self.kill:
                detail = "kill switch (drawdown máximo)"
            elif self.paused:
                detail = "bot em pausa (manual)"
            elif self.daily_block:
                detail = "limite de perda diária atingido"
            elif n_open >= C.MAX_POSICOES:
                detail = f"máx. {C.MAX_POSICOES} posições"
            else:
                tid, err = self._buy(s, sig, now, equity, risk, regime)
                if tid:
                    decision, detail = "ENTRADA", f"trade #{tid}"
                    n_open += 1
                    taken += 1
                else:
                    detail = err
            self.db.insert("signals", {"time": now, "symbol": s, "price": sig["price"], "score": sig["score"],
                                       "decision": decision, "detail": f"{sig['reason']} — {detail}",
                                       "indicators": json.dumps({k: (round(v, 6) if isinstance(v, float) else v) for k, v in ind.items()})})
        self.db.set_state("last_scan", {
            "time": now, "evaluated": len(self.universe), "signals": len(signals), "taken": taken,
            "errors": errors, "btc_regime": regime, "btc_close": bt["close"] if bt else None,
            "btc_ema50": bt["ema50"] if bt else None, "seconds": round(time.time() - t0, 1),
            "rejections": dict(rejections.most_common()),
        })

    # ───────────────────────── snapshot / proteções ─────────────────────────
    def risk_and_snapshot(self, now):
        trades = self.db.open_trades()
        equity, pos_val = self.equity(trades)
        day = utc_day(now)
        if day != self.day:
            self.day, self.day_start_equity = day, equity
            self.db.set_state("day", day)
            self.db.set_state("day_start_equity", equity)
        if equity > self.peak:
            self.peak = equity
            self.db.set_state("peak", equity)
        dd = (self.peak - equity) / self.peak if self.peak else 0
        if dd >= C.DRAWDOWN_MAX and not self.kill:
            self.kill = True
            self.db.set_state("kill", True)
            self.db.event(now, "ALERTA", f"KILL SWITCH: drawdown {dd*100:.1f}% ≥ {C.DRAWDOWN_MAX*100:.0f}%. Novas entradas bloqueadas.")
        was = getattr(self, "daily_block", False)
        self.daily_block = equity < self.day_start_equity * (1 - C.PERDA_DIARIA_MAX)
        if self.daily_block and not was:
            self.db.event(now, "ALERTA", f"Perda diária ≥ {C.PERDA_DIARIA_MAX*100:.0f}% — sem novas entradas até 00:00 UTC.")
        if now - self.last_snapshot >= self.snapshot_every_ms:
            self.last_snapshot = now
            upnl = sum(t["unrealized_pnl"] or 0 for t in trades)
            realized = self.db.one("SELECT COALESCE(SUM(pnl),0) s FROM fills WHERE action='SELL'")["s"]
            self.db.x("INSERT OR REPLACE INTO equity VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (now, self.cash, equity, pos_val, upnl, realized, len(trades),
                       pos_val / equity * 100 if equity else 0, dd * 100, self.peak))

    # ───────────────────────── comandos do dashboard ─────────────────────────
    def process_commands(self, now):
        while True:
            try:
                cmd, arg = self.commands.get_nowait()
            except queue.Empty:
                return
            if cmd == "pause":
                self.paused = True
                self.db.set_state("paused", True)
                self.db.event(now, "INFO", "Bot pausado manualmente (posições abertas continuam geridas).")
            elif cmd == "resume":
                self.paused = False
                self.kill = False
                self.db.set_state("paused", False)
                self.db.set_state("kill", False)
                self.db.event(now, "INFO", "Bot retomado.")
            elif cmd == "close":
                self.close_trade(int(arg), now)
            elif cmd == "closeall":
                for t in self.db.open_trades():
                    self.close_trade(t["id"], now)

    # ───────────────────────── ciclo principal ─────────────────────────
    def step(self):
        now = self.mx.now_ms()
        self.process_commands(now)
        if now - self.last_universe >= C.ATUALIZAR_UNIVERSO_H * H1 or not self.universe:
            self.refresh_universe(now)
        self.prices = self.mx.prices()
        self.manage_positions(now)
        if not hasattr(self, "daily_block"):
            self.risk_and_snapshot(now)
        bucket = now // M15
        if bucket != self.last_scan_bucket and (self.mx.demo or now % M15 >= 5_000):
            self.last_scan_bucket = bucket
            self.scan(now)
        self.risk_and_snapshot(now)

    def run(self, stop):
        self.db.event(self.mx.now_ms(), "INFO", f"Bot iniciado — fonte: {self.mx.name}")
        while not stop.is_set():
            try:
                self.step()
                self.last_error = None
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                self.db.event(self.mx.now_ms(), "ERRO", self.last_error)
                traceback.print_exc()
                time.sleep(5)
            self.mx.sleep(C.INTERVALO_LOOP_S)
        self.running = False
