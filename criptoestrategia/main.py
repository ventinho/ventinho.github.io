"""
CriptoEstratégia — bot de paper trading na MEXC com dashboard.

  python main.py              -> dados reais da MEXC, entradas fictícias, dashboard em http://localhost:8050
  python main.py --demo       -> mercado simulado acelerado (testar sem internet)
  python main.py --reset      -> apaga a base de dados e recomeça com o capital inicial
"""
import argparse
import os
import threading
import webbrowser

import config as C
from database import DB
from engine import Engine
from exchange import MexcClient, SimMarket
from server import serve


def main():
    ap = argparse.ArgumentParser(description="CriptoEstratégia paper-trading bot")
    ap.add_argument("--demo", action="store_true", help="usar mercado simulado (sem internet)")
    ap.add_argument("--reset", action="store_true", help="apagar o histórico e recomeçar")
    ap.add_argument("--port", type=int, default=C.PORTA_DASHBOARD)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--db", default=None, help="caminho da base de dados")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    db_path = args.db or os.path.join(here, ("demo_" if args.demo else "") + C.DB_PATH)
    db = DB(db_path)
    if args.reset:
        db.reset()
        print("Base de dados limpa.")

    market = SimMarket() if args.demo else MexcClient()
    engine = Engine(db, market)
    stop = threading.Event()
    bot = threading.Thread(target=engine.run, args=(stop,), daemon=True, name="bot")
    bot.start()

    httpd = serve(db, engine, args.host, args.port)
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print(f"\n  CriptoEstratégia a correr — fonte: {market.name}\n  Dashboard: {url}\n  Base de dados: {db_path}\n  Ctrl+C para parar.\n")
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
