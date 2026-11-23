"""フラッシュ暗記カード: サーバー側 (Vercel Python Function)

ブラウザからは POST /api/flash に {"action": "...", ...} を送る。
合言葉は X-Flash-Pass ヘッダーで受け取り、Supabase へそのまま渡す
(Supabase 側の RLS が「親 / 子」を判定する)。
"""
import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

SUPABASE_URL = os.environ.get("FLASH_SUPABASE_URL", "https://cgwydtowirpjekmskxgx.supabase.co")
# 公開用(anon)キー。データは RLS と合言葉で守られている。
SUPABASE_KEY = os.environ.get(
    "FLASH_SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNnd3lkdG93aXJwamVrbXNreGd4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODczNTc5OTcsImV4cCI6MjEwMjkzMzk5N30.T6xwm4_5Pur_t7srRx3ND4tolwus698ZnatENDOPeqo",
)
MODEL = os.environ.get("FLASH_MODEL", "claude-opus-5-5")
# 画面で選べる AI (どちらも「中エフォート」で問題を作り、読み取りは「低エフォート」)
MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5"}
MODEL_LABEL = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5"}


def pick_model(key):
    return MODELS.get(key or "", MODEL)
MOCK = os.environ.get("FLASH_MOCK") == "1"  # ローカル確認用 (DB も AI も使わない)

# 復習フラッシュ: 連続正解の回数 -> 次に出すまでの日数。3回連続正解で卒業。
REVIEW_INTERVAL_DAYS = {1: 1, 2: 3}
REVIEW_GRADUATE = 3

CARD_FIELDS = ("question", "answer", "note", "example", "tag")


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat() if dt else None


def clean_card(c):
    out = {}
    for k in CARD_FIELDS:
        v = c.get(k)
        out[k] = str(v).strip() if v is not None else ""
    return out


def apply_answer(prog, correct, mode):
    """1回の解答結果を progress 行に反映する (復習フラッシュのルールもここ)。"""
    t = now_utc()
    p = dict(prog or {})
    p.setdefault("correct_count", 0)
    p.setdefault("wrong_count", 0)
    p.setdefault("in_review", False)
    p.setdefault("review_streak", 0)
    p["last_answered_at"] = iso(t)
    if correct:
        p["correct_count"] += 1
        p["last_result"] = "correct"
        if mode == "review" and p["in_review"]:
            p["review_streak"] += 1
            if p["review_streak"] >= REVIEW_GRADUATE:
                p["in_review"] = False
                p["next_due_at"] = None
            else:
                days = REVIEW_INTERVAL_DAYS.get(p["review_streak"], 1)
                p["next_due_at"] = iso(t + timedelta(days=days))
    else:
        p["wrong_count"] += 1
        p["last_result"] = "wrong"
        p["in_review"] = True
        p["review_streak"] = 0
        p["next_due_at"] = iso(t)
    return p


# ---------------------------------------------------------------- Supabase


