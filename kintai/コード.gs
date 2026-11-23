/**
 * 勤怠記録 Webアプリ（改良版）
 *
 * ・今までの月別シート（例: 2026-11）をそのまま読み書きします
 * ・時給は「時給履歴」シートで管理し、途中で変わっても日付ごとに正しく計算します
 * ・毎週金曜日に「今週あと何時間働けるか」をメールでお知らせします
 *
 * 設定方法は README.md を見てください。
 */

// 時給履歴がまだ1件もないときに使う時給（最初の1回だけ使われます）
var YOUR_HOURLY_WAGE = 1500;

var TZ = 'Asia/Tokyo';
var SETTINGS_SHEET = '設定';
var WAGE_SHEET = '時給履歴';
var MONTH_SHEET_RE = /^\d{4}-\d{2}$/;
var HEADER = ['日付', '出勤時間', '退勤時間', '勤務時間(h)', '概算給与(円)', '時給(円)'];

// 設定のデフォルト値（「設定」シートで変更できます）
var DEFAULT_SETTINGS = {
  '週の上限時間': 20,
  '週の始まり': '月',          // 月〜日のどれか
  '標準の出勤時刻': '09:00',
  '通知先メール': '',          // 空欄なら自分のGmail
  '金曜通知の時刻': 8,         // 金曜日の何時に通知するか（0〜23）
  '学生': 'はい',              // はい / いいえ
  '19〜22歳': 'はい'           // はい / いいえ（12/31時点の年齢）
};
var SETTING_NOTES = {
  '週の上限時間': 'この時間を超えないようにお知らせします',
  '週の始まり': '1週間を何曜日から数えるか（勤務先のルールに合わせてください）',
  '標準の出勤時刻': '出勤ボタンを押さなかった日はこの時刻で計算します',
  '通知先メール': '空欄なら自分のGmailに届きます',
  '金曜通知の時刻': '金曜日の何時ごろにメールを送るか',
  '学生': '税金・社会保険の説明を切り替えます',
  '19〜22歳': '扶養の説明を切り替えます（その年の12/31時点）'
};
var WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'];

// ============================================================
//  画面を表示
// ============================================================
function doGet() {
  ensureSetup_();
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('勤怠記録')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1.0');
}

function getSheetUrl() { return SpreadsheetApp.getActiveSpreadsheet().getUrl(); }

// ============================================================
//  出勤・退勤
// ============================================================

/** 出勤を記録（timeStr を省略すると「今」） */
function punchIn(timeStr) {
  var today = todayStr_();
  var t = timeStr ? normTime_(timeStr) : Utilities.formatDate(new Date(), TZ, 'HH:mm:ss');
  if (!t) throw new Error('時刻の形式が正しくありません');
  PropertiesService.getScriptProperties().setProperty('SHUKKIN_' + today, t);
  return '【出勤】' + t.slice(0, 5) + ' で記録しました。';
}

/** 出勤記録を取り消す（標準の出勤時刻に戻る） */
function cancelPunchIn() {
  PropertiesService.getScriptProperties().deleteProperty('SHUKKIN_' + todayStr_());
  var s = getSettings_();
  return '出勤記録を取り消しました（' + s['標準の出勤時刻'] + ' 出勤として計算します）。';
}

// 昔のボタン名でも動くように残しています
function recordShukkin(customTime) { return punchIn(customTime); }
function recordTaikin() { return punchOut().message; }

/** 退勤を記録 */
function punchOut() {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var s = getSettings_();
    var today = todayStr_();
    var props = PropertiesService.getScriptProperties();
    var start = props.getProperty('SHUKKIN_' + today) || normTime_(s['標準の出勤時刻']);
    var end = Utilities.formatDate(new Date(), TZ, 'HH:mm:ss');
    var rec = writeRecord_(today, start, end);
    props.deleteProperty('SHUKKIN_' + today);

    var week = weekSummary_(readAllRecords_(), today, s);
    var limit = Number(s['週の上限時間']);
    var msg = '【退勤】記録しました！\n本日 ' + start.slice(0, 5) + '〜' + end.slice(0, 5) +
      ' / ' + rec.hours.toFixed(2) + '時間（' + rec.salary.toLocaleString() + '円）\n' +
      '今週の合計: ' + week.hours.toFixed(2) + '時間';
    var warn = '';
    if (week.hours > limit) {
      warn = '⚠️ 今週は上限' + limit + '時間を ' + (week.hours - limit).toFixed(2) + '時間 超えています';
    } else if (limit - week.hours < 4) {
      warn = '今週の残りは あと ' + (limit - week.hours).toFixed(2) + '時間 です';
    }
    return { message: msg, warning: warn };
  } finally {
    lock.releaseLock();
  }
}

