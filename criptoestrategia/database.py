"""Base de dados SQLite: trades, execuções (fills), curva de equity, universo, sinais, eventos e estado."""
import json
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,                         -- contrato de futuros, ex.: BTC_USDT
    side TEXT NOT NULL,                           -- LONG / SHORT
    leverage REAL NOT NULL,                       -- alavancagem (ex.: 5)
    status TEXT NOT NULL DEFAULT 'OPEN',          -- OPEN / CLOSED
    entry_time INTEGER NOT NULL,                  -- ms UTC
    entry_price REAL NOT NULL,
    contracts REAL NOT NULL,                      -- nº de contratos na entrada
    contracts_open REAL,                          -- nº de contratos ainda abertos
    contract_size REAL NOT NULL,                  -- moedas por contrato
    qty REAL NOT NULL,                            -- quantidade inicial (moedas)
    qty_open REAL NOT NULL,                       -- quantidade ainda aberta (moedas)
    notional REAL NOT NULL,                       -- valor da posição na entrada (USDT)
    margin REAL NOT NULL,                         -- margem isolada (notional / alavancagem)
    entry_fee REAL NOT NULL,
    taker_fee REAL NOT NULL,                      -- taxa real do contrato (MEXC)
    maker_fee REAL NOT NULL,
    initial_sl REAL NOT NULL,
    sl REAL NOT NULL,                             -- stop atual (move com breakeven/trailing)
    tp1 REAL NOT NULL,
    tp2 REAL NOT NULL,
    tp1_hit INTEGER NOT NULL DEFAULT 0,
    liq_price REAL NOT NULL,                      -- preço de liquidação estimado (margem isolada)
    risk_usdt REAL NOT NULL,                      -- 1R em USDT
    atr REAL NOT NULL,
    score REAL,
    entry_reason TEXT,
    market_regime TEXT,                           -- tendência do BTC no 15m na entrada
    highest REAL,                                 -- preço máximo desde a entrada
    lowest REAL,                                  -- preço mínimo desde a entrada
    current_price REAL,
    unrealized_pnl REAL DEFAULT 0,                -- PnL flutuante da parte aberta
    realized_pnl REAL DEFAULT 0,                  -- PnL já realizado (TP1 parcial, funding, saída)
    fees_total REAL DEFAULT 0,
    funding_total REAL DEFAULT 0,                 -- funding pago (−) / recebido (+)
    funding_next INTEGER,                         -- próxima liquidação de funding (ms)
    funding_cycle_h REAL,
    exit_time INTEGER,
    exit_price REAL,                              -- preço médio ponderado de saída
    exit_reason TEXT,
    pnl REAL,                                     -- PnL final líquido (USDT)
    pnl_pct REAL,                                 -- % sobre o notional
    roe_pct REAL,                                 -- % sobre a margem (retorno com alavancagem)
    r_multiple REAL,
    mfe_pct REAL,
    mae_pct REAL,
    duration_min REAL,
    updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS ix_trades_status ON trades(status);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    time INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,          -- BUY / SELL / FUNDING
    kind TEXT NOT NULL,            -- ENTRADA, TP1, TP2, STOP LOSS, TRAILING STOP, FECHO ABAIXO EMA20, FUNDING, ...
    price REAL NOT NULL,
    qty REAL NOT NULL,
    notional REAL NOT NULL,
    fee REAL NOT NULL,
    pnl REAL NOT NULL DEFAULT 0,
    balance_after REAL
);
CREATE TABLE IF NOT EXISTS equity (
    time INTEGER PRIMARY KEY,
    balance REAL, equity REAL, margin_used REAL,
    unrealized_pnl REAL, realized_pnl REAL,
    open_positions INTEGER, exposure_pct REAL, drawdown_pct REAL, peak REAL
);
CREATE TABLE IF NOT EXISTS universe (
    symbol TEXT PRIMARY KEY, rank INTEGER, score REAL, quote_volume REAL,
    volatility_pct REAL, change_pct REAL, last_price REAL, updated_at INTEGER,
    spread_pct REAL, funding_rate REAL, taker_fee REAL, maker_fee REAL
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time INTEGER, symbol TEXT, side TEXT, price REAL, score REAL, decision TEXT, detail TEXT, indicators TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER, level TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


class DB:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ── utilitários ──
    def q(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        r = self.q(sql, params)
        return r[0] if r else None

    def x(self, sql, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur.lastrowid

    def xmany(self, sql, rows):
        with self.lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    def insert(self, table, row):
        cols = ",".join(row)
        ph = ",".join("?" * len(row))
        return self.x(f"INSERT INTO {table} ({cols}) VALUES ({ph})", tuple(row.values()))

    def update(self, table, id_, fields):
        sets = ",".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE {table} SET {sets} WHERE id=?", (*fields.values(), id_))

    # ── estado chave/valor ──
    def get_state(self, key, default=None):
        r = self.one("SELECT value FROM state WHERE key=?", (key,))
        return json.loads(r["value"]) if r else default

    def set_state(self, key, value):
        self.x("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value)))

    def event(self, t, level, msg):
        self.x("INSERT INTO events(time,level,message) VALUES(?,?,?)", (t, level, msg))
        print(f"[{level}] {msg}", flush=True)

    def open_trades(self):
        return self.q("SELECT * FROM trades WHERE status='OPEN' ORDER BY entry_time")

    def closed_trades(self):
        return self.q("SELECT * FROM trades WHERE status='CLOSED' ORDER BY exit_time")

    def reset(self):
        with self.lock:
            for t in ("trades", "fills", "equity", "universe", "signals", "events", "state"):
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.execute("DELETE FROM sqlite_sequence WHERE 1")
            self.conn.commit()