class SupaStore:
    def __init__(self, passcode):
        self.h = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "x-flash-pass": passcode or "",
        }

    def _req(self, method, path, params=None, body=None, prefer=None):
        h = dict(self.h)
        if prefer:
            h["Prefer"] = prefer
        r = requests.request(method, f"{SUPABASE_URL}/rest/v1/{path}", params=params,
                             data=json.dumps(body) if body is not None else None, headers=h, timeout=30)
        if r.status_code >= 400:
            if r.status_code in (401, 403) or "row-level security" in r.text:
                raise ApiError("この操作をする権限がありません", 403)
            raise ApiError(f"データベースエラー: {r.text[:300]}", 500)
        return r.json() if r.text else None

    def rpc(self, name, args=None):
        return self._req("POST", f"rpc/{name}", body=args or {})

    # 役割
    def is_setup(self):
        return bool(self.rpc("flash_is_setup"))

    def setup(self, family_pass):
        return self.rpc("flash_setup", {"family_pass": family_pass})

    def whoami(self):
        return self.rpc("flash_whoami")

    def change_pass(self, new_pass):
        return self.rpc("flash_change_pass", {"new_pass": new_pass})

    # 学習者 (息子・娘)
    def list_profiles(self):
        return self._req("GET", "flash_profiles", {"select": "*", "order": "sort.asc,id.asc"})

    def update_profile(self, pid, data):
        self._req("PATCH", "flash_profiles", {"id": f"eq.{int(pid)}"}, data, prefer="return=minimal")

    def add_profile(self, data):
        self._req("POST", "flash_profiles", body=data, prefer="return=minimal")

    # 教材
    def list_decks(self, profile_id):
        decks = self._req("GET", "flash_decks", {
            "profile_id": f"eq.{int(profile_id)}",
            "select": "id,profile_id,created_at,title,grade,term,subject,card_kind,memo,flash_cards(count)",
            "order": "created_at.desc,id.desc"})
        prog = self._req("GET", "flash_progress", {
            "select": "correct_count,wrong_count,in_review,flash_cards!inner(deck_id,flash_decks!inner(profile_id))",
            "flash_cards.flash_decks.profile_id": f"eq.{int(profile_id)}"})
        for d in decks:
            cnt = d.pop("flash_cards", None) or [{"count": 0}]
            d["card_count"] = cnt[0]["count"] if cnt else 0
        return decks, [
            {"deck_id": (p.get("flash_cards") or {}).get("deck_id"), **{k: p[k] for k in ("correct_count", "wrong_count", "in_review")}}
            for p in prog]

    def get_deck(self, deck_id):
        rows = self._req("GET", "flash_decks", {"id": f"eq.{int(deck_id)}", "select": "*"})
        if not rows:
            raise ApiError("教材が見つかりません", 404)
        cards = self._req("GET", "flash_cards", {
            "deck_id": f"eq.{int(deck_id)}", "select": "*,flash_progress(*)", "order": "position.asc,id.asc"})
        for c in cards:
            p = c.pop("flash_progress", None)
            if isinstance(p, list):
                p = p[0] if p else None
            c["progress"] = p
        return rows[0], cards

    def create_deck(self, deck, cards):
        d = self._req("POST", "flash_decks", body=deck, prefer="return=representation")[0]
        rows = [{"deck_id": d["id"], "position": i, **clean_card(c)} for i, c in enumerate(cards)]
        if rows:
            self._req("POST", "flash_cards", body=rows, prefer="return=minimal")
        return d

    def update_deck(self, deck_id, data):
        self._req("PATCH", "flash_decks", {"id": f"eq.{int(deck_id)}"}, data, prefer="return=minimal")

    def delete_deck(self, deck_id):
        self._req("DELETE", "flash_decks", {"id": f"eq.{int(deck_id)}"})

    # カード
    def get_cards(self, ids):
        if not ids:
            return []
        return self._req("GET", "flash_cards", {"id": f"in.({','.join(str(int(i)) for i in ids)})", "select": "*"})

    def update_card(self, card_id, data):
        data = dict(data, updated_at=iso(now_utc()))
        self._req("PATCH", "flash_cards", {"id": f"eq.{int(card_id)}"}, data, prefer="return=minimal")

    def delete_cards(self, ids):
        if ids:
            self._req("DELETE", "flash_cards", {"id": f"in.({','.join(str(int(i)) for i in ids)})"})

    def add_cards(self, deck_id, cards, start_pos):
        rows = [{"deck_id": int(deck_id), "position": start_pos + i, **clean_card(c)} for i, c in enumerate(cards)]
        if rows:
            self._req("POST", "flash_cards", body=rows, prefer="return=minimal")

    # 成績
    def get_progress(self, card_id):
        rows = self._req("GET", "flash_progress", {"card_id": f"eq.{int(card_id)}", "select": "*"})
        return rows[0] if rows else None

    def save_progress(self, row):
        self._req("POST", "flash_progress", body=row, prefer="resolution=merge-duplicates,return=minimal")

    def review_cards(self, profile_id):
        rows = self._req("GET", "flash_progress", {
            "in_review": "is.true",
            "select": "*,flash_cards!inner(*,flash_decks!inner(id,profile_id,title,subject,grade,term,card_kind))",
            "flash_cards.flash_decks.profile_id": f"eq.{int(profile_id)}",
            "order": "next_due_at.asc"})
        out = []
        for p in rows:
            c = p.pop("flash_cards", None)
            if not c:
                continue
            deck = c.pop("flash_decks", None) or {}
            c["progress"] = p
            c["deck"] = deck
            out.append(c)
        return out