// ============================================================
//  画面に出すデータ
// ============================================================

/** ホーム画面のデータ */
function getDashboard() {
  ensureSetup_();
  var s = getSettings_();
  var recs = readAllRecords_();
  var today = todayStr_();
  var nowTime = Utilities.formatDate(new Date(), TZ, 'HH:mm');
  var y = today.slice(0, 4), ym = today.slice(0, 7);
  var limit = Number(s['週の上限時間']);

  var pending = PropertiesService.getScriptProperties().getProperty('SHUKKIN_' + today);
  var todayRecs = recs.filter(function (r) { return r.date === today; });
  var week = weekSummary_(recs, today, s);

  // 今日あと何時まで働けるか
  var plannedStart = pending || normTime_(s['標準の出勤時刻']);
  var remain = Math.max(0, limit - week.hours);
  var okUntil = '';
  if (todayRecs.length === 0) {
    okUntil = addHours_(plannedStart, remain);
  }

  var month = sumUp_(recs.filter(function (r) { return r.date.slice(0, 7) === ym; }));
  var yearRecs = recs.filter(function (r) { return r.date.slice(0, 4) === y; });
  var year = sumUp_(yearRecs);
  var projection = projectYear_(yearRecs, today);

  return {
    today: today,
    todayLabel: labelDate_(today),
    now: nowTime,
    isFriday: dateObj_(today).getDay() === 5,
    pendingStart: pending ? pending.slice(0, 5) : '',
    defaultStart: s['標準の出勤時刻'],
    todayRecords: todayRecs.map(slim_),
    week: week,
    limit: limit,
    remain: round2_(remain),
    okUntil: okUntil,
    month: month,
    year: year,
    projection: projection,
    wage: wageFor_(today, getWageHistory_()),
    walls: buildWalls_(Number(y), year.salary, projection, s),
    settings: s
  };
}

/** 勤怠表（1か月分） ym = "2026-11" */
function getMonth(ym) {
  var s = getSettings_();
  var recs = readAllRecords_();
  var list = recs.filter(function (r) { return r.date.slice(0, 7) === ym; });
  list.sort(function (a, b) { return (a.date + a.start).localeCompare(b.date + b.start); });

  // その月にかかる週ごとの合計（月をまたぐ週は前後の月も含めて計算）
  var weeks = [];
  var seen = {};
  var y = Number(ym.slice(0, 4)), m = Number(ym.slice(5, 7));
  var last = new Date(y, m, 0).getDate();
  for (var d = 1; d <= last; d++) {
    var ds = ym.replace('-', '/') + '/' + pad_(d);
    var ws = weekStartStr_(ds, s);
    if (seen[ws]) continue;
    seen[ws] = true;
    var w = weekSummary_(recs, ds, s);
    weeks.push(w);
  }

  return {
    ym: ym,
    records: list.map(slim_),
    total: sumUp_(list),
    weeks: weeks,
    limit: Number(s['週の上限時間']),
    months: listMonths_(recs)
  };
}

