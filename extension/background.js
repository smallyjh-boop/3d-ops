// 后台：替页面里的面板访问3D 运营管理系统（NAS / 本机），以及截取当前标签页画面。
// v2.8：两个地址——局域网地址 + 外网地址（Tailscale）。哪个通用哪个，记住上次能用的那个。
// v2.9：面单 PDF 转交在 labels.js（下载面单时问一下，点「发送」才发到系统）。
importScripts("labels.js");
async function cfg() {
  const d = await chrome.storage.sync.get({ server: "", server2: "", key: "", lang: "zh" });
  const norm = (x) => (x || "").trim().replace(/\/+$/, "");
  d.server = norm(d.server); d.server2 = norm(d.server2);
  d.servers = [d.server, d.server2].filter(Boolean);
  const loc = await chrome.storage.local.get({ active: "" });
  if (loc.active && d.servers.includes(loc.active)) d.servers = [loc.active].concat(d.servers.filter((x) => x !== loc.active));
  d.server = d.servers[0] || "";
  return d;
}

async function fetchT(url, opt, ms) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), ms);
  try { return await fetch(url, { ...opt, signal: ac.signal }); } finally { clearTimeout(t); }
}

async function callApi(path, body, method) {
  const c = await cfg();
  if (!c.servers.length || !c.key) throw new Error("NO_CONFIG");
  const opt = {
    method: method || (body ? "POST" : "GET"),
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + c.key, "X-Ext-Version": chrome.runtime.getManifest().version },
    body: body ? JSON.stringify(body) : undefined,
  };
  let r = null, lastErr = null;
  for (let i = 0; i < c.servers.length; i++) {
    try {
      // 有备用地址时：第一个地址 8 秒连不上就换下一个（AI 生成回复可能要几十秒，所以只有一个地址时不限时）
      r = c.servers.length > 1 && i === 0 ? await fetchT(c.servers[i] + path, opt, path.includes("/draft") || path.includes("/capture") ? 90000 : 8000)
                                          : await fetch(c.servers[i] + path, opt);
      if (i > 0 || c.servers.length > 1) chrome.storage.local.set({ active: c.servers[i] });
      break;
    } catch (e) { lastErr = e; r = null; }
  }
  if (!r) throw new Error(c.lang === "th" ? "เชื่อมต่อระบบไม่ได้ (ถ้าอยู่นอกร้านให้เปิด Tailscale)" : "连不上系统（不在店里时请打开电脑上的 Tailscale）");
  let d = null;
  try { d = await r.json(); } catch { d = null; }
  if (!r.ok) throw new Error((d && d.error) || `HTTP ${r.status}`);
  return d;
}

// 聊天可能在页面里的某个框架（iframe）里：问所有框架，用读到最多聊天的那个
const PEND = {};
const BEST_FRAME = {};

