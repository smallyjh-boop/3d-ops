"use strict";
// 选品（v2.50，「商品」菜单的第一个页面）：页面头（大按钮：贴链接采集 / 打开模型站去采集 / 刷新）→ 页签 → 数字卡片 → 明细（说明收进「?」）。
// 界面文字 Z(中文, 泰文)，原始数据（模型名、作者、原站文字）放 data-notr。
// 四个页签 = 四个 ghost 页面 id：cur_cand 候选池 · cur_inbox 采集箱 · cur_queue 采集队列 · cur_watch 关注巡逻（待办 / 提醒里的链接直接打开对的页签）。
// 「采用 / 采集」= 马上建 ERP 产品草稿（许可待核验），先放「采集箱」（v2.50.1，不进产品库），整理好「转入产品库」。
// 上架客服：接口里已经去掉成本、利润、估计售价（api.py _strip），页面上对应的格子也不画。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const SUBS = [["cur_cand", "候选池", "คลังผู้สมัคร"], ["cur_inbox", "采集箱", "กล่องเก็บสินค้า"], ["cur_queue", "采集队列", "คิวเก็บข้อมูล"], ["cur_watch", "关注巡逻", "ตระเวนติดตาม"]];
  const PARTS = () => ({ demand: Z("泰国需求", "ความต้องการไทย"), production: Z("生产效率", "ประสิทธิภาพการผลิต"), profit: Z("利润", "กำไร"),
    competition: Z("竞争少", "แข่งน้อย"), popularity: Z("原站热度", "ความนิยมต้นทาง"), listing: Z("上架难度", "ความง่ายในการลงขาย") });
  const OWN = () => !!(window.ME && ME.role === "owner");
  const n0 = (v) => (v == null || v === "" ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }));
  const scTone = (s, ex) => (ex ? "bad" : s >= 70 ? "ok" : s >= 50 ? "warn" : "");
  const pill = (t, tone, tip) => `<span class="cur-pill ${tone || ""}"${tip ? ` title="${esc(tip)}"` : ""}>${t}</span>`;
  const img = (u, s = 48) => (u ? `<img class="cur-thumb" src="${esc(u)}" referrerpolicy="no-referrer" loading="lazy" style="width:${s}px;height:${s}px" alt="">`
    : `<span class="cur-thumb cur-noimg" style="width:${s}px;height:${s}px"></span>`);
  const link = (u, t) => `<a href="${esc(u)}" target="_blank" rel="noopener" data-notr>${esc(t || u)}</a>`;
  const partTip = (p) => Object.entries(p || {}).map(([k, v]) => `${PARTS()[k] || k} ${v}`).join(" · ");
  const reasonTxt = (r) => (TH() && r.excluded_th ? r.excluded_th : r.excluded);
  const catTxt = (r) => (TH() && r.category_th ? r.category_th : r.category);
  const LS = (k, d) => { try { return JSON.parse(localStorage.getItem("cur_" + k)) ?? d; } catch { return d; } };
  const LSset = (k, v) => { try { localStorage.setItem("cur_" + k, JSON.stringify(v)); } catch { /* 忽略 */ } };
  const EXT_TIP = () => Z("要有一台装了扩展、登录了原站的 Chrome 开着", "ต้องมี Chrome ที่ติดตั้งส่วนขยายและล็อกอินเว็บต้นทางเปิดอยู่");
  let CUR = "cur_cand", OV = null, IN = null;
  let FC = Object.assign({ min: "0", platform: "", cat: "", ex: "", new: "", q: "", status: "open", bad: "" }, LS("fc", {}));
  let IF = LS("ifolder", "all"), IQ = "";
  const SEL = new Set(), ISEL = new Set();

  function sec() { return $("#tab-curate"); }
  async function show(tab) {
    if (tab === "curate") tab = LS("last", "cur_cand");
    if (!SUBS.some(([s]) => s === tab)) tab = "cur_cand";
    if (tab !== CUR) { SEL.clear(); ISEL.clear(); QSEL.clear(); }
    CUR = tab; LSset("last", tab);
    try { OV = await api("/api/cur/overview"); } catch (e) { OV = OV || {}; }
    frame();
    await render();
  }

  // ======================= 页面头：大按钮 + 提醒 + 页签 =======================
  function frame() {
    const s = sec();
    if (!s) return;
    const cnt = { cur_cand: OV.cand, cur_inbox: OV.inbox, cur_queue: OV.queue, cur_watch: OV.watch };
    const ext = OV.ext || {};
    const sitesMenu = (OV.sites || []).map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener" data-notr>${esc(x.name)} ↗</a>`).join("");
    s.querySelector(".cur-top").innerHTML = UX.head(Z("选品", "คัดเลือกสินค้า"),
      `<div class="cur-acts">
        <button class="primary cur-big" data-c-paste>＋ ${Z("贴链接采集", "วางลิงก์เพื่อเก็บ")}</button>
        <details class="cur-sites"><summary>🧩 ${Z("打开模型站去采集", "เปิดเว็บโมเดลเพื่อเก็บ")} ▾</summary>
          <div class="cur-menu">${sitesMenu}<p class="small muted">${Z("装好 ERP 扩展后，搜索页的每个模型左上角有推荐分和「＋ 采集」，点一下就进采集箱。", "ติดตั้งส่วนขยาย ERP แล้ว ทุกโมเดลในหน้าค้นหาจะมีคะแนนและปุ่ม「＋ เก็บ」ที่มุมซ้ายบน กดแล้วเข้ากล่องเก็บสินค้า")}</p></div></details>
        <button data-c-reload title="${esc(Z("刷新", "รีเฟรช"))}">⟳</button></div>`,
      Z("在模型网站找能卖的模型 → 候选池打分（泰国市场排除规则 + AI）→「采用 / 采集」= 马上建产品草稿，先放进「采集箱」（图片、模型文件、文案自动补进来）→ 核验许可、在编辑页补完 →「转入产品库」→「上架」。浏览器扩展（和 AI 客服同一个）在 MakerWorld / Printables / Thingiverse 上显示推荐分和「＋采集」按钮。",
        "หาโมเดลที่ขายได้จากเว็บโมเดล → ให้คะแนน (กฎตลาดไทย + AI) →「ใช้ / เก็บ」= สร้างสินค้าฉบับร่างทันที เข้า「กล่องเก็บสินค้า」ก่อน (รูป ไฟล์โมเดล ข้อความ เติมอัตโนมัติ) → ตรวจสัญญาอนุญาต แก้ไขให้ครบ →「ย้ายเข้าคลังสินค้า」→「ลงขาย」 ส่วนขยายเบราว์เซอร์แสดงคะแนนและปุ่ม「＋เก็บ」บน MakerWorld / Printables / Thingiverse"))
      + (OV.ai === false ? `<div class="warn-box small cur-note">${Z("还没设置 AI（设置 → AI 与对接）：候选只按规则打分，采集的草稿不会自动写文案。", "ยังไม่ได้ตั้งค่า AI (ตั้งค่า → AI และการเชื่อมต่อ): ให้คะแนนตามกฎเท่านั้น และไม่เขียนข้อความให้สินค้าฉบับร่างอัตโนมัติ")}</div>` : "")
      + (!ext.online && OV.waiting ? `<div class="warn-box small cur-note cur-ext-note">⚠ <b>${Z("没有在线的扩展，采集队列不会动", "ไม่มีส่วนขยายออนไลน์ คิวเก็บข้อมูลจะไม่ทำงาน")}</b>（${Z(`${OV.waiting} 个在等`, `รอ ${OV.waiting} รายการ`)}）：${EXT_TIP()}${ext.last ? Z(`。上次在线 ${fmtTime(ext.last)}`, ` ออนไลน์ล่าสุด ${fmtTime(ext.last)}`) : ""}</div>` : "")
      + UX.tabs(SUBS.map(([k, zh, th]) => [k, Z(zh, th), cnt[k] || ""]), CUR, "curate");
  }
  async function render() {
    const box = sec() && sec().querySelector(".cur-body");
    if (!box) return;
    if (!box.innerHTML) box.innerHTML = `<p class="muted">${Z("加载中…", "กำลังโหลด…")}</p>`;
    try {
      if (CUR === "cur_cand") await candPage(box);
      else if (CUR === "cur_inbox") await inboxPage(box);
      else if (CUR === "cur_queue") await queuePage(box);
      else await watchPage(box);
    } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
    floatBar();
  }

  // 勾选了才出现的浮动操作条（像订单页）
  function floatBar() {
    const s = sec();
    if (!s) return;
    let bar = s.querySelector(".cur-float");
    if (!bar) { bar = document.createElement("div"); bar.className = "cur-float hidden"; s.appendChild(bar); }
    let h = "";
    if (CUR === "cur_cand" && SEL.size) {
      h = `<span class="fb-n">${Z("已选", "เลือก")} <b>${SEL.size}</b></span>
        <button class="primary-lite" data-c-bulk="collect">✓ ${Z("采用所选", "ใช้ที่เลือก")}</button>
        <button data-c-bulk="ignore">${Z("忽略所选", "ข้ามที่เลือก")}</button>
        <button data-c-bulk="reread" title="${esc(Z("让扩展重新读这些模型的详情页，改正标题、作者、图片", "ให้ส่วนขยายอ่านหน้ารายละเอียดใหม่ แก้ชื่อ ผู้ออกแบบ รูป"))}">↻ ${Z("重新读取", "อ่านใหม่")}</button>
        <button class="mini" data-c-bulk="clear">✕ ${Z("清除", "ล้าง")}</button>`;
    } else if (CUR === "cur_queue" && QSEL.size) {
      const B = QBULK();
      h = `<span class="fb-n">${Z("已选", "เลือก")} <b>${QSEL.size}</b></span>
        <button data-q-bulk="retry">↻ ${B.retry}</button><button data-q-bulk="hold">⏸ ${B.hold}</button><button data-q-bulk="resume">▶ ${B.resume}</button>
        <button data-q-bulk="top">⤒ ${B.top}</button><button data-q-bulk="up">↑ ${B.up}</button><button data-q-bulk="down">↓ ${B.down}</button><button data-q-bulk="bottom">⤓ ${B.bottom}</button>
        <select data-q-prio><option value="">${Z("优先级…", "ความสำคัญ…")}</option><option value="1">${Z("高", "สูง")}</option><option value="0">${Z("普通", "ปกติ")}</option><option value="-1">${Z("低", "ต่ำ")}</option></select>
        <button data-q-bulk="delete" class="fb-del">${B.delete}</button>
        <button class="mini" data-q-bulk="clear">✕ ${Z("清除", "ล้าง")}</button>`;
    } else if (CUR === "cur_inbox" && ISEL.size) {
      h = `<span class="fb-n">${Z("已选", "เลือก")} <b>${ISEL.size}</b></span>
        <button class="primary-lite" data-i-bulk="to_library">→ ${Z("转入产品库", "ย้ายเข้าคลังสินค้า")}</button>
        <button data-i-bulk="folder">📁 ${Z("移到文件夹", "ย้ายไปโฟลเดอร์")}</button>
        <button data-i-bulk="download">⬇ ${Z("下载模型文件", "ดาวน์โหลดไฟล์โมเดล")}</button>
        <button data-i-bulk="copy">✨ ${Z("AI 写文案", "AI เขียนข้อความ")}</button>
        <button data-i-bulk="delete" class="fb-del">${Z("删除", "ลบ")}</button>
        <button class="mini" data-i-bulk="clear">✕ ${Z("清除", "ล้าง")}</button>`;
    }
    bar.innerHTML = h;
    bar.classList.toggle("hidden", !h);
    s.classList.toggle("cur-has-sel", !!h);
  }

  // ======================= 候选池 =======================
  async function candPage(box) {
    const qs = new URLSearchParams(Object.entries(FC).filter(([, v]) => v !== "" && v != null)).toString();
    const d = await api("/api/cur/candidates?" + qs);
    const k = d.kpi;
    const hist = d.hist.map((v, i) => ({ label: `${i * 10}–${i * 10 + 9}`, value: v, tone: i >= 7 ? "ok" : "" }));
    const plats = [...new Set(d.rows.map((r) => r.platform))];
    for (const id of [...SEL]) if (!d.rows.some((r) => r.id === id)) SEL.delete(id);
    const opt = (v, cur, t) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${t}</option>`;
    box.innerHTML = UX.kpis([
      { label: Z("候选模型", "โมเดลผู้สมัคร"), value: n0(k.total), help: Z("扩展在模型网站列表页上看到、打过分的模型", "โมเดลที่ส่วนขยายเห็นในหน้ารายการและให้คะแนนแล้ว") },
      { label: Z(`高分（≥ ${d.alert_score}）`, `คะแนนสูง (≥ ${d.alert_score})`), value: n0(k.good), tone: k.good ? "ok" : "", go: "cand:hi" },
      { label: Z("今日新品", "ใหม่วันนี้"), value: n0(k.new_today), tone: k.new_today ? "info" : "", go: "cand:new", help: Z("关注巡逻今天新找到的", "ที่ตระเวนเจอใหม่วันนี้") },
      { label: Z("被排除", "ถูกคัดออก"), value: n0(k.excluded), go: "cand:ex", help: Z("儿童玩具（TISI）、宗教、武器、接触食物、成人、品牌 / 动漫角色、打印太久（多色不排除，只扣分）", "ของเล่นเด็ก (มอก.) ศาสนา อาวุธ สัมผัสอาหาร ผู้ใหญ่ แบรนด์ / ตัวการ์ตูน พิมพ์นานเกิน (หลายสีไม่คัดออก แค่หักคะแนน)") },
      k.bad ? { label: Z("采集可能出错", "อาจเก็บข้อมูลผิด"), value: n0(k.bad), tone: "bad", go: "cand:bad", help: Z("列表页读成了作者那一块（标题是作者名、图是头像），不交给 AI 打分", "อ่านส่วนผู้ออกแบบแทนโมเดล (ชื่อเป็นชื่อผู้ออกแบบ รูปเป็นรูปโปรไฟล์) จึงไม่ส่งให้ AI") } : null,
      d.ai ? { label: Z("等 AI 判断", "รอ AI ประเมิน"), value: n0(k.wait_ai), tone: k.wait_ai ? "warn" : "" } : null,
    ]) + (k.bad ? `<div class="warn-box small cur-note cur-badnote">⚠ ${Z(`有 ${k.bad} 个候选采集可能出错（标题是作者 / 店铺名，或缩略图是头像），多半是 Printables 列表页读错了（扩展 3.1.1 已修好）。`, `มี ${k.bad} รายการที่อาจเก็บข้อมูลผิด (ชื่อเป็นชื่อผู้ออกแบบ / ร้าน หรือรูปย่อเป็นรูปโปรไฟล์) ส่วนใหญ่มาจากหน้ารายการ Printables (ส่วนขยาย 3.1.1 แก้แล้ว)`)}
        <button class="mini" data-c-badonly>${FC.bad ? Z("看全部", "ดูทั้งหมด") : Z("只看这些", "ดูเฉพาะรายการนี้")}</button>
        <button class="mini" data-c-rereadbad>↻ ${Z("全部重新读取", "อ่านใหม่ทั้งหมด")}</button>
        <button class="mini" data-c-delbad>✕ ${Z("删除采集错误的", "ลบที่เก็บผิด")}</button></div>` : "")
      + `<div class="cur-grid2">${UX.card({ title: Z("分数分布", "การกระจายคะแนน"), help: Z("不含被排除的。分数 = 六项加权：泰国需求、生产效率、利润、竞争少、原站热度、上架难度（权重在设置 → 商品）", "ไม่รวมที่ถูกคัดออก คะแนน = 6 ด้านถ่วงน้ำหนัก (ตั้งค่า → สินค้า)"),
        body: UX.columns(hist, { h: 90, from: "0", to: "100" }) })}
      ${UX.card({ title: Z("排除原因", "เหตุผลที่คัดออก"), body: UX.bars(d.reasons.map((r) => ({ label: TH() && r.reason_th ? r.reason_th : r.reason, value: r.n, tone: "bad" })), { empty: Z("没有被排除的", "ไม่มีที่ถูกคัดออก") }) })}</div>
      ${UX.card({ title: Z("候选模型", "โมเดลผู้สมัคร"),
        body: `<div class="cur-fbar cur-frow">
          <select data-fc="min" title="${esc(Z("最低分", "คะแนนขั้นต่ำ"))}">${["0", "40", "50", "60", "70", "80"].map((v) => opt(v, FC.min, v === "0" ? Z("全部分数", "ทุกคะแนน") : `≥ ${v}`)).join("")}</select>
          <select data-fc="platform"><option value="">${Z("全部网站", "ทุกเว็บ")}</option>${plats.concat(FC.platform && !plats.includes(FC.platform) ? [FC.platform] : []).map((p) => `<option value="${esc(p)}" ${p === FC.platform ? "selected" : ""} data-notr>${esc((d.rows.find((r) => r.platform === p) || {}).platform_name || p)}</option>`).join("")}</select>
          <select data-fc="cat"><option value="">${Z("全部类目", "ทุกหมวด")}</option>${d.cats.map((c) => `<option value="${esc(c.name)}" ${c.name === FC.cat ? "selected" : ""}>${esc(TH() ? c.th : c.name)}</option>`).join("")}</select>
          <select data-fc="status">${opt("open", FC.status, Z("待处理", "รอดำเนินการ"))}${opt("ignored", FC.status, Z("已忽略", "ข้ามแล้ว"))}${opt("adopted", FC.status, Z("已采用", "ใช้แล้ว"))}${opt("all", FC.status, Z("全部", "ทั้งหมด"))}</select>
          <label class="chk"><input type="checkbox" data-fc="ex" ${FC.ex ? "checked" : ""}> ${Z("含被排除的", "รวมที่ถูกคัดออก")}</label>
          <label class="chk"><input type="checkbox" data-fc="new" ${FC.new ? "checked" : ""}> ${Z("今日新品", "ใหม่วันนี้")}</label>
          <input type="search" data-fc="q" value="${esc(FC.q)}" placeholder="${Z("搜索标题 / 作者", "ค้นหาชื่อ / ผู้ออกแบบ")}">
          <span class="cur-sp"></span><span class="small muted">${Z(`${d.rows.length} 个`, `${d.rows.length} รายการ`)}</span></div>
        ${d.rows.length ? `<div class="cur-wrap"><table class="grid cur-tbl"><thead><tr><th><input type="checkbox" data-c-all ${d.rows.length && d.rows.every((r) => SEL.has(r.id)) ? "checked" : ""}></th><th>${Z("分", "คะแนน")}</th><th>${Z("模型", "โมเดล")}</th>
          <th>${Z("估算", "ประมาณ")}</th><th>${Z("泰国市场", "ตลาดไทย")}</th><th>${Z("AI 判断", "AI ประเมิน")}</th><th></th></tr></thead><tbody>${d.rows.map((r) => candRow(r, d.radar)).join("")}</tbody></table></div>`
          : UX.empty(Z("还没有候选。点上面的「🧩 打开模型站去采集」，装好浏览器扩展（3.1 以上）后打开 MakerWorld / Printables / Thingiverse 的搜索页、分类页，系统会自动给每个模型打分并记到这里；也可以在「关注巡逻」里添加关注让扩展每天自动找。",
            "ยังไม่มีผู้สมัคร กด「🧩 เปิดเว็บโมเดลเพื่อเก็บ」ด้านบน ติดตั้งส่วนขยาย (3.1 ขึ้นไป) แล้วเปิดหน้าค้นหา / หมวดหมู่ของ MakerWorld / Printables / Thingiverse ระบบจะให้คะแนนแต่ละโมเดลอัตโนมัติ หรือเพิ่มการติดตามใน「ตระเวนติดตาม」"))}` })}
      <p class="small muted">${Z("校准：", "การปรับเทียบ: ")}${d.calib.n >= 5 ? Z(`实测时长约是 AI 估算的 ${d.calib.m} 倍、克数 ${d.calib.g} 倍（${d.calib.n} 个样本，其中 ${d.calib.production || 0} 个来自 ERP 生产记录）`, `เวลาจริงประมาณ ${d.calib.m} เท่าของที่ AI ประมาณ กรัม ${d.calib.g} เท่า (${d.calib.n} ตัวอย่าง)`)
        : Z(`要至少 5 个「估算过、又有实测」的模型才开始校准（现在 ${d.calib.n || 0} 个）`, `ต้องมีอย่างน้อย 5 โมเดลที่มีทั้งค่าประมาณและค่าจริงจึงจะปรับเทียบ (ตอนนี้ ${d.calib.n || 0})`)}</p>`;
  }
  function marketCell(mk, radar) {
    if (!mk) {
      return radar === false ? `<a href="#" class="small" data-c-radar title="${esc(Z("运营 → 市场与竞争 → 找新品（爆款雷达）：加泰国平台的搜索词，这里就能看到需求和价格", "การตลาด → หาสินค้าใหม่ (เรดาร์): เพิ่มคำค้นของแพลตฟอร์มไทย แล้วจะเห็นความต้องการและราคาที่นี่"))}">${Z("去雷达查", "ไปดูในเรดาร์")} →</a>`
        : `<span class="muted">—</span>`;
    }
    return `${mk.near ? `<span class="muted">${Z("相近：", "ใกล้เคียง: ")}</span>` : ""}<span data-notr>${esc(mk.keyword)}</span> · ${Z("机会分", "คะแนนโอกาส")} <b>${mk.score}</b>${mk.price_median ? `<div class="muted">${Z("到手价中位", "ราคากลาง")} ฿${n0(mk.price_median)}</div>` : ""}${mk.daily_top10 != null ? `<div class="muted">${Z("前 10 日销", "ขาย/วัน 10 อันดับ")} ${mk.daily_top10}</div>` : ""}${mk.total_results ? `<div class="muted">${Z("结果数", "ผลค้นหา")} ${n0(mk.total_results)}</div>` : ""}`;
  }
  function candRow(r, radar) {
    const tone = scTone(r.score, r.excluded);
    const act = r.product_id ? `<span class="mono" data-p360="${esc(r.product_id)}" data-notr>${esc(r.product_id)}</span> <button class="mini" data-c-prod="${esc(r.product_id)}">${Z("编辑产品", "แก้ไขสินค้า")}</button>`
        : `<button class="mini primary-lite" data-c-collect="${r.id}" title="${esc(Z("马上建产品草稿放进采集箱（许可待核验），扩展在后台读详情页、下载模型文件", "สร้างสินค้าฉบับร่างเข้ากล่องเก็บทันที ส่วนขยายจะอ่านหน้ารายละเอียดและดาวน์โหลดไฟล์เบื้องหลัง"))}">✓ ${Z("采用", "ใช้")}</button> ${r.status === "ignored" ? `<button class="mini" data-c-unignore="${r.id}">${Z("恢复", "คืน")}</button>` : `<button class="mini ghost" data-c-ignore="${r.id}">${Z("忽略", "ข้าม")}</button>`}`;
    const bad = r.capture_bad ? `<div class="small bad">⚠ ${Z("采集可能出错", "อาจเก็บข้อมูลผิด")}：${esc(TH() && r.capture_bad_th ? r.capture_bad_th : r.capture_bad)}
      ${r.refreshing ? pill(Z("正在重新读取", "กำลังอ่านใหม่"), "info") : `<button class="mini" data-c-reread="${r.id}">↻ ${Z("重新读取", "อ่านใหม่")}</button>`}</div>` : "";
    const ai = r.capture_bad ? `<span class="muted">${Z("先改正采集，再让 AI 判断", "แก้ข้อมูลก่อน แล้ว AI จะประเมิน")}</span>`
      : r.ai_error ? `<span class="warn-t"${TH() ? "" : ` title="${esc(r.ai_error)}"`}>${Z("AI 判断出错，只按规则打分", "AI ประเมินผิดพลาด ใช้คะแนนตามกฎ")}</span>`
      : r.ai ? `<span data-notr>${esc(TH() && r.reason_th ? r.reason_th : r.reason || "")}</span>${(r.keywords || []).length ? `<div class="muted" data-notr>${esc(r.keywords.slice(0, 4).join(", "))}</div>` : ""}` : `<span class="muted">${Z("等 AI 判断", "รอ AI")}</span>`;
    return `<tr class="${r.excluded ? "cur-ex" : ""}${r.capture_bad ? " cur-badrow" : ""}"><td><input type="checkbox" data-c-sel="${r.id}" ${SEL.has(r.id) ? "checked" : ""}></td>
      <td><span class="cur-sc ${tone}" title="${esc(partTip(r.parts))}">${Math.round(r.score)}</span></td>
      <td><div class="cur-pic">${img(r.thumb)}<div>${link(r.url, (r.title || r.url).slice(0, 80))}${r.new ? " " + pill(Z("新品", "ใหม่"), "info") : ""}
        <div class="small muted"><span data-notr>${esc(r.platform_name)}${r.author ? " · " + esc(r.author) : ""}</span>${r.category ? ` · <span data-notr>${esc(catTxt(r))}</span>` : ""}</div>
        ${r.excluded ? `<div class="small bad" data-notr>✕ ${esc(reasonTxt(r))}</div>` : ""}${bad}</div></div></td>
      <td class="small nowrap">${r.est ? `<span data-notr>${esc(r.est)}</span> ${r.measured ? pill(Z("实测", "วัดจริง"), "ok") : pill(Z("估", "ประมาณ"), "")}` : "—"}${r.single === false ? `<div title="${Z("多色：能打（P1S + AMS），生产效率和利润分扣一些", "หลายสี: พิมพ์ได้ (P1S + AMS) หักคะแนนประสิทธิภาพและกำไรเล็กน้อย")}">${pill(Z("多色（需要 AMS）", "หลายสี (ต้องมี AMS)"), "warn")}</div>` : ""}${r.price ? `<div class="muted" data-notr>${esc(r.price)}</div>` : ""}</td>
      <td class="small">${marketCell(r.market, radar)}</td>
      <td class="small cur-reason">${ai}</td>
      <td class="nowrap">${act}</td></tr>`;
  }

  // ======================= 采集箱 =======================
  // 采用的模型 = 产品草稿，先放这里（不进产品库）：左边文件夹（全部 · 按类目 · 未分类 · 自己建的文件夹 = 产品分组），右边每个产品的状态和操作。
  const chipFiles = (f) => {
    if (!f) return "";
    if (f.ok) return pill(`📦 ${Z(`已下载 ${f.ok} 个`, `ดาวน์โหลดแล้ว ${f.ok}`)}`, "ok");
    if (f.downloading) return pill(`📦 ${Z("下载中", "กำลังดาวน์โหลด")}`, "info");
    if (f.queued) return pill(`📦 ${f.ext && f.ext.online ? Z("排队下载", "รอดาวน์โหลด") : Z("等扩展下载", "รอส่วนขยาย")}`, "info", f.ext && f.ext.online ? "" : EXT_TIP());
    if (f.failed) return pill(`📦 ${Z("下载失败", "ดาวน์โหลดไม่สำเร็จ")}`, "bad", (f.errors || [])[0] || "");
    if (f.collect === "waiting" || f.collect === "running") return pill(`📦 ${Z("等读详情页", "รออ่านรายละเอียด")}`, "info");
    return pill(`📦 ${Z("没有模型文件", "ไม่มีไฟล์โมเดล")}`, "warn");
  };
  const chipCopy = (c) => (c === "done" ? pill(`✍ ${Z("AI 已写文案", "AI เขียนแล้ว")}`, "ok") : c === "writing" ? pill(`✍ ${Z("文案写作中", "กำลังเขียน")}`, "info") : pill(`✍ ${Z("文案待写", "รอเขียนข้อความ")}`, "warn"));
  const chipLic = (r) => (r.license === "pending" ? pill(`⚖ ${Z("许可待核验", "รอตรวจสัญญาอนุญาต")}`, r.license_auto === "禁止商用" ? "bad" : "warn", r.license_name) : pill(`⚖ ${Z("许可已核验", "ตรวจสัญญาแล้ว")}`, "ok"));
  const chipImg = (r) => (r.images === "source" ? pill(`🖼 ${Z("原站图", "รูปต้นทาง")}`, "warn", Z("原站图片，可能有水印，建议换成自己拍的或去水印", "รูปจากเว็บต้นทาง อาจมีลายน้ำ แนะนำเปลี่ยนเป็นรูปถ่ายเองหรือลบลายน้ำ"))
    : r.images === "own" ? pill(`🖼 ${Z("已换图", "เปลี่ยนรูปแล้ว")}`, "ok") : pill(`🖼 ${Z("没有图片", "ไม่มีรูป")}`, ""));
  async function inboxPage(box) {
    const d = IN = await api("/api/cur/inbox?" + new URLSearchParams({ folder: IF, q: IQ }).toString());
    const f = d.folders;
    for (const id of [...ISEL]) if (!d.rows.some((r) => r.product_id === id)) ISEL.delete(id);
    const fo = (key, label, n, extra = "") => `<div class="cur-fo ${IF === key ? "on" : ""}" data-i-folder="${esc(key)}">${label}<span class="muted">${n}</span>${extra}</div>`;
    const k = d.kpi;
    const ext = d.ext || {};
    box.innerHTML = `<div class="cur-inbox">
      <aside class="card cur-folders">
        ${fo("all", `📥 ${Z("全部", "ทั้งหมด")}`, f.all)}
        <div class="cur-fo-h">${Z("按类目", "ตามหมวด")}</div>
        ${f.cats.map((c) => fo("cat:" + c.name, `<span data-notr>${esc(TH() && c.th ? c.th : c.name)}</span>`, c.n)).join("")}
        ${fo("nocat", Z("未分类", "ยังไม่จัดหมวด"), f.nocat)}
        <div class="cur-fo-h row between">${Z("我的文件夹", "โฟลเดอร์ของฉัน")} <button class="mini" data-i-newfolder>＋</button></div>
        ${f.groups.map((g) => fo("g:" + g.id, `📁 <span data-notr>${esc(g.name)}</span>`, g.n)).join("") || `<div class="small muted">${Z("还没有文件夹（和产品库的分组是同一套，转入产品库后还在）", "ยังไม่มีโฟลเดอร์ (ใช้ร่วมกับกลุ่มสินค้าในคลัง)")}</div>`}
      </aside>
      <div class="cur-in-main">
        ${UX.kpis([
          { label: Z("采集箱里", "ในกล่องเก็บ"), value: n0(k.total), help: Z("采用 / 采集的模型先放在这里，不进产品库；整理好点「转入产品库」", "โมเดลที่ใช้ / เก็บจะอยู่ที่นี่ก่อน ยังไม่เข้าคลังสินค้า จัดให้เรียบร้อยแล้วกด「ย้ายเข้าคลังสินค้า」") },
          { label: Z("许可待核验", "รอตรวจสัญญาอนุญาต"), value: n0(k.lic_pending), tone: k.lic_pending ? "warn" : "ok" },
          { label: Z("还没有模型文件", "ยังไม่มีไฟล์โมเดล"), value: n0(k.no_files), tone: k.no_files ? "warn" : "ok" },
          { label: Z("文案还没写", "ยังไม่มีข้อความ"), value: n0(k.no_copy), tone: k.no_copy ? "warn" : "ok" },
          { label: Z("还在用原站图", "ยังใช้รูปต้นทาง"), value: n0(k.source_img), tone: k.source_img ? "warn" : "ok", help: Z("原站图片可能有水印 / 版权，建议换成自己拍的或去水印", "รูปจากเว็บต้นทางอาจมีลายน้ำ / ลิขสิทธิ์") },
        ])}
        <div class="cur-fbar cur-frow"><input type="search" data-i-q value="${esc(IQ)}" placeholder="${Z("搜索编号 / 品名 / 原站标题 / 作者", "ค้นหารหัส / ชื่อ / ชื่อต้นทาง / ผู้ออกแบบ")}">
          <label class="chk"><input type="checkbox" data-i-all ${d.rows.length && d.rows.every((r) => ISEL.has(r.product_id)) ? "checked" : ""}> ${Z("全选", "เลือกทั้งหมด")}</label>
          <span class="cur-sp"></span>${!ext.online ? `<span class="small warn-t">⚠ ${Z("没有在线的扩展，模型文件不会下载", "ไม่มีส่วนขยายออนไลน์ ไฟล์จะไม่ถูกดาวน์โหลด")}（${EXT_TIP()}）</span>` : `<span class="small ok">● ${Z("扩展在线", "ส่วนขยายออนไลน์")}</span>`}</div>
        ${d.rows.length ? `<div class="cur-cards">${d.rows.map(inboxCard).join("")}</div>`
          : UX.empty(IF === "all" && !IQ ? Z("采集箱是空的。点上面的「＋ 贴链接采集」，或在候选池点「采用」、在模型网站上点扩展的「＋ 采集」。", "กล่องเก็บว่าง กด「＋ วางลิงก์เพื่อเก็บ」ด้านบน หรือกด「ใช้」ในคลังผู้สมัคร / 「＋ เก็บ」บนเว็บโมเดล")
            : Z("这个文件夹里没有", "ไม่มีในโฟลเดอร์นี้"))}
      </div></div>`;
  }
  function inboxCard(r) {
    const g = (IN.folders.groups || []).filter((x) => r.groups.map(String).includes(String(x.id)));
    return `<div class="cur-ic ${ISEL.has(r.product_id) ? "sel" : ""}">
      <label class="cur-ic-sel"><input type="checkbox" data-i-sel="${esc(r.product_id)}" ${ISEL.has(r.product_id) ? "checked" : ""}></label>
      ${img(r.thumb, 76)}
      <div class="cur-ic-main">
        <div><span class="mono" data-p360="${esc(r.product_id)}" data-notr>${esc(r.product_id)}</span> <b data-notr>${esc(r.name || r.title_original)}</b>${r.score != null ? ` <span class="cur-sc ${scTone(r.score)}" title="${esc(Z("推荐分", "คะแนนแนะนำ"))}">${Math.round(r.score)}</span>` : ""}</div>
        <div class="small muted">${r.url ? link(r.url, r.platform || r.url) : ""}${r.author ? ` · <span data-notr>${esc(r.author)}</span>` : ""}${r.category ? ` · <span data-notr>${esc(r.category)}</span>` : ""}${g.map((x) => ` · 📁 <span data-notr>${esc(x.name)}</span>`).join("")}${r.adopted_at ? ` · ${fmtTime(r.adopted_at).slice(0, 10)}` : ""}</div>
        ${r.title_th ? `<div class="small clamp1" data-notr>${esc(r.title_th)}</div>` : ""}
        <div class="cur-chips">${chipFiles(r.files)} ${chipCopy(r.copy)} ${chipLic(r)} ${chipImg(r)}${r.ip ? " " + pill(Z("侵权待确认", "รอยืนยันลิขสิทธิ์"), "bad") : ""}${r.model ? " " + pill("🧊 " + Z("3D 模型", "โมเดล 3D"), "ok") : ""}</div>
      </div>
      <div class="cur-ic-act">
        <button class="mini primary-lite" data-c-prod="${esc(r.product_id)}">✏ ${Z("编辑", "แก้ไข")}</button>
        <button class="mini" data-c-dl="${esc(r.product_id)}">⬇ ${Z("下载模型文件", "ดาวน์โหลดไฟล์โมเดล")}</button>
        ${r.license === "pending" ? `<button class="mini" data-i-lic="${esc(r.product_id)}" data-auto="${esc(r.license_auto)}" data-url="${esc(r.url)}">⚖ ${Z("核验许可", "ตรวจสัญญาอนุญาต")}</button>` : ""}
        <button class="mini" data-i-move="${esc(r.product_id)}">📁 ${Z("移到文件夹", "ย้ายไปโฟลเดอร์")}</button>
        <button class="mini" data-i-to="${esc(r.product_id)}">→ ${Z("转入产品库", "ย้ายเข้าคลังสินค้า")}</button>
        <button class="mini ghost" data-i-del="${esc(r.product_id)}">${Z("删除", "ลบ")}</button>
      </div></div>`;
  }
  async function inboxAction(action, ids, btn) {
    if (!ids.length) return toast(Z("先勾选", "เลือกก่อน"), true);
    if (action === "folder") return moveFolder(ids);
    if (action === "delete" && !confirm(Z(`删除 ${ids.length} 个采集的产品草稿？图片、模型文件一起删；候选池里标成「已忽略」，以后还能恢复重新采用。`, `ลบสินค้าฉบับร่าง ${ids.length} รายการ? รูปและไฟล์จะถูกลบด้วย ในคลังผู้สมัครจะเป็น「ข้ามแล้ว」 กู้คืนได้ภายหลัง`))) return;
    const run = async () => {
      const r = await api("/api/cur/inbox/action", { json: { action, ids } });
      if (action === "to_library") {
        const w = Object.entries(r.warnings || {});
        toast(Z(`已转入产品库 ${r.moved.length} 个`, `ย้ายเข้าคลังสินค้าแล้ว ${r.moved.length} รายการ`) + (w.length ? Z(`；${w.length} 个还有要注意的：`, ` ; ${w.length} รายการยังต้องดู: `) + w.slice(0, 3).map(([id, m]) => `${id} ${m.map(warnTh).join("、")}`).join("；") : ""), !!w.length);
      } else if (action === "delete") toast(Z(`已删除 ${r.deleted} 个`, `ลบแล้ว ${r.deleted} รายการ`));
      else if (action === "copy") toast(Z(`已排队写文案 ${r.queued} 个（后台做，只填空着的）`, `เข้าคิวเขียนข้อความ ${r.queued} รายการ (ทำเบื้องหลัง เติมเฉพาะที่ว่าง)`));
      else if (action === "download") toast(Z(`已排队 ${r.queued} 个文件`, `เข้าคิว ${r.queued} ไฟล์`) + (r.recollect ? Z(`，${r.recollect} 个先重新读详情页`, ` อ่านหน้ารายละเอียดใหม่ ${r.recollect} รายการ`) : "") + (OV && OV.ext && !OV.ext.online ? Z("。现在没有在线的扩展：", " ตอนนี้ไม่มีส่วนขยายออนไลน์: ") + EXT_TIP() : ""));
      ids.forEach((x) => ISEL.delete(x));
      await show(CUR);
    };
    return btn ? busy(btn, run) : run();
  }
  const WARN_TH = { "许可还没核验（核验前不能导出 / 推送）": "ยังไม่ได้ตรวจสัญญาอนุญาต (ส่งออก / ส่งขึ้นแพลตฟอร์มไม่ได้)", "还没有模型文件": "ยังไม่มีไฟล์โมเดล", "还在用原站图片（可能有水印）": "ยังใช้รูปจากเว็บต้นทาง (อาจมีลายน้ำ)" };
  const warnTh = (m) => (TH() ? WARN_TH[m] || m : m);
  function moveFolder(ids) {
    const groups = (IN && IN.folders.groups) || [];
    const box = MODAL.open(`<h3>${Z(`把 ${ids.length} 个移到文件夹`, `ย้าย ${ids.length} รายการไปโฟลเดอร์`)}</h3>
      <p class="small muted">${Z("文件夹和产品库的「分组」是同一套：转入产品库以后还在这个分组里。", "โฟลเดอร์ใช้ร่วมกับ「กลุ่ม」ของคลังสินค้า ย้ายเข้าคลังแล้วยังอยู่ในกลุ่มนี้")}</p>
      <div class="cur-mvlist">${groups.map((g) => `<label class="chk"><input type="radio" name="cur-mv" value="${g.id}"> <span data-notr>${esc(g.name)}</span></label>`).join("")}</div>
      <div class="row gap" style="margin-top:8px"><input data-mv-new placeholder="${esc(Z("或者新建文件夹：名称", "หรือสร้างโฟลเดอร์ใหม่: ชื่อ"))}" style="flex:1"></div>
      <div class="row gap" style="margin-top:10px"><button class="primary" data-mv-go>${Z("移过去", "ย้าย")}</button><button data-mclose>${Z("取消", "ยกเลิก")}</button></div>`);
    box.onclick = async (ev) => {
      const go = ev.target.closest("[data-mv-go]");
      if (!go) return;
      await busy(go, async () => {
        let gid = +((box.querySelector("input[name=cur-mv]:checked") || {}).value || 0);
        const nn = box.querySelector("[data-mv-new]").value.trim();
        if (nn) { const r = await api("/api/groups", { json: { name: nn } }); gid = (r.groups.find((x) => x.name === nn) || {}).id; }
        if (!gid) return toast(Z("选一个文件夹，或填新文件夹的名称", "เลือกโฟลเดอร์ หรือกรอกชื่อโฟลเดอร์ใหม่"), true);
        if (IF.startsWith("g:") && String(IF.slice(2)) !== String(gid)) await api("/api/groups/assign", { json: { ids, group: +IF.slice(2), add: false } });
        await api("/api/groups/assign", { json: { ids, group: gid, add: true } });
        MODAL.close(); toast(Z("已移到文件夹", "ย้ายไปโฟลเดอร์แล้ว")); ISEL.clear(); render();
      });
    };
  }

  // ======================= 采集队列 =======================
  // 采用的模型：扩展读详情页、下载文件、ERP 处理（模型库、规格、文案）走到哪一步，许可核验了没有；每个产品都能「⬇ 下载模型文件」「手动上传」。
  function fileStatus(fs) {
    if (!fs) return "—";
    const ext = fs.ext || {};
    const p = [];
    if (fs.ok) p.push(`<span class="ok">✓ ${Z(`已下载 ${fs.ok} 个`, `ดาวน์โหลดแล้ว ${fs.ok}`)}</span>`);
    if (fs.downloading) p.push(`<span class="info-t">⏳ ${Z(`下载中 ${fs.downloading} 个`, `กำลังดาวน์โหลด ${fs.downloading}`)}</span>`);
    if (fs.queued) p.push(ext.online ? `<span class="info-t">⏳ ${Z(`排队 ${fs.queued} 个`, `รอคิว ${fs.queued}`)}</span>` : `<span class="warn-t" title="${esc(EXT_TIP())}">⏳ ${Z(`等扩展 ${fs.queued} 个`, `รอส่วนขยาย ${fs.queued}`)}</span>`);
    if (fs.failed) p.push(`<span class="bad">✕ ${Z(`失败 ${fs.failed} 个`, `ไม่สำเร็จ ${fs.failed}`)}</span>${(fs.errors || [])[0] ? `<div class="muted" data-notr>${esc(fs.errors[0].slice(0, 110))}</div>` : ""}`);
    if (!p.length) p.push(fs.collect === "waiting" || fs.collect === "running" ? `<span class="${ext.online ? "info-t" : "warn-t"}">${ext.online ? Z("等读详情页", "รออ่านรายละเอียด") : Z("等扩展读详情页", "รอส่วนขยายอ่านรายละเอียด")}</span>`
      : fs.none ? `<span class="muted">${Z(`${fs.none} 个没下载`, `${fs.none} ไฟล์ยังไม่ดาวน์โหลด`)}</span>` : `<span class="muted">${Z("还没有模型文件", "ยังไม่มีไฟล์โมเดล")}</span>`);
    return p.join(" · ");
  }
  // v2.51.x（扩展 3.1.2）：上面「现在」——速度（个 / 分钟）、还要多久、扩展正在做什么（下载进度）、每个网站的节奏和暂停（「继续」）；
  // 中间「任务」——详情页和文件下载的任务列表：勾选（全选 / 按网站 / 按状态）→ 浮动条批量删除、重试、暂停 / 继续、置顶 / 提前 / 推后 / 置底、优先级；等着的可以拖动排序。
  const QSEL = new Set();
  let QF = Object.assign({ lane: "", site: "", state: "" }, LS("qf", {})), QD = null, QDRAG = null, QTIMER = null;
  const REASON = () => ({
    risk: Z("原站要人机验证 / 说请求太频繁：这个网站自动暂停，到时间自动继续", "เว็บต้นทางขอยืนยันตัวตน / แจ้งว่าถี่เกินไป: หยุดเว็บนี้อัตโนมัติ ครบเวลาจะทำต่อเอง"),
    login: Z("原站要求登录：在装了扩展的 Chrome 里登录原站，再点「重试」", "เว็บต้นทางให้ล็อกอิน: ล็อกอินใน Chrome ที่ติดตั้งส่วนขยาย แล้วกด「ลองใหม่」"),
    missing: Z("原站上找不到了（可能被作者删掉或改成私密）", "ไม่พบในเว็บต้นทาง (ผู้ออกแบบอาจลบหรือซ่อน)"),
    timeout: Z("扩展读了几次都没读完（Chrome 关了、电脑睡了，或页面太慢）：可以点「重试」", "ส่วนขยายอ่านหลายครั้งไม่สำเร็จ (ปิด Chrome / คอมพักเครื่อง / หน้าช้า): กด「ลองใหม่」ได้"),
    stall: Z("下载了几次都中断了（Chrome 关了、电脑睡了或网络断了）：可以点「重试」", "ดาวน์โหลดหลายครั้งแต่ขาดกลางทาง: กด「ลองใหม่」ได้"),
    detail: Z("页面上没读到模型资料（可能没加载完或网站改版了）：可以点「重试」", "อ่านข้อมูลโมเดลจากหน้าไม่ได้ (โหลดไม่เสร็จหรือเว็บเปลี่ยน): กด「ลองใหม่」ได้"),
    file: Z("下载失败：可以点「重试」", "ดาวน์โหลดไม่สำเร็จ: กด「ลองใหม่」ได้"),
    retry: Z("上次没做完，已放回队列，会自动再试", "ครั้งก่อนไม่เสร็จ ใส่กลับเข้าคิวแล้ว จะลองใหม่อัตโนมัติ"),
    gone: Z("候选 / 产品草稿已删除，任务自动取消", "ผู้สมัคร / สินค้าฉบับร่างถูกลบแล้ว ยกเลิกงานอัตโนมัติ"),
    removed: Z("已从队列删除", "ลบออกจากคิวแล้ว"),
  });
  const QSTATE = () => ({ waiting: Z("等待", "รอ"), queued: Z("等待", "รอ"), running: Z("正在读", "กำลังอ่าน"), downloading: Z("下载中", "กำลังดาวน์โหลด"),
    failed: Z("失败", "ไม่สำเร็จ"), canceled: Z("已取消", "ยกเลิกแล้ว") });
  const PRIO = () => ({ 1: Z("高", "สูง"), 0: Z("普通", "ปกติ"), "-1": Z("低", "ต่ำ") });
  const mb = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB");
  const dur = (s) => (s < 90 ? Z(`${Math.max(1, Math.round(s))} 秒`, `${Math.max(1, Math.round(s))} วินาที`) : s < 5400 ? Z(`约 ${Math.round(s / 60)} 分钟`, `~${Math.round(s / 60)} นาที`)
    : Z(`约 ${Math.floor(s / 3600)} 小时 ${Math.round((s % 3600) / 60)} 分`, `~${Math.floor(s / 3600)} ชม. ${Math.round((s % 3600) / 60)} นาที`));
  const bar = (got, total) => (total ? `<div class="cur-prog"><i style="width:${Math.min(100, Math.round((got / total) * 100))}%"></i></div><span class="small muted">${Math.min(100, Math.round((got / total) * 100))}% · ${mb(got)} / ${mb(total)}</span>`
    : got ? `<span class="small muted">${mb(got)}</span>` : "");
  function reasonHtml(j) {
    if (!j.message) return "";
    const t = REASON()[j.code];
    return `<div class="small ${j.state === "failed" ? "bad" : "muted"}">${t ? esc(t) : `<span data-notr>${esc(j.message.slice(0, 160))}</span>`}</div>`
      + (t && j.detail ? `<div class="small muted" data-notr title="${esc(j.message)}">${esc(j.detail.slice(0, 120))}</div>` : "");
  }
  function siteLine(s, lane) {
    const x = s[lane];
    const p = [`${x.running}/${x.conc} ${lane === "detail" ? Z("在读", "กำลังอ่าน") : Z("在下载", "กำลังดาวน์โหลด")}`];
    if (x.left) p.push(Z(`还有 ${x.left} 个`, `เหลือ ${x.left}`));
    if (x.left && x.next_in && !s.held && !s.until) p.push(Z(`${x.next_in} 秒后下一个`, `อีก ${x.next_in} วินาทีถัดไป`));
    p.push(Z(`这小时 ${x.hour}/${x.cap}`, `ชั่วโมงนี้ ${x.hour}/${x.cap}`));
    return p.join(" · ");
  }
  function nowCard(st) {
    const doing = st.doing || [];
    const act = doing.length ? `<table class="grid small"><tbody>${doing.map((x) => `<tr><td class="nowrap">${x.lane === "detail" ? "📄 " + Z("读详情页", "อ่านหน้ารายละเอียด") : "⬇ " + Z("下载", "ดาวน์โหลด")}</td>
        <td><span data-notr>${esc(String(x.title).slice(0, 70))}</span> <span class="muted" data-notr>${esc(x.site_name)}</span></td>
        <td class="nowrap">${x.lane === "file" ? bar(x.got, x.total) : ""}</td><td class="nowrap muted">${dur(x.secs)}</td></tr>`).join("")}</tbody></table>`
      : `<p class="small muted">${st.left.detail + st.left.file ? (st.paused ? Z("采集队列已暂停", "หยุดคิวไว้") : (st.blocked || []).length === (st.sites || []).filter((s) => s.detail.left + s.file.left).length && (st.blocked || []).length
        ? Z("有活的网站都暂停了（看下面）", "เว็บที่มีงานหยุดอยู่ทั้งหมด (ดูด้านล่าง)") : Z("在按节奏等下一个（几秒）", "กำลังรอจังหวะถัดไป (ไม่กี่วินาที)")) : Z("没有要做的", "ไม่มีงาน")}</p>`;
    const sites = (st.sites || []).filter((s) => s.detail.left || s.file.left || s.held || s.until || s.detail.running || s.file.running);
    const srows = sites.length ? `<table class="grid small cur-sitetbl"><tbody>${sites.map((s) => `<tr><td data-notr><b>${esc(s.name)}</b></td>
        <td>${s.held ? UX.dot("warn", Z("手动暂停", "หยุดเอง")) : s.until ? UX.dot("bad", Z("风控暂停到 ", "หยุดกันบล็อกถึง ") + fmtTime(s.until).slice(11, 16)) : UX.dot("ok", Z("正常", "ปกติ"))}
          ${s.factor > 1 ? `<span class="muted">${Z("减速", "ลดความเร็ว")} ×${s.factor}</span>` : ""}${s.until && s.reason ? `<div class="muted small" data-notr>${esc(s.reason)}</div>` : ""}</td>
        <td>📄 ${siteLine(s, "detail")}<br>⬇ ${siteLine(s, "file")}</td>
        <td class="nowrap">${s.held || s.until || s.factor > 1 ? `<button class="mini primary-lite" data-q-site="${esc(s.key)}" data-on="0">▶ ${Z("继续", "ทำต่อ")}</button>` : `<button class="mini" data-q-site="${esc(s.key)}" data-on="1">⏸ ${Z("暂停", "หยุด")}</button>`}</td></tr>`).join("")}</tbody></table>` : "";
    const pace = st.pacing || {};
    return UX.card({ title: Z("现在", "ตอนนี้"), right: `<button class="mini" data-q-act="${st.paused ? "resume" : "pause"}">${st.paused ? "▶ " + Z("继续全部", "ทำต่อทั้งหมด") : "⏸ " + Z("暂停全部", "หยุดทั้งหมด")}</button>`,
      help: Z(`扩展有活就一直做：详情页、文件下载两条线同时进行，每个网站同时最多读 ${(pace.detail || {}).conc || 2} 个详情页、下载 ${(pace.file || {}).conc || 2} 个文件；同一个网站两次之间随机停 ${((pace.detail || {}).gap || []).join("–")} 秒（详情页）/ ${((pace.file || {}).gap || []).join("–")} 秒（文件），像人在点。遇到人机验证 / 请求太频繁，这个网站自动暂停（30 分钟，6 小时内再出现 2 小时），确认原站能正常打开可以点「继续」。速度和上限在「设置 → 商品」里改。`,
        `ส่วนขยายทำงานต่อเนื่องเมื่อมีงาน: อ่านรายละเอียดและดาวน์โหลดพร้อมกัน แต่ละเว็บอ่านพร้อมกันได้ ${(pace.detail || {}).conc || 2} หน้า ดาวน์โหลด ${(pace.file || {}).conc || 2} ไฟล์ เว้นช่วงสุ่ม ${((pace.detail || {}).gap || []).join("–")} / ${((pace.file || {}).gap || []).join("–")} วินาทีเหมือนคนกด เจอแคปช่า / ถี่เกินไปจะหยุดเว็บนั้นอัตโนมัติ เปิดเว็บต้นทางได้ปกติแล้วกด「ทำต่อ」ได้ ปรับความเร็วและเพดานได้ใน「ตั้งค่า → สินค้า」`),
      body: act + srows });
  }
  function jobRow(j) {
    const wait = j.state === "waiting" || j.state === "queued";
    return `<tr data-qj="${j.id}" class="${QSEL.has(j.id) ? "cur-qsel" : ""}${j.held ? " muted" : ""}"${wait ? ` draggable="true"` : ""}>
      <td><input type="checkbox" data-q-sel="${j.id}" ${QSEL.has(j.id) ? "checked" : ""}></td>
      <td class="cur-drag">${wait ? `<span title="${esc(Z("拖动排序", "ลากเพื่อเรียง"))}">⋮⋮</span>` : ""}</td>
      <td>${j.lane === "detail" ? "📄" : "⬇"} ${link(j.url, String(j.title || j.url).slice(0, 70))}${j.refresh ? " " + pill(Z("重新读取候选", "อ่านผู้สมัครใหม่"), "") : ""}
        <div class="small muted"><span data-notr>${esc(j.site_name)}</span>${j.product_id ? ` · <span class="mono" data-p360="${esc(j.product_id)}" data-notr>${esc(j.product_id)}</span>` : ""}${j.product_title && j.lane === "file" ? ` <span data-notr>${esc(String(j.product_title).slice(0, 40))}</span>` : ""}${j.size ? ` · <span data-notr>${esc(j.size)}</span>` : ""}</div></td>
      <td>${pill(QSTATE()[j.state] || j.state, j.state === "failed" ? "bad" : j.state === "running" || j.state === "downloading" ? "info" : "")}${j.held ? " " + pill("⏸ " + Z("已暂停", "หยุดไว้"), "warn") : ""}
        ${j.state === "downloading" ? `<div>${bar(j.got, j.total)}</div>` : j.secs ? `<div class="small muted">${dur(j.secs)}</div>` : ""}${reasonHtml(j)}</td>
      <td>${j.prio ? pill(PRIO()[j.prio], j.prio > 0 ? "info" : "") : ""}</td>
      <td class="nowrap">${wait ? `<button class="mini ghost" data-q-one="up" data-q="${j.id}" title="${esc(Z("提前", "เลื่อนขึ้น"))}">↑</button><button class="mini ghost" data-q-one="down" data-q="${j.id}" title="${esc(Z("推后", "เลื่อนลง"))}">↓</button>` : ""}
        ${j.state === "failed" || j.state === "canceled" ? `<button class="mini" data-q-one="retry" data-q="${j.id}">↻ ${Z("重试", "ลองใหม่")}</button>`
          : wait ? `<button class="mini" data-q-one="${j.held ? "resume" : "hold"}" data-q="${j.id}">${j.held ? "▶ " + Z("继续", "ทำต่อ") : "⏸ " + Z("暂停", "หยุด")}</button>` : ""}</td></tr>`;
  }
  function jobsCard(d) {
    const st = d.status || {};
    const jobs = d.jobs || [];
    const sitesSel = (st.sites || []).map((s) => `<option value="${esc(s.key)}" ${QF.site === s.key ? "selected" : ""} data-notr>${esc(s.name)}</option>`).join("");
    const seg = [["", Z("全部", "ทั้งหมด")], ["waiting", Z("等待", "รอ")], ["running", Z("进行中", "กำลังทำ")], ["held", Z("已暂停", "หยุดไว้")], ["failed", Z("失败", "ไม่สำเร็จ")]];
    const nFail = jobs.filter((j) => j.state === "failed" || j.state === "canceled").length;
    return UX.card({ title: Z(`任务 · ${jobs.length}`, `งาน · ${jobs.length}`),
      right: `<button class="mini" data-q-clean title="${esc(Z("候选 / 产品已删除的任务取消；失败的详情页任务拿掉；失败的下载变回「没下载」（产品上还能重新下载）", "ยกเลิกงานของผู้สมัคร / สินค้าที่ถูกลบ ลบงานที่ไม่สำเร็จออก ไฟล์ที่ดาวน์โหลดไม่สำเร็จกลับเป็น「ยังไม่ดาวน์โหลด」"))}">🧹 ${Z("清理失败 / 无效任务", "ล้างงานที่ไม่สำเร็จ / ใช้ไม่ได้")}${nFail ? ` (${nFail})` : ""}</button>`,
      help: Z("扩展按这里的顺序领活：优先级高的先做，同一优先级按队列顺序。勾选后用下面的浮动条批量操作；等着的任务可以按住 ⋮⋮ 拖动排序。删除下载任务只是不下载这个文件，产品草稿不动。",
        "ส่วนขยายรับงานตามลำดับนี้: ความสำคัญสูงก่อน ความสำคัญเท่ากันตามลำดับคิว เลือกแล้วใช้แถบลอยด้านล่าง งานที่รอลาก ⋮⋮ เพื่อเรียงได้ ลบงานดาวน์โหลดคือไม่ดาวน์โหลดไฟล์นั้น สินค้าฉบับร่างไม่เปลี่ยน"),
      body: `<div class="cur-fbar"><select data-qf="lane"><option value="">${Z("详情页 + 文件", "รายละเอียด + ไฟล์")}</option><option value="detail" ${QF.lane === "detail" ? "selected" : ""}>📄 ${Z("详情页", "หน้ารายละเอียด")}</option><option value="file" ${QF.lane === "file" ? "selected" : ""}>⬇ ${Z("文件下载", "ดาวน์โหลดไฟล์")}</option></select>
          <select data-qf="site"><option value="">${Z("全部网站", "ทุกเว็บ")}</option>${sitesSel}</select>
          <span class="seg">${seg.map(([k, t]) => `<button data-qf-state="${k}" class="${QF.state === k ? "on" : ""}">${t}</button>`).join("")}</span>
          <label class="chk"><input type="checkbox" data-q-all ${jobs.length && jobs.every((j) => QSEL.has(j.id)) ? "checked" : ""}> ${Z("全选（这个筛选下的）", "เลือกทั้งหมด (ตามตัวกรอง)")}</label></div>`
        + (jobs.length ? `<div class="cur-wrap"><table class="grid cur-tbl cur-jobs"><thead><tr><th></th><th></th><th>${Z("任务", "งาน")}</th><th>${Z("状态", "สถานะ")}</th><th>${Z("优先级", "ความสำคัญ")}</th><th></th></tr></thead><tbody>${jobs.map(jobRow).join("")}</tbody></table></div>`
          : UX.empty(Z("没有任务", "ไม่มีงาน"))) });
  }
  async function queuePage(box) {
    const qs = new URLSearchParams(Object.entries(QF).filter(([, v]) => v)).toString();
    const d = await api("/api/cur/queue" + (qs ? "?" + qs : ""));
    QD = d;
    for (const id of [...QSEL]) if (!d.jobs.some((j) => j.id === id)) QSEL.delete(id);
    const k = d.kpi, ext = d.ext || {}, st = d.status || {};
    const step = (ok, zh, th) => pill((ok ? "✓ " : "· ") + Z(zh, th), ok ? "ok" : "");
    const CS = () => ({ waiting: Z("等读详情页", "รออ่านหน้ารายละเอียด"), running: Z("正在读取", "กำลังอ่าน"), done: Z("详情已读", "อ่านแล้ว"), failed: Z("读取失败", "อ่านไม่สำเร็จ"), canceled: Z("已取消", "ยกเลิก") });
    const extH = ext.online ? `<span class="small ok">● ${Z("扩展在线", "ส่วนขยายออนไลน์")}</span>` : `<span class="small warn-t">⚠ ${Z("没有在线的扩展", "ไม่มีส่วนขยายออนไลน์")}：${EXT_TIP()}</span>`;
    const left = (st.left || {}).detail + (st.left || {}).file;
    box.innerHTML = UX.kpis([
      { label: Z("速度", "ความเร็ว"), value: st.rate && st.rate.total ? `${st.rate.total.toFixed(1)}` : "—", sub: Z(`个 / 分钟 · 10 分钟做完 ${(st.rate || {}).done_10m || 0} 个`, `รายการ/นาที · 10 นาทีเสร็จ ${(st.rate || {}).done_10m || 0}`),
        tone: st.rate && st.rate.total ? "ok" : "", help: Z("最近 10 分钟扩展做完的详情页 + 文件", "หน้ารายละเอียด + ไฟล์ที่ส่วนขยายทำเสร็จใน 10 นาทีล่าสุด") },
      { label: Z("还要多久", "อีกนานเท่าไร"), value: left ? (st.eta ? dur(st.eta) : "—") : Z("做完了", "เสร็จแล้ว"), tone: left ? "" : "ok",
        help: Z("按现在的速度（没有实测时按节奏估）算的，包括风控暂停剩下的时间", "คำนวณจากความเร็วตอนนี้ (ยังไม่มีข้อมูลจริงคิดจากจังหวะ) รวมเวลาหยุดกันบล็อกที่เหลือ") },
      { label: Z("等读详情页", "รออ่านหน้ารายละเอียด"), value: n0(k.waiting), sub: st.paused ? Z("已暂停", "หยุดชั่วคราว") : "", tone: st.paused ? "warn" : "",
        help: Z("采用以后，装了 ERP 扩展的 Chrome 在后台标签页打开原站详情页，读图片、描述、许可证、文件链接，补进产品草稿", "หลังจากกดใช้ Chrome ที่ติดตั้งส่วนขยายจะเปิดหน้ารายละเอียดเบื้องหลัง อ่านรูป คำอธิบาย สัญญาอนุญาต ลิงก์ไฟล์ แล้วเติมลงสินค้าฉบับร่าง") },
      { label: Z("文件等下载", "ไฟล์รอดาวน์โหลด"), value: n0(k.files), help: Z("扩展用浏览器里原站的登录状态下载，上传后直接进产品的模型库", "ส่วนขยายดาวน์โหลดด้วยการล็อกอินเว็บต้นทางในเบราว์เซอร์ แล้วใส่ในคลังโมเดลของสินค้า") },
      { label: Z("下载失败", "ดาวน์โหลดไม่สำเร็จ"), value: n0(k.failed), tone: k.failed ? "bad" : "" },
      { label: Z("许可待核验", "รอตรวจสัญญาอนุญาต"), value: n0(k.lic_pending), tone: k.lic_pending ? "warn" : "ok", help: Z("核验前产品不能导出、不能推送到平台。在产品编辑页上面点「核验通过」", "ก่อนตรวจ สินค้าส่งออก / ส่งขึ้นแพลตฟอร์มไม่ได้ กด「ตรวจผ่าน」ที่หน้าแก้ไขสินค้า") },
      { label: Z("扩展", "ส่วนขยาย"), value: ext.online ? Z("在线", "ออนไลน์") : Z("不在线", "ออฟไลน์"), tone: ext.online ? "ok" : "warn", sub: !ext.online && ext.last ? Z("上次 ", "ล่าสุด ") + fmtTime(ext.last).slice(5, 16) : "", help: EXT_TIP() },
    ]) + nowCard(st) + jobsCard(d)
      + `${UX.card({ title: Z("采用的产品草稿", "สินค้าฉบับร่างที่ใช้"), right: extH, help: Z("采用就是产品草稿（先在采集箱）：用 ERP 的编辑页补颜色、主图、类目属性、售价；模型文件在产品的模型库；许可核验过、上架检查通过才能导出 / 推送。没有模型文件的点「⬇ 下载模型文件」（扩展用原站登录状态下载），或者自己「⬆ 手动上传」。",
          "กดใช้แล้วเป็นสินค้าฉบับร่าง (อยู่ในกล่องเก็บก่อน) แก้ไขด้วยหน้าแก้ไขของ ERP ไฟล์อยู่ในคลังโมเดลของสินค้า ไม่มีไฟล์กด「⬇ ดาวน์โหลดไฟล์โมเดล」หรือ「⬆ อัปโหลดเอง」"),
        body: d.rows.length ? `<div class="cur-wrap"><table class="grid cur-tbl"><thead><tr><th>${Z("产品", "สินค้า")}</th><th>${Z("许可", "สัญญาอนุญาต")}</th><th>${Z("进度", "ความคืบหน้า")}</th><th>${Z("模型文件", "ไฟล์โมเดล")}</th><th></th></tr></thead><tbody>
          ${d.rows.map((r) => { const f = r.files || {}; const fs = r.fstat || {};
            return `<tr><td><div class="cur-pic">${img(r.thumb)}<div><span class="mono" data-p360="${esc(r.product_id)}" data-notr>${esc(r.product_id)}</span> <b data-notr>${esc(r.name)}</b>${r.inbox ? " " + pill(Z("采集箱", "กล่องเก็บ"), "info") : ""}
              <div class="small muted">${link(r.url, r.platform)} · ${fmtTime(r.adopted_at)}${r.adopted_by ? ` · <span data-notr>${esc(r.adopted_by)}</span>` : ""}</div></div></div></td>
              <td>${r.license === "pending" ? pill(Z("许可待核验", "รอตรวจสัญญาอนุญาต"), r.license_auto === "禁止商用" ? "bad" : "warn") : pill("✓ " + Z("已核验", "ตรวจแล้ว"), "ok")}${r.license_name ? `<div class="small muted" data-notr>${esc(r.license_name)}</div>` : ""}${r.ip ? `<div>${pill(Z("侵权待确认", "รอยืนยันลิขสิทธิ์"), "bad")}</div>` : ""}</td>
              <td class="small">${r.collect && r.collect !== "done" ? pill(CS()[r.collect] || r.collect, r.collect === "failed" ? "bad" : "info") + " " : step(r.collect === "done", "详情", "รายละเอียด") + " "}${step((f.img_ok || 0) > 0, "图片", "รูป")} ${step(r.model, "3D 模型", "โมเดล 3D")} ${step(r.specs > 0, `规格 ${r.specs || ""}`, `ตัวเลือก ${r.specs || ""}`)} ${step(r.copy, "文案", "ข้อความ")}</td>
              <td class="small cur-fcell">${fileStatus(fs)}</td>
              <td class="nowrap cur-qact"><button class="mini" data-c-prod="${esc(r.product_id)}">${Z("编辑产品", "แก้ไขสินค้า")}</button>
                <button class="mini primary-lite" data-c-dl="${esc(r.product_id)}" title="${esc(Z("让扩展用原站的登录状态下载这个模型的文件（还没有文件链接就先重新读详情页）", "ให้ส่วนขยายดาวน์โหลดไฟล์ด้วยการล็อกอินเว็บต้นทาง"))}">${fs.failed ? `↻ ${Z("重新下载", "ดาวน์โหลดใหม่")}` : `⬇ ${Z("下载模型文件", "ดาวน์โหลดไฟล์โมเดล")}`}</button>
                <label class="filebtn mini" title="${esc(Z("自己上传 STL / 3MF / ZIP，和下载的一样做 ERP 分析", "อัปโหลด STL / 3MF / ZIP เอง วิเคราะห์เหมือนไฟล์ที่ดาวน์โหลด"))}">⬆ ${Z("手动上传", "อัปโหลดเอง")}<input type="file" data-c-up="${esc(r.product_id)}" multiple accept=".stl,.3mf,.zip,.obj,.step,.stp" hidden></label></td></tr>`; }).join("")}</tbody></table></div>`
          : UX.empty(Z("还没有采用过模型：在「候选池」里点「采用」，或在模型网站上点扩展的「＋采集」。", "ยังไม่เคยใช้โมเดล: กด「ใช้」ในคลังผู้สมัคร หรือกด「＋เก็บ」ของส่วนขยายบนเว็บโมเดล")) })}
      ${UX.card({ title: Z("每天采用（14 天）", "ใช้ต่อวัน (14 วัน)"), body: UX.columns(d.days.map((x) => ({ label: x.day, value: x.n, tone: "ok" })), { h: 90, from: d.days[0].day, to: d.days[d.days.length - 1].day }) })}`;
    // 有活时每 6 秒自己刷新（速度、进度、扩展在做什么）；拖动、勾选不受影响（勾选记在 QSEL 里）
    clearTimeout(QTIMER);
    if (left || (st.doing || []).length) QTIMER = setTimeout(() => { if (CUR === "cur_queue" && !QDRAG && !document.hidden && sec() && sec().offsetParent) render(); }, 6000);
  }
  async function qAction(ids, action, extra) {
    const r = await api("/api/cur/jobs/action", { json: { ids, action, ...(extra || {}) } });
    return r;
  }
  const QBULK = () => ({ delete: Z("删除", "ลบ"), retry: Z("重试", "ลองใหม่"), hold: Z("暂停", "หยุด"), resume: Z("继续", "ทำต่อ"), top: Z("置顶", "ขึ้นบนสุด"),
    up: Z("提前", "เลื่อนขึ้น"), down: Z("推后", "เลื่อนลง"), bottom: Z("置底", "ลงล่างสุด") });

  // ======================= 关注巡逻 =======================
  async function watchPage(box) {
    const d = await api("/api/cur/watches");
    const cw = d.cfg;
    const kinds = d.kinds;
    box.innerHTML = UX.kpis([
      { label: Z("关注中", "กำลังติดตาม"), value: n0(d.rows.filter((r) => r.enabled).length) },
      { label: Z("今日新品", "ใหม่วันนี้"), value: n0(d.new_today), tone: d.new_today ? "info" : "", go: "cand:new" },
      { label: Z("采集队列", "คิวเก็บข้อมูล"), value: n0(d.collect.waiting), sub: d.collect.paused ? Z("已暂停", "หยุดชั่วคราว") : "", tone: d.collect.paused ? "warn" : "", go: "tab:cur_queue" },
      { label: Z("文件等下载", "ไฟล์รอดาวน์โหลด"), value: n0(d.files_waiting), go: "tab:cur_queue" },
      { label: Z("暂停的网站", "เว็บที่หยุดชั่วคราว"), value: n0(d.pace.filter((p) => p.paused).length), tone: d.pace.some((p) => p.paused) ? "bad" : "ok" },
    ]) + `<div class="cur-grid2">${UX.card({ title: Z("每天找到的新模型（14 天）", "โมเดลใหม่ต่อวัน (14 วัน)"), body: UX.columns(d.days.map((x) => ({ label: x.day, value: x.new })), { h: 90, from: d.days[0].day, to: d.days[d.days.length - 1].day }) })}
      ${UX.card({ title: Z("各网站的节奏", "จังหวะของแต่ละเว็บ"), help: Z("扩展模仿人的速度：页面之间、文件之间随机停一会儿，每个网站每小时下载有上限、每天巡逻有上限；一出现人机验证 / 请求太频繁就自动减速并暂停这个网站 30 分钟（6 小时内再出现暂停 2 小时）。确认原站能正常打开后可以点「恢复」。",
        "ส่วนขยายทำงานเหมือนคน: หยุดสุ่มระหว่างหน้าและไฟล์ จำกัดจำนวนต่อชั่วโมง / ต่อวัน ถ้าเจอแคปช่าหรือถูกจำกัดจะลดความเร็วและหยุดเว็บนั้น 30 นาที (ซ้ำใน 6 ชม. หยุด 2 ชม.)"),
        body: `<table class="grid small"><tbody>${d.pace.map((p) => `<tr><td data-notr>${esc(p.name)}</td><td>${p.paused ? UX.dot("bad", Z("暂停到 ", "หยุดถึง ") + fmtTime(p.until).slice(11)) : UX.dot("ok", Z("正常", "ปกติ"))}${p.reason ? `<div class="muted" data-notr>${esc(p.reason)}</div>` : ""}</td>
          <td>${Z("今天巡逻", "ตระเวนวันนี้")} ${p.pages_today}/${p.daily_cap}</td><td>${Z("这小时下载", "ดาวน์โหลดชั่วโมงนี้")} ${p.hour_count}/${p.cap}${p.factor > 1 ? ` · ${Z("减速", "ลดความเร็ว")} ×${p.factor}` : ""}</td>
          <td>${p.paused || p.factor > 1 ? `<button class="mini" data-w-reset="${esc(p.key)}">${Z("恢复", "คืนค่า")}</button>` : ""}</td></tr>`).join("")}</tbody></table>
          <p class="small muted">${Z("速度档位：", "ระดับความเร็ว: ")}${esc(TH() ? d.speeds[d.speed][1] : d.speeds[d.speed][0])} · ${cw.enabled ? Z(`巡逻：每个网站每天最多 ${cw.daily_cap} 页，页面之间隔 ${cw.gap_min}–${cw.gap_max} 分钟`, `ตระเวน: เว็บละไม่เกิน ${cw.daily_cap} หน้า/วัน ห่าง ${cw.gap_min}–${cw.gap_max} นาที`) : Z("巡逻已关闭", "ปิดการตระเวน")}${OWN() ? ` · ${Z("在「设置 → 商品」里改", "แก้ใน「ตั้งค่า → สินค้า」")}` : ""}</p>` })}</div>
      ${UX.card({ title: Z("添加关注", "เพิ่มการติดตาม"), help: Z("关注设计师、关键词或搜索链接，扩展每天自动去看一遍列表页（不进详情页、不下载），新出来的模型打分放进候选池。第一次巡逻只记下已有的，之后新出现的才算新品。要有一台电脑开着装了 ERP 扩展的 Chrome。",
        "ติดตามนักออกแบบ คีย์เวิร์ด หรือลิงก์ค้นหา ส่วนขยายจะเปิดหน้ารายการวันละครั้ง (ไม่เข้าหน้ารายละเอียด ไม่ดาวน์โหลด) โมเดลใหม่จะได้คะแนนและเข้าคลังผู้สมัคร ต้องมีคอมเปิด Chrome ที่ติดตั้งส่วนขยาย ERP"),
        body: `<div class="cur-fbar cur-add"><select data-w="kind">${Object.entries(kinds).map(([k, v]) => `<option value="${k}">${TH() ? v[1] : v[0]}</option>`).join("")}</select>
          <select data-w="site">${d.search.map((s) => `<option value="${esc(s.id)}" data-notr>${esc(s.name)}</option>`).join("")}</select>
          <input data-w="value" placeholder="${Z("设计师主页 / 搜索页链接，或英文关键词（cable organizer）", "ลิงก์หน้านักออกแบบ / หน้าค้นหา หรือคีย์เวิร์ดภาษาอังกฤษ")}" style="flex:1;min-width:240px">
          <input data-w="label" placeholder="${Z("名称（可不填）", "ชื่อ (ไม่บังคับ)")}" style="width:150px">
          <select data-w="freq_hours"><option value="24">${Z("每天", "ทุกวัน")}</option><option value="48">${Z("每 2 天", "ทุก 2 วัน")}</option><option value="168">${Z("每周", "ทุกสัปดาห์")}</option></select>
          <button class="primary" data-w-add>${Z("添加", "เพิ่ม")}</button></div>` })}
      ${UX.card({ title: Z("关注列表", "รายการติดตาม"), body: d.rows.length ? `<div class="cur-wrap"><table class="grid cur-tbl"><thead><tr><th>${Z("关注", "ติดตาม")}</th><th>${Z("多久", "ความถี่")}</th><th>${Z("上次巡逻", "ตระเวนล่าสุด")}</th><th>${Z("找到 / 新品", "เจอ / ใหม่")}</th><th>${Z("累计新品 / 已采集", "ใหม่สะสม / เก็บแล้ว")}</th><th></th></tr></thead><tbody>
        ${d.rows.map((w) => `<tr class="${w.enabled ? "" : "muted"}"><td><b data-notr>${esc(w.label)}</b> ${pill(TH() ? (kinds[w.kind] || [])[1] || w.kind : (kinds[w.kind] || [])[0] || w.kind, "")}${w.source === "radar" ? " " + pill(Z("来自爆款雷达", "จากเรดาร์"), "info") : ""}${w.running_at ? " " + pill(Z("巡逻中", "กำลังตระเวน"), "info") : ""}
          <div class="small muted"><span data-notr>${esc(w.platform_name)}</span> · ${link(w.url, decodeURIComponent(w.url).slice(0, 70))}</div>${w.last_error ? `<div class="small bad" data-notr>${esc(w.last_error.slice(0, 160))}</div>` : ""}</td>
          <td class="small">${{ 24: Z("每天", "ทุกวัน"), 48: Z("每 2 天", "ทุก 2 วัน"), 168: Z("每周", "ทุกสัปดาห์") }[w.freq_hours] || w.freq_hours + "h"}</td>
          <td class="small">${w.last_run ? fmtTime(w.last_run) : `<span class="muted">${Z("还没巡逻", "ยังไม่ตระเวน")}</span>`}${w.enabled && w.next_run ? `<div class="muted">${Z("下次", "ครั้งถัดไป")} ${fmtTime(w.next_run)}</div>` : ""}</td>
          <td>${w.last_found} / <b>${w.last_new}</b>${w.runs === 1 ? `<div class="small muted">${Z("第一次：只记下已有的", "ครั้งแรก: บันทึกของที่มีอยู่")}</div>` : ""}</td><td>${w.total_new} / ${w.adopted}</td>
          <td class="nowrap"><button class="mini" data-w-cand="${w.id}">${Z("看候选", "ดูผู้สมัคร")}</button> <button class="mini" data-w-run="${w.id}">${Z("马上看", "ดูตอนนี้")}</button>
            <button class="mini" data-w-tog="${w.id}" data-on="${w.enabled}">${w.enabled ? Z("暂停", "หยุด") : Z("启用", "เปิด")}</button> <button class="mini ghost" data-w-del="${w.id}">${Z("删", "ลบ")}</button></td></tr>`).join("")}</tbody></table></div>`
        : UX.empty(Z("还没有关注。用上面的表单添加，或者在「运营 → 市场与竞争 → 找新品」的高分关键词上点「去模型站找」。", "ยังไม่มีการติดตาม เพิ่มด้วยฟอร์มด้านบน หรือกด「ไปหาในเว็บโมเดล」บนคีย์เวิร์ดคะแนนสูงในเรดาร์")) })}
      ${UX.card({ title: Z("最近巡逻记录", "บันทึกการตระเวนล่าสุด"), body: d.log.length ? `<table class="grid small"><tbody>${d.log.map((l) => `<tr><td class="nowrap">${fmtTime(l.ts)}</td><td data-notr>${esc(l.label || "#" + l.watch_id)}</td>
          <td>${l.error ? `<span class="bad" data-notr>${esc(l.error.slice(0, 120))}</span>` : `${Z("找到", "เจอ")} ${l.found} · ${Z("新品", "ใหม่")} ${l.new}`}</td></tr>`).join("")}</tbody></table>` : UX.empty(Z("还没有巡逻过", "ยังไม่เคยตระเวน")) })}`;
  }

  // ======================= 事件 =======================
  async function dlOne(pid, b) {
    return busy(b, async () => {
      const r = await api(`/api/cur/products/${encodeURIComponent(pid)}/download`, { json: {} });
      toast((r.queued ? Z(`已排队 ${r.queued} 个文件，扩展会用原站的登录状态下载`, `เข้าคิว ${r.queued} ไฟล์ ส่วนขยายจะดาวน์โหลดด้วยการล็อกอินเว็บต้นทาง`)
        : r.busy ? Z("已经在下载了", "กำลังดาวน์โหลดอยู่แล้ว")
        : Z("还没有文件链接：已让扩展重新读原站详情页，读到后自动下载", "ยังไม่มีลิงก์ไฟล์: ให้ส่วนขยายอ่านหน้ารายละเอียดใหม่ เจอแล้วจะดาวน์โหลดอัตโนมัติ"))
        + (r.status && r.status.ext && !r.status.ext.online ? Z("。现在没有在线的扩展：", " ตอนนี้ไม่มีส่วนขยายออนไลน์: ") + EXT_TIP() : ""), !!(r.status && r.status.ext && !r.status.ext.online));
      render();
    });
  }
  document.addEventListener("click", async (e) => {
    const s = sec();
    if (!s || !s.contains(e.target)) return;
    const t = (q) => e.target.closest(q);
    let b;
    if ((b = t(".ux-tabs[data-ux-group='curate'] [data-ux-tab]"))) return goTab(b.dataset.uxTab);
    if ((b = t("[data-ux-go]"))) {
      const g = b.dataset.uxGo;
      if (g.startsWith("tab:")) return;
      if (g === "cand:hi") Object.assign(FC, { min: String(OV.alert_score || 70), ex: "", new: "", bad: "" });
      else if (g === "cand:new") Object.assign(FC, { new: "1", min: "0", bad: "" });
      else if (g === "cand:ex") Object.assign(FC, { ex: "1", status: "all", min: "0", bad: "" });
      else if (g === "cand:bad") Object.assign(FC, { bad: "1", ex: "1", status: "all", min: "0", new: "" });
      LSset("fc", FC);
      return goTab("cur_cand");
    }
    if ((b = t("[data-c-reload]"))) return busy(b, () => show(CUR));
    if ((b = t("[data-c-radar]"))) { e.preventDefault(); return goTab("ops_radar"); }
    if ((b = t("[data-c-collect]"))) return busy(b, async () => { const r = await api("/api/cur/candidates/adopt", { json: { ids: [+b.dataset.cCollect] } }); toast(collectMsg(r)); await show(CUR); });
    if ((b = t("[data-c-dl]"))) return dlOne(b.dataset.cDl, b);
    if ((b = t("[data-c-ignore],[data-c-unignore]"))) { await api("/api/cur/candidates/status", { json: { ids: [+(b.dataset.cIgnore || b.dataset.cUnignore)], status: b.dataset.cIgnore ? "ignored" : "" } }); return render(); }
    if ((b = t("[data-c-reread]"))) return busy(b, async () => { const r = await api("/api/cur/candidates/recollect", { json: { ids: [+b.dataset.cReread] } }); toast(rereadMsg(r)); render(); });
    if ((b = t("[data-c-rereadbad]"))) return busy(b, async () => { const r = await api("/api/cur/candidates/recollect", { json: {} }); toast(rereadMsg(r)); render(); });
    if ((b = t("[data-c-delbad]"))) {
      if (!confirm(Z("删掉所有「采集可能出错」的候选？（采用过的不删；以后在模型网站上再看到会重新记下来）", "ลบผู้สมัครที่「อาจเก็บข้อมูลผิด」ทั้งหมด? (ที่ใช้แล้วไม่ลบ)"))) return;
      return busy(b, async () => { const r = await api("/api/cur/candidates/delete-bad", { json: {} }); toast(Z(`删了 ${r.deleted} 个`, `ลบแล้ว ${r.deleted} รายการ`)); FC.bad = ""; LSset("fc", FC); await show(CUR); });
    }
    if ((b = t("[data-c-badonly]"))) { FC.bad = FC.bad ? "" : "1"; if (FC.bad) Object.assign(FC, { ex: "1", status: "all", min: "0" }); LSset("fc", FC); return render(); }
    if ((b = t("[data-c-all]"))) { s.querySelectorAll("[data-c-sel]").forEach((x) => { x.checked = b.checked; (b.checked ? SEL.add(+x.dataset.cSel) : SEL.delete(+x.dataset.cSel)); }); return floatBar(); }
    if ((b = t("[data-c-sel]"))) { (b.checked ? SEL.add(+b.dataset.cSel) : SEL.delete(+b.dataset.cSel)); return floatBar(); }
    if ((b = t("[data-c-bulk]"))) {
      const ids = [...SEL];
      if (b.dataset.cBulk === "clear") { SEL.clear(); return render(); }
      if (!ids.length) return toast(Z("先勾选", "เลือกก่อน"), true);
      return busy(b, async () => {
        if (b.dataset.cBulk === "collect") toast(collectMsg(await api("/api/cur/candidates/adopt", { json: { ids } })));
        else if (b.dataset.cBulk === "reread") toast(rereadMsg(await api("/api/cur/candidates/recollect", { json: { ids } })));
        else await api("/api/cur/candidates/status", { json: { ids, status: "ignored" } });
        SEL.clear();
        await show(CUR);
      });
    }
    if ((b = t("[data-c-paste]"))) {
      const box = MODAL.open(`<h3>${Z("贴模型链接采集", "วางลิงก์โมเดลเพื่อเก็บ")}</h3><p class="small muted">${Z("一行一个 MakerWorld / Printables / Thingiverse 的模型详情页链接。每个马上建一个产品草稿放进「采集箱」，装了扩展的 Chrome 会在后台读详情页、下载模型文件。", "บรรทัดละลิงก์หน้ารายละเอียดโมเดล แต่ละลิงก์จะสร้างสินค้าฉบับร่างเข้า「กล่องเก็บสินค้า」ทันที Chrome ที่ติดตั้งส่วนขยายจะอ่านรายละเอียดและดาวน์โหลดไฟล์เบื้องหลัง")}</p>
        <textarea rows="6" style="width:100%" data-p-urls placeholder="https://www.printables.com/model/123456-...\nhttps://makerworld.com/en/models/..."></textarea><div class="row gap" style="margin-top:8px"><button class="primary" data-p-go>${Z("采集", "เก็บ")}</button><button data-mclose>${Z("取消", "ยกเลิก")}</button></div>`);
      box.onclick = async (ev) => { const g = ev.target.closest("[data-p-go]"); if (!g) return; await busy(g, async () => { toast(collectMsg(await api("/api/cur/candidates/adopt", { json: { urls: box.querySelector("[data-p-urls]").value } }))); MODAL.close(); goTab("cur_inbox"); }); };
      return;
    }
    if ((b = t("[data-c-prod]"))) { e.stopPropagation(); if (window.openProduct) return openProduct(b.dataset.cProd, true); return goTab("library"); }
    // 采集箱
    if ((b = t("[data-i-folder]"))) { IF = b.dataset.iFolder; LSset("ifolder", IF); ISEL.clear(); return render(); }
    if ((b = t("[data-i-newfolder]"))) {
      const n = prompt(Z("新文件夹名称（例如：猫用品、车载、待拍照）", "ชื่อโฟลเดอร์ใหม่")); if (!n) return;
      try { await api("/api/groups", { json: { name: n } }); render(); } catch (err) { toast(err.message, true); }
      return;
    }
    if ((b = t("[data-i-all]"))) { (IN ? IN.rows : []).forEach((r) => (b.checked ? ISEL.add(r.product_id) : ISEL.delete(r.product_id))); s.querySelectorAll("[data-i-sel]").forEach((x) => { x.checked = b.checked; x.closest(".cur-ic").classList.toggle("sel", b.checked); }); return floatBar(); }
    if ((b = t("[data-i-sel]"))) { (b.checked ? ISEL.add(b.dataset.iSel) : ISEL.delete(b.dataset.iSel)); b.closest(".cur-ic").classList.toggle("sel", b.checked); return floatBar(); }
    if ((b = t("[data-i-bulk]"))) { if (b.dataset.iBulk === "clear") { ISEL.clear(); return render(); } return inboxAction(b.dataset.iBulk, [...ISEL], b); }
    if ((b = t("[data-i-to]"))) return inboxAction("to_library", [b.dataset.iTo], b);
    if ((b = t("[data-i-del]"))) return inboxAction("delete", [b.dataset.iDel], b);
    if ((b = t("[data-i-move]"))) return moveFolder([b.dataset.iMove]);
    if ((b = t("[data-i-lic]"))) {
      const forced = b.dataset.auto === "禁止商用";
      if (!confirm(forced ? Z("系统初判这个许可证禁止商用。确认另外买了商用授权，仍然核验通过？", "ระบบประเมินว่าสัญญานี้ห้ามใช้เชิงพาณิชย์ ยืนยันว่าซื้อสิทธิ์เชิงพาณิชย์แล้ว และตรวจผ่าน?")
        : Z("确认已经打开原站看过许可证，可以商用（CC BY 要署名）？", "ยืนยันว่าเปิดดูสัญญาอนุญาตที่เว็บต้นทางแล้ว และใช้เชิงพาณิชย์ได้?"))) return;
      return busy(b, async () => { await api(`/api/products/${encodeURIComponent(b.dataset.iLic)}/license`, { json: { verified: true, force: forced } }); toast(Z("许可已核验", "ตรวจสัญญาอนุญาตแล้ว")); render(); });
    }
  });
  document.addEventListener("click", async (e) => {
    const s = sec();
    if (!s || !s.contains(e.target)) return;
    const t = (q) => e.target.closest(q);
    let b;
    if ((b = t("[data-w-add]"))) {
      const o = {}; s.querySelectorAll("[data-w]").forEach((i) => { o[i.dataset.w] = i.value; });
      return busy(b, async () => { await api("/api/cur/watches", { json: o }); toast(Z("已添加", "เพิ่มแล้ว")); render(); });
    }
    if ((b = t("[data-w-run]"))) return busy(b, async () => { await api(`/api/cur/watches/${b.dataset.wRun}`, { json: { run: true } }); toast(Z("排到最前了，扩展下次轮到时就去看", "จัดคิวแรกแล้ว")); render(); });
    if ((b = t("[data-w-tog]"))) { await api(`/api/cur/watches/${b.dataset.wTog}`, { json: { enabled: b.dataset.on !== "1" } }); return render(); }
    if ((b = t("[data-w-del]"))) { if (!confirm(Z("删掉这个关注？已经进候选池的模型会保留。", "ลบการติดตามนี้? โมเดลในคลังผู้สมัครยังอยู่"))) return; await api(`/api/cur/watches/${b.dataset.wDel}`, { json: { delete: true } }); return render(); }
    if ((b = t("[data-w-cand]"))) { Object.assign(FC, { min: "0", ex: "1", status: "all", new: "", bad: "" }); FC.watch = b.dataset.wCand; LSset("fc", { ...FC, watch: "" }); return goTab("cur_cand"); }
    if ((b = t("[data-w-reset]"))) return busy(b, async () => { await api("/api/cur/pace/reset", { json: { platform: b.dataset.wReset } }); render(); });
    if ((b = t("[data-q-act]"))) return busy(b, async () => { await api("/api/cur/collect/action", { json: { id: +(b.dataset.q || 0), action: b.dataset.qAct } }); render(); });
    // 采集队列：网站暂停 / 继续、清理、筛选、勾选、单个任务和批量操作
    if ((b = t("[data-q-site]"))) return busy(b, async () => { await api(`/api/cur/sites/${encodeURIComponent(b.dataset.qSite)}/hold`, { json: { on: b.dataset.on === "1" } }); render(); });
    if ((b = t("[data-q-clean]"))) return busy(b, async () => {
      const r = await api("/api/cur/queue/cleanup", { json: {} });
      toast(Z(`清理了 ${r.orphans + r.collect} 个详情页任务、${r.files} 个失败的下载（产品上还能重新下载）`, `ล้างงานอ่านรายละเอียด ${r.orphans + r.collect} รายการ ดาวน์โหลดไม่สำเร็จ ${r.files} ไฟล์ (ดาวน์โหลดใหม่จากสินค้าได้)`));
      QSEL.clear(); render();
    });
    if ((b = t("[data-qf-state]"))) { QF.state = b.dataset.qfState; LSset("qf", QF); QSEL.clear(); return render(); }
    if ((b = t("[data-q-all]"))) { ((QD && QD.jobs) || []).forEach((j) => (b.checked ? QSEL.add(j.id) : QSEL.delete(j.id))); s.querySelectorAll("[data-q-sel]").forEach((x) => { x.checked = b.checked; x.closest("tr").classList.toggle("cur-qsel", b.checked); }); return floatBar(); }
    if ((b = t("[data-q-sel]"))) { (b.checked ? QSEL.add(b.dataset.qSel) : QSEL.delete(b.dataset.qSel)); b.closest("tr").classList.toggle("cur-qsel", b.checked); return floatBar(); }
    if ((b = t("[data-q-one]"))) return busy(b, async () => { await qAction([b.dataset.q], b.dataset.qOne); render(); });
    if ((b = t("[data-q-bulk]"))) {
      const ids = [...QSEL], act = b.dataset.qBulk;
      if (act === "clear") { QSEL.clear(); return render(); }
      if (act === "delete" && !confirm(Z(`从采集队列删除 ${ids.length} 个任务？（下载任务只是不下载这个文件，产品草稿不动；以后在产品上点「⬇ 下载模型文件」还能再排队）`,
        `ลบ ${ids.length} งานออกจากคิว? (งานดาวน์โหลดคือไม่ดาวน์โหลดไฟล์นั้น สินค้าฉบับร่างไม่เปลี่ยน กด「⬇ ดาวน์โหลดไฟล์โมเดล」ที่สินค้าเพื่อเข้าคิวใหม่ได้)`))) return;
      return busy(b, async () => {
        const r = await qAction(ids, act);
        toast(Z(`${QBULK()[act]}：${r.n} 个`, `${QBULK()[act]}: ${r.n} รายการ`));
        if (act === "delete") QSEL.clear();
        render();
      });
    }
  });
  document.addEventListener("change", async (e) => {
    const s = sec();
    if (!s || !s.contains(e.target) || CUR !== "cur_queue") return;
    const f = e.target.closest("[data-qf]");
    if (f) { QF[f.dataset.qf] = f.value; LSset("qf", QF); QSEL.clear(); return render(); }
    const pr = e.target.closest("[data-q-prio]");
    if (pr && pr.value !== "" && QSEL.size) {
      const r = await qAction([...QSEL], "prio", { prio: +pr.value }).catch((err) => toast(err.message, true));
      if (r) toast(Z(`优先级已改：${r.n} 个`, `เปลี่ยนความสำคัญแล้ว: ${r.n} รายการ`));
      render();
    }
  });
  // 拖动排序（只有等着的任务能拖；拖的是勾选里的一个就整批一起挪）
  document.addEventListener("dragstart", (e) => {
    const tr = e.target.closest && e.target.closest("#tab-curate tr[data-qj][draggable]");
    if (!tr) return;
    QDRAG = tr.dataset.qj;
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", QDRAG); } catch (err) { /* 忽略 */ }
  });
  document.addEventListener("dragover", (e) => {
    const tr = QDRAG && e.target.closest && e.target.closest("#tab-curate tr[data-qj][draggable]");
    if (!tr || tr.dataset.qj[0] !== QDRAG[0]) return;
    e.preventDefault();
    document.querySelectorAll("#tab-curate tr.cur-dropto").forEach((x) => x !== tr && x.classList.remove("cur-dropto"));
    tr.classList.add("cur-dropto");
  });
  document.addEventListener("drop", async (e) => {
    const tr = QDRAG && e.target.closest && e.target.closest("#tab-curate tr[data-qj][draggable]");
    if (!tr) return;
    e.preventDefault();
    const from = QDRAG, before = tr.dataset.qj;
    QDRAG = null;
    if (from === before) return render();
    const ids = QSEL.has(from) ? [...QSEL].filter((x) => x[0] === from[0] && x !== before) : [from];
    try { await qAction(ids, "move", { before }); } catch (err) { toast(err.message, true); }
    render();
  });
  document.addEventListener("dragend", () => { QDRAG = null; document.querySelectorAll("#tab-curate tr.cur-dropto").forEach((x) => x.classList.remove("cur-dropto")); });
  // 打开模型站的菜单：点别处收起
  document.addEventListener("click", (e) => { document.querySelectorAll("#tab-curate details.cur-sites[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; }); });
  function collectMsg(r) {
    const sk = Object.values(r.skipped || {});
    return Z(`采集了 ${r.added} 个，已放进采集箱 ${(r.products || []).map((x) => x.product_code).join("、")}`, `เก็บแล้ว ${r.added} รายการ เข้ากล่องเก็บสินค้า ${(r.products || []).map((x) => x.product_code).join(", ")}`)
      + (sk.length ? Z(`（${sk.length} 个已经采用过）`, ` (${sk.length} รายการใช้แล้ว)`) : "")
      + (r.added ? Z("。扩展会在后台读详情页、下载模型文件，AI 马上写文案。", " ส่วนขยายจะอ่านรายละเอียดและดาวน์โหลดไฟล์เบื้องหลัง AI จะเขียนข้อความทันที") : "");
  }
  const rereadMsg = (r) => Z(`已排队重新读取 ${r.queued} 个（扩展读详情页后改正标题、图片）`, `เข้าคิวอ่านใหม่ ${r.queued} รายการ (ส่วนขยายจะแก้ชื่อและรูปจากหน้ารายละเอียด)`)
    + (OV && OV.ext && !OV.ext.online ? Z("。现在没有在线的扩展：", " ตอนนี้ไม่มีส่วนขยายออนไลน์: ") + EXT_TIP() : "");
  let qT = null, iT = null;
  document.addEventListener("change", async (e) => {
    const s = sec();
    if (!s || !s.contains(e.target)) return;
    const up = e.target.closest("[data-c-up]");
    if (up && up.files.length) {
      const fd = new FormData();
      [...up.files].forEach((f) => fd.append("file", f));
      try {
        await busyToast(Z("正在上传模型文件…", "กำลังอัปโหลดไฟล์โมเดล…"), () => api(`/api/cur/products/${encodeURIComponent(up.dataset.cUp)}/upload`, { method: "POST", body: fd }));
        toast(Z("已上传，ERP 正在分析（尺寸、克数、时长、规格），第一个 STL / 3MF 自动当 3D 模型", "อัปโหลดแล้ว ERP กำลังวิเคราะห์ ไฟล์ STL / 3MF แรกจะเป็นโมเดล 3D อัตโนมัติ"));
        render();
      } catch (err) { toast(err.message, true); }
      up.value = "";
      return;
    }
    const i = e.target.closest("[data-fc]");
    if (i && i.dataset.fc !== "q") { FC[i.dataset.fc] = i.type === "checkbox" ? (i.checked ? "1" : "") : i.value; FC.watch = ""; LSset("fc", FC); render(); }
  });
  document.addEventListener("input", (e) => {
    const s = sec();
    if (!s || !s.contains(e.target)) return;
    const i = e.target.closest("[data-fc='q']"), iq = e.target.closest("[data-i-q]");
    const refocus = (sel) => () => { const n = s.querySelector(sel); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } };
    if (i) { clearTimeout(qT); qT = setTimeout(() => { FC.q = i.value; render().then(refocus("[data-fc='q']")); }, 350); }
    if (iq) { clearTimeout(iT); iT = setTimeout(() => { IQ = iq.value; render().then(refocus("[data-i-q]")); }, 350); }
  });

  // v2.53：从采集箱 / 候选池 / 队列打开产品编辑，「← 返回」回到这里：文件夹、搜索、筛选和离开时一样（刷新页面后也记得）
  if (window.NAV) {
    NAV.keep(SUBS.map(([k]) => k).concat("curate"), {
      form: false,
      get: () => ({ IF, IQ, FC: { ...FC }, QF: { ...QF } }),
      set: (s) => {
        if (!s) return;
        if (s.IF != null) { IF = s.IF; LSset("ifolder", IF); }
        if (s.IQ != null) IQ = s.IQ;
        if (s.FC) FC = Object.assign(FC, s.FC);
        if (s.QF) QF = Object.assign(QF, s.QF);
      },
    });
  }

  window.MODS = window.MODS || {};
  window.MODS.curate = { show };
  window.CURATE = { show };
})();