/** 振り返り（1年分） */
function getYear(y) {
  y = String(y);
  var s = getSettings_();
  var recs = readAllRecords_();
  var months = [];
  for (var m = 1; m <= 12; m++) {
    var ym = y + '-' + pad_(m);
    var list = recs.filter(function (r) { return r.date.slice(0, 7) === ym; });
    var sum = sumUp_(list);
    sum.ym = ym;
    months.push(sum);
  }
  var yearRecs = recs.filter(function (r) { return r.date.slice(0, 4) === y; });
  var prevRecs = recs.filter(function (r) { return r.date.slice(0, 4) === String(Number(y) - 1); });

  // 上限を超えた週の数
  var limit = Number(s['週の上限時間']);
  var weekMap = {};
  yearRecs.forEach(function (r) {
    var ws = weekStartStr_(r.date, s);
    weekMap[ws] = (weekMap[ws] || 0) + r.hours;
  });
  var weekKeys = Object.keys(weekMap);
  var overWeeks = weekKeys.filter(function (k) { return weekMap[k] > limit + 1e-9; }).sort();

  var years = {};
  recs.forEach(function (r) { years[r.date.slice(0, 4)] = true; });
  years[todayStr_().slice(0, 4)] = true;

  var projection = (y === todayStr_().slice(0, 4)) ? projectYear_(yearRecs, todayStr_()) : sumUp_(yearRecs).salary;
  var total = sumUp_(yearRecs);

  return {
    year: y,
    months: months,
    total: total,
    prevTotal: sumUp_(prevRecs),
    weekCount: weekKeys.length,
    avgWeekHours: weekKeys.length ? round2_(total.hours / weekKeys.length) : 0,
    overWeeks: overWeeks.map(function (k) { return { start: k, label: labelDate_(k), hours: round2_(weekMap[k]) }; }),
    years: Object.keys(years).sort().reverse(),
    walls: buildWalls_(Number(y), total.salary, projection, s),
    projection: projection,
    isCurrent: y === todayStr_().slice(0, 4)
  };
}

// ============================================================
//  記録の追加・修正・削除
// ============================================================

/** 記録を手で追加（押し忘れたとき） */
function addRecord(date, start, end) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var d = normDate_(date), st = normTime_(start), en = normTime_(end);
    if (!d || !st || !en) throw new Error('日付・時刻を正しく入力してください');
    writeRecord_(d, st, en);
    return '追加しました';
  } finally { lock.releaseLock(); }
}

/** 記録を修正 */
function updateRecord(sheetName, row, origDate, date, start, end) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var d = normDate_(date), st = normTime_(start), en = normTime_(end);
    if (!d || !st || !en) throw new Error('日付・時刻を正しく入力してください');
    var sheet = checkRow_(sheetName, row, origDate);
    if (d.slice(0, 7).replace('/', '-') === sheetName) {
      var hours = calcHours_(st, en);
      var wage = wageFor_(d, getWageHistory_());
      sheet.getRange(row, 1, 1, 6).setValues([[d, st, en, hours, Math.floor(hours * wage), wage]]);
      sortSheet_(sheet);
    } else {
      // 別の月に移す
      sheet.deleteRow(row);
      writeRecord_(d, st, en);
    }
    return '修正しました';
  } finally { lock.releaseLock(); }
}

/** 記録を削除 */
function deleteRecord(sheetName, row, origDate) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    checkRow_(sheetName, row, origDate).deleteRow(row);
    return '削除しました';
  } finally { lock.releaseLock(); }
}

// ============================================================
//  時給
// ============================================================

function getWages() {
  return getWageHistory_().map(function (w) { return { from: w.from, wage: w.wage, row: w.row }; });
}

/** 時給の変更を登録 → 全部の記録を計算し直す */
function addWage(fromDate, wage) {
  var d = normDate_(fromDate);
  wage = Number(wage);
  if (!d || !(wage > 0)) throw new Error('日付と時給を正しく入力してください');
  var sh = getWageSheet_();
  var hist = getWageHistory_();
  var same = hist.filter(function (h) { return h.from === d; })[0];
  if (same) {
    sh.getRange(same.row, 2).setValue(wage);
  } else {
    sh.appendRow([d, wage]);
  }
  sortWageSheet_(sh);
  var n = recalcAll();
  return d + ' から時給 ' + wage.toLocaleString() + '円 にしました（' + n + '件を計算し直しました）';
}

function deleteWage(row) {
  var sh = getWageSheet_();
  if (sh.getLastRow() <= 2) throw new Error('時給は最低1件必要です');
  sh.deleteRow(Number(row));
  var n = recalcAll();
  return '削除しました（' + n + '件を計算し直しました）';
}

