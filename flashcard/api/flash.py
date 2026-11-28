"""フラッシュ暗記カード: サーバー側 (Vercel Python Function)

ブラウザからは POST /api/flash に {"action": "...", ...} を送る。
合言葉は X-Flash-Pass ヘッダーで受け取り、Supabase へそのまま渡す
(Supabase 側の RLS が「親 / 子」を判定する)。
"""
import base64
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, Response, jsonify, request, stream_with_context

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
MOCK = os.environ.get("FLASH_MOCK") == "1"
APP_VERSION = "1.28"  # 画面(index.html)の APP_VERSION と同じにする
COMMIT = (os.environ.get("VERCEL_GIT_COMMIT_SHA") or "")[:7]  # ローカル確認用 (DB も AI も使わない)

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


def clean_year(v):
    """西暦の目安 (時系列の並べ替え用)。なし/0 は None。"""
    try:
        y = int(v)
    except (TypeError, ValueError):
        return None
    return y if y and -10000 < y < 3000 else None


def clean_card(c):
    out = {}
    for k in CARD_FIELDS:
        v = c.get(k)
        out[k] = str(v).strip() if v is not None else ""
    out["year"] = clean_year(c.get("year"))
    out["importance"] = clean_importance(c.get("importance"))
    return out


def clean_importance(v):
    """テストに出やすさ 1〜5 (なし/範囲外は None)。"""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 5 else None


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

    def get_deck_row(self, deck_id):
        rows = self._req("GET", "flash_decks", {"id": f"eq.{int(deck_id)}", "select": "id,title,subject,grade,term,card_kind,source_text"})
        return rows[0] if rows else {}

    def get_deck(self, deck_id):
        rows = self._req("GET", "flash_decks", {"id": f"eq.{int(deck_id)}", "select": "*"})
        if not rows:
            raise ApiError("教材が見つかりません", 404)
        cards = self._req("GET", "flash_cards", {
            "deck_id": f"eq.{int(deck_id)}", "order": "position.asc,id.asc",
            "select": "id,deck_id,position,question,answer,note,example,tag,year,importance,needs_regen,created_at,updated_at,explain,explain_choices,flash_progress(*)"})
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

    def get_progress_many(self, ids):
        if not ids:
            return []
        return self._req("GET", "flash_progress", {"card_id": f"in.({','.join(str(int(i)) for i in ids)})", "select": "*"})

    def save_progress_many(self, rows):
        if rows:
            self._req("POST", "flash_progress", body=rows, prefer="resolution=merge-duplicates,return=minimal")

    def add_session(self, row):
        self._req("POST", "flash_sessions", body=row, prefer="return=minimal")

    def add_answers(self, rows):
        if rows:
            self._req("POST", "flash_answers", body=rows, prefer="return=minimal")

    def growth(self, profile_id):
        return self.rpc("flash_growth", {"pid": int(profile_id)})

    def set_session_mode(self, session_id, mode):
        rows = self._req("PATCH", "flash_sessions", {"id": f"eq.{int(session_id)}"}, {"answer_mode": mode}, prefer="return=representation")
        if not rows:
            raise ApiError("記録が見つかりません", 404)
        x = rows[0]
        if x.get("deck_id"):  # さかのぼって作ったグラフ用の記録も合わせる
            self._req("PATCH", "flash_answers", {"profile_id": f"eq.{x['profile_id']}", "deck_id": f"eq.{x['deck_id']}",
                                                 "study_mode": "eq.backfill", "answered_at": f"eq.{x['finished_at']}"},
                      {"ans_mode": mode}, prefer="return=minimal")

    def list_sessions(self, profile_id, limit=300):
        return self._req("GET", "flash_sessions", {"profile_id": f"eq.{int(profile_id)}", "select": "*",
                                                   "order": "finished_at.desc", "limit": str(limit)})

    # テスト
    def add_test(self, row):
        return self._req("POST", "flash_tests", body=row, prefer="return=representation")[0]

    def list_tests(self, profile_id):
        tests = self._req("GET", "flash_tests", {"profile_id": f"eq.{int(profile_id)}",
                                                 "select": "id,title,subject,deck_ids,memo,created_at", "order": "created_at.desc"})
        atts = self._req("GET", "flash_test_attempts", {"profile_id": f"eq.{int(profile_id)}",
                                                        "select": "id,test_id,score,total,finished_at", "order": "finished_at.desc"})
        return tests, atts

    def get_test(self, test_id):
        rows = self._req("GET", "flash_tests", {"id": f"eq.{int(test_id)}", "select": "*"})
        if not rows:
            raise ApiError("テストが見つかりません", 404)
        atts = self._req("GET", "flash_test_attempts", {"test_id": f"eq.{int(test_id)}", "select": "*", "order": "finished_at.desc"})
        return rows[0], atts

    def add_attempt(self, row):
        return self._req("POST", "flash_test_attempts", body=row, prefer="return=representation")[0]

    # 裏で進める作成ジョブ
    def job_insert(self, row):
        return self._req("POST", "flash_jobs", body=row, prefer="return=representation")[0]

    def job_get(self, job_id):
        rows = self._req("GET", "flash_jobs", {"id": f"eq.{int(job_id)}", "select": "*"})
        if not rows:
            raise ApiError("作成中の教材が見つかりません", 404)
        return rows[0]

    def job_update(self, job_id, data):
        self._req("PATCH", "flash_jobs", {"id": f"eq.{int(job_id)}"}, dict(data, updated_at=iso(now_utc())), prefer="return=minimal")

    def job_claim(self, job_id, token):
        stale = (now_utc() - timedelta(seconds=90)).replace(microsecond=0).isoformat()
        rows = self._req("PATCH", "flash_jobs", {"id": f"eq.{int(job_id)}", "status": "in.(queued,reading,generating)",
                                                 "or": f'(runner.is.null,heartbeat_at.lt."{stale}")'},
                         {"runner": token, "heartbeat_at": iso(now_utc())}, prefer="return=representation")
        return bool(rows)

    def job_list(self):
        since = iso(now_utc() - timedelta(days=2))
        return self._req("GET", "flash_jobs", {"created_at": f"gte.{since}", "dismissed": "is.false",
                                               "select": "id,profile_id,kind,label,status,params,page_count,read_done,deck_id,card_count,error,heartbeat_at,gen_started_at,created_at,updated_at",
                                               "order": "created_at.desc"})

    def pages_put(self, rows):
        if rows:
            self._req("POST", "flash_job_pages", body=rows, prefer="resolution=merge-duplicates,return=minimal")

    def pages_get(self, job_id, start, end):
        return self._req("GET", "flash_job_pages", {"job_id": f"eq.{int(job_id)}", "and": f"(idx.gte.{int(start)},idx.lt.{int(end)})",
                                                    "select": "idx,data", "order": "idx.asc"})

    def pages_delete(self, job_id):
        self._req("DELETE", "flash_job_pages", {"job_id": f"eq.{int(job_id)}"})

    def delete_test(self, test_id):
        self._req("DELETE", "flash_tests", {"id": f"eq.{int(test_id)}"})

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

    def get_deck_row(self, deck_id):
        self._need()
        return dict(next((d for d in self.data["decks"] if d["id"] == int(deck_id)), {}))

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

    def add_test(self, row):
        self._need()
        r = dict(row, id=self._id(), created_at=iso(now_utc()))
        self.data.setdefault("tests", []).append(r)
        return r

    def list_tests(self, profile_id):
        self._need()
        tests = sorted([dict(t) for t in self.data.get("tests", []) if t["profile_id"] == int(profile_id)],
                       key=lambda t: t["created_at"], reverse=True)
        atts = sorted([dict(a) for a in self.data.get("attempts", []) if a["profile_id"] == int(profile_id)],
                      key=lambda a: a["finished_at"], reverse=True)
        return tests, atts

    def get_test(self, test_id):
        self._need()
        t = next((dict(t) for t in self.data.get("tests", []) if t["id"] == int(test_id)), None)
        if not t:
            raise ApiError("テストが見つかりません", 404)
        atts = sorted([dict(a) for a in self.data.get("attempts", []) if a["test_id"] == int(test_id)],
                      key=lambda a: a["finished_at"], reverse=True)
        return t, atts

    def add_attempt(self, row):
        self._need()
        r = dict(row, id=self._id())
        self.data.setdefault("attempts", []).append(r)
        return r

    def job_insert(self, row):
        self._need()
        r = dict(dict(page_count=0, read_done=0, source_text="", deck_id=None, card_count=0, error="", runner=None,
                      heartbeat_at=None, gen_started_at=None, dismissed=False), **row, id=self._id(), created_at=iso(now_utc()))
        self.data.setdefault("jobs", []).append(r)
        return dict(r)

    def job_get(self, job_id):
        self._need()
        j = next((j for j in self.data.get("jobs", []) if j["id"] == int(job_id)), None)
        if not j:
            raise ApiError("作成中の教材が見つかりません", 404)
        return dict(j)

    def job_update(self, job_id, data):
        self._need()
        for j in self.data.get("jobs", []):
            if j["id"] == int(job_id):
                j.update(data)

    def job_claim(self, job_id, token):
        j = next((j for j in self.data.get("jobs", []) if j["id"] == int(job_id)), None)
        if not j or j["status"] not in ("queued", "reading", "generating"):
            return False
        hb = j.get("heartbeat_at")
        if j.get("runner") and hb and datetime.fromisoformat(hb) > now_utc() - timedelta(seconds=90):
            return False
        j.update(runner=token, heartbeat_at=iso(now_utc()))
        return True

    def job_list(self):
        self._need()
        return [{k: v for k, v in j.items() if k != "source_text"} for j in sorted(self.data.get("jobs", []), key=lambda j: j["created_at"], reverse=True)
                if not j.get("dismissed")]

    def pages_put(self, rows):
        self._need()
        pg = self.data.setdefault("pages", {})
        for r in rows:
            pg[(int(r["job_id"]), int(r["idx"]))] = r["data"]

    def pages_get(self, job_id, start, end):
        pg = self.data.get("pages", {})
        return [{"idx": i, "data": pg[(int(job_id), i)]} for i in range(int(start), int(end)) if (int(job_id), i) in pg]

    def pages_delete(self, job_id):
        pg = self.data.get("pages", {})
        for k in [k for k in pg if k[0] == int(job_id)]:
            pg.pop(k)

    def delete_test(self, test_id):
        self._need()
        self.data["tests"] = [t for t in self.data.get("tests", []) if t["id"] != int(test_id)]
        self.data["attempts"] = [a for a in self.data.get("attempts", []) if a["test_id"] != int(test_id)]

    def get_progress_many(self, ids):
        self._need()
        return [dict(self.data["progress"][int(i)]) for i in ids if int(i) in self.data["progress"]]

    def save_progress_many(self, rows):
        self._need()
        for r in rows:
            self.data["progress"][int(r["card_id"])] = r

    def add_session(self, row):
        self._need()
        self.data.setdefault("sessions", []).append(dict(row, id=self._id()))

    def add_answers(self, rows):
        self._need()
        self.data.setdefault("answers", []).extend(rows)

    def set_session_mode(self, session_id, mode):
        self._need()
        for x in self.data.get("sessions", []):
            if x["id"] == int(session_id):
                x["answer_mode"] = mode
                for a in self.data.get("answers", []):
                    if a.get("study_mode") == "backfill" and a.get("deck_id") == x.get("deck_id") and a.get("answered_at") == x.get("finished_at"):
                        a["ans_mode"] = mode

    def growth(self, profile_id):
        self._need()
        rows = [r for r in self.data.get("answers", []) if r["profile_id"] == int(profile_id)]
        daily, att = {}, {}
        for r in rows:
            d = (datetime.fromisoformat(r["answered_at"]) + timedelta(hours=9)).date().isoformat()
            k = (r["subject"], r["ans_mode"], d)
            daily.setdefault(k, [0, 0]); daily[k][0] += 1; daily[k][1] += 1 if r["correct"] else 0
            k2 = (r["subject"], r["ans_mode"], min(r["attempt_no"], 5))
            att.setdefault(k2, [0, 0]); att[k2][0] += 1; att[k2][1] += 1 if r["correct"] else 0
        return {"daily": [{"subject": a, "ans_mode": b, "d": c, "n": v[0], "ok": v[1]} for (a, b, c), v in sorted(daily.items(), key=lambda x: x[0][2])],
                "attempts": [{"subject": a, "ans_mode": b, "a": c, "n": v[0], "ok": v[1]} for (a, b, c), v in att.items()],
                "since": min((r["answered_at"] for r in rows), default=None)}

    def list_sessions(self, profile_id, limit=300):
        self._need()
        rows = [r for r in self.data.get("sessions", []) if r["profile_id"] == int(profile_id)]
        return sorted(rows, key=lambda r: r["finished_at"], reverse=True)[:limit]

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
        "- year: 歴史のカードは、その出来事・人物が活躍した西暦の目安を整数で(例: 1603。文化や時代全体なら中ごろの年。紀元前はマイナス)。後で時系列に並べ替えるのに使う。歴史以外は 0。",
        "- importance: その学年・科目の一般的な中間・期末テストでよく出題されるか(頻出度)を1〜5で。教材の中で目立つかではなく、全国の学校の定期テストや対策問題集で実際によく問われるかで判断する(5=定番中の定番 / 3=ふつう / 1=めったに出ない細かい知識)。全部を高くしない。",
        "- 内容は教材にあることを中心に。教材の誤字や手書きの書き込みは正しい内容に直してよい。",
        "- 同じ問いを重複させない。",
        "",
        "## 並べ方",
        "- 必ず教材の順番どおりに並べる(教科書・プリントの順に覚えたいので、並べ替えない)。",
        "- プリントに番号(③④・No.11 など)やページ番号があるときは、その番号の順。写真の順番が番号とずれていても番号を優先する。同じプリントの中は問題番号・上から下(縦書きは右から左)の順。",
        "- 時系列での出題は year を使ってアプリ側で並べ替えるので、ここでは時代順にしない。",
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
    "properties": {**{k: {"type": "string"} for k in CARD_FIELDS}, "year": {"type": "integer"}, "importance": {"type": "integer"}},
    "required": [*CARD_FIELDS, "year", "importance"],
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
        "properties": {"id": {"type": "integer"}, **{k: {"type": "string"} for k in CARD_FIELDS}, "year": {"type": "integer"}, "importance": {"type": "integer"}},
        "required": ["id", *CARD_FIELDS, "year", "importance"],
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


