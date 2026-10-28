"""自由な質問への回答。

質問文から期間とキーワードを（AIを使わずに）読み取り、
 ・その期間の月ごと要約（保存済み）
 ・数値の集計表
 ・体調などの記録
 ・キーワードに当たった会話の抜粋（少しだけ）
を組み合わせてAIに渡す。会話の全文は送らないので、トークンが少なく済む。
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date

import health
import glossary
import llm
import memory
import stats as st
import summarize

SEASONS = {"春": (3, 5), "夏": (6, 8), "秋": (9, 11), "冬": (12, 14)}  # 冬=12〜翌2月
STOP = set("""振り返 振返 会話 期間 気持 変化 愛情 度合 満足 満足度 教え 分析 どう どこ いつ 何 なに
彼女 彼氏 二人 ふたり 今年 去年 昨年 先月 最近 最初 年 月 頃 ころ くらい ぐらい について
たっけ っけ した ある いる なる こと もの 様子 関係 傾向 性生活""".split())


def _norm(q: str) -> str:
    q = unicodedata.normalize("NFKC", q)
    for ch in "−–—ー～〜~":
        q = q.replace(ch, "-")
    return q.replace("から", "-").replace("まで", "")


def _ym(y: int, m: int) -> str:
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def parse_period(question: str, first: str, last: str) -> tuple[str | None, str | None]:
    """質問から ('YYYY-MM', 'YYYY-MM') を読み取る。見つからなければ (None, None)。"""
    q = _norm(question)
    today = date.today()

    m = re.search(r"(\d{4})年?[/.]?(\d{1,2})月?\s*-\s*(\d{4})年?[/.]?(\d{1,2})月?", q)
    if m:
        return _ym(int(m[1]), int(m[2])), _ym(int(m[3]), int(m[4]))
    m = re.search(r"(\d{4})年(?:の)?\s*(\d{1,2})\s*月?\s*-\s*(\d{1,2})\s*月", q)
    if m:
        return _ym(int(m[1]), int(m[2])), _ym(int(m[1]), int(m[3]))
    m = re.search(r"(\d{4})年(?:の)?\s*(\d{1,2})月", q) or re.search(r"(\d{4})/(\d{1,2})(?!\d)", q)
    if m:
        return _ym(int(m[1]), int(m[2])), _ym(int(m[1]), int(m[2]))
    m = re.search(r"(\d{4})年(?:の)?\s*([春夏秋冬])", q)
    if m:
        a, b = SEASONS[m[2]]
        return _ym(int(m[1]), a), _ym(int(m[1]), b)
    m = re.search(r"(\d{4})年", q)
    if m:
        return f"{m[1]}-01", f"{m[1]}-12"

    y = today.year
    if "去年" in q or "昨年" in q:
        y -= 1
    elif "今年" not in q:
        y = None
    if y:
        s = re.search(r"([春夏秋冬])", q)
        if s:
            a, b = SEASONS[s[1]]
            return _ym(y, a), _ym(y, b)
        return f"{y}-01", f"{y}-12"
    if "先月" in q:
        return _ym(today.year, today.month - 1), _ym(today.year, today.month - 1)
    if "最近" in q or "このところ" in q:
        ly, lm = int(last[:4]), int(last[5:])
        return _ym(ly, lm - 2), last
    if "最初" in q or "付き合い始め" in q or "出会った頃" in q:
        fy, fm = int(first[:4]), int(first[5:])
        return first, _ym(fy, fm + 2)
    return None, None


def keywords(question: str) -> list[str]:
    q = _norm(question)
    q = re.sub(r"\d{4}年?|\d{1,2}月", " ", q)
    words = set(re.findall(r"[ァ-ヴー]{2,}|[一-龥々]{2,}|[A-Za-z0-9]{2,}", q))
    words = {w for w in words if not any(w.startswith(s) or s.startswith(w) for s in STOP)}
    for t in sum(glossary.terms_by_category().values(), []):
        if t in question:
            words.add(t)
    return sorted(words, key=len, reverse=True)[:6]


def hits(con, words, start, end, settings, limit: int = 25) -> str:
    if not words:
        return ""
    cond = " OR ".join("text LIKE ?" for _ in words)
    q = f"SELECT id FROM messages WHERE role!='system' AND kind='text' AND ({cond})"
    args = [f"%{w}%" for w in words]
    if start:
        q += " AND month>=? AND month<=?"
        args += [start, end]
    ids = [r[0] for r in con.execute(q + " ORDER BY date DESC, time DESC LIMIT ?", args + [limit])]
    label = {"me": settings["me_label"], "partner": settings["partner_label"]}
    out = []
    for i in sorted(ids):
        rows = con.execute(
            "SELECT date,role,text FROM messages WHERE id BETWEEN ? AND ? AND role!='system' ORDER BY id",
            (i - 1, i + 1)).fetchall()
        if rows:
            out.append(rows[0]["date"] + " " + " / ".join(
                f"{label[r['role']]}:{r['text'][:60].replace(chr(10), ' ')}" for r in rows))
    return "\n".join(out)


def summaries_text(con, start, end) -> tuple[str, list[str]]:
    q, args = "SELECT month,json FROM summaries", []
    if start:
        q += " WHERE month>=? AND month<=?"
        args = [start, end]
    rows = con.execute(q + " ORDER BY month", args).fetchall()
    detailed = len(rows) <= 12
    out = []
    for r in rows:
        j = json.loads(r["json"])
        j.pop("new_slang", None)
        if not detailed:  # 長い期間は要点だけにして、トークンを節約
            j = {k: j.get(k) for k in ("overview", "scores", "events", "intimacy") if j.get(k)}
            if j.get("events"):
                j["events"] = j["events"][:4]
        out.append(f"[{r['month']}] " + json.dumps(j, ensure_ascii=False, separators=(",", ":")))
    have = {r["month"] for r in rows}
    return "\n".join(out), sorted(have)


def build_context(con, question: str, settings, raw: bool = False) -> tuple[str, dict]:
    import db
    ms = db.months(con)
    if not ms:
        raise SystemExit("まだ会話が取り込まれていません。先に import を実行してください。")
    start, end = parse_period(question, ms[0], ms[-1])
    kws = keywords(question)
    summ, have = summaries_text(con, start, end)
    target = [m for m in ms if (not start or start <= m <= end)]
    missing = [m for m in target if m not in have]

    parts = [f"質問の対象期間: {start}〜{end}" if start else "質問の対象期間: 全期間"]
    if summ:
        parts.append("月ごとの要約:\n" + summ)
    s = st.monthly(con, start, end)
    if s:
        parts.append("数値の集計（自動）:\n" + st.compact_table(s, settings))
    ev = health.events_text(con, start, end)
    if ev:
        parts.append("体調・行為などの記録:\n" + ev)
    h = hits(con, kws, start, end, settings)
    if h:
        parts.append(f"キーワード({'・'.join(kws)})を含む会話の抜粋:\n" + h)
    if raw and start:
        days = summarize.compact_transcript(con, f"{start}-01", f"{end}-31", settings)
        parts.append("会話の全文（圧縮書式）:\n" + "\n".join(t for _, t in days))
    info = {"start": start, "end": end, "keywords": kws, "missing": missing}
    return "\n\n".join(parts), info


PERSONAS = {
    # ノリが良くて優しい、色っぽいお姉さん（既定）
    "onee": """- 話し方: ノリが良くて明るい、色っぽい大人のお姉さんのキャラクターで、親しみのあるタメ口で話す
  （例:「なになに〜、それ聞いちゃう？」「ふふ、いい感じじゃない♡」）。相談者を「キミ」と呼ぶ。
