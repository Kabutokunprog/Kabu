"""隠語辞書の一覧画面（Mac内だけで動くページ。外には何も送らない）。

python3 la.py glossary edit で、ブラウザに表を開く。
言葉ごとに「本当の意味（自分用）」「AIに伝える意味」「重要度」「セクシー度」などを編集して保存できる。
"""
from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import glossary

PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ふたりの言葉辞書</title>
<style>
:root { --bg:#fff7f9; --card:#fff; --ink:#3a2a30; --sub:#8a6f78; --accent:#d6457a; --line:#f0d6df; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.5 -apple-system, "Hiragino Sans", sans-serif; }
header { position:sticky; top:0; background:var(--bg); padding:14px 16px 10px;
         border-bottom:1px solid var(--line); z-index:2; }
h1 { margin:0 0 8px; font-size:20px; }
.bar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.bar label { color:var(--sub); font-size:13px; }
button { border:0; border-radius:999px; padding:8px 16px; font-size:14px; cursor:pointer;
         background:var(--line); color:var(--ink); }
button.main { background:var(--accent); color:#fff; font-weight:600; }
select, input[type=text] { font:inherit; border:1px solid var(--line); border-radius:8px;
         padding:6px 8px; background:#fff; color:var(--ink); width:100%; }
main { padding:12px 16px 80px; }
.note { color:var(--sub); font-size:13px; margin:0 0 12px; }
.row { background:var(--card); border:1px solid var(--line); border-radius:14px;
       padding:12px; margin-bottom:10px; display:grid; gap:8px;
       grid-template-columns: 1.1fr 2fr 2fr .9fr .9fr 1fr; align-items:end; }
.row.todo { border-left:5px solid var(--accent); }
.row.del { opacity:.4; }
.f { display:flex; flex-direction:column; gap:3px; min-width:0; }
.f > span { font-size:11px; color:var(--sub); }
.term { font-weight:700; font-size:17px; word-break:break-all; }
.cnt { font-size:12px; color:var(--sub); }
.checks { display:flex; flex-direction:column; gap:4px; font-size:13px; }
#msg { color:var(--accent); font-weight:600; }
@media (max-width: 760px) {
  .row { grid-template-columns: 1fr 1fr; }
  .row .wide { grid-column: 1 / -1; }
}
</style></head><body>
<header>
  <h1>ふたりの言葉辞書</h1>
  <div class="bar">
    <label>並び順 <select id="sort">
      <option value="count">出てきた回数</option><option value="imp">重要度</option>
      <option value="sexy">セクシー度</option><option value="todo">確認待ちを先に</option></select></label>
    <label><input type="checkbox" id="onlyTodo"> 確認待ちだけ</label>
    <button id="add">＋ 言葉を足す</button>
    <button class="main" id="save">保存する</button>
    <button id="quit">保存して閉じる</button>
    <span id="msg"></span>
  </div>
</header>
<main>
  <p class="note">「本当の意味」はこのMacの中だけに保存され、AIには送りません。AIには「AIに伝える意味」だけを渡します。
  左がピンクの行は、AIが推測しただけでまだ確認していない言葉です。</p>
  <div id="list"></div>
</main>
<script>
const TOKEN = "__TOKEN__";
const CATS = {intimacy:"夜のこと", affection:"愛情", nickname:"呼び名", place:"場所", health:"体調", other:"その他"};
let items = __ITEMS__;
const list = document.getElementById("list");

function opt(map, v) { return Object.entries(map).map(([k, l]) =>
  `<option value="${k}" ${String(k) === String(v) ? "selected" : ""}>${l}</option>`).join(""); }
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
const STARS = {1:"★1",2:"★2",3:"★3",4:"★4",5:"★5"};
const SEXY = {0:"0 なし",1:"1",2:"2",3:"3",4:"4",5:"5 とても"};

function render() {
  const s = document.getElementById("sort").value;
  const only = document.getElementById("onlyTodo").checked;
  const order = items.map((it, i) => i).sort((a, b) => {
    const x = items[a], y = items[b];
    if (s === "imp") return (y.importance ?? 3) - (x.importance ?? 3);
    if (s === "sexy") return (y.sexy ?? 0) - (x.sexy ?? 0);
    if (s === "todo") return (x.confirmed ? 1 : 0) - (y.confirmed ? 1 : 0) || y.count - x.count;
    return y.count - x.count;
  });
  list.innerHTML = order.filter(i => !only || !items[i].confirmed).map(i => {
    const it = items[i];
    return `<div class="row ${it.confirmed ? "" : "todo"} ${it._del ? "del" : ""}" data-i="${i}">
      <div class="f">${it._new
        ? `<span>言葉</span><input type="text" data-k="term" value="${esc(it.term)}">`
        : `<div class="term">${esc(it.term)}</div><div class="cnt">${it.count}回</div>`}</div>
      <div class="f wide"><span>本当の意味（自分用・AIには送らない）</span>
        <input type="text" data-k="private" value="${esc(it.private)}"></div>
      <div class="f wide"><span>AIに伝える意味（やわらかめ）</span>
        <input type="text" data-k="meaning" value="${esc(it.meaning)}"></div>
      <div class="f"><span>重要度</span><select data-k="importance">${opt(STARS, it.importance ?? 3)}</select></div>
      <div class="f"><span>セクシー度</span><select data-k="sexy">${opt(SEXY, it.sexy ?? 0)}</select></div>
      <div class="f"><span>種類</span><select data-k="category">${opt(CATS, it.category || "other")}</select>
        <div class="checks">
          <label><input type="checkbox" data-k="confirmed" ${it.confirmed ? "checked" : ""}> 正しい</label>
          <label><input type="checkbox" data-k="_del" ${it._del ? "checked" : ""}> 消す</label></div></div>
    </div>`;
  }).join("") || "<p class='note'>表示する言葉がありません。</p>";
}

list.addEventListener("input", e => {
  const row = e.target.closest(".row"); const k = e.target.dataset.k;
  if (!row || !k) return;
  const it = items[row.dataset.i];
  it[k] = e.target.type === "checkbox" ? e.target.checked
        : (k === "importance" || k === "sexy") ? Number(e.target.value) : e.target.value;
  if (k === "_del" || k === "confirmed") row.classList.toggle(k === "_del" ? "del" : "todo",
        k === "_del" ? it._del : !it.confirmed);
});
document.getElementById("sort").onchange = render;
document.getElementById("onlyTodo").onchange = render;
document.getElementById("add").onclick = () => {
  items.unshift({term:"", private:"", meaning:"", category:"other", importance:3, sexy:0,
                 confirmed:true, count:0, _new:true});
  document.getElementById("sort").value = "count"; render();
};

async function save(quit) {
  const msg = document.getElementById("msg");
  const out = items.filter(it => !it._del && String(it.term).trim()).map(it => {
    const { count, _new, _del, ...rest } = it; rest.term = String(rest.term).trim(); return rest; });
  const r = await fetch(`/save?t=${TOKEN}${quit ? "&quit=1" : ""}`, {method:"POST",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify(out)});
  msg.textContent = r.ok ? (quit ? "保存しました。この画面は閉じて大丈夫です。" : "保存しました") : "保存できませんでした";
  if (r.ok && !quit) { items = items.filter(it => !it._del); items.forEach(it => delete it._new); render(); }
  setTimeout(() => { if (!quit) msg.textContent = ""; }, 2500);
}
document.getElementById("save").onclick = () => save(false);
document.getElementById("quit").onclick = () => save(true);
render();
</script></body></html>"""


def _counts(con, terms) -> dict[str, int]:
    out = {}
    for t in terms:
        out[t] = con.execute(
            "SELECT COUNT(*) FROM messages WHERE kind='text' AND role!='system' AND text LIKE ?",
            (f"%{t}%",)).fetchone()[0]
    return out


def run(con) -> None:
    items = glossary.load()
    counts = _counts(con, [i["term"] for i in items])
    for i in items:
        i["count"] = counts.get(i["term"], 0)
        i.setdefault("private", "")
        i.setdefault("importance", 3)
        i.setdefault("sexy", 0)
    token = secrets.token_urlsafe(16)
    html = PAGE.replace("__TOKEN__", token).replace(
        "__ITEMS__", json.dumps(items, ensure_ascii=False).replace("</", "<\\/"))
    done = threading.Event()

    class H(BaseHTTPRequestHandler):
        def _ok(self, body: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != f"/?t={token}":
                self.send_error(403)
                return
            self._ok(html.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):
            if not self.path.startswith(f"/save?t={token}"):
                self.send_error(403)
                return
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
            glossary.save([d for d in data if isinstance(d, dict) and d.get("term")])
            self._ok(b"ok", "text/plain")
            if "quit=1" in self.path:
                done.set()

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={token}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"辞書の画面を開きました: {url}", flush=True)
    print("編集が終わったら、画面の「保存して閉じる」を押してください（Ctrl+C でも終了できます）。")
    webbrowser.open(url)
    try:
        done.wait()
    except KeyboardInterrupt:
        pass
    srv.shutdown()
    print("辞書を閉じました。過去の要約にも反映したいときは `summarize --force` を実行してください。")
