"""指紋認証（Touch ID）。

touchid/touchid.swift を初回だけ組み立てて、秘密フォルダの bin/ に置いて使う。
Touch ID が使えないときは、Macのログインパスワードでの認証になる。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import config

SRC = Path(__file__).resolve().parent / "touchid" / "touchid.swift"


def _binary() -> Path:
    b = config.home() / "bin" / "touchid"
    if not b.exists() or b.stat().st_mtime < SRC.stat().st_mtime:
        b.parent.mkdir(exist_ok=True)
        b.parent.chmod(0o700)
        print("指紋認証の準備をしています（初回だけ、少し時間がかかります）…", flush=True)
        r = subprocess.run(["swiftc", "-O", str(SRC), "-o", str(b)], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit("指紋認証の準備に失敗しました。Xcode（またはコマンドラインツール）が入っているか確認してください。\n"
                             + r.stderr[-500:])
    return b


def require(reason: str = "ふたりの記録帳を開きます") -> None:
    """認証できなければ終了する。"""
    if subprocess.run([str(_binary()), reason]).returncode != 0:
        raise SystemExit("認証できませんでした。")