def mock_wait():
    if MOCK and os.environ.get("FLASH_MOCK_DELAY"):
        time.sleep(float(os.environ["FLASH_MOCK_DELAY"]))


def ai_transcribe(images, page_offset, model=None):
    mock_wait()
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
    mock_wait()
    if MOCK:
        cards = [
            {"question": "江戸幕府を開いた人物は誰か。", "answer": "徳川家康", "note": "とくがわいえやす", "example": "", "tag": "1603年", "year": 1603, "importance": 5},
            {"question": "8代将軍徳川吉宗が行った改革を何というか。", "answer": "享保の改革", "note": "きょうほう", "example": "", "tag": "1716年", "year": 1716},
            {"question": "老中松平定信による改革を何というか。", "answer": "寛政の改革", "note": "かんせい", "example": "", "tag": "1787年", "year": 1787},
        ]
        return {"title": "お試し教材", "card_kind": "qa", "cards": cards}
    text = claude_call(build_generate_prompt(opts), "medium", schema=GENERATE_SCHEMA, max_tokens=64000,
                       model=pick_model(opts.get("model")))
    data = json.loads(text)
    data["cards"] = [clean_card(c) for c in data.get("cards", []) if c.get("question") and c.get("answer")]
    if not data["cards"]:
        raise ApiError("問題を作れませんでした。教材の写真が読み取りにくいかもしれません。", 422)
    return data


