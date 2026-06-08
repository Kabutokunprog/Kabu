# TAKE NEWS NAVI 素材・材料メーカー強化 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TAKE NEWS NAVI v3 に日本の素材・材料メーカー8社の専用クエリと専門メディアRSSフィードを追加し、Geminiの関連度スコアリングでノイズを除去する

**Architecture:** 既存の単一 GAS ファイルを修正する。追加は3箇所：①CONFIG の INTEREST_QUERIES に企業名クエリ8件追加、②専門メディア収集関数 collectSpecialty_() の新規追加 + buildEmailHtml_ に第4部追加、③Gemini の出力スキーマを `{comment, score}` に変更してスコア≤2をフィルタ。

**Tech Stack:** Google Apps Script (JavaScript), Google News RSS, Gemini API (gemini-2.5-flash)

---

## ファイル構成

- **新規作成:** `TakeNewsNavi_v3.gs` — チャットで受け取った既存コードをベースに3つの変更を加えた完全版。このファイルを Google Apps Script エディタにそのまま貼り付けて使う。

---

### Task 1: ローカルにベースファイルを作成する

**Files:**
- Create: `TakeNewsNavi_v3.gs`

- [ ] **Step 1: チャットのコードをそのままファイルに保存する**

チャットに貼られていた TAKE NEWS NAVI v3 のコードを `/Users/juntakeda/Documents/JT/02_Personal/★01プログラム/TakeNewsNavi_v3.gs` として保存する。

- [ ] **Step 2: ファイルが作成されたことを確認する**

```bash
wc -l TakeNewsNavi_v3.gs
```

期待値: 行数が表示される（300行前後）

- [ ] **Step 3: コミット**

```bash
git add TakeNewsNavi_v3.gs
git commit -m "feat: add base GAS file for TAKE NEWS NAVI v3"
```

---

### Task 2: INTEREST_QUERIES に企業名クエリ8件を追加する

**Files:**
- Modify: `TakeNewsNavi_v3.gs` — CONFIG.INTEREST_QUERIES

- [ ] **Step 1: INTEREST_QUERIES の末尾に8エントリを追加する**

既存の `{ q: '6G 光通信 photonics', pri: 'low' }` の直後に以下を追加：

```javascript
    { q: 'DNP 大日本印刷 フィルム 材料',  pri: 'high' },
    { q: 'レゾナック 半導体材料',          pri: 'high' },
    { q: 'JSR 半導体 フォトレジスト',      pri: 'high' },
    { q: '住友化学 素材 機能材料',          pri: 'high' },
    { q: 'AGC ガラス フッ素 材料',          pri: 'high' },
    { q: '信越化学 シリコン 半導体',        pri: 'high' },
    { q: '日東電工 光学フィルム テープ',    pri: 'high' },
    { q: 'リンテック 粘着 半導体',          pri: 'high' },
```

- [ ] **Step 2: コミット**

```bash
git add TakeNewsNavi_v3.gs
git commit -m "feat: add 8 Japanese materials maker queries to INTEREST_QUERIES"
```

---

### Task 3: CONFIG に SPECIALTY_FEEDS を追加する

**Files:**
- Modify: `TakeNewsNavi_v3.gs` — CONFIG オブジェクト

- [ ] **Step 1: CONFIG に SPECIALTY_FEEDS と MAX_SPECIALTY を追加する**

`MAX_INTEREST: 15,` の直後に以下を追加：

```javascript
  MAX_SPECIALTY: 15,    // 専門メディアの最大件数

  // 第4部：素材・材料 専門メディア（RSS直接購読）
  SPECIALTY_FEEDS: [
    { name: 'MONOist',        url: 'https://monoist.itmedia.co.jp/rss/monoist_all.xml' },
    { name: 'EE Times Japan', url: 'https://eetimes.itmedia.co.jp/rss/eetimelj.xml' },
    { name: '日刊工業新聞',    url: 'https://www.nikkan.co.jp/rss/news.rss' }
  ],
```

- [ ] **Step 2: コミット**

```bash
git add TakeNewsNavi_v3.gs
git commit -m "feat: add SPECIALTY_FEEDS config for specialist media RSS"
```

---

### Task 4: collectSpecialty_() 関数を追加する

**Files:**
- Modify: `TakeNewsNavi_v3.gs` — collectInterest_() 関数の直後に新関数を追加

- [ ] **Step 1: collectSpecialty_() を追加する**

`collectInterest_()` 関数の閉じ括弧 `}` の直後に以下を追加：

```javascript
/** 第4部：素材・材料 専門メディア */
function collectSpecialty_() {
  var all = [];
  var seen = {};
  var cutoff = Date.now() - CONFIG.LOOKBACK_HOURS * 3600 * 1000;
  CONFIG.SPECIALTY_FEEDS.forEach(function (feed) {
    var items = fetchFeed_(feed.url, cutoff);
    var count = 0;
    items.forEach(function (it) {
      if (count >= 5) return; // 1媒体最大5件
      var key = normalizeTitle_(it.title);
      if (!key || seen[key]) return;
      seen[key] = true;
      it.source = feed.name;
      all.push(it);
      count++;
    });
  });
  return all.slice(0, CONFIG.MAX_SPECIALTY);
}
```

