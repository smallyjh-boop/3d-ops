// 选品 · 扩展后台（3.1，从「3D选品工具」扩展的 background.js 搬过来；background.js 用 importScripts 载入，callApi / cfg 共用）。
// 都走 ERP 的 /api/v1/curate/ext/…（员工的扩展密钥，和 AI 客服、运营采集同一把）：
//   · 模型网站页面上的推荐分、「＋采集」（cur_picker.js 发 cur-* 消息到这里）
//   · 采集队列：ERP 说哪个详情页该读了，就在后台标签页打开、读（cur_extract.js）、交回、关掉
//   · 模型文件下载：用浏览器里原站的登录状态下载（credentials: include），再上传到 ERP（直接进产品的模型库）
//   · 关注巡逻：ERP 说哪个列表页该看了，就在后台标签页打开、往下翻几屏、读卡片、交回
// 节奏由 ERP 定（页面 / 文件之间随机等、每小时 / 每天上限、遇到人机验证 / 429 整个网站暂停），扩展只照做；每分钟问一次有没有活。
// 站点规则（站点包）每 10 分钟从 ERP 拿一次（版本变了才换），不用升级扩展。
const CUR_EXTRACT = ["cur_sites_builtin.js", "cur_sites.js", "cur_extract.js"];
let curSitesAt = 0, curBusy = false;

