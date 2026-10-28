"""設定と保存場所（秘密フォルダ）の管理。

会話データはリポジトリの外、ホームディレクトリ直下の秘密フォルダに保存する。
フォルダは本人だけが読める権限（700）にする。
場所は環境変数 LA_HOME で変更できる（例: 暗号化ディスクイメージの中）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_HOME = Path.home() / ".line_analyzer_private"

DEFAULT_SETTINGS = {
    # LINE上の表示名（初回取り込み時に設定）
    "me_name": "",
    "partner_name": "",
    # 分析結果での呼び方
    "me_label": "彼",
    "partner_label": "彼女",
    # 質問への回答の話し方: "onee"（ノリの良い色っぽいお姉さん） / "plain"（丁寧な説明）
    "persona": "onee",
    # 使うAI: "ollama"（Mac内のAI・オフライン・無料） / "claude"（Claude API・有料）
    "backend": "ollama",
    # 使うClaudeのモデル（費用を抑えたい場合は summary を claude-haiku-5-5 に）
    "model_summary": "claude-opus-5-5",
    "model_answer": "claude-opus-5-5",
    # 1回の要約に送る最大文字数（これを超える月は分割して要約）
    "max_chars_per_chunk": 40000,
    # Mac内のAI（Ollama）の設定
    "ollama_model": "qwen3.5:9b",       # 候補: qwen3.5:9b / gemma4:12b / qwen3:8b
    "ollama_url": "http://localhost:11434",
    "ollama_num_ctx": 16384,          # 一度に読める量（トークン）
    "ollama_chars_per_chunk": 8000,   # Mac内のAIで1回に送る最大文字数
}


def home() -> Path:
    p = Path(os.environ.get("LA_HOME", DEFAULT_HOME)).expanduser()
    if not p.exists():
        p.mkdir(parents=True)
    os.chmod(p, 0o700)
    return p


def db_path() -> Path:
    return home() / "talk.db"


def settings_path() -> Path:
    return home() / "settings.json"


def glossary_path() -> Path:
    return home() / "glossary.json"


def reports_dir() -> Path:
    p = home() / "reports"
    p.mkdir(exist_ok=True)
    return p


def secure(path: Path) -> None:
    """ファイルを本人だけが読み書きできる権限にする。"""
    if path.exists():
        os.chmod(path, 0o600)


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    p = settings_path()
    if p.exists():
        s.update(json.loads(p.read_text(encoding="utf-8")))
    return s


def save_settings(s: dict) -> None:
    p = settings_path()
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    secure(p)