class MemoryStore:
    """ローカル確認用。サーバーを止めると消える。"""
    data = {"members": {}, "profiles": [], "decks": [], "cards": [], "progress": {}, "seq": 0}

    def __init__(self, passcode):
        self.passcode = passcode or ""

    def _id(self):
        self.data["seq"] += 1
        return self.data["seq"]

    def is_setup(self):
        return bool(self.data["members"])

    def setup(self, p):
        if self.data["members"]:
            return "already"
        if len(p) < 6:
            return "invalid"
        self.data["members"] = {p: "family"}
        if not self.data["profiles"]:
            self.data["profiles"] = [dict(id=self._id(), name="息子", emoji="👦", sort=1),
                                     dict(id=self._id(), name="娘", emoji="👧", sort=2)]
        return "ok"

    def whoami(self):
        return self.data["members"].get(self.passcode)

    def change_pass(self, new_pass):
        if not self.whoami():
            return "forbidden"
        if len(new_pass) < 6:
            return "invalid"
        self.data["members"] = {new_pass: "family"}
        return "ok"

    def _need(self, parent=False):
        if not self.whoami():
            raise ApiError("この操作をする権限がありません", 403)

    def list_profiles(self):
        self._need()
        return sorted([dict(p) for p in self.data["profiles"]], key=lambda p: (p["sort"], p["id"]))

    def update_profile(self, pid, data):
        self._need()
        for p in self.data["profiles"]:
            if p["id"] == int(pid):
                p.update(data)

    def add_profile(self, data):
        self._need()
        self.data["profiles"].append(dict(id=self._id(), **data))

    def list_decks(self, profile_id):
        self._need()
        decks = []
        mine = [d for d in self.data["decks"] if d["profile_id"] == int(profile_id)]
        for d in sorted(mine, key=lambda d: (d["created_at"], d["id"]), reverse=True):
            x = {k: v for k, v in d.items() if k != "source_text"}
            x["card_count"] = sum(1 for c in self.data["cards"] if c["deck_id"] == d["id"])
            decks.append(x)
        my_ids = {d["id"] for d in mine}
        deck_of = {c["id"]: c["deck_id"] for c in self.data["cards"]}
        prog = [{"deck_id": deck_of.get(cid), **{k: p[k] for k in ("correct_count", "wrong_count", "in_review")}}
                for cid, p in self.data["progress"].items() if deck_of.get(cid) in my_ids]
        return decks, prog

    def get_deck(self, deck_id):
        self._need()
        d = next((d for d in self.data["decks"] if d["id"] == int(deck_id)), None)
        if not d:
            raise ApiError("教材が見つかりません", 404)
        cards = sorted([dict(c) for c in self.data["cards"] if c["deck_id"] == d["id"]], key=lambda c: (c["position"], c["id"]))
        for c in cards:
            c["progress"] = self.data["progress"].get(c["id"])
        return dict(d), cards

    def create_deck(self, deck, cards):
        self._need()
        d = dict(id=self._id(), created_at=iso(now_utc()), **deck)
        self.data["decks"].append(d)
        self.add_cards(d["id"], cards, 0)
        return d

    def update_deck(self, deck_id, data):
        self._need()
        for d in self.data["decks"]:
            if d["id"] == int(deck_id):
                d.update(data)

    def delete_deck(self, deck_id):
        self._need()
        self.data["decks"] = [d for d in self.data["decks"] if d["id"] != int(deck_id)]
        ids = {c["id"] for c in self.data["cards"] if c["deck_id"] == int(deck_id)}
        self.delete_cards(ids)

    def get_cards(self, ids):
        ids = {int(i) for i in ids}
        return [dict(c) for c in self.data["cards"] if c["id"] in ids]

    def update_card(self, card_id, data):
        self._need()
        for c in self.data["cards"]:
            if c["id"] == int(card_id):
                c.update(data)

    def delete_cards(self, ids):
        self._need()
        ids = {int(i) for i in ids}
        self.data["cards"] = [c for c in self.data["cards"] if c["id"] not in ids]
        for i in ids:
            self.data["progress"].pop(i, None)

    def add_cards(self, deck_id, cards, start_pos):
        self._need()
        for i, c in enumerate(cards):
            self.data["cards"].append(dict(id=self._id(), deck_id=int(deck_id), position=start_pos + i,
                                           needs_regen=False, **clean_card(c)))

    def get_progress(self, card_id):
        self._need()
        return self.data["progress"].get(int(card_id))

    def save_progress(self, row):
        self._need()
        self.data["progress"][int(row["card_id"])] = row

    def review_cards(self, profile_id):
        self._need()
        out = []
        for cid, p in self.data["progress"].items():
            if not p.get("in_review"):
                continue
            c = next((dict(c) for c in self.data["cards"] if c["id"] == cid), None)
            if not c:
                continue
            d = next((d for d in self.data["decks"] if d["id"] == c["deck_id"]), {})
            if d.get("profile_id") != int(profile_id):
                continue
            c["progress"] = p
            c["deck"] = {k: d.get(k) for k in ("id", "profile_id", "title", "subject", "grade", "term", "card_kind")}
            out.append(c)
        return sorted(out, key=lambda c: c["progress"].get("next_due_at") or "")


