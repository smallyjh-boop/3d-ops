// 插件弹窗 / 设置页（v3.0.2 重新排版）：状态一行 → 三个大按钮 + 最近一次结果 → 收起的「连接设置」「设置」。
const TH = {
  h3: "ระบบจัดการ 3D · ส่วนขยาย", conn: "การเชื่อมต่อ", opts: "ตั้งค่า",
  server: "ที่อยู่ในวง LAN (NAS หรือคอมพิวเตอร์)", key: "API Key",
  server2: "ที่อยู่ภายนอก (Tailscale ไม่บังคับ)", s2help: "ใช้ตอนไม่อยู่ร้าน: ติดตั้ง Tailscale และล็อกอินบัญชีเดียวกัน ถ้าที่อยู่ LAN ใช้ไม่ได้จะสลับมาใช้อันนี้อัตโนมัติ",
  keyhelp: "ในระบบบริหารจัดการ 3D: ระบบ → ตั้งค่า → บัญชีและสิทธิ์ →「คีย์ส่วนขยายของพนักงาน」สร้างใหม่ (พนักงานคนละอัน คำตอบจะบันทึกในชื่อนี้)",
  save: "บันทึกและทดสอบ",
  oarun: "เก็บข้อมูลหน้านี้", oapatrol: "เริ่มตระเวนวันนี้", lbltab: "ส่ง PDF ในแท็บนี้",
  lblon: "ดาวน์โหลดใบปะหน้า PDF แล้วถามว่าจะส่งเข้าระบบไหม",
  lblhelp: "เมื่อดาวน์โหลดใบปะหน้า PDF จากเว็บผู้ขาย / BigSeller จะมีข้อความถาม กด「ส่งเข้าระบบ」ถึงจะส่ง บางแพลตฟอร์มกด「พิมพ์ใบปะหน้า」แล้วเปิด PDF ในแท็บใหม่: ให้กด「📄 ส่ง PDF ในแท็บนี้」ในแท็บนั้น ระบบจะจับคู่ออเดอร์จากเลขออเดอร์ / เลขพัสดุในแต่ละหน้า",
  oaauto: "เก็บข้อมูลหน้าข้อมูลหลังร้านอัตโนมัติ",
  oahelp: "เปิดหน้าข้อมูลในหลังร้าน (ประสิทธิภาพสินค้า / ทราฟฟิก / คีย์เวิร์ด) แล้วเก็บอัตโนมัติ หน้าเดิม 12 ชม. ครั้ง ในหน้าสินค้า หน้าค้นหา หน้าร้านของ Lazada / Shopee / TikTok มีปุ่มเก็บข้อมูลมุมขวาล่าง และ「📊 เก็บ」บนการ์ดสินค้า ตระเวนวันนี้: ใช้ตอนอยู่หน้าคอม เปิดตามรายการในระบบทีละหน้า มีจำนวนสูงสุดต่อวัน เจอแคปช่าหยุดทันที ดูผลใน「สินค้า → สินค้าคู่แข่ง / เรดาร์สินค้าขายดี / ร้านคู่แข่ง」",
  cs: "AI แชทลูกค้า (แผงมุมขวาล่างของหน้าแชท)", csauto: "เปิดหน้าแชทแล้วเปิด AI แชทลูกค้าทันที",
  cspatrol: "มีข้อความยังไม่อ่านและฉันไม่ได้ใช้งานอยู่ ให้สลับไปหาลูกค้าคนนั้นเอง", cssync: "ใส่คำตอบในช่องพิมพ์ของแพลตฟอร์มด้วย",
  cshelp: "เป็นการตั้งค่าเดียวกับสวิตช์ในแผงหน้าแชท แก้แล้วรีเฟรชหน้าแชทถึงจะมีผล โหมดของแต่ละหน้า (ปิด / กึ่งอัตโนมัติ / อัตโนมัติ) เลือกในแผง",
  cur: "คัดเลือกสินค้า (เว็บโมเดล)", cursub: "คัดเลือกสินค้า (เว็บโมเดล)", curopen: "เปิดคัดเลือก",
  curhelp: "ในหน้ารายการของ MakerWorld / Printables / Thingiverse แต่ละโมเดลจะมีคะแนนและปุ่ม「＋เก็บ」(= ใช้ใน ERP สร้างสินค้าฉบับร่างทันที) ส่วนขยายจะอ่านหน้ารายละเอียด ดาวน์โหลดไฟล์ด้วยการล็อกอินเว็บต้นทางในเบราว์เซอร์นี้ และตระเวนตามรายการติดตามตามจังหวะที่ ERP กำหนด ถ้าเจอแคปช่าหรือถูกจำกัดจะหยุดเว็บนั้นอัตโนมัติ ดูผลที่ ERP「สินค้า → คัดเลือกสินค้า」",
  curpick: "แสดงคะแนนและปุ่ม「＋เก็บ」บนเว็บโมเดล", curauto: "เก็บรายละเอียด ดาวน์โหลดไฟล์ และตระเวนเบื้องหลังอัตโนมัติ",
  curautohelp: "ถาม ERP ทุกนาทีว่ามีงานไหม เปิดแท็บเบื้องหลังทีละแท็บ อ่านเสร็จแล้วปิด ต้องเปิดคอมและ Chrome ไว้ ต้องล็อกอินเว็บต้นทางก่อนจึงจะดาวน์โหลดไฟล์ที่ต้องล็อกอินได้ ปิดแล้วจะไม่ทำอัตโนมัติ (คะแนนในหน้ารายการยังแสดง)",
};
const $ = (id) => document.getElementById(id);
let LANG = "zh";
const Z = (zh, th) => (LANG === "th" ? th : zh);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const DAY = 86400000;
function tr(lang) { document.querySelectorAll("[data-t]").forEach((e) => { if (lang === "th" && TH[e.dataset.t]) e.textContent = TH[e.dataset.t]; }); }
const send = (m) => new Promise((res) => chrome.runtime.sendMessage(m, (r) => { void chrome.runtime.lastError; res(r); }));

