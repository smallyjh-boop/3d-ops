// 测试用（t_curate_queue.py 调用）：在无头 Chromium 里装上真的 ERP 扩展，跑选品的后台循环（cur_bg.js）。
// 本机起一个假 ERP（/api/v1/curate/ext/… 领活接口，节奏缩小：同一网站两次领活隔 0.3–0.6 秒、同时 2 个）+ 假模型网站（详情页、模型文件）。
// 检查：全部详情页读完、文件上传完；详情页 / 下载各自同时 2 个；不用等每分钟的闹钟；下载报进度；
//       一个永远打不开的详情页和一个卡住不给数据的文件不会卡住整个循环（到时限交回，服务器再排一次就成功）。
// 用法：node queue_ext_check.js <扩展目录>   输出最后一行 JSON
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright");

const N_DETAIL = 8, N_FILES = 8, CONC = 2;
const st = { details: 0, files: 0, progress: 0, run: { detail: 0, file: 0 }, max: { detail: 0, file: 0 }, tries: {}, stuckRetried: { detail: false, file: false } };
const queue = { detail: [], file: [] };
for (let i = 1; i <= N_DETAIL; i++) queue.detail.push({ id: i, n: i });
for (let i = 1; i <= N_FILES; i++) queue.file.push({ id: 100 + i, n: i });
const nextAt = { detail: 0, file: 0 };
const running = { detail: new Set(), file: new Set() };
let port = 0;
const gap = () => 300 + Math.random() * 300;
const send = (res, code, obj, type = "application/json") => { res.writeHead(code, { "Content-Type": type, "Access-Control-Allow-Origin": "*" }); res.end(typeof obj === "string" ? obj : JSON.stringify(obj)); };
const body = (req) => new Promise((r) => { const parts = []; req.on("data", (c) => parts.push(c)); req.on("end", () => r(Buffer.concat(parts))); });

function claim(lane) {
  if (!queue[lane].length) return { wait: 0 };
  if (running[lane].size >= CONC) return { wait: 1 };
  if (Date.now() < nextAt[lane]) return { wait: 1 };
  const job = queue[lane].shift();
  running[lane].add(job.id);
  st.max[lane] = Math.max(st.max[lane], running[lane].size);
  nextAt[lane] = Date.now() + gap();
  st.tries[job.id] = (st.tries[job.id] || 0) + 1;
  return { job };
}
function finish(lane, id, okDone) {
  running[lane].delete(id);
  if (okDone) return;
  queue[lane].push({ id, n: lane === "detail" ? id : id - 100 });     // 失败 / 超时：再排一次（像 ERP 那样）
}

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, "http://x");
  const p = u.pathname;
  // ---- 假 ERP ----
  if (p === "/api/v1/curate/ext/sites") return send(res, 200, { ok: true, version: "t1", sites: [{ id: "fk", name: "Fake", key_prefix: "fk", domains: ["127.0.0.1"], detail: { path: "(/model/(\\d+))" }, extract: {} }] });
  if (p === "/api/v1/curate/ext/next") {
    const r = claim("detail");
    return send(res, 200, r.job ? { ok: true, item: { id: r.job.id, url: `http://127.0.0.1:${port}/model/${r.job.n}`, title: "" }, conc: CONC } : { ok: true, item: null, wait: r.wait });
  }
  if (p === "/api/v1/curate/ext/result") {
    const b = JSON.parse((await body(req)).toString() || "{}");
    const good = !!(b.data && b.data.title);
    if (good) st.details++;
    else if (b.id === 7) st.stuckRetried.detail = true;
    finish("detail", b.id, good);
    return send(res, 200, { ok: true });
  }
  if (p === "/api/v1/curate/ext/files/next") {
    const r = claim("file");
    return send(res, 200, r.job ? { ok: true, product: "P1", files: [{ id: r.job.id, url: `http://127.0.0.1:${port}/files/${r.job.id}.stl`, name: `f${r.job.id}.stl` }], conc: CONC }
      : { ok: true, product: null, files: [], wait: r.wait });
  }
  let m;
  if ((m = p.match(/^\/api\/v1\/curate\/ext\/files\/(\d+)\/progress$/))) { await body(req); st.progress++; return send(res, 200, { ok: true, cancel: false }); }
  if ((m = p.match(/^\/api\/v1\/curate\/ext\/files\/(\d+)\/upload$/))) {
    const data = await body(req);
    if (data.length > 1000) st.files++;
    finish("file", +m[1], data.length > 1000);
    return send(res, 200, { ok: true, bytes: data.length });
  }
  if ((m = p.match(/^\/api\/v1\/curate\/ext\/files\/(\d+)\/fail$/))) {
    await body(req);
    if (+m[1] === 105) st.stuckRetried.file = true;
    finish("file", +m[1], false);
    return send(res, 200, { ok: true, kind: "other", stop: false });
  }
  if (p.startsWith("/api/v1/curate/ext/watch/next")) return send(res, 200, { ok: true, watch: null });
  if (p.startsWith("/api/v1/curate/ext/")) return send(res, 200, { ok: true });
  // ---- 假模型网站 ----
  if ((m = p.match(/^\/model\/(\d+)$/))) {
    if (+m[1] === 7 && st.tries[7] === 1) return;                   // 第一次：永远不回（扩展到时限交回超时）
    return setTimeout(() => send(res, 200, `<!doctype html><html><head><title>Model ${m[1]}</title><meta property="og:image" content="https://example.com/m${m[1]}.jpg"></head>
      <body><main><h1>Fake model ${m[1]}</h1><p>Description</p><a href="/files/${m[1]}.stl">part.stl</a></main></body></html>`, "text/html"), 300);
  }
  if ((m = p.match(/^\/files\/(\d+)\.stl$/))) {
    if (+m[1] === 105 && st.tries[105] === 1) { res.writeHead(200, { "Content-Type": "application/octet-stream", "Content-Length": "50000" }); res.write(Buffer.alloc(100, 49)); return; }   // 第一次：给一点就卡住
    res.writeHead(200, { "Content-Type": "application/octet-stream", "Content-Length": String(60000) });
    let k = 0;
    const t = setInterval(() => { res.write(Buffer.alloc(10000, 48)); if (++k === 6) { clearInterval(t); res.end(); } }, 150);
    return;
  }
  send(res, 404, "not found", "text/plain");
});

