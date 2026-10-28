"""SQLiteデータベース（秘密フォルダ内の talk.db）の読み書き。

同じメッセージには同じ識別子(uid)を付けるので、新しいエクスポートを丸ごと
取り込んでも、まだ無いメッセージ（差分）だけが追加される。
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from datetime import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE,
    date TEXT, time TEXT, month TEXT,
    sender TEXT, role TEXT,          -- role: me / partner / system
    kind TEXT, text TEXT, call_sec INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_msg_date ON messages(date, time);
CREATE INDEX IF NOT EXISTS idx_msg_month ON messages(month);

CREATE TABLE IF NOT EXISTS events (       -- MedicationReminder 等の記録
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE,
    date TEXT, time TEXT, month TEXT,
    kind TEXT, category TEXT, value TEXT, note TEXT, source TEXT
);
CREATE INDEX IF NOT EXISTS idx_ev_date ON events(date);

CREATE TABLE IF NOT EXISTS summaries (    -- 月ごとのAI要約（キャッシュ）
    month TEXT PRIMARY KEY,
    sig TEXT, json TEXT, model TEXT, created TEXT
);

CREATE TABLE IF NOT EXISTS usage (        -- トークン使用量の記録
    id INTEGER PRIMARY KEY,
    ts TEXT, purpose TEXT, model TEXT,
    input_tokens INTEGER, output_tokens INTEGER,
    cache_read INTEGER, cache_write INTEGER
);
"""


def connect() -> sqlite3.Connection:
    path = config.db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    config.secure(path)
    return con


def _uid(*parts) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()


def role_of(sender, settings) -> str:
    if sender is None:
        return "system"
    if sender == settings["me_name"]:
        return "me"
    if sender == settings["partner_name"]:
        return "partner"
    return "system"


def import_messages(con, msgs, settings) -> tuple[int, set[str]]:
    """差分だけを追加し、(追加件数, 追加があった月の集合) を返す。"""
    seen = Counter()
    added = 0
    months = set()
    for m in msgs:
        key = (m.date, m.time, m.sender, m.text)
        seen[key] += 1  # 同じ分に同じ文面が複数ある場合を区別
        uid = _uid(*key, seen[key])
        month = m.date[:7]
        cur = con.execute(
            "INSERT OR IGNORE INTO messages(uid,date,time,month,sender,role,kind,text,call_sec)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (uid, m.date, m.time, month, m.sender, role_of(m.sender, settings),
             m.kind, m.text, m.call_sec),
        )
        if cur.rowcount:
            added += 1
            months.add(month)
    con.commit()
    return added, months


def refresh_roles(con, settings) -> None:
    """名前の設定を変えたときに、全メッセージの送信者区分を付け直す。"""
    for sender, in con.execute("SELECT DISTINCT sender FROM messages").fetchall():
        con.execute("UPDATE messages SET role=? WHERE sender IS ?",
                    (role_of(sender, settings), sender))
    con.commit()


def import_events(con, events) -> int:
    added = 0
    for e in events:
        uid = _uid(e["date"], e["time"], e["kind"], e["value"], e["note"], e["source"])
        cur = con.execute(
            "INSERT OR IGNORE INTO events(uid,date,time,month,kind,category,value,note,source)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (uid, e["date"], e["time"], e["date"][:7], e["kind"], e["category"],
             e["value"], e["note"], e["source"]),
        )
        added += cur.rowcount
    con.commit()
    return added


def months(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT DISTINCT month FROM messages ORDER BY month")]


def month_signature(con, month: str) -> str:
    """その月のデータが変わったかを判定する目印（件数ベース）。"""
    n = con.execute("SELECT COUNT(*) FROM messages WHERE month=?", (month,)).fetchone()[0]
    e = con.execute("SELECT COUNT(*) FROM events WHERE month=?", (month,)).fetchone()[0]
    return f"{n}:{e}"


def log_usage(con, purpose, model, usage) -> None:
    con.execute(
        "INSERT INTO usage(ts,purpose,model,input_tokens,output_tokens,cache_read,cache_write)"
        " VALUES(?,?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), purpose, model,
         getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0,
         getattr(usage, "cache_read_input_tokens", 0) or 0,
         getattr(usage, "cache_creation_input_tokens", 0) or 0),
    )
    con.commit()
