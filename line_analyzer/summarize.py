"""月ごとのAI要約。

・会話は「圧縮した書式」にしてから送る（日付は日ごとに1回、時刻は1時間ごと、
  スタンプ等は記号に置き換え）→ 送るトークンを減らす
・要約済みの月は保存しておき、内容が変わった月（差分が入った月）だけ作り直す
"""
from __future__ import annotations

import json
from datetime import datetime

import db
import glossary
import health
import llm
import stats as st

SHORT_KIND = {"sticker": "[ス]", "photo": "[写]", "video": "[動]", "voice": "[声]",
              "file": "[ファ]", "location": "[位置]", "unsent": "[取消]"}


def compact_transcript(con, start_date: str, end_date: str, settings) -> list[tuple[str, str]]:
    """[(日付, その日の圧縮テキスト)] を返す。"""
    rows = con.execute(
        "SELECT date,time,role,kind,text,call_sec FROM messages"
        " WHERE date>=? AND date<=? AND role!='system' ORDER BY date,time,id",
        (start_date, end_date)).fetchall()
    label = {"me": settings["me_label"], "partner": settings["partner_label"]}
    days: list[tuple[str, list[str]]] = []
    last_hour = None
    for r in rows:
        if not days or days[-1][0] != r["date"]:
            days.append((r["date"], [f"■{int(r['date'][5:7])}/{int(r['date'][8:])}"]))
            last_hour = None
        if r["kind"] == "call":
            body = f"[通話{r['call_sec'] // 60}分]" if r["call_sec"] else "[通話/不在]"
        else:
            body = SHORT_KIND.get(r["kind"], r["text"].replace("\n", " "))
            if r["kind"] == "text" and ("http://" in body or "https://" in body):
                body = "[URL]"
        hour = r["time"][:2]
        prefix = f"{hour}時 " if hour != last_hour else ""
        last_hour = hour
        lines = days[-1][1]
        # 同じ人のスタンプ連打などはまとめる
        if lines and lines[-1].endswith(body) and body.startswith("[") and not prefix:
            continue
        lines.append(f"{prefix}{label[r['role']]}:{body}")
    return [(d, "\n".join(ls)) for d, ls in days]


INTIMACY_RULE = """- 性生活に関する内容は、露骨な描写をせず、穏やかで臨床的な言い方で記述する
  （例:「深いつながりを好む傾向」「満足している様子」「頻度が減っている」）。"""


def system_prompt(settings) -> str:
    me, pa = settings["me_label"], settings["partner_label"]
    return f"""あなたは恋愛関係のカウンセラー兼データアナリストです。
カップルのLINEのやりとり（本人＝「{me}」の依頼による、本人の会話の分析）を読み、
二人の関係と気持ちの変化を客観的にまとめます。

会話の書式: 「■月/日」が日付、「HH時」は時刻、「{me}:」「{pa}:」が発言者。
[ス]=スタンプ [写]=写真 [動]=動画 [声]=ボイス [通話N分]=通話。

二人だけの言葉（隠語）の辞書:
{glossary.as_prompt_text()}

ルール:
- 推測は根拠（言動）に基づき、断定しすぎない。
{INTIMACY_RULE}
- 体調・痛み・生理などの記録が与えられたら、会話との関係（気遣い、気分の変化等）も見る。
- 出力は指定のJSONのみ。日本語で簡潔に。"""


JSON_SPEC = """次の形のJSONだけを出力:
{
 "overview": "この期間の二人の様子（3〜5文）",
 "events": ["日付 出来事（デート・旅行・行った場所・記念日・喧嘩など）"],
 "places": ["行った/行く予定の場所"],
 "me_feelings": "彼の気持ち・態度の傾向",
 "partner_feelings": "彼女の気持ち・態度の傾向",
 "scores": {"partner_affection": 0-10, "me_affection": 0-10,
            "partner_satisfaction": 0-10, "me_satisfaction": 0-10,
            "closeness": 0-10, "conflict": 0-10,
            "intimacy_satisfaction": 0-10 または null（手がかりが無ければnull）},
 "intimacy": "性生活についての婉曲な所見（好み・頻度・満足度の傾向）。手がかり無しならnull",
 "health": "体調・痛み等の所見。無ければnull",
 "conflicts": ["すれ違い・喧嘩とその原因"],
 "changes": "前の期間からの変化",
 "keywords": ["この期間を象徴する話題"],
 "new_slang": [{"term": "辞書に無い二人特有の言葉", "guess": "推測される意味", "category": "intimacy/affection/nickname/place/health/other"}]
}"""


