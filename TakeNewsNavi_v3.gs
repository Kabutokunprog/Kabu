/*************************************************************
 * TAKE NEWS NAVI v3  ―  素材・材料メーカー強化版
 *
 * 【構成】
 *   第1部 本日のトップニュース（日本・米国・世界）
 *   第2部 マーケット（前夜のNASDAQ・S&P500・半導体株 関連ニュース）
 *   第3部 あなたの関心ジャンル（企業クエリ8社強化 + Geminiスコアフィルタ）
 *   第4部 素材・材料 専門メディア（MONOist / EE Times Japan / 日刊工業新聞）
 *
 * 【途切れない仕組み】
 *   メール本体はこのコードが組み立てる（文字数上限なし）。
 *   Geminiは各記事の短評＋関連度スコア(1-5)を生成。スコア≤2は第3部・第4部から除外。
 *
 * 【使い方】
 *   1) script.google.com で新規プロジェクト → 全部貼り付け
 *   2) CONFIG の GEMINI_API_KEY と RECIPIENTS だけ修正
 *   3) sendDailyNewsDigest で手動テスト → OKなら setupTrigger を実行
 *************************************************************/

/*==================== 設定（ここだけ触ればOK）====================*/
var CONFIG = {
  GEMINI_API_KEY: 'ここにGeminiのAPIキーを貼り付け',
  RECIPIENTS: ['あなたのアドレス@example.com'],
  GEMINI_MODEL: 'gemini-2.5-flash',

  LOOKBACK_HOURS: 48,     // 関心ジャンル・マーケットは直近48時間
  TOP_PER_REGION: 3,      // トップニュースは各地域この件数
  MAX_MARKET: 4,          // マーケットの件数
  MAX_INTEREST: 15,       // 関心ジャンルの最大件数
  MAX_SPECIALTY: 15,      // 専門メディアの最大件数

  // 第1部：トップニュース（Google News の地域別トップ）
  TOP_FEEDS: [
    { region: '🇯🇵 日本',  url: 'https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja' },
    { region: '🇺🇸 米国',  url: 'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en' },
    { region: '🌍 世界',  url: 'https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en' }
  ],

  // 第2部：マーケット（検索クエリ）
  MARKET_QUERIES: ['S&P 500 stock market', 'Nasdaq 100', '半導体 株 NVIDIA'],

  // 第3部：関心ジャンル（優先度別の検索クエリ）
  INTEREST_QUERIES: [
    { q: 'HDD HAMR storage',          pri: 'high' },
    { q: 'MLCC capacitor',            pri: 'high' },
    { q: '生成AI 企業',                pri: 'high' },
    { q: 'AI agent enterprise',       pri: 'high' },
    { q: '富士フイルム 半導体 材料',    pri: 'high' },
    { q: 'semiconductor manufacturing', pri: 'high' },
    { q: 'ヒューマノイド ロボット',     pri: 'medium' },
    { q: 'digital pathology AI',      pri: 'medium' },
    { q: 'スマートグラス AR',          pri: 'medium' },
    { q: '水素 PEM 電解',              pri: 'medium' },
    { q: '6G 光通信 photonics',        pri: 'low' },
    // ↓ 変更1: 素材・材料メーカー8社の専用クエリ
    { q: 'DNP 大日本印刷 フィルム 材料',  pri: 'high' },
    { q: 'レゾナック 半導体材料',          pri: 'high' },
    { q: 'JSR 半導体 フォトレジスト',      pri: 'high' },
    { q: '住友化学 素材 機能材料',          pri: 'high' },
    { q: 'AGC ガラス フッ素 材料',          pri: 'high' },
    { q: '信越化学 シリコン 半導体',        pri: 'high' },
    { q: '日東電工 光学フィルム テープ',    pri: 'high' },
    { q: 'リンテック 粘着 半導体',          pri: 'high' }
  ],

  // 第4部：素材・材料 専門メディア（RSS直接購読）
  SPECIALTY_FEEDS: [
    { name: 'MONOist',        url: 'https://monoist.itmedia.co.jp/rss/monoist_all.xml' },
    { name: 'EE Times Japan', url: 'https://eetimes.itmedia.co.jp/rss/eetimelj.xml' },
    { name: '日刊工業新聞',    url: 'https://www.nikkan.co.jp/rss/news.rss' }
  ]
};
/*================================================================*/


