// 选品 · 扩展后台（3.1，从「3D选品工具」扩展的 background.js 搬过来；background.js 用 importScripts 载入，callApi / cfg 共用）。
// 都走 ERP 的 /api/v1/curate/ext/…（员工的扩展密钥，和 AI 客服、运营采集同一把）：
//   · 模型网站页面上的推荐分、「＋采集」（cur_picker.js 发 cur-* 消息到这里）
//   · 采集队列：ERP 说哪个详情页该读了，就在后台标签页打开、读（cur_extract.js）、交回、关掉
//   · 模型文件下载：用浏览器里原站的登录状态下载（credentials: include），再上传到 ERP（直接进产品的模型库）
//   · 关注巡逻：ERP 说哪个列表页该看了，就在后台标签页打开、往下翻几屏、读卡片、交回
// 节奏由 ERP 定（页面 / 文件之间随机等几秒、每个网站同时几个、每小时 / 每天上限、遇到人机验证 / 429 整个网站暂停），扩展只照做。
// 3.1.2：有活就一直做（详情页、文件两条线并行，每件活有时限，下载边下边报进度），没活了才停下等每分钟的闹钟。
// 站点规则（站点包）每 10 分钟从 ERP 拿一次（版本变了才换），不用升级扩展。
const CUR_EXTRACT = ["cur_sites_builtin.js", "cur_sites.js", "cur_extract.js"];
let curSitesAt = 0, curBusy = false;

async function curOn() {
  const s = await chrome.storage.local.get({ curAuto: true });
  return s.curAuto !== false;
}
async function curRefreshSites(force) {
  if (!force && Date.now() - curSitesAt < 10 * 60 * 1000) return;
  try {
    const r = await curApi("/api/v1/curate/ext/sites");
    curSitesAt = Date.now();                                    // 没连上（还没设置 ERP 地址）就下次再试，不等 10 分钟
    const { curSiteRules } = await chrome.storage.local.get("curSiteRules");
    if (r && r.sites && (!curSiteRules || r.version !== curSiteRules.version)) await chrome.storage.local.set({ curSiteRules: { version: r.version, sites: r.sites, at: Date.now() } });
  } catch (e) { /* 没连上 ERP：用内置规则 */ }
  await curRegisterSites().catch(() => {});
}
// 站点包里新加的网站（不在 manifest 里写死的）：动态登记内容脚本（扩展有 <all_urls> 权限，不用再授权）
async function curRegisterSites() {
  const fixed = ["makerworld.com", "makerworld.com.cn", "printables.com", "thingiverse.com"];
  const sites = await CuratorSites.load();
  const matches = [];
  for (const s of sites) {
    if (s.enabled === false) continue;
    for (const d of s.domains || []) if (!fixed.includes(d)) matches.push(`https://${d}/*`, `https://*.${d}/*`);
  }
  try { await chrome.scripting.unregisterContentScripts({ ids: ["cur-sites"] }); } catch (e) { /* 没登记过 */ }
  if (matches.length) {
    await chrome.scripting.registerContentScripts([{ id: "cur-sites", matches, js: ["cur_sites_builtin.js", "cur_sites.js", "cur_extract.js", "cur_picker.js"], runAt: "document_idle", persistAcrossSessions: true }]);
  }
}

const curSleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 等待时每 20 秒碰一下扩展接口，防止 Chrome 把后台当成空闲关掉
async function curSleepAlive(ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    await curSleep(Math.min(20000, end - Date.now()));
    try { await chrome.runtime.getPlatformInfo(); } catch (e) { /* 忽略 */ }
  }
}
function curWaitTab(tabId, ms) {
  return new Promise((resolve) => {
    const done = () => { chrome.tabs.onUpdated.removeListener(fn); clearTimeout(t); resolve(); };
    const fn = (id, info) => { if (id === tabId && info.status === "complete") done(); };
    const t = setTimeout(done, ms);
    chrome.tabs.onUpdated.addListener(fn);
    chrome.tabs.get(tabId).then((tab) => { if (tab.status === "complete") done(); }).catch(done);
  });
}
async function curPageText(tabId, url) {
  const [{ result: page } = {}] = await chrome.scripting.executeScript({ target: { tabId }, func: () => ({ text: (document.body && document.body.innerText || "").slice(0, 1500), url: location.href }) }).catch(() => [{}]);
  return { snippet: (page && page.text) || "", url: (page && page.url) || url };
}