/**
 * 全部の記録の「勤務時間・給与・時給」を計算し直す
 * （スクリプトエディタからこの関数を選んで実行してもOK）
 */
function recalcAll() {
  var hist = getWageHistory_();
  var count = 0;
  getMonthSheets_().forEach(function (sheet) {
    var last = sheet.getLastRow();
    if (last < 2) return;
    sheet.getRange(1, 6).setValue(HEADER[5]).setFontWeight('bold');
    var rng = sheet.getRange(2, 1, last - 1, 6);
    var vals = rng.getValues(), disp = rng.getDisplayValues();
    var out = [];
    for (var i = 0; i < vals.length; i++) {
      var d = cellDate_(vals[i][0], disp[i][0]);
      var st = cellTime_(vals[i][1], disp[i][1]);
      var en = cellTime_(vals[i][2], disp[i][2]);
      if (!d || !st || !en) { out.push([vals[i][3], vals[i][4], vals[i][5]]); continue; }
      var h = calcHours_(st, en);
      var w = wageFor_(d, hist);
      out.push([h, Math.floor(h * w), w]);
      count++;
    }
    sheet.getRange(2, 4, out.length, 3).setValues(out);
    formatSheet_(sheet);
  });
  return count;
}

// ============================================================
//  設定
// ============================================================

function saveSettings(obj) {
  var sh = getSettingsSheet_();
  var vals = sh.getDataRange().getValues();
  Object.keys(obj).forEach(function (k) {
    if (!(k in DEFAULT_SETTINGS)) return;
    for (var i = 1; i < vals.length; i++) {
      if (vals[i][0] === k) { sh.getRange(i + 1, 2).setValue(obj[k]); return; }
    }
    sh.appendRow([k, obj[k], SETTING_NOTES[k] || '']);
  });
  return '設定を保存しました';
}

// ============================================================
//  金曜日のお知らせ・退勤忘れのお知らせ
// ============================================================

/** 通知を設定する（アプリの「設定」から、またはエディタで1回実行） */
function setupNotifications() {
  removeNotifications();
  var s = getSettings_();
  var hour = Math.min(23, Math.max(0, Number(s['金曜通知の時刻']) || 8));
  ScriptApp.newTrigger('fridayReminder').timeBased()
    .onWeekDay(ScriptApp.WeekDay.FRIDAY).atHour(hour).inTimezone(TZ).create();
  ScriptApp.newTrigger('forgotCheck').timeBased()
    .everyDays(1).atHour(22).inTimezone(TZ).create();
  return '通知をオンにしました（毎週金曜 ' + hour + '時ごろ ＋ 毎日22時の退勤忘れチェック）';
}

function removeNotifications() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    var f = t.getHandlerFunction();
    if (f === 'fridayReminder' || f === 'forgotCheck') ScriptApp.deleteTrigger(t);
  });
  return '通知をオフにしました';
}

function notificationsOn() {
  return ScriptApp.getProjectTriggers().some(function (t) { return t.getHandlerFunction() === 'fridayReminder'; });
}

/** 金曜日に今週の残り時間をメールで知らせる */
function fridayReminder() {
  var s = getSettings_();
  var today = todayStr_();
  var recs = readAllRecords_();
  var week = weekSummary_(recs, today, s);
  var limit = Number(s['週の上限時間']);
  var remain = limit - week.hours;
  var start = PropertiesService.getScriptProperties().getProperty('SHUKKIN_' + today) || normTime_(s['標準の出勤時刻']);

  var lines = [];
  lines.push('今週（' + labelDate_(week.start) + '〜' + labelDate_(week.end) + '）の勤務状況です。');
  lines.push('');
  week.days.forEach(function (d) {
    lines.push('  ' + d.label + '  ' + (d.hours ? d.hours.toFixed(2) + '時間' : '-'));
  });
  lines.push('');
  lines.push('今週の合計: ' + week.hours.toFixed(2) + ' 時間 ／ 上限 ' + limit + ' 時間');
  var subject;
  if (remain <= 0) {
    subject = '【勤怠】⚠️ 今週はすでに' + limit + '時間に達しています';
    lines.push('⚠️ 上限に達しています。今日以降の勤務は上限超えになります。');
  } else {
    subject = '【勤怠】今週はあと ' + remain.toFixed(1) + ' 時間 働けます';
    lines.push('残り: ' + remain.toFixed(2) + ' 時間');
    lines.push('今日 ' + start.slice(0, 5) + ' 出勤なら、' + addHours_(start, remain) + ' までに退勤すれば上限内です。');
    if (week.restDays > 1) lines.push('（土日も含めた残りです。土日に働く予定があればその分も考えてください）');
  }
  lines.push('');
  lines.push('アプリ: ' + ScriptApp.getService().getUrl());
  MailApp.sendEmail(mailTo_(s), subject, lines.join('\n'));
}

