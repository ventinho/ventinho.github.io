"""Servidor HTTP do dashboard (biblioteca padrão) + API JSON."""
import csv
import io
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import config as C
import stats

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def make_handler(db, engine):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, default=str, allow_nan=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            qs = {k: v[0] for k, v in parse_qs(u.query).items()}
            limit = min(int(qs.get("limit", 500)), 5000)
            p = u.path
            try:
                if p in ("/", "/index.html"):
                    return self._file("index.html")
                if p.startswith("/static/"):
                    return self._file(p[len("/static/"):])
                if p == "/api/status":
                    return self._send(200, {
                        "source": engine.mx.name, "demo": engine.mx.demo, "now": engine.mx.now_ms(),
                        "paused": engine.paused, "kill": engine.kill, "daily_block": getattr(engine, "daily_block", False),
                        "last_error": engine.last_error, "universe_size": len(engine.universe),
                        "universe_at": engine.last_universe, "last_scan": db.get_state("last_scan"),
                        "running": engine.running,
                    })
                if p == "/api/stats":
                    return self._send(200, _clean(stats.compute(db, engine)))
                if p == "/api/equity":
                    rows = db.q("SELECT * FROM equity ORDER BY time")
                    step = max(1, len(rows) // 1500)
                    rows = rows[::step] + (rows[-1:] if rows and (len(rows) - 1) % step else [])
                    return self._send(200, rows)
                if p == "/api/positions":
                    out = []
                    for t in db.open_trades():
                        px = engine.prices.get(t["symbol"], t["current_price"] or t["entry_price"])
                        upnl = (px - t["entry_price"]) * t["qty_open"]
                        t.update({"price": px, "unrealized_pnl": upnl,
                                  "unrealized_pct": (px / t["entry_price"] - 1) * 100,
                                  "r_now": (upnl + t["realized_pnl"]) / t["risk_usdt"] if t["risk_usdt"] else 0,
                                  "value": px * t["qty_open"],
                                  "dist_sl_pct": (px / t["sl"] - 1) * 100,
                                  "dist_tp_pct": ((t["tp2"] if t["tp1_hit"] else t["tp1"]) / px - 1) * 100,
                                  "age_min": (engine.mx.now_ms() - t["entry_time"]) / 60000})
                        out.append(t)
                    return self._send(200, out)
                if p == "/api/trades":
                    return self._send(200, db.q("SELECT * FROM trades WHERE status='CLOSED' ORDER BY exit_time DESC LIMIT ?", (limit,)))
                if p == "/api/fills":
                    return self._send(200, db.q("SELECT * FROM fills ORDER BY id DESC LIMIT ?", (limit,)))
                if p == "/api/universe":
                    return self._send(200, db.q("SELECT * FROM universe ORDER BY rank"))
                if p == "/api/signals":
                    return self._send(200, db.q("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)))
                if p == "/api/events":
                    return self._send(200, db.q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)))
                if p == "/api/config":
                    return self._send(200, {k: (sorted(v) if isinstance(v, set) else v) for k, v in vars(C).items()
                                            if k.isupper()})
                if p.startswith("/api/export/") and p.endswith(".csv"):
                    table = p[len("/api/export/"):-4]
                    if table not in ("trades", "fills", "equity", "signals", "events", "universe"):
                        return self._send(404, {"error": "tabela desconhecida"})
                    rows = db.q(f"SELECT * FROM {table}")
                    buf = io.StringIO()
                    if rows:
                        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
                        w.writeheader()
                        w.writerows(rows)
                    return self._send(200, buf.getvalue(), "text/csv; charset=utf-8",
                                      {"Content-Disposition": f"attachment; filename={table}.csv"})
                self._send(404, {"error": "not found"})
            except Exception as e:
                self._send(500, {"error": str(e)})

        def do_POST(self):
            p = urlparse(self.path).path
            parts = p.strip("/").split("/")
            if len(parts) >= 3 and parts[:2] == ["api", "control"]:
                cmd = parts[2]
                arg = parts[3] if len(parts) > 3 else None
                if cmd in ("pause", "resume", "closeall") or (cmd == "close" and arg and arg.isdigit()):
                    engine.commands.put((cmd, arg))
                    return self._send(200, {"ok": True, "queued": cmd})
            self._send(400, {"error": "comando inválido"})

        def _file(self, name):
            path = os.path.normpath(os.path.join(STATIC, name))
            if not path.startswith(STATIC) or not os.path.isfile(path):
                return self._send(404, {"error": "not found"})
            with open(path, "rb") as f:
                self._send(200, f.read(), (mimetypes.guess_type(path)[0] or "application/octet-stream") + "; charset=utf-8")

    return H


def _clean(o):
    """Remove NaN/inf para JSON válido."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
        return None
    return o


def serve(db, engine, host, port):
    httpd = ThreadingHTTPServer((host, port), make_handler(db, engine))
    return httpd
