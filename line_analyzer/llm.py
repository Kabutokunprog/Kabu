"""AIの呼び出し（トークン使用量の記録つき）。

AIの呼び出しはこのファイルだけで行う。設定 backend で呼び出し先を切り替える:
  "ollama" … Mac内のAI（Ollama）。会話は外に出ない・無料
  "claude" … Claude API（Anthropic）。精度が高い・有料・圧縮した会話が送られる
  "gemini" … Gemini API（Google）。精度が高い・圧縮した会話が送られる
"""
from __future__ import annotations

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import config
import db

FALLBACK_MODELS = ("claude-opus", "claude-sonnet", "claude-fable")
REFUSAL = "（AIがこの内容への回答を断りました。質問の表現を変えてお試しください）"

_override: str | None = None


def set_backend(name: str | None) -> None:
    """このコマンドの間だけ、設定とは別のAIを使う（読み比べ用）。"""
    global _override
    _override = name


def backend(settings=None) -> str:
    s = settings or config.load_settings()
    return _override or s.get("backend", "ollama")


def is_local(settings=None) -> bool:
    return backend(settings) == "ollama"


def chunk_chars(settings) -> int:
    """1回の要約に送る最大文字数。Mac内のAIは一度に読める量が少ないので小さくする。"""
    return settings["ollama_chars_per_chunk"] if is_local(settings) else settings["max_chars_per_chunk"]


def model_name(settings, model: str) -> str:
    """実際に使われるモデル名（Mac内のAIなら ollama_model、Geminiなら gemini_model）。"""
    b = backend(settings)
    if b == "ollama":
        return settings["ollama_model"]
    if b == "gemini":
        return settings["gemini_model"]
    return model


def estimate_tokens(text: str) -> int:
    """日本語はおおよそ1文字≒1トークン、英数字は4文字≒1トークンとして概算。"""
    ascii_n = sum(1 for c in text if ord(c) < 128)
    return int((len(text) - ascii_n) * 1.0 + ascii_n / 4)


def call(con, purpose: str, model: str, system: str, user: str,
         effort: str = "medium", max_tokens: int = 16000, history=None,
         json_mode: bool = False) -> str:
    s = config.load_settings()
    if is_local(s):
        return _call_ollama(con, purpose, s, system, user, max_tokens, history, json_mode)
    if backend(s) == "gemini":
        return _call_gemini(con, purpose, s, system, user, max_tokens, history, json_mode)
    return _call_claude(con, purpose, model, system, user, effort, max_tokens, history)


def _call_claude(con, purpose, model, system, user, effort, max_tokens, history) -> str:
    try:
        import anthropic
    except ImportError:
        raise SystemExit("anthropic が入っていません。 python3 -m pip install -r requirements.txt を実行してください。")

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
        return REFUSAL
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _call_ollama(con, purpose, s, system, user, max_tokens, history, json_mode) -> str:
    model = s["ollama_model"]
    num_ctx = int(s["ollama_num_ctx"])
    messages = [{"role": "system", "content": system}] + list(history or []) \
        + [{"role": "user", "content": user}]
    est = sum(estimate_tokens(m["content"]) for m in messages)
    if est + max_tokens > num_ctx * 1.3:
        print(f"（注意: 送る量 約{est:,}トークンが、Mac内のAIが一度に読める量 {num_ctx:,} を超えそうです。"
              "古い部分が読み飛ばされる可能性があります）", file=sys.stderr)
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,  # 考える過程を省いて速くする
        "options": {"num_ctx": num_ctx, "num_predict": min(max_tokens, 4096), "temperature": 0.3},
    }
    if json_mode:
        body["format"] = "json"
    req = urllib.request.Request(
        s["ollama_url"].rstrip("/") + "/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        if e.code == 404 or "not found" in detail:
            raise SystemExit(f"Mac内のAIに「{model}」が入っていません。ターミナルで `ollama pull {model}` を実行してください。")
        raise SystemExit(f"Mac内のAIでエラーが起きました（{e.code}）: {detail[:200]}")
    except urllib.error.URLError:
        raise SystemExit("Mac内のAI（Ollama）に接続できません。Ollamaのアプリを起動してから、もう一度お試しください。")

    db.log_usage(con, purpose, model, SimpleNamespace(
        input_tokens=resp.get("prompt_eval_count", 0), output_tokens=resp.get("eval_count", 0)))
    text = (resp.get("message") or {}).get("content", "")
    # 考える過程を本文に混ぜるモデルがあるので取り除く
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    env = Path.home() / ".claude" / "gemini.env"  # ほかのツールと共用の保存場所
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(("GEMINI_API_KEY=", "export GEMINI_API_KEY=")):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise SystemExit("GeminiのAPIキーがありません。 export GEMINI_API_KEY=... で設定してください。")
    return key


def _ssl_context():
    """python.org版のPythonは証明書の一覧が空のことがあるので、そのときはMac本体の一覧を使う。"""
    ctx = ssl.create_default_context()
    if not ctx.cert_store_stats().get("x509_ca") and Path("/etc/ssl/cert.pem").exists():
        ctx.load_verify_locations("/etc/ssl/cert.pem")
    return ctx


def _call_gemini(con, purpose, s, system, user, max_tokens, history, json_mode) -> str:
    model = s["gemini_model"]
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in list(history or [])] + [{"role": "user", "parts": [{"text": user}]}]
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.4},
        # 恋人同士の会話の分析なので、性的な話題でも止めないようにする
        "safetySettings": [{"category": c, "threshold": "BLOCK_NONE"} for c in (
            "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")],
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": _gemini_key()})
    try:
        with urllib.request.urlopen(req, timeout=600, context=_ssl_context()) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Geminiでエラーが起きました（{e.code}）: {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError:
        raise SystemExit("Geminiに接続できません。インターネットの接続を確認してください。")

    u = resp.get("usageMetadata") or {}
    db.log_usage(con, purpose, model, SimpleNamespace(
        input_tokens=u.get("promptTokenCount", 0),
        output_tokens=u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)))
    cands = resp.get("candidates") or []
    if not cands or cands[0].get("finishReason") in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
        return REFUSAL
    parts = (cands[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def parse_json(text: str):
    """AIの返答からJSON部分を取り出す。失敗したら None。"""
    m = re.search(r"\{.*\}|\[.*\]", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