REORDER_SCHEMA = {
    "type": "object",
    "properties": {"cards": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "integer"}, "year": {"type": "integer"}},
        "required": ["id", "year"], "additionalProperties": False}}},
    "required": ["cards"], "additionalProperties": False,
}


def ai_reorder(deck, cards, model=None):
    """カードを教材(プリント)の順番に並べ直し、歴史なら西暦の目安を付ける。"""
    if MOCK:
        return [{"id": c["id"], "year": 1600 + i} for i, c in enumerate(reversed(cards))]
    prompt = "\n".join([
        "下のフラッシュカードを、教材(教科書・プリント)に出てくる順番に並べ直してください。",
        "- プリントに番号(③④・No.11 など)やページがあれば、その番号の順。同じプリントの中は問題番号・上から下の順。",
        "- 教材の内容(書き起こし)を見て順番を決める。教材に見当たらないカードは、近い内容のカードの後ろに置く。",
        "- 各カードに year を付ける: 歴史なら出来事・人物の西暦の目安(整数。紀元前はマイナス)。歴史でなければ 0。",
        "- すべてのカードの id を1回ずつ返す。",
        f"科目: {deck.get('subject') or '不明'}",
        "", "## カード", json.dumps([{"id": c["id"], "question": c["question"], "answer": c["answer"], "tag": c.get("tag", "")}
                                     for c in cards], ensure_ascii=False),
        "", "## 教材の内容", "<material>", deck.get("source_text") or "(記録なし)", "</material>",
    ])
    data = json.loads(claude_call(prompt, "low", schema=REORDER_SCHEMA, max_tokens=16000, model=model))
    return data.get("cards", [])


IMPORTANCE_SCHEMA = {
    "type": "object",
    "properties": {"cards": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "integer"}, "importance": {"type": "integer"}},
        "required": ["id", "importance"], "additionalProperties": False}}},
    "required": ["cards"], "additionalProperties": False,
}


def ai_importance(deck, cards, model=None):
    """各カードに「定期テストに出やすさ」1〜5を付ける。"""
    if MOCK:
        return [{"id": c["id"], "importance": 5 - (i % 5)} for i, c in enumerate(cards)]
    prompt = "\n".join([
        "あなたは日本の中学・高校で定期テスト(中間・期末)を長年作ってきたベテラン教師です。",
        "下のフラッシュカードそれぞれについて、「この学年・科目の一般的な中間・期末テストで、どれくらいよく出題されるか(頻出度)」を1〜5で付けてください。",
        "- 教材(プリント)の中で目立つかどうかではなく、全国の学校の一般的な中間・期末テストや定期テスト対策の問題集で、実際によく問われるかどうかで判断する(入試での頻出は参考程度)。",
        "- 5: 定番中の定番(ほぼどのテストにも出る) / 4: よく出る / 3: ふつう / 2: たまに出る / 1: めったに出ない細かい知識",
        "- 例: 歴史なら教科書の太字レベルの人物・改革・条約は高め、細かい作品名や人物の別名は低め。古文単語なら入試頻出の古今異義語や重要多義語は高め。",
        "- 全部を5にしない。メリハリをつける。すべてのカードの id を1回ずつ返す。",
        f"教材: {deck.get('title')} / 科目: {deck.get('subject') or '不明'} / 学年: {deck.get('grade') or '不明'} / テスト: {deck.get('term') or '中間・期末'}",
        "", "## カード", json.dumps([{"id": c["id"], "question": c["question"], "answer": c["answer"]} for c in cards], ensure_ascii=False),
        "", "## 教材の内容", "<material>", (deck.get("source_text") or "(記録なし)")[:30000], "</material>",
    ])
    data = json.loads(claude_call(prompt, "low", schema=IMPORTANCE_SCHEMA, max_tokens=16000, model=model))
    return data.get("cards", [])