# ---------------------------------------------------------------- AI (Claude)

STYLE_GUIDE = {
    "auto": "教材を見て、下の「一問一答」「単語型」「テスト予想」のうち最も合う作り方を自分で判断してください。",
    "qa": "【一問一答】教材に問題と答え(模範解答)が載っています。その問題と答えをそのまま、もれなくカードにしてください。答えが書かれていない問題は、自分で正しく解いて答えを入れてください。",
    "word": "【単語型】教材は単語集・用語集です。見出し語ごとに1枚、question=見出し語(古文単語ならひらがなの見出し語。漢字表記は答えがばれるので question に書かない)、answer=意味 (複数の意味は ①②③ で全部)。",
    "predict": "【テスト予想】教材は授業プリント・参考書です。定期テストに出そうなところを予想して、自分で問題を作ってください。穴埋め欄【 】・赤字・太字・マーカー部分は必ず問題にします。図や表から読み取れる重要事項、計算・判定の手順も問題にします。",
}


def build_generate_prompt(o):
    lines = [
        "あなたは日本の中学生・高校生の定期テスト対策を手伝うベテラン教師です。",
        "下の教材の内容から、暗記用フラッシュカード(表=問題、裏=答え)を作ってください。",
        "",
        f"学年: {o.get('grade') or '不明'} / テスト: {o.get('term') or '不明'} / 科目: {o.get('subject') or '不明'}",
        "",
        "## 作り方",
        STYLE_GUIDE.get(o.get("style") or "auto", STYLE_GUIDE["auto"]),
        "",
        "## カードの書き方 (どの作り方でも共通)",
        "- question: 1枚で答えが1つに決まる問い。「〜した人物は誰か。」「〜を何というか。」のように、それだけ読んで分かる文にする(時代・場面などの手がかりを入れる)。問題文の中に答えを書かない。",
        "- answer: できるだけ短く(用語・人名・年号など)。難しい漢字の答えには note に読みがなを書く。",
        "- note: 覚え方のコツ・関連事項・読みがななどの一言解説(なければ空)。",
        "- example: 単語型なら教材の例文と訳(「例文（出典）→訳：…」の形)。それ以外は空でよい。",
        "- tag: 小さなラベル。歴史なら時代や年(例:「1716年 享保」)、単語型なら品詞(例:「形・ク」)、それ以外は単元名など短く。",
        "- 内容は教材にあることを中心に。教材の誤字や手書きの書き込みは正しい内容に直してよい。",
        "- 同じ問いを重複させない。",
        "",
        "## 並べ方",
        "- 歴史(日本史・世界史・歴史的分野)は、古い出来事から新しい出来事へ時代順(時系列)に並べる。プリントの順番より時代順を優先する。",
        "- それ以外は教材の順番どおり(プリント番号・ページ・問題番号の順)。",
    ]
    if o.get("style") == "predict" or (o.get("style") == "auto"):
        if o.get("include_written"):
            lines.append("- 「説明しよう」「理由を書こう」などの記述問題も、question の先頭に【記述】と付けて数問入れ、answer に模範解答(2〜3文)を書く。")
        else:
            lines.append("- 記述問題は作らず、短い答えの問題だけにする。")
    if o.get("style") == "word" or o.get("style") == "auto":
        if o.get("include_related"):
            lines.append("- 単語型の場合、関連語・類義語・対義語も別のカードにする。")
        else:
            lines.append("- 単語型の場合、関連語は別のカードにせず note に一言だけ書く。")
    count = o.get("count") or "auto"
    if count == "auto":
        lines.append("- 枚数: おまかせ。単語集・用語集なら見出し語の数だけ、問題と答えが載っている教材なら問題の数だけ、ちょうど全部をカードにする(抜かさない・水増ししない)。それ以外は重要事項をもれなく(最大150枚)。")
    else:
        n = max(5, min(150, int(count)))
        lines.append(f"- 枚数: だいたい {n} 枚 (±1割)。教材の内容が少なければ無理に増やさず、多ければ大事なものから選ぶ。")
    if (o.get("instructions") or "").strip():
        lines += ["", "## 追加の指示 (家族から)", o["instructions"].strip()]
    lines += ["", "## 出力",
              "title には教材名を短く(例:「江戸時代③④」「古文単語 122〜149」)。card_kind は単語型なら word、それ以外は qa。",
              "", "## 教材の内容 (写真・PDF から書き起こしたもの)", "<material>", o.get("source_text", ""), "</material>"]
    return "\n".join(lines)


