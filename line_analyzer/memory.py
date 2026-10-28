"""お姉さん（回答役）の記憶とレベル。

・やりとりは秘密フォルダの talk.db（chat_log テーブル）に保存し、次回は続きから話せる
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
"""
TURNS_PER_LEVEL = 10      # 何回質問するとレベルが1つ上がるか
NOTE_EVERY = 6            # 何回質問するごとにメモをまとめ直すか
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


def _ensure(con) -> None:
    con.executescript(SCHEMA)


def recent(con, n: int = 6) -> list[dict]:
    """前回までの最後のやりとり（続きから話すため）。"""
    _ensure(con)
    rows = con.execute("SELECT role,content FROM chat_log ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    out = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def record(con, question: str, answer: str) -> dict:
    """やりとりを保存し、回数を数える。レベルが上がったら m["level_up"] に新しいレベルを入れる。"""
    _ensure(con)
    now = datetime.now().isoformat(timespec="seconds")
    con.executemany("INSERT INTO chat_log(ts,role,content) VALUES(?,?,?)",
                    [(now, "user", question), (now, "assistant", answer)])
    con.commit()
    m = load()
    before = level(m)
    m["turns"] += 1
    save(m)
    if level(m) > before:
        m["level_up"] = level(m)
    return m


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
    con.commit()
    save({"notes": "", "turns": 0, "noted_at": 0})