TEST_TYPES = {"choice": "4択", "short": "一問一答(書いて答える)", "tf": "○×", "written": "記述(説明する)"}
TEST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "questions": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": list(TEST_TYPES)},
                "question": {"type": "string"},
                "choices": {"type": "array", "items": {"type": "string"}},
                "answer": {"type": "string"},
                "explanation": {"type": "string"},
                "card_id": {"type": "integer"},
            },
            "required": ["type", "question", "choices", "answer", "explanation", "card_id"],
            "additionalProperties": False}},
    },
    "required": ["title", "questions"],
    "additionalProperties": False,
}
GRADE_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object", "properties": {"index": {"type": "integer"}, "ok": {"type": "boolean"}, "comment": {"type": "string"}},
        "required": ["index", "ok", "comment"], "additionalProperties": False}}},
    "required": ["results"], "additionalProperties": False,
}


def ai_make_test(decks, opts):
    types = [t for t in (opts.get("types") or []) if t in TEST_TYPES] or ["choice", "short"]
    count = max(5, min(60, int(opts.get("count") or 20)))
    cards = [c for _, cs in decks for c in cs]
    if MOCK:
        qs = []
        for i, c in enumerate(cards[:count]):
            t = types[i % len(types)]
            if t == "choice":
                qs.append({"type": t, "question": c["question"], "choices": [c["answer"], "ちがう1", "ちがう2", "ちがう3"],
                           "answer": c["answer"], "explanation": c.get("note", ""), "card_id": c["id"]})
            elif t == "tf":
                qs.append({"type": t, "question": f"「{c['question']}」の答えは「{c['answer']}」である。", "choices": ["○", "×"],
                           "answer": "○", "explanation": "", "card_id": c["id"]})
            else:
                qs.append({"type": t, "question": c["question"], "choices": [], "answer": c["answer"], "explanation": "", "card_id": c["id"]})
        return {"title": "お試しテスト", "questions": qs}
    parts = []
    for d, cs in decks:
        parts.append(f"### 教材「{d.get('title')}」(科目: {d.get('subject') or '不明'})")
        parts.append(json.dumps([{"card_id": c["id"], "q": c["question"], "a": c["answer"], "note": c.get("note", "")} for c in cs][:200],
                                ensure_ascii=False))
        if d.get("source_text"):
            parts.append("教材の内容(抜粋):\n" + d["source_text"][:6000])
    prompt = "\n".join([
        "あなたは日本の中学・高校のベテラン教師です。下のフラッシュカードと教材の内容から、定期テストの本番に近い試験問題を作ってください。",
        f"- 問題数: {count}問。形式は次の中から、バランスよく混ぜる: " + "、".join(TEST_TYPES[t] for t in types),
        "- フラッシュカードの丸写しではなく、聞き方を変えたり、2つの知識を組み合わせたりして、本当に理解しているかを確かめる問題にする。ただし教材の範囲を出ない。",
        "- choice(4択): choices に4つ。正解は1つだけ。answer は正解の選択肢の文字列そのもの。まぎらわしいが明らかに間違いの選択肢を入れる。正解の位置はばらばらに。",
        "- tf(○×): choices は [\"○\", \"×\"]。answer は \"○\" か \"×\"。×の問題も入れる。",
        "- short(一問一答): choices は空。answer は短い正解(用語・人名・年など)。別の書き方も正解なら「／」で区切って並べる(例: 外国船打払令／異国船打払令)。",
        "- written(記述): choices は空。answer は模範解答(1〜3文)。question には「〜を説明しなさい」など何を書けばよいか分かるように。",
        "- explanation: なぜその答えになるかの短い解説。",
        "- card_id: その問題の元になったカードの card_id(複数なら一番関係の深いもの)。なければ 0。",
        "- 出題の順番は教材の順番を基本にする。",
        "- title: テストの名前(例:「江戸時代 確認テスト」)。",
        ("## 追加の注文\n" + opts["instructions"].strip()) if (opts.get("instructions") or "").strip() else "",
        "", "## 範囲(フラッシュカードと教材)", *parts,
    ])
    data = json.loads(claude_call(prompt, "medium", schema=TEST_SCHEMA, max_tokens=48000, model=pick_model(opts.get("model"))))
    valid = {c["id"] for c in cards}
    qs = []
    for q in data.get("questions", []):
        if not q.get("question") or not q.get("answer"):
            continue
        q["card_id"] = q.get("card_id") if q.get("card_id") in valid else 0
        if q["type"] == "tf":
            q["choices"] = ["○", "×"]
        if q["type"] == "choice" and q["answer"] not in q.get("choices", []):
            q["choices"] = (q.get("choices") or [])[:3] + [q["answer"]]
        if q["type"] in ("short", "written"):
            q["choices"] = []
        qs.append(q)
    if not qs:
        raise ApiError("テストを作れませんでした。もう一度お試しください。", 422)
    return {"title": data.get("title") or "確認テスト", "questions": qs}


def norm_ans(x):
    import unicodedata
    x = unicodedata.normalize("NFKC", str(x or "")).lower()
    return re.sub(r"[\s、。，．,.・「」『』()（）]", "", x)


