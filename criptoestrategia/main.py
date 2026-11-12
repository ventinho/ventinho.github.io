"""
CriptoEstratégia — bot de paper trading nos FUTUROS da MEXC (5x) com dashboard.

  python main.py              -> dados reais da MEXC Futuros, entradas fictícias, dashboard em http://0.0.0.0:8050
  python main.py --reset      -> apaga a base de dados e recomeça com o capital inicial
"""
import argparse
import os
import threading
import webbrowser

import config as C
from database import DB
from engine import Engine
from exchange import MexcFutures
from server import serve


def main():
    ap = argparse.ArgumentParser(description="CriptoEstratégia paper-trading bot")
    ap.add_argument("--reset", action="store_true", help="apagar o histórico e recomeçar")
    ap.add_argument("--port", type=int, default=int(os.environ.get("CE_PORT", C.PORTA_DASHBOARD)))
    ap.add_argument("--host", default=os.environ.get("CE_HOST", C.HOST_DASHBOARD))
    ap.add_argument("--db", default=os.environ.get("CE_DB"), help="caminho da base de dados")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    db_path = args.db or os.path.join(here, C.DB_PATH)
    db = DB(db_path)
    if args.reset:
        db.reset()
        print("Base de dados limpa.")

    market = MexcFutures()
    try:
        market.ping()
    except Exception as e:
        print(f"\n  AVISO: não consegui ligar à API da MEXC ({e}).\n  Verifica a ligação à internet. O bot vai continuar a tentar.\n")
    engine = Engine(db, market)
    stop = threading.Event()
    bot = threading.Thread(target=engine.run, args=(stop,), daemon=True, name="bot")
    bot.start()

    httpd = serve(db, engine, args.host, args.port)
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    lan = f"\n  Na rede local: http://192.168.1.64:{args.port}" if args.host == "0.0.0.0" else ""
    print(f"\n  CriptoEstratégia a correr — {market.name} · {C.ALAVANCAGEM}x\n  Dashboard: {url}{lan}"
          f"\n  Base de dados: {db_path}\n  Ctrl+C para parar.\n")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nA parar...")
    finally:
        stop.set()
        httpd.server_close()
        bot.join(timeout=15)


if __name__ == "__main__":
    main()