// 时限（毫秒）。测试（modules/curate/tests/queue_ext_check.js）可以用 chrome.storage.local.curTiming 改小
const CUR_T = { api: 45000, detailMax: 150000, stall: 120000, tabLoad: 60000 };
async function curLoadTiming() {
  try { const { curTiming } = await chrome.storage.local.get("curTiming"); if (curTiming && typeof curTiming === "object") Object.assign(CUR_T, curTiming); } catch (e) { /* 忽略 */ }
}
// 扩展接口加个时限：ERP 没回话（只有一个地址时 callApi 不限时）不能把整个后台卡住
function curApi(path, body, ms) {
  ms = ms || CUR_T.api;
  let t;
  return Promise.race([callApi(path, body).finally(() => clearTimeout(t)),
    new Promise((_, rej) => { t = setTimeout(() => rej(new Error("ERP 没有回应（超时）")), ms); })]);
}
// 一件活最多做多久（读详情页：打开、等加载、读，最多 2.5 分钟；到时间关掉标签页、交回「超时」）
function curWithin(ms, fn, onTimeout) {
  let t;
  return Promise.race([Promise.resolve().then(fn).finally(() => clearTimeout(t)),
    new Promise((resolve) => { t = setTimeout(() => resolve(onTimeout()), ms); })]);
}

// ---------------- 采集队列：读详情页 ----------------
async function curCollectOne(item) {
  const ctl = { tabId: 0, done: false };
  const result = await curWithin(CUR_T.detailMax, () => curReadDetail(item, ctl), () => ({ id: item.id, error: "读取超时（页面一直没加载完）", timeout: true }));
  ctl.done = true;
  if (ctl.tabId) chrome.tabs.remove(ctl.tabId).catch(() => {});
  await curApi("/api/v1/curate/ext/result", result).catch(() => {});
}
async function curReadDetail(item, ctl) {
  const result = { id: item.id };
  try {
    const u = new URL(item.url); u.searchParams.set("cur_collect", "1");
    const tab = await chrome.tabs.create({ url: u.href, active: false });
    ctl.tabId = tab.id;
    const tabId = tab.id;
    await curWaitTab(tabId, CUR_T.tabLoad);
    await curSleepAlive(1500);
    let data = null, last = null;
    for (let i = 0; i < 6 && !data && !ctl.done; i++) {
      const [{ result: d } = {}] = await chrome.scripting.executeScript({ target: { tabId }, func: async () => {
        if (!window.__modelCatalogExtract) return { err: "noextract" };
        try { return await window.__modelCatalogExtract({}); } catch (e) { return { err: String((e && e.message) || e) }; }
      } }).catch((err) => [{ result: { err: String((err && err.message) || err) } }]);
      if (d && d.err === "noextract") { await chrome.scripting.executeScript({ target: { tabId }, files: CUR_EXTRACT }).catch(() => {}); continue; }
      if (d && d.title && (d.image_urls || []).length) data = d;
      else { last = d; if (i < 5) await curSleepAlive(i < 2 ? 1500 : 3000); }
    }
    if (!data && last && last.title) data = last;
    if (data) result.data = data;
    else Object.assign(result, { error: "页面上没读到产品信息（可能要登录、验证，或页面没加载完）" }, await curPageText(tabId, item.url));
  } catch (err) {
    result.error = String((err && err.message) || err);
  }
  return result;
}

