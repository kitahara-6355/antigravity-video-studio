/**
 * 字幕の朱入れ（info@ のウェブアプリ）。スマホで開き、2 人で同じ印を見て直す。
 *
 * - 動画: Drive の「_確認用_<版>_小分け」フォルダ（review_pack.json と seg_*.ts）を要る所だけ渡す
 * - 印: 同じフォルダのシート「朱入れの印」に 1 行 1 印。Claude はこのシートを読んで直しに使う
 * - 一緒に見る: 進める人の再生位置を CacheService に置き、もう片方が 1 秒ごとに読む
 * どれも Business Standard の定額内（課金のある API は使わない）。
 * 正本: kitahara-6355/antigravity-video-studio の .claude/skills/caption-review/webapp/（clasp で送る）
 */
var PACK = 'review_pack.json';
var SHEET_NAME = '朱入れの印';
var HEAD = ['id', '時刻', '字幕', '正しくは', 'メモ', '状態', '付けた人', '更新', 'json'];

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('字幕の朱入れ')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1, viewport-fit=cover');
}

/** Drive にある確認用の小分けの一覧（新しい順） */
function listPacks() {
  var url = ScriptApp.getService().getUrl();
  var it = DriveApp.searchFiles('title = "' + PACK + '" and trashed = false');
  var out = [];
  while (it.hasNext() && out.length < 30) {
    var f = it.next(), ps = f.getParents();
    if (!ps.hasNext()) continue;
    var folder = ps.next();
    var name = folder.getName();
    var up = folder.getParents();
    if (up.hasNext()) name = up.next().getName() + ' / ' + name;
    out.push({ id: folder.getId(), name: name, at: f.getLastUpdated().getTime(), url: url + '?pack=' + folder.getId() });
  }
  out.sort(function (a, b) { return b.at - a.at; });
  return out;
}

function packFile_(packId) {
  var it = DriveApp.getFolderById(packId).getFilesByName(PACK);
  if (!it.hasNext()) throw new Error('確認用の控え（' + PACK + '）がありません');
  return it.next();
}

/** 字幕の控えと小分けの一覧（JSON の文字列） */
function getPack(packId) {
  var text = packFile_(packId).getBlob().getDataAsString('UTF-8');
  var ids = JSON.parse(text).segments.map(function (s) { return s.id; }).join(',');
  CacheService.getScriptCache().put('ids_' + packId, ids, 21600);
  return text;
}

/** 小分け 1 つ（base64）。その回の小分け以外は渡さない */
function getSeg(packId, fileId) {
  var cache = CacheService.getScriptCache();
  var ids = cache.get('ids_' + packId);
  if (ids === null) { getPack(packId); ids = cache.get('ids_' + packId) || ''; }
  if ((',' + ids + ',').indexOf(',' + fileId + ',') < 0) throw new Error('この回の動画ではありません');
  return Utilities.base64Encode(DriveApp.getFileById(fileId).getBlob().getBytes());
}

/** 小分けをまとめて（base64 の配列）。1 回の往復で数個取って待ち時間を減らす */
function getSegs(packId, fileIds) {
  if (!fileIds || fileIds.length > 12) throw new Error('一度に取れるのは 12 個までです');
  return fileIds.map(function (id) { return getSeg(packId, id); });
}

function sheet_(packId) {
  var props = PropertiesService.getScriptProperties();
  var key = 'sheet_' + packId, id = props.getProperty(key);
  if (id) { try { return SpreadsheetApp.openById(id).getSheets()[0]; } catch (e) { /* 消されていたら作り直す */ } }
  var folder = DriveApp.getFolderById(packId);
  var it = folder.getFilesByName(SHEET_NAME);
  var ss;
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

function readMarks_(packId) {
  var sh = sheet_(packId), n = sh.getLastRow() - 1, marks = {};
  if (n > 0) sh.getRange(2, 1, n, HEAD.length).getValues().forEach(function (r) {
    if (r[0] && r[8]) { try { marks[r[0]] = JSON.parse(r[8]); } catch (e) { /* 手で壊した行は飛ばす */ } }
  });
  return marks;
}

function version_(packId) {
  return Number(PropertiesService.getScriptProperties().getProperty('ver_' + packId) || 0);
}

/** 印（版が変わった時だけ）と、一緒に見る位置 */
function poll(packId, since, withLive) {
  var cache = CacheService.getScriptCache();
  var ver = version_(packId), out = { ver: ver };
  if (ver !== since) {
    var hit = cache.get('marks_' + packId + '_' + ver);
    out.marks = hit ? JSON.parse(hit) : readMarks_(packId);
    if (!hit) { var s = JSON.stringify(out.marks); if (s.length < 90000) cache.put('marks_' + packId + '_' + ver, s, 600); }
  }
  if (withLive) { var live = cache.get('live_' + packId); if (live) out.live = JSON.parse(live); }
  return out;
}

function clock_(t) { t = Math.max(0, t || 0); var m = Math.floor(t / 60), s = Math.floor(t % 60); return m + ':' + (s < 10 ? '0' : '') + s; }

/** 印を足す・変える・消す。kind は set / update / delete。新しい版の番号を返す */
function saveMark(packId, id, kind, json, by) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = sheet_(packId), n = sh.getLastRow() - 1, row = -1, cur = null;
    if (n > 0) {
      var ids = sh.getRange(2, 1, n, 1).getValues();
      for (var i = 0; i < n; i++) if (ids[i][0] === id) { row = i + 2; break; }
    }
    if (row > 0) { try { cur = JSON.parse(sh.getRange(row, 9).getValue()); } catch (e) { cur = null; } }
    if (kind === 'delete') { if (row > 0) sh.deleteRow(row); }
    else {
      var body = JSON.parse(json || '{}');
      var m = kind === 'update' && cur ? Object.assign(cur, body) : body;
      var vals = [id, clock_(m.t), String(m.text || '').replace(/\n/g, ' / '), String(m.fix || '').replace(/\n/g, ' / '),
        m.note || '', m.state || '', m.by || by || '', new Date(), JSON.stringify(m)];
      if (row > 0) sh.getRange(row, 1, 1, vals.length).setValues([vals]);
      else sh.appendRow(vals);
    }
    var ver = version_(packId) + 1;
    PropertiesService.getScriptProperties().setProperty('ver_' + packId, String(ver));
    return ver;
  } finally { lock.releaseLock(); }
}

/** 一緒に見る: 進める人の位置を置く（2 分で消える） */
function setLive(packId, json) {
  CacheService.getScriptCache().put('live_' + packId, json, 120);
  return true;
}
