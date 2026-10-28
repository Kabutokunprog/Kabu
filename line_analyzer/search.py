"""キーワード検索（AI不使用・無料・オフライン）。

キーワードを含む会話を、前後の会話つきで日付順に一覧表示する。
複数のキーワードを渡したときは、すべてを含む発言だけを探す。
"""
from __future__ import annotations

from datetime import date

import glossary

WEEK = "月火水木金土日"
KIND_LABEL = {"sticker": "[スタンプ]", "photo": "[写真]", "video": "[動画]", "voice": "[ボイス]",
              "file": "[ファイル]", "location": "[位置情報]", "unsent": "[送信取消]"}


def _body(r) -> str:
    if r["kind"] == "call":
        return f"[通話 {r['call_sec'] // 60}分]" if r["call_sec"] else "[通話/不在]"
    return KIND_LABEL.get(r["kind"], r["text"].replace("\n", " ⏎ "))


def find(con, words, start=None, end=None, limit=200):
    """(当たった発言の一覧, 当たった総数) を返す。"""
    cond = " AND ".join("text LIKE ?" for _ in words)
    q = f"FROM messages WHERE role!='system' AND kind='text' AND {cond}"
    args = [f"%{w}%" for w in words]
    if start:
        q += " AND month>=?"
        args.append(start)
    if end:
        q += " AND month<=?"
        args.append(end)
    total = con.execute("SELECT COUNT(*) " + q, args).fetchone()[0]
    rows = con.execute("SELECT * " + q + " ORDER BY date,time,id LIMIT ?", args + [limit]).fetchall()
    return rows, total


def neighbors(con, r, n: int):
    """その発言の前後 n 通（日付・時刻の順）。"""
    key = (r["date"], r["time"], r["id"])
    before = con.execute(
        "SELECT * FROM messages WHERE role!='system' AND (date,time,id) < (?,?,?)"
        " ORDER BY date DESC,time DESC,id DESC LIMIT ?", key + (n,)).fetchall()
    after = con.execute(
        "SELECT * FROM messages WHERE role!='system' AND (date,time,id) > (?,?,?)"
        " ORDER BY date,time,id LIMIT ?", key + (n,)).fetchall()
    return list(reversed(before)) + [r] + list(after)


def glossary_notes(words) -> list[str]:
    items = {i["term"]: i for i in glossary.load()}
    out = []
    for w in words:
        i = items.get(w)
        if i:
            mark = "" if i.get("confirmed") else "（推測）"
            out.append(f"「{w}」= {i.get('private') or i['meaning']}{mark}")
    return out


def render(con, words, settings, start=None, end=None, context: int = 1, limit: int = 200) -> str:
    label = {"me": settings["me_label"], "partner": settings["partner_label"]}
    lines = [f"辞書: {n}" for n in glossary_notes(words)]
    hits, total = find(con, words, start, end, limit)
    if not hits:
        lines.append(f"「{' '.join(words)}」を含む会話は見つかりませんでした。")
        return "\n".join(lines)

    hit_ids = {r["id"] for r in hits}
    # 前後の会話をまとめ、重なる部分は1つの塊にする
    blocks: list[list] = []
    for r in hits:
        rows = neighbors(con, r, context)
        if blocks and rows[0]["id"] in {x["id"] for x in blocks[-1]}:
            seen = {x["id"] for x in blocks[-1]}
            blocks[-1] += [x for x in rows if x["id"] not in seen]
        else:
            blocks.append(rows)

    if lines:
        lines.append("")
    for b in blocks:
        last_date = None
        for x in b:
            if x["date"] != last_date:
                y, m, d = map(int, x["date"].split("-"))
                lines.append(f"── {y}年{m}月{d}日({WEEK[date(y, m, d).weekday()]}) ──")
                last_date = x["date"]
            mark = "▶" if x["id"] in hit_ids else " "
            lines.append(f"{mark} {x['time']} {label.get(x['role'], '?')}: {_body(x)}")
        lines.append("")
    more = f"（先頭の{limit}件だけ表示。--limit で増やせます）" if total > limit else ""
    lines.append(f"見つかった発言: {total}件{more}")
    return "\n".join(lines)
