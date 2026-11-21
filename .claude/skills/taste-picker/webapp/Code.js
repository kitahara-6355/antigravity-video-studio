/**
 * 好みえらび（info@ のウェブアプリ）。美麗さんがスマホで、同じ場面で曲だけ変えた 2 本を見比べて押す。
 *
 * - 見本: Drive の 30_AVS_作業/好みカルテ/<名前>/見本（taste_pack.json と *.mp4）。python -m backend.program_package.taste が作る
 * - 答え: 同じフォルダのシート「好みの答え」に 1 回 1 行。Claude はこのシートを読んで順位と好みカルテにする
 * どれも Business Standard の定額内（課金のある API は使わない）。
 * 正本: kitahara-6355/antigravity-video-studio の .claude/skills/taste-picker/webapp/（clasp で送る）
 */
var PACK = 'taste_pack.json';
var SHEET_NAME = '好みの答え';
var HEAD = ['時刻', '答えた人', '回', 'A', 'B', '選んだ', '一言', '決めた曲', 'json'];

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('好みえらび')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1, viewport-fit=cover');
}

/** Drive にある見本の一覧（新しい順） */
function listPacks() {
  var url = ScriptApp.getService().getUrl();
  var it = DriveApp.searchFiles('title = "' + PACK + '" and trashed = false');
  var out = [];
  while (it.hasNext() && out.length < 30) {
    var f = it.next(), ps = f.getParents();
    if (!ps.hasNext()) continue;
    var folder = ps.next(), name = folder.getName(), up = folder.getParents();
    if (up.hasNext()) name = up.next().getName();
    out.push({ id: folder.getId(), name: name, at: f.getLastUpdated().getTime(), url: url + '?pack=' + folder.getId() });
  }
  out.sort(function (a, b) { return b.at - a.at; });
  return out;
}

function packFile_(packId) {
  var it = DriveApp.getFolderById(packId).getFilesByName(PACK);
  if (!it.hasNext()) throw new Error('見本の控え（' + PACK + '）がありません');
  return it.next();
}

/** 見本の控え（JSON の文字列）と、これまでの答え */
function getPack(packId) {
  var text = packFile_(packId).getBlob().getDataAsString('UTF-8');
  var clips = JSON.parse(text).items.map(function (x) { return x.clip; }).join('/');
  CacheService.getScriptCache().put('clips_' + packId, clips, 21600);
  return { pack: text, answers: readAnswers_(packId), who: Session.getActiveUser().getEmail() || '' };
}

/** 見本 1 本（base64）。控えにある見本以外は渡さない */
function getClip(packId, clip) {
  var cache = CacheService.getScriptCache(), clips = cache.get('clips_' + packId);
  if (clips === null) { getPack(packId); clips = cache.get('clips_' + packId) || ''; }
  if (('/' + clips + '/').indexOf('/' + clip + '/') < 0) throw new Error('この見本ではありません');
  var it = DriveApp.getFolderById(packId).getFilesByName(clip);
  if (!it.hasNext()) throw new Error('見本がありません: ' + clip);
  return Utilities.base64Encode(it.next().getBlob().getBytes());
}

function sheet_(packId) {
  var props = PropertiesService.getScriptProperties();
  var key = 'sheet_' + packId, id = props.getProperty(key);
  if (id) { try { return SpreadsheetApp.openById(id).getSheets()[0]; } catch (e) { /* 消されていたら作り直す */ } }
  var folder = DriveApp.getFolderById(packId), it = folder.getFilesByName(SHEET_NAME), ss;
  if (it.hasNext()) ss = SpreadsheetApp.openById(it.next().getId());
  else {
    ss = SpreadsheetApp.create(SHEET_NAME);
    ss.setSpreadsheetTimeZone('Asia/Tokyo');
    DriveApp.getFileById(ss.getId()).moveTo(folder);
    var sh = ss.getSheets()[0];
    sh.getRange(1, 1, 1, HEAD.length).setValues([HEAD]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  props.setProperty(key, ss.getId());
  return ss.getSheets()[0];
}

function readAnswers_(packId) {
  var sh = sheet_(packId), n = sh.getLastRow() - 1, out = [];
  if (n > 0) sh.getRange(2, HEAD.length, n, 1).getValues().forEach(function (r) {
    try { out.push(JSON.parse(r[0])); } catch (e) { /* 手で壊した行は飛ばす */ }
  });
  return out;
}

/** 答えを 1 つ足す。json は {a, b, pick: a|b|both|neither, note, round, decided} */
function saveAnswer(packId, json) {
  var m = JSON.parse(json);
  if (!m.decided && ['a', 'b', 'both', 'neither'].indexOf(m.pick) < 0) throw new Error('答えの形が違います');
  var who = Session.getActiveUser().getEmail() || '';
  m.by = m.by || who;
  m.at = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss');
  var word = { a: 'A', b: 'B', both: 'どちらも好き', neither: 'どちらも違う' }[m.pick] || '';
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    sheet_(packId).appendRow([new Date(), m.by, m.round || '', m.a || '', m.b || '', word,
      String(m.note || ''), m.decided || '', JSON.stringify(m)]);
  } finally { lock.releaseLock(); }
  return true;
}