- [ ] **Step 2: コミット**

```bash
git add TakeNewsNavi_v3.gs
git commit -m "feat: add collectSpecialty_() for specialist media RSS feeds"
```

---

### Task 5: Gemini の出力スキーマを {comment, score} に変更する

**Files:**
- Modify: `TakeNewsNavi_v3.gs` — addCommentsByGemini_() 関数

- [ ] **Step 1: addCommentsByGemini_() のプロンプトと解析ロジックを書き換える**

`addCommentsByGemini_` 関数全体を以下に置き換える：

```javascript
/** 全記事に短評と関連度スコアを付与（1回のAPI呼び出し・失敗時は要約で代替） */
function addCommentsByGemini_(items) {
  if (items.length === 0) return;

  var list = items.map(function (n, i) {
    return i + '\t' + n.title + ' ／ ' + n.snippet;
  }).join('\n');

  var prompt =
    '次のニュース見出し（番号\\tタイトル ／ 要約）それぞれに、日本語で40〜70字の短評と関連度スコアを付けてください。\n' +
    '読者は富士フイルム勤務の技術系マネージャー。要点や「なぜ重要か」を簡潔に。\n' +
    '関連度スコアの基準:\n' +
    '5 = 追いたい日本メーカー(DNP/レゾナック/JSR/住友化学/AGC/信越化学/日東電工/リンテック/富士フイルム)の具体的動向\n' +
    '4 = 日本の素材・材料産業に直結\n' +
    '3 = 関連技術・市場の動向\n' +
    '2 = 周辺情報\n' +
    '1 = ほぼ無関係\n' +
    '出力は厳密にJSON配列のみ。i番目の要素が記事iの情報。前置き・コードフェンス禁止。\n' +
    '例: [{"comment":"短評0","score":4},{"comment":"短評1","score":2}]\n\n' + list;

  try {
    var raw = stripFences_(callGeminiWithRetry_(prompt));
    var arr = JSON.parse(raw);
    if (Object.prototype.toString.call(arr) === '[object Array]') {
      for (var i = 0; i < items.length; i++) {
        var entry = arr[i];
        if (entry && typeof entry === 'object') {
          items[i].comment = (typeof entry.comment === 'string' && entry.comment) ? entry.comment : items[i].snippet;
          items[i].score = (typeof entry.score === 'number') ? entry.score : 3;
        } else if (typeof entry === 'string' && entry) {
          // フォールバック：旧形式（文字列配列）にも対応
          items[i].comment = entry;
          items[i].score = 3;
        } else {
          items[i].comment = items[i].snippet;
          items[i].score = 3;
        }
      }
      return;
    }
    throw new Error('JSON配列でない');
  } catch (e) {
    Logger.log('短評生成に失敗。RSS要約で代替: ' + e);
    items.forEach(function (n) { n.comment = n.snippet; n.score = 3; });
  }
}
```

- [ ] **Step 2: コミット**

```bash
git add TakeNewsNavi_v3.gs
git commit -m "feat: update Gemini output schema to include relevance score (1-5)"
```

---

### Task 6: buildEmailHtml_() に第4部を追加し、スコアフィルタを適用する

**Files:**
- Modify: `TakeNewsNavi_v3.gs` — buildEmailHtml_() 関数のシグネチャとロジック

- [ ] **Step 1: buildEmailHtml_() の引数と第3部・第4部のロジックを書き換える**

関数シグネチャを `function buildEmailHtml_(top, market, interest, specialty)` に変更し、第3部にスコアフィルタを追加、第4部を末尾に追加する。

`buildEmailHtml_` 関数全体を以下に置き換える：

```javascript
function buildEmailHtml_(top, market, interest, specialty) {
  var html = '<div style="font-family:sans-serif;line-height:1.7;color:#222;max-width:700px">';

  // 第1部 トップニュース
  html += sectionTitle_('🌅 本日のトップニュース');
  top.forEach(function (g) {
    html += '<h3 style="margin:16px 0 6px;font-size:15px;color:#444">' + g.region + '</h3>';
    g.items.forEach(function (it) { html += itemHtml_(it); });
  });

  // 第2部 マーケット
  html += sectionTitle_('💹 マーケット（NASDAQ・S&P500・半導体）');
  if (market.length === 0) html += '<p style="color:#888">該当ニュースなし</p>';
  market.forEach(function (it) { html += itemHtml_(it); });

  // 第3部 関心ジャンル（スコア≤2をフィルタ）
  html += sectionTitle_('🎯 あなたの関心ジャンル');
  var filteredInterest = interest.filter(function (it) { return (it.score || 3) >= 3; });
  if (filteredInterest.length === 0) html += '<p style="color:#888">該当ニュースなし</p>';
  var labels = { high: '【高優先度】', medium: '【中優先度】', low: '【低優先度】' };
  var lastPri = '';
  filteredInterest.forEach(function (it) {
    if (it.priority !== lastPri) {
      html += '<h3 style="margin:16px 0 6px;font-size:15px;color:#444">' + (labels[it.priority] || '') + '</h3>';
      lastPri = it.priority;
    }
    html += itemHtml_(it);
  });

  // 第4部 素材・材料 専門メディア（スコア≤2をフィルタ）
  html += sectionTitle_('🔬 素材・材料 専門メディア');
  var filteredSpecialty = (specialty || []).filter(function (it) { return (it.score || 3) >= 3; });
  if (filteredSpecialty.length === 0) html += '<p style="color:#888">該当ニュースなし</p>';
  filteredSpecialty.forEach(function (it) { html += itemHtml_(it); });

  html += '<hr style="margin-top:24px;border:none;border-top:1px solid #ddd">' +
          '<p style="font-size:11px;color:#999">— TAKE NEWS NAVI（Google News × Gemini 自動生成）</p></div>';
  return html;
}
```