(async () => {
  const [extDir] = process.argv.slice(2);
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  port = server.address().port;
  const prof = fs.mkdtempSync(path.join(os.tmpdir(), "curq-"));
  let ctx;
  try {
    ctx = await chromium.launchPersistentContext(prof, { channel: "chromium", headless: true, args: [`--disable-extensions-except=${extDir}`, `--load-extension=${extDir}`] });
  } catch (e) {
    process.stdout.write(JSON.stringify({ skip: "cannot load extension in headless Chromium: " + String(e.message || e).slice(0, 200) }) + "\n");
    server.close(); return;
  }
  try {
    let [sw] = ctx.serviceWorkers();
    if (!sw) sw = await ctx.waitForEvent("serviceworker", { timeout: 20000 });
    await sw.evaluate(async (base) => {
      await chrome.storage.sync.set({ server: base, key: "k" });
      await chrome.storage.local.set({ curAuto: true, curTiming: { detailMax: 8000, stall: 3000, tabLoad: 4000, api: 10000 } });
    }, `http://127.0.0.1:${port}`);
    const t0 = Date.now();
    await sw.evaluate(() => curTick());
    const budget = 40;              // 以前一分钟只做一件：8 个详情页 + 8 个文件要十几分钟
    while (Date.now() - t0 < budget * 1000 && (st.details < N_DETAIL || st.files < N_FILES)) await new Promise((r) => setTimeout(r, 200));
    const secs = Math.round((Date.now() - t0) / 100) / 10;
    process.stdout.write(JSON.stringify({ details: st.details, want_details: N_DETAIL, files: st.files, want_files: N_FILES, max_detail: st.max.detail, max_file: st.max.file,
      progress: st.progress, secs, budget, stuck_retried: st.stuckRetried.detail && st.stuckRetried.file }) + "\n");
  } finally { await ctx.close(); server.close(); fs.rmSync(prof, { recursive: true, force: true }); }
})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
