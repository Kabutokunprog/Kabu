"""LINEのトーク履歴テキスト（エクスポートファイル）を1メッセージずつに分解する。

対応している書式:
  iPhone / Android の新しい形式   2024/04/01(月) + "09:15<TAB>名前<TAB>本文"
  Android の古い形式             "午後3:05 名前 本文" など
  PC版の古い形式                 2019.04.01 月曜日
  曜日が先・月/日/年の形式        火, 10/28/2026
複数行のメッセージ（"..." で囲まれる）にも対応。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DATE_RE = re.compile(
    r"^\s*(\d{4})[/.](\d{1,2})[/.](\d{1,2})\s*(?:\(.{1,3}\)|（.{1,3}）|[月火水木金土日]曜日?)?\s*$"
)
# 「火, 10/28/2026」「Tue, 10/28/2026」のように曜日が先で、月/日/年の順の形式
DATE_MDY_RE = re.compile(r"^\s*(?:[月火水木金土日]|[A-Z][a-z]{2})[^,]{0,3},\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")
TIME_RE = re.compile(r"^(午前|午後|AM|PM)?\s?(\d{1,2}):(\d{2})(?:\t| )(.*)$")
CALL_RE = re.compile(r"通話時間\s*(?:(\d+):)?(\d{1,2}):(\d{2})")

KIND_MARKERS = {
    "sticker": ("[スタンプ]", "[Sticker]"),
    "photo": ("[写真]", "[Photo]", "[アルバム]"),
    "video": ("[動画]", "[Video]"),
    "voice": ("[ボイスメッセージ]", "[Voice message]"),
    "file": ("[ファイル]", "[File]"),
    "location": ("[位置情報]", "[Location]"),
}


@dataclass
class Message:
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    sender: str | None  # None = システムメッセージ
    text: str
    kind: str = "text"
    call_sec: int = 0


def _kind_of(text: str) -> tuple[str, int]:
    t = text.strip()
    if "☎" in t or "通話時間" in t or "不在着信" in t or "通話をキャンセル" in t:
        m = CALL_RE.search(t)
        if m:
            h, mi, s = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
            return "call", h * 3600 + mi * 60 + s
        return "call", 0
    if "メッセージの送信を取り消しました" in t:
        return "unsent", 0
    for kind, marks in KIND_MARKERS.items():
        if t in marks:
            return kind, 0
    return "text", 0


def parse(lines) -> list[Message]:
    msgs: list[Message] = []
    cur_date: str | None = None
    in_quote = False

    for raw in lines:
        line = raw.rstrip("\r\n").lstrip("﻿")

        # 複数行メッセージの続き
        if in_quote and msgs:
            if line.endswith('"'):
                msgs[-1].text += "\n" + line[:-1]
                in_quote = False
            else:
                msgs[-1].text += "\n" + line
            continue

        m = DATE_RE.match(line)
        if m:
            y, mo, d = m.groups()[:3]
            cur_date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            continue
        m = DATE_MDY_RE.match(line)
        if m:
            mo, d, y = m.groups()
            cur_date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            continue

        if cur_date is None:
            continue  # ヘッダー部分（[LINE] ○○とのトーク履歴 など）

        t = TIME_RE.match(line)
        if not t:
            if line.strip() and msgs:
                msgs[-1].text += "\n" + line  # 引用符なしの改行の続き
            continue

        ampm, hh, mm, rest = t.groups()
        h = int(hh)
        if ampm in ("午後", "PM") and h < 12:
            h += 12
        if ampm in ("午前", "AM") and h == 12:
            h = 0
        time = f"{h:02d}:{mm}"

        if "\t" in rest:
            parts = rest.split("\t", 1)
        else:
            parts = rest.split(" ", 1)
        if len(parts) == 2:
            sender, text = parts
        else:
            sender, text = None, parts[0]  # 「○○がアルバムを作成しました」等

        if text.startswith('"') and not (len(text) > 1 and text.endswith('"')):
            in_quote = True
            text = text[1:]
        elif len(text) > 1 and text.startswith('"') and text.endswith('"'):
            text = text[1:-1]

        kind, call_sec = _kind_of(text)
        msgs.append(Message(cur_date, time, sender, text, kind, call_sec))

    return msgs


def parse_file(path: str) -> list[Message]:
    with open(path, "rb") as f:
        head = f.read(2)
    encs = ("utf-16",) if head in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp932")
    for enc in encs:
        try:
            with open(path, encoding=enc) as f:
                return parse(f)
        except UnicodeError:
            continue
    raise ValueError("文字コードを判別できませんでした: " + path)
