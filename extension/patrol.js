// v3.0 今日巡逻控制台（从原来的「运营分析采集」插件并进来）：一个专用标签页按清单逐页打开 → 等加载 → 随机停留并慢慢滚动 → 读页面 → 发回系统。
// 规矩：每天有上限（系统「设置 → 运营分析」）、每页随机停留、遇到验证码立刻停、连续出错 3 次停、关掉巡逻标签页就停。
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const dec = (u) => { try { return decodeURI(u); } catch (e) { return u; } };
const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
let LANG = "zh";
const Z = (zh, th) => (LANG === "th" ? th : zh);
const TH = {
  title: "🔭 ตระเวนวันนี้", k1: "ตระเวนวันนี้ / สูงสุด", k2: "รอบนี้ต้องดู", k3: "อยู่หน้าละ", k4: "ใช้เวลาประมาณ", start: "เริ่มตระเวน", stop: "หยุด",
  reload: "รีเฟรชรายการ", list: "รายการ", c1: "ประเภท", c2: "หน้า", c3: "ผล",
  intro: "เปิดหน้าค้นหาคีย์เวิร์ด ร้านที่เฝ้า และหน้าสินค้าคู่แข่งทีละหน้า อยู่สักพัก เลื่อนลงช้าๆ แล้วอ่านตัวเลขที่เปิดเผยส่งกลับระบบ ใช้ตอนอยู่หน้าคอม แนะนำใช้โปรไฟล์ Chrome แยกที่ไม่ได้ล็อกอินบัญชีผู้ขาย เจอแคปช่าจะหยุดทันที ให้ยืนยันเองแล้ววันนี้อย่าตระเวนอีก",
};
const KIND = () => ({ search: Z("搜索页", "หน้าค้นหา"), product: Z("竞品页", "หน้าคู่แข่ง"), shop: Z("店铺页", "หน้าร้าน") });
let PLAN = null, running = false, stopFlag = false, tabId = null, SPEED = 1;

const bg = (msg) => new Promise((ok) => chrome.runtime.sendMessage(msg, (r) => { void chrome.runtime.lastError; ok(r || { ok: false, error: Z("插件后台没响应", "ส่วนขยายไม่ตอบ") }); }));
async function call(path, body) {
  const r = await bg({ type: "api", path, body });
  if (r.ok) return r.data || { ok: false };
  return { ok: false, error: r.error === "NO_CONFIG" ? Z("还没设置：点插件图标，填系统地址和员工密钥", "ยังไม่ได้ตั้งค่า: กดไอคอนส่วนขยาย กรอกที่อยู่ระบบและคีย์") : r.error };
}
function msg(text, cls = "warn") { const m = $("#msg"); m.className = "on " + cls; m.innerHTML = text; }
function setRow(i, html) { const td = document.querySelector(`#r${i} .res`); if (td) td.innerHTML = html; }

