"""二人だけの言葉（隠語・あだ名・合言葉）の辞書。

秘密フォルダの glossary.json に保存する。中身は次の形の一覧:
  {"term": "言葉", "meaning": "AIに伝える意味（やわらかめ）", "private": "本当の意味（自分用・AIには送らない）",
   "category": "intimacy", "importance": 3, "sexy": 0, "confirmed": true}
importance = 重要度(1〜5、高いものからAIに伝える) / sexy = セクシー度(0〜5、集計の「色っぽさ」に使う)
category の例: intimacy(性生活) / affection(愛情表現) / nickname(呼び名) /
place(場所) / health(体調) / other
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

import config

CATEGORIES = ["intimacy", "affection", "nickname", "place", "health", "other"]


def load() -> list[dict]:
    p = config.glossary_path()
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def save(items: list[dict]) -> None:
    p = config.glossary_path()
    items = sorted(items, key=lambda x: (x.get("category", ""), x["term"]))
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    config.secure(p)


def add(term: str, meaning: str, category: str = "other") -> None:
    items = [i for i in load() if i["term"] != term]
    items.append({"term": term, "meaning": meaning, "category": category, "confirmed": True})
    save(items)


def terms_by_category(confirmed_only: bool = False) -> dict[str, list[str]]:
    out = defaultdict(list)
    for i in load():
        if confirmed_only and not i.get("confirmed"):
            continue
        out[i.get("category", "other")].append(i["term"])
    return dict(out)


def sexy_weights() -> dict[str, int]:
    """セクシー度が1以上の言葉と、その度合い（AI不使用の集計用）。"""
    return {i["term"]: int(i.get("sexy") or 0) for i in load() if int(i.get("sexy") or 0) > 0}


def as_prompt_text() -> str:
    """AIに渡す辞書。本当の意味（private）は渡さず、重要度の高い順に並べる。"""
    items = sorted(load(), key=lambda i: -int(i.get("importance") or 3))
    if not items:
        return "（登録なし）"
    lines = []
    for i in items:
        mark = "" if i.get("confirmed") else "（推測）"
        extra = f" 重要度{i.get('importance', 3)}"
        if int(i.get("sexy") or 0):
            extra += f" 色っぽさ{i['sexy']}/5"
        lines.append(f"- 「{i['term']}」= {i['meaning']} [{i.get('category', 'other')}{extra}]{mark}")
    return "\n".join(lines)


# ---- 隠語の候補探し（ここまではAIを使わない） ----

KATA_RE = re.compile(r"[ァ-ヴー]{2,10}")
COMMON = set("""ありがとう おはよう おやすみ おつかれ りょうかい はーい うん はい
ごめん ごめんね おけ OK ok わかった いいよ そうだね そうなの ほんと えー
ねー まじ マジ スタンプ 写真 動画 了解 了解です""".split())


def local_candidates(con, top: int = 80) -> list[tuple[str, int]]:
    """よく使われる短い決まり文句やカタカナ語を、隠語の候補として拾う。"""
    short = Counter()
    kata = Counter()
    for (text,) in con.execute(
            "SELECT text FROM messages WHERE kind='text' AND role!='system'"):
        t = text.strip()
        if 1 < len(t) <= 10 and "\n" not in t:
            short[t] += 1
        for w in KATA_RE.findall(t):
            kata[w] += 1
    known = {i["term"] for i in load()}
    merged = Counter()
    for w, n in list(short.items()) + list(kata.items()):
        if w not in COMMON and w not in known and n >= 3:
            merged[w] = max(merged[w], n)
    return merged.most_common(top)


def contexts(con, term: str, n: int = 2, width: int = 2) -> list[str]:
    """候補の言葉が使われた場面を、前後数行つきで少しだけ取り出す。"""
    ids = [r[0] for r in con.execute(
        "SELECT id FROM messages WHERE text LIKE ? AND role!='system' ORDER BY random() LIMIT ?",
        (f"%{term}%", n))]
    out = []
    for i in ids:
        rows = con.execute(
            "SELECT role,text FROM messages WHERE id BETWEEN ? AND ? AND role!='system' ORDER BY id",
            (i - width, i + width)).fetchall()
        out.append(" / ".join(f"{r['role'][0].upper()}:{r['text'][:40]}" for r in rows))
    return out
