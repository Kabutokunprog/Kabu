"""MedicationReminder など、別アプリの記録（CSV / JSON）の取り込みと、会話との関連分析。

列名は自動で推測する（日付・種類・値・メモ）。アプリの出力形式が分かれば
COLUMN_HINTS にその列名を足すだけで対応できる。
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import date as Date, datetime, timedelta

import stats as st

COLUMN_HINTS = {
    "datetime": ["datetime", "timestamp", "日時", "taken_at", "created_at", "date_time", "recorded_at"],
    "date": ["date", "日付", "day"],
    "time": ["time", "時刻", "時間"],
    "kind": ["type", "kind", "種類", "event", "項目", "name", "category", "medication", "title"],
    "value": ["value", "値", "level", "強さ", "dose", "score", "amount", "intensity", "程度"],
    "note": ["note", "notes", "memo", "メモ", "comment", "備考", "description"],
}

CATEGORY_WORDS = {
    "intimacy": ["交渉", "性交", "セックス", "sex", "intercourse", "エッチ", "えっち", "営み"],
    "pain": ["痛", "pain", "ache", "疼"],
    "period": ["生理", "月経", "period", "menstru"],
    "medication": ["薬", "服用", "服薬", "pill", "dose", "taken", "錠", "medication"],
    "mood": ["気分", "mood", "イライラ", "落ち込"],
}


def categorize(*texts) -> str:
    t = " ".join(str(x) for x in texts if x).lower()
    for cat, words in CATEGORY_WORDS.items():
        if any(w.lower() in t for w in words):
            return cat
    return "other"


def _find(cols, key):
    low = {c.lower().strip(): c for c in cols}
    for h in COLUMN_HINTS[key]:
        if h.lower() in low:
            return low[h.lower()]
    return None


def _parse_dt(s) -> datetime | None:
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)) or str(s).isdigit():
        v = float(s)
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v)
    s = str(s).strip().replace("Z", "").replace("T", " ")
    s = s.split("+")[0].split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
                "%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日 %H:%M", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def load_records(path: str) -> list[dict]:
    if path.lower().endswith(".json"):
        data = json.load(open(path, encoding="utf-8-sig"))
        if isinstance(data, dict):  # {"records": [...]} のような形
            data = next((v for v in data.values() if isinstance(v, list)), [])
        return [r for r in data if isinstance(r, dict)]
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def to_events(records: list[dict], source: str) -> tuple[list[dict], dict]:
    if not records:
        return [], {}
    cols = list(records[0].keys())
    m = {k: _find(cols, k) for k in COLUMN_HINTS}
    events = []
    for r in records:
        dt = _parse_dt(r.get(m["datetime"])) if m["datetime"] else None
        if dt is None and m["date"]:
            d = r.get(m["date"])
            t = r.get(m["time"]) if m["time"] else ""
            dt = _parse_dt(f"{d} {t}".strip()) or _parse_dt(d)
        if dt is None:
            continue
        kind = str(r.get(m["kind"], "") or "") if m["kind"] else ""
        value = str(r.get(m["value"], "") or "") if m["value"] else ""
        note = str(r.get(m["note"], "") or "") if m["note"] else ""
        if not kind and not m["kind"]:
            # 種類の列がなければ、残りの列をまとめてメモにする
            note = note or " ".join(f"{k}={v}" for k, v in r.items() if v and k not in m.values())
        events.append({
            "date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M"),
            "kind": kind, "category": categorize(kind, note), "value": value,
            "note": note, "source": source,
        })
    return events, m


def events_text(con, start: str | None, end: str | None, limit: int = 120) -> str:
    """期間内の記録を、AIに渡す用に短くまとめる。"""
    q, args = "SELECT date,category,kind,value,note FROM events WHERE 1=1", []
    if start:
        q += " AND month>=?"
        args.append(start)
    if end:
        q += " AND month<=?"
        args.append(end)
    rows = con.execute(q + " AND category!='medication' ORDER BY date,time", args).fetchall()
    if not rows:
        return ""
    lines = []
    for r in rows[:limit]:
        extra = " ".join(x for x in (r["kind"], r["value"], r["note"][:40]) if x)
        lines.append(f"{r['date'][5:]} [{r['category']}] {extra}")
    if len(rows) > limit:
        lines.append(f"…ほか{len(rows) - limit}件")
    return "\n".join(lines)


def _daily_chat(con) -> dict[str, dict]:
    out = defaultdict(lambda: {"msgs": 0, "love": 0, "neg": 0})
    for r in con.execute("SELECT date,text FROM messages WHERE role!='system'"):
        d = out[r["date"]]
        d["msgs"] += 1
        d["love"] += st.count_words(r["text"], st.LOVE_WORDS)
        d["neg"] += st.count_words(r["text"], st.NEG_WORDS)
    return out


def correlate(con, window: int = 2) -> str:
    """記録のあった日の前後と、普段の会話を比べる（AIを使わない）。"""
    daily = _daily_chat(con)
    if not daily:
        return "会話データがありません。"
    days = sorted(daily)
    d0, d1 = Date.fromisoformat(days[0]), Date.fromisoformat(days[-1])
    all_days = [(d0 + timedelta(i)).isoformat() for i in range((d1 - d0).days + 1)]

    def mean(vals):
        return round(statistics.mean(vals), 1) if vals else 0

    def summarize(day_list):
        ms = [daily[d]["msgs"] if d in daily else 0 for d in day_list]
        lv = [daily[d]["love"] * 100 / daily[d]["msgs"] for d in day_list if daily.get(d, {}).get("msgs")]
        ng = [daily[d]["neg"] * 100 / daily[d]["msgs"] for d in day_list if daily.get(d, {}).get("msgs")]
        return mean(ms), mean(lv), mean(ng)

    base = summarize(all_days)
    lines = [f"比較の基準（全期間の1日平均）: 件数{base[0]} / 愛情表現{base[1]}% / ネガ表現{base[2]}%", ""]
    lines.append("記録の種類      | 回数 | 区間          | 1日件数 | 愛情% | ネガ%")
    cats = [r[0] for r in con.execute(
        "SELECT category FROM events WHERE category!='medication' GROUP BY category ORDER BY COUNT(*) DESC")]
    for cat in cats:
        ev_days = sorted({r[0] for r in con.execute("SELECT date FROM events WHERE category=?", (cat,))})
        ev_days = [d for d in ev_days if days[0] <= d <= days[-1]]
        if not ev_days:
            continue
        sets = {"前(-%d〜-1日)" % window: [], "当日": [], "後(+1〜+%d日)" % window: []}
        for d in ev_days:
            dd = Date.fromisoformat(d)
            sets["当日"].append(d)
            for k in range(1, window + 1):
                sets["前(-%d〜-1日)" % window].append((dd - timedelta(k)).isoformat())
                sets["後(+1〜+%d日)" % window].append((dd + timedelta(k)).isoformat())
        for label, dl in sets.items():
            m, lv, ng = summarize(dl)
            lines.append(f"{cat:<14} | {len(ev_days):>4} | {label:<12} | {m:>7} | {lv:>5} | {ng:>5}")
    if not cats:
        lines.append("（記録がまだ取り込まれていません）")
    return "\n".join(lines)