def grade_test(questions, answers):
    """4択・○×・答えが一致した一問一答はその場で採点。残りはAIがまとめて採点する。"""
    results, ask = [], []
    for i, q in enumerate(questions):
        given = str(answers[i] if i < len(answers) and answers[i] is not None else "").strip()
        r = {"ok": False, "comment": "", "given": given}
        if not given:
            r["comment"] = "未回答"
        elif q["type"] in ("choice", "tf"):
            r["ok"] = norm_ans(given) == norm_ans(q["answer"])
        else:
            alts = [norm_ans(a) for a in re.split(r"[／/]", q["answer"]) if a.strip()]
            if norm_ans(given) in alts:
                r["ok"] = True
            else:
                ask.append(i)
        results.append(r)
    if ask:
        if MOCK:
            for i in ask:
                results[i]["comment"] = "(お試しモード: AI採点の代わり)"
        else:
            items = [{"index": i, "type": TEST_TYPES[questions[i]["type"]], "question": questions[i]["question"],
                      "model_answer": questions[i]["answer"], "student_answer": results[i]["given"]} for i in ask]
            prompt = "\n".join([
                "あなたは中学・高校の先生です。生徒の答えを採点してください。",
                "- 一問一答: 意味が同じで正しい用語・人名なら正解(ひらがな書き・別名・表記ゆれは正解でよい。ただし明らかに違う語は不正解)。漢字の誤りがあれば正解でもコメントで指摘。",
                "- 記述: 模範解答の大事なポイントが入っていれば正解。足りないポイントがあれば不正解にして、何が足りないかをコメントで。",
                "- comment は生徒向けに短く、やさしく(1〜2文)。",
                "", json.dumps(items, ensure_ascii=False)])
            data = json.loads(claude_call(prompt, "low", schema=GRADE_SCHEMA, max_tokens=8000, model=pick_model("sonnet")))
            for g in data.get("results", []):
                i = g.get("index")
                if i in ask:
                    results[i]["ok"] = bool(g.get("ok"))
                    results[i]["comment"] = str(g.get("comment") or "")
    return results