// v2.6：多店铺——每个标签页的未读数（扩展图标上显示合计）；点桌面通知回到那个标签页
const UNREAD = {};
const NOTE_TAB = {};
function updateBadge() {
  const n = Object.values(UNREAD).reduce((a, b) => a + b, 0);
  chrome.action.setBadgeText({ text: n ? (n > 99 ? "99+" : String(n)) : "" });
  chrome.action.setBadgeBackgroundColor({ color: "#dc2626" });
}
chrome.tabs.onRemoved.addListener((id) => { delete UNREAD[id]; updateBadge(); });
chrome.notifications.onClicked.addListener((nid) => {
  const tabId = NOTE_TAB[nid];
  if (tabId == null) return;
  chrome.tabs.get(tabId, (t) => {
    if (chrome.runtime.lastError || !t) return;
    chrome.tabs.update(tabId, { active: true });
    chrome.windows.update(t.windowId, { focused: true });
  });
  chrome.notifications.clear(nid);
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && typeof msg.type === "string" && msg.type.startsWith("label-")) return false;   // 面单转交：labels.js 处理
  const tabId = sender.tab && sender.tab.id;
  if (msg.type === "whoami") { reply({ ok: true, data: { tab: tabId } }); return false; }
  if (msg.type === "focus-tab") {
    const id = +msg.tab;
    chrome.tabs.get(id, (t) => {
      if (chrome.runtime.lastError || !t) return reply({ ok: false, error: "tab gone" });
      chrome.tabs.update(id, { active: true }); chrome.windows.update(t.windowId, { focused: true });
      reply({ ok: true });
    });
    return true;
  }
  if (msg.type === "unread-ans") { if (PEND[msg.req]) PEND[msg.req].push({ frameId: sender.frameId, data: msg.data }); return false; }
  if (msg.type === "unread-all") {
    const req = "u" + Date.now() + "_" + Math.random();
    PEND[req] = [];
    chrome.tabs.sendMessage(tabId, { type: "unread-q", req });
    setTimeout(() => {
      const arr = (PEND[req] || []).filter((x) => x.data);
      delete PEND[req];
      arr.sort((a, b) => (b.data.n || 0) - (a.data.n || 0));
      const d = arr[0] ? arr[0].data : { n: 0, buyers: [] };
      UNREAD[tabId] = d.n || 0;
      updateBadge();
      reply({ ok: true, data: d });
    }, 700);
    return true;
  }
  if (msg.type === "collected") { if (PEND[msg.req]) PEND[msg.req].push({ frameId: sender.frameId, data: msg.data }); return false; }
  if (msg.type === "chat-changed") { chrome.tabs.sendMessage(tabId, { type: "chat-changed-top", last: msg.last }, { frameId: 0 }); return false; }
  if (msg.type === "collect-all") {
    const req = Date.now() + "_" + Math.random();
    PEND[req] = [];
    chrome.tabs.sendMessage(tabId, { type: "collect", req });
    setTimeout(() => {
      const arr = (PEND[req] || []).filter((x) => x.data && x.data.messages && x.data.messages.length);
      delete PEND[req];
      arr.sort((a, b) => b.data.score - a.data.score);
      if (arr[0]) BEST_FRAME[tabId] = arr[0].frameId;
      reply({ ok: true, data: arr[0] ? arr[0].data : null });
    }, 800);
    return true;
  }
  if (msg.type === "sendmsg-all" || msg.type === "patrol-all") {
    const m = msg.type === "sendmsg-all" ? { type: "sendmsg", text: msg.text } : { type: "patrol" };
    chrome.tabs.sendMessage(tabId, m, { frameId: BEST_FRAME[tabId] || 0 }, (r) => {
      void chrome.runtime.lastError;
      reply({ ok: true, data: r || null });
    });
    return true;
  }
  if (msg.type === "notify") {
    chrome.notifications.create({ type: "basic", iconUrl: "icon128.png", title: msg.title || "AI 客服", message: (msg.message || "").slice(0, 200), priority: 2 },
      (nid) => { if (nid && tabId != null) NOTE_TAB[nid] = tabId; });
    return false;
  }
  if (msg.type === "insert-all") {
    chrome.tabs.sendMessage(tabId, { type: "insert", text: msg.text }, { frameId: BEST_FRAME[tabId] || 0 }, (r) => {
      void chrome.runtime.lastError;
      reply({ ok: true, data: !!(r && r.ok) });
    });
    return true;
  }
  (async () => {
    try {
      if (msg.type === "api") return reply({ ok: true, data: await callApi(msg.path, msg.body, msg.method) });
      if (msg.type === "shot") {
        const url = await chrome.tabs.captureVisibleTab(sender.tab.windowId, { format: "jpeg", quality: 80 });
        return reply({ ok: true, data: url });
      }
      if (msg.type === "cfg") return reply({ ok: true, data: await cfg() });
      if (msg.type === "options") { chrome.runtime.openOptionsPage(); return reply({ ok: true }); }
      if (msg.type === "open") { const c = await cfg(); chrome.tabs.create({ url: c.server + (msg.path || "/") }); return reply({ ok: true }); }
      reply({ ok: false, error: "unknown" });
    } catch (e) {
      reply({ ok: false, error: String(e.message || e) });
    }
  })();
  return true;
});