// ---------------- 模型文件：用浏览器的登录状态下载，上传到 ERP ----------------
const CUR_FILE_RE = /\.(3mf|stl|step|stp|obj|zip|gcode|f3d|scad)(\?|$)/i;
function curFindFileUrl(obj, depth = 0) {
  if (!obj || depth > 6) return "";
  if (typeof obj === "string") return /^https?:\/\//.test(obj) && (CUR_FILE_RE.test(obj) || /download|file/i.test(obj)) ? obj : "";
  if (Array.isArray(obj)) { for (const v of obj) { const r = curFindFileUrl(v, depth + 1); if (r) return r; } return ""; }
  if (typeof obj === "object") {
    for (const k of ["url", "downloadUrl", "download_url", "link", "fileUrl"]) if (typeof obj[k] === "string" && /^https?:\/\//.test(obj[k])) return obj[k];
    for (const v of Object.values(obj)) { const r = curFindFileUrl(v, depth + 1); if (r) return r; }
  }
  return "";
}
function curNameFrom(resp, fallback) {
  const cd = resp.headers.get("content-disposition") || "";
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) { try { return decodeURIComponent(star[1]); } catch (e) { /* 忽略 */ } }
  const plain = cd.match(/filename="?([^";]+)"?/i);
  if (plain) return plain[1];
  try { const last = new URL(resp.url).pathname.split("/").pop(); if (CUR_FILE_RE.test(last)) return decodeURIComponent(last); } catch (e) { /* 忽略 */ }
  return fallback;
}
// 边下载边报进度（也是心跳）：ERP 说这个任务已经删掉 / 取消了就停下
async function curReadBody(resp, fid, ac) {
  const total = +(resp.headers.get("content-length") || 0);
  if (!resp.body || !resp.body.getReader) return resp.blob();
  const reader = resp.body.getReader();
  const parts = [];
  let got = 0, lastBeat = 0, stall = null;
  const arm = () => { clearTimeout(stall); stall = setTimeout(() => ac.abort(), CUR_T.stall); };
  arm();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parts.push(value); got += value.length; arm();
      if (Date.now() - lastBeat > 4000) {
        lastBeat = Date.now();
        const r = await curApi(`/api/v1/curate/ext/files/${fid}/progress`, { got, total }, 15000).catch(() => null);
        if (r && r.cancel) { ac.abort(); const e = new Error("任务已取消"); e.canceled = true; throw e; }
      }
    }
  } finally { clearTimeout(stall); }
  return new Blob(parts, { type: resp.headers.get("content-type") || "application/octet-stream" });
}
async function curFetchFile(url, fid) {
  const sites = await CuratorSites.load();
  const site = CuratorSites.siteForHost(sites, new URL(url).hostname);
  if (!site) throw new Error("只下载站点包里登记的模型网站的文件");
  const ac = new AbortController();
  url = await CuratorSites.resolveDownload(site, url);          // 有的网站要先换真实下载地址（规则在站点包 download 里）
  const first = setTimeout(() => ac.abort(), CUR_T.stall);      // 原站 2 分钟都没开始回话
  let resp, type;
  try {
    resp = await fetch(url, { credentials: "include", redirect: "follow", signal: ac.signal });
    type = (resp.headers.get("content-type") || "").toLowerCase();
    if (resp.ok && type.includes("json")) {
      const next = curFindFileUrl(await resp.json());
      if (!next) throw new Error("原站没有返回下载地址（可能需要登录或验证）");
      const same = sites.some((s) => CuratorSites.hostIn(new URL(next).hostname, [...(s.domains || []), ...(s.related_hosts || [])]));
      resp = await fetch(next, { credentials: same ? "include" : "omit", redirect: "follow", signal: ac.signal });
      type = (resp.headers.get("content-type") || "").toLowerCase();
    }
  } catch (e) {
    if (ac.signal.aborted) throw new Error("原站一直没有回应（超时）");
    throw e;
  } finally { clearTimeout(first); }
  const fail = async (message) => {
    const err = new Error(message); err.status = resp.status; err.url = resp.url;
    try { err.snippet = (await resp.text()).replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").slice(0, 2000); } catch (e) { /* 忽略 */ }
    throw err;
  };
  if (resp.status === 401 || resp.status === 403) await fail(`原站拒绝下载（HTTP ${resp.status}）`);
  if (!resp.ok) await fail(`原站返回 HTTP ${resp.status}`);
  if (type.includes("text/html")) await fail("原站返回的是网页，不是文件");
  let blob;
  try { blob = await curReadBody(resp, fid, ac); } catch (e) {
    if (e.canceled) throw e;
    if (ac.signal.aborted) throw new Error("下载卡住了（2 分钟没有收到数据）");
    throw e;
  }
  if (blob.size < 64) throw new Error("下载到的文件是空的");
  return { blob, resp };
}
async function curUpload(fid, name, blob) {
  const c = await cfg();
  let last = null;
  for (const s of c.servers) {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), 10 * 60 * 1000);
    try {
      const r = await fetch(`${s}/api/v1/curate/ext/files/${fid}/upload?name=${encodeURIComponent(name)}`, { method: "POST", body: blob, signal: ac.signal,
        headers: { "Content-Type": "application/octet-stream", Authorization: "Bearer " + c.key, "X-Ext-Version": chrome.runtime.getManifest().version } });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || d.ok === false) throw new Error(d.error || `HTTP ${r.status}`);
      return d;
    } catch (e) { last = e; } finally { clearTimeout(t); }
  }
  throw last || new Error("NO_CONFIG");
}
async function curDownloadOne(f) {
  try {
    const { blob, resp } = await curFetchFile(f.url, f.id);
    await curUpload(f.id, curNameFrom(resp, f.name), blob);
  } catch (err) {
    if (err && err.canceled) return;                         // ERP 那边删掉了这个下载：不用报
    await curApi(`/api/v1/curate/ext/files/${f.id}/fail`, { error: String((err && err.message) || err), status: (err && err.status) || 0,
      url: (err && err.url) || f.url, snippet: (err && err.snippet) || "" }).catch(() => ({}));
  }
}