// 「?」：点一下展开 / 收起说明
document.addEventListener("click", (e) => {
  const q = e.target.closest && e.target.closest(".q");
  if (!q) return;
  e.preventDefault();          // 在 label 里：不要顺便勾选
  $(q.dataset.q).classList.toggle("on");
});

chrome.storage.sync.get({ server: "", server2: "", key: "", lang: "zh", label_forward: true, oa_auto_back: true }, (d) => {
  $("server").value = d.server; $("server2").value = d.server2; $("key").value = d.key; $("lang").value = d.lang;
  $("label_forward").checked = d.label_forward !== false;
  $("oa_auto_back").checked = d.oa_auto_back !== false;
  LANG = d.lang; tr(d.lang);
  if (!d.server || !d.key) { $("conn").open = true; status(false, Z("请先填写地址和密钥", "กรุณากรอกที่อยู่และคีย์ก่อน")); }
  else ping();
  loadLast();
});
// AI 客服面板的开关（content.js 读同样的 chrome.storage.local 键）
chrome.storage.local.get({ autorun: true, patrol: true, sync: true }, (d) => {
  $("cs_autorun").checked = d.autorun !== false; $("cs_patrol").checked = !!d.patrol; $("cs_sync").checked = d.sync !== false;
});
$("cs_autorun").onchange = () => chrome.storage.local.set({ autorun: $("cs_autorun").checked });
$("cs_patrol").onchange = () => chrome.storage.local.set({ patrol: $("cs_patrol").checked });
$("cs_sync").onchange = () => chrome.storage.local.set({ sync: $("cs_sync").checked });