/** 出勤したのに退勤を押し忘れていたら知らせる */
function forgotCheck() {
  var s = getSettings_();
  var today = todayStr_();
  var pending = PropertiesService.getScriptProperties().getProperty('SHUKKIN_' + today);
  if (!pending) return;
  var has = readAllRecords_().some(function (r) { return r.date === today; });
  if (has) return;
  MailApp.sendEmail(mailTo_(s), '【勤怠】退勤の記録がまだです',
    '今日は ' + pending.slice(0, 5) + ' に出勤しましたが、退勤がまだ記録されていません。\n' +
    'アプリの「勤怠表」から退勤時刻を追加してください。\n\n' + ScriptApp.getService().getUrl());
}

/** テスト用：今すぐ金曜メールを送る */
function testFridayMail() { fridayReminder(); return 'テストメールを送りました'; }

// ============================================================
//  ここから下は内部の処理
// ============================================================

function ensureSetup_() {
  getSettingsSheet_();
  getWageSheet_();
}

function getSettingsSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SETTINGS_SHEET);
  if (!sh) {
    sh = ss.insertSheet(SETTINGS_SHEET);
    var rows = [['項目', '値', '説明']];
    Object.keys(DEFAULT_SETTINGS).forEach(function (k) { rows.push([k, DEFAULT_SETTINGS[k], SETTING_NOTES[k]]); });
    sh.getRange(1, 1, rows.length, 3).setValues(rows);
    sh.getRange('B4').setNumberFormat('@').setValue(DEFAULT_SETTINGS['標準の出勤時刻']);
    sh.getRange('A1:C1').setFontWeight('bold');
    sh.setColumnWidth(1, 140); sh.setColumnWidth(3, 380);
  }
  return sh;
}

function getSettings_() {
  var s = {};
  Object.keys(DEFAULT_SETTINGS).forEach(function (k) { s[k] = DEFAULT_SETTINGS[k]; });
  var sh = getSettingsSheet_();
  var vals = sh.getDataRange().getValues(), disp = sh.getDataRange().getDisplayValues();
  for (var i = 1; i < vals.length; i++) {
    var k = vals[i][0];
    if (!(k in DEFAULT_SETTINGS)) continue;
    if (vals[i][1] === '' || vals[i][1] === null) continue;
    s[k] = (k === '標準の出勤時刻') ? (normTime_(disp[i][1]) || '09:00:00').slice(0, 5) : vals[i][1];
  }
  if (WEEKDAYS.indexOf(String(s['週の始まり']).charAt(0)) < 0) s['週の始まり'] = '月';
  return s;
}

function getWageSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(WAGE_SHEET);
  if (!sh) {
    sh = ss.insertSheet(WAGE_SHEET);
    sh.getRange(1, 1, 2, 2).setValues([['適用開始日', '時給(円)'], ['2000/01/01', YOUR_HOURLY_WAGE]]);
    sh.getRange('A1:B1').setFontWeight('bold');
  }
  return sh;
}