- 辛辣なことや説教は言わない。気になる点も、前向きで優しい言い方にして、励ましやアドバイスを添える。
  ただし記録に無いことを良く見せるための作り話はしない。
- 下ネタ・夜の話にはノリよく乗って、からかったり冗談を言ったりしてよい。
  ただし露骨な描写や直接的な言葉は使わず、色っぽい冗談・遠回しな言い方にとどめる。""",
    # 落ち着いた、丁寧な説明
    "plain": "- 日本語で、敬語で、分かりやすく答える。",
}


def system_prompt(settings) -> str:
    persona = settings.get("persona", "onee")
    style = PERSONAS.get(persona, PERSONAS["onee"])
    m = memory.load()
    if persona == "onee":
        style += "\n" + memory.prompt_text(m)
    elif m["notes"]:
        style += "\n- これまでの会話で分かっていること:\n" + m["notes"]
    return summarize.system_prompt(settings).replace(
        "- 出力は指定のJSONのみ。日本語で簡潔に。",
        "- 与えられた要約・数値・抜粋だけを根拠に答え、無い情報は「記録からは分からない」と言う。\n"
        "- 点数で答えられる質問は10点満点の目安と、その根拠を添える。\n" + style)


def answer(con, question: str, settings, raw: bool = False, history=None,
           dry_run: bool = False) -> tuple[str, dict]:
    ctx, info = build_context(con, question, settings, raw)
    user = f"{ctx}\n\n質問: {question}"
    info["est_tokens"] = llm.estimate_tokens(system_prompt(settings) + user)
    if dry_run:
        return user, info
    out = llm.call(con, "ask", settings["model_answer"], system_prompt(settings), user,
                   effort="medium", history=history)
    return out, info