- [ ] **Step 2: コミット**

```bash
git add TakeNewsNavi_v3.gs
git commit -m "feat: add section 4 for specialist media and apply score filtering to sections 3-4"
```

---

### Task 7: sendDailyNewsDigest() を更新して第4部を組み込む

**Files:**
- Modify: `TakeNewsNavi_v3.gs` — sendDailyNewsDigest() 関数

- [ ] **Step 1: sendDailyNewsDigest() の収集・集計・ログ・HTML生成部分を更新する**

`sendDailyNewsDigest` 関数全体を以下に置き換える：

```javascript
function sendDailyNewsDigest() {
  // ---- 収集 ----
  var top = collectTopNews_();
  var market = collectMarket_();
  var interest = collectInterest_();
  var specialty = collectSpecialty_();

  var totalCount = market.length + interest.length + specialty.length;
  top.forEach(function (g) { totalCount += g.items.length; });
  if (totalCount === 0) { Logger.log('記事0件。中止。'); return; }
  Logger.log('収集: トップ' + top.reduce(function(s,g){return s+g.items.length;},0) +
             ' / マーケット' + market.length + ' / 関心' + interest.length +
             ' / 専門メディア' + specialty.length);

  // ---- Geminiで短評＋スコアを一括生成 ----
  var allItems = [];
  top.forEach(function (g) { g.items.forEach(function (it) { allItems.push(it); }); });
  market.forEach(function (it) { allItems.push(it); });
  interest.forEach(function (it) { allItems.push(it); });
  specialty.forEach(function (it) { allItems.push(it); });
  addCommentsByGemini_(allItems);

  // ---- メール本体を組み立て ----
  var html = buildEmailHtml_(top, market, interest, specialty);

  // ---- 送信 ----
  var today = new Date();
  var dateStr = Utilities.formatDate(today, 'Asia/Tokyo', 'yyyy年M月d日');
  var dow = ['日','月','火','水','木','金','土'][Number(Utilities.formatDate(today, 'Asia/Tokyo', 'u')) % 7];
  var subject = 'TAKE NEWS NAVI｜' + dateStr + '（' + dow + '）';

  GmailApp.sendEmail(
    CONFIG.RECIPIENTS.join(','),
    subject,
    stripHtml_(html),
    { htmlBody: html, name: 'TAKE NEWS NAVI' }
  );
  Logger.log('配信完了: ' + subject);
}
```

- [ ] **Step 2: コミット**

```bash
git add TakeNewsNavi_v3.gs
git commit -m "feat: integrate specialty collection into main digest function"
```

---

### Task 8: 動作確認と GAS への反映

**Files:**
- Read: `TakeNewsNavi_v3.gs`（完成版）

- [ ] **Step 1: ファイルの最終状態を確認する**

```bash
grep -n "collectSpecialty_\|SPECIALTY_FEEDS\|score\|第4部" TakeNewsNavi_v3.gs
```

期待値: 各キーワードが適切な行に存在する

- [ ] **Step 2: 変更点をユーザーに説明し、GAS エディタへの反映を依頼する**

以下の手順を案内する：
1. https://script.google.com を開く
2. 既存プロジェクトを開く
3. 全コードを選択して削除
4. `TakeNewsNavi_v3.gs` の内容を貼り付ける
5. API キーと受信アドレスを設定する（`CONFIG.GEMINI_API_KEY` と `CONFIG.RECIPIENTS`）

- [ ] **Step 3: テスト実行の手順を案内する**

GAS エディタで以下の順にテストする：

1. **専門メディア取得テスト:** `collectSpecialty_` を選択して「実行」→ ログに件数が表示されること
2. **全体テスト:** `sendDailyNewsDigest` を選択して「実行」→ メールが届いて第4部があること
3. **スコアフィルタ確認:** 届いたメールの第3部・第4部でノイズが減っていること

- [ ] **Step 4: 最終コミット**

```bash
git add TakeNewsNavi_v3.gs
git commit -m "feat: complete TAKE NEWS NAVI v3 materials enhancement - adds 8 company queries, specialist media RSS (4th section), and Gemini relevance scoring"
```