function getWageHistory_() {
  var sh = getWageSheet_();
  var last = sh.getLastRow();
  if (last < 2) return [{ from: '2000/01/01', wage: YOUR_HOURLY_WAGE, row: 0 }];
  var rng = sh.getRange(2, 1, last - 1, 2);
  var vals = rng.getValues(), disp = rng.getDisplayValues();
  var out = [];
  for (var i = 0; i < vals.length; i++) {
    var d = cellDate_(vals[i][0], disp[i][0]);
    var w = Number(vals[i][1]);
    if (d && w > 0) out.push({ from: d, wage: w, row: i + 2 });
  }
  out.sort(function (a, b) { return a.from.localeCompare(b.from); });
  return out.length ? out : [{ from: '2000/01/01', wage: YOUR_HOURLY_WAGE, row: 0 }];
}

function sortWageSheet_(sh) {
  if (sh.getLastRow() > 2) sh.getRange(2, 1, sh.getLastRow() - 1, 2).sort(1);
}

function wageFor_(date, hist) {
  var w = hist[0].wage;
  for (var i = 0; i < hist.length; i++) {
    if (hist[i].from <= date) w = hist[i].wage;
  }
  return w;
}

function getMonthSheets_() {
  return SpreadsheetApp.getActiveSpreadsheet().getSheets().filter(function (sh) {
    return MONTH_SHEET_RE.test(sh.getName());
  });
}

function getOrCreateMonthSheet_(ym) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(ym);
  if (!sheet) {
    sheet = ss.insertSheet(ym);
    sheet.appendRow(HEADER);
    sheet.getRange('A1:F1').setFontWeight('bold');
    formatSheet_(sheet);
  } else if (sheet.getRange(1, 6).getValue() === '') {
    sheet.getRange(1, 6).setValue(HEADER[5]).setFontWeight('bold');
  }
  return sheet;
}

function formatSheet_(sheet) {
  sheet.getRange('D:D').setNumberFormat('0.00');
  sheet.getRange('E:F').setNumberFormat('#,##0');
}

function sortSheet_(sheet) {
  var last = sheet.getLastRow();
  if (last > 2) sheet.getRange(2, 1, last - 1, 6).sort([{ column: 1 }, { column: 2 }]);
}

/** 1件書き込む（今までと同じ形式） */
function writeRecord_(date, start, end) {
  var ym = date.slice(0, 7).replace('/', '-');
  var sheet = getOrCreateMonthSheet_(ym);
  var hours = calcHours_(start, end);
  var wage = wageFor_(date, getWageHistory_());
  var salary = Math.floor(hours * wage);
  sheet.appendRow([date, start, end, hours, salary, wage]);
  sortSheet_(sheet);
  return { hours: hours, salary: salary, wage: wage };
}

function checkRow_(sheetName, row, origDate) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
  row = Number(row);
  if (!sheet || row < 2 || row > sheet.getLastRow()) throw new Error('記録が見つかりません。画面を更新してください');
  var c = sheet.getRange(row, 1);
  if (cellDate_(c.getValue(), c.getDisplayValue()) !== origDate) {
    throw new Error('記録が変わっています。画面を更新してやり直してください');
  }
  return sheet;
}

/** 全部の月別シートを読む */
function readAllRecords_() {
  var out = [];
  getMonthSheets_().forEach(function (sheet) {
    var last = sheet.getLastRow();
    if (last < 2) return;
    var rng = sheet.getRange(2, 1, last - 1, 6);
    var vals = rng.getValues(), disp = rng.getDisplayValues();
    for (var i = 0; i < vals.length; i++) {
      var d = cellDate_(vals[i][0], disp[i][0]);
      if (!d) continue;
      var st = cellTime_(vals[i][1], disp[i][1]) || '';
      var en = cellTime_(vals[i][2], disp[i][2]) || '';
      var h = Number(vals[i][3]);
      if (!(h >= 0) || vals[i][3] === '') h = (st && en) ? calcHours_(st, en) : 0;
      out.push({
        sheet: sheet.getName(), row: i + 2, date: d, start: st, end: en,
        hours: h, salary: Number(vals[i][4]) || 0, wage: Number(vals[i][5]) || 0
      });
    }
  });
  out.sort(function (a, b) { return (a.date + a.start).localeCompare(b.date + b.start); });
  return out;
}

function slim_(r) {
  return {
    sheet: r.sheet, row: r.row, date: r.date, label: labelDate_(r.date),
    start: r.start.slice(0, 5), end: r.end.slice(0, 5),
    hours: round2_(r.hours), salary: r.salary, wage: r.wage
  };
}

