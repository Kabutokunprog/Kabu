"""お姉さんとのおしゃべり画面（Mac内だけで動くページ）。

python3 la.py app で、指紋認証（Touch ID）のあとにブラウザで開く。
・左に話題（スレッド）の一覧、右に吹き出しのやりとり。履歴はいつでも読み返せる
・しばらく操作しないと自動で鍵がかかる（もう一度開くには指紋認証が必要）
"""
from __future__ import annotations

import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ask
import config
import db
import llm
import memory

IDLE_LOCK_SEC = 30 * 60

PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ふたりの記録帳</title>
<style>
:root { --bg:#fff5f8; --side:#fde8ef; --card:#fff; --ink:#3a2a30; --sub:#8a6f78;
        --accent:#d6457a; --mine:#d6457a; --line:#f2d3de; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#1d1418; --side:#271a20; --card:#30212a; --ink:#f6e9ee; --sub:#c6a5b2;
          --accent:#ff6fa3; --mine:#b8396a; --line:#3d2a33; }
}
* { box-sizing:border-box; }
html, body { height:100%; margin:0; }
body { background:var(--bg); color:var(--ink); font:15px/1.6 -apple-system, "Hiragino Sans", sans-serif;
       display:flex; overflow:hidden; }
aside { width:270px; flex:none; background:var(--side); border-right:1px solid var(--line);
        display:flex; flex-direction:column; }