async function load() {
  const s = await chrome.storage.sync.get({ lang: "zh" });
  LANG = s.lang || "zh";
  if (LANG === "th") document.querySelectorAll("[data-t]").forEach((e) => { if (TH[e.dataset.t]) e.textContent = TH[e.dataset.t]; });
  SPEED = Math.max(1, +((await chrome.storage.local.get("oaPatrolSpeed")).oaPatrolSpeed || 1));   // 只给测试用
  PLAN = await call("/api/v1/ops/ext/patrol");
  if (!PLAN.ok) { msg(esc(PLAN.error), "err"); $("#start").disabled = true; return; }
  const p = PLAN, avg = (p.wait[0] + p.wait[1]) / 2 + 6;
  $("#k-done").textContent = `${p.done} / ${p.cap}`;
  $("#k-left").textContent = p.items.length;
  $("#k-wait").textContent = `${p.wait[0]}–${p.wait[1]} ${Z("秒", "วินาที")}`;
  $("#k-time").textContent = p.items.length ? Z(`约 ${Math.ceil((p.items.length * avg) / 60)} 分钟`, `ราว ${Math.ceil((p.items.length * avg) / 60)} นาที`) : "-";
  $("#list").innerHTML = p.items.map((it, i) => `<tr id="r${i}"><td>${i + 1}</td><td>${KIND()[it.kind] || esc(it.kind)}</td>
    <td class="u"><b>${esc(it.label)}</b> <span class="hint">${esc(it.platform)}</span><div class="hint">${esc(dec(it.url))}</div></td><td class="res"><span class="pill">${Z("等待", "รอ")}</span></td></tr>`).join("");
  $("#start").disabled = !p.items.length;
  if (!p.items.length) msg(p.left === 0 ? Z(`今天已经巡逻 ${p.done} 页，到上限了（${p.cap}），明天再来。`, `วันนี้ตระเวนแล้ว ${p.done} หน้า ครบจำนวนสูงสุด (${p.cap}) พรุ่งนี้ค่อยมาใหม่`)
    : Z("没有要巡逻的页面：先到系统「商品 → 爆款雷达」加关键词，或者今天都看过了。", "ไม่มีหน้าที่ต้องตระเวน: เพิ่มคีย์เวิร์ดใน「สินค้า → เรดาร์สินค้าขายดี」ก่อน หรือวันนี้ดูครบแล้ว"), "ok");
}
function waitLoaded(id) {
  return new Promise((resolve) => {
    let done = false;
    const fin = (v) => { if (!done) { done = true; chrome.tabs.onUpdated.removeListener(l); clearTimeout(t); resolve(v); } };
    const l = (tid, info) => { if (tid === id && info.status === "complete") fin(true); };
    const t = setTimeout(() => fin(false), 45000);
    chrome.tabs.onUpdated.addListener(l);
  });
}
async function tabMsg(m, tries = 10) {
  for (let i = 0; i < tries; i++) {
    const r = await new Promise((ok) => chrome.tabs.sendMessage(tabId, m, { frameId: 0 }, (x) => ok(chrome.runtime.lastError ? null : x)));
    if (r) return r;
    await sleep(1000);
  }
  return null;
}
async function tabAlive() { try { await chrome.tabs.get(tabId); return true; } catch (e) { return false; } }
const plog = (it, ok, note) => call("/api/v1/ops/ext/patrol/log", { kind: it.kind, url: it.url, ok, note });

async function visit(it, i) {
  setRow(i, `<span class="pill run">${Z("打开中…", "กำลังเปิด…")}</span>`);
  if (tabId == null || !(await tabAlive())) {
    const t = await chrome.tabs.create({ url: "about:blank", active: true });     // 先开空白页再跳转：插件脚本更稳
    tabId = t.id;
    await sleep(500);
  }
  const loaded = waitLoaded(tabId);
  await chrome.tabs.update(tabId, { url: it.url, active: true });
  await loaded;
  if (stopFlag) return { stop: true };
  if (!(await tabAlive())) return { stop: true, why: Z("巡逻标签页被关掉了", "แท็บตระเวนถูกปิด") };
  const c = await tabMsg({ type: "oa-check" });
  if (!c) return { ok: false, note: Z("页面没反应（插件脚本没加载）", "หน้าไม่ตอบ (สคริปต์ไม่โหลด)") };
  if (c.captcha) return { captcha: true };
  const [a, b] = PLAN.wait, wait = ((a + Math.random() * (b - a)) * 1000) / SPEED;
  setRow(i, `<span class="pill run">${Z(`停留 ${Math.round(wait / 1000)} 秒…`, `อยู่ ${Math.round(wait / 1000)} วินาที…`)}</span>`);
  const s = await tabMsg({ type: "oa-scroll", ms: wait }, 2);
  if (stopFlag) return { stop: true };
  if (s && s.captcha) return { captcha: true };
  const r = await tabMsg({ type: "oa-collect", kind: it.kind }, 3);
  if (!r) return { ok: false, note: Z("读不到页面", "อ่านหน้าไม่ได้") };
  if (r.captcha) return { captcha: true };
  if (it.kind === "shop") {
    const res = await call("/api/v1/ops/ext/shop", { ...r.data, ref: it.ref });
    await plog(it, !!res.ok, res.ok ? `${res.items} items` : res.error);
    if (!res.ok) return { ok: false, note: res.error, logged: true };
    const m = res.metrics || {};
    return { ok: true, html: `<span class="pill ok">${res.items} ${Z("个商品", "สินค้า")}</span>${m.followers != null ? ` ${Z("粉丝", "ผู้ติดตาม")} ${m.followers}` : ""}${m.daily != null ? ` · ${Z("店铺日销", "ขาย/วัน")} ${m.daily}` : ""}`, logged: true };
  }
  if (it.kind === "search") {
    const res = await call("/api/v1/ops/ext/search", { ...r.data, ref: it.ref });      // 系统那边会记巡逻日志
    if (!res.ok) return { ok: false, note: res.error, logged: true };
    const o = res.opportunity || {};
    return { ok: true, html: `<span class="pill ok">${res.cards} ${Z("个商品", "สินค้า")}</span> ${Z("机会分", "คะแนนโอกาส")} <b>${o.score ?? "-"}</b>${o.ip_risk ? ` <span class="pill bad">${Z("侵权", "ลิขสิทธิ์")}</span>` : ""}`, logged: true };
  }
  const res = await call("/api/v1/ops/ext/competitor", r.data);
  await plog(it, !!res.ok, res.ok ? "updated" : res.error);
  if (!res.ok) return { ok: false, note: res.error, logged: true };
  const e = res.est || {};
  return { ok: true, html: `<span class="pill ok">${Z("已更新", "อัปเดตแล้ว")}</span> ${Z("到手价", "ราคาสุทธิ")} ฿${e.price_eff ?? "-"}${e.daily != null ? ` · ${Z("日销", "ขาย/วัน")} ${e.daily}` : ""}`, logged: true };
}