function sumUp_(list) {
  var h = 0, p = 0, days = {};
  list.forEach(function (r) { h += r.hours; p += r.salary; days[r.date] = true; });
  return { hours: round2_(h), salary: p, days: Object.keys(days).length };
}

/** date を含む週のまとめ */
function weekSummary_(recs, date, s) {
  var ws = weekStartStr_(date, s);
  var start = dateObj_(ws);
  var days = [], total = 0, pay = 0;
  var today = todayStr_();
  var restDays = 0;
  for (var i = 0; i < 7; i++) {
    var d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i, 12);
    var ds = fmt_(d);
    var h = 0;
    recs.forEach(function (r) { if (r.date === ds) { h += r.hours; pay += r.salary; } });
    total += h;
    if (ds >= today) restDays++;
    days.push({ date: ds, label: labelDate_(ds), wd: WEEKDAYS[d.getDay()], hours: round2_(h), isToday: ds === today });
  }
  return {
    start: ws, end: days[6].date, label: labelDate_(ws) + '〜' + labelDate_(days[6].date),
    hours: round2_(total), salary: pay, days: days, restDays: restDays
  };
}

function weekStartStr_(date, s) {
  var startDow = WEEKDAYS.indexOf(String(s['週の始まり']).charAt(0));
  if (startDow < 0) startDow = 1;
  var d = dateObj_(date);
  var diff = (d.getDay() - startDow + 7) % 7;
  return fmt_(new Date(d.getFullYear(), d.getMonth(), d.getDate() - diff, 12));
}

/** 今のペースで1年働いた場合の年収見込み */
function projectYear_(yearRecs, today) {
  var sum = sumUp_(yearRecs).salary;
  if (!yearRecs.length) return 0;
  var y = Number(today.slice(0, 4));
  var first = dateObj_(yearRecs[0].date);
  var t = dateObj_(today);
  var jan1 = new Date(y, 0, 1, 12), dec31 = new Date(y, 11, 31, 12);
  var from = first > jan1 ? first : jan1;
  var elapsed = Math.max(28, (t - from) / 86400000 + 1); // 最初の4週間はならす
  var remainDays = Math.max(0, (dec31 - t) / 86400000);
  return Math.round(sum + sum / elapsed * remainDays);
}

/**
 * 年収の壁（2026年11月時点の制度をもとにした目安）
 * 金額や条件は法律改正で変わるので、毎年見直してください。
 */
function buildWalls_(year, actual, projection, s) {
  var student = String(s['学生']) === 'はい';
  var young = String(s['19〜22歳']) === 'はい';
  var taxLine = year <= 2025 ? 1600000 : 1780000;
  var depLine = year <= 2025 ? 1230000 : 1360000;
  var walls = [
    { amount: 1100000, title: '住民税がかかり始める', who: '自分',
      desc: '年収がおよそ110万円を超えると住民税がかかり始めます（お住まいの市区町村で少し前後します）。金額は1年で数千円〜数万円程度で、翌年に払います。' },
    { amount: depLine, title: young ? '親の扶養控除が減り始める' : '家族の扶養控除の対象外になる', who: '家族',
      desc: young
        ? '19〜22歳は、この金額を超えても150万円くらいまでは親の税金の控除は満額のまま（特定親族特別控除）。それを超えると少しずつ減ります。親の税金が増えるので要相談。'
        : 'この金額を超えると、家族（親など）が税金の「扶養控除」を受けられなくなり、家族の税金が増えます。' },
    { amount: young ? 1500000 : 1300000, title: '家族の健康保険の扶養から外れる', who: '自分',
      desc: (young ? '19〜22歳はこのラインが150万円です（2025年10月〜）。' : '') +
        '超えると家族の健康保険から外れ、自分で国民健康保険・国民年金に入る必要があり、年に約20〜30万円の負担になります。いちばん影響が大きい壁です。' },
    { amount: taxLine, title: '自分に所得税がかかり始める', who: '自分',
      desc: (year <= 2025 ? '2025年分は160万円。' : '2026年分から178万円に引き上げられました。') +
        '給料から引かれていた所得税は、年末調整で戻ってくることが多いです。' }
  ];
  walls.forEach(function (w) {
    w.actualRate = Math.min(1.5, actual / w.amount);
    w.projRate = Math.min(1.5, projection / w.amount);
    w.status = actual > w.amount ? '超えた' : projection > w.amount ? '超えそう' : projection > w.amount * 0.9 ? '注意' : '余裕';
  });
  return {
    list: walls,
    weekly: {
      title: '週20時間の壁（社会保険・雇用保険）',
      desc: student
        ? '昼間の学生は、週20時間以上でも勤務先の社会保険（厚生年金・健康保険）と雇用保険には原則入りません。ただし留学生の場合は「週28時間以内」の別ルールがあります。'
        : '契約上の勤務時間が週20時間以上になると、勤務先によっては社会保険（厚生年金・健康保険）や雇用保険に入ることになり、給料から保険料が引かれます。2026年10月から「月8.8万円（106万円の壁）」の条件はなくなり、時間で判断されます。'
    }
  };
}