// ---------- 连接 ----------
function status(ok, text) { const st = $("st"); st.className = ok ? "ok" : "bad"; st.textContent = text; }
function ping() {
  $("st").className = ""; $("st").textContent = "…";
  chrome.runtime.sendMessage({ type: "api", path: "/api/v1/cs/ping" }, (r) => {
    void chrome.runtime.lastError;
    if (r && r.ok) {
      chrome.storage.local.get({ active: "" }, (l) => {
        const s2 = $("server2").value.trim().replace(/\/+$/, "");
        status(true, Z(`✓ 已连接（${r.data.user}）· 待回复 ${r.data.stats.open}`, `✓ เชื่อมต่อแล้ว (${r.data.user}) · รอตอบ ${r.data.stats.open}`)
          + (l.active && s2 && l.active === s2 ? Z(" · 外网", " · ภายนอก") : ""));
      });
      $("conn").open = false;
    } else {
      status(false, "✗ " + ((r && r.error) === "NO_CONFIG" ? Z("请填写地址和密钥", "กรุณากรอกที่อยู่และคีย์")
        : (r && r.error) || Z("连接失败（检查地址、密钥；在店外用要填外网地址并打开 Tailscale）", "เชื่อมต่อไม่ได้ (ตรวจที่อยู่ คีย์ ถ้าอยู่นอกร้านต้องกรอกที่อยู่ภายนอกและเปิด Tailscale)")));
      $("conn").open = true;
    }
  });
}
const fixUrl = (v) => { v = v.trim().replace(/\/+$/, ""); return v && !/^https?:\/\//.test(v) ? "http://" + v : v; };
$("save").onclick = async () => {
  const server = fixUrl($("server").value), server2 = fixUrl($("server2").value);
  await chrome.storage.sync.set({ server, server2, key: $("key").value.trim(), lang: $("lang").value, label_forward: $("label_forward").checked });
  await chrome.storage.local.remove("active");
  $("server").value = server; $("server2").value = server2;
  ping();
};
$("lang").onchange = async () => { await chrome.storage.sync.set({ lang: $("lang").value }); location.reload(); };

// ---------- 最近一次结果（面单发送 / 采集）：一行，超过 1 天的不显示 ----------
function fmtAgo(ts) {
  const m = Math.max(0, Math.round((Date.now() - ts) / 60000));
  if (m < 1) return Z("刚才", "เมื่อกี้");
  return m < 60 ? Z(`${m} 分钟前`, `${m} นาทีที่แล้ว`) : Z(`${Math.round(m / 60)} 小时前`, `${Math.round(m / 60)} ชม.ที่แล้ว`);
}
const sizeOf = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB");
function showLast(x) {
  const el = $("last");
  if (!x || !x.ts || Date.now() - x.ts > DAY) { el.innerHTML = ""; el.title = ""; return; }
  el.innerHTML = `<span class="${x.ok ? "ok" : "bad"}">${x.ok ? "✓" : "✗"} ${esc(x.msg)}</span> <span class="muted">· ${fmtAgo(x.ts)}</span>`;
  el.title = x.msg || "";
}
function setLast(x) { chrome.storage.local.set({ oa_last: x }); showLast(x); }
async function loadLast() {
  const r = await send({ type: "label-list" });
  const { oa_last } = await chrome.storage.local.get({ oa_last: null });
  const box = $("lbl-list");
  const items = r && r.ok ? r.data.items || [] : [];
  const lbl = r && r.ok ? (r.data.last || [])[0] : null;
  box.innerHTML = items.map((x) => `<div class="lbl">📄 <b>${esc(x.name)}</b> <span class="muted">${esc(x.site)} · ${sizeOf(x.size)} · ${fmtAgo(x.ts)}</span><br>
    <button data-send="${esc(x.id)}">${Z("发送到系统", "ส่งเข้าระบบ")}</button><button class="sec" data-drop="${esc(x.id)}">${Z("不用", "ไม่ต้อง")}</button></div>`).join("");
  showLast([lbl, oa_last].filter(Boolean).sort((a, b) => b.ts - a.ts)[0]);
}
function labelResult(r) {
  const d = r && r.ok ? r.data : null;
  if (!d) return showLast({ ts: Date.now(), ok: false, msg: (r && r.error) || Z("没发出去", "ส่งไม่สำเร็จ") });
  loadLast();
}
function busyLast(text) { $("last").innerHTML = `<span class="muted">${esc(text)}</span>`; }

// ---------- 面单 PDF ----------
$("label_forward").onchange = () => chrome.storage.sync.set({ label_forward: $("label_forward").checked });
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-send],[data-drop]");
  if (!b) return;
  if (b.dataset.send) {
    b.disabled = true; busyLast(Z("发送中…", "กำลังส่ง…"));
    send({ type: "label-send", id: b.dataset.send }).then(labelResult);
  } else send({ type: "label-drop", id: b.dataset.drop }).then(loadLast);
});
$("lbl-tab").onclick = () => {
  $("lbl-tab").disabled = true; busyLast(Z("发送中…", "กำลังส่ง…"));
  send({ type: "label-send-tab" }).then((r) => { $("lbl-tab").disabled = false; labelResult(r); });
};