CARD_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in CARD_FIELDS},
    "required": list(CARD_FIELDS),
    "additionalProperties": False,
}
GENERATE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "card_kind": {"type": "string", "enum": ["word", "qa"]},
        "cards": {"type": "array", "items": CARD_SCHEMA},
    },
    "required": ["title", "card_kind", "cards"],
    "additionalProperties": False,
}
REGEN_SCHEMA = {
    "type": "object",
    "properties": {"cards": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, **{k: {"type": "string"} for k in CARD_FIELDS}},
        "required": ["id", *CARD_FIELDS],
        "additionalProperties": False}}},
    "required": ["cards"],
    "additionalProperties": False,
}

TRANSCRIBE_PROMPT = """これは日本の中学生・高校生の教材(問題集・プリント・参考書・単語集など)の写真またはPDFのページです。
後でこの文字起こしだけを見てテスト対策の問題を作るので、内容をもれなく正確に文字に起こしてください。

- 読む順番どおりに(縦書きは右の行から)。ページの区切りは「=== ページ N ===」と書く。
- 見出し・番号・問題文・答え(模範解答)をすべて書く。問題と答えが別の列にあるときは「1. 問題文 → 答え」のように対応させる。
- 穴埋め欄【 】や( )に書き込まれた答えは【答え】の形で残す。空欄なら【　】のまま。
- 赤字・太字・マーカーの語句は ★語句★ のように印をつける。
- 表は「項目: 内容」の形で行ごとに。図・グラフ・地図は [図: 何を表しているか、読み取れる重要事項] と短く説明する。
- 手書きの書き込みで内容に関係するもの(読みがな・補足)は (手書き: …) として残す。落書きは無視。
- 文字起こしだけを出力し、前置きや感想は書かない。"""


def anthropic_client():
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ApiError("AIの鍵(ANTHROPIC_API_KEY)がまだ設定されていません。Vercel の設定で登録してください。", 500)
    return anthropic.Anthropic(max_retries=2)