function mailTo_(s) {
  return s['通知先メール'] || Session.getEffectiveUser().getEmail();
}

// ---------- 日付・時刻の小道具 ----------

function todayStr_() { return Utilities.formatDate(new Date(), TZ, 'yyyy/MM/dd'); }
function pad_(n) { return (n < 10 ? '0' : '') + n; }
function round2_(n) { return Math.round(n * 100) / 100; }
function fmt_(d) { return d.getFullYear() + '/' + pad_(d.getMonth() + 1) + '/' + pad_(d.getDate()); }

function dateObj_(ds) {
  var p = ds.split('/');
  return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]), 12);
}

function labelDate_(ds) {
  var d = dateObj_(ds);
  return (d.getMonth() + 1) + '/' + d.getDate() + '(' + WEEKDAYS[d.getDay()] + ')';
}

/** "2026-11-3" や "2026/11/03" → "2026/11/03" */
function normDate_(v) {
  var m = String(v).match(/(\d{4})\D+(\d{1,2})\D+(\d{1,2})/);
  if (!m) return '';
  return m[1] + '/' + pad_(Number(m[2])) + '/' + pad_(Number(m[3]));
}

/** "9:00" や "09:00:00" → "09:00:00" */
function normTime_(v) {
  var m = String(v).match(/(\d{1,2}):(\d{2})(?::(\d{2}))?/);
  if (!m) return '';
  return pad_(Number(m[1])) + ':' + m[2] + ':' + (m[3] || '00');
}

function cellDate_(val, disp) {
  if (val instanceof Date) {
    return Utilities.formatDate(val, SpreadsheetApp.getActiveSpreadsheet().getSpreadsheetTimeZone(), 'yyyy/MM/dd');
  }
  return normDate_(disp || val);
}

function cellTime_(val, disp) {
  var t = normTime_(disp);
  if (t) return t;
  if (val instanceof Date) {
    return Utilities.formatDate(val, SpreadsheetApp.getActiveSpreadsheet().getSpreadsheetTimeZone(), 'HH:mm:ss');
  }
  return normTime_(val);
}

function toSec_(t) {
  var p = t.split(':');
  return Number(p[0]) * 3600 + Number(p[1]) * 60 + Number(p[2] || 0);
}

/** 勤務時間（時間）。退勤が出勤より前なら日付またぎとして計算 */
function calcHours_(start, end) {
  var diff = toSec_(end) - toSec_(start);
  if (diff < 0) diff += 24 * 3600;
  return diff / 3600;
}

function addHours_(time, hours) {
  var sec = toSec_(time) + Math.round(hours * 3600);
  var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return (h >= 24 ? '翌' + (h - 24) : h) + ':' + pad_(m);
}

function listMonths_(recs) {
  var m = {};
  recs.forEach(function (r) { m[r.date.slice(0, 7).replace('/', '-')] = true; });
  m[todayStr_().slice(0, 7).replace('/', '-')] = true;
  return Object.keys(m).sort().reverse();
}