def ai_regenerate(deck, targets, others, instructions):
    if MOCK:
        return [dict(id=c["id"], question=c["question"] + "(作り直し)", answer=c["answer"], note=c.get("note", ""),
                     example=c.get("example", ""), tag=c.get("tag", "")) for c in targets]
    prompt = "\n".join([
        "あなたは日本の中学生・高校生の定期テスト対策を手伝うベテラン教師です。",
        f"教材「{deck.get('title')}」(学年: {deck.get('grade') or '不明'} / 科目: {deck.get('subject') or '不明'}) のフラッシュカードのうち、",
        "「作り直してほしい」と印がついたカードを、より良い問題に作り直してください。",
        "",
        "- 同じ id のまま、question / answer / note / example / tag / year / importance をすべて書き直して返す(year は歴史なら西暦の目安、それ以外は 0。importance はテストに出る可能性1〜5)。",
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



# ---------------------------------------------------------------- 裏で進める作成ジョブ
# スマホは写真を預けるだけ。読み取り→問題づくり→保存はサーバーが自分で進める。
# 1回の呼び出しの持ち時間(最大300秒)を超えそうなら、自分自身をもう一度呼んで続きをやる。
JOB_STEP_BUDGET = float(os.environ.get("FLASH_JOB_BUDGET", "170"))  # 秒。これを過ぎたら次の呼び出しに引き継ぐ


def self_url():
    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    return f"{proto}://{request.host}/api/flash"


def kick_job(job_id, passcode):
    """自分自身を呼んで続きを始めてもらう (返事は待たない)。"""
    try:
        requests.post(self_url(), json={"action": "job_continue", "job_id": int(job_id)},
                      headers={"X-Flash-Pass": passcode, "Content-Type": "application/json"}, timeout=4)
    except requests.RequestException:
        pass


def run_job(s, job_id, passcode):
    token = uuid.uuid4().hex
    if not s.job_claim(job_id, token):
        return "busy"
    start = time.time()
    try:
        while True:
            j = s.job_get(job_id)
            if j["status"] in ("done", "error"):
                return j["status"]
            if time.time() - start > JOB_STEP_BUDGET:
                s.job_update(job_id, {"runner": None})
                kick_job(job_id, passcode)
                return "continued"
            p = j.get("params") or {}
            if j["status"] in ("queued", "reading") and j["read_done"] < j["page_count"]:
                # 5ページ(または約3MB)ずつ読み取る
                rows = s.pages_get(job_id, j["read_done"], j["read_done"] + 5)
                batch, size = [], 0
                for r in rows:
                    if batch and size + len(r["data"]) > 3_200_000:
                        break
                    batch.append(r["data"])
                    size += len(r["data"])
                if not batch:
                    raise ApiError("預かった写真が見つかりません。もう一度作り直してください。")
                text = ai_transcribe(batch, j["read_done"], pick_model(p.get("model")))
                src = (j.get("source_text") or "") + ("\n\n" if j.get("source_text") else "") + text
                s.job_update(job_id, {"status": "reading", "source_text": src, "read_done": j["read_done"] + len(batch),
                                      "heartbeat_at": iso(now_utc())})
            elif j["status"] in ("queued", "reading"):
                s.pages_delete(job_id)
                s.job_update(job_id, {"status": "generating", "gen_started_at": iso(now_utc()), "heartbeat_at": iso(now_utc())})
            elif j["status"] == "generating":
                opts = dict(p, source_text=j["source_text"])
                data = ai_generate(opts)
                label = MODEL_LABEL.get(pick_model(p.get("model")), "")
                deck = {k: str(p.get(k) or "") for k in ("grade", "term", "subject")}
                deck.update(title=str(p.get("title") or "").strip() or data.get("title") or "無題の教材",
                            card_kind="word" if data.get("card_kind") == "word" else "qa",
                            profile_id=int(j["profile_id"]), source_text=j["source_text"],
                            memo=f"AI: {label}" if label else "")
                d = s.create_deck(deck, data["cards"])
                s.job_update(job_id, {"status": "done", "deck_id": d["id"], "card_count": len(data["cards"]),
                                      "label": deck["title"], "runner": None, "heartbeat_at": iso(now_utc())})
                return "done"
            else:
                return j["status"]
    except ApiError as e:
        s.job_update(job_id, {"status": "error", "error": e.message, "runner": None})
        return "error"
    except Exception as e:  # 予期しないエラーも記録して止める
        s.job_update(job_id, {"status": "error", "error": f"うまく作れませんでした ({type(e).__name__})", "runner": None})
        return "error"

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


def log_answers(s, body, answers, old, mode):
    """1問ずつの記録 (科目ごとの成長グラフ用): 何回目に解いたか・4択か自分で答えたか"""
    ans_mode = "choice" if body.get("answer_mode") == "choice" else "flip"
    deck_of = {int(c["id"]): c.get("deck_id") for c in s.get_cards(list(answers))}
    subj = {}
    for did in set(v for v in deck_of.values() if v):
        subj[did] = (s.get_deck_row(did) or {}).get("subject") or "その他"
    now_s = iso(now_utc())
    s.add_answers([{
        "profile_id": int(body["profile_id"]), "card_id": cid, "deck_id": deck_of.get(cid),
        "subject": subj.get(deck_of.get(cid), "その他"), "correct": ok, "ans_mode": ans_mode,
        "study_mode": "review" if mode == "review" else "normal",
        "attempt_no": int((old.get(cid) or {}).get("correct_count") or 0) + int((old.get(cid) or {}).get("wrong_count") or 0) + 1,
        "answered_at": now_s,
    } for cid, ok in answers.items() if cid in deck_of])


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
        if "avatar" in body:
            av = str(body.get("avatar") or "")
            if av and (not re.match(r"^data:image/(jpeg|png|webp);base64,", av) or len(av) > 80_000):
                raise ApiError("アイコンの画像が大きすぎるか、形式が違います")
            data["avatar"] = av
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

    if action == "finish_session":
        # 1回分の学習をまとめて記録 (戻って答えを直せるよう、最後にまとめて送る)
        answers = {}
        for a in body.get("answers") or []:
            answers[int(a["card_id"])] = bool(a.get("correct"))
        mode = body.get("mode", "normal")
        if answers:
            old = {int(p["card_id"]): p for p in s.get_progress_many(list(answers))}
            rows = []
            for cid, ok in answers.items():
                row = apply_answer(old.get(cid), ok, mode)
                row["card_id"] = cid
                for k in ("correct_count", "wrong_count", "last_result", "last_answered_at", "in_review", "review_streak", "next_due_at"):
                    row.setdefault(k, None)
                rows.append({k: row[k] for k in ("card_id", "correct_count", "wrong_count", "last_result", "last_answered_at",
                                                   "in_review", "review_streak", "next_due_at")})
            s.save_progress_many(rows)
            # 1問ずつの記録 (科目ごとの成長グラフ用): 何回目に解いたか・4択か自分で答えたか
            try:
                log_answers(s, body, answers, old, mode)
            except Exception:  # グラフ用の記録に失敗しても、学習の記録は必ず残す
                pass
            wrong = [w for w in (body.get("wrong_items") or [])][:100]
            s.add_session({
                "profile_id": int(body["profile_id"]),
                "deck_id": int(body["deck_id"]) if body.get("deck_id") else None,
                "deck_title": str(body.get("deck_title") or "")[:200],
                "subject": str(body.get("subject") or "")[:50],
                "mode": "review" if mode == "review" else "normal",
                "answer_mode": "choice" if body.get("answer_mode") == "choice" else "flip",
                "total": len(answers),
                "correct": sum(1 for v in answers.values() if v),
                "wrong_items": [{"q": str(w.get("q", ""))[:300], "a": str(w.get("a", ""))[:300]} for w in wrong],
                "started_at": body.get("started_at"),
                "finished_at": iso(now_utc()),
            })
        return {"saved": len(answers)}

    if action == "history":
        return {"sessions": s.list_sessions(body["profile_id"])}

    if action == "set_session_mode":
        mode = body.get("answer_mode")
        if mode not in ("choice", "flip", "mixed"):
            raise ApiError("答え方の指定が正しくありません")
        s.set_session_mode(body["session_id"], mode)
        return {"ok": True}

    if action == "mock_seed_answers" and MOCK:  # お試しモードでのグラフ確認用
        s.add_answers(body.get("rows") or [])
        return {"ok": True}

    if action == "growth":
        g = s.growth(body["profile_id"]) or {}
        decks, prog = s.list_decks(body["profile_id"])
        mastery = {}
        for d in deck_stats(decks, prog):
            m = mastery.setdefault(d.get("subject") or "その他", {"cards": 0, "mastered": 0})
            m["cards"] += d["card_count"]
            m["mastered"] += d["stats"]["mastered"]
        return {"daily": g.get("daily") or [], "attempts": g.get("attempts") or [], "since": g.get("since"), "mastery": mastery}

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
        if body.get("save"):
            # 作ったらサーバーでそのまま保存する (途中でスマホを閉じても教材が残るように)
            deck = {k: str(body.get(k) or "") for k in ("grade", "term", "subject", "source_text")}
            deck["title"] = str(body.get("title") or "").strip() or data.get("title") or "無題の教材"
            deck["card_kind"] = "word" if data.get("card_kind") == "word" else "qa"
            deck["profile_id"] = int(body["profile_id"])
            deck["memo"] = f"AI: {data['model_label']}" if data["model_label"] else ""
            d = s.create_deck(deck, data["cards"])
            data["deck_id"] = d["id"]
            data["title"] = deck["title"]
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
        if "year" in body:
            data["year"] = clean_year(body["year"])
        if "importance" in body:
            data["importance"] = clean_importance(body["importance"])
        if "needs_regen" in body:
            data["needs_regen"] = bool(body["needs_regen"])
        if "question" in data or "answer" in data:
            old = (s.get_cards([body["card_id"]]) or [{}])[0]
            if data.get("question", old.get("question")) != old.get("question") or data.get("answer", old.get("answer")) != old.get("answer"):
                data.update(explain="", explain_detail="", explain_choices={})
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

    if action == "job_create":
        keys = ("style", "grade", "term", "subject", "count", "include_written", "include_related", "instructions", "model", "title")
        params = {k: body.get(k) for k in keys}
        text = str(body.get("source_text") or "")
        j = s.job_insert({
            "profile_id": int(body["profile_id"]), "kind": "make",
            "label": str(body.get("label") or body.get("title") or "新しい教材")[:100],
            "status": "queued" if text and not body.get("page_count") else "uploading",
            "params": params, "page_count": int(body.get("page_count") or 0), "source_text": text,
        })
        return {"job_id": j["id"]}

    if action == "job_pages":
        rows = [{"job_id": int(body["job_id"]), "idx": int(body.get("start", 0)) + i, "data": d}
                for i, d in enumerate(body.get("pages") or [])]
        s.pages_put(rows)
        return {"ok": True}

    if action in ("job_start", "job_continue"):
        jid = int(body["job_id"])
        if action == "job_start":
            j = s.job_get(jid)
            if j["status"] == "uploading":
                s.job_update(jid, {"status": "queued"})
        return {"result": run_job(s, jid, passcode)}

    if action == "job_list":
        return {"jobs": s.job_list(), "now": iso(now_utc())}

    if action == "job_dismiss":
        s.job_update(int(body["job_id"]), {"dismissed": True})
        return {"ok": True}

    if action == "create_test":
        decks = []
        for did in body.get("deck_ids") or []:
            d, cs = s.get_deck(did)
            if cs:
                decks.append((d, cs))
        if not decks:
            raise ApiError("範囲にする教材を選んでください")
        t = ai_make_test(decks, body)
        subjects = [d.get("subject") for d, _ in decks if d.get("subject")]
        row = s.add_test({
            "profile_id": int(body["profile_id"]),
            "title": str(body.get("title") or "").strip() or t["title"],
            "subject": subjects[0] if subjects and len(set(subjects)) == 1 else ("・".join(sorted(set(subjects))) if subjects else ""),
            "deck_ids": [int(d["id"]) for d, _ in decks],
            "questions": t["questions"],
            "memo": f"AI: {MODEL_LABEL.get(pick_model(body.get('model')), '')}",
        })
        return {"test_id": row["id"], "title": row["title"], "count": len(t["questions"])}

    if action == "list_tests":
        tests, atts = s.list_tests(body["profile_id"])
        for t in tests:
            mine = [a for a in atts if a["test_id"] == t["id"]]
            t["attempts"] = len(mine)
            t["last"] = mine[0] if mine else None
            t["best"] = max(mine, key=lambda a: (a["score"] / a["total"]) if a["total"] else 0) if mine else None
        return {"tests": tests}

    if action == "get_test":
        t, atts = s.get_test(body["test_id"])
        return {"test": t, "attempts": atts}

    if action == "delete_test":
        s.delete_test(body["test_id"])
        return {"ok": True}

    if action == "submit_test":
        t, _ = s.get_test(body["test_id"])
        qs = t["questions"]
        only = body.get("only")  # 間違えた問題だけ解き直すときの問題番号
        idx = [int(i) for i in only] if only else list(range(len(qs)))
        idx = [i for i in idx if 0 <= i < len(qs)]
        answers = body.get("answers") or []
        sub_q = [qs[i] for i in idx]
        res = grade_test(sub_q, [answers[k] if k < len(answers) else "" for k in range(len(idx))])
        results = [dict(r, index=i) for i, r in zip(idx, res)]
        # 元になったカードの成績に反映 (まちがいは復習へ)
        card_ok = {}
        for i, r in zip(idx, res):
            cid = int(qs[i].get("card_id") or 0)
            if cid:
                card_ok[cid] = card_ok.get(cid, True) and r["ok"]
        if card_ok:
            exist = {c["id"] for c in s.get_cards(list(card_ok))}
            old = {int(p["card_id"]): p for p in s.get_progress_many([c for c in card_ok if c in exist])}
            rows = []
            for cid, ok in card_ok.items():
                if cid not in exist:
                    continue
                row = apply_answer(old.get(cid), ok, "normal")
                row["card_id"] = cid
                rows.append({k: row.get(k) for k in ("card_id", "correct_count", "wrong_count", "last_result", "last_answered_at",
                                                      "in_review", "review_streak", "next_due_at")})
            s.save_progress_many(rows)
        att = s.add_attempt({
            "test_id": int(t["id"]), "profile_id": int(t["profile_id"]),
            "answers": [r["given"] for r in res], "results": results,
            "score": sum(1 for r in res if r["ok"]), "total": len(res),
            "started_at": body.get("started_at"), "finished_at": iso(now_utc()),
        })
        return {"attempt": att}

    if action == "rate_importance":
        deck, cards = s.get_deck(body["deck_id"])
        if not cards:
            return {"updated": 0}
        ids = {c["id"] for c in cards}
        done = 0
        for r in ai_importance(deck, cards, pick_model(body.get("model") or "sonnet")):
            cid, imp = int(r.get("id", -1)), clean_importance(r.get("importance"))
            if cid in ids and imp:
                s.update_card(cid, {"importance": imp})
                done += 1
        return {"updated": done}

    if action == "reorder":
        deck, cards = s.get_deck(body["deck_id"])
        if not cards:
            return {"updated": 0}
        res = ai_reorder(deck, cards, pick_model(body.get("model") or "sonnet"))
        ids = {c["id"] for c in cards}
        seen, order = set(), []
        for r in res:
            cid = int(r.get("id", -1))
            if cid in ids and cid not in seen:
                seen.add(cid)
                order.append((cid, clean_year(r.get("year"))))
        order += [(c["id"], c.get("year")) for c in cards if c["id"] not in seen]  # 返ってこなかった分は最後に
        for pos, (cid, year) in enumerate(order):
            s.update_card(cid, {"position": pos, "year": year})
        return {"updated": len(order)}

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



# ---------------------------------------------------------------- 解説 (できた文字から順に返す)
EXPLAIN_MODEL = "claude-sonnet-5-5"   # 速さ優先
DETAIL_MODEL = "claude-opus-5-5"      # もっと詳しく
CHOICE_MARK = "【選んだ答え"


def claude_stream(prompt, model, effort, max_tokens):
    """Claude の返事を、できた文字から順に返す。"""
    import anthropic
    client = anthropic_client()
    kwargs = dict(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}],
                  output_config={"effort": effort}, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    try:
        with client.beta.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text
            msg = stream.get_final_message()
            if msg.stop_reason == "refusal":
                raise ApiError("AIが解説を断りました。", 422)
    except anthropic.AuthenticationError:
        raise ApiError("AIの鍵(ANTHROPIC_API_KEY)が正しくないようです。", 500)
    except anthropic.RateLimitError:
        raise ApiError("AIが混み合っています。少し待ってからもう一度お試しください。", 429)
    except anthropic.APIStatusError as e:
        raise ApiError(f"AIでエラーが起きました ({e.status_code})。", 502)
    except anthropic.APIConnectionError:
        raise ApiError("AIにつながりませんでした。", 502)


def material_snippet(source, card, size=1500):
    """教材の書き起こしから、このカードに関係しそうな所だけを抜き出す(速く・安くするため)。"""
    source = source or ""
    if len(source) <= size * 2:
        return source
    for key in (card.get("answer", ""), card.get("question", "")):
        k = re.sub(r"[①-⑳\s。、()（）「」]", "", key)[:6]
        if len(k) >= 2:
            i = source.find(k)
            if i >= 0:
                return source[max(0, i - size): i + size]
    return source[: size * 2]


def card_context(card, deck):
    return "\n".join([
        f"科目: {deck.get('subject') or '不明'} / 学年: {deck.get('grade') or '中高生'} / 教材: {deck.get('title') or ''}",
        f"問題(表): {card.get('question')}",
        f"答え(裏): {card.get('answer')}",
        f"カードのメモ: {card.get('note') or 'なし'}" + (f" / 例文: {card.get('example')}" if card.get("example") else ""),
        "", "## 元の教材の関係しそうな部分", "<material>", material_snippet(deck.get("source_text"), card) or "(記録なし)", "</material>",
    ])


def explain_prompt(card, deck, picked, need_general):
    lines = ["あなたは中高生に教えるのがとても上手な先生です。下のフラッシュカードの解説を書いてください。",
             "- できるだけ元の教材の内容に沿って。中高生に分かりやすい言葉で、短めに(全体で300字くらいまで)。",
             "- 見出しは下の【】の形をそのまま使い、マークダウン記号(#や**)は使わない。箇条書きは「・」。", ""]
    if need_general:
        lines += ["【なぜこれが正解か】1〜2文で。",
                  "【覚え方】語呂合わせ・イメージ・似た言葉との区別のうち、効きそうなものを1〜2個。無理な語呂合わせは作らない。",
                  "【まちがえやすいポイント】よくある勘違いや、似ていてまぎらわしいものを1〜2個。"]
    if picked:
        lines += [f"{CHOICE_MARK}「{picked}」がちがう理由】生徒が4択でまちがえて選んだ「{picked}」が、なぜこの問題の答えではないのか(それは何のことか)を1〜2文で。"]
    if not need_general:
        lines += ["(この見出しだけを書く)"]
    return "\n".join(lines + ["", card_context(card, deck)])


def detail_prompt(card, deck):
    return "\n".join([
        "あなたは中高生に教えるのがとても上手な先生です。下のフラッシュカードについて、もっと詳しく、丁寧に説明してください。",
        "- 背景(なぜそうなったのか・どんな流れの中の話か)、理由、関連する知識、具体例まで入れて、理解が深まるように。",
        "- できるだけ元の教材の内容に沿い、中高生に分かりやすい言葉で。教材にない話をするときは、教科書レベルの確かな内容だけにする。",
        "- 見出しは【背景】【くわしい理由】【関連する知識】【具体例】などの【】の形。マークダウン記号(#や**)は使わない。全体で800字くらいまで。",
        "", card_context(card, deck)])


def explain_stream(s, body, detail):
    cid = int(body["card_id"])
    cards = s.get_cards([cid])
    if not cards:
        yield "（このカードが見つかりませんでした）"
        return
    c = cards[0]
    regen = bool(body.get("regenerate"))
    correct = str(c.get("answer") or "").strip()
    picked = str(body.get("picked") or "").strip()
    if picked in (correct, str(c.get("question") or "").strip()):
        picked = ""
    choices = c.get("explain_choices") or {}
    if detail:
        if c.get("explain_detail") and not regen:
            yield c["explain_detail"]
            return
    else:
        need_general = regen or not c.get("explain")
        need_choice = bool(picked) and (regen or picked not in choices)
        if not need_general and not need_choice:
            yield c["explain"] + (("\n\n" + choices[picked]) if picked else "")
            return
        if not need_general:
            yield c["explain"] + "\n\n"
    deck = s.get_deck_row(c["deck_id"])
    buf = ""
    try:
        if MOCK:
            fake = ("【背景】(お試しモード)江戸時代のはじめ…\n【くわしい理由】…\n【関連する知識】…\n【具体例】…" if detail else
                    ("【なぜこれが正解か】(お試しモード)教材にそう書いてあるからです。\n【覚え方】・語呂合わせ「いろはにほへと」\n【まちがえやすいポイント】・似た言葉に注意。" if need_general else "")
                    + (f"\n{CHOICE_MARK}「{picked}」がちがう理由】それは別のことです。" if picked else ""))
            for i in range(0, len(fake), 6):
                time.sleep(float(os.environ.get("FLASH_MOCK_STREAM", "0.03")))
                buf += fake[i:i + 6]
                yield fake[i:i + 6]
        elif detail:
            for t in claude_stream(detail_prompt(c, deck), DETAIL_MODEL, "medium", 4000):
                buf += t
                yield t
        else:
            for t in claude_stream(explain_prompt(c, deck, picked, need_general), EXPLAIN_MODEL, "low", 1500):
                buf += t
                yield t
    except ApiError as e:
        yield f"\n\n（{e.message}）"
        return
    buf = buf.strip()
    if not buf:
        return
    # 保存して、2回目からはAIを使わずに出す
    if detail:
        s.update_card(cid, {"explain_detail": buf})
    else:
        i = buf.find(CHOICE_MARK)
        general, part4 = (buf[:i].strip(), buf[i:].strip()) if i >= 0 else (buf, "")
        data = {}
        if need_general:
            data["explain"] = general or c.get("explain") or ""
        else:
            part4 = buf
        if picked and part4:
            data["explain_choices"] = dict(choices, **{picked: part4})
        if data:
            s.update_card(cid, data)

@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def api(path):
    if request.method == "GET":
        return jsonify({"ok": True, "app": "flashcard", "mock": MOCK, "version": APP_VERSION, "commit": COMMIT})
    body = request.get_json(silent=True) or {}
    if body.get("action") in ("explain", "explain_detail"):
        # 解説は、できた文字から順に送る
        try:
            st = store_for(request.headers.get("X-Flash-Pass", ""))
            require_login(st)
        except ApiError as e:
            return jsonify({"error": e.message}), e.status
        gen = explain_stream(st, body, body["action"] == "explain_detail")
        return Response(stream_with_context(gen), mimetype="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
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
