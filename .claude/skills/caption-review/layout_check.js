#!/usr/bin/env node
// 朱入れ画面（caption_review.html）が1画面に収まり、ボタンが動かないことを確かめる。
//
//   node .claude/skills/caption-review/layout_check.js <画面の控え review_captions.json> [幅x高さ,...]
//
// 画面の大きさを変えながら、短い字幕・2行の長い字幕・字幕の無い所・印の所だけ再生・要確認の送り（1枚目と11枚目）を
// 順に出し、次のどれかがあれば「PROBLEMS」と出して終了コード 1 で終わる:
//   ページがスクロールする / 物が画面の外にはみ出す / 「違和感あり」・動画・字幕の窓の位置か大きさが変わる /
//   字幕の窓で字が切れる / ボタンの帯が入りきらない / 送りの間にボタンが横にずれる
// 背の低い画面（高さ 480px 未満）はページごとスクロールする作りなので対象にしない。
//
// 要るもの: Playwright（npm の global）・ffmpeg。動画は H.264 を読めない Chromium でも再生できるよう、
// 控えの長さに合わせた灰色の動画（VP8）を作って使う。Google Fonts は curl で取れれば使い、取れなければ手元の字体で測る。
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const { execFile, execFileSync } = require("child_process");

const SHEET = process.argv[2];
const SIZES = (process.argv[3] || "950x700,1180x870,1280x720,1536x864,1920x1080,760x600,700x700,640x600,600x700,"
  + "1080x1600,390x844,360x740,320x640,950x520").split(",").map((s) => s.split("x").map(Number));
if (!SHEET) { console.error("使い方: node layout_check.js <review_captions.json> [幅x高さ,...]"); process.exit(2); }
const { chromium } = require(path.join(execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim(), "playwright"));
const PAGE = path.join(__dirname, "caption_review.html");

// 画面が読む共有フォルダ・db・利用者を、手元の物に差し替える
const STUB = `<script>
(() => {
  const DIR = "outputs/test";
  const cache = {};
  const get = (p) => cache[p] || (cache[p] = fetch(p.endsWith(".json") ? "/f/sheet" : "/f/video").then((r) => r.arrayBuffer()));
  const files = {
    // どの収録を選んでいても見つかるように、動画の名前を両方並べる
    list: async () => ({ entries: [{ path: DIR + "/raw4_concat_preview_360p.mp4", isDirectory: false },
                                   { path: DIR + "/full360.mp4", isDirectory: false },
                                   { path: DIR + "/review_captions.json", isDirectory: false }] }),
    read: async (p, o) => { const buf = await get(p); const off = o.offset || 0, len = Math.min(o.length, buf.byteLength - off);
      return { bytes: new Uint8Array(buf.slice(off, off + len)), size: buf.byteLength, revision: "r1" }; },
  };
  const store = new Map(), subs = [];
  const emit = () => { const docs = Array.from(store, ([id, d]) => ({ id, exists: true, data: () => Object.assign({}, d) }));
    subs.forEach((fn) => fn({ docs })); };
  const db = { collection: () => ({
    doc: (id) => ({ set: async (d) => { store.set(id, Object.assign({}, d)); setTimeout(emit, 20); },
                    update: async (p) => { store.set(id, Object.assign({}, store.get(id), p)); setTimeout(emit, 20); },
                    delete: async () => { store.delete(id); setTimeout(emit, 20); } }),
    onSnapshot: (fn) => { subs.push(fn); setTimeout(emit, 20); return () => {}; } }) };
  const user = { id: async () => "u-test", can: async () => true };
  window.claude = { use: async (name) => ({ files, db, user })[name] || null };
})();
</script>`;
// Artifact の公開時に付く骨組み（文字コード・viewport・小さな reset）と同じもので包む
const SKELETON = '<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">'
  + "<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)}"
  + "body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style></head><body>";

const metrics = () => {
  const r = (sel) => { const e = document.querySelector(sel); if (!e || !e.getClientRects().length) return null;
    const b = e.getBoundingClientRect(); return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height),
      b: Math.round(b.bottom), r: Math.round(b.right) }; };
  const se = document.scrollingElement, nt = document.getElementById("nowText"), ac = document.querySelector(".actions");
  const parts = { top: r(".top"), screen: r(".screen"), strip: r(".strip"), actions: r(".actions"), mark: r("#markBtn"),
    last: r("#reel:not([hidden]) #reelStop") || r("#reelBtn"), now: r("#now"), ledger: r(".ledger"), foot: r(".ledger .foot") };
  const outside = Object.entries(parts).filter(([, v]) => v && (v.b > innerHeight + 0.5 || v.r > innerWidth + 0.5 || v.x < -0.5 || v.y < -0.5))
    .map(([k]) => k);
  return { vw: innerWidth, vh: innerHeight, sh: se.scrollHeight, sw: se.scrollWidth, ...parts, outside,
    textOver: nt.scrollHeight - nt.clientHeight, actOver: ac.scrollWidth - ac.clientWidth };
};
const reelRects = () => ["markBtn", "reelPrev", "reelAgain", "reelNext", "reelStop"].map((id) => {
  const b = document.getElementById(id).getBoundingClientRect(); return [Math.round(b.x), Math.round(b.y), Math.round(b.width)].join(",");
}).join(" ");