def claude_call(content, effort, schema=None, max_tokens=32000, model=None):
    """Claude を呼んで最終テキストを返す (長くなるので stream で受け取る)。"""
    import anthropic
    client = anthropic_client()
    kwargs = dict(
        model=model or MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": effort},
    )
    if schema:
        kwargs["output_config"]["format"] = {"type": "json_schema", "schema": schema}
    if kwargs["model"] in ("claude-opus-5-5", "claude-fable-5-2", "claude-sonnet-5-5"):
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
        stream_fn = client.beta.messages.stream
    else:
        stream_fn = client.messages.stream
    try:
        with stream_fn(**kwargs) as stream:
            msg = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise ApiError("AIの鍵(ANTHROPIC_API_KEY)が正しくないようです。", 500)
    except anthropic.RateLimitError:
        raise ApiError("AIが混み合っています。少し待ってからもう一度お試しください。", 429)
    except anthropic.APIStatusError as e:
        raise ApiError(f"AIでエラーが起きました ({e.status_code})。もう一度お試しください。", 502)
    except anthropic.APIConnectionError:
        raise ApiError("AIにつながりませんでした。もう一度お試しください。", 502)
    if msg.stop_reason == "refusal":
        raise ApiError("AIがこの教材の処理を断りました。別の写真でお試しください。", 422)
    if msg.stop_reason == "max_tokens":
        raise ApiError("教材が長すぎて最後まで作れませんでした。写真を分けてお試しください。", 422)
    return "".join(b.text for b in msg.content if b.type == "text")