async function curOn() {
  const s = await chrome.storage.local.get({ curAuto: true });
  return s.curAuto !== false;
}
async function curRefreshSites(force) {
  if (!force && Date.now() - curSitesAt < 10 * 60 * 1000) return;
  curSitesAt = Date.now();
  try {
    const r = await callApi("/api/v1/curate/ext/sites");
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

// ---------------- 采集队列：读详情页 ----------------
async function curCollectOne(item) {
  let tabId = 0;
  const result = { id: item.id };
  try {
    const u = new URL(item.url); u.searchParams.set("cur_collect", "1");
    const tab = await chrome.tabs.create({ url: u.href, active: false });
    tabId = tab.id;
    await curWaitTab(tabId, 60000);
    await curSleepAlive(2500);
    let data = null, last = null;
    for (let i = 0; i < 6 && !data; i++) {
      const [{ result: d } = {}] = await chrome.scripting.executeScript({ target: { tabId }, func: async () => {
        if (!window.__modelCatalogExtract) return { err: "noextract" };
        try { return await window.__modelCatalogExtract({}); } catch (e) { return { err: String((e && e.message) || e) }; }
      } }).catch((err) => [{ result: { err: String((err && err.message) || err) } }]);
      if (d && d.err === "noextract") await chrome.scripting.executeScript({ target: { tabId }, files: CUR_EXTRACT }).catch(() => {});
      if (d && d.title && (d.image_urls || []).length) data = d;
      else { last = d; await curSleepAlive(3000); }
    }
    if (!data && last && last.title) data = last;
    if (data) result.data = data;
    else Object.assign(result, { error: "页面上没读到产品信息（可能要登录、验证，或页面没加载完）" }, await curPageText(tabId, item.url));
  } catch (err) {
    result.error = String((err && err.message) || err);
  } finally {
    if (tabId) chrome.tabs.remove(tabId).catch(() => {});
  }
  await callApi("/api/v1/curate/ext/result", result).catch(() => {});
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
async function curFetchFile(url) {
  const sites = await CuratorSites.load();
  const site = CuratorSites.siteForHost(sites, new URL(url).hostname);
  if (!site) throw new Error("只下载站点包里登记的模型网站的文件");
  url = await CuratorSites.resolveDownload(site, url);          // 有的网站要先换真实下载地址（规则在站点包 download 里）
  let resp = await fetch(url, { credentials: "include", redirect: "follow" });
  let type = (resp.headers.get("content-type") || "").toLowerCase();
  if (resp.ok && type.includes("json")) {
    const next = curFindFileUrl(await resp.json());
    if (!next) throw new Error("原站没有返回下载地址（可能需要登录或验证）");
    const same = sites.some((s) => CuratorSites.hostIn(new URL(next).hostname, [...(s.domains || []), ...(s.related_hosts || [])]));
    resp = await fetch(next, { credentials: same ? "include" : "omit", redirect: "follow" });
    type = (resp.headers.get("content-type") || "").toLowerCase();
  }
  const fail = async (message) => {
    const err = new Error(message); err.status = resp.status; err.url = resp.url;
    try { err.snippet = (await resp.text()).replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").slice(0, 2000); } catch (e) { /* 忽略 */ }
    throw err;
  };
  if (resp.status === 401 || resp.status === 403) await fail(`原站拒绝下载（HTTP ${resp.status}）`);
  if (!resp.ok) await fail(`原站返回 HTTP ${resp.status}`);
  if (type.includes("text/html")) await fail("原站返回的是网页，不是文件");
  const blob = await resp.blob();
  if (blob.size < 64) throw new Error("下载到的文件是空的");
  return { blob, resp };
}
async function curUpload(fid, name, blob) {
  const c = await cfg();
  let last = null;
  for (const s of c.servers) {
    try {
      const r = await fetch(`${s}/api/v1/curate/ext/files/${fid}/upload?name=${encodeURIComponent(name)}`, { method: "POST", body: blob,
        headers: { "Content-Type": "application/octet-stream", Authorization: "Bearer " + c.key, "X-Ext-Version": chrome.runtime.getManifest().version } });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || d.ok === false) throw new Error(d.error || `HTTP ${r.status}`);
      return d;
    } catch (e) { last = e; }
  }
  throw last || new Error("NO_CONFIG");
}
async function curFilesOnce() {
  const job = await callApi("/api/v1/curate/ext/files/next");
  if (!job || !job.product) return false;
  const gap = (job.pacing && job.pacing.file_gap) || [8, 20];
  let n = 0;
  for (const f of job.files) {
    if (n++) await curSleepAlive(Math.round((gap[0] + Math.random() * (gap[1] - gap[0])) * 1000));   // 像人一个个点下载
    try {
      const { blob, resp } = await curFetchFile(f.url);
      await curUpload(f.id, curNameFrom(resp, f.name), blob);
    } catch (err) {
      const r = await callApi(`/api/v1/curate/ext/files/${f.id}/fail`, { error: String((err && err.message) || err), status: (err && err.status) || 0,
        url: (err && err.url) || f.url, snippet: (err && err.snippet) || "" }).catch(() => ({}));
      if (r && r.stop) break;                                  // 风控或要登录：马上停，不再请求
    }
  }
  return true;
}

// ---------------- 关注巡逻：读列表页 ----------------
async function curWatchOnce() {
  const r = await callApi("/api/v1/curate/ext/watch/next").catch(() => null);
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
  await callApi("/api/v1/curate/ext/watch/result", result).catch(() => {});
  return true;
}

// ---------------- 一轮：采集 → 下载 → 巡逻（一次只做一件，ERP 决定节奏） ----------------
async function curTick() {
  if (curBusy || !(await curOn())) return;
  curBusy = true;
  try {
    await curRefreshSites(false);
    for (let guard = 0; guard < 50; guard++) {
      const r = await callApi("/api/v1/curate/ext/next");
      if (r && r.item) { await curCollectOne(r.item); continue; }
      if (r && r.wait > 0 && r.wait <= 120) { await curSleepAlive(r.wait * 1000); continue; }
      if (await curFilesOnce()) continue;
      await curWatchOnce();
      break;
    }
  } catch (e) { /* 没连上 ERP / 没设置：下一分钟再说 */ } finally { curBusy = false; }
}

chrome.alarms.create("cur-tick", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "cur-tick") curTick(); });
chrome.runtime.onStartup.addListener(() => { curRefreshSites(true); curTick(); });
chrome.runtime.onInstalled.addListener(() => { curRefreshSites(true); });

// ---------------- 页面（cur_picker.js）和弹窗发来的消息 ----------------
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || typeof msg.type !== "string" || !msg.type.startsWith("cur-")) return false;
  (async () => {
    try {
      let data;
      if (msg.type === "cur-score") data = await callApi("/api/v1/curate/ext/score", { items: msg.items || [] });
      else if (msg.type === "cur-status") data = await callApi("/api/v1/curate/ext/status", { urls: msg.urls || [] });
      else if (msg.type === "cur-collect") { data = await callApi("/api/v1/curate/ext/collect", { items: [msg.item] }); curTick(); }
      else if (msg.type === "cur-queue") data = await callApi("/api/v1/curate/ext/queue");
      else if (msg.type === "cur-action") { data = await callApi("/api/v1/curate/ext/queue/action", { id: msg.id || 0, action: msg.action }); if (msg.action === "resume") curTick(); }
      else if (msg.type === "cur-ping") data = await callApi("/api/v1/curate/ext/ping");
      else if (msg.type === "cur-kick") { curRefreshSites(true); curTick(); data = { busy: curBusy }; }
      else return reply({ ok: false, error: "unknown" });
      reply({ ok: true, data });
    } catch (e) { reply({ ok: false, error: String((e && e.message) || e) }); }
  })();
  return true;
});
