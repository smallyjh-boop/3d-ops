// 面单 PDF 转交（v2.9）：员工在 Shopee / Lazada / TikTok 卖家中心或 BigSeller 下载面单 PDF 时，
// 插件弹一个通知「发到系统？」，点「发送到系统」才把这个 PDF 传给3D 运营管理系统（POST /api/v1/labels/import），
// 系统按每页上的订单号 / 运单号自动对应订单。点「不用」或不理它就不发（2 小时后自动丢掉）。
// 通知没看到也没关系：点浏览器上的插件图标，里面列着最近下载的面单，可以在那里发送。
// 只管从这几个网站下载的 PDF；不读网页上的别的东西，不碰账号密码，不改网页。
// 由 background.js 用 importScripts 载入（用到那边的 cfg()、fetchT()）。

const LBL_SITES = [["shopee", "Shopee"], ["lazada", "Lazada"], ["tiktok", "TikTok"], ["bigseller", "BigSeller"]];
const LBL_KEEP_MS = 2 * 3600 * 1000;       // 没发的面单留 2 小时
const LBL_MAX = 10;                        // 最多留 10 个
const LBL_MAX_BYTES = 30 * 1024 * 1024;

const lblT = (lang, zh, th) => (lang === "th" ? th : zh);

async function lblCfg() {
  return chrome.storage.sync.get({ label_forward: true, lang: "zh" });
}

// 从哪个网站来的（下载地址 / 最终地址 / 来源页面，任何一个是这几个平台就算）
function lblSite(...urls) {
  for (const u of urls) {
    if (!u) continue;
    let host = "";
    try { host = new URL(u.startsWith("blob:") ? u.slice(5) : u).hostname.toLowerCase(); } catch { continue; }
    for (const [k, name] of LBL_SITES) if (host.includes(k)) return name;
  }
  return "";
}

const lblBase = (p) => String(p || "").split(/[\\/]/).pop().split("?")[0] || "";
const lblSize = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB");

function lblIsPdf(buf) {
  if (!buf || !buf.byteLength) return false;
  const b = new Uint8Array(buf, 0, Math.min(1024, buf.byteLength));
  let s = "";
  for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
  return s.includes("%PDF-");
}

function lblB64(s) {
  const bin = atob(s), u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u.buffer;
}