// ---------- 运营采集 ----------
$("oa_auto_back").onchange = () => chrome.storage.sync.set({ oa_auto_back: $("oa_auto_back").checked });
$("oa-patrol").onclick = () => chrome.tabs.create({ url: chrome.runtime.getURL("patrol.html") });
$("oa-run").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  chrome.tabs.sendMessage(tab.id, { type: "oa-run" }, { frameId: 0 }, (r) => {
    if (chrome.runtime.lastError || !r || !r.ok) {
      setLast({ ts: Date.now(), ok: false, msg: Z("这一页不能采集：请打开 Lazada / Shopee / TikTok 的商品页、搜索结果页、店铺页，或卖家中心的数据页面（打开后刷新一次）",
        "หน้านี้เก็บไม่ได้: เปิดหน้าสินค้า หน้าค้นหา หน้าร้าน ของ Lazada / Shopee / TikTok หรือหน้าข้อมูลในหลังร้าน (เปิดแล้วรีเฟรชหนึ่งครั้ง)") });
    } else {
      setLast({ ts: Date.now(), ok: true, msg: Z("已开始采集当前页（结果看页面右下角）", "เริ่มเก็บข้อมูลหน้านี้แล้ว (ดูผลที่มุมขวาล่างของหน้า)") });
      window.close();
    }
  });
};

// ---------- 选品（v3.1）：状态一行 + 打开 ERP 的选品页；设置里两个开关 ----------
chrome.storage.local.get({ curPicker: true, curAuto: true }, (d) => { $("cur_picker").checked = d.curPicker !== false; $("cur_auto").checked = d.curAuto !== false; });
$("cur_picker").onchange = () => chrome.storage.local.set({ curPicker: $("cur_picker").checked });
$("cur_auto").onchange = () => { chrome.storage.local.set({ curAuto: $("cur_auto").checked }); if ($("cur_auto").checked) send({ type: "cur-kick" }); };
$("cur-open").onclick = () => send({ type: "open", path: "/#cur_cand" });
(async function curStatus() {
  const r = await send({ type: "cur-ping" });
  const el = $("cur-st");
  if (!r || !r.ok) { el.textContent = Z("没连上（先在上面填好连接设置）", "ยังไม่เชื่อมต่อ (กรอกการเชื่อมต่อด้านบนก่อน)"); return; }
  const d = r.data || {};
  const parts = [Z(`今日新品 ${d.new_today || 0}`, `ใหม่วันนี้ ${d.new_today || 0}`), Z(`待采集 ${d.queue || 0}`, `รอเก็บ ${d.queue || 0}`), Z(`待下载 ${d.files || 0}`, `รอดาวน์โหลด ${d.files || 0}`),
    Z(`关注 ${d.watches || 0}`, `ติดตาม ${d.watches || 0}`)];
  el.textContent = parts.join(" · ") + ((d.paused || []).length ? Z(" · 暂停：", " · หยุด: ") + d.paused.join(", ") : "");
  el.className = (d.paused || []).length ? "bad" : "";
  el.title = el.textContent;
  if ((d.queue || d.files) && $("cur_auto").checked) send({ type: "cur-kick" });
})();
