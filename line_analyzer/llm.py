"""Claude API の呼び出し（トークン使用量の記録つき）。"""
from __future__ import annotations

import json
import re

import db

FALLBACK_MODELS = ("claude-opus", "claude-sonnet", "claude-fable")


def estimate_tokens(text: str) -> int:
    """日本語はおおよそ1文字≒1トークン、英数字は4文字≒1トークンとして概算。"""
    ascii_n = sum(1 for c in text if ord(c) < 128)
    return int((len(text) - ascii_n) * 1.0 + ascii_n / 4)


def call(con, purpose: str, model: str, system: str, user: str,
         effort: str = "medium", max_tokens: int = 16000, history=None) -> str:
    try:
        import anthropic
    except ImportError:
        raise SystemExit("anthropic が入っていません。 pip install anthropic を実行してください。")

    client = anthropic.Anthropic()
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        # 固定の指示部分はキャッシュして、2回目以降の料金を下げる
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=list(history or []) + [{"role": "user", "content": user}],
        output_config={"effort": effort},
    )
    if model.startswith(FALLBACK_MODELS):
        # 安全フィルタで断られた場合に、別モデルで自動的にやり直す設定
        resp = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    else:
        resp = client.messages.create(**kwargs)

    db.log_usage(con, purpose, model, resp.usage)
    if resp.stop_reason == "refusal":
        return "（AIがこの内容への回答を断りました。質問の表現を変えてお試しください）"
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def parse_json(text: str):
    """AIの返答からJSON部分を取り出す。失敗したら None。"""
    m = re.search(r"\{.*\}|\[.*\]", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