def _split(days: list[tuple[str, str]], max_chars: int) -> list[list[tuple[str, str]]]:
    parts, cur, n = [], [], 0
    for d, txt in days:
        if cur and n + len(txt) > max_chars:
            parts.append(cur)
            cur, n = [], 0
        cur.append((d, txt))
        n += len(txt)
    if cur:
        parts.append(cur)
    return parts


def build_month_requests(con, month: str, settings) -> list[str]:
    """その月の要約に必要な依頼文（分割された場合は複数）を作る。"""
    days = compact_transcript(con, f"{month}-01", f"{month}-31", settings)
    s = st.monthly(con, month, month)
    stat_txt = st.compact_table(s, settings) if s else ""
    ev = health.events_text(con, month, month)
    prev = con.execute("SELECT json FROM summaries WHERE month<? ORDER BY month DESC LIMIT 1",
                       (month,)).fetchone()
    prev_txt = ""
    if prev:
        pj = json.loads(prev["json"])
        prev_txt = f"前の期間の様子（参考）: {pj.get('overview', '')}\n"
    parts = _split(days, llm.chunk_chars(settings))
    reqs = []
    for i, part in enumerate(parts, 1):
        head = f"対象期間: {month}" + (f"（{len(parts)}分割の{i}番目）" if len(parts) > 1 else "")
        body = "\n".join(t for _, t in part)
        reqs.append(f"{head}\n{prev_txt}\n数値（自動集計）:\n{stat_txt}\n\n"
                    + (f"体調・行為などの記録:\n{ev}\n\n" if ev else "")
                    + f"会話:\n{body}\n\n{JSON_SPEC}")
    return reqs


def stale_months(con) -> list[str]:
    done = {r["month"]: r["sig"] for r in con.execute("SELECT month,sig FROM summaries")}
    return [m for m in db.months(con) if done.get(m) != db.month_signature(con, m)]


def make_summary(con, month: str, settings) -> dict:
    """その月の要約を作って返す（保存はしない）。"""
    model = settings["model_summary"]
    system = system_prompt(settings)
    reqs = build_month_requests(con, month, settings)
    results = []
    for req in reqs:
        out = llm.call(con, f"summary {month}", model, system, req, effort="low", max_tokens=8000,
                       json_mode=True)
        results.append(llm.parse_json(out) or {"overview": out})
    # 分割した結果を統合する。一度に読める量を超えないよう、少しずつ段階的にまとめる
    limit = llm.chunk_chars(settings)
    while len(results) > 1:
        groups, cur = [], []
        for r in results:
            if len(cur) >= 2 and len(json.dumps(cur + [r], ensure_ascii=False)) > limit:
                groups.append(cur)
                cur = []
            cur.append(r)
        groups.append(cur)
        merged = []
        for g in groups:
            if len(g) == 1:
                merged.append(g[0])
                continue
            merge_req = (f"対象期間: {month}。以下は同じ月を分割して要約した結果です（時間順）。"
                         f"1つに統合してください。\n{json.dumps(g, ensure_ascii=False)}\n\n{JSON_SPEC}")
            out = llm.call(con, f"merge {month}", model, system, merge_req, effort="low", max_tokens=8000,
                           json_mode=True)
            merged.append(llm.parse_json(out) or g[-1])
        results = merged
    return results[0]


def summarize_month(con, month: str, settings) -> dict:
    result = make_summary(con, month, settings)
    model = llm.model_name(settings, settings["model_summary"])
    con.execute(
        "INSERT OR REPLACE INTO summaries(month,sig,json,model,created) VALUES(?,?,?,?,?)",
        (month, db.month_signature(con, month), json.dumps(result, ensure_ascii=False), model,
         datetime.now().isoformat(timespec="seconds")))
    con.commit()
    _collect_slang(result)
    return result


def _collect_slang(result: dict) -> None:
    """AIが見つけた新しい隠語の候補を、未確認として辞書に追加する。"""
    new = result.get("new_slang") or []
    if not new:
        return
    items = glossary.load()
    known = {i["term"] for i in items}
    changed = False
    for s in new:
        if isinstance(s, dict) and s.get("term") and s["term"] not in known:
            items.append({"term": s["term"], "meaning": s.get("guess", ""),
                          "category": s.get("category", "other"), "confirmed": False})
            known.add(s["term"])
            changed = True
    if changed:
        glossary.save(items)
