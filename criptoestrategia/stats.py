"""Cálculo de todas as estatísticas de desempenho para o dashboard."""
import math
from collections import defaultdict
from datetime import datetime, timezone

import config as C


def _dt(ms, fmt):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(fmt)


def streaks(pnls):
    best_w = best_l = cur_w = cur_l = 0
    for p in pnls:
        if p > 0:
            cur_w, cur_l = cur_w + 1, 0
        else:
            cur_l, cur_w = cur_l + 1, 0
        best_w, best_l = max(best_w, cur_w), max(best_l, cur_l)
    current = cur_w if cur_w else -cur_l
    return best_w, best_l, current


def ratios_from_equity(eq):
    """Sharpe/Sortino com retornos horários anualizados (crypto negoceia 24/7)."""
    if len(eq) < 3:
        return None, None
    hourly = {}
    for e in eq:
        hourly[e["time"] // 3_600_000] = e["equity"]
    vals = [hourly[k] for k in sorted(hourly)]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1]]
    if len(rets) < 2:
        return None, None
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
    neg = [min(r, 0) for r in rets]
    dsd = math.sqrt(sum(r * r for r in neg) / len(neg))
    ann = math.sqrt(24 * 365)
    return (mean / sd * ann if sd else None), (mean / dsd * ann if dsd else None)


def compute(db, engine):
    closed = db.closed_trades()
    open_tr = db.open_trades()
    eq = db.q("SELECT time, equity, drawdown_pct FROM equity ORDER BY time")
    cap0 = db.get_state("capital_inicial", C.CAPITAL_INICIAL)
    equity, pos_val = engine.equity(open_tr)
    upnl = sum((engine.prices.get(t["symbol"], t["current_price"] or t["entry_price"]) - t["entry_price"]) * t["qty_open"]
               for t in open_tr)
    realized_partial_open = sum(t["realized_pnl"] for t in open_tr)

    pnls = [t["pnl"] for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gp, gl = sum(wins), -sum(losses)
    n = len(pnls)
    rs = [t["r_multiple"] or 0 for t in closed]
    best_w, best_l, cur_streak = streaks(pnls)
    fees = db.one("SELECT COALESCE(SUM(fee),0) f FROM fills")["f"]

    max_dd = max((e["drawdown_pct"] for e in eq), default=0)
    peak_curve, max_dd_usdt = 0, 0
    for e in eq:
        peak_curve = max(peak_curve, e["equity"])
        max_dd_usdt = max(max_dd_usdt, peak_curve - e["equity"])
    sharpe, sortino = ratios_from_equity(eq)
    created = db.get_state("created_at", engine.started_at)
    days = max((engine.mx.now_ms() - created) / 86_400_000, 1e-9)
    net = equity - cap0

    summary = {
        "capital_inicial": cap0, "equity": equity, "cash": engine.cash, "positions_value": pos_val,
        "net_pnl": net, "return_pct": net / cap0 * 100,
        "realized_pnl": sum(pnls) + realized_partial_open, "unrealized_pnl": upnl,
        "peak": engine.peak, "drawdown_pct": (engine.peak - equity) / engine.peak * 100 if engine.peak else 0,
        "max_drawdown_pct": max_dd, "max_drawdown_usdt": max_dd_usdt,
        "exposure_pct": pos_val / equity * 100 if equity else 0,
        "open_positions": len(open_tr), "max_positions": C.MAX_POSICOES,
        "trades": n, "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / n * 100 if n else None,
        "gross_profit": gp, "gross_loss": gl,
        "profit_factor": gp / gl if gl else (None if not gp else float("inf")),
        "avg_win": gp / len(wins) if wins else None, "avg_loss": -gl / len(losses) if losses else None,
        "payoff": (gp / len(wins)) / (gl / len(losses)) if wins and losses and gl else None,
        "expectancy": sum(pnls) / n if n else None, "avg_r": sum(rs) / n if n else None,
        "total_r": sum(rs),
        "best_trade": max(pnls) if pnls else None, "worst_trade": min(pnls) if pnls else None,
        "max_win_streak": best_w, "max_loss_streak": best_l, "current_streak": cur_streak,
        "avg_duration_min": sum(t["duration_min"] for t in closed) / n if n else None,
        "avg_win_duration_min": (sum(t["duration_min"] for t in closed if t["pnl"] > 0) / len(wins)) if wins else None,
        "avg_loss_duration_min": (sum(t["duration_min"] for t in closed if t["pnl"] <= 0) / len(losses)) if losses else None,
        "avg_mfe_pct": sum(t["mfe_pct"] for t in closed) / n if n else None,
        "avg_mae_pct": sum(t["mae_pct"] for t in closed) / n if n else None,
        "fees": fees, "sharpe": sharpe, "sortino": sortino,
        "recovery_factor": net / max_dd_usdt if max_dd_usdt else None,
        "trades_per_day": n / days, "days_running": days,
        "tp1_rate": sum(1 for t in closed if t["tp1_hit"]) / n * 100 if n else None,
        "volume_traded": db.one("SELECT COALESCE(SUM(notional),0) v FROM fills")["v"],
    }
    if summary["profit_factor"] == float("inf"):
        summary["profit_factor"] = None

    # ── distribuições ──
    by_sym = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0, "r": 0.0})
    by_exit = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    by_hour = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    by_wday = defaultdict(lambda: {"trades": 0, "pnl": 0.0})
    daily = defaultdict(float)
    for t in closed:
        s = by_sym[t["symbol"]]
        s["trades"] += 1
        s["wins"] += t["pnl"] > 0
        s["pnl"] += t["pnl"]
        s["r"] += t["r_multiple"] or 0
        e = by_exit[t["exit_reason"]]
        e["count"] += 1
        e["pnl"] += t["pnl"]
        h = by_hour[int(_dt(t["entry_time"], "%H"))]
        h["trades"] += 1
        h["wins"] += t["pnl"] > 0
        h["pnl"] += t["pnl"]
        w = by_wday[int(_dt(t["entry_time"], "%w"))]
        w["trades"] += 1
        w["pnl"] += t["pnl"]
    for f in db.q("SELECT time, pnl FROM fills WHERE action='SELL'"):
        daily[_dt(f["time"], "%Y-%m-%d")] += f["pnl"]
    buckets = [(-99, -1.5), (-1.5, -1), (-1, -0.5), (-0.5, 0), (0, 0.5), (0.5, 1), (1, 1.5), (1.5, 2), (2, 2.5), (2.5, 99)]
    labels = ["< -1.5R", "-1.5..-1R", "-1..-0.5R", "-0.5..0R", "0..0.5R", "0.5..1R", "1..1.5R", "1.5..2R", "2..2.5R", "> 2.5R"]
    r_hist = [{"label": lb, "count": sum(1 for r in rs if a <= r < b)} for (a, b), lb in zip(buckets, labels)]

    return {
        "summary": summary,
        "by_symbol": sorted(({"symbol": k, **v, "win_rate": v["wins"] / v["trades"] * 100} for k, v in by_sym.items()),
                            key=lambda x: x["pnl"], reverse=True),
        "by_exit": [{"reason": k, **v} for k, v in sorted(by_exit.items(), key=lambda x: -x[1]["count"])],
        "by_hour": [{"hour": h, **by_hour[h]} for h in range(24)],
        "by_weekday": [{"day": d, **by_wday[d]} for d in range(7)],
        "daily": [{"day": k, "pnl": v} for k, v in sorted(daily.items())],
        "r_hist": r_hist,
    }
