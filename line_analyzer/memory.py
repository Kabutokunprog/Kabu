"""お姉さん（回答役）の記憶とレベル。

・やりとりは秘密フォルダの talk.db に話題（スレッド）ごとに保存し、次回は続きから話せる
・何回か話すたびに「覚えておくことメモ」をAIにまとめ直してもらい、毎回の指示に含める
・話した回数でレベルが上がり、だんだん親しい距離感になる
"""
from __future__ import annotations

import json
from datetime import datetime

import config
import llm

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_log (
    id INTEGER PRIMARY KEY,
    ts TEXT, role TEXT, content TEXT
);
CREATE TABLE IF NOT EXISTS threads (       -- 話題（スレッド）
    id INTEGER PRIMARY KEY,
    title TEXT, created TEXT, updated TEXT
);
"""
TURNS_PER_LEVEL = 10      # 何回質問するとレベルが1つ上がるか
NOTE_EVERY = 6            # 何回質問するごとにメモをまとめ直すか
KEEP_RECENT = 16          # そのまま覚えておく最近の発言数（これより前は「これまでの流れ」に要約）
FLOW_EVERY = 12           # 要約されていない古い発言がこの数を超えたら、流れをまとめ直す
MAX_NOTE_CHARS = 1200

STAGES = [  # (このレベル以上, 距離感)
    (1, "知り合ったばかり。ノリは良いが、まだ少し様子をうかがっている"),
    (3, "打ち解けてきた。冗談やからかいが増え、キミの話し方の癖も分かってきた"),
    (6, "すっかり仲良し。前に聞いた話を自然に持ち出し、遠慮なく甘えたりからかったりする"),
    (10, "何でも話せる特別な相手。キミのことをよく分かっていて、言わなくても察してくれる"),
]


def _path():
    return config.home() / "memory.json"


def load() -> dict:
    p = _path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"notes": "", "turns": 0, "noted_at": 0}


def save(m: dict) -> None:
    p = _path()
    p.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    config.secure(p)


def level(m: dict) -> int:
    return 1 + m["turns"] // TURNS_PER_LEVEL


def stage(m: dict) -> str:
    lv = level(m)
    return [s for need, s in STAGES if lv >= need][-1]


def prompt_text(m: dict) -> str:
    """回答役への指示に足す部分。"""
    lines = [f"- キミとの仲: レベル{level(m)}（{stage(m)}）。この距離感で話す。"]
    if m["notes"]:
        lines.append("- これまでの会話で覚えていること（自然に活かす。メモがあることは言わない）:\n" + m["notes"])
    return "\n".join(lines)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure(con) -> None:
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(chat_log)")}
    tcols = {r[1] for r in con.execute("PRAGMA table_info(threads)")}
    if "flow" not in tcols:  # 長い話題の「これまでの流れ」と、どこまで要約したか
        con.execute("ALTER TABLE threads ADD COLUMN flow TEXT DEFAULT ''")
        con.execute("ALTER TABLE threads ADD COLUMN flow_upto INTEGER DEFAULT 0")
        con.commit()
    if "thread_id" not in cols:
        # スレッド式になる前の履歴は「はじめての会話」にまとめる
        con.execute("ALTER TABLE chat_log ADD COLUMN thread_id INTEGER")
        if con.execute("SELECT COUNT(*) FROM chat_log").fetchone()[0]:
            tid = new_thread(con, "はじめての会話")
            con.execute("UPDATE chat_log SET thread_id=?", (tid,))
        con.commit()


# ---- 話題（スレッド） ----

def new_thread(con, title: str = "新しい話題") -> int:
    now = _now()
    cur = con.execute("INSERT INTO threads(title,created,updated) VALUES(?,?,?)", (title, now, now))
    con.commit()
    return cur.lastrowid


def threads(con) -> list[dict]:
    _ensure(con)
    rows = con.execute(
        "SELECT t.id,t.title,t.updated,(SELECT COUNT(*) FROM chat_log c WHERE c.thread_id=t.id AND c.role='user') n"
        " FROM threads t ORDER BY t.updated DESC").fetchall()
    return [dict(r) for r in rows]


def latest_thread(con) -> int:
    ts = threads(con)
    return ts[0]["id"] if ts else new_thread(con)


def rename_thread(con, tid: int, title: str) -> None:
    con.execute("UPDATE threads SET title=? WHERE id=?", (title.strip()[:60] or "無題", tid))
    con.commit()


def delete_thread(con, tid: int) -> None:
    con.execute("DELETE FROM chat_log WHERE thread_id=?", (tid,))
    con.execute("DELETE FROM threads WHERE id=?", (tid,))
    con.commit()


def messages(con, tid: int) -> list[dict]:
    _ensure(con)
    rows = con.execute("SELECT ts,role,content FROM chat_log WHERE thread_id=? ORDER BY id", (tid,)).fetchall()
    return [dict(r) for r in rows]


def recent(con, tid: int, n: int = KEEP_RECENT) -> list[dict]:
    """その話題の最後のやりとり（続きから話すため）。"""
    _ensure(con)
    rows = con.execute("SELECT role,content FROM chat_log WHERE thread_id=? ORDER BY id DESC LIMIT ?",
                       (tid, n)).fetchall()
    out = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def record(con, question: str, answer: str, tid: int | None = None) -> dict:
    """やりとりを保存し、回数を数える。レベルが上がったら m["level_up"] に新しいレベルを入れる。"""
    _ensure(con)
    tid = tid or latest_thread(con)
    now = _now()
    con.executemany("INSERT INTO chat_log(ts,role,content,thread_id) VALUES(?,?,?,?)",
                    [(now, "user", question, tid), (now, "assistant", answer, tid)])
    # 最初の質問を話題の名前にする
    con.execute("UPDATE threads SET updated=?, title=CASE WHEN title='新しい話題' THEN ? ELSE title END WHERE id=?",
                (now, question.replace("\n", " ")[:24], tid))
    con.commit()
    m = load()
    before = level(m)
    m["turns"] += 1
    save(m)
    if level(m) > before:
        m["level_up"] = level(m)
    return m


def context_text(con, tid: int) -> str:
    """この話題のこれまでの流れと、ほかの話題で最近話したこと（お姉さんを1人の人格にするため）。"""
    _ensure(con)
    out = []
    row = con.execute("SELECT flow FROM threads WHERE id=?", (tid,)).fetchone()
    if row and row["flow"]:
        out.append("この話題のこれまでの流れ（古い部分の要約）:\n" + row["flow"])
    others = []
    for t in con.execute("SELECT id,title,flow,updated FROM threads WHERE id!=? ORDER BY updated DESC LIMIT 3",
                         (tid,)).fetchall():
        last = con.execute("SELECT content FROM chat_log WHERE thread_id=? AND role='user' ORDER BY id DESC LIMIT 2",
                           (t["id"],)).fetchall()
        gist = t["flow"][:200] if t["flow"] else " / ".join(r["content"][:60].replace("\n", " ") for r in last)
        if gist:
            others.append(f"- {t['updated'][:10]}「{t['title']}」: {gist}")
    if others:
        out.append("ほかの話題で最近キミと話したこと（同じ相手との会話。必要なら自然に触れてよい）:\n" + "\n".join(others))
    return "\n\n".join(out)


def update_flow(con, tid: int, settings, system: str) -> None:
    """長くなった話題の古い部分を「これまでの流れ」にまとめ直す。"""
    _ensure(con)
    th = con.execute("SELECT flow,flow_upto FROM threads WHERE id=?", (tid,)).fetchone()
    if not th:
        return
    ids = [r["id"] for r in con.execute("SELECT id FROM chat_log WHERE thread_id=? ORDER BY id", (tid,))]
    old = [i for i in ids[:-KEEP_RECENT] if i > (th["flow_upto"] or 0)] if len(ids) > KEEP_RECENT else []
    if len(old) < FLOW_EVERY:
        return
    rows = con.execute(f"SELECT role,content FROM chat_log WHERE id IN ({','.join('?' * len(old))}) ORDER BY id",
                       old).fetchall()
    talk = "\n".join(f"{'キミ' if r['role'] == 'user' else 'わたし'}: {r['content'][:600]}" for r in rows)
    req = (f"相談者「キミ」と、あなた（お姉さん）との会話の流れの要約を更新します。\n"
           f"今までの要約:\n{th['flow'] or '（なし）'}\n\n続きの会話:\n{talk}\n\n"
           "話題の流れ・キミの悩みや気持ち・あなたが言ったアドバイスや約束を、時間順に800文字以内でまとめてください。"
           "露骨な表現は使わないこと。要約の本文だけを出力。")
    out = llm.call(con, "flow", settings["model_answer"], system, req, effort="low", max_tokens=2000)
    con.execute("UPDATE threads SET flow=?, flow_upto=? WHERE id=?", (out.strip()[:1500], old[-1], tid))
    con.commit()


def after_reply(con, tid: int, m: dict, settings, system: str) -> None:
    """返事のあとの片付け（長い話題の要約・メモの更新）。"""
    update_flow(con, tid, settings, system)
    if needs_notes(m):
        update_notes(con, settings, system)


def needs_notes(m: dict) -> bool:
    return m["turns"] - m.get("noted_at", 0) >= NOTE_EVERY


def update_notes(con, settings, system: str) -> None:
    """最近のやりとりから「覚えておくことメモ」をまとめ直す。"""
    _ensure(con)
    m = load()
    n = (m["turns"] - m.get("noted_at", 0)) * 2
    if n <= 0:
        return
    rows = con.execute("SELECT role,content FROM chat_log ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    talk = "\n".join(f"{'キミ' if r['role'] == 'user' else 'わたし'}: {r['content'][:400]}"
                     for r in reversed(rows))
    req = (f"あなた（回答役のお姉さん）が、相談者「キミ」について覚えておくメモを更新します。\n"
           f"今までのメモ:\n{m['notes'] or '（なし）'}\n\n最近のやりとり:\n{talk}\n\n"
           f"キミの好み・気にしていること・よく聞く話題・喜んだ反応・話し方の癖・二人（キミと彼女）について新しく分かったことを、"
           f"今までのメモと統合して、箇条書き（「- 」で始まる行）で{MAX_NOTE_CHARS}文字以内にまとめてください。"
           f"古くなった内容は消し、露骨な表現は使わないこと。メモの本文だけを出力。")
    out = llm.call(con, "memory", settings["model_answer"], system, req, effort="low", max_tokens=2000)
    m["notes"] = out.strip()[:MAX_NOTE_CHARS]
    m["noted_at"] = m["turns"]
    save(m)


def reset(con) -> None:
    _ensure(con)
    con.execute("DELETE FROM chat_log")
    con.execute("DELETE FROM threads")
    con.commit()
    save({"notes": "", "turns": 0, "noted_at": 0})
