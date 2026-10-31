const TH = {
  server: "ที่อยู่ในวง LAN (NAS หรือคอมพิวเตอร์)", key: "API Key",
  server2: "ที่อยู่ภายนอก (Tailscale ไม่บังคับ)", s2help: "ใช้ตอนไม่อยู่ร้าน: ติดตั้ง Tailscale และล็อกอินบัญชีเดียวกัน ถ้าที่อยู่ LAN ใช้ไม่ได้จะสลับมาใช้อันนี้อัตโนมัติ",
  keyhelp: "ในระบบบริหารจัดการ 3D: ระบบ → ตั้งค่า → บัญชีและสิทธิ์ →「คีย์ส่วนขยายของพนักงาน」สร้างใหม่ (พนักงานคนละอัน)", lang: "ภาษาของแผง",
  save: "บันทึกและทดสอบ",
  lbltitle: "ส่งใบปะหน้า PDF เข้าระบบ",
  lblon: "เมื่อดาวน์โหลดใบปะหน้า PDF จากเว็บผู้ขาย / BigSeller ให้ถามว่าจะส่งเข้าระบบไหม (กด「ส่งเข้าระบบ」ถึงจะส่ง)",
  lbltab: "ส่ง PDF ในแท็บนี้เข้าระบบ",
  h3: "ระบบบริหารจัดการ 3D · ส่วนขยายเบราว์เซอร์",
  oatitle: "เก็บข้อมูลการขาย (คู่แข่ง ผลค้นหา ร้าน ข้อมูลหลังร้าน)", oarun: "เก็บข้อมูลหน้านี้", oapatrol: "🔭 เริ่มตระเวนวันนี้",
  oaauto: "เปิดหน้าข้อมูลในหลังร้าน (ประสิทธิภาพสินค้า / ทราฟฟิก / คีย์เวิร์ด) แล้วเก็บอัตโนมัติ (หน้าเดิม 12 ชม. ครั้ง)",
  oahelp: "ในหน้าสินค้า หน้าค้นหา หน้าร้านของ Lazada / Shopee / TikTok มีปุ่มเก็บข้อมูลมุมขวาล่าง และ「📊 เก็บ」บนการ์ดสินค้า ตระเวนวันนี้: ใช้ตอนอยู่หน้าคอม เปิดตามรายการในระบบทีละหน้า มีจำนวนสูงสุดต่อวัน เจอแคปช่าหยุดทันที ดูผลใน「สินค้า → สินค้าคู่แข่ง / เรดาร์สินค้าขายดี / ร้านคู่แข่ง」",
  lblhelp: "บางแพลตฟอร์มกด「พิมพ์ใบปะหน้า」แล้วเปิด PDF ในแท็บใหม่ ไม่ได้ดาวน์โหลด: ให้กดปุ่มนี้ในแท็บนั้น ระบบจะจับคู่ออเดอร์จากเลขออเดอร์ / เลขพัสดุในแต่ละหน้า",
};
const $ = (id) => document.getElementById(id);
let LANG = "zh";
const Z = (zh, th) => (LANG === "th" ? th : zh);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function tr(lang) { document.querySelectorAll("[data-t]").forEach((e) => { if (lang === "th" && TH[e.dataset.t]) e.textContent = TH[e.dataset.t]; }); }
chrome.storage.sync.get({ server: "", server2: "", key: "", lang: "zh", label_forward: true, oa_auto_back: true }, (d) => {
  $("server").value = d.server; $("server2").value = d.server2; $("key").value = d.key; $("lang").value = d.lang;
  $("label_forward").checked = d.label_forward !== false;
  $("oa_auto_back").checked = d.oa_auto_back !== false;
  LANG = d.lang; tr(d.lang); loadLabels();
});
$("save").onclick = async () => {
  let server = $("server").value.trim().replace(/\/+$/, "");
  if (server && !/^https?:\/\//.test(server)) server = "http://" + server;
  let server2 = $("server2").value.trim().replace(/\/+$/, "");
  if (server2 && !/^https?:\/\//.test(server2)) server2 = "http://" + server2;
  await chrome.storage.sync.set({ server, server2, key: $("key").value.trim(), lang: $("lang").value, label_forward: $("label_forward").checked });
  await chrome.storage.local.remove("active");
  $("server").value = server; $("server2").value = server2;
  $("st").textContent = "…";
  chrome.runtime.sendMessage({ type: "api", path: "/api/v1/cs/ping" }, (r) => {
    if (r && r.ok) { $("st").className = "ok"; chrome.storage.local.get({ active: "" }, (l) => { $("st").textContent = `✓ 已连接（${r.data.user}）· 待回复 ${r.data.stats.open}` + (l.active && server2 && l.active === server2 ? " · 外网" : ""); }); }
    else { $("st").className = "bad"; $("st").textContent = "✗ " + ((r && r.error) === "NO_CONFIG" ? "请填写地址和密钥" : (r && r.error) || "连接失败（检查地址、密钥；在店外用要填外网地址并打开 Tailscale）"); }
  });
};

// ---------- 面单 PDF 转交（v2.9）----------
$("label_forward").onchange = () => chrome.storage.sync.set({ label_forward: $("label_forward").checked });

function fmtAgo(ts) {
  const m = Math.max(0, Math.round((Date.now() - ts) / 60000));
  if (m < 1) return Z("刚才", "เมื่อกี้");
  return m < 60 ? Z(`${m} 分钟前`, `${m} นาทีที่แล้ว`) : Z(`${Math.round(m / 60)} 小时前`, `${Math.round(m / 60)} ชม.ที่แล้ว`);
}
const sizeOf = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB");

function loadLabels() {
  chrome.runtime.sendMessage({ type: "label-list" }, (r) => {
    void chrome.runtime.lastError;
    const box = $("lbl-list");
    if (!r || !r.ok) { box.innerHTML = ""; return; }
    const items = r.data.items || [], last = r.data.last || [];
    box.innerHTML = (items.length ? `<p class="muted">${Z("最近下载、还没发的面单：", "ใบปะหน้าที่ดาวน์โหลดแล้วแต่ยังไม่ได้ส่ง:")}</p>` : "")
      + items.map((x) => `<div class="lbl"><b>${esc(x.name)}</b> <span class="muted">${esc(x.site)} · ${sizeOf(x.size)} · ${fmtAgo(x.ts)}</span><br>
        <button data-send="${esc(x.id)}">${Z("发送到系统", "ส่งเข้าระบบ")}</button><button class="sec" data-drop="${esc(x.id)}">${Z("不用", "ไม่ต้อง")}</button></div>`).join("")
      + last.slice(0, 3).map((x) => `<div class="last ${x.ok ? "ok" : "bad"}">${x.ok ? "✓" : "✗"} ${esc(x.msg)} <span class="muted">· ${fmtAgo(x.ts)}</span></div>`).join("");
  });
}

function showResult(r) {
  const st = $("lbl-st");
  const d = r && r.ok ? r.data : null;
  if (!d) { st.className = "bad"; st.textContent = "✗ " + ((r && r.error) || Z("没发出去", "ส่งไม่สำเร็จ")); return; }
  st.className = d.ok ? "ok" : "bad";
  st.textContent = (d.ok ? "✓ " : "✗ ") + (d.msg || "");
}

document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-send],[data-drop]");
  if (!b) return;
  if (b.dataset.send) {
    b.disabled = true; $("lbl-st").className = ""; $("lbl-st").textContent = Z("发送中…", "กำลังส่ง…");
    chrome.runtime.sendMessage({ type: "label-send", id: b.dataset.send }, (r) => { void chrome.runtime.lastError; showResult(r); loadLabels(); });
  } else {
    chrome.runtime.sendMessage({ type: "label-drop", id: b.dataset.drop }, () => { void chrome.runtime.lastError; loadLabels(); });
  }
});