const fetchViaCurl = (() => {
  const cache = new Map();
  return (url) => cache.get(url) || cache.set(url, new Promise((res, rej) => execFile("curl", ["-sS", "--max-time", "30", "-A",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36", url],
    { encoding: "buffer", maxBuffer: 64 << 20 }, (e, out) => (e ? rej(e) : res(out))))).get(url);
})();

(async () => {
  const sheet = JSON.parse(fs.readFileSync(SHEET, "utf8"));
  const caps = sheet.captions || [];
  if (!caps.length) throw new Error("字幕が入っていない控えです: " + SHEET);
  const flat = (t) => t.replace(/\n/g, "");
  const longest = caps.slice().sort((a, b) => flat(b.t).length - flat(a.t).length)[0];
  const second = caps.filter((c) => c !== longest && c.t.includes("\n")).sort((a, b) => flat(b.t).length - flat(a.t).length)[0] || caps[1];
  const k = caps.findIndex((c, i) => caps[i + 1] && caps[i + 1].s - c.e > 0.4);
  const gapT = k >= 0 ? caps[k].e + 0.2 : null;

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "caption-layout-"));
  const video = path.join(tmp, "video.webm");
  execFileSync("ffmpeg", ["-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=1",
    "-t", String(Math.ceil(sheet.duration || caps[caps.length - 1].e + 1)), "-c:v", "libvpx", "-b:v", "20k", "-g", "4", video]);
  const html = SKELETON + STUB + fs.readFileSync(PAGE, "utf8") + "</body></html>";
  const server = http.createServer((req, res) => {
    const body = req.url === "/" ? html : req.url === "/f/video" ? fs.readFileSync(video) : req.url === "/f/sheet" ? fs.readFileSync(SHEET) : null;
    if (body == null) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { "content-type": req.url === "/" ? "text/html; charset=utf-8" : "application/octet-stream" });
    res.end(body);
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const URL = "http://127.0.0.1:" + server.address().port + "/";

  const browser = await chromium.launch();
  const failed = [];
  for (const [w, h] of SIZES) {
    const tag = w + "x" + h;
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    await ctx.route(/^https?:\/\/(?!127\.0\.0\.1)/, (route) => route.abort());  // 外へは出ない（字体だけ下で curl から渡す）
    await ctx.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, async (route) => {
      const url = route.request().url();
      try { await route.fulfill({ status: 200, body: await fetchViaCurl(url), headers: { "access-control-allow-origin": "*" },
        contentType: url.includes("googleapis") ? "text/css; charset=utf-8" : "font/woff2" }); } catch (_) { await route.abort(); }
    });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(URL);
    await page.waitForFunction(() => document.getElementById("loader").hidden && document.getElementById("video").readyState >= 1,
      null, { timeout: 60000 });
    await page.evaluate(() => document.fonts.ready);
    const seek = (t) => page.evaluate((t) => new Promise((res) => { const v = document.getElementById("video");
      v.addEventListener("seeked", () => setTimeout(res, 80), { once: true }); v.currentTime = t; }), t);
    const states = {};
    await seek(caps[0].s + 0.1); states["短い字幕"] = await page.evaluate(metrics);
    await seek(longest.s + 0.1); states["長い字幕"] = await page.evaluate(metrics);
    await page.keyboard.press("m");
    await seek(second.s + 0.1); states["長い字幕2"] = await page.evaluate(metrics);
    await page.keyboard.press("m");
    if (gapT != null) { await seek(gapT); states["字幕なし"] = await page.evaluate(metrics); }
    await page.click("#reelBtn");
    await page.waitForTimeout(300);
    await page.evaluate(() => document.getElementById("video").pause());
    states["印の所だけ再生"] = await page.evaluate(metrics);
    await page.click("#reelStop");
    states["再生をやめた後"] = await page.evaluate(metrics);
    const problems = [];
    if ((sheet.flags || []).length >= 11) {
      await page.click("#tabFlags");
      await page.click(".flag-lead button");
      await page.waitForTimeout(300);
      const first = await page.evaluate(reelRects);
      for (let n = 0; n < 10; n++) { await page.click("#reelNext"); await page.waitForTimeout(40); }
      await page.evaluate(() => document.getElementById("video").pause());
      if (first !== await page.evaluate(reelRects)) problems.push("要確認の送り: 1枚目と11枚目でボタンが横にずれた");
      states["要確認の送り"] = await page.evaluate(metrics);
      await page.click("#reelStop");
    }
    const base = states["短い字幕"];
    const same = (a, b) => a && b && a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
    for (const [name, s] of Object.entries(states)) {
      if (s.sh > s.vh || s.sw > s.vw) problems.push(`${name}: ページがスクロールする（${s.sw}x${s.sh}）`);
      if (s.outside.length) problems.push(`${name}: 画面の外にはみ出す（${s.outside.join("・")}）`);
      if (!same(s.mark, base.mark)) problems.push(`${name}: 「違和感あり」が動いた ${JSON.stringify(base.mark)} → ${JSON.stringify(s.mark)}`);
      if (!same(s.now, base.now)) problems.push(`${name}: 字幕の窓が動いたか大きさが変わった`);
      if (!same(s.screen, base.screen)) problems.push(`${name}: 動画が動いたか大きさが変わった`);
      if (s.textOver > 0) problems.push(`${name}: 字幕の窓で字が ${s.textOver}px 切れる`);
      if (s.actOver > 0) problems.push(`${name}: ボタンの帯に ${s.actOver}px 入りきらない`);
    }
    problems.push(...errors.map((e) => "画面の中のエラー: " + e));
    console.log(`${tag}: 動画 ${base.screen.w}x${base.screen.h} · 字幕の窓 ${base.now.h}px · 控え ${base.ledger.w}x${base.ledger.h}`
      + ` · 違和感あり ${base.mark.x},${base.mark.y} … ${problems.length ? "PROBLEMS\n  " + problems.join("\n  ") : "OK"}`);
    if (problems.length) failed.push(tag);
    await ctx.close();
  }
  await browser.close();
  server.close();
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(failed.length ? "収まらない大きさ: " + failed.join(" ") : `${SIZES.length} 通りの大きさで、すべて1画面に収まりボタンは動かなかった`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
