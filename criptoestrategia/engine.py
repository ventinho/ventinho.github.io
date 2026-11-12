"""
Motor do bot (FUTUROS MEXC, margem isolada, alavancagem configurável):
escolhe o universo, procura sinais EMA9/EMA20 no 1m (long e short), abre posições fictícias
e gere-as: TP1 parcial + breakeven, trailing, TP2, stop loss, saída técnica pela EMA20,
time stop, estagnação, liquidação e funding.
"""
import json
import math
import queue
import threading
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import config as C
import strategy
from exchange import INTERVAL_MS

TF_MS = INTERVAL_MS[C.TF_ENTRADA]       # 1m
TREND_MS = INTERVAL_MS[C.TF_TENDENCIA]  # 15m
H1 = 3_600_000
BTC = "BTC_USDT"


def utc_day(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def sgn(side):
    return 1 if side == "LONG" else -1


class Engine:
    def __init__(self, db, market):
        self.db, self.mx = db, market
        self.commands = queue.Queue()
        self.tickers = {}      # dados reais: bid/ask/last/funding por contrato
        self.contracts = {}    # especificações dos contratos
        self.ktf_cache = {}
        self.last_error = None
        self.started_at = market.now_ms()
        self.running = True
        if self.db.get_state("balance") is None:
            self.db.set_state("balance", C.CAPITAL_INICIAL)
            self.db.set_state("peak", C.CAPITAL_INICIAL)
            self.db.set_state("capital_inicial", C.CAPITAL_INICIAL)
            self.db.set_state("created_at", market.now_ms())
            self.db.event(market.now_ms(), "INFO",
                          f"Conta fictícia de futuros criada com {C.CAPITAL_INICIAL:.2f} USDT · alavancagem {C.ALAVANCAGEM}x")
        self.balance = self.db.get_state("balance")
        self.peak = self.db.get_state("peak", self.balance)
        self.paused = self.db.get_state("paused", False)
        self.kill = self.db.get_state("kill", False)
        self.day = self.db.get_state("day")
        self.day_start_equity = self.db.get_state("day_start_equity", self.balance)
        self.cooldown = self.db.get_state("cooldown", {})
        self.daily_block = False
        self.last_scan_bucket = None
        self.last_universe = 0  # recalcula sempre ao arrancar (precisa das especificações dos contratos)
        self.last_snapshot = 0
        self.universe = []

    # ───────────────────────── preços e contabilidade ─────────────────────────
    def mark(self, t):
        """Preço a que a posição seria fechada agora: LONG vende ao bid, SHORT compra ao ask."""
        tk = self.tickers.get(t["symbol"])
        if not tk or tk["bid"] <= 0:
            return t["current_price"] or t["entry_price"]
        return tk["bid"] if t["side"] == "LONG" else tk["ask"]

    def upnl(self, t, p=None):
        p = self.mark(t) if p is None else p
        return sgn(t["side"]) * (p - t["entry_price"]) * t["qty_open"]

    def equity(self, trades=None):
        trades = self.db.open_trades() if trades is None else trades
        u = sum(self.upnl(t) for t in trades)
        margin = sum(t["qty_open"] * t["entry_price"] / t["leverage"] for t in trades)
        notional = sum(t["qty_open"] * self.mark(t) for t in trades)
        return self.balance + u, margin, notional, u

    def position_view(self, t, now):
        p = self.mark(t)
        u = self.upnl(t, p)
        margin = t["qty_open"] * t["entry_price"] / t["leverage"]
        nxt = t["tp2"] if t["tp1_hit"] else t["tp1"]
        d = sgn(t["side"])
        return {**t, "price": p, "unrealized_pnl": u, "margin_open": margin,
                "roe_pct": u / margin * 100 if margin else 0,
                "unrealized_pct": d * (p / t["entry_price"] - 1) * 100,
                "r_now": (u + t["realized_pnl"]) / t["risk_usdt"] if t["risk_usdt"] else 0,
                "value": p * t["qty_open"],
                "dist_sl_pct": d * (p / t["sl"] - 1) * 100,
                "dist_tp_pct": d * (nxt / p - 1) * 100,
                "dist_liq_pct": d * (p / t["liq_price"] - 1) * 100,
                "age_min": (now - t["entry_time"]) / 60000}

    def _save_balance(self):
        self.db.set_state("balance", self.balance)

    # ───────────────────────── abrir posição ─────────────────────────
    def _open(self, symbol, sig, now, equity, margin_used, risk_frac, regime):
        spec, tk = self.contracts.get(symbol), self.tickers.get(symbol)
        if not spec or not tk or tk["bid"] <= 0 or tk["ask"] <= 0:
            return None, "sem dados do contrato/livro"
        bid, ask = tk["bid"], tk["ask"]
        spread = (ask - bid) / ((ask + bid) / 2) * 100
        if spread > C.SPREAD_MAX_PCT:
            return None, f"spread {spread:.3f}% > {C.SPREAD_MAX_PCT}%"
        side, d, lev = sig["side"], sgn(sig["side"]), C.ALAVANCAGEM
        entry = ask * (1 + C.SLIPPAGE) if side == "LONG" else bid * (1 - C.SLIPPAGE)
        atr = sig["atr"]
        if side == "LONG":
            sl_raw = min(sig["swing"], sig["ema20"]) - C.SL_ATR_BUFFER * atr
            dist = (entry - sl_raw) / entry
        else:
            sl_raw = max(sig["swing"], sig["ema20"]) + C.SL_ATR_BUFFER * atr
            dist = (sl_raw - entry) / entry
        dist = min(max(dist, C.SL_PCT_MIN), C.SL_PCT_MAX)
        sl = entry * (1 - d * dist)
        R = entry * dist
        available = equity - margin_used
        max_notional = min(equity * C.MAX_MARGEM_POSICAO_PCT * lev,
                           (equity * C.MAX_MARGEM_TOTAL_PCT - margin_used) * lev,
                           available * 0.98 * lev)
        notional = min(equity * risk_frac / R * entry, max_notional)
        cs, vu = spec["contract_size"], spec["vol_unit"] or 1
        contracts = math.floor(notional / entry / cs / vu) * vu
        if contracts < spec["min_vol"]:
            return None, f"abaixo do mínimo de contratos ({spec['min_vol']:g} × {cs:g})"
        qty = contracts * cs
        notional = qty * entry
        if notional < C.NOTIONAL_MIN:
            return None, f"notional {notional:.2f} < mínimo {C.NOTIONAL_MIN}"
        margin = notional / lev
        fee = notional * spec["taker"]
        self.balance -= fee
        self._save_balance()
        liq = entry * (1 - d * (1 / lev - spec["mmr"]))
        try:
            f = self.mx.funding(symbol)
            f_next, f_cycle = f["next"], f["cycle_h"]
        except Exception:
            f_next, f_cycle = 0, 8
        tid = self.db.insert("trades", {
            "symbol": symbol, "side": side, "leverage": lev, "entry_time": now, "entry_price": entry,
            "contracts": contracts, "contract_size": cs, "qty": qty, "qty_open": qty, "notional": notional,
            "margin": margin, "entry_fee": fee, "taker_fee": spec["taker"], "maker_fee": spec["maker"],
            "initial_sl": sl, "sl": sl, "tp1": entry + d * C.TP1_R * R, "tp2": entry + d * C.TP2_R * R,
            "liq_price": liq, "risk_usdt": qty * R, "atr": atr, "score": sig["score"],
            "entry_reason": sig["reason"], "market_regime": regime, "highest": entry, "lowest": entry,
            "current_price": entry, "unrealized_pnl": 0, "realized_pnl": 0, "fees_total": fee,
            "funding_total": 0, "funding_next": f_next, "funding_cycle_h": f_cycle, "updated_at": now,
        })
        self.db.insert("fills", {"trade_id": tid, "time": now, "symbol": symbol,
                                 "action": "BUY" if side == "LONG" else "SELL", "kind": "ENTRADA",
                                 "price": entry, "qty": qty, "notional": notional, "fee": fee, "pnl": -fee,
                                 "balance_after": self.balance})
        self.db.event(now, "TRADE", f"ABRE {side} {symbol} {lev}x @ {entry:.6g} | {contracts:g} contratos | "
                                    f"notional {notional:.2f} · margem {margin:.2f} USDT | SL {sl:.6g} ({dist*100:.2f}%) | "
                                    f"TP1 {entry + d*C.TP1_R*R:.6g} | TP2 {entry + d*C.TP2_R*R:.6g} | liq {liq:.6g} | score {sig['score']}")
        return tid, None

    # ───────────────────────── fechar (parcial ou total) ─────────────────────────
    def _close(self, t, qty, price, kind, now, maker=False, liquidation=False):
        d = sgn(t["side"])
        qty = min(qty, t["qty_open"])
        notional = qty * price
        fee = 0.0 if liquidation else notional * (t["maker_fee"] if maker else t["taker_fee"])
        entry_fee_part = t["entry_fee"] * qty / t["qty"]
        gross = -(qty * t["entry_price"] / t["leverage"]) if liquidation else d * (price - t["entry_price"]) * qty
        pnl = gross - fee - entry_fee_part
        self.balance += gross - fee
        self._save_balance()
        t["qty_open"] -= qty
        t["realized_pnl"] += gross - fee - entry_fee_part
        t["fees_total"] += fee
        self.db.insert("fills", {"trade_id": t["id"], "time": now, "symbol": t["symbol"],
                                 "action": "SELL" if t["side"] == "LONG" else "BUY", "kind": kind,
                                 "price": price, "qty": qty, "notional": notional, "fee": fee, "pnl": pnl,
                                 "balance_after": self.balance})
        fields = {"qty_open": t["qty_open"], "realized_pnl": t["realized_pnl"], "fees_total": t["fees_total"],
                  "sl": t["sl"], "tp1_hit": t["tp1_hit"], "highest": t["highest"], "lowest": t["lowest"],
                  "current_price": price, "updated_at": now,
                  "contracts_open": round(t["qty_open"] / t["contract_size"], 8)}
        closed = t["qty_open"] <= t["qty"] * 1e-9
        if closed:
            sells = self.db.q("SELECT price, qty FROM fills WHERE trade_id=? AND kind NOT IN ('ENTRADA','FUNDING')",
                              (t["id"],))
            sq = sum(s["qty"] for s in sells)
            exit_px = sum(s["price"] * s["qty"] for s in sells) / sq
            if d == 1:
                mfe, mae = (t["highest"] / t["entry_price"] - 1) * 100, (t["lowest"] / t["entry_price"] - 1) * 100
            else:
                mfe, mae = (1 - t["lowest"] / t["entry_price"]) * 100, (1 - t["highest"] / t["entry_price"]) * 100
            fields.update({
                "status": "CLOSED", "qty_open": 0, "contracts_open": 0, "exit_time": now, "exit_price": exit_px,
                "exit_reason": kind, "pnl": t["realized_pnl"],
                "pnl_pct": t["realized_pnl"] / t["notional"] * 100,
                "roe_pct": t["realized_pnl"] / t["margin"] * 100,
                "r_multiple": t["realized_pnl"] / t["risk_usdt"] if t["risk_usdt"] else 0,
                "mfe_pct": mfe, "mae_pct": mae, "duration_min": (now - t["entry_time"]) / 60000, "unrealized_pnl": 0,
            })
            cd = C.COOLDOWN_PERDA_MIN if t["realized_pnl"] < 0 else C.COOLDOWN_MIN
            self.cooldown[t["symbol"]] = now + cd * 60_000
            self.db.set_state("cooldown", self.cooldown)
        self.db.update("trades", t["id"], fields)
        tag = "FECHO" if closed else "PARCIAL"
        self.db.event(now, "ALERTA" if liquidation else "TRADE",
                      f"{tag} {kind} {t['side']} {t['symbol']} @ {price:.6g} | qty {qty:.6g} | PnL {pnl:+.4f} USDT"
                      + (f" | total {t['realized_pnl']:+.4f} USDT ({fields['r_multiple']:+.2f}R · ROE {fields['roe_pct']:+.1f}%)" if closed else ""))
        return closed

    def close_trade(self, trade_id, now, kind="MANUAL"):
        t = self.db.one("SELECT * FROM trades WHERE id=? AND status='OPEN'", (trade_id,))
        if not t:
            return False
        p = self.mark(t)
        self._close(t, t["qty_open"], p * (1 - sgn(t["side"]) * C.SLIPPAGE), kind, now)
        return True

    # ───────────────────────── gestão de posições (cada tick, ~3 s) ─────────────────────────
    def manage_positions(self, now):
        updates = []
        for t in self.db.open_trades():
            if t["symbol"] not in self.tickers:
                continue
            p = self.mark(t)
            d = sgn(t["side"])
            t["highest"], t["lowest"] = max(t["highest"], p), min(t["lowest"], p)

            # funding (horas reais de liquidação de cada contrato)
            if t["funding_next"] and now >= t["funding_next"]:
                rate = self.tickers[t["symbol"]]["funding_rate"]
                pay = -d * rate * t["qty_open"] * p
                self.balance += pay
                self._save_balance()
                t["funding_total"] += pay
                t["realized_pnl"] += pay
                t["funding_next"] += int(t["funding_cycle_h"] * H1)
                self.db.insert("fills", {"trade_id": t["id"], "time": now, "symbol": t["symbol"], "action": "FUNDING",
                                         "kind": "FUNDING", "price": p, "qty": 0, "notional": t["qty_open"] * p,
                                         "fee": 0, "pnl": pay, "balance_after": self.balance})
                self.db.update("trades", t["id"], {"funding_total": t["funding_total"], "realized_pnl": t["realized_pnl"],
                                                   "funding_next": t["funding_next"]})
                self.db.event(now, "INFO", f"Funding {t['symbol']} {t['side']}: taxa {rate*100:.4f}% → {pay:+.4f} USDT")

            # liquidação (margem isolada)
            if d * (p - t["liq_price"]) <= 0:
                self._close(t, t["qty_open"], t["liq_price"], "LIQUIDAÇÃO", now, liquidation=True)
                continue

            be = t["entry_price"] * (1 + d * 2 * t["taker_fee"])
            if not t["tp1_hit"] and d * (p - t["tp1"]) >= 0:
                t["tp1_hit"] = 1
                t["sl"] = max(t["sl"], be) if d == 1 else min(t["sl"], be)
                vu = 1
                part = math.floor(t["contracts"] * C.TP1_FRACAO / vu) * vu
                if part >= 1:
                    self._close(t, part * t["contract_size"], t["tp1"], "TP1", now, maker=True)
                else:
                    self.db.update("trades", t["id"], {"tp1_hit": 1, "sl": t["sl"]})
            if t["tp1_hit"]:
                if d == 1:
                    t["sl"] = max(t["sl"], t["highest"] - C.TRAILING_ATR_MULT * t["atr"])
                else:
                    t["sl"] = min(t["sl"], t["lowest"] + C.TRAILING_ATR_MULT * t["atr"])
            if d * (p - t["tp2"]) >= 0:
                self._close(t, t["qty_open"], t["tp2"], "TP2", now, maker=True)
                continue
            if d * (p - t["sl"]) <= 0:
                fill = p * (1 - d * C.SLIPPAGE)
                if not t["tp1_hit"]:
                    kind = "STOP LOSS"
                elif d * (t["sl"] - be) > be * 0.0005:
                    kind = "TRAILING STOP"
                else:
                    kind = "BREAKEVEN"
                self._close(t, t["qty_open"], fill, kind, now)
                continue
            updates.append((t["sl"], t["tp1_hit"], t["highest"], t["lowest"], p, self.upnl(t, p), now, t["id"]))
        if updates:
            self.db.xmany("UPDATE trades SET sl=?, tp1_hit=?, highest=?, lowest=?, current_price=?, "
                          "unrealized_pnl=?, updated_at=? WHERE id=?", updates)

    # ───────────────────────── universo ─────────────────────────
    def refresh_universe(self, now):
        self.contracts = self.mx.contracts()
        tick = self.tickers or self.mx.tickers()
        cands = []
        for s, d in tick.items():
            spec = self.contracts.get(s)
            if not s.endswith("_USDT") or not spec or not spec["active"] or spec["tradfi"]:
                continue
            base = s[:-5]
            if (base in C.EXCLUIR_BASES or base.endswith(C.EXCLUIR_SUFIXOS) or not base.isalnum()
                    or spec["max_leverage"] < C.ALAVANCAGEM or d["last"] <= 0 or d["low"] <= 0):
                continue
            if d["quote_volume"] < C.VOLUME_MIN_24H or d["bid"] <= 0 or d["ask"] <= 0:
                continue
            d = dict(d)
            d["spread"] = (d["ask"] - d["bid"]) / ((d["ask"] + d["bid"]) / 2) * 100
            if d["spread"] > C.SPREAD_MAX_PCT:
                continue
            d["volatility"] = (d["high"] - d["low"]) / d["low"] * 100
            if d["volatility"] > C.VOLATILIDADE_MAX_24H:
                continue
            cands.append(d)
        cands.sort(key=lambda d: d["quote_volume"], reverse=True)
        cands = cands[:C.PRE_FILTRO_TOP_VOLUME]
        n = len(cands)
        if n == 0:
            raise RuntimeError("nenhum contrato passou os filtros do universo")
        for i, d in enumerate(cands):
            d["r_vol"] = 1 - i / n
        for i, d in enumerate(sorted(cands, key=lambda d: d["volatility"], reverse=True)):
            d["r_volat"] = 1 - i / n
        for d in cands:
            d["score"] = C.PESO_VOLUME * d["r_vol"] + C.PESO_VOLATILIDADE * d["r_volat"]
        top = sorted(cands, key=lambda d: d["score"], reverse=True)[:C.N_MOEDAS]
        self.db.x("DELETE FROM universe")
        self.db.xmany("INSERT INTO universe VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      [(d["symbol"], i + 1, round(d["score"] * 100, 1), d["quote_volume"], d["volatility"],
                        d["change_pct"], d["last"], now, d["spread"], d["funding_rate"],
                        self.contracts[d["symbol"]]["taker"], self.contracts[d["symbol"]]["maker"])
                       for i, d in enumerate(top)])
        self.universe = [d["symbol"] for d in top]
        self.last_universe = now
        self.db.set_state("universe_at", now)
        self.db.event(now, "INFO", f"Universo atualizado: {len(top)} contratos de futuros (de {len(tick)}). "
                                   f"Top 5: {', '.join(self.universe[:5])}")

    # ───────────────────────── scan de sinais (cada vela de 1m) ─────────────────────────
    def _ktrend(self, sym, now):
        b = now // TREND_MS
        cached = self.ktf_cache.get(sym)
        if cached and cached[0] == b:
            return cached[1]
        k = strategy.closed_only(self.mx.klines(sym, C.TF_TENDENCIA, C.VELAS_TENDENCIA), now)
        self.ktf_cache[sym] = (b, k)
        return k

    def _fetch(self, sym, now):
        try:
            k1m = strategy.closed_only(self.mx.klines(sym, C.TF_ENTRADA, C.VELAS_ENTRADA), now)
            need = C.FILTRO_TENDENCIA or sym == BTC
            return sym, k1m, (self._ktrend(sym, now) if need else None), None
        except Exception as e:
            return sym, None, None, str(e)

    def scan(self, now):
        t0 = time.time()
        open_tr = self.db.open_trades()
        open_syms = {t["symbol"] for t in open_tr}
        symbols = list(dict.fromkeys([BTC] + self.universe + list(open_syms)))
        with ThreadPoolExecutor(C.WORKERS_HTTP) as ex:
            data = {s: (k1m, ktf, err) for s, k1m, ktf, err in ex.map(lambda s: self._fetch(s, now), symbols)}

        btc = data.get(BTC)
        bt = strategy.trend_filter(btc[1]) if btc and btc[1] else None
        regime = ("ALTA" if bt["up"] else "BAIXA" if bt["down"] else "LATERAL") if bt else "?"

        # saídas: técnica (EMA9/EMA20 no 1m), tempo e estagnação
        for t in open_tr:
            mins = (now - t["entry_time"]) / 60_000
            R = abs(t["entry_price"] - t["initial_sl"])
            k1m = data.get(t["symbol"], (None, None, None))[0]
            ema_exit = strategy.exit_signal(k1m, t["side"]) if C.SAIDA_EMA and k1m and k1m[-1]["ct"] > t["entry_time"] else None
            best = t["highest"] if t["side"] == "LONG" else t["lowest"]
            moved = sgn(t["side"]) * (best - t["entry_price"])
            if ema_exit:
                self.close_trade(t["id"], now, ema_exit)
            elif mins >= C.TIME_STOP_MIN:
                self.close_trade(t["id"], now, "TIME STOP")
            elif not t["tp1_hit"] and mins >= C.ESTAGNACAO_MIN and moved < C.ESTAGNACAO_R * R:
                self.close_trade(t["id"], now, "ESTAGNAÇÃO")

        rejections, signals, errors = Counter(), [], 0
        open_syms = {t["symbol"] for t in self.db.open_trades()}
        for s in self.universe:
            k1m, ktf, err = data.get(s, (None, None, "sem dados"))
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
            sig, why, ind = strategy.evaluate(k1m, ktf, C.PERMITIR_SHORT)
            if sig is None:
                rejections[why] += 1
                continue
            signals.append((s, sig, ind))
        signals.sort(key=lambda x: x[1]["score"], reverse=True)

        equity, margin_used, _, _ = self.equity()
        n_open = len(open_syms)
        taken = 0
        for s, sig, ind in signals:
            against = (sig["side"] == "LONG" and regime == "BAIXA") or (sig["side"] == "SHORT" and regime == "ALTA")
            min_score = C.SCORE_MIN_CONTRA_BTC if against else C.SCORE_MIN
            risk = C.RISCO_CONTRA_BTC if against else C.RISCO_POR_TRADE
            decision, detail = "IGNORADO", ""
            if sig["score"] < min_score:
                detail = f"score {sig['score']} < {min_score}" + (" (contra o BTC)" if against else "")
            elif self.kill:
                detail = "kill switch (drawdown máximo)"
            elif self.paused:
                detail = "bot em pausa (manual)"
            elif self.daily_block:
                detail = "limite de perda diária atingido"
            elif n_open >= C.MAX_POSICOES:
                detail = f"máx. {C.MAX_POSICOES} posições"
            else:
                tid, err = self._open(s, sig, now, equity, margin_used, risk, regime)
                if tid:
                    decision, detail = "ENTRADA", f"trade #{tid}"
                    n_open += 1
                    taken += 1
                    equity, margin_used, _, _ = self.equity()
                else:
                    detail = err
            self.db.insert("signals", {"time": now, "symbol": s, "side": sig["side"], "price": sig["price"],
                                       "score": sig["score"], "decision": decision,
                                       "detail": f"{sig['reason']} — {detail}",
                                       "indicators": json.dumps({k: (round(v, 6) if isinstance(v, float) else v)
                                                                 for k, v in ind.items()})})
        self.db.set_state("last_scan", {
            "time": now, "evaluated": len(self.universe), "signals": len(signals), "taken": taken,
            "errors": errors, "btc_regime": regime, "btc_close": bt["close"] if bt else None,
            "btc_ema50": bt["ema"] if bt else None, "seconds": round(time.time() - t0, 1),
            "rejections": dict(rejections.most_common()),
        })

    # ───────────────────────── snapshot / proteções ─────────────────────────
    def risk_and_snapshot(self, now):
        trades = self.db.open_trades()
        equity, margin, notional, u = self.equity(trades)
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
        was = self.daily_block
        self.daily_block = equity < self.day_start_equity * (1 - C.PERDA_DIARIA_MAX)
        if self.daily_block and not was:
            self.db.event(now, "ALERTA", f"Perda diária ≥ {C.PERDA_DIARIA_MAX*100:.0f}% — sem novas entradas até 00:00 UTC.")
        if now - self.last_snapshot >= C.SNAPSHOT_EQUITY_S * 1000:
            self.last_snapshot = now
            realized = self.db.one("SELECT COALESCE(SUM(pnl),0) s FROM fills WHERE kind<>'ENTRADA'")["s"]
            self.db.x("INSERT OR REPLACE INTO equity VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (now, self.balance, equity, margin, u, realized, len(trades),
                       notional / equity * 100 if equity else 0, dd * 100, self.peak))

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
        self.tickers = self.mx.tickers()
        self.process_commands(now)
        if now - self.last_universe >= C.ATUALIZAR_UNIVERSO_H * H1 or not self.universe:
            self.refresh_universe(now)
        self.manage_positions(now)
        bucket = now // TF_MS
        if bucket != self.last_scan_bucket and now % TF_MS >= C.ATRASO_SCAN_S * 1000:
            self.last_scan_bucket = bucket
            self.scan(now)
        self.risk_and_snapshot(now)

    def run(self, stop):
        self.db.event(self.mx.now_ms(), "INFO", f"Bot iniciado — {self.mx.name} · {C.ALAVANCAGEM}x · "
                                                f"{'long + short' if C.PERMITIR_SHORT else 'só long'}")
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