def ai_transcribe(images, page_offset, model=None):
    if MOCK:
        return "\n".join(f"=== ページ {page_offset + i + 1} ===\n(お試しモード: 文字起こしの代わり)\n1. 江戸幕府を開いた人物は誰か。 → 徳川家康\n2. 8代将軍が行った改革は何か。 → 享保の改革"
                         for i in range(len(images)))
    content = []
    for img in images:
        m = re.match(r"data:(image/(?:jpeg|png|webp|gif));base64,(.*)$", img, re.S)
        if not m:
            raise ApiError("画像の形式が読み取れません")
        content.append({"type": "image", "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)}})
    content.append({"type": "text", "text": TRANSCRIBE_PROMPT + f"\n\n(このまとまりは全体の {page_offset + 1} ページ目からです)"})
    return claude_call(content, "low", max_tokens=32000, model=model).strip()


def ai_generate(opts):
    if MOCK:
        cards = [
            {"question": "江戸幕府を開いた人物は誰か。", "answer": "徳川家康", "note": "とくがわいえやす", "example": "", "tag": "1603年"},
            {"question": "8代将軍徳川吉宗が行った改革を何というか。", "answer": "享保の改革", "note": "きょうほう", "example": "", "tag": "1716年"},
            {"question": "老中松平定信による改革を何というか。", "answer": "寛政の改革", "note": "かんせい", "example": "", "tag": "1787年"},
        ]
        return {"title": "お試し教材", "card_kind": "qa", "cards": cards}
    text = claude_call(build_generate_prompt(opts), "medium", schema=GENERATE_SCHEMA, max_tokens=64000,
                       model=pick_model(opts.get("model")))
    data = json.loads(text)
    data["cards"] = [clean_card(c) for c in data.get("cards", []) if c.get("question") and c.get("answer")]
    if not data["cards"]:
        raise ApiError("問題を作れませんでした。教材の写真が読み取りにくいかもしれません。", 422)
    return data


def ai_regenerate(deck, targets, others, instructions):
    if MOCK:
        return [dict(id=c["id"], question=c["question"] + "(作り直し)", answer=c["answer"], note=c.get("note", ""),
                     example=c.get("example", ""), tag=c.get("tag", "")) for c in targets]
    prompt = "\n".join([
        "あなたは日本の中学生・高校生の定期テスト対策を手伝うベテラン教師です。",
        f"教材「{deck.get('title')}」(学年: {deck.get('grade') or '不明'} / 科目: {deck.get('subject') or '不明'}) のフラッシュカードのうち、",
        "「作り直してほしい」と印がついたカードを、より良い問題に作り直してください。",
        "",
        "- 同じ id のまま、question / answer / note / example / tag をすべて書き直して返す。",
        "- 答えが1つに決まり、問題文だけで何を聞かれているか分かるようにする。問題文に答えを書かない。",
        "- 教材の内容の範囲で作る。ほかのカードと同じ問いにならないようにする。",
        "- 単語型(card_kind=word)なら question=見出し語、answer=意味 の形を守る。",
        f"- card_kind: {deck.get('card_kind')}",
        "",
        "## 作り直しの指示", (instructions or "").strip() or "(特になし。分かりやすく、テストに出やすい形にしてください)",
        "", "## 作り直すカード", json.dumps(targets, ensure_ascii=False),
        "", "## ほかのカードの問題(重複しないように)", json.dumps(others, ensure_ascii=False),
        "", "## 教材の内容", "<material>", deck.get("source_text") or "(記録なし)", "</material>",
    ])
    data = json.loads(claude_call(prompt, "medium", schema=REGEN_SCHEMA, max_tokens=32000))
    return data.get("cards", [])


# ---------------------------------------------------------------- API


def store_for(passcode):
    return MemoryStore(passcode) if MOCK else SupaStore(passcode)


def require_login(store):
    role = store.whoami()
    if not role:
        raise ApiError("合言葉が違います", 401)
    return role


def deck_stats(decks, prog):
    empty = {"answered": 0, "correct": 0, "wrong": 0, "in_review": 0, "mastered": 0}
    stats = {}
    for p in prog:
        st = stats.setdefault(p["deck_id"], dict(empty))
        st["answered"] += 1
        st["correct"] += p["correct_count"]
        st["wrong"] += p["wrong_count"]
        st["in_review"] += 1 if p["in_review"] else 0
        st["mastered"] += 1 if (p["correct_count"] > 0 and not p["in_review"]) else 0
    for d in decks:
        d["stats"] = stats.get(d["id"], dict(empty))
    return decks


def is_due(card):
    due = (card.get("progress") or {}).get("next_due_at")
    if not due:
        return True
    try:
        return datetime.fromisoformat(due.replace("Z", "+00:00")) <= now_utc()
    except ValueError:
        return True


DECK_EDIT_FIELDS = ("title", "grade", "term", "subject", "memo", "card_kind", "profile_id")


def handle(action, body, passcode):
    s = store_for(passcode)

    if action == "status":
        return {"setup": s.is_setup(), "ok": bool(passcode) and bool(s.whoami()), "mock": MOCK}
    if action == "setup":
        r = s.setup(str(body.get("family_pass", "")))
        if r == "already":
            raise ApiError("すでに設定済みです")
        if r != "ok":
            raise ApiError("合言葉は6文字以上にしてください")
        return {"ok": True}

    require_login(s)

    if action == "change_pass":
        if s.change_pass(str(body.get("new_pass", ""))) != "ok":
            raise ApiError("合言葉は6文字以上にしてください")
        return {"ok": True}

    if action == "list_profiles":
        return {"profiles": s.list_profiles()}

    if action == "update_profile":
        data = {k: str(body[k]).strip() for k in ("name", "emoji") if k in body}
        if "name" in data and not data["name"]:
            raise ApiError("名前を入れてください")
        s.update_profile(body["profile_id"], data)
        return {"ok": True}

    if action == "add_profile":
        name = str(body.get("name") or "").strip()
        if not name:
            raise ApiError("名前を入れてください")
        s.add_profile({"name": name, "emoji": str(body.get("emoji") or "🙂"), "sort": int(body.get("sort") or 9)})
        return {"ok": True}

    if action == "list_decks":
        decks, prog = s.list_decks(body["profile_id"])
        stats = {}
        return {"decks": deck_stats(decks, prog)}

    if action == "overview":
        out = []
        for p in s.list_profiles():
            decks, prog = s.list_decks(p["id"])
            decks = deck_stats(decks, prog)
            due = [c for c in s.review_cards(p["id"]) if is_due(c)]
            out.append(dict(p, deck_count=len(decks), card_count=sum(d["card_count"] for d in decks),
                            mastered=sum(d["stats"]["mastered"] for d in decks),
                            in_review=sum(d["stats"]["in_review"] for d in decks), due=len(due)))
        return {"profiles": out}

    if action == "get_deck":
        deck, cards = s.get_deck(body["deck_id"])
        return {"deck": deck, "cards": cards}

    if action == "answer":
        mode = body.get("mode", "normal")
        prog = s.get_progress(body["card_id"])
        row = apply_answer(prog, bool(body.get("correct")), mode)
        row["card_id"] = int(body["card_id"])
        s.save_progress(row)
        return {"progress": row}

    if action == "review_list":
        return {"cards": s.review_cards(body["profile_id"]), "now": iso(now_utc())}

    if action == "transcribe":
        images = body.get("images") or []
        if not images:
            raise ApiError("画像がありません")
        return {"text": ai_transcribe(images, int(body.get("page_offset", 0)), pick_model(body.get("model")))}

    if action == "generate":
        if not (body.get("source_text") or "").strip():
            raise ApiError("教材の内容が空です")
        data = ai_generate(body)
        data["model_label"] = MODEL_LABEL.get(pick_model(body.get("model")), "")
        return data

    if action == "create_deck":
        deck = {k: str(body.get(k) or "") for k in ("title", "grade", "term", "subject", "source_text", "memo")}
        deck["title"] = deck["title"] or "無題の教材"
        deck["card_kind"] = "word" if body.get("card_kind") == "word" else "qa"
        deck["profile_id"] = int(body["profile_id"])
        d = s.create_deck(deck, body.get("cards") or [])
        return {"deck_id": d["id"]}

    if action == "update_deck":
        data = {k: str(body[k]) for k in DECK_EDIT_FIELDS if k in body}
        s.update_deck(body["deck_id"], data)
        return {"ok": True}

    if action == "delete_deck":
        s.delete_deck(body["deck_id"])
        return {"ok": True}

    if action == "update_card":
        data = {k: str(body[k]).strip() for k in CARD_FIELDS if k in body}
        if "needs_regen" in body:
            data["needs_regen"] = bool(body["needs_regen"])
        s.update_card(body["card_id"], data)
        return {"ok": True}

    if action == "add_card":
        deck, cards = s.get_deck(body["deck_id"])
        pos = (max([c["position"] for c in cards]) + 1) if cards else 0
        s.add_cards(deck["id"], [body], pos)
        return {"ok": True}

    if action == "delete_cards":
        s.delete_cards(body.get("card_ids") or [])
        return {"ok": True}

    if action == "regenerate":
        deck, cards = s.get_deck(body["deck_id"])
        ids = {int(i) for i in body.get("card_ids") or []}
        targets = [{"id": c["id"], **clean_card(c)} for c in cards if c["id"] in ids]
        if not targets:
            raise ApiError("作り直すカードを選んでください")
        others = [c["question"] for c in cards if c["id"] not in ids]
        new_cards = ai_regenerate(deck, targets, others, body.get("instructions"))
        done = 0
        for nc in new_cards:
            if int(nc.get("id", -1)) in ids and nc.get("question") and nc.get("answer"):
                s.update_card(nc["id"], dict(clean_card(nc), needs_regen=False))
                done += 1
        return {"updated": done}

    raise ApiError("不明な操作です")


@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def api(path):
    if request.method == "GET":
        return jsonify({"ok": True, "app": "flashcard", "mock": MOCK})
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(handle(body.get("action", ""), body, request.headers.get("X-Flash-Pass", "")))
    except ApiError as e:
        return jsonify({"error": e.message}), e.status
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": f"送られた内容が正しくありません ({e})"}), 400
    except requests.RequestException:
        return jsonify({"error": "データベースにつながりませんでした。もう一度お試しください。"}), 502


if __name__ == "__main__":
    # ローカル確認用: FLASH_MOCK=1 python api/flash.py  → http://localhost:5050
    from flask import send_from_directory
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @app.route("/api/flash", methods=["GET", "POST"])
    def api_local():
        return api("")

    @app.route("/app/<path:f>")
    def static_local(f):
        return send_from_directory(root, f)

    app.run(port=5050, debug=False)
