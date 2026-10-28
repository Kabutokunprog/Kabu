#!/usr/bin/env python3
"""LINEトーク分析アプリ（ふたりの記録帳）の操作コマンド。

使い方の例:
  python3 la.py import ~/Downloads/トーク履歴.txt     会話を取り込む（2回目以降は差分だけ）
  python3 la.py summarize                             新しい月・変わった月だけAI要約
  python3 la.py ask "2026年4-6月を振り返って"          質問する
  python3 la.py chat                                  続けて何度も質問する
詳しくは README.md を参照。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ask  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import glossary  # noqa: E402
import health  # noqa: E402
import line_parser  # noqa: E402
import llm  # noqa: E402
import memory  # noqa: E402
import search  # noqa: E402
import stats as st  # noqa: E402
import summarize  # noqa: E402

# 1Mトークンあたりの料金（ドル） 入力, 出力
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0),
          "claude-haiku-5-5": (0.10, 0.50)}
EST_OUTPUT_PER_CALL = 2500  # 要約1回あたりの出力トークンの目安（考える分も含む）
# Mac内のAI（M1 Pro・メモリ16GB・9B前後のモデル）の速さの目安（トークン/秒）
LOCAL_READ_SPEED, LOCAL_WRITE_SPEED, LOCAL_OUTPUT_PER_CALL = 250, 20, 1500


def _cost(model, tin, tout) -> float:
    if not model.startswith("claude"):
        return 0.0  # Mac内のAIは無料（Geminiは料金表が別なので計算しない）
    pi, po = PRICES.get(model, (4.0, 20.0))
    return tin / 1e6 * pi + tout / 1e6 * po


def _confirm(msg: str, yes: bool) -> bool:
    if yes:
        return True
    return input(f"{msg} [y/N]: ").strip().lower() in ("y", "yes", "はい")


# ---------------- 各コマンド ----------------

def cmd_import(a):
    s = config.load_settings()
    msgs = line_parser.parse_file(a.file)
    if not msgs:
        raise SystemExit("メッセージを読み取れませんでした。LINEの「トーク履歴を送信」で出したテキストか確認してください。")
    senders = Counter(m.sender for m in msgs if m.sender)
    if a.me:
        s["me_name"] = a.me
    if a.partner:
        s["partner_name"] = a.partner
    if not s["me_name"] or not s["partner_name"]:
        top = [n for n, _ in senders.most_common(5)]
        print("見つかった発言者:", "、".join(f"{i + 1}) {n}" for i, n in enumerate(top)))
        if not s["me_name"]:
            s["me_name"] = top[int(input("あなた（彼）の番号: ")) - 1]
        if not s["partner_name"]:
            s["partner_name"] = top[int(input("お相手（彼女）の番号: ")) - 1]
    config.save_settings(s)
    con = db.connect()
    db.refresh_roles(con, s)
    added, months = db.import_messages(con, msgs, s)
    total = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    print(f"読み込み {len(msgs)}件 → 新しく追加 {added}件（保存済み合計 {total}件）")
    if months:
        print("追加があった月:", ", ".join(sorted(months)))
        print("→ 次に `python3 la.py summarize` で、この月の要約を作れます。")
    print("保存場所:", config.home())


def _plan(con, s, months):
    model = llm.model_name(s, s["model_summary"])
    tin = tout = calls = 0
    sys_tok = llm.estimate_tokens(summarize.system_prompt(s))
    for m in months:
        for req in summarize.build_month_requests(con, m, s):
            tin += sys_tok + llm.estimate_tokens(req)
            tout += EST_OUTPUT_PER_CALL
            calls += 1
    return model, tin, tout, calls


def _print_plan(con, s, months):
    model, tin, tout, calls = _plan(con, s, months)
    print(f"対象 {len(months)}か月（{months[0]}〜{months[-1]}） / AI呼び出し約{calls}回")
    if llm.is_local(s):
        sec = tin / LOCAL_READ_SPEED + calls * LOCAL_OUTPUT_PER_CALL / LOCAL_WRITE_SPEED
        print(f"Mac内のAI（{model}）で処理します。料金0円・会話は外に出ません。")
        print(f"処理時間の目安: 約{_duration(sec)}（Macの状態で前後します。途中で止めても、終わった月は保存されます）")
    elif llm.backend(s) == "gemini":
        print(f"Gemini（{model}）で処理します。圧縮した会話がGoogle社に送られます。")
        print(f"送る量: 入力 約{tin:,}トークン + 出力 約{tout:,}トークン（料金はGoogleの料金表によります）")
    else:
        print(f"Claude（{model}）で処理します。圧縮した会話がAnthropic社に送られます。")
        print(f"見積もり: 入力 約{tin:,}トークン + 出力 約{tout:,}トークン ≒ ${_cost(model, tin, tout):.2f}")


def _duration(sec: float) -> str:
    if sec < 60:
        return "1分以内"
    if sec < 3600:
        return f"{round(sec / 60)}分"
    return f"{sec / 3600:.1f}時間"


def cmd_summarize(a):
    s = config.load_settings()
    con = db.connect()
    if a.month:
        months = a.month
    elif a.force:
        months = db.months(con)
    else:
        months = summarize.stale_months(con)
    if not months:
        print("要約が必要な月はありません（すべて最新です）。")
        return
    _print_plan(con, s, months)
    if a.dry_run or not _confirm("実行しますか？", a.yes):
        return
    for i, m in enumerate(months, 1):
        print(f"[{i}/{len(months)}] {m} を要約中…", flush=True)
        r = summarize.summarize_month(con, m, s)
        print("   ", (r.get("overview") or "")[:80])
    print("完了しました。`python3 la.py report` で一覧を作れます。")


def cmd_stats(a):
    s = config.load_settings()
    con = db.connect()
    st.print_table(st.monthly(con, a.start, a.end), s)


def _print_answer(out, info):
    if info.get("missing"):
        print(f"※ 要約がまだ無い月があります（{len(info['missing'])}か月）。"
              "`python3 la.py summarize` を実行すると回答の精度が上がります。\n")
    print(out)


def cmd_ask(a):
    s = config.load_settings()
    print(f"（使うAI: {_ai_label(s)}）\n", file=sys.stderr)
    con = db.connect()
    out, info = ask.answer(con, a.question, s, raw=a.raw, dry_run=a.dry_run)
    if a.dry_run:
        print(out)
        print(f"\n--- 送信予定 約{info['est_tokens']:,}トークン / 期間 {info['start']}〜{info['end']} / キーワード {info['keywords']}")
        return
    _print_answer(out, info)
    _remember(con, s, a.question, out)


def _remember(con, s, question, out):
    """やりとりを記憶し、レベルアップを知らせ、ときどきメモをまとめ直す。"""
    m = memory.record(con, question, out)
    if m.get("level_up"):
        print(f"\n♡ 仲良しレベルが {m['level_up']} に上がりました（{memory.stage(m)}）")
    if memory.needs_notes(m):
        memory.update_notes(con, s, ask.system_prompt(s))


def _ai_label(s) -> str:
    b = llm.backend(s)
    if b == "ollama":
        return f"Mac内のAI {s['ollama_model']}"
    if b == "gemini":
        return f"Gemini {s['gemini_model']}"
    return f"Claude {s['model_answer']}"


def cmd_chat(a):
    s = config.load_settings()
    print(f"（使うAI: {_ai_label(s)}）")
    con = db.connect()
    history = memory.recent(con)
    m = memory.load()
    if m["turns"]:
        print(f"仲良しレベル {memory.level(m)}（これまで{m['turns']}回お話ししました）。前回の続きからどうぞ。")
    print("質問をどうぞ（終わるときは「終了」または Ctrl+D）")
    while True:
        try:
            q = input("\n> ").strip()
        except EOFError:
            break
        if q in ("終了", "exit", "quit", "q"):
            break
        if not q:
            continue
        out, info = ask.answer(con, q, s, history=history[-6:])
        print()
        _print_answer(out, info)
        # 次の質問のために、質問と答えだけ（根拠データは除く）を覚えておく
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": out}]
        _remember(con, s, q, out)
    # 終わるときに、まだメモに入れていない話を覚えておく
    m = memory.load()
    if m["turns"] - m.get("noted_at", 0) >= 2:
        print("（今日の話を覚えています…）")
        memory.update_notes(con, s, ask.system_prompt(s))


def cmd_health_import(a):
    con = db.connect()
    recs = health.load_records(a.file)
    events, cols = health.to_events(recs, a.source)
    print("列の対応:", {k: v for k, v in cols.items() if v})
    added = db.import_events(con, events)
    cats = Counter(e["category"] for e in events)
    print(f"読み込み {len(events)}件 → 新しく追加 {added}件  内訳: {dict(cats)}")
    if added:
        print("→ 記録が増えた月は、次の summarize で要約が作り直されます。")


def cmd_correlate(a):
    con = db.connect()
    print(health.correlate(con, a.window))


def cmd_glossary(a):
    if a.action == "list":
        items = glossary.load()
        if not items:
            print("辞書は空です。`glossary add 言葉 意味 カテゴリ` か `glossary suggest` で追加できます。")
        for i in items:
            mark = "  " if i.get("confirmed") else "？"
            own = f"  （本当の意味: {i['private']}）" if i.get("private") else ""
            print(f"{mark} [{i.get('category', 'other'):<9}] {i['term']} = {i['meaning']}{own}")
        print(f"\n辞書ファイル: {config.glossary_path()}（テキストエディタで直接直せます）")
    elif a.action == "add":
        if len(a.args) < 2:
            raise SystemExit('例: python3 la.py glossary add "言葉" "意味" intimacy')
        cat = a.args[2] if len(a.args) > 2 else "other"
        glossary.add(a.args[0], a.args[1], cat)
        print("追加しました。過去の要約に反映するには `summarize --force` を実行してください。")
    elif a.action == "confirm":
        items = glossary.load()
        for i in items:
            if not a.args or i["term"] in a.args:
                i["confirmed"] = True
        glossary.save(items)
        print("確認済みにしました。")
    elif a.action == "edit":
        import glossary_web
        glossary_web.run(db.connect())
    elif a.action == "review":
        items = glossary.load()
        todo = [i for i in items if not i.get("confirmed")]
        if not todo:
            print("確認待ちの言葉はありません。")
            return
        print(f"確認待ちの言葉が{len(todo)}個あります。1つずつ答えてください。")
        print("  Enter = 正しい / 正しい意味を入力 = 意味を直す / d = 消す / s = あとで / q = やめる\n")
        drop = set()
        for n, i in enumerate(todo, 1):
            print(f"[{n}/{len(todo)}] 「{i['term']}」 = {i['meaning']}  （{i.get('category', 'other')}）")
            ans = input("  → ").strip()
            if ans.lower() == "q":
                break
            if ans.lower() == "s":
                continue
            if ans.lower() == "d":
                drop.add(i["term"])
                continue
            if ans:
                i["meaning"] = ans
            i["confirmed"] = True
        glossary.save([i for i in items if i["term"] not in drop])
        print("\n保存しました。過去の要約にも反映したいときは `summarize --force` を実行してください。")
    elif a.action == "suggest":
        s = config.load_settings()
        con = db.connect()
        cands = glossary.local_candidates(con)
        if not cands:
            print("候補が見つかりませんでした。")
            return
        lines = []
        for term, n in cands:
            ctx = " ｜ ".join(glossary.contexts(con, term))
            lines.append(f"- {term}（{n}回） 例: {ctx}")
        req = (f"次はカップルのLINEで頻出する言葉と使用例です（M={s['me_label']}, P={s['partner_label']}）。"
               "一般的な言葉は除き、二人特有の隠語・あだ名・合言葉と思われるものだけを選び、"
               "意味を推測してください。性的な隠語は婉曲な説明にしてください。\n"
               + "\n".join(lines)
               + '\n\nJSONのみ: {"items": [{"term": "", "meaning": "", "category": "intimacy/affection/nickname/place/health/other"}]}')
        print(f"候補{len(cands)}語をAIに判定してもらいます（約{llm.estimate_tokens(req):,}トークン）。")
        if not _confirm("実行しますか？", a.yes):
            return
        out = llm.call(con, "glossary", s["model_summary"], summarize.system_prompt(s), req, effort="low",
                       json_mode=True)
        found = llm.parse_json(out) or []
        if isinstance(found, dict):
            found = found.get("items") or next((v for v in found.values() if isinstance(v, list)), [])
        items = glossary.load()
        known = {i["term"] for i in items}
        for f in found:
            if isinstance(f, dict) and f.get("term") and f["term"] not in known:
                items.append({**f, "confirmed": False})
                print(f"？ [{f.get('category')}] {f['term']} = {f.get('meaning')}")
        glossary.save(items)
        print("推測として追加しました。正しいものは `glossary confirm 言葉`、違うものは辞書ファイルから削除してください。")


def cmd_report(a):
    s = config.load_settings()
    con = db.connect()
    me, pa = s["me_label"], s["partner_label"]
    stats = st.monthly(con)
    lines = ["# ふたりの記録帳", ""]
    for r in con.execute("SELECT month,json FROM summaries ORDER BY month"):
        j = json.loads(r["json"])
        sc = {k: ("-" if v is None else v) for k, v in (j.get("scores") or {}).items()}
        x = stats.get(r["month"], {})
        lines += [f"## {r['month']}", "",
                  j.get("overview", ""), "",
                  f"- 点数: {pa}→{me}の愛情 {sc.get('partner_affection', '-')} / {me}→{pa}の愛情 {sc.get('me_affection', '-')}"
                  f" / {pa}の満足 {sc.get('partner_satisfaction', '-')} / 親密さ {sc.get('closeness', '-')}"
                  f" / 衝突 {sc.get('conflict', '-')} / 夜の満足 {sc.get('intimacy_satisfaction', '-')}",
                  f"- 件数: {me} {int(x.get('msgs_me', 0))} / {pa} {int(x.get('msgs_partner', 0))}"
                  f"、通話 {x.get('call_min', 0)}分"]
        for key, title in (("events", "出来事"), ("conflicts", "すれ違い")):
            if j.get(key):
                lines.append(f"- {title}: " + "、".join(j[key]))
        for key, title in (("partner_feelings", f"{pa}の気持ち"), ("me_feelings", f"{me}の気持ち"),
                           ("intimacy", "夜のこと"), ("health", "体調"), ("changes", "変化")):
            if j.get(key):
                lines.append(f"- {title}: {j[key]}")
        lines.append("")
    path = config.reports_dir() / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    config.secure(path)
    print("作成しました:", path)


def cmd_cost(a):
    con = db.connect()
    rows = con.execute(
        "SELECT model, COUNT(*) n, SUM(input_tokens) i, SUM(output_tokens) o,"
        " SUM(cache_read) cr, SUM(cache_write) cw FROM usage GROUP BY model").fetchall()
    if not rows:
        print("まだAIは使われていません。")
    total = 0.0
    for r in rows:
        c = _cost(r["model"], (r["i"] or 0) + (r["cw"] or 0) * 1.25 + (r["cr"] or 0) * 0.1, r["o"] or 0)
        total += c
        free = "" if r["model"].startswith("claude") else (
            "（Gemini・料金はGoogleで確認）" if r["model"].startswith("gemini") else "（Mac内のAI・無料）")
        print(f"{r['model']}{free}: {r['n']}回 入力{(r['i'] or 0) + (r['cr'] or 0) + (r['cw'] or 0):,} 出力{r['o'] or 0:,}トークン ≒ ${c:.2f}")
    print(f"合計 ≒ ${total:.2f}")


def cmd_search(a):
    s = config.load_settings()
    con = db.connect()
    print(search.render(con, a.words, s, a.start, a.end, a.context, a.limit))


def cmd_trial(a):
    """1か月分を Mac内のAI と Claude の両方で要約し、読み比べ用のファイルを作る（要約の保存はしない）。"""
    s = config.load_settings()
    con = db.connect()
    if a.month not in db.months(con):
        raise SystemExit(f"{a.month} の会話がありません。取り込み済みの月: {', '.join(db.months(con)[-6:])} など")
    for name in a.ai:
        llm.set_backend(name)
        title = _ai_label(s)
        print(f"\n■ {title}")
        _print_plan(con, s, [a.month])
        if name != "ollama" and not _confirm(f"この1か月分の圧縮した会話を{title}に送ります。よろしいですか？", a.yes):
            continue
        print("要約中…", flush=True)
        j = summarize.make_summary(con, a.month, s)
        lines = [f"# 読み比べ {a.month}（{title}）", ""]
        for k, v in j.items():
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            lines.append(f"- **{k}**: {v}")
        path = config.reports_dir() / f"trial_{a.month}_{name}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        config.secure(path)
        print("作成しました:", path)
        print(f"開くには: open {path}")
    llm.set_backend(None)


def cmd_memory(a):
    con = db.connect()
    m = memory.load()
    if a.action == "reset":
        if _confirm("お姉さんの記憶（やりとりの履歴・メモ・レベル）をすべて消します。よろしいですか？", a.yes):
            memory.reset(con)
            print("記憶を消しました。次は初対面からです。")
        return
    print(f"仲良しレベル {memory.level(m)}（{memory.stage(m)}） / これまで{m['turns']}回")
    print("覚えていること:\n" + (m["notes"] or "（まだありません）"))


def cmd_settings(a):
    s = config.load_settings()
    for kv in a.set or []:
        k, v = kv.split("=", 1)
        if k not in config.DEFAULT_SETTINGS:
            raise SystemExit(f"不明な項目です: {k}")
        if k == "backend" and v not in ("ollama", "claude", "gemini"):
            raise SystemExit("backend は ollama（Mac内のAI）・claude・gemini のどれかです。")
        s[k] = int(v) if isinstance(config.DEFAULT_SETTINGS[k], int) else v
    if a.set:
        config.save_settings(s)
        db.refresh_roles(db.connect(), s)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    print("保存場所:", config.home())


def main(argv=None):
    p = argparse.ArgumentParser(prog="la.py", description="LINEトーク分析（ふたりの記録帳）")
    sub = p.add_subparsers(dest="cmd", required=True)

    x = sub.add_parser("import", help="LINEのトーク履歴を取り込む（差分のみ追加）")
    x.add_argument("file")
    x.add_argument("--me", help="あなたのLINE表示名")
    x.add_argument("--partner", help="お相手のLINE表示名")
    x.set_defaults(func=cmd_import)

    x = sub.add_parser("summarize", help="月ごとのAI要約を作る（新しい・変わった月だけ）")
    x.add_argument("--month", nargs="+", help="特定の月だけ（例: 2026-04 2026-05）")
    x.add_argument("--force", action="store_true", help="全部の月を作り直す")
    x.add_argument("--dry-run", action="store_true", help="見積もりだけ表示")
    x.add_argument("--ai", choices=["ollama", "claude", "gemini"], help="今回だけ使うAIを指定")
    x.add_argument("-y", "--yes", action="store_true", help="確認なしで実行")
    x.set_defaults(func=cmd_summarize)

    x = sub.add_parser("stats", help="数値の集計を表示（AI不使用）")
    x.add_argument("--from", dest="start")
    x.add_argument("--to", dest="end")
    x.set_defaults(func=cmd_stats)

    x = sub.add_parser("ask", help="質問する")
    x.add_argument("question")
    x.add_argument("--raw", action="store_true", help="その期間の会話全文も渡す（トークン多め）")
    x.add_argument("--dry-run", action="store_true", help="AIに送る内容と量だけ表示")
    x.add_argument("--ai", choices=["ollama", "claude", "gemini"], help="今回だけ使うAIを指定")
    x.set_defaults(func=cmd_ask)

    x = sub.add_parser("search", help="キーワードを含む会話を一覧表示（AI不使用・無料）")
    x.add_argument("words", nargs="+", help="探す言葉（複数なら、すべてを含む発言）")
    x.add_argument("--from", dest="start", help="この月から（例: 2026-04）")
    x.add_argument("--to", dest="end", help="この月まで（例: 2026-06）")
    x.add_argument("-C", "--context", type=int, default=1, help="前後に何通ずつ表示するか（既定1）")
    x.add_argument("--limit", type=int, default=200, help="表示する最大件数")
    x.set_defaults(func=cmd_search)

    x = sub.add_parser("trial", help="1か月分をMac内のAIとClaudeの両方で要約して読み比べる")
    x.add_argument("month", help="例: 2026-04")
    x.add_argument("--ai", nargs="+", choices=["ollama", "claude", "gemini"], default=["ollama", "claude"],
                   help="使うAI（既定は両方）")
    x.add_argument("-y", "--yes", action="store_true")
    x.set_defaults(func=cmd_trial)

    x = sub.add_parser("chat", help="続けて質問する")
    x.set_defaults(func=cmd_chat)

    x = sub.add_parser("health-import", help="MedicationReminder等の記録(CSV/JSON)を取り込む")
    x.add_argument("file")
    x.add_argument("--source", default="MedicationReminder")
    x.set_defaults(func=cmd_health_import)

    x = sub.add_parser("correlate", help="記録と会話の関係を数値で比べる（AI不使用）")
    x.add_argument("--window", type=int, default=2, help="前後何日を見るか")
    x.set_defaults(func=cmd_correlate)

    x = sub.add_parser("glossary", help="二人の言葉（隠語）辞書")
    x.add_argument("action", choices=["list", "edit", "add", "confirm", "review", "suggest"])
    x.add_argument("args", nargs="*")
    x.add_argument("-y", "--yes", action="store_true")
    x.set_defaults(func=cmd_glossary)

    x = sub.add_parser("report", help="月ごとの要約を1つの読み物(report.md)にまとめる")
    x.set_defaults(func=cmd_report)

    x = sub.add_parser("cost", help="これまでのAI使用量と料金の目安")
    x.set_defaults(func=cmd_cost)

    x = sub.add_parser("memory", help="お姉さんの記憶とレベルを見る・消す")
    x.add_argument("action", nargs="?", choices=["show", "reset"], default="show")
    x.add_argument("-y", "--yes", action="store_true")
    x.set_defaults(func=cmd_memory)

    x = sub.add_parser("settings", help="設定の表示・変更（例: --set model_summary=claude-haiku-5-5）")
    x.add_argument("--set", nargs="+")
    x.set_defaults(func=cmd_settings)

    a = p.parse_args(argv)
    if getattr(a, "ai", None) and a.cmd != "trial":
        llm.set_backend(a.ai)
    a.func(a)


if __name__ == "__main__":
    main()