aside .top { padding:14px; display:flex; flex-direction:column; gap:10px; }
aside h1 { font-size:17px; margin:0; }
.lv { font-size:13px; color:var(--sub); }
.lv b { color:var(--accent); }
button { font:inherit; border:0; border-radius:999px; padding:8px 14px; cursor:pointer;
         background:var(--accent); color:#fff; font-weight:600; }
button.ghost { background:transparent; color:var(--sub); font-weight:400; padding:4px 8px; }
#threads { overflow-y:auto; flex:1; padding:0 8px 12px; }
.th { padding:10px 12px; border-radius:12px; cursor:pointer; margin-bottom:4px; }
.th:hover { background:var(--line); }
.th.on { background:var(--card); box-shadow:0 1px 0 var(--line); }
.th .t { font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.th .d { font-size:12px; color:var(--sub); }
main { flex:1; display:flex; flex-direction:column; min-width:0; }
.head { display:flex; align-items:center; gap:8px; padding:10px 16px; border-bottom:1px solid var(--line); }
.head .title { font-weight:700; flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
#menu { display:none; }
#log { flex:1; overflow-y:auto; padding:18px 16px; display:flex; flex-direction:column; gap:12px; }
.b { max-width:min(680px, 86%); padding:10px 14px; border-radius:18px; white-space:pre-wrap; word-break:break-word; }
.b.user { align-self:flex-end; background:var(--mine); color:#fff; border-bottom-right-radius:6px; }
.b.assistant { align-self:flex-start; background:var(--card); border:1px solid var(--line); border-bottom-left-radius:6px; }
.who { font-size:12px; color:var(--sub); margin:0 4px -8px; }
.who.user { align-self:flex-end; }
.sys { align-self:center; font-size:13px; color:var(--accent); }
.empty { margin:auto; color:var(--sub); text-align:center; }
form { display:flex; gap:8px; padding:10px 16px 16px; border-top:1px solid var(--line); }
textarea { flex:1; font:inherit; color:var(--ink); background:var(--card); border:1px solid var(--line);
           border-radius:16px; padding:10px 14px; resize:none; height:48px; max-height:160px; }
@media (max-width: 760px) {
  aside { position:fixed; inset:0 auto 0 0; z-index:5; transform:translateX(-100%); transition:transform .2s;
          width:82%; max-width:300px; }
  aside.open { transform:none; box-shadow:0 0 40px rgba(0,0,0,.25); }
  #menu { display:inline-block; }
}
</style></head><body>
<aside id="side">
  <div class="top">
    <h1>ふたりの記録帳</h1>
    <div class="lv" id="lv"></div>
    <button id="new">＋ 新しい話題</button>
  </div>
  <div id="threads"></div>
</aside>
<main>
  <div class="head">
    <button class="ghost" id="menu">☰</button>
    <div class="title" id="title"></div>
    <button class="ghost" id="rename">名前を変える</button>
    <button class="ghost" id="del">削除</button>
  </div>
  <div id="log"></div>
  <form id="f">
    <textarea id="q" placeholder="お姉さんに話しかける（Enterで改行、⌘+Enterで送信）"></textarea>
    <button id="send">送信</button>
  </form>
</main>
<script>
const T = "__TOKEN__";
let cur = null, busy = false, threads = [];
const $ = id => document.getElementById(id);

async function api(path, body) {
  let r;
  try { r = await fetch(`/api/${path}${path.includes("?") ? "&" : "?"}t=${T}`,
    body === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  } catch (e) { throw new Error("locked"); }  // 裏の仕組みが止まっている（鍵がかかった）
  if (r.status === 403 || !r.ok && r.status !== 500) throw new Error("locked");
  return r.json();
}
function locked() {
  document.body.innerHTML = "<div class='empty' style='padding:40px'>鍵がかかりました（30分操作がなかったか、画面を閉じたため）。<br>「ふたりの記録帳」アイコンからもう一度開いてください。</div>";
}
function fmt(ts) { return ts ? ts.slice(5, 16).replace("T", " ").replace("-", "/") : ""; }
function esc(s) { return String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

async function loadThreads() {
  const d = await api("threads");
  threads = d.threads;
  $("lv").innerHTML = `仲良しレベル <b>${d.level}</b>・これまで${d.turns}回<br>${esc(d.stage)}`;
  $("threads").innerHTML = threads.map(t => `<div class="th ${t.id === cur ? "on" : ""}" data-id="${t.id}">
      <div class="t">${esc(t.title)}</div><div class="d">${fmt(t.updated)}・${t.n}回</div></div>`).join("")
    || "<div class='lv' style='padding:12px'>まだ話題はありません</div>";
}
async function open(id) {
  cur = id;
  const d = await api(`messages?id=${id}`);
  $("title").textContent = d.title;
  $("log").innerHTML = d.messages.length ? "" :
    "<div class='empty'>ふふ、何でも聞いて♡<br>例:「4月はどこにデートに行ったっけ？」</div>";
  d.messages.forEach(m => bubble(m.role, m.content));
  $("side").classList.remove("open");
  await loadThreads();
  $("q").focus();
}
function bubble(role, text) {
  if ($("log").querySelector(".empty")) $("log").innerHTML = "";
  const who = document.createElement("div");
  who.className = "who " + role; who.textContent = role === "user" ? "キミ" : "お姉さん";
  const b = document.createElement("div");
  b.className = "b " + role; b.textContent = text;
  $("log").append(who, b); $("log").scrollTop = $("log").scrollHeight;
  return b;
}
function note(text) {
  const n = document.createElement("div"); n.className = "sys"; n.textContent = text;
  $("log").append(n); $("log").scrollTop = $("log").scrollHeight;
}

$("f").onsubmit = async e => {
  e.preventDefault();
  const q = $("q").value.trim();
  if (!q || busy) return;
  if (!cur) cur = (await api("new", {})).id;
  busy = true; $("send").disabled = true; $("q").value = "";
  bubble("user", q);
  const wait = bubble("assistant", "考え中…");
  try {
    const d = await api("send", {id: cur, text: q});
    wait.textContent = d.answer;
    if (d.missing) note(`※ まだ要約が無い月があります（${d.missing}か月）`);
    if (d.level_up) note(`♡ 仲良しレベルが ${d.level_up} に上がりました`);
    await loadThreads();
    const th = threads.find(x => x.id === cur); if (th) $("title").textContent = th.title;
  } catch (err) {
    if (err.message === "locked") return locked();
    wait.textContent = "ごめんね、うまく答えられなかったみたい。もう一度送ってみて。";
  }
  busy = false; $("send").disabled = false; $("q").focus();
};
$("q").addEventListener("keydown", e => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); $("f").requestSubmit(); }
});
$("threads").onclick = e => { const t = e.target.closest(".th"); if (t) open(Number(t.dataset.id)); };
$("new").onclick = async () => open((await api("new", {})).id);
$("rename").onclick = async () => {
  if (!cur) return;
  const name = prompt("話題の名前", $("title").textContent);
  if (name) { await api("rename", {id: cur, title: name}); open(cur); }
};
$("del").onclick = async () => {
  if (!cur || !confirm("この話題の履歴を消しますか？（お姉さんの記憶メモとレベルは残ります）")) return;
  await api("delete", {id: cur}); cur = null; $("log").innerHTML = ""; $("title").textContent = "";
  await loadThreads(); if (threads[0]) open(threads[0].id);
};
$("menu").onclick = () => $("side").classList.toggle("open");
loadThreads().then(() => threads[0] ? open(threads[0].id) : open(null).catch(() => {})).catch(locked);
</script></body></html>"""


def run() -> None:
    token = secrets.token_urlsafe(24)
    last = [time.time()]
    stop = threading.Event()
    with db.connect() as con:
        memory.threads(con)  # 履歴の置き場所を用意（古い履歴の移し替えも）

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False)
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _ok_token(self) -> dict | None:
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if q.get("t") != token or stop.is_set():
                self._send(403, {"error": "locked"})
                return None
            last[0] = time.time()
            q["_path"] = u.path
            return q

        def do_GET(self):
            q = self._ok_token()
            if q is None:
                return
            con = db.connect()
            if q["_path"] == "/":
                self._send(200, PAGE.replace("__TOKEN__", token), "text/html; charset=utf-8")
            elif q["_path"] == "/api/threads":
                m = memory.load()
                self._send(200, {"threads": memory.threads(con), "level": memory.level(m),
                                 "turns": m["turns"], "stage": memory.stage(m)})
            elif q["_path"] == "/api/messages":
                tid = int(q.get("id") or 0) or memory.latest_thread(con)
                row = con.execute("SELECT title FROM threads WHERE id=?", (tid,)).fetchone()
                self._send(200, {"id": tid, "title": row["title"] if row else "",
                                 "messages": memory.messages(con, tid)})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            q = self._ok_token()
            if q is None:
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            con = db.connect()
            path = q["_path"]
            if path == "/api/new":
                self._send(200, {"id": memory.new_thread(con)})
            elif path == "/api/rename":
                memory.rename_thread(con, int(body["id"]), body.get("title", ""))
                self._send(200, {"ok": True})
            elif path == "/api/delete":
                memory.delete_thread(con, int(body["id"]))
                self._send(200, {"ok": True})
            elif path == "/api/send":
                tid, text = int(body["id"]), str(body.get("text", "")).strip()
                s = config.load_settings()
                try:
                    out, info = ask.answer(con, text, s, history=memory.recent(con, tid),
                                           chat_context=memory.context_text(con, tid))
                except SystemExit as e:  # AIにつながらない等
                    self._send(500, {"answer": f"（{e}）"})
                    return
                m = memory.record(con, text, out, tid)
                self._send(200, {"answer": out, "level_up": m.get("level_up"),
                                 "missing": len(info.get("missing") or [])})
                memory.after_reply(con, tid, m, s, ask.system_prompt(s))  # 返事を返してから片付ける
            else:
                self._send(404, {"error": "not found"})

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={token}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    s = config.load_settings()
    who = f"Mac内のAI {s['ollama_model']}" if llm.is_local(s) else llm.model_name(s, s["model_answer"])
    print(f"おしゃべり画面を開きました（使うAI: {who}）", flush=True)
    print(f"{IDLE_LOCK_SEC // 60}分操作しないと自動で鍵がかかります。終わるときは Ctrl+C か、このウィンドウを閉じてください。", flush=True)
    webbrowser.open(url)
    try:
        while not stop.is_set():
            time.sleep(5)
            if time.time() - last[0] > IDLE_LOCK_SEC:
                stop.set()
                print("しばらく操作がなかったので鍵をかけました。", flush=True)
    except KeyboardInterrupt:
        pass
    stop.set()
    srv.shutdown()