/** 毎朝5時に自動実行される本体 */
function sendDailyNewsDigest() {
  // ---- 収集 ----
  var top = collectTopNews_();        // [{region, items:[...]}]
  var market = collectMarket_();      // [...]
  var interest = collectInterest_();  // [...]
  var specialty = collectSpecialty_(); // 第4部

  var totalCount = market.length + interest.length + specialty.length;
  top.forEach(function (g) { totalCount += g.items.length; });
  if (totalCount === 0) { Logger.log('記事0件。中止。'); return; }
  Logger.log('収集: トップ' + top.reduce(function(s,g){return s+g.items.length;},0) +
             ' / マーケット' + market.length + ' / 関心' + interest.length +
             ' / 専門メディア' + specialty.length);

  // ---- Geminiで短評＋スコアを一括生成（失敗してもRSS要約で代替）----
  var allItems = [];
  top.forEach(function (g) { g.items.forEach(function (it) { allItems.push(it); }); });
  market.forEach(function (it) { allItems.push(it); });
  interest.forEach(function (it) { allItems.push(it); });
  specialty.forEach(function (it) { allItems.push(it); });
  addCommentsByGemini_(allItems);

  // ---- メール本体をコードで組み立て（途中で切れない）----
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


/*==================== 収集系 ====================*/

/** 第1部：地域別トップニュース */
function collectTopNews_() {
  var result = [];
  var seen = {};
  CONFIG.TOP_FEEDS.forEach(function (feed) {
    var items = fetchFeed_(feed.url, 0); // トップは日付フィルタなし
    var picked = [];
    for (var i = 0; i < items.length && picked.length < CONFIG.TOP_PER_REGION; i++) {
      var key = normalizeTitle_(items[i].title);
      if (!key || seen[key]) continue;
      seen[key] = true;
      picked.push(items[i]);
    }
    result.push({ region: feed.region, items: picked });
  });
  return result;
}

/** 第2部：マーケット関連ニュース */
function collectMarket_() {
  var all = [];
  var seen = {};
  var cutoff = Date.now() - CONFIG.LOOKBACK_HOURS * 3600 * 1000;
  CONFIG.MARKET_QUERIES.forEach(function (q) {
    var url = 'https://news.google.com/rss/search?q=' + encodeURIComponent(q) +
              '&hl=ja&gl=JP&ceid=JP:ja';
    fetchFeed_(url, cutoff).forEach(function (it) {
      var key = normalizeTitle_(it.title);
      if (!key || seen[key]) return;
      seen[key] = true;
      all.push(it);
    });
  });
  return all.slice(0, CONFIG.MAX_MARKET);
}

/** 第3部：関心ジャンル（優先度順） */
function collectInterest_() {
  var all = [];
  var seen = {};
  var cutoff = Date.now() - CONFIG.LOOKBACK_HOURS * 3600 * 1000;
  CONFIG.INTEREST_QUERIES.forEach(function (entry) {
    var url = 'https://news.google.com/rss/search?q=' + encodeURIComponent(entry.q) +
              '&hl=ja&gl=JP&ceid=JP:ja';
    var count = 0;
    fetchFeed_(url, cutoff).forEach(function (it) {
      if (count >= 3) return; // 1クエリ最大3件
      var key = normalizeTitle_(it.title);
      if (!key || seen[key]) return;
      seen[key] = true;
      it.priority = entry.pri;
      all.push(it);
      count++;
    });
  });
  var order = { high: 0, medium: 1, low: 2 };
  all.sort(function (a, b) { return order[a.priority] - order[b.priority]; });
  return all.slice(0, CONFIG.MAX_INTEREST);
}

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

/** RSSフィードを取得してパース（cutoff=0なら日付フィルタなし） */
function fetchFeed_(url, cutoff) {
  try {
    var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
    if (resp.getResponseCode() >= 400) { Logger.log('取得失敗(' + resp.getResponseCode() + '): ' + url); return []; }
    var channel = XmlService.parse(resp.getContentText()).getRootElement().getChild('channel');
    if (!channel) return [];
    var out = [];
    channel.getChildren('item').forEach(function (it) {
      var pub = it.getChildText('pubDate');
      if (cutoff && pub && new Date(pub).getTime() < cutoff) return;
      var src = it.getChild('source');
      out.push({
        title: stripHtml_(it.getChildText('title') || ''),
        link: it.getChildText('link') || '',
        snippet: stripHtml_(it.getChildText('description') || '').substring(0, 200),
        source: src ? src.getText() : 'Google News',
        comment: '',
        score: 3
      });
    });
    return out;
  } catch (e) {
    Logger.log('fetchFeed_ エラー: ' + url + ' / ' + e);
    return [];
  }
}


/*==================== Gemini短評＋スコアリング ====================*/

/** 全記事に短評と関連度スコア(1-5)を付与（1回のAPI呼び出し・失敗時は要約で代替） */
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

/** Gemini呼び出し（503は最大3回リトライ） */
function callGeminiWithRetry_(prompt) {
  var url = 'https://generativelanguage.googleapis.com/v1beta/models/' +
            CONFIG.GEMINI_MODEL + ':generateContent?key=' +
            encodeURIComponent(CONFIG.GEMINI_API_KEY);
  var body = JSON.stringify({
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: { temperature: 0.3, maxOutputTokens: 8192 }
  });

  for (var attempt = 1; attempt <= 3; attempt++) {
    var resp = UrlFetchApp.fetch(url, {
      method: 'post', contentType: 'application/json',
      payload: body, muteHttpExceptions: true
    });
    var code = resp.getResponseCode();
    if (code === 200) {
      var data = JSON.parse(resp.getContentText());
      if (data.candidates && data.candidates[0] && data.candidates[0].content) {
        return (data.candidates[0].content.parts || [])
          .map(function (p) { return p.text || ''; }).join('');
      }
      throw new Error('空の応答');
    }
    if (code === 503 && attempt < 3) {
      Logger.log('503。' + (attempt * 10) + '秒待って再試行(' + attempt + '/3)');
      Utilities.sleep(attempt * 10000);
      continue;
    }
    throw new Error('Gemini API error ' + code + ': ' + resp.getContentText().substring(0, 200));
  }
}


/*==================== メール組み立て ====================*/
function buildEmailHtml_(top, market, interest, specialty) {
  var html = '<div style="font-family:sans-serif;line-height:1.7;color:#222;max-width:700px">';

  // 第1部 トップニュース（フィルタなし）
  html += sectionTitle_('🌅 本日のトップニュース');
  top.forEach(function (g) {
    html += '<h3 style="margin:16px 0 6px;font-size:15px;color:#444">' + g.region + '</h3>';
    g.items.forEach(function (it) { html += itemHtml_(it); });
  });

  // 第2部 マーケット（フィルタなし）
  html += sectionTitle_('💹 マーケット（NASDAQ・S&P500・半導体）');
  if (market.length === 0) html += '<p style="color:#888">該当ニュースなし</p>';
  market.forEach(function (it) { html += itemHtml_(it); });

  // 第3部 関心ジャンル（スコア≤2を除外）
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

  // 第4部 素材・材料 専門メディア（スコア≤2を除外）
  html += sectionTitle_('🔬 素材・材料 専門メディア');
  var filteredSpecialty = (specialty || []).filter(function (it) { return (it.score || 3) >= 3; });
  if (filteredSpecialty.length === 0) html += '<p style="color:#888">該当ニュースなし</p>';
  filteredSpecialty.forEach(function (it) { html += itemHtml_(it); });

  html += '<hr style="margin-top:24px;border:none;border-top:1px solid #ddd">' +
          '<p style="font-size:11px;color:#999">— TAKE NEWS NAVI（Google News × Gemini 自動生成）</p></div>';
  return html;
}

function sectionTitle_(t) {
  return '<h2 style="margin:24px 0 8px;font-size:18px;border-bottom:2px solid #1a73e8;padding-bottom:4px">' + t + '</h2>';
}

function itemHtml_(it) {
  return '<p style="margin:8px 0">' +
         '■ <a href="' + it.link + '" style="color:#1a73e8;text-decoration:none;font-weight:bold">' + escapeHtml_(it.title) + '</a><br>' +
         '<span style="color:#333">' + escapeHtml_(it.comment || it.snippet) + '</span><br>' +
         '<span style="font-size:12px;color:#999">出典: ' + escapeHtml_(it.source) + '</span></p>';
}


/*==================== 補助 ====================*/
function stripHtml_(html) {
  if (!html) return '';
  var t = html.replace(/<script[\s\S]*?<\/script>/gi, ' ')
              .replace(/<style[\s\S]*?<\/style>/gi, ' ')
              .replace(/<[^>]+>/g, ' ')
              .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&')
              .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
              .replace(/&quot;/g, '"').replace(/&#39;/g, "'");
  return t.replace(/\s+/g, ' ').trim();
}
function escapeHtml_(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function stripFences_(s) {
  return (s || '').replace(/```(?:json|html)?/gi, '').replace(/```/g, '').trim();
}
function normalizeTitle_(title) {
  return (title || '').toLowerCase().replace(/\s+/g, '').replace(/[「」『』\-\–\—|｜]/g, '').substring(0, 60);
}

/*==================== トリガー設定（最初に1回だけ実行）====================*/
function setupTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'sendDailyNewsDigest') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('sendDailyNewsDigest')
    .timeBased().atHour(5).everyDays(1).inTimezone('Asia/Tokyo').create();
  Logger.log('毎朝5時(JST)の自動配信を設定しました。');
}