async function start() {
  if (running) return;
  running = true; stopFlag = false;
  $("#start").disabled = true; $("#stop").disabled = false; $("#reload").disabled = true;
  msg(Z("巡逻中…不要在巡逻标签页里操作；想停就点「停止」或关掉巡逻标签页。", "กำลังตระเวน… อย่าใช้งานในแท็บตระเวน จะหยุดให้กด「หยุด」หรือปิดแท็บ"), "ok");
  const items = PLAN.items;
  let fails = 0, done = 0, why = "";
  for (let i = 0; i < items.length; i++) {
    if (stopFlag) { why = Z("已停止", "หยุดแล้ว"); break; }
    $("#now").textContent = Z(`第 ${i + 1} / ${items.length} 页`, `หน้า ${i + 1} / ${items.length}`);
    let r;
    try { r = await visit(items[i], i); } catch (e) { r = { ok: false, note: String((e && e.message) || e) }; }
    if (r.stop) { why = r.why || Z("已停止", "หยุดแล้ว"); setRow(i, `<span class="pill">${Z("停止", "หยุด")}</span>`); break; }
    if (r.captcha) {
      setRow(i, `<span class="pill bad">${Z("验证码", "แคปช่า")}</span>`);
      await plog(items[i], false, "遇到验证码，巡逻停止");
      why = "captcha"; break;
    }
    if (r.ok) { fails = 0; done++; setRow(i, r.html); }
    else {
      fails++; setRow(i, `<span class="pill bad">${Z("失败", "ไม่สำเร็จ")}</span> <span class="hint">${esc(r.note || "")}</span>`);
      if (!r.logged) await plog(items[i], false, r.note || "");
      if (fails >= 3) { why = Z("连续 3 页失败", "ไม่สำเร็จติดกัน 3 หน้า"); break; }
    }
    $("#bar").style.width = `${Math.round(((i + 1) / items.length) * 100)}%`;
    if (i < items.length - 1 && !stopFlag) await sleep((2000 + Math.random() * 3000) / SPEED);
  }
  running = false;
  $("#k-done").textContent = `${PLAN.done + done} / ${PLAN.cap}`;
  $("#stop").disabled = true; $("#reload").disabled = false; $("#now").textContent = "";
  if (why === "captcha") msg(Z("⚠️ 遇到验证码，巡逻已停止。请在那个标签页里手动完成验证；今天别再巡逻了，明天把「每天最多巡逻几个页面」调小一点、停留时间调长一点。",
    "⚠️ เจอแคปช่า หยุดตระเวนแล้ว ให้ยืนยันเองในแท็บนั้น วันนี้อย่าตระเวนอีก พรุ่งนี้ลดจำนวนหน้าต่อวันและเพิ่มเวลาที่อยู่แต่ละหน้า"), "err");
  else if (why) msg(Z(`巡逻停止：${esc(why)}。已完成 ${done} 页。`, `หยุดตระเวน: ${esc(why)} ทำเสร็จ ${done} หน้า`), "warn");
  else msg(Z(`✅ 巡逻完成：${done} 页。结果在系统「商品 → 爆款雷达」。`, `✅ ตระเวนเสร็จ ${done} หน้า ดูผลที่「สินค้า → เรดาร์สินค้าขายดี」`), "ok");
}

$("#start").onclick = start;
$("#stop").onclick = () => { stopFlag = true; $("#stop").disabled = true; msg(Z("正在停止…（当前这一页结束后停）", "กำลังหยุด… (หยุดหลังหน้านี้)"), "warn"); };
$("#reload").onclick = load;
chrome.tabs.onRemoved.addListener((id) => { if (id === tabId && running) stopFlag = true; });
load();
