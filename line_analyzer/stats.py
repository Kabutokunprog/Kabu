"""AIを使わずに（トークン0で）計算できる数値の分析。

月ごとに、メッセージ数・返信の速さ・どちらから話しかけたか・愛情表現や
ネガティブな言葉の頻度・通話時間・隠語（辞書）の出現数などを数える。
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta

import glossary

LOVE_WORDS = ["好き", "大好き", "愛してる", "愛して", "会いたい", "あいたい", "寂しい", "さみしい",
              "ありがとう", "嬉しい", "うれしい", "可愛い", "かわいい", "ちゅ", "ぎゅ", "おやすみ",
              "♡", "❤", "💕", "💗", "😘", "🥰", "😍"]
NEG_WORDS = ["怒", "ムカ", "むか", "最悪", "もういい", "別れ", "嫌い", "きらい", "うざ", "ウザ",
             "疲れ", "しんどい", "無理", "ごめん", "悲しい", "かなしい", "泣", "😢", "😭", "💢"]
NEW_TOPIC_GAP = timedelta(hours=6)  # これ以上空いたら「新しく話しかけた」とみなす
MAX_REPLY_GAP = timedelta(hours=12)  # これ以上空いた返事は返信速度の計算から除外


def _dt(r) -> datetime:
    return datetime.strptime(f"{r['date']} {r['time']}", "%Y-%m-%d %H:%M")


def count_words(text: str, words) -> int:
    return sum(text.count(w) for w in words)


def monthly(con, start: str | None = None, end: str | None = None) -> dict[str, dict]:
    """{月: {指標: 値}} を返す。start/end は 'YYYY-MM'。"""
    q = "SELECT date,time,month,role,kind,text,call_sec FROM messages WHERE role!='system'"
    args = []
    if start:
        q += " AND month>=?"
        args.append(start)
    if end:
        q += " AND month<=?"
        args.append(end)
    rows = con.execute(q + " ORDER BY date,time,id", args).fetchall()
    gl_terms = glossary.terms_by_category()

    acc: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    replies = defaultdict(lambda: defaultdict(list))
    prev = None
    for r in rows:
        mon, role = r["month"], r["role"]
        a = acc[mon]
        a[f"msgs_{role}"] += 1
        a[f"chars_{role}"] += len(r["text"]) if r["kind"] == "text" else 0
        if r["kind"] == "call":
            a["calls"] += 1
            a["call_min"] += r["call_sec"] / 60
        if r["kind"] == "sticker":
            a[f"stickers_{role}"] += 1
        a[f"love_{role}"] += count_words(r["text"], LOVE_WORDS)
        a[f"neg_{role}"] += count_words(r["text"], NEG_WORDS)
        for cat, terms in gl_terms.items():
            a[f"gl_{cat}"] += count_words(r["text"], terms)
        h = int(r["time"][:2])
        if h >= 23 or h < 4:
            a["late_night"] += 1

        t = _dt(r)
        if prev is None or t - prev[0] >= NEW_TOPIC_GAP:
            a[f"start_{role}"] += 1
        elif prev[1] != role and t - prev[0] <= MAX_REPLY_GAP:
            replies[mon][role].append((t - prev[0]).total_seconds() / 60)
        prev = (t, role)
    days = defaultdict(set)
    for r in rows:
        days[r["month"]].add(r["date"])

    out = {}
    for mon in sorted(acc):
        a = acc[mon]
        res = {k: int(v) if float(v).is_integer() else round(v, 1) for k, v in a.items()}
        res["active_days"] = len(days[mon])
        for role in ("me", "partner"):
            n = a[f"msgs_{role}"] or 1
            res[f"avg_len_{role}"] = round(a[f"chars_{role}"] / n, 1)
            res[f"love_rate_{role}"] = round(a[f"love_{role}"] * 100 / n, 1)
            res[f"neg_rate_{role}"] = round(a[f"neg_{role}"] * 100 / n, 1)
            rr = replies[mon][role]
            res[f"reply_min_{role}"] = round(statistics.median(rr), 1) if rr else None
        out[mon] = res
    return out


LABELS = [
    ("msgs_me", "{me}の件数"), ("msgs_partner", "{pa}の件数"),
    ("active_days", "会話した日数"),
    ("start_me", "{me}から話しかけ"), ("start_partner", "{pa}から話しかけ"),
    ("reply_min_me", "{me}の返信(中央値・分)"), ("reply_min_partner", "{pa}の返信(中央値・分)"),
    ("love_rate_me", "{me}の愛情表現/100通"), ("love_rate_partner", "{pa}の愛情表現/100通"),
    ("neg_rate_me", "{me}のネガ表現/100通"), ("neg_rate_partner", "{pa}のネガ表現/100通"),
    ("calls", "通話回数"), ("call_min", "通話(分)"), ("late_night", "深夜のやりとり"),
]


def compact_table(stats: dict[str, dict], settings) -> str:
    """AIに渡す用の、トークンの少ない表（CSV風）。"""
    me, pa = settings["me_label"], settings["partner_label"]
    keys = [k for k, _ in LABELS]
    gl_keys = sorted({k for s in stats.values() for k in s if k.startswith("gl_")})
    head = ["月"] + [lab.format(me=me, pa=pa) for _, lab in LABELS] + \
           [f"隠語[{k[3:]}]" for k in gl_keys]
    lines = [",".join(head)]
    for mon, s in stats.items():
        vals = [mon] + ["" if s.get(k) is None else str(s.get(k, 0)) for k in keys + gl_keys]
        lines.append(",".join(vals))
    return "\n".join(lines)


def print_table(stats: dict[str, dict], settings) -> None:
    me, pa = settings["me_label"], settings["partner_label"]
    cols = [("msgs_me", f"{me}件数"), ("msgs_partner", f"{pa}件数"),
            ("start_me", f"{me}発"), ("start_partner", f"{pa}発"),
            ("reply_min_me", f"{me}返信分"), ("reply_min_partner", f"{pa}返信分"),
            ("love_rate_me", f"{me}愛%"), ("love_rate_partner", f"{pa}愛%"),
            ("neg_rate_me", f"{me}ネガ%"), ("neg_rate_partner", f"{pa}ネガ%"),
            ("call_min", "通話分")]
    print("月      " + " ".join(f"{lab:>8}" for _, lab in cols))
    for mon, s in stats.items():
        cells = []
        for k, _ in cols:
            v = s.get(k)
            cells.append(f"{'-' if v is None else v:>10}")
        print(mon + " " + "".join(cells))
