// 呼び出し口。**frontend から backend へ出る唯一の扉。**
//
// なぜ1つに集約するか: 呼び出しが散らばっていると「全部見た」を走査で示すしか
// なく、走査は精度を要求する。精度を要求する判定は、読み違いが黙って PASS になる。
// 扉を1つにすれば、外側の判定は「扉の外に呼び出しが無い」という**禁止**になる。
// 禁止は精度を要求しない — 誤検出しても FAIL が増えるだけで、沈黙にはならない。
//
// ここ以外に fetch / WebSocket / window.open / backend の URL リテラルを
// 書いてはいけない。書けば ui_api_closure のゲートが CI で落とす。
//
// **宛先は必ず ENDPOINTS のキーで指定する。** パスを文字列で受け取る関数は
// 置かない。置いた瞬間、呼び出し側がパスを組み立てられるようになり、
// カタログが「叩ける先の全部」でなくなる。

import { ENDPOINTS } from './endpoints.js';

// backend のオリジン。**カタログのパス以外の URL 断片はここにしか無い。**
const HTTP_ORIGIN = 'http://localhost:8000';
const WS_ORIGIN = 'ws://localhost:8000';

function entryOf(name) {
  const entry = ENDPOINTS[name];
  if (!entry) {
    // 静的には ui_api_closure の C-3 が落とすが、実行時にも黙らせない。
    // カタログに無い名前で叩けることにすると、閉包が実行時に破れる。
    throw new Error(`ENDPOINTS に無い呼び出し先です: ${name}`);
  }
  return entry;
}

// `/api/director/tasks/{task_id}` の `{task_id}` を params から埋める。
// 足りなければ投げる。**空文字で埋めない** — 別のパスに化けて黙って通る。
function fillParams(path, params) {
  return path.replace(/\{(\w+)\}/g, (_match, key) => {
    const value = params && params[key];
    if (value === undefined || value === null || value === '') {
      throw new Error(`パスパラメータ ${key} が足りません: ${path}`);
    }
    return encodeURIComponent(String(value));
  });
}

function withQuery(path, query) {
  if (!query) return path;
  const pairs = Object.entries(query).filter(
    ([, value]) => value !== undefined && value !== null,
  );
  if (pairs.length === 0) return path;
  const qs = pairs
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join('&');
  return `${path}?${qs}`;
}

/** カタログの項目から絶対 URL を作る。src / href に渡す用。 */
export function apiUrl(name, { params, query } = {}) {
  const entry = entryOf(name);
  const origin = entry.method === 'WEBSOCKET' ? WS_ORIGIN : HTTP_ORIGIN;
  return origin + withQuery(fillParams(entry.path, params), query);
}

/**
 * カタログの項目を叩く。**メソッドはカタログが決める** — 呼び出し側は
 * 指定できない。指定できるようにすると、宣言と実際の呼び出しがずれる余地が戻る。
 *
 * body にオブジェクトを渡すと JSON にして Content-Type を付ける。
 * 文字列をそのまま送りたいときは呼び出し側で JSON.stringify しない。
 */
export function apiFetch(name, { params, query, body, headers, signal } = {}) {
  const entry = entryOf(name);
  if (entry.method === 'WEBSOCKET') {
    throw new Error(`${name} は WebSocket です。apiSocket を使ってください`);
  }
  const init = { method: entry.method };
  if (body !== undefined) {
    init.body = typeof body === 'string' ? body : JSON.stringify(body);
    init.headers = { 'Content-Type': 'application/json', ...(headers || {}) };
  } else if (headers) {
    init.headers = headers;
  }
  if (signal) init.signal = signal;
  return fetch(apiUrl(name, { params, query }), init);
}

/** 叩いて JSON にする。res.ok を見ない呼び出しが散らばるのを避ける。 */
export async function apiJson(name, options) {
  const res = await apiFetch(name, options);
  if (!res.ok) {
    throw new Error(`${name} が ${res.status} を返しました`);
  }
  return res.json();
}

/** WebSocket を開く。 */
export function apiSocket(name, { params, query } = {}) {
  const entry = entryOf(name);
  if (entry.method !== 'WEBSOCKET') {
    throw new Error(`${name} は WebSocket ではありません`);
  }
  return new WebSocket(apiUrl(name, { params, query }));
}

/** 別タブで開く。window.open を呼び出し側に書かせないための扉。 */
export function openApiUrl(name, { params, query, target = '_blank' } = {}) {
  return window.open(apiUrl(name, { params, query }), target);
}
