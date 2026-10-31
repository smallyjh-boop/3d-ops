"use strict";
// 选品（v2.50，「商品」菜单的第一个页面）：页面头 → 数字卡片 → 图表 → 明细表（说明收进「?」）。界面文字 Z(中文, 泰文)，原始数据（模型名、作者、原站文字）放 data-notr。
// 三个页签 = 三个 ghost 页面 id：cur_cand 候选池 · cur_queue 采集队列 · cur_watch 关注巡逻（待办 / 提醒里的链接直接打开对的页签）。
// 选品只管「找模型」：候选池里「采用」= 马上在产品库建 ERP 产品草稿（许可待核验），之后用 ERP 的编辑页、模型库、上架检查。
// 上架客服：接口里已经去掉成本、利润、估计售价（api.py _strip），页面上对应的格子也不画。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const SUBS = [["cur_cand", "候选池", "คลังผู้สมัคร"], ["cur_queue", "采集队列", "คิวเก็บข้อมูล"], ["cur_watch", "关注巡逻", "ตระเวนติดตาม"]];
  const PARTS = () => ({ demand: Z("泰国需求", "ความต้องการไทย"), production: Z("生产效率", "ประสิทธิภาพการผลิต"), profit: Z("利润", "กำไร"),
    competition: Z("竞争少", "แข่งน้อย"), popularity: Z("原站热度", "ความนิยมต้นทาง"), listing: Z("上架难度", "ความง่ายในการลงขาย") });
  const ST = () => ({ new: Z("新采集", "เก็บใหม่"), checked: Z("已检查", "ตรวจแล้ว"), selected: Z("要做", "จะทำ"), converted: Z("已转产品", "แปลงแล้ว"), rejected: Z("不采用", "ไม่ใช้") });
  const STEP = () => ({ thumbs: Z("缩略图", "รูปย่อ"), translate: Z("翻译", "แปล"), files: Z("文件分析", "วิเคราะห์ไฟล์"), variants: Z("规格", "ตัวเลือก"),
    category: Z("类目", "หมวดหมู่"), listing: Z("文案", "ข้อความ") });
  const FST = () => ({ "": Z("没下载", "ยังไม่ดาวน์โหลด"), queued: Z("等扩展下载", "รอส่วนขยายดาวน์โหลด"), downloading: Z("下载中", "กำลังดาวน์โหลด"), ok: Z("已存", "เก็บแล้ว"),
    failed: Z("失败", "ไม่สำเร็จ") });
  const QL = () => ({ ok: Z("合格", "ผ่าน"), fix: Z("需处理", "ต้องแก้"), block: Z("阻断", "ห้ามผ่าน"), pending: Z("检查中", "กำลังตรวจ"), warn: Z("提醒", "เตือน"), info: Z("提示", "ข้อมูล") });
  const OWN = () => !!(window.ME && ME.role === "owner");
  const n0 = (v) => (v == null || v === "" ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }));
  const hrs = (m) => (m ? `${(m / 60).toFixed(1)}${Z(" 小时", " ชม.")}` : "—");
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
  let CUR = "cur_cand", OV = null;
  let FC = Object.assign({ min: "0", platform: "", cat: "", ex: "", new: "", q: "", status: "open" }, LS("fc", {}));

  function sec() { return $("#tab-curate"); }
  async function show(tab) {
    if (tab === "curate") tab = LS("last", "cur_cand");
    if (!SUBS.some(([s]) => s === tab)) tab = "cur_cand";
    CUR = tab; LSset("last", tab);
    try { OV = await api("/api/cur/overview"); } catch (e) { OV = OV || {}; }
    frame();
    await render();
  }
  function frame() {
    const s = sec();
    if (!s) return;
    const cnt = { cur_cand: OV.cand, cur_queue: OV.queue, cur_watch: OV.watch };
    s.querySelector(".cur-top").innerHTML = UX.head(Z("选品", "คัดเลือกสินค้า"),
      `<button class="mini" data-c-reload>⟳ ${Z("刷新", "รีเฟรช")}</button>`,
      Z("在模型网站找能卖的模型 → 候选池打分（泰国市场排除规则 + AI）→「采用」= 马上在「产品库」建产品草稿（图片、模型文件、规格、文案自动补进来）→ 核验许可、在编辑页补完 →「上架」。浏览器扩展（和 AI 客服同一个）在 MakerWorld / Printables / Thingiverse 上显示推荐分和「＋采集」按钮。",
        "หาโมเดลที่ขายได้จากเว็บโมเดล → ให้คะแนน (กฎตลาดไทย + AI) →「ใช้」= สร้างสินค้าฉบับร่างใน「คลังสินค้า」ทันที (รูป ไฟล์โมเดล ตัวเลือก ข้อความ เติมอัตโนมัติ) → ตรวจสัญญาอนุญาต แก้ไขให้ครบ →「ลงขาย」 ส่วนขยายเบราว์เซอร์แสดงคะแนนและปุ่ม「＋เก็บ」บน MakerWorld / Printables / Thingiverse"))
      + (OV.ai === false ? `<div class="warn-box small">${Z("还没设置 AI（设置 → AI 与对接）：候选只按规则打分，采用的草稿不会自动写文案。", "ยังไม่ได้ตั้งค่า AI (ตั้งค่า → AI และการเชื่อมต่อ): ให้คะแนนตามกฎเท่านั้น และไม่เขียนข้อความให้สินค้าฉบับร่างอัตโนมัติ")}</div>` : "")
      + UX.tabs(SUBS.map(([k, zh, th]) => [k, Z(zh, th), cnt[k] || ""]), CUR, "curate");
  }
  async function render() {
    const box = sec() && sec().querySelector(".cur-body");
    if (!box) return;
    if (!box.innerHTML) box.innerHTML = `<p class="muted">${Z("加载中…", "กำลังโหลด…")}</p>`;
    try {
      if (CUR === "cur_cand") await candPage(box);
      else if (CUR === "cur_queue") await queuePage(box);
      else await watchPage(box);
    } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
  }

  // ======================= 候选池 =======================
  async function candPage(box) {
    const qs = new URLSearchParams(Object.entries(FC).filter(([, v]) => v !== "" && v != null)).toString();
    const d = await api("/api/cur/candidates?" + qs);
    const k = d.kpi;
    const hist = d.hist.map((v, i) => ({ label: `${i * 10}–${i * 10 + 9}`, value: v, tone: i >= 7 ? "ok" : "" }));
    const plats = [...new Set(d.rows.map((r) => r.platform))];
    box.innerHTML = UX.kpis([
      { label: Z("候选模型", "โมเดลผู้สมัคร"), value: n0(k.total), help: Z("扩展在模型网站列表页上看到、打过分的模型", "โมเดลที่ส่วนขยายเห็นในหน้ารายการและให้คะแนนแล้ว") },
      { label: Z(`高分（≥ ${d.alert_score}）`, `คะแนนสูง (≥ ${d.alert_score})`), value: n0(k.good), tone: k.good ? "ok" : "", go: "cand:hi" },
      { label: Z("今日新品", "ใหม่วันนี้"), value: n0(k.new_today), tone: k.new_today ? "info" : "", go: "cand:new", help: Z("关注巡逻今天新找到的", "ที่ตระเวนเจอใหม่วันนี้") },
      { label: Z("被排除", "ถูกคัดออก"), value: n0(k.excluded), go: "cand:ex", help: Z("儿童玩具（TISI）、宗教、武器、接触食物、成人、品牌 / 动漫角色、多色、打印太久", "ของเล่นเด็ก (มอก.) ศาสนา อาวุธ สัมผัสอาหาร ผู้ใหญ่ แบรนด์ / ตัวการ์ตูน หลายสี พิมพ์นานเกิน") },
      d.ai ? { label: Z("等 AI 判断", "รอ AI ประเมิน"), value: n0(k.wait_ai), tone: k.wait_ai ? "warn" : "" } : null,
    ]) + `<div class="cur-grid2">${UX.card({ title: Z("分数分布", "การกระจายคะแนน"), help: Z("不含被排除的。分数 = 六项加权：泰国需求、生产效率、利润、竞争少、原站热度、上架难度（权重在设置 → 商品）", "ไม่รวมที่ถูกคัดออก คะแนน = 6 ด้านถ่วงน้ำหนัก (ตั้งค่า → สินค้า)"),
        body: UX.columns(hist, { h: 90, from: "0", to: "100" }) })}
      ${UX.card({ title: Z("排除原因", "เหตุผลที่คัดออก"), body: UX.bars(d.reasons.map((r) => ({ label: TH() && r.reason_th ? r.reason_th : r.reason, value: r.n, tone: "bad" })), { empty: Z("没有被排除的", "ไม่มีที่ถูกคัดออก") }) })}</div>
      ${UX.card({ title: Z("候选模型", "โมเดลผู้สมัคร"), right: `<button class="mini" data-c-paste>${Z("＋ 贴链接采用", "＋ วางลิงก์เพื่อใช้")}</button>`,
        body: `<div class="cur-fbar">
          <label>${Z("最低分", "คะแนนขั้นต่ำ")} <select data-fc="min">${["0", "40", "50", "60", "70", "80"].map((v) => `<option ${v === FC.min ? "selected" : ""}>${v}</option>`).join("")}</select></label>
          <select data-fc="platform"><option value="">${Z("全部网站", "ทุกเว็บ")}</option>${plats.concat(FC.platform && !plats.includes(FC.platform) ? [FC.platform] : []).map((p) => `<option value="${esc(p)}" ${p === FC.platform ? "selected" : ""} data-notr>${esc((d.rows.find((r) => r.platform === p) || {}).platform_name || p)}</option>`).join("")}</select>
          <select data-fc="cat"><option value="">${Z("全部类目", "ทุกหมวด")}</option>${d.cats.map((c) => `<option value="${esc(c.name)}" ${c.name === FC.cat ? "selected" : ""}>${esc(TH() ? c.th : c.name)}</option>`).join("")}</select>
          <select data-fc="status"><option value="open" ${FC.status === "open" ? "selected" : ""}>${Z("待处理", "รอดำเนินการ")}</option><option value="ignored" ${FC.status === "ignored" ? "selected" : ""}>${Z("已忽略", "ข้ามแล้ว")}</option><option value="adopted" ${FC.status === "adopted" ? "selected" : ""}>${Z("已采用", "ใช้แล้ว")}</option><option value="all" ${FC.status === "all" ? "selected" : ""}>${Z("全部", "ทั้งหมด")}</option></select>
          <label class="chk"><input type="checkbox" data-fc="ex" ${FC.ex ? "checked" : ""}> ${Z("显示被排除的", "แสดงที่ถูกคัดออก")}</label>
          <label class="chk"><input type="checkbox" data-fc="new" ${FC.new ? "checked" : ""}> ${Z("只看今日新品", "เฉพาะใหม่วันนี้")}</label>
          <input type="search" data-fc="q" value="${esc(FC.q)}" placeholder="${Z("搜索标题 / 作者", "ค้นหาชื่อ / ผู้ออกแบบ")}">
          <span class="cur-sp"></span><button class="mini" data-c-bulk="collect">${Z("采用所选", "ใช้ที่เลือก")}</button><button class="mini" data-c-bulk="ignore">${Z("忽略所选", "ข้ามที่เลือก")}</button></div>
        ${d.rows.length ? `<div class="cur-wrap"><table class="grid cur-tbl"><thead><tr><th><input type="checkbox" data-c-all></th><th>${Z("分", "คะแนน")}</th><th>${Z("模型", "โมเดล")}</th>
          <th>${Z("估算", "ประมาณ")}</th><th>${Z("泰国市场", "ตลาดไทย")}</th><th>${Z("AI 判断", "AI ประเมิน")}</th><th></th></tr></thead><tbody>${d.rows.map(candRow).join("")}</tbody></table></div>`
          : UX.empty(Z("还没有候选。装好浏览器扩展（3.1 以上）后打开 MakerWorld / Printables / Thingiverse 的搜索页、分类页，系统会自动给每个模型打分并记到这里；也可以在「关注巡逻」里添加关注让扩展每天自动找。",
            "ยังไม่มีผู้สมัคร ติดตั้งส่วนขยาย (3.1 ขึ้นไป) แล้วเปิดหน้าค้นหา / หมวดหมู่ของ MakerWorld / Printables / Thingiverse ระบบจะให้คะแนนแต่ละโมเดลอัตโนมัติ หรือเพิ่มการติดตามใน「ตระเวนติดตาม」"))}` })}
      <p class="small muted">${Z("校准：", "การปรับเทียบ: ")}${d.calib.n >= 5 ? Z(`实测时长约是 AI 估算的 ${d.calib.m} 倍、克数 ${d.calib.g} 倍（${d.calib.n} 个样本，其中 ${d.calib.production || 0} 个来自 ERP 生产记录）`, `เวลาจริงประมาณ ${d.calib.m} เท่าของที่ AI ประมาณ กรัม ${d.calib.g} เท่า (${d.calib.n} ตัวอย่าง)`)
        : Z(`要至少 5 个「估算过、又有实测」的模型才开始校准（现在 ${d.calib.n || 0} 个）`, `ต้องมีอย่างน้อย 5 โมเดลที่มีทั้งค่าประมาณและค่าจริงจึงจะปรับเทียบ (ตอนนี้ ${d.calib.n || 0})`)}</p>`;
  }
  function candRow(r) {
    const tone = scTone(r.score, r.excluded);
    const mk = r.market;
    const act = r.product_id ? `<span class="mono" data-p360="${esc(r.product_id)}" data-notr>${esc(r.product_id)}</span> <button class="mini" data-c-prod="${esc(r.product_id)}">${Z("编辑产品", "แก้ไขสินค้า")}</button>`
        : `<button class="mini" data-c-collect="${r.id}" title="${esc(Z("马上在产品库建产品草稿（许可待核验），扩展在后台读详情页、下载模型文件", "สร้างสินค้าฉบับร่างทันที ส่วนขยายจะอ่านหน้ารายละเอียดและดาวน์โหลดไฟล์เบื้องหลัง"))}">✓ ${Z("采用", "ใช้")}</button> ${r.status === "ignored" ? `<button class="mini" data-c-unignore="${r.id}">${Z("恢复", "คืน")}</button>` : `<button class="mini ghost" data-c-ignore="${r.id}">${Z("忽略", "ข้าม")}</button>`}`;
    return `<tr class="${r.excluded ? "cur-ex" : ""}"><td><input type="checkbox" data-c-sel="${r.id}"></td>
      <td><span class="cur-sc ${tone}" title="${esc(partTip(r.parts))}">${Math.round(r.score)}</span></td>
      <td><div class="cur-pic">${img(r.thumb)}<div>${link(r.url, (r.title || r.url).slice(0, 80))}${r.new ? " " + pill(Z("新品", "ใหม่"), "info") : ""}
        <div class="small muted"><span data-notr>${esc(r.platform_name)}${r.author ? " · " + esc(r.author) : ""}</span>${r.category ? ` · <span data-notr>${esc(catTxt(r))}</span>` : ""}</div>
        ${r.excluded ? `<div class="small bad" data-notr>✕ ${esc(reasonTxt(r))}</div>` : ""}</div></div></td>
      <td class="small nowrap">${r.est ? `<span data-notr>${esc(r.est)}</span> ${r.measured ? pill(Z("实测", "วัดจริง"), "ok") : pill(Z("估", "ประมาณ"), "")}` : "—"}${r.single === false ? `<div>${pill(Z("多色", "หลายสี"), "warn")}</div>` : ""}${r.price ? `<div class="muted" data-notr>${esc(r.price)}</div>` : ""}</td>
      <td class="small">${mk ? `<span data-notr>${esc(mk.keyword)}</span> · ${Z("机会分", "คะแนนโอกาส")} <b>${mk.score}</b>${mk.price_median ? `<div class="muted">${Z("到手价中位", "ราคากลาง")} ฿${n0(mk.price_median)}</div>` : ""}${mk.daily_top10 != null ? `<div class="muted">${Z("前 10 日销", "ขาย/วัน 10 อันดับ")} ${mk.daily_top10}</div>` : ""}${mk.total_results ? `<div class="muted">${Z("结果数", "ผลค้นหา")} ${n0(mk.total_results)}</div>` : ""}` : `<span class="muted">—</span>`}</td>
      <td class="small cur-reason">${r.ai_error ? `<span class="warn-t"${TH() ? "" : ` title="${esc(r.ai_error)}"`}>${Z("AI 判断出错，只按规则打分", "AI ประเมินผิดพลาด ใช้คะแนนตามกฎ")}</span>` : r.ai ? `<span data-notr>${esc(TH() && r.reason_th ? r.reason_th : r.reason || "")}</span>${(r.keywords || []).length ? `<div class="muted" data-notr>${esc(r.keywords.slice(0, 4).join(", "))}</div>` : ""}` : `<span class="muted">${Z("等 AI 判断", "รอ AI")}</span>`}</td>
      <td class="nowrap">${act}</td></tr>`;
  }

  // ======================= 采集队列 =======================
  // 采用的模型：马上是产品库里的草稿；这里看扩展读详情页、下载文件、ERP 处理（模型库、规格、文案）走到哪一步，许可核验了没有。
  async function queuePage(box) {
    const d = await api("/api/cur/queue");
    const k = d.kpi, q = d.collect;
    const FS = () => ({ none: Z("没下载", "ยังไม่ดาวน์โหลด"), queued: Z("等下载", "รอดาวน์โหลด"), downloading: Z("下载中", "กำลังดาวน์โหลด"), ok: Z("已存", "เก็บแล้ว"), failed: Z("失败", "ไม่สำเร็จ") });
    const CS = () => ({ waiting: Z("等读详情页", "รออ่านหน้ารายละเอียด"), running: Z("正在读取", "กำลังอ่าน"), done: Z("详情已读", "อ่านแล้ว"), failed: Z("读取失败", "อ่านไม่สำเร็จ"), canceled: Z("已取消", "ยกเลิก") });
    const step = (ok, zh, th) => pill((ok ? "✓ " : "· ") + Z(zh, th), ok ? "ok" : "");
    box.innerHTML = UX.kpis([
      { label: Z("等读详情页", "รออ่านหน้ารายละเอียด"), value: n0(k.waiting), sub: q.paused ? Z("已暂停", "หยุดชั่วคราว") : "", tone: q.paused ? "warn" : "",
        help: Z("采用以后，装了 ERP 扩展的 Chrome 在后台标签页一个个打开原站详情页，读图片、描述、许可证、文件链接，补进产品草稿", "หลังจากกดใช้ Chrome ที่ติดตั้งส่วนขยายจะเปิดหน้ารายละเอียดเบื้องหลังทีละหน้า อ่านรูป คำอธิบาย สัญญาอนุญาต ลิงก์ไฟล์ แล้วเติมลงสินค้าฉบับร่าง") },
      { label: Z("文件等下载", "ไฟล์รอดาวน์โหลด"), value: n0(k.files), help: Z("扩展用浏览器里原站的登录状态下载，上传后直接进产品的模型库", "ส่วนขยายดาวน์โหลดด้วยการล็อกอินเว็บต้นทางในเบราว์เซอร์ แล้วใส่ในคลังโมเดลของสินค้า") },
      { label: Z("下载失败", "ดาวน์โหลดไม่สำเร็จ"), value: n0(k.failed), tone: k.failed ? "bad" : "" },
      { label: Z("许可待核验", "รอตรวจสัญญาอนุญาต"), value: n0(k.lic_pending), tone: k.lic_pending ? "warn" : "ok", help: Z("核验前产品不能导出、不能推送到平台。在产品编辑页上面点「核验通过」", "ก่อนตรวจ สินค้าส่งออก / ส่งขึ้นแพลตฟอร์มไม่ได้ กด「ตรวจผ่าน」ที่หน้าแก้ไขสินค้า") },
      { label: Z("近 30 天采用", "ใช้ใน 30 วัน"), value: n0(k.adopted_30d) },
    ]) + `<div class="cur-grid2">${UX.card({ title: Z("每天采用（14 天）", "ใช้ต่อวัน (14 วัน)"), body: UX.columns(d.days.map((x) => ({ label: x.day, value: x.n, tone: "ok" })), { h: 90, from: d.days[0].day, to: d.days[d.days.length - 1].day }) })}
      ${UX.card({ title: Z("采集队列", "คิวเก็บข้อมูล"), right: `<button class="mini" data-q-act="${q.paused ? "resume" : "pause"}">${q.paused ? Z("▶ 继续", "▶ ทำต่อ") : Z("⏸ 暂停", "⏸ หยุด")}</button>`,
        body: [...q.active, ...q.recent.filter((x) => x.state !== "done")].length ? `<table class="grid small"><tbody>${[...q.active, ...q.recent.filter((x) => x.state !== "done")].slice(0, 12).map((r) => `<tr><td>${link(r.url, (r.title || r.url).slice(0, 60))}</td>
          <td>${pill(CS()[r.state] || r.state, r.state === "failed" ? "bad" : "info")}${r.message ? `<div class="muted" data-notr>${esc(r.message.slice(0, 100))}</div>` : ""}</td>
          <td class="nowrap">${r.state === "waiting" ? `<button class="mini ghost" data-q-act="cancel" data-q="${r.id}">${Z("取消", "ยกเลิก")}</button>` : ["failed", "canceled"].includes(r.state) ? `<button class="mini" data-q-act="retry" data-q="${r.id}">${Z("重试", "ลองใหม่")}</button>` : ""}</td></tr>`).join("")}</tbody></table>`
          : UX.empty(Z("队列是空的", "คิวว่าง")) })}</div>
      ${UX.card({ title: Z("采用的产品草稿", "สินค้าฉบับร่างที่ใช้"), help: Z("采用就是产品库里的草稿：用 ERP 的编辑页补颜色、主图、类目属性、售价；模型文件在产品的模型库；许可核验过、上架检查通过才能导出 / 推送。",
          "กดใช้แล้วเป็นสินค้าฉบับร่างในคลังสินค้า แก้ไขด้วยหน้าแก้ไขของ ERP (สี รูป หมวดหมู่ ราคา) ไฟล์อยู่ในคลังโมเดลของสินค้า ต้องตรวจสัญญาอนุญาตและผ่านการตรวจก่อนลงขาย"),
        body: d.rows.length ? `<div class="cur-wrap"><table class="grid cur-tbl"><thead><tr><th>${Z("产品", "สินค้า")}</th><th>${Z("许可", "สัญญาอนุญาต")}</th><th>${Z("进度", "ความคืบหน้า")}</th><th>${Z("文件", "ไฟล์")}</th><th></th></tr></thead><tbody>
          ${d.rows.map((r) => { const f = r.files || {}; const mf = ["ok", "queued", "downloading", "failed", "none"].filter((s) => f[s]).map((s) => `${FS()[s]} ${f[s]}`).join(" · ");
            return `<tr><td><div class="cur-pic">${img(r.thumb)}<div><span class="mono" data-p360="${esc(r.product_id)}" data-notr>${esc(r.product_id)}</span> <b data-notr>${esc(r.name)}</b>
              <div class="small muted">${link(r.url, r.platform)} · ${fmtTime(r.adopted_at)}${r.adopted_by ? ` · <span data-notr>${esc(r.adopted_by)}</span>` : ""}</div></div></div></td>
              <td>${r.license === "pending" ? pill(Z("许可待核验", "รอตรวจสัญญาอนุญาต"), r.license_auto === "禁止商用" ? "bad" : "warn") : pill("✓ " + Z("已核验", "ตรวจแล้ว"), "ok")}${r.license_name ? `<div class="small muted" data-notr>${esc(r.license_name)}</div>` : ""}${r.ip ? `<div>${pill(Z("侵权待确认", "รอยืนยันลิขสิทธิ์"), "bad")}</div>` : ""}</td>
              <td class="small">${r.collect && r.collect !== "done" ? pill(CS()[r.collect] || r.collect, r.collect === "failed" ? "bad" : "info") + " " : step(r.collect === "done", "详情", "รายละเอียด") + " "}${step((f.img_ok || 0) > 0, "图片", "รูป")} ${step(r.model, "3D 模型", "โมเดล 3D")} ${step(r.specs > 0, `规格 ${r.specs || ""}`, `ตัวเลือก ${r.specs || ""}`)} ${step(r.copy, "文案", "ข้อความ")}</td>
              <td class="small">${mf || "—"}</td>
              <td class="nowrap"><button class="mini" data-c-prod="${esc(r.product_id)}">${Z("编辑产品", "แก้ไขสินค้า")}</button>${f.failed ? ` <button class="mini" data-c-dl="${esc(r.product_id)}">${Z("重新下载", "ดาวน์โหลดใหม่")}</button>` : ""}</td></tr>`; }).join("")}</tbody></table></div>`
          : UX.empty(Z("还没有采用过模型：在「候选池」里点「采用」，或在模型网站上点扩展的「＋采集」。", "ยังไม่เคยใช้โมเดล: กด「ใช้」ในคลังผู้สมัคร หรือกด「＋เก็บ」ของส่วนขยายบนเว็บโมเดล")) })}
      ${d.downloads.length ? UX.card({ title: Z("文件下载", "การดาวน์โหลดไฟล์"), body: `<table class="grid small"><tbody>${d.downloads.map((x) => `<tr><td class="mono" data-notr>${esc(x.product_id)}</td><td data-notr>${esc(x.name)}</td>
          <td>${pill(FS()[x.state] || x.state, x.state === "failed" ? "bad" : "info")}${x.error ? `<div class="muted" data-notr>${esc(x.error.slice(0, 120))}</div>` : ""}</td></tr>`).join("")}</tbody></table>` }) : ""}`;
  }

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
  document.addEventListener("click", async (e) => {
    const s = sec();
    if (!s || !s.contains(e.target)) return;
    const t = (q) => e.target.closest(q);
    let b;
    if ((b = t(".ux-tabs[data-ux-group='curate'] [data-ux-tab]"))) return goTab(b.dataset.uxTab);
    if ((b = t("[data-ux-go]"))) {
      const g = b.dataset.uxGo;
      if (g.startsWith("tab:")) return;
      if (g === "cand:hi") Object.assign(FC, { min: String(OV.alert_score || 70), ex: "", new: "" });
      else if (g === "cand:new") Object.assign(FC, { new: "1", min: "0" });
      else if (g === "cand:ex") Object.assign(FC, { ex: "1", status: "all", min: "0" });
      LSset("fc", FC);
      return goTab("cur_cand");
    }
    if ((b = t("[data-c-reload]"))) return busy(b, () => show(CUR));
    if ((b = t("[data-c-collect]"))) return busy(b, async () => { const r = await api("/api/cur/candidates/adopt", { json: { ids: [+b.dataset.cCollect] } }); toast(collectMsg(r)); render(); });
    if ((b = t("[data-c-dl]"))) return busy(b, async () => { const r = await api(`/api/cur/products/${encodeURIComponent(b.dataset.cDl)}/download`, { json: {} }); toast(Z(`重新排队 ${r.queued} 个文件`, `เข้าคิวใหม่ ${r.queued} ไฟล์`)); render(); });
    if ((b = t("[data-c-ignore],[data-c-unignore]"))) { await api("/api/cur/candidates/status", { json: { ids: [+(b.dataset.cIgnore || b.dataset.cUnignore)], status: b.dataset.cIgnore ? "ignored" : "" } }); return render(); }
    if ((b = t("[data-c-all]"))) { s.querySelectorAll("[data-c-sel]").forEach((x) => { x.checked = b.checked; }); return; }
    if ((b = t("[data-c-bulk]"))) {
      const ids = [...s.querySelectorAll("[data-c-sel]:checked")].map((x) => +x.dataset.cSel);
      if (!ids.length) return toast(Z("先勾选", "เลือกก่อน"), true);
      return busy(b, async () => {
        if (b.dataset.cBulk === "collect") toast(collectMsg(await api("/api/cur/candidates/adopt", { json: { ids } })));
        else await api("/api/cur/candidates/status", { json: { ids, status: "ignored" } });
        render();
      });
    }
    if ((b = t("[data-c-paste]"))) {
      const box = MODAL.open(`<h3>${Z("贴模型链接采用", "วางลิงก์โมเดลเพื่อใช้")}</h3><p class="small muted">${Z("一行一个 MakerWorld / Printables / Thingiverse 的模型详情页链接。每个马上建一个产品草稿，装了扩展的 Chrome 会在后台读详情页、下载模型文件。", "บรรทัดละลิงก์หน้ารายละเอียดโมเดล แต่ละลิงก์จะสร้างสินค้าฉบับร่างทันที Chrome ที่ติดตั้งส่วนขยายจะอ่านรายละเอียดและดาวน์โหลดไฟล์เบื้องหลัง")}</p>
        <textarea rows="6" style="width:100%" data-p-urls placeholder="https://makerworld.com/en/models/..."></textarea><div class="row gap" style="margin-top:8px"><button class="primary" data-p-go>${Z("采用", "ใช้")}</button><button data-mclose>${Z("取消", "ยกเลิก")}</button></div>`);
      box.onclick = async (ev) => { const g = ev.target.closest("[data-p-go]"); if (!g) return; await busy(g, async () => { toast(collectMsg(await api("/api/cur/candidates/adopt", { json: { urls: box.querySelector("[data-p-urls]").value } }))); MODAL.close(); }); };
      return;
    }
    if ((b = t("[data-c-prod]"))) { e.stopPropagation(); if (window.openProduct) return openProduct(b.dataset.cProd, true); return goTab("library"); }
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
    if ((b = t("[data-w-cand]"))) { Object.assign(FC, { min: "0", ex: "1", status: "all", new: "" }); FC.watch = b.dataset.wCand; LSset("fc", { ...FC, watch: "" }); return goTab("cur_cand"); }
    if ((b = t("[data-w-reset]"))) return busy(b, async () => { await api("/api/cur/pace/reset", { json: { platform: b.dataset.wReset } }); render(); });
    if ((b = t("[data-q-act]"))) return busy(b, async () => { await api("/api/cur/collect/action", { json: { id: +(b.dataset.q || 0), action: b.dataset.qAct } }); render(); });
  });
  function collectMsg(r) {
    const sk = Object.values(r.skipped || {});
    return Z(`采用了 ${r.added} 个，产品库里已建草稿 ${(r.products || []).map((x) => x.product_code).join("、")}`, `ใช้แล้ว ${r.added} รายการ สร้างฉบับร่าง ${(r.products || []).map((x) => x.product_code).join(", ")}`)
      + (sk.length ? Z(`（${sk.length} 个已经采用过）`, ` (${sk.length} รายการใช้แล้ว)`) : "")
      + (r.added ? Z("。扩展会在后台读详情页、下载模型文件。", " ส่วนขยายจะอ่านรายละเอียดและดาวน์โหลดไฟล์เบื้องหลัง") : "");
  }
  let qT = null;
  document.addEventListener("change", (e) => {
    const s = sec();
    if (!s || !s.contains(e.target)) return;
    const i = e.target.closest("[data-fc]");
    if (i && i.dataset.fc !== "q") { FC[i.dataset.fc] = i.type === "checkbox" ? (i.checked ? "1" : "") : i.value; FC.watch = ""; LSset("fc", FC); render(); }
  });
  document.addEventListener("input", (e) => {
    const s = sec();
    if (!s || !s.contains(e.target)) return;
    const i = e.target.closest("[data-fc='q']");
    if (!i) return;
    clearTimeout(qT);
    qT = setTimeout(() => { FC.q = i.value; render().then(() => { const n = s.querySelector("[data-fc='q']"); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }); }, 350);
  });

  window.MODS = window.MODS || {};
  window.MODS.curate = { show };
  window.CURATE = { show };
})();