// ---------------- 关注巡逻：读列表页 ----------------
async function curWatchOnce() {
  const r = await curApi("/api/v1/curate/ext/watch/next").catch(() => null);
  if (!r || !r.watch) return false;
  const w = r.watch;
  let tabId = 0;
  const result = { id: w.id };
  try {
    const u = new URL(w.url); u.searchParams.set("cur_watch", "1");
    const tab = await chrome.tabs.create({ url: u.href, active: false });
    tabId = tab.id;
    await curWaitTab(tabId, 60000);
    await curSleepAlive(3000);
    let got = null;
    for (let i = 0; i < 4 && !(got && (got.items || []).length); i++) {
      const [{ result: d } = {}] = await chrome.scripting.executeScript({ target: { tabId }, func: async (n) => {
        if (!window.__curatorCards) return { err: "nopicker" };
        try { return await window.__curatorCards(n); } catch (e) { return { err: String((e && e.message) || e) }; }
      }, args: [w.scrolls || 1] }).catch((err) => [{ result: { err: String((err && err.message) || err) } }]);
      got = d;
      if (!(d && (d.items || []).length)) {
        if (d && d.err === "nopicker") await chrome.scripting.executeScript({ target: { tabId }, files: ["cur_sites_builtin.js", "cur_sites.js", "cur_picker.js"] }).catch(() => {});
        await curSleepAlive(3000);
      }
    }
    if (got && (got.items || []).length) result.items = got.items;
    else Object.assign(result, { error: got && got.err && got.err !== "nopicker" ? got.err : "列表页上没读到模型（可能要登录、验证，或页面没加载完）",
      snippet: (got && got.snippet) || "", url: (got && got.url) || w.url });
  } catch (err) {
    result.error = String((err && err.message) || err);
  } finally {
    if (tabId) chrome.tabs.remove(tabId).catch(() => {});
  }
  await curApi("/api/v1/curate/ext/watch/result", result).catch(() => {});
  return true;
}