// ---------- 暂存（IndexedDB，后台被浏览器休眠后也还在）----------
const LDB = (() => {
  let p = null;
  const open = () => p || (p = new Promise((res, rej) => {
    const r = indexedDB.open("lh-labels", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("pdf", { keyPath: "id" });
    r.onsuccess = () => res(r.result);
    r.onerror = () => { p = null; rej(r.error); };
  }));
  const run = async (mode, fn) => {
    const db = await open();
    return new Promise((res, rej) => {
      const t = db.transaction("pdf", mode);
      const req = fn(t.objectStore("pdf"));
      t.oncomplete = () => res(req ? req.result : undefined);
      t.onerror = () => rej(t.error);
    });
  };
  return {
    put: (v) => run("readwrite", (s) => s.put(v)),
    add: (v) => run("readwrite", (s) => s.add(v)),          // 已经有了就不写（不覆盖已经对上下载记录的那一份）
    get: (id) => run("readonly", (s) => s.get(id)),
    del: (id) => run("readwrite", (s) => s.delete(id)),
    all: () => run("readonly", (s) => s.getAll()),
  };
})();

async function lblPrune() {
  const all = (await LDB.all().catch(() => [])) || [];
  const now = Date.now();
  // 先读好、但没对上下载记录的（下载取消了等）10 分钟后丢掉；等确认的留 2 小时、最多 10 个
  const dead = (x) => now - x.ts >= (x.ready ? LBL_KEEP_MS : 600000);
  const live = all.filter((x) => x.ready && !dead(x)).sort((a, b) => b.ts - a.ts);
  for (const x of all.filter(dead).concat(live.slice(LBL_MAX))) await LDB.del(x.id).catch(() => {});
}

// ---------- 拿到 PDF 的内容 ----------
// 网页里临时生成的 PDF（blob: 地址）只有同一个网站的页面读得到：到这个网站开着的标签页里读一下（只读这一个文件）
function lblReadInPage(u) {
  return fetch(u).then((r) => (r.ok ? r.arrayBuffer() : null)).then((ab) => {
    if (!ab || ab.byteLength > 30 * 1024 * 1024) return null;
    const b = new Uint8Array(ab);
    let s = "";
    for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
    return btoa(s);
  }).catch(() => null);
}

async function lblGrabBlob(url, tabId) {
  let origin = "";
  try { origin = new URL(url.slice(5)).origin; } catch { return null; }
  const tabs = await chrome.tabs.query({});
  const score = (t) => (t.id === tabId ? 4 : 0) + (t.url === url ? 2 : 0) + (t.active ? 1 : 0);
  const cands = tabs.filter((t) => t.url && (t.url === url || t.url.startsWith(origin + "/") || lblSite(t.url)))
    .sort((a, b) => score(b) - score(a) || (b.lastAccessed || 0) - (a.lastAccessed || 0)).slice(0, 8);
  for (const t of cands) {
    try {
      const res = await chrome.scripting.executeScript({ target: { tabId: t.id, allFrames: true }, func: lblReadInPage, args: [url] });
      const hit = (res || []).map((r) => r && r.result).find((x) => typeof x === "string" && x);
      if (hit) return lblB64(hit);
    } catch (e) { /* 这个标签页读不了，试下一个 */ }
  }
  return null;
}

async function lblFetch(url, tabId) {
  if (url.startsWith("data:")) return (await fetch(url)).arrayBuffer();
  if (url.startsWith("blob:")) return lblGrabBlob(url, tabId);
  if (!/^https?:/i.test(url)) return null;
  const r = await fetch(url, { credentials: "include" });
  if (!r.ok) return null;
  if (+(r.headers.get("content-length") || 0) > LBL_MAX_BYTES) return null;
  return r.arrayBuffer();
}

// ---------- 下载面单时：问一下 ----------
// 网页生成的 PDF（blob:）常常下载完马上就删掉了：
//   1) pdfgrab.js 在点下载的那一下先读一份交过来（label-blob，按地址暂存 "u:<地址>"）
//   2) 没交过来的，刚开始下载就到网页里读一份（"d<下载编号>"）
// 都只是先放在插件里，点「发送到系统」才发。
chrome.downloads.onCreated.addListener(async (it) => {
  try {
    const url = it.finalUrl || it.url || "";
    if (!url.startsWith("blob:") || !lblSite(url, it.referrer)) return;
    if (!(await lblCfg()).label_forward) return;
    if (await LDB.get("u:" + url).catch(() => null)) return;
    const buf = await lblGrabBlob(url);
    if (buf && buf.byteLength <= LBL_MAX_BYTES && lblIsPdf(buf)) {
      await LDB.add({ id: "d" + it.id, bytes: buf, size: buf.byteLength, ts: Date.now(), site: lblSite(url, it.referrer), name: "" }).catch(() => {});
    }
  } catch (e) { console.warn("label grab", e); }
});

// 先读好的那一份（pdfgrab.js 交过来的）：下载记录对上以后才算数
async function lblStashed(key, url) {
  for (let i = 0; i < (url.startsWith("blob:") ? 8 : 1); i++) {
    const a = await LDB.get(key).catch(() => null);
    if (a && a.bytes) return a;
    const b = url.startsWith("blob:") ? await LDB.get("u:" + url).catch(() => null) : null;
    if (b && b.bytes) { await LDB.del(b.id).catch(() => {}); return b; }
    if (i) await new Promise((r) => setTimeout(r, 250));       // 网页那边可能还在读，等一下
  }
  return null;
}

chrome.downloads.onChanged.addListener(async (d) => {
  if (!d.state || d.state.current !== "complete") return;
  try {
    const [it] = await chrome.downloads.search({ id: d.id });
    if (it) await lblDownloaded(it);
  } catch (e) { console.warn("label", e); }
});

async function lblDownloaded(it) {
  const c = await lblCfg();
  const url = it.finalUrl || it.url || "";
  const site = lblSite(url, it.url, it.referrer);
  const name = lblBase(it.filename) || "label.pdf";           // 只用文件名，不传电脑上的路径
  const key = "d" + it.id;
  const isPdf = /pdf/i.test(it.mime || "") || /\.pdf$/i.test(name);
  if (!c.label_forward || !site || !isPdf) { await LDB.del(key).catch(() => {}); return; }
  const old = await lblStashed(key, url);
  let buf = old && old.bytes;
  if (!buf) {
    try { buf = await lblFetch(url); } catch { buf = null; }
    if (buf && (buf.byteLength > LBL_MAX_BYTES || !lblIsPdf(buf))) buf = null;
  }
  if (!buf) return lblNote(c.lang, { ok: false, title: site, msg: lblT(c.lang,
    `${name}：插件拿不到这个文件（网页生成后马上删了）。请到系统「订单列表」点「⬆ 上传平台面单 PDF」，选这个文件。`,
    `${name}: ส่วนขยายอ่านไฟล์นี้ไม่ได้ กรุณาไปที่ระบบ「รายการออเดอร์」กด「⬆ อัปโหลดใบปะหน้า PDF」แล้วเลือกไฟล์นี้`) });
  const rec = { id: key, bytes: buf, size: buf.byteLength, ts: Date.now(), site, name, ready: true };
  await LDB.put(rec);
  await lblPrune();
  lblAsk(c.lang, rec);
}

function lblAsk(lang, rec) {
  chrome.notifications.create("lbl:" + rec.id, {
    type: "basic", iconUrl: "icon128.png", priority: 2, requireInteraction: true,
    title: lblT(lang, `面单 PDF · ${rec.site}`, `ใบปะหน้า PDF · ${rec.site}`),
    message: `${rec.name}（${lblSize(rec.size)}）\n` + lblT(lang, "发到系统，自动对应订单？", "ส่งเข้าระบบเพื่อจับคู่กับออเดอร์ไหม?"),
    buttons: [{ title: lblT(lang, "发送到系统", "ส่งเข้าระบบ") }, { title: lblT(lang, "不用", "ไม่ต้อง") }],
  });
}

// 结果通知（点一下打开系统的订单列表）；最近 5 条也记下来，插件弹窗里能看到
async function lblNote(lang, r) {
  chrome.notifications.create("lblr:" + Date.now(), {
    type: "basic", iconUrl: "icon128.png", priority: 1,
    title: (r.ok ? "✓ " : "✗ ") + lblT(lang, "面单 PDF", "ใบปะหน้า PDF") + (r.title ? " · " + r.title : ""),
    message: String(r.msg || "").slice(0, 300),
  });
  const { lbl_last } = await chrome.storage.local.get({ lbl_last: [] });
  lbl_last.unshift({ ts: Date.now(), ok: !!r.ok, msg: r.msg || "", name: r.name || "" });
  await chrome.storage.local.set({ lbl_last: lbl_last.slice(0, 5) });
  return r;
}

chrome.notifications.onButtonClicked.addListener((nid, idx) => {
  if (!nid.startsWith("lbl:")) return;
  chrome.notifications.clear(nid);
  const id = nid.slice(4);
  if (idx === 0) lblSend(id).catch((e) => console.warn("label send", e));
  else LDB.del(id).catch(() => {});
});

chrome.notifications.onClicked.addListener(async (nid) => {
  if (!nid.startsWith("lblr:")) return;
  chrome.notifications.clear(nid);
  const c = await cfg();
  if (c.server) chrome.tabs.create({ url: c.server + "/#orders" });
});

// ---------- 发送 ----------
async function lblUpload(rec) {
  const c = await cfg();
  if (!c.servers.length || !c.key) throw new Error("NO_CONFIG");
  for (let i = 0; i < c.servers.length; i++) {
    const fd = new FormData();
    fd.append("file", new Blob([rec.bytes], { type: "application/pdf" }), rec.name || "label.pdf");
    fd.append("site", rec.site || "");
    let r = null;
    try {
      r = await fetchT(c.servers[i] + "/api/v1/labels/import", {
        method: "POST", body: fd,
        headers: { Authorization: "Bearer " + c.key, "X-Ext-Version": chrome.runtime.getManifest().version },
      }, c.servers.length > 1 && i === 0 ? 20000 : 120000);
    } catch (e) { continue; }
    if (c.servers.length > 1) chrome.storage.local.set({ active: c.servers[i] });
    let d = null;
    try { d = await r.json(); } catch { d = null; }
    if (!r.ok) throw new Error((d && d.error) || `HTTP ${r.status}`);
    return d;
  }
  throw new Error(lblT(c.lang, "连不上系统（不在店里时请打开电脑上的 Tailscale）", "เชื่อมต่อระบบไม่ได้ (ถ้าอยู่นอกร้านให้เปิด Tailscale)"));
}

async function lblSend(id) {
  const { lang } = await lblCfg();
  const rec = await LDB.get(id).catch(() => null);
  if (!rec || !rec.bytes) return lblNote(lang, { ok: false, msg: lblT(lang, "这个面单已经过期了，请重新下载一次", "ไฟล์นี้หมดอายุแล้ว กรุณาดาวน์โหลดใหม่") });
  let d;
  try {
    d = await lblUpload(rec);
  } catch (e) {
    const m = String(e.message || e);
    return lblNote(lang, { ok: false, title: rec.site, name: rec.name, msg: m === "NO_CONFIG"
      ? lblT(lang, "请先在插件设置里填系统地址和密钥", "กรุณากรอกที่อยู่ระบบและ API Key ในการตั้งค่าส่วนขยายก่อน")
      : `${rec.name}：${m}` });
  }
  await LDB.del(id).catch(() => {});
  const miss = (d.unmatched_pages || []).length;
  const nos = (d.order_nos || []).slice(0, 4).join(", ") + ((d.order_nos || []).length > 4 ? " …" : "");
  let msg;
  if (d.matched) {
    msg = lblT(lang, `已发到系统：${d.pages} 页，对上 ${d.matched} 个订单（${nos}）`, `ส่งเข้าระบบแล้ว: ${d.pages} หน้า ตรงกับ ${d.matched} ออเดอร์ (${nos})`);
    if (miss) msg += lblT(lang, `\n第 ${d.unmatched_pages.join("、")} 页没对上（订单可能还没导入系统）`, `\nหน้า ${d.unmatched_pages.join(", ")} ไม่ตรงกับออเดอร์ (อาจยังไม่ได้นำเข้าออเดอร์)`);
  } else {
    msg = lblT(lang, `发到了系统，但 ${d.pages} 页都没对上订单（可能是图片型 PDF，或这些订单还没导入系统）`,
      `ส่งแล้ว แต่ทั้ง ${d.pages} หน้าไม่ตรงกับออเดอร์ (อาจเป็น PDF แบบรูปภาพ หรือยังไม่ได้นำเข้าออเดอร์)`);
  }
  return lblNote(lang, { ok: !!d.matched, title: rec.site, name: rec.name, msg, data: d });
}

// 插件弹窗里的按钮：把当前标签页打开的 PDF 发到系统（有的平台点「打印面单」是在新标签页打开 PDF，不是下载）
async function lblSendTab() {
  const { lang } = await lblCfg();
  const [t] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const url = (t && t.url) || "";
  let buf = null;
  if (/^(https?|blob|data):/i.test(url)) {
    try { buf = await lblFetch(url, t.id); } catch { buf = null; }
  }
  if (!buf || buf.byteLength > LBL_MAX_BYTES || !lblIsPdf(buf)) {
    return lblNote(lang, { ok: false, msg: lblT(lang, "当前标签页不是 PDF：请先在卖家中心 / BigSeller 打开面单 PDF，再点这个按钮",
      "แท็บนี้ไม่ใช่ PDF: เปิดใบปะหน้า PDF ในเว็บผู้ขายหรือ BigSeller ก่อน แล้วค่อยกดปุ่มนี้") });
  }
  let name = "";
  try { name = url.startsWith("http") ? decodeURIComponent(lblBase(new URL(url).pathname)) : ""; } catch { name = ""; }
  if (!/\.pdf$/i.test(name)) name = "label.pdf";
  const rec = { id: "t" + Date.now(), bytes: buf, size: buf.byteLength, ts: Date.now(), site: lblSite(url) || "", name, ready: true };
  await LDB.put(rec);
  return lblSend(rec.id);
}

// 插件弹窗（options.html）用的消息：label-list / label-send / label-drop / label-send-tab
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg || typeof msg.type !== "string" || !msg.type.startsWith("label-")) return false;
  if (sender.id !== chrome.runtime.id) return false;
  // 发送 / 丢掉 / 列表只有插件自己的弹窗能用；网页里的脚本（pdfgrab.js）只能交 PDF 过来暂存
  const fromPopup = !!(sender.url && sender.url.startsWith(chrome.runtime.getURL("")));
  if ((msg.type === "label-blob") === fromPopup) { reply({ ok: false, error: "not allowed" }); return false; }
  (async () => {
    try {
      if (msg.type === "label-blob") {                 // pdfgrab.js：点下载的那一下读到的 PDF，先暂存
        const site = lblSite(msg.url, sender.tab && sender.tab.url);
        if (!site || !(await lblCfg()).label_forward || typeof msg.b64 !== "string") return reply({ ok: false });
        const buf = lblB64(msg.b64);
        if (buf.byteLength > LBL_MAX_BYTES || !lblIsPdf(buf)) return reply({ ok: false });
        await LDB.put({ id: "u:" + msg.url, bytes: buf, size: buf.byteLength, ts: Date.now(), site, name: lblBase(msg.name) });
        await lblPrune();
        return reply({ ok: true });
      }
      if (msg.type === "label-list") {
        await lblPrune();
        const all = (await LDB.all()) || [];
        const items = all.filter((x) => x.bytes && x.ready).sort((a, b) => b.ts - a.ts)
          .map((x) => ({ id: x.id, name: x.name, site: x.site, size: x.size, ts: x.ts }));
        const { lbl_last } = await chrome.storage.local.get({ lbl_last: [] });
        return reply({ ok: true, data: { items, last: lbl_last } });
      }
      if (msg.type === "label-send") { chrome.notifications.clear("lbl:" + msg.id); return reply({ ok: true, data: await lblSend(msg.id) }); }
      if (msg.type === "label-drop") { chrome.notifications.clear("lbl:" + msg.id); await LDB.del(msg.id); return reply({ ok: true }); }
      if (msg.type === "label-send-tab") return reply({ ok: true, data: await lblSendTab() });
      reply({ ok: false, error: "unknown" });
    } catch (e) {
      reply({ ok: false, error: String(e.message || e) });
    }
  })();
  return true;
});