$("lbl-tab").onclick = () => {
  $("lbl-tab").disabled = true; $("lbl-st").className = ""; $("lbl-st").textContent = Z("发送中…", "กำลังส่ง…");
  chrome.runtime.sendMessage({ type: "label-send-tab" }, (r) => {
    void chrome.runtime.lastError;
    $("lbl-tab").disabled = false; showResult(r); loadLabels();
  });
};

// ---------- 运营采集（v3.0）----------
$("oa_auto_back").onchange = () => chrome.storage.sync.set({ oa_auto_back: $("oa_auto_back").checked });
$("oa-patrol").onclick = () => chrome.tabs.create({ url: chrome.runtime.getURL("patrol.html") });
$("oa-run").onclick = async () => {
  const st = $("oa-st");
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  chrome.tabs.sendMessage(tab.id, { type: "oa-run" }, { frameId: 0 }, (r) => {
    if (chrome.runtime.lastError || !r || !r.ok) {
      st.className = "bad";
      st.textContent = Z("这一页不能采集：请打开 Lazada / Shopee / TikTok 的商品页、搜索结果页、店铺页，或卖家中心的数据页面（打开后刷新一次）",
        "หน้านี้เก็บไม่ได้: เปิดหน้าสินค้า หน้าค้นหา หน้าร้าน ของ Lazada / Shopee / TikTok หรือหน้าข้อมูลในหลังร้าน (เปิดแล้วรีเฟรชหนึ่งครั้ง)");
    } else window.close();
  });
};