// ---------------- 后台循环（3.1.2）：有活就一直做，两条线并行 ----------------
// 详情页一条线、文件一条线，各自向 ERP 领活；ERP 按每个网站的节奏（间隔几秒、同时几个、每小时上限、风控暂停）决定给不给，
// 不给时告诉我们多少秒后再来（wait）。一件活做完马上叫醒循环再领。都没活了就停下，等闹钟（每分钟）或页面上点「＋采集」再叫醒。
// 以前：每分钟闹钟一次、一次只做一件、等节奏时整个循环睡着，文件下载要等所有详情页读完。
const CUR_LANES = { detail: { run: 0, max: 4, until: 0 }, file: { run: 0, max: 4, until: 0 } };
const CUR_HARD_MAX = 6;               // 一条线最多同时几件（每个网站的上限由 ERP 管）
let curLoopGen = 0, curLoopBeat = 0, curWake = null, curWatchAt = 0;
function curKickLoop() { if (curWake) { const w = curWake; curWake = null; w(); } }
// 睡一会儿（每 20 秒碰一下扩展接口，防止 Chrome 把后台当成空闲关掉）；有活做完会被提前叫醒
async function curNap(ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const woke = await new Promise((resolve) => {
      const t = setTimeout(() => { curWake = null; resolve(false); }, Math.min(20000, end - Date.now()));
      curWake = () => { clearTimeout(t); resolve(true); };
    });
    if (woke) return;
    try { await chrome.runtime.getPlatformInfo(); } catch (e) { /* 忽略 */ }
  }
}
async function curClaim(lane) {
  const L = CUR_LANES[lane];
  const r = await curApi(lane === "detail" ? "/api/v1/curate/ext/next" : "/api/v1/curate/ext/files/next?v=2", null, 30000);
  const job = lane === "detail" ? r && r.item : r && r.product && (r.files || [])[0];
  if (r && r.conc) L.max = Math.min(CUR_HARD_MAX, Math.max(2, r.conc * 2));
  if (!job) return { job: null, wait: r && r.wait > 0 ? r.wait * 1000 : 60000 };
  L.run++;
  const work = lane === "detail" ? curCollectOne(job) : curDownloadOne(job);
  // 做完一件：两条线都马上再问（读完详情页会多出要下载的文件；失败的会被 ERP 重新排队）
  work.catch(() => {}).finally(() => { L.run--; for (const x of Object.values(CUR_LANES)) x.until = 0; curKickLoop(); });
  return { job, wait: 0 };
}
async function curLoop() {
  if (curLoopGen && Date.now() - curLoopBeat < 5 * 60 * 1000) { curKickLoop(); return; }   // 已经在跑：叫醒它
  const gen = ++curLoopGen;                       // 上一个循环 5 分钟没动静（卡住了）：换一个新的，旧的看到 gen 变了自己退出
  curBusy = true;
  try {
    await curLoadTiming();
    await curRefreshSites(false).catch(() => {});
    while (gen === curLoopGen && (await curOn())) {
      curLoopBeat = Date.now();
      let started = 0, wait = 60000;
      for (const lane of ["detail", "file"]) {
        const L = CUR_LANES[lane];
        if (L.run >= L.max) continue;
        if (L.until > Date.now()) { wait = Math.min(wait, L.until - Date.now()); continue; }
        try {
          const r = await curClaim(lane);
          if (r.job) { started++; L.until = 0; } else { L.until = Date.now() + Math.min(r.wait, 60000); wait = Math.min(wait, r.wait); }
        } catch (e) { L.until = Date.now() + 30000; wait = Math.min(wait, 30000); }
      }
      const running = CUR_LANES.detail.run + CUR_LANES.file.run;
      if (started) { await curSleep(300); continue; }                 // 领到了：马上再问（ERP 按节奏决定给不给）
      if (!running && Date.now() > curWatchAt) {                       // 两条线都空着：巡逻一页（ERP 管间隔）
        curWatchAt = Date.now() + 60000;
        if (await curWatchOnce().catch(() => false)) continue;
      }
      if (!running && wait >= 60000) break;                            // 没活了：等闹钟 / 「＋采集」叫醒
      await curNap(Math.max(500, Math.min(wait, 60000)));
    }
  } finally { if (gen === curLoopGen) { curBusy = false; curLoopGen = 0; } }
}
// 闹钟（每分钟）和页面消息：叫醒循环（新活来了：两条线的等待清零）
function curTick() {
  curOn().then((on) => {
    if (!on) return;
    for (const L of Object.values(CUR_LANES)) L.until = 0;
    curLoop();
  }).catch(() => {});
}

chrome.alarms.create("cur-tick", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "cur-tick") curTick(); });
chrome.runtime.onStartup.addListener(() => { curRefreshSites(true); curTick(); });
chrome.runtime.onInstalled.addListener(() => { curRefreshSites(true); curTick(); });

// ---------------- 页面（cur_picker.js）和弹窗发来的消息 ----------------
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || typeof msg.type !== "string" || !msg.type.startsWith("cur-")) return false;
  (async () => {
    try {
      let data;
      if (msg.type === "cur-score") data = await callApi("/api/v1/curate/ext/score", { items: msg.items || [] });
      else if (msg.type === "cur-status") data = await callApi("/api/v1/curate/ext/status", { urls: msg.urls || [] });
      else if (msg.type === "cur-collect") { data = await callApi("/api/v1/curate/ext/collect", { items: [msg.item] }); curTick(); }
      else if (msg.type === "cur-download") { data = await callApi("/api/v1/curate/ext/download", { url: msg.url || "" }); curTick(); }
      else if (msg.type === "cur-queue") data = await callApi("/api/v1/curate/ext/queue");
      else if (msg.type === "cur-action") { data = await callApi("/api/v1/curate/ext/queue/action", { id: msg.id || 0, action: msg.action }); if (msg.action === "resume") curTick(); }
      else if (msg.type === "cur-ping") data = await callApi("/api/v1/curate/ext/ping");
      else if (msg.type === "cur-kick") { curRefreshSites(true); curTick(); data = { busy: curBusy, detail: CUR_LANES.detail.run, files: CUR_LANES.file.run }; }
      else return reply({ ok: false, error: "unknown" });
      reply({ ok: true, data });
    } catch (e) { reply({ ok: false, error: String((e && e.message) || e) }); }
  })();
  return true;
});
