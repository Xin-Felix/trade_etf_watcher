"""SQLite 状态持久化."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from watcher.config import Config
from watcher.models import MinuteBar, OptionContract, Quote, Signal


SCHEMA = """
CREATE TABLE IF NOT EXISTS quote_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    price REAL,
    open REAL,
    high REAL,
    low REAL,
    prev_close REAL,
    volume INTEGER,
    ts TEXT NOT NULL,
    source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_quote_code_ts ON quote_snapshots(code, ts);

CREATE TABLE IF NOT EXISTS minute_bars (
    code TEXT NOT NULL,
    ts TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    source TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (code, ts)
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    signal_key TEXT NOT NULL,
    label TEXT,
    detail TEXT,
    level TEXT,
    ts TEXT,
    ack INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, code, signal_key)
);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(date);

CREATE TABLE IF NOT EXISTS option_contracts (
    option_code TEXT PRIMARY KEY,
    underlying_code TEXT NOT NULL,
    option_name TEXT,
    exchange TEXT,
    option_type TEXT,
    strike REAL,
    expire_date TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_option_underlying ON option_contracts(underlying_code);

CREATE TABLE IF NOT EXISTS option_quotes (
    option_code TEXT PRIMARY KEY,
    underlying_code TEXT NOT NULL,
    option_name TEXT,
    option_type TEXT,
    strike REAL,
    price REAL,
    change_pct REAL,
    volume INTEGER,
    open_interest INTEGER,
    iv REAL,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL,
    ts TEXT,
    expire_date TEXT,
    buy_price REAL,
    buy_vol INTEGER,
    sell_price REAL,
    sell_vol INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_option_quote_underlying ON option_quotes(underlying_code);

CREATE TABLE IF NOT EXISTS state_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- 交易日历（Tushare trade_cal 落地，节假日不轮询；离线也能判断）
CREATE TABLE IF NOT EXISTS trade_calendar (
    cal_date TEXT PRIMARY KEY,   -- YYYYMMDD，只存交易日
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 期权每日快照（收盘后存一次，用于历史 IV/OI 分析、信号回测）
CREATE TABLE IF NOT EXISTS option_daily_snapshot (
    date TEXT NOT NULL,              -- YYYYMMDD
    option_code TEXT NOT NULL,
    underlying_code TEXT NOT NULL,
    option_type TEXT,                -- call/put
    strike REAL,
    expire_date TEXT,
    price REAL,                      -- 收盘价（最后一次行情快照）
    volume INTEGER,
    open_interest INTEGER,
    iv REAL,                         -- 隐含波动率
    delta REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, option_code)
);
CREATE INDEX IF NOT EXISTS idx_ods_underlying ON option_daily_snapshot(underlying_code, date);
CREATE INDEX IF NOT EXISTS idx_ods_date ON option_daily_snapshot(date);
"""


class StateStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (Config.data_dir() / "etf_watcher.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)
            # 增量迁移：option_quotes 补充买卖价量列（T 型报价用）
            cols = {r[1] for r in conn.execute("PRAGMA table_info(option_quotes)")}
            for col, typ in [
                ("buy_price", "REAL"), ("buy_vol", "INTEGER"),
                ("sell_price", "REAL"), ("sell_vol", "INTEGER"),
            ]:
                if col not in cols:
                    conn.execute(f"ALTER TABLE option_quotes ADD COLUMN {col} {typ}")
            conn.commit()

    def save_quote(self, quote: Quote, date: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO quote_snapshots
                (code, name, price, open, high, low, prev_close, volume, ts, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quote.code,
                    quote.name,
                    quote.price,
                    quote.open,
                    quote.high,
                    quote.low,
                    quote.prev_close,
                    quote.volume,
                    quote.ts,
                    quote.source,
                ),
            )
            conn.commit()

    def save_bar(self, bar: MinuteBar, date: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO minute_bars
                (code, ts, open, high, low, close, volume, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (bar.code, bar.ts, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.source),
            )
            conn.commit()

    def save_bars(self, bars: list[MinuteBar], date: str) -> None:
        """批量保存分钟 K（单连接，避免逐条开关连接）."""
        if not bars:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO minute_bars
                (code, ts, open, high, low, close, volume, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(b.code, b.ts, b.open, b.high, b.low, b.close, b.volume, b.source) for b in bars],
            )
            conn.commit()

    def save_signal(self, signal: Signal, date: str) -> bool:
        """保存信号，若当日已存在同名信号则返回 False."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO signals
                (date, code, name, signal_key, label, detail, level, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    date,
                    signal.code,
                    signal.name,
                    signal.key,
                    signal.label,
                    signal.detail,
                    signal.level,
                    signal.ts,
                ),
            )
            conn.commit()
            return cur.rowcount == 1

    def get_today_signals(self, date: str) -> list[Signal]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM signals WHERE date = ? ORDER BY created_at DESC",
                (date,),
            ).fetchall()
        return [self._row_to_signal(dict(r)) for r in rows]

    def get_today_signals_with_ts(self, date: str, code: str | None = None) -> list[dict]:
        """返回今日信号（含 created_at）。code 为 None 时返回全部标的."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if code:
                rows = conn.execute(
                    "SELECT * FROM signals WHERE date = ? AND code = ? ORDER BY created_at",
                    (date, code),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM signals WHERE date = ? ORDER BY created_at DESC",
                    (date,),
                ).fetchall()
        return [dict(r) for r in rows]

    def ack_signal(self, signal_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE signals SET ack = 1 WHERE id = ?", (signal_id,))
            conn.commit()

    def latest_quotes(self) -> dict[str, Quote]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT qs.* FROM quote_snapshots qs
                INNER JOIN (
                    SELECT code, MAX(created_at) as max_ca FROM quote_snapshots GROUP BY code
                ) m ON qs.code = m.code AND qs.created_at = m.max_ca
                """
            ).fetchall()
        return {r["code"]: self._row_to_quote(dict(r)) for r in rows}

    def get_bars(self, code: str, limit: int = 120) -> list[MinuteBar]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM minute_bars WHERE code = ? ORDER BY ts DESC LIMIT ?",
                (code, limit),
            ).fetchall()
        return [self._row_to_bar(dict(r)) for r in reversed(rows)]

    def get_option_bars(self, code: str, limit: int = 240, source: str = "%option%") -> list[MinuteBar]:
        """获取期权合约的分钟/日 K 线.

        source 为 SQL LIKE 模式：默认 '%option%' 匹配全部期权源
        （eastmoney_option / sina_option / sina_option_daily），聚合前务必按源过滤.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM minute_bars WHERE code = ? AND source LIKE ? ORDER BY ts DESC LIMIT ?",
                (code, source, limit),
            ).fetchall()
        return [self._row_to_bar(dict(r)) for r in reversed(rows)]

    def cleanup_old_data(self, quotes_days: int = 7, bars_days: int = 30) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM quote_snapshots WHERE created_at < datetime('now', '-{} days')".format(quotes_days)
            )
            conn.execute(
                "DELETE FROM minute_bars WHERE updated_at < datetime('now', '-{} days')".format(bars_days)
            )
            conn.commit()

    def _row_to_quote(self, r: dict) -> Quote:
        return Quote(
            code=r["code"],
            name=r["name"] or r["code"],
            price=r["price"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            prev_close=r["prev_close"],
            volume=r.get("volume", 0) or 0,
            ts=r["ts"],
            source=r.get("source", ""),
        )

    def _row_to_bar(self, r: dict) -> MinuteBar:
        return MinuteBar(
            code=r["code"],
            ts=r["ts"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r.get("volume", 0) or 0,
            source=r.get("source", ""),
        )

    def save_option_contracts(self, contracts: list[OptionContract]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO option_contracts
                (option_code, underlying_code, option_name, exchange, option_type, strike, expire_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        c.option_code,
                        c.underlying_code,
                        c.option_name,
                        c.exchange,
                        c.option_type,
                        c.strike,
                        c.expire_date,
                    )
                    for c in contracts
                ],
            )
            conn.commit()

    def get_option_contracts(self, underlying_code: str) -> list[OptionContract]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM option_contracts WHERE underlying_code = ? ORDER BY expire_date, strike, option_type",
                (underlying_code,),
            ).fetchall()
        return [self._row_to_contract(r) for r in rows]

    def get_option_contracts_by_code(self, option_code: str) -> list[OptionContract]:
        """按期权合约代码查（返回列表是为了兼容多合约场景，通常只有 1 条）."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM option_contracts WHERE option_code = ?",
                (option_code,),
            ).fetchall()
        return [self._row_to_contract(r) for r in rows]

    def _row_to_contract(self, r) -> OptionContract:
        return OptionContract(
            option_code=r["option_code"],
            underlying_code=r["underlying_code"],
            option_name=r["option_name"] or r["option_code"],
            exchange=r["exchange"] or "",
            option_type=r["option_type"],
            strike=r["strike"],
            expire_date=r["expire_date"] or "",
        )

    def save_option_quotes(self, quotes: list[dict]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO option_quotes
                (option_code, underlying_code, option_name, option_type, strike, price, change_pct,
                 volume, open_interest, iv, delta, gamma, theta, vega, ts, expire_date,
                 buy_price, buy_vol, sell_price, sell_vol)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        q.get("option_code", ""),
                        q.get("underlying_code", ""),
                        q.get("name", ""),
                        q.get("option_type", ""),
                        q.get("strike", 0.0),
                        q.get("price", 0.0),
                        q.get("change_pct", 0.0),
                        q.get("volume", 0),
                        q.get("open_interest", 0),
                        q.get("iv", 0.0),
                        q.get("delta", 0.0),
                        q.get("gamma", 0.0),
                        q.get("theta", 0.0),
                        q.get("vega", 0.0),
                        q.get("ts", ""),
                        q.get("expire_date", ""),
                        q.get("buy_price", 0.0),
                        q.get("buy_vol", 0),
                        q.get("sell_price", 0.0),
                        q.get("sell_vol", 0),
                    )
                    for q in quotes
                ],
            )
            conn.commit()

    def get_option_quotes(self, underlying_code: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM option_quotes
                WHERE underlying_code = ?
                ORDER BY expire_date, strike, option_type
                """,
                (underlying_code,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_option_quote(self, option_code: str) -> Optional[dict]:
        """单个期权合约的最新行情（K 线图信息面板用）."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM option_quotes WHERE option_code = ?",
                (option_code,),
            ).fetchone()
        return dict(row) if row else None

    def save_option_daily_snapshot(self, date_str: str) -> int:
        """将当前 option_quotes 表中的数据存入每日快照表（收盘后调用一次）.

        返回写入的记录数。重复调用同一天会 REPLACE（幂等）。
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM option_quotes").fetchall()
            if not rows:
                return 0
            conn.executemany(
                """
                INSERT OR REPLACE INTO option_daily_snapshot
                (date, option_code, underlying_code, option_type, strike, expire_date,
                 price, volume, open_interest, iv, delta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        date_str,
                        r["option_code"],
                        r["underlying_code"],
                        r["option_type"],
                        r["strike"],
                        r["expire_date"],
                        r["price"],
                        r["volume"],
                        r["open_interest"],
                        r["iv"],
                        r["delta"],
                    )
                    for r in rows
                    if r["price"] and r["price"] > 0  # 跳过无行情的合约
                ],
            )
            conn.commit()
            return len(rows)

    def get_option_daily_history(self, underlying_code: str, days: int = 60) -> list[dict]:
        """获取指定标的的每日快照历史（用于 IV/OI 趋势分析）."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM option_daily_snapshot
                WHERE underlying_code = ?
                ORDER BY date DESC, strike, option_type
                LIMIT ?
                """,
                (underlying_code, days * 50),  # 每天约 50 个合约
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 提醒偏好 ----------

    def get_alert_codes(self) -> set[str]:
        """获取用户勾选了"提醒"的标的代码集合。空集=全部提醒（初始状态）."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM state_meta WHERE key = 'alert_codes'"
            ).fetchone()
        if not row or not row[0]:
            return set()
        return set(row[0].split(","))

    def set_alert_codes(self, codes: set[str]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO state_meta (key, value) VALUES ('alert_codes', ?)",
                (",".join(sorted(codes)),),
            )
            conn.commit()

    def toggle_alert(self, code: str) -> bool:
        """切换一个标的的提醒状态，返回切换后是否开启."""
        codes = self.get_alert_codes()
        if code in codes:
            codes.discard(code)
            on = False
        else:
            codes.add(code)
            on = True
        self.set_alert_codes(codes)
        return on

    def should_alert(self, code: str) -> bool:
        """该标的是否应弹窗提醒。空集=全部提醒（向后兼容）."""
        codes = self.get_alert_codes()
        return code in codes if codes else True

    # ---------- 交易日历 ----------

    def save_trade_dates(self, dates: list[str]) -> int:
        """写入交易日（幂等）。返回写入条数."""
        rows = [(d,) for d in dates if len(d) == 8 and d.isdigit()]
        if not rows:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO trade_calendar (cal_date) VALUES (?)", rows
            )
            conn.commit()
        return len(rows)

    def trade_dates(self, start: str = "", end: str = "") -> list[str]:
        sql = "SELECT cal_date FROM trade_calendar"
        args: list[str] = []
        conds = []
        if start:
            conds.append("cal_date >= ?")
            args.append(start)
        if end:
            conds.append("cal_date <= ?")
            args.append(end)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY cal_date"
        with sqlite3.connect(self.db_path) as conn:
            return [r[0] for r in conn.execute(sql, args).fetchall()]

    def has_trade_calendar(self) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            return bool(conn.execute("SELECT 1 FROM trade_calendar LIMIT 1").fetchone())

    def is_trade_date(self, day: str) -> bool | None:
        """是否交易日。日历里没有覆盖该日期时返回 None（表示"不知道"）."""
        d = (day or "").replace("-", "")
        if len(d) != 8:
            return None
        with sqlite3.connect(self.db_path) as conn:
            hit = conn.execute(
                "SELECT 1 FROM trade_calendar WHERE cal_date = ?", (d,)
            ).fetchone()
            if hit:
                return True
            # 该日期落在已知区间内但不在表里 → 明确是非交易日
            bounds = conn.execute(
                "SELECT MIN(cal_date), MAX(cal_date) FROM trade_calendar"
            ).fetchone()
        if not bounds or not bounds[0]:
            return None
        return False if bounds[0] <= d <= bounds[1] else None

    def option_underlyings(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT underlying_code FROM option_contracts ORDER BY underlying_code"
            ).fetchall()
        return [r[0] for r in rows]

    def _row_to_quote(self, r: dict) -> Quote:
        return Quote(
            code=r["code"],
            name=r["name"] or r["code"],
            price=r["price"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            prev_close=r["prev_close"],
            volume=r.get("volume", 0) or 0,
            ts=r["ts"],
            source=r.get("source", ""),
        )

    def _row_to_bar(self, r: dict) -> MinuteBar:
        return MinuteBar(
            code=r["code"],
            ts=r["ts"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r.get("volume", 0) or 0,
            source=r.get("source", ""),
        )

    def _row_to_signal(self, r: dict) -> Signal:
        return Signal(
            key=r["signal_key"],
            code=r["code"],
            name=r["name"] or r["code"],
            label=r["label"] or r["signal_key"],
            detail=r["detail"] or "",
            level=r["level"] or "warning",
            ts=r["ts"] or "",
        )
