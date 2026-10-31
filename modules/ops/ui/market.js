"use strict";
// 运营分析第二期（v2.48）：竞品、爆款雷达、竞店（v2.49 起在「运营 → 市场与竞争」的页签里，页面框架见 hub.js）。界面文字 Z(中文, 泰文)。
// 公共小函数放在 window.OPSU，plan.js（计划、营销日历、流量数据）也用。
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const m = (v) => (v == null || v === "" ? "—" : (v < 0 ? "-฿" : "฿") + Math.abs(Number(v)).toLocaleString(undefined, { maximumFractionDigits: 2 }));
  const n1 = (v, d = 1) => (v == null || v === "" ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const pct = (v) => (v == null ? "—" : `${v}%`);
  const neg = (v) => (v != null && v < 0 ? "bad" : "");
  const PLAT = (p) => ({ lazada: "Lazada", shopee: "Shopee", tiktok: "TikTok" }[p] || p || Z("全部平台", "ทุกแพลตฟอร์ม"));
  const day = (ts) => (ts ? fmtTime(ts) : "—");
  const card = (title, body, extra = "") => `<div class="card"><h3>${title}${extra ? ` <span class="muted small">${extra}</span>` : ""}</h3>${body}</div>`;
  // v2.48.0：上架客服也能看竞品 / 雷达 / 竞店，但成本、利润、平台费那几列和格子不显示（接口也不给这些数）
  const OWN = () => !!(window.OPSH && OPSH.isOwner());
  const MONEY_TXT = /成本|利润|平台费|扣点|最低价|销售额|ต้นทุน|กำไร|ค่าธรรมเนียม|ราคาขั้นต่ำ|ยอดขาย/;
  const tbl = (head, rows, empty) => {
    if (!rows.length) return `<p class="muted">${empty || Z("没有", "ไม่มี")}</p>`;
    let html = `<div class="oa-wrap"><table class="grid"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
    const drop = OWN() ? [] : head.map((h, i) => (MONEY_TXT.test(String(h)) ? i : -1)).filter((i) => i >= 0);
    if (!drop.length) return html;
    const t = document.createElement("template");
    t.innerHTML = html;
    t.content.querySelectorAll("tr").forEach((tr) => { const cells = [...tr.children]; if (cells.length === head.length) drop.slice().reverse().forEach((i) => cells[i] && cells[i].remove()); });
    return t.innerHTML;
  };
  // 员工：页面画好以后把成本利润的格子、成本设置项、「AI 估成本」按钮去掉
  const scrub = (root) => {
    if (OWN() || !root) return;
    root.querySelectorAll(".tile").forEach((x) => { const lab = x.querySelector("span"); if (lab && MONEY_TXT.test(lab.textContent)) x.remove(); else x.querySelectorAll("small").forEach((sm) => { if (MONEY_TXT.test(sm.textContent)) sm.remove(); }); });
    root.querySelectorAll("label").forEach((l) => { const i = l.querySelector("[name]"); if (i && /cost|fee|gram|hour|material/.test(i.name)) l.remove(); });
    root.querySelectorAll("button").forEach((b) => { if (/AI 估成本|AI ประเมินต้นทุน/.test(b.textContent)) b.remove(); });
  };
  if (window.MutationObserver) {
    new MutationObserver(() => { if (!OWN()) ["#tab-ops_market"].forEach((sel) => scrub(document.querySelector(sel))); })
      .observe(document.body, { childList: true, subtree: true });
  }
  const img = (u, s = 40) => (u ? `<img class="oa-thumb" src="${esc(u)}" referrerpolicy="no-referrer" loading="lazy" style="width:${s}px;height:${s}px" alt="">` : "");
  const link = (u, t) => (u ? `<a href="${esc(u)}" target="_blank" rel="noopener" data-notr>${esc(t || u)}</a>` : `<span data-notr>${esc(t || "")}</span>`);
  const conf = (c) => (c ? `<span class="oa-pill ${c === "实测" ? "ok" : "warn"}">${c === "实测" ? Z("实测", "วัดจริง") : Z("估", "ประมาณ")}</span>` : "");
  const form = (root) => { const o = {}; root.querySelectorAll("[name]").forEach((i) => { o[i.name] = i.type === "checkbox" ? i.checked : i.value; }); return o; };
  const fill = (root, d) => { for (const [k, v] of Object.entries(d || {})) { const i = root.querySelector(`[name="${k}"]`); if (i && v != null && v !== "") i.value = typeof v === "boolean" ? (v ? "1" : "0") : v; } };
  window.OPSU = { $, Z, m, n1, pct, neg, PLAT, day, card, tbl, img, link, conf, form, fill };

  const BOX = { ops_comp: "ops-comp", ops_radar: "ops-radar", ops_shops: "ops-shops" };
  async function show(tab) {
    const box = $("#" + BOX[tab]);
    if (!box) return;
    if (!box.innerHTML) box.innerHTML = `<p class="muted">${Z("加载中…", "กำลังโหลด…")}</p>`;
    try {
      if (tab === "ops_comp") return await compPage(box);
      if (tab === "ops_radar") return await radarPage(box);
      if (tab === "ops_shops") return await shopsPage(box);
    } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
  }
  const extHint = () => `<p class="small muted">${Z("浏览器扩展（和 AI 客服同一个，系统 → 设置 → 组件与插件 下载）装好后：在 Lazada / Shopee / TikTok 的商品页、搜索页、店铺页右下角点按钮就能采集；插件图标里还有「今日巡逻」。",
    "หลังติดตั้งส่วนขยายเบราว์เซอร์ (ตัวเดียวกับ AI แชท ดาวน์โหลดที่ ระบบ → ตั้งค่า → ส่วนประกอบและปลั๊กอิน): กดปุ่มมุมขวาล่างในหน้าสินค้า หน้าค้นหา หน้าร้านของ Lazada / Shopee / TikTok เพื่อเก็บข้อมูล และมี「ตระเวนวันนี้」ในไอคอนส่วนขยาย")}</p>`;

  // ======================= 竞品 =======================
  let COMP = null, CVIEW = "cmp", CDET = null, CADD = false;
  const CSEL = new Set();
  const SNAP_INPUTS = [["price", "售价 ฿", "ราคา ฿"], ["list_price", "划线原价 ฿", "ราคาก่อนลด ฿"], ["voucher", "店铺券减 ฿", "คูปองร้านลด ฿"],
    ["sold_text", "累计已售（如 1.2k）", "ขายแล้ว (เช่น 1.2k)"], ["sold_30d", "近 30 天已售（页面上有才填）", "ขาย 30 วัน (ถ้ามี)"], ["reviews", "评价数", "จำนวนรีวิว"], ["rating", "评分", "คะแนน"]];
  const snapFields = () => `<div class="oa-fgrid">${SNAP_INPUTS.map(([k, zh, th]) => `<label>${Z(zh, th)}<input name="${k}"></label>`).join("")}
    <label>${Z("包邮", "ส่งฟรี")}<select name="free_ship"><option value="">—</option><option value="1">${Z("是", "ใช่")}</option><option value="0">${Z("否", "ไม่")}</option></select></label></div>`;
  const pasteBox = () => `<p class="small">${Z("在竞品商品页按 Ctrl+A 全选、Ctrl+C 复制，粘到下面点「识别」，自动填数字（配了 AI 用 AI，没配只认常见写法）。装了浏览器扩展就不用粘贴，直接在商品页点「📊 采集竞品」。",
    "ในหน้าสินค้าคู่แข่งกด Ctrl+A แล้ว Ctrl+C วางด้านล่างแล้วกด「อ่านข้อมูล」 ระบบจะกรอกตัวเลขให้ (ถ้าติดตั้งส่วนขยายแล้ว กด「📊 เก็บข้อมูลคู่แข่ง」ในหน้าสินค้าได้เลย)")}</p>
    <textarea name="_text" rows="4" class="oa-full"></textarea><div class="row gap"><button class="mini" data-c-extract>${Z("识别", "อ่านข้อมูล")}</button><span class="small muted" data-c-exmsg></span></div>`;

  async function compPage(box) {
    COMP = await api("/api/oa/comp");
    const views = [["cmp", Z("我的商品 vs 竞品", "สินค้าเรา vs คู่แข่ง")], ["all", Z("全部竞品", "คู่แข่งทั้งหมด")], ["radar", Z("选品雷达", "เรดาร์คัดสินค้า")], ["ev", Z("竞品动态", "ความเคลื่อนไหวคู่แข่ง")]];
    box.innerHTML = `${COMP.ai ? "" : `<div class="warn-box small">${Z("还没设置 AI（设置 → AI）：粘贴页面文字只能识别常见写法，也不能自动估成本；手动填数字可以用。", "ยังไม่ได้ตั้งค่า AI (ตั้งค่า → AI): อ่านข้อความได้เฉพาะรูปแบบทั่วไป และประมาณต้นทุนอัตโนมัติไม่ได้ กรอกตัวเลขเองได้")}</div>`}
      <div class="row gap wrap" style="margin-bottom:8px"><div class="chips">${views.map(([k, l]) => `<button class="chip ${k === CVIEW ? "on" : ""}" data-cview="${k}">${l}</button>`).join("")}</div>
        <span style="flex:1"></span><button class="mini" data-c-cmp>${Z("横向对比勾选的", "เปรียบเทียบที่เลือก")}（<span data-c-n>${CSEL.size}</span>）</button>
        <button data-c-add>${Z("＋ 添加竞品", "＋ เพิ่มคู่แข่ง")}</button></div>
      <datalist id="oa-skulist">${COMP.skus.map((s) => `<option value="${esc(s.sku)}">${esc(s.name)} ${esc(s.color || "")}</option>`).join("")}</datalist>
      <div id="oc-add"></div><div id="oc-det"></div><div id="oc-body"></div>${extHint()}`;
    renderAdd(); compRender();
    if (CDET) compDetail(CDET);
    box.onclick = compClick;
    box.onchange = async (e) => {
      const c = e.target.closest("[data-c-sel]");
      if (c) { c.checked ? CSEL.add(+c.dataset.cSel) : CSEL.delete(+c.dataset.cSel); $("[data-c-n]", box).textContent = CSEL.size; }
      const r = e.target.closest("[data-c-radar]");
      if (r) { await api(`/api/oa/comp/${r.dataset.cRadar}`, { json: { radar_status: r.value } }); toast(Z("已保存", "บันทึกแล้ว")); }
    };
  }
  function compRow(r) {
    const e = r.est;
    return `<tr><td><div class="oa-pic">${img(r.image)}<div><input type="checkbox" data-c-sel="${r.id}" ${CSEL.has(r.id) ? "checked" : ""}> ${link(r.url, (r.title || r.item_key || "#" + r.id).slice(0, 70))}
        <div class="small muted">${esc(PLAT(r.platform))} · <span data-notr>${esc(r.shop || "")}</span>${r.skus.length ? ` · <span class="mono" data-notr>${esc(r.skus.join(", "))}</span>` : ""}${r.status === "archived" ? ` · ${Z("已归档", "เก็บแล้ว")}` : ""}</div></div></div></td>
      <td class="num">${m(e.price_eff)}${e.voucher ? `<div class="small muted">${Z("券", "คูปอง")} -${m(e.voucher)}</div>` : ""}</td>
      <td class="num" title="${esc(Z(e.method || e.note || "", e.method_th || e.note_th || ""))}">${n1(e.daily)} ${conf(e.confidence)}</td><td class="num">${n1(e.d7, 0)}</td><td class="num">${m(e.rev_7d)}</td>
      <td class="num" title="${esc(Z(e.fee_src, e.fee_src_th))}">${m(e.fee_unit)}<div class="small muted">${e.fee_rate != null ? (e.fee_rate * 100).toFixed(1) + "%" : ""}</div></td>
      <td class="num" title="${esc(Z(e.cost_src, e.cost_src_th))}">${m(e.unit_cost)}</td>
      <td class="num ${neg(e.profit_unit)}">${m(e.profit_unit)}${e.margin != null ? `<div class="small muted">${e.margin}%</div>` : ""}</td><td class="num">${m(e.profit_7d)}</td>
      <td class="small nowrap">${day(e.last_ts)}${e.stale ? ` <span class="warn">${Z("要更新", "ต้องอัปเดต")}</span>` : ""}</td>
      <td class="nowrap"><button class="mini" data-c-det="${r.id}">${Z("详情 / 更新", "รายละเอียด / อัปเดต")}</button></td></tr>`;
  }
  const COMP_HEAD = () => [Z("竞品", "คู่แข่ง"), Z("到手价", "ราคาสุทธิ"), Z("日销", "ขาย/วัน"), Z("7 日销量", "ขาย 7 วัน"), Z("7 日销售额", "ยอดขาย 7 วัน"),
    Z("平台费/件", "ค่าธรรมเนียม/ชิ้น"), Z("生产成本/件", "ต้นทุน/ชิ้น"), Z("单件利润", "กำไร/ชิ้น"), Z("7 日利润", "กำไร 7 วัน"), Z("更新于", "อัปเดต"), ""];
  function compRender() {
    const body = $("#oc-body");
    document.querySelectorAll("[data-cview]").forEach((b) => b.classList.toggle("on", b.dataset.cview === CVIEW));
    if (CVIEW === "all") {
      body.innerHTML = tbl(COMP_HEAD(), COMP.rows.map(compRow), Z("还没有竞品：点「＋ 添加竞品」，或者用浏览器扩展在商品页采集。", "ยังไม่มีคู่แข่ง: กด「＋ เพิ่มคู่แข่ง」 หรือเก็บด้วยส่วนขยายในหน้าสินค้า"))
        + `<p class="small muted">${Z("日销：两次「累计已售」相减 ÷ 天数（实测）；只有评价数时按留评比例估。Lazada 平台费用第一期财务流水算出的真实扣点。鼠标停在数字上看来源。",
          "ขาย/วัน: ผลต่างยอดขายสะสม 2 ครั้ง ÷ จำนวนวัน (วัดจริง) ถ้ามีแค่รีวิวจะประมาณจากอัตรารีวิว ค่าธรรมเนียม Lazada ใช้อัตราจริงจากรายการการเงิน ชี้เมาส์ที่ตัวเลขเพื่อดูที่มา")}</p>`;
    } else if (CVIEW === "cmp") {
      body.innerHTML = COMP.compare.length ? COMP.compare.map((g) => {
        const rows = COMP.rows.filter((r) => g.comp_ids.includes(r.id));
        const share = g.comp_daily_total ? n1((g.my_daily / (g.my_daily + g.comp_daily_total)) * 100) + "%" : "—";
        return card(`<span class="mono" data-notr>${esc(g.sku)}</span> <span data-notr>${esc(g.name || Z("（ERP 里没有这个 SKU）", "(ไม่มี SKU นี้ใน ERP)"))} ${esc(g.color || "")}</span> · ${esc(PLAT(g.platform))}
          <button class="mini" data-c-plan="${esc(g.sku)}|${esc(g.platform)}">${Z("建计划", "สร้างแผน")}</button>`,
          `<div class="tiles">
            <div class="tile"><span>${Z("我的售价", "ราคาของเรา")}</span><b>${m(g.my_price)}</b><small>${Z("竞品中位", "ค่ากลางคู่แข่ง")} ${m(g.comp_price_median)}（${g.price_vs_median_pct > 0 ? "+" : ""}${n1(g.price_vs_median_pct)}%）${g.price_pos ? ` · ${Z("从低到高排第", "อันดับราคาต่ำ→สูง")} ${g.price_pos.rank}/${g.price_pos.of}` : ""}</small></div>
            <div class="tile"><span>${Z("我的日销（30 天，ERP 订单）", "ยอดขาย/วันของเรา (30 วัน ออเดอร์ ERP)")}</span><b>${n1(g.my_daily, 2)}</b><small>${Z("竞品最高", "คู่แข่งสูงสุด")} ${n1(g.comp_daily_top)} · ${Z("合计", "รวม")} ${n1(g.comp_daily_total)}</small></div>
            <div class="tile"><span>${Z("我的单件利润", "กำไร/ชิ้นของเรา")}</span><b class="${neg(g.my_profit_unit)}">${m(g.my_profit_unit)}</b><small>${Z("最低价", "ราคาขั้นต่ำ")} ${m(g.floor_price)} · ${Z("成本", "ต้นทุน")} ${m(g.my_unit_cost)}</small></div>
            <div class="tile"><span>${Z("市场份额（按日销）", "ส่วนแบ่งตลาด (ตามยอดขาย/วัน)")}</span><b>${share}</b><small>${g.comp_count} ${Z("个竞品", "คู่แข่ง")}</small></div></div>`
          + tbl(COMP_HEAD(), rows.map(compRow)));
      }).join("") : `<p class="muted">${Z("还没有关联到我方 SKU 的竞品。添加竞品时填上要对比的 SKU；没填的在「选品雷达」里。", "ยังไม่มีคู่แข่งที่ผูกกับ SKU ของเรา ตอนเพิ่มคู่แข่งให้กรอก SKU ที่จะเทียบ ที่ไม่ได้กรอกอยู่ใน「เรดาร์คัดสินค้า」")}</p>`;
    } else if (CVIEW === "radar") {
      const R = { new: Z("待看", "รอดู"), want: Z("要做", "จะทำ"), skip: Z("不做", "ไม่ทำ"), done: Z("已做", "ทำแล้ว") };
      body.innerHTML = tbl([Z("竞品", "คู่แข่ง"), Z("日销", "ขาย/วัน"), Z("到手价", "ราคาสุทธิ"), Z("单件利润", "กำไร/ชิ้น"), Z("月利润（推算）", "กำไร/เดือน (ประมาณ)"), Z("每天要打印", "ต้องพิมพ์/วัน"), Z("状态", "สถานะ"), ""],
        COMP.radar.map((r) => `<tr><td><div class="oa-pic">${img(r.image)}<div>${link(r.url, (r.title || "#" + r.id).slice(0, 70))}<div class="small muted">${esc(PLAT(r.platform))} · <span data-notr>${esc(r.shop || "")}</span></div></div></div></td>
          <td class="num">${n1(r.daily)} ${conf(r.confidence)}</td><td class="num">${m(r.price_eff)}</td><td class="num ${neg(r.profit_unit)}">${m(r.profit_unit)}${r.margin != null ? `<div class="small muted">${r.margin}%</div>` : ""}</td>
          <td class="num"><b>${m(r.profit_30d)}</b></td><td class="num">${r.print_hours_daily != null ? `${r.print_hours_daily} ${Z("小时", "ชม.")}${r.capacity_share != null ? `<div class="small muted">${Z("产能", "กำลังผลิต")} ${r.capacity_share}%</div>` : ""}` : "—"}</td>
          <td><select data-c-radar="${r.id}">${Object.entries(R).map(([k, l]) => `<option value="${k}" ${k === r.radar_status ? "selected" : ""}>${l}</option>`).join("")}</select></td>
          <td><button class="mini" data-c-det="${r.id}">${Z("详情", "รายละเอียด")}</button></td></tr>`), Z("没有：所有竞品都关联了我方 SKU", "ไม่มี: คู่แข่งทุกตัวผูก SKU แล้ว"))
        + `<p class="small muted">${Z("选品雷达 = 还没关联我方 SKU 的竞品，按推算的月利润排。利润要先有生产成本：详情里点「AI 估成本」或手动填。标「要做」会进今日待办。",
          "เรดาร์คัดสินค้า = คู่แข่งที่ยังไม่ผูก SKU ของเรา เรียงตามกำไรต่อเดือนที่ประมาณ ต้องมีต้นทุนก่อน: กด「AI ประมาณต้นทุน」ในรายละเอียดหรือกรอกเอง ที่ตั้ง「จะทำ」จะขึ้นในงานวันนี้")}</p>`;
    } else {
      body.innerHTML = tbl([Z("时间", "เวลา"), Z("说明", "รายละเอียด")], COMP.events.map((e) => `<tr><td class="small nowrap">${day(e.ts)}</td>
        <td><div class="oa-pic">${img(e.image, 32)}<div data-notr>${esc(Z(e.text, e.text_th || e.text))}</div></div></td></tr>`), Z("近 14 天没有竞品动态（降价、开券、放量、改标题）", "14 วันที่ผ่านมาไม่มีความเคลื่อนไหว (ลดราคา คูปอง ยอดพุ่ง เปลี่ยนชื่อ)"));
    }
  }
  function renderAdd() {
    const b = $("#oc-add");
    if (!CADD) { b.innerHTML = ""; return; }
    b.innerHTML = card(Z("添加竞品", "เพิ่มคู่แข่ง"), `<div class="oa-fgrid">
        <label class="oa-span">${Z("商品链接", "ลิงก์สินค้า")}<input name="url" placeholder="https://www.lazada.co.th/products/...-i123456-s789.html"></label>
        <label class="oa-span">${Z("对比我方 SKU（逗号分隔；不填 = 放进选品雷达）", "SKU ของเราที่จะเทียบ (คั่นด้วยจุลภาค ว่าง = เข้าเรดาร์คัดสินค้า)")}<input name="skus" list="oa-skulist"></label>
        <label class="oa-span">${Z("标题", "ชื่อสินค้า")}<input name="title"></label><label>${Z("店铺", "ร้าน")}<input name="shop"></label>
        <label>${Z("上架日期（知道才填）", "วันลงขาย (ถ้ารู้)")}<input name="listed_on" type="date"></label></div>${pasteBox()}${snapFields()}
      <div class="row gap"><button data-c-save>${Z("保存", "บันทึก")}</button><button class="mini" data-c-addclose>${Z("取消", "ยกเลิก")}</button></div>`);
  }
  async function compDetail(id) {
    CDET = id;
    const d = await api(`/api/oa/comp/${id}`);
    const c = d.comp, e = d.est;
    const b = $("#oc-det");
    if (!b) return;
    b.innerHTML = card(`${img(c.image, 48)} <span data-notr>${esc((c.title || c.item_key || "#" + c.id).slice(0, 80))}</span> <span class="muted small">${esc(PLAT(c.platform))}</span>
      <button class="mini" data-c-detclose>${Z("关闭", "ปิด")}</button>`,
      `<div class="tiles">
        <div class="tile"><span>${Z("到手价", "ราคาสุทธิ")}</span><b>${m(e.price_eff)}</b><small>${Z("已售", "ขายแล้ว")} ${esc(e.sold_text || "—")} · ${Z("评价", "รีวิว")} ${n1(e.reviews, 0)} · ★${n1(e.rating)}</small></div>
        <div class="tile"><span>${Z("日销", "ขาย/วัน")} ${conf(e.confidence)}</span><b>${n1(e.daily)}</b><small>${esc(Z(e.method || e.note, e.method_th || e.note_th))}</small></div>
        <div class="tile"><span>${Z("单件利润", "กำไร/ชิ้น")}</span><b class="${neg(e.profit_unit)}">${m(e.profit_unit)}</b><small>${Z("平台费", "ค่าธรรมเนียม")} ${m(e.fee_unit)}（${esc(Z(e.fee_src, e.fee_src_th))}）· ${Z("成本", "ต้นทุน")} ${m(e.unit_cost)}（${esc(Z(e.cost_src, e.cost_src_th))}）</small></div>
        <div class="tile"><span>${Z("30 天（推算）", "30 วัน (ประมาณ)")}</span><b>${m(e.rev_30d)}</b><small>${Z("利润", "กำไร")} ${m(e.profit_30d)} · ${Z("每天要打印", "ต้องพิมพ์/วัน")} ${e.print_hours_daily ?? "—"} ${Z("小时", "ชม.")}</small></div></div>
      <h4>${Z("资料和成本", "ข้อมูลและต้นทุน")}</h4><div class="oa-fgrid" data-c-edit>
        <label class="oa-span">${Z("商品链接", "ลิงก์สินค้า")}<input name="url" value="${esc(c.url || "")}"></label>
        <label class="oa-span">${Z("标题", "ชื่อสินค้า")}<input name="title" value="${esc(c.title || "")}"></label>
        <label>${Z("店铺", "ร้าน")}<input name="shop" value="${esc(c.shop || "")}"></label>
        <label>${Z("对比我方 SKU", "SKU ของเราที่เทียบ")}<input name="skus" list="oa-skulist" value="${esc(c.skus.join(", "))}"></label>
        <label>${Z("上架日期", "วันลงขาย")}<input name="listed_on" type="date" value="${esc(c.listed_on || "")}"></label>
        <label>${Z("估克重 g", "กรัมโดยประมาณ")}<input name="est_grams" value="${esc(c.est_grams ?? "")}"></label>
        <label>${Z("估打印小时", "ชม.พิมพ์โดยประมาณ")}<input name="est_hours" value="${esc(c.est_hours ?? "")}"></label>
        <label>${Z("材料", "วัสดุ")}<select name="est_material">${["", "PLA", "PETG", "TPU", "RESIN"].map((x) => `<option ${x === (c.est_material || "") ? "selected" : ""}>${x}</option>`).join("")}</select></label>
        <label>${Z("手动成本 ฿/件", "ต้นทุนกรอกเอง ฿/ชิ้น")}<input name="est_unit_cost" value="${esc(c.est_unit_cost ?? "")}"></label>
        <label>${Z("成本用哪个", "ใช้ต้นทุนแบบไหน")}<select name="cost_source">${[["", Z("自动", "อัตโนมัติ")], ["manual", Z("手动填的", "กรอกเอง")], ["sku", Z("关联的我方 SKU", "SKU ของเรา")], ["ai", Z("AI 估克重时长", "AI ประมาณ")]]
          .map(([k, l]) => `<option value="${k}" ${k === (c.cost_source || "") ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label>${Z("这个竞品的平台扣点（%，空 = 自动）", "ค่าธรรมเนียมของคู่แข่งนี้ (% ว่าง = อัตโนมัติ)")}<input name="fee_rate_override" value="${c.fee_rate_override != null ? Math.round(c.fee_rate_override * 1000) / 10 : ""}"></label>
        <label class="oa-span">${Z("备注 / 规格", "หมายเหตุ / สเปก")}<input name="note" value="${esc(c.note || "")}"></label></div>
      ${c.cost_note ? `<p class="small muted">AI：<span data-notr>${esc(c.cost_note)}</span></p>` : ""}
      <div class="row gap wrap"><button data-c-upd="${c.id}">${Z("保存资料", "บันทึกข้อมูล")}</button><button class="mini" data-c-aicost="${c.id}">${Z("AI 估成本", "AI ประมาณต้นทุน")}</button>
        <button class="mini" data-c-arch="${c.id}" data-st="${c.status === "archived" ? "active" : "archived"}">${c.status === "archived" ? Z("恢复", "กู้คืน") : Z("归档（不再跟踪）", "เก็บ (ไม่ติดตามแล้ว)")}</button></div>
      <h4>${Z("记一次数据（隔天再记，日销才算得出）", "บันทึกข้อมูล (บันทึกอีกครั้งวันถัดไปจะได้ยอดขาย/วัน)")}</h4><div data-c-snapbox>${pasteBox()}${snapFields()}
        <button data-c-snap="${c.id}">${Z("记下", "บันทึก")}</button></div>
      <h4>${Z("历史记录", "ประวัติ")}</h4>` + tbl([Z("时间", "เวลา"), Z("售价", "ราคา"), Z("券", "คูปอง"), Z("累计已售", "ขายสะสม"), Z("近 30 天", "30 วัน"), Z("评价", "รีวิว"), Z("评分", "คะแนน"), Z("来源", "ที่มา"), ""],
        d.snaps.slice().reverse().map((s) => `<tr><td class="small nowrap">${day(s.ts)}</td><td class="num">${m(s.price)}</td><td class="num">${m(s.voucher)}</td><td class="num" data-notr>${esc(s.sold_text || n1(s.sold_total, 0))}</td>
          <td class="num">${n1(s.sold_30d, 0)}</td><td class="num">${n1(s.reviews, 0)}</td><td class="num">${n1(s.rating)}</td><td class="small" data-notr>${esc(s.source || "")}</td>
          <td><button class="mini" data-c-snapdel="${s.id}">${Z("删", "ลบ")}</button></td></tr>`)));
    b.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function extractInto(btn) {
    const root = btn.closest(".card");
    const ta = root.querySelector('[name="_text"]'), msg = root.querySelector("[data-c-exmsg]");
    const urlI = root.querySelector('[name="url"]');
    await busy(btn, async () => {
      const r = await apiJob("/api/oa/comp/extract", { json: { text: ta.value, url: urlI ? urlI.value : "" } });
      fill(root, r.data);
      msg.textContent = r.how === "ai" ? Z("已识别，请核对", "อ่านแล้ว กรุณาตรวจ") : Z("没设置 AI，用简单规则识别了一部分，请核对", "ยังไม่ได้ตั้ง AI อ่านได้บางส่วน กรุณาตรวจ");
    });
  }
  async function compClick(e) {
    const t = (s) => e.target.closest(s);
    let b;
    if ((b = t("[data-cview]"))) { CVIEW = b.dataset.cview; return compRender(); }
    if (t("[data-c-add]")) { CADD = !CADD; return renderAdd(); }
    if (t("[data-c-addclose]")) { CADD = false; return renderAdd(); }
    if (t("[data-c-detclose]")) { CDET = null; $("#oc-det").innerHTML = ""; return; }
    if ((b = t("[data-c-extract]"))) return extractInto(b);
    if ((b = t("[data-c-det]"))) return compDetail(+b.dataset.cDet);
    if ((b = t("[data-c-plan]"))) { const [sku, platform] = b.dataset.cPlan.split("|"); window.OPS_PLAN_PREFILL = { sku, platform }; return goTab("ops_plans"); }
    if ((b = t("[data-c-cmp]"))) return compareBox([...CSEL]);
    if ((b = t("[data-c-save]"))) {
      const f = form($("#oc-add")); delete f._text;
      return busy(b, async () => { const r = await api("/api/oa/comp", { json: f }); toast(r.new ? Z("已加入竞品", "เพิ่มคู่แข่งแล้ว") : Z("这个商品已经在竞品库里，已更新", "สินค้านี้มีอยู่แล้ว อัปเดตแล้ว")); CADD = false; CDET = r.id; show("ops_comp"); });
    }
    if ((b = t("[data-c-upd]"))) {
      const f = form($("[data-c-edit]")); f.fee_rate_override = f.fee_rate_override === "" ? null : f.fee_rate_override;
      ["est_grams", "est_hours", "est_unit_cost"].forEach((k) => { if (f[k] === "") f[k] = null; });
      return busy(b, async () => { await api(`/api/oa/comp/${b.dataset.cUpd}`, { json: f }); toast(Z("已保存", "บันทึกแล้ว")); show("ops_comp"); });
    }
    if ((b = t("[data-c-aicost]"))) return busy(b, async () => { const r = await apiJob(`/api/oa/comp/${b.dataset.cAicost}/ai-cost`, { json: {} }); toast(`${r.grams}g / ${r.hours}h`); show("ops_comp"); });
    if ((b = t("[data-c-arch]"))) return busy(b, async () => { await api(`/api/oa/comp/${b.dataset.cArch}`, { json: { status: b.dataset.st } }); CDET = null; show("ops_comp"); });
    if ((b = t("[data-c-snap]"))) {
      const f = form($("[data-c-snapbox]")); delete f._text;
      return busy(b, async () => { await api(`/api/oa/comp/${b.dataset.cSnap}/snap`, { json: f }); toast(Z("已记下", "บันทึกแล้ว")); show("ops_comp"); });
    }
    if ((b = t("[data-c-snapdel]"))) { if (!confirm(Z("删掉这条记录？", "ลบบันทึกนี้?"))) return; await api(`/api/oa/comp/snap/${b.dataset.cSnapdel}/delete`, { json: {} }); return show("ops_comp"); }
  }
  async function compareBox(ids) {
    if (!ids.length) return toast(Z("先勾选要对比的竞品", "เลือกคู่แข่งที่จะเทียบก่อน"), true);
    const d = await api(`/api/oa/comp/compare?ids=${ids.join(",")}`);
    const rows = d.rows || [];
    const best = (f, hi) => { const v = rows.map((x) => x.est[f]).filter((x) => x != null); return v.length ? (hi ? Math.max(...v) : Math.min(...v)) : null; };
    const line = (label, f, fmt, hi) => { const bb = hi == null ? null : best(f, hi);
      return `<tr><th>${label}</th>${rows.map((x) => `<td class="num ${bb != null && rows.length > 1 && x.est[f] === bb ? "ok" : ""}">${fmt(x.est[f], x)}</td>`).join("")}</tr>`; };
    $("#oc-det").innerHTML = card(`${Z("横向对比", "เปรียบเทียบ")} <button class="mini" data-c-detclose>${Z("关闭", "ปิด")}</button>`, `<div class="oa-wrap"><table class="grid"><tr><th></th>${rows.map((x) => `<th>${img(x.image, 64)}<br>${link(x.url, (x.title || "#" + x.id).slice(0, 40))}<div class="small muted">${esc(PLAT(x.platform))}</div></th>`).join("")}</tr>
      ${line(Z("到手价", "ราคาสุทธิ"), "price_eff", (v) => m(v), false)}${line(Z("已售", "ขายแล้ว"), "sold_text", (v) => esc(v || "—"))}
      ${line(Z("评价数", "รีวิว"), "reviews", (v) => n1(v, 0), true)}${line(Z("日销", "ขาย/วัน"), "daily", (v, x) => `${n1(v)} ${conf(x.est.confidence)}`, true)}
      ${line(Z("7 日销售额", "ยอดขาย 7 วัน"), "rev_7d", (v) => m(v), true)}${line(Z("平台费/件", "ค่าธรรมเนียม/ชิ้น"), "fee_unit", (v) => m(v), false)}
      ${line(Z("生产成本/件", "ต้นทุน/ชิ้น"), "unit_cost", (v) => m(v), false)}${line(Z("单件利润", "กำไร/ชิ้น"), "profit_unit", (v) => m(v), true)}
      ${line(Z("30 日利润", "กำไร 30 วัน"), "profit_30d", (v) => m(v), true)}${line(Z("每天要打印（小时）", "ต้องพิมพ์/วัน (ชม.)"), "print_hours_daily", (v) => n1(v))}</table></div>
      <p class="small muted">${Z("绿色 = 这一行里最好的（价格、成本越低越好，其他越高越好）。", "สีเขียว = ดีที่สุดในแถว (ราคา ต้นทุน ยิ่งต่ำยิ่งดี อื่นๆ ยิ่งสูงยิ่งดี)")}</p>`);
  }

  // ======================= 爆款雷达 =======================
  let RAD = null, RDET = null;
  const KST = () => ({ new: Z("新", "ใหม่"), watch: Z("观察", "เฝ้าดู"), want: Z("要做", "จะทำ"), skip: Z("不做", "ไม่ทำ"), done: Z("已做", "ทำแล้ว") });
  const curOn = () => !!(window.MODKIT && MODKIT.enabled("curate"));       // v2.50 选品模块开着才有「去模型站找」
  const searchUrl = (p, k) => (p === "shopee" ? "https://shopee.co.th/search?keyword=" : "https://www.lazada.co.th/catalog/?q=") + encodeURIComponent(k);
  async function radarPage(box) {
    RAD = await api("/api/oa/radar");
    const p = RAD.patrol;
    const parts = (o) => `${Z("需求", "ความต้องการ")} ${o.parts.demand} · ${Z("竞争少", "แข่งน้อย")} ${o.parts.competition} · ${Z("能打印", "พิมพ์ได้")} ${o.parts.printable} · ${Z("利润", "กำไร")} ${o.parts.profit} · ${Z("潜力", "ศักยภาพ")} ${o.parts.potential}`;
    box.innerHTML = `${RAD.ai ? "" : `<div class="warn-box small">${Z("还没设置 AI：「能不能打印」「侵权风险」「小爆潜力」按 50 分算。到「设置 → AI」填密钥。", "ยังไม่ได้ตั้ง AI: พิมพ์ได้ไหม / เสี่ยงลิขสิทธิ์ / ศักยภาพ คิดเป็น 50 คะแนน")}</div>`}
      <div class="tiles"><div class="tile"><span>${Z("今天已巡逻 / 上限", "ตระเวนวันนี้ / สูงสุด")}</span><b>${p.done} / ${p.cap}</b><small>${Z("每页停留", "อยู่หน้าละ")} ${p.wait[0]}–${p.wait[1]} ${Z("秒", "วินาที")}</small></div>
        <div class="tile"><span>${Z("待巡逻页面", "หน้าที่รอตระเวน")}</span><b>${p.total}</b><small>${Z("关键词搜索页 + 盯着的店铺 + 竞品页", "หน้าค้นหา + ร้านที่เฝ้า + หน้าคู่แข่ง")}</small></div>
        <div class="tile"><span>${Z("关键词", "คีย์เวิร์ด")}</span><b>${RAD.rows.length}</b><small>${Z(`${RAD.alert_score} 分以上进今日待办`, `${RAD.alert_score} คะแนนขึ้นไปเข้างานวันนี้`)}</small></div></div>
      <p class="small">${Z("巡逻：人在电脑旁时，点浏览器扩展图标 →「🔭 开始今日巡逻」，扩展按清单一页一页打开、慢慢滚动后读页面上公开的数字；每天有上限，遇到验证码马上停。建议用一个没登录卖家账号的单独 Chrome 用户巡逻。",
        "ตระเวน: ตอนอยู่หน้าคอม กดไอคอนส่วนขยาย →「🔭 เริ่มตระเวนวันนี้」 ส่วนขยายจะเปิดทีละหน้า เลื่อนช้าๆ แล้วอ่านตัวเลขที่เปิดเผย มีจำนวนสูงสุดต่อวัน เจอแคปช่าจะหยุดทันที แนะนำใช้โปรไฟล์ Chrome แยกที่ไม่ได้ล็อกอินบัญชีผู้ขาย")}</p>
      ${card(Z("加关键词", "เพิ่มคีย์เวิร์ด"), `<div class="row gap wrap"><select data-r-plat><option value="lazada">Lazada</option><option value="shopee">Shopee</option></select>
        <textarea data-r-kws rows="2" style="flex:1;min-width:220px" placeholder="${Z("一行一个（泰文），例如 ที่วางโทรศัพท์", "บรรทัดละคำ เช่น ที่วางโทรศัพท์")}"></textarea>
        <button data-r-add>${Z("加入", "เพิ่ม")}</button><button class="mini" data-r-import>${Z("从产品搜索词导入", "นำเข้าจากคีย์เวิร์ดสินค้า")}</button><button class="mini" data-r-report>${Z("现在发一次机会日报", "ส่งรายงานโอกาสตอนนี้")}</button></div>
        <p class="small muted">${Z("「从产品搜索词导入」：把每个产品「搜索优化」里的标题主词和核心词加进来巡逻（搜索词只存在产品里，雷达不另存一份）。表里「我们的产品」= 搜索词或泰文标题里已经有这个词的产品。",
          "「นำเข้าจากคีย์เวิร์ดสินค้า」: เพิ่มคำหลักในชื่อและคำหลักจาก「ปรับปรุงการค้นหา」ของแต่ละสินค้า 「สินค้าของเรา」= สินค้าที่มีคำนี้ในคีย์เวิร์ดหรือชื่อภาษาไทยแล้ว")}</p>`)}
      <div id="or-det"></div>
      ${tbl([Z("关键词", "คีย์เวิร์ด"), Z("机会分", "คะแนนโอกาส"), Z("前 10 日销", "ขาย/วัน 10 อันดับแรก"), Z("结果数", "ผลค้นหา"), Z("到手价中位", "ราคากลาง"), Z("单件利润", "กำไร/ชิ้น"), Z("我们的产品", "สินค้าของเรา"), Z("状态", "สถานะ"), ""],
        RAD.rows.map((r) => { const o = r.opp; return `<tr class="${r.active ? "" : "muted"}"><td><b data-notr>${esc(r.keyword)}</b> <span class="small muted">${esc(PLAT(r.platform))}</span>
          <div class="small">${link(searchUrl(r.platform, r.keyword), Z("打开搜索页", "เปิดหน้าค้นหา"))} · ${o.searched_at ? day(o.searched_at) : Z("还没采集", "ยังไม่เก็บ")}</div></td>
          <td class="num"><b class="${o.ip_risk ? "bad" : o.score >= RAD.alert_score ? "ok" : ""}">${o.score}</b>${o.ip_risk ? ` <span class="bad small">${Z("侵权", "ลิขสิทธิ์")}</span>` : ""}<div class="small muted">${parts(o)}</div></td>
          <td class="num">${n1(o.daily_top10)} ${conf(o.demand_conf)}</td><td class="num">${n1(o.total_results, 0)}</td><td class="num">${m(o.price_median)}</td>
          <td class="num ${neg(o.profit_unit)}">${m(o.profit_unit)}${o.margin != null ? `<div class="small muted">${o.margin}%</div>` : ""}</td>
          <td class="small mono" data-notr>${esc((r.products || []).join(", ")) || "—"}</td>
          <td><select data-r-st="${r.id}">${Object.entries(KST()).map(([k, l]) => `<option value="${k}" ${k === r.status ? "selected" : ""}>${l}</option>`).join("")}</select>
            <label class="small"><input type="checkbox" data-r-act="${r.id}" ${r.active ? "checked" : ""}> ${Z("巡逻", "ตระเวน")}</label></td>
          <td class="nowrap"><button class="mini" data-r-det="${r.id}">${Z("详情", "รายละเอียด")}</button> <button class="mini" data-r-ai="${r.id}">${Z("AI 评估", "AI ประเมิน")}</button> ${curOn() ? `<button class="mini" data-r-cur="${r.id}" title="${Z("在模型网站上按这个词建关注巡逻，新模型进「商品 → 选品」的候选池", "สร้างการตระเวนบนเว็บโมเดลด้วยคำนี้ โมเดลใหม่เข้าคลังผู้สมัครใน「สินค้า → คัดเลือกสินค้า」")}">${Z("去模型站找", "ไปหาในเว็บโมเดล")}</button> ` : ""}<button class="mini" data-r-del="${r.id}">${Z("删", "ลบ")}</button></td></tr>`; }),
        Z("还没有关键词：在上面加，或者用浏览器扩展在搜索结果页点「🔭 采集搜索结果」。", "ยังไม่มีคีย์เวิร์ด: เพิ่มด้านบน หรือกด「🔭 เก็บผลการค้นหา」ในหน้าค้นหาด้วยส่วนขยาย"))}
      <p class="small muted">${Z("机会分 = 需求（前 10 名日销、关键词搜索量）+ 竞争少（结果数、前 3 家占比）+ 能打印（AI）+ 利润（到手价中位 − 平台费 − ERP 成本）+ 小爆潜力（AI）；AI 判断有侵权风险（品牌 / 角色 / 外观设计）直接 0 分。权重在「设置 → 运营分析」。",
        "คะแนนโอกาส = ความต้องการ + การแข่งขันน้อย + พิมพ์ได้ (AI) + กำไร (ราคากลาง − ค่าธรรมเนียม − ต้นทุน ERP) + ศักยภาพ (AI) ถ้า AI เห็นว่าเสี่ยงละเมิดลิขสิทธิ์ = 0 คะแนน น้ำหนักตั้งที่「ตั้งค่า → วิเคราะห์การขาย」")}</p>
      ${card(Z("最近巡逻记录", "บันทึกการตระเวนล่าสุด"), tbl([Z("时间", "เวลา"), Z("类型", "ประเภท"), Z("页面", "หน้า"), Z("结果", "ผล"), Z("谁", "ใคร")],
        RAD.log.map((l) => `<tr><td class="small nowrap">${day(l.ts)}</td><td class="small">${esc({ search: Z("搜索页", "หน้าค้นหา"), product: Z("竞品页", "หน้าคู่แข่ง"), shop: Z("店铺页", "หน้าร้าน") }[l.kind] || l.kind)}</td>
          <td class="small oa-url" data-notr>${esc(decodeURIComponent(l.url || "").slice(0, 90))}</td><td class="small ${l.ok ? "ok" : "bad"}" data-notr>${esc(l.note || (l.ok ? "OK" : ""))}</td><td class="small" data-notr>${esc(l.who || "")}</td></tr>`), Z("还没有巡逻过", "ยังไม่เคยตระเวน")))}`;
    if (RDET) radarDetail(RDET);
    box.onclick = radarClick;
    box.onchange = async (e) => {
      const s = e.target.closest("[data-r-st]");
      if (s) { await api(`/api/oa/radar/keywords/${s.dataset.rSt}`, { json: { status: s.value } }); toast(Z("已保存", "บันทึกแล้ว")); }
      const a = e.target.closest("[data-r-act]");
      if (a) { await api(`/api/oa/radar/keywords/${a.dataset.rAct}`, { json: { active: a.checked } }); toast(Z("已保存", "บันทึกแล้ว")); }
    };
  }
  async function radarDetail(id) {
    RDET = id;
    const d = await api(`/api/oa/radar/keywords/${id}`);
    const o = d.opp, a = o.ai || {};
    const b = $("#or-det");
    if (!b) return;
    b.innerHTML = card(`<span data-notr>${esc(d.keyword.keyword)}</span> · ${esc(PLAT(d.keyword.platform))} · ${Z("机会分", "คะแนนโอกาส")} <b>${o.score}</b> <button class="mini" data-r-detclose>${Z("关闭", "ปิด")}</button>`,
      `${o.ip_risk ? `<p class="bad">${Z("侵权风险，不做：", "เสี่ยงละเมิดลิขสิทธิ์ ไม่ทำ: ")}<span data-notr>${esc(a.ip_reason || "")}</span></p>` : ""}
      ${a.summary ? `<p>AI：<span data-notr>${esc(a.summary)}</span></p>` : ""}${a.design_idea ? `<p class="small">${Z("我们的版本：", "เวอร์ชันของเรา: ")}<span data-notr>${esc(a.design_idea)}</span></p>` : ""}
      ${a.printable != null ? `<p class="small">${Z("能打印", "พิมพ์ได้")} ${Math.round(a.printable * 100)}%（<span data-notr>${esc(a.printable_reason || "")}</span>）· ${Z("约", "ประมาณ")} ${a.grams || "?"}g / ${a.hours || "?"}h ${esc(a.material || "")} · ${Z("潜力", "ศักยภาพ")} ${Math.round((a.potential || 0) * 100)}%</p>` : ""}
      <p class="small muted">${esc((Z(o.notes, o.notes_th) || []).join("；"))}${o.volume ? ` · ${Z("后台搜索量", "ปริมาณค้นหา")} ${n1(o.volume, 0)}` : ""}</p>`
      + tbl(["#", Z("商品", "สินค้า"), Z("价格", "ราคา"), Z("已售", "ขายแล้ว"), Z("日销", "ขาย/วัน")], d.items.map((i) => `<tr><td>${i.rank}</td><td><div class="oa-pic">${img(i.image, 36)}${link(i.url, (i.title || "").slice(0, 80))}</div></td>
        <td class="num">${m(i.price)}</td><td class="num" data-notr>${esc(i.sold_text || "—")}</td><td class="num">${n1(i.daily)}</td></tr>`), Z("还没有搜索结果", "ยังไม่มีผลการค้นหา")));
  }
  async function radarClick(e) {
    const t = (s) => e.target.closest(s);
    let b;
    if ((b = t("[data-r-add]"))) {
      const box = b.closest(".card");
      return busy(b, async () => { const r = await api("/api/oa/radar/keywords", { json: { platform: $("[data-r-plat]", box).value, keywords: $("[data-r-kws]", box).value } }); toast(Z(`加了 ${r.added} 个`, `เพิ่ม ${r.added} คำ`)); show("ops_radar"); });
    }
    if ((b = t("[data-r-import]"))) return busy(b, async () => { const r = await api("/api/oa/radar/import", { json: { platform: $("[data-r-plat]").value } }); toast(Z(`导入了 ${r.added} 个`, `นำเข้า ${r.added} คำ`)); show("ops_radar"); });
    if ((b = t("[data-r-report]"))) return busy(b, async () => { const r = await api("/api/oa/radar/report", { json: {} }); toast(r.text ? Z("日报发出去了", "ส่งรายงานแล้ว") : Z("现在没有够分的机会", "ตอนนี้ไม่มีโอกาสที่คะแนนถึง"), !r.text); });
    if (t("[data-r-detclose]")) { RDET = null; $("#or-det").innerHTML = ""; return; }
    if ((b = t("[data-r-det]"))) return radarDetail(+b.dataset.rDet);
    // v2.50：高分关键词 → 选品模块的关注巡逻（每个模型网站一个关键词搜索），然后打开「商品 → 选品 → 关注巡逻」
    if ((b = t("[data-r-cur]"))) return busy(b, async () => {
      const r = await api("/api/cur/from-radar", { json: { kid: +b.dataset.rCur } });
      toast(Z(`已建 ${r.added.length} 个关注（搜索「${r.term}」）`, `สร้างการติดตาม ${r.added.length} รายการ (ค้นหา「${r.term}」)`) + (r.existing ? Z(`，${r.existing} 个已经有了`, ` มีอยู่แล้ว ${r.existing}`) : ""));
      goTab("cur_watch");
    });
    if ((b = t("[data-r-ai]"))) return busy(b, async () => { await apiJob(`/api/oa/radar/keywords/${b.dataset.rAi}/ai`, { json: {} }); RDET = +b.dataset.rAi; show("ops_radar"); });
    if ((b = t("[data-r-del]"))) { if (!confirm(Z("删掉这个关键词和它的搜索记录？", "ลบคีย์เวิร์ดนี้และประวัติ?"))) return; await api(`/api/oa/radar/keywords/${b.dataset.rDel}`, { json: { delete: true } }); return show("ops_radar"); }
  }

  // ======================= 竞店 =======================
  let SHB = null, SDET = null;
  async function shopsPage(box) {
    SHB = await api("/api/oa/shops");
    const bn = SHB.bench;
    const erp = SHB.erp.map((x) => `<tr><td>${esc(PLAT(x.platform))}</td><td data-notr>${esc(x.shop || Z("（没填店铺名）", "(ไม่มีชื่อร้าน)"))}</td><td class="num">${x.orders}</td><td class="num">${x.daily_orders}</td>
      <td class="num">${x.daily_units}</td><td class="num">${m(x.revenue)}</td><td class="num">${x.response_rate != null ? x.response_rate + "%" : "—"}</td><td class="num">${x.positive != null ? n1(x.positive) : "—"}</td></tr>`);
    const gaps = SHB.gaps.map((g) => `<div class="small warn">${Z("我的店铺", "ร้านของเรา")} <span data-notr>${esc(g.shop)}</span>：${esc(Z(g.label, g.label_th))} ${g.mine ?? "—"}${g.unit} · ${Z("竞店中位", "ค่ากลางคู่แข่ง")} ${g.bench}${g.unit}</div>`).join("");
    const rows = SHB.rows.map((r) => { const x = r.m; return `<tr class="${r.watch || r.is_mine ? "" : "muted"}"><td><div class="oa-pic">${img(r.logo, 32)}<div>${link(r.url, r.name || r.shop_key)}
        <div class="small muted">${esc(PLAT(r.platform))}${r.is_mine ? ` · <b>${Z("我的", "ของเรา")}</b>` : ""}${r.comps ? ` · ${r.comps} ${Z("个竞品", "คู่แข่ง")}` : ""}</div></div></div></td>
      <td class="num">${n1(x.followers, 0)}${x.followers_7d != null ? `<div class="small muted">${x.followers_7d >= 0 ? "+" : ""}${x.followers_7d} / 7d</div>` : ""}</td>
      <td class="num">${x.positive_pct != null ? n1(x.positive_pct) + "%" : "—"}${x.rating != null ? `<div class="small muted">★${x.rating}</div>` : ""}</td>
      <td class="num">${x.response_rate != null ? n1(x.response_rate, 0) + "%" : "—"}<div class="small muted" data-notr>${esc(x.response_time || "")}</div></td>
      <td class="num">${x.items_seen}${x.products ? `<div class="small muted">/ ${n1(x.products, 0)}</div>` : ""}</td>
      <td class="num">${n1(x.daily)}${x.daily != null ? `<div class="small muted">${x.daily_n} ${Z("个商品", "สินค้า")}</div>` : ""}</td><td class="num">${x.new_7d ?? "—"}</td>
      <td class="num">${x.price_min != null ? `${m(x.price_min)}–${m(x.price_max)}` : "—"}</td><td class="small nowrap">${day(x.last_ts)}</td>
      <td class="nowrap"><button class="mini" data-s-det="${r.id}">${Z("详情", "รายละเอียด")}</button> ${r.is_mine ? "" : `<button class="mini" data-s-watch="${r.id}" data-w="${r.watch ? 0 : 1}">${r.watch ? Z("不盯了", "เลิกเฝ้า") : Z("盯这家", "เฝ้าร้านนี้")}</button>`}
        <button class="mini" data-s-del="${r.id}">${Z("删", "ลบ")}</button></td></tr>`; });
    box.innerHTML = `${card(Z("我的店铺（ERP 实际数，近 30 天）", "ร้านของเรา (ข้อมูลจริงใน ERP 30 วัน)"), tbl([Z("平台", "แพลตฟอร์ม"), Z("店铺", "ร้าน"), Z("订单", "ออเดอร์"), Z("每天几单", "ออเดอร์/วัน"), Z("每天几件", "ชิ้น/วัน"),
        Z("销售额", "ยอดขาย"), Z("回复率（Lazada 店铺表现）", "อัตราตอบ (Lazada)"), Z("评分 / 好评", "คะแนน")], erp, Z("近 30 天没有平台订单", "30 วันไม่มีออเดอร์จากแพลตฟอร์ม"))
        + `<p class="small muted">${Z("订单按店铺名分开；回复率、评分来自「Lazada 数据 → 店铺表现」。和下面竞店比较时，我的店铺日销用 ERP 的真实件数。", "แยกตามชื่อร้านในออเดอร์ อัตราตอบและคะแนนจาก「ข้อมูล Lazada → ประสิทธิภาพร้าน」")}</p>`)}
      ${card(Z("竞店中位（盯着的竞店）", "ค่ากลางร้านคู่แข่งที่เฝ้า"), `<div class="tiles">${[["followers", Z("粉丝", "ผู้ติดตาม"), ""], ["positive_pct", Z("好评率", "คะแนนเชิงบวก"), "%"], ["response_rate", Z("回复率", "อัตราตอบ"), "%"],
          ["items_seen", Z("在售商品（看得到的）", "สินค้าที่เห็น"), ""], ["daily", Z("店铺日销（下限）", "ขาย/วัน (ขั้นต่ำ)"), ""], ["new_7d", Z("近 7 天上新", "สินค้าใหม่ 7 วัน"), ""]]
          .map(([k, l, u]) => `<div class="tile"><span>${l}</span><b>${bn[k] != null ? n1(bn[k]) + u : "—"}</b></div>`).join("")}
          <div class="tile"><span>${Z("我的店铺每天卖出（ERP）", "ร้านเราขาย/วัน (ERP)")}</span><b>${n1(SHB.erp_daily_units)}</b><small>${Z("件", "ชิ้น")}</small></div></div>
        ${gaps || `<p class="small muted">${SHB.n_watch ? Z("我的店铺没有明显落后的地方", "ร้านเราไม่ได้ตามหลังชัดเจน") : Z("还没有盯着的竞店", "ยังไม่มีร้านคู่แข่งที่เฝ้า")}</p>`}
        ${SHB.mine_set ? "" : `<p class="small warn">${Z("还没填我的店铺前台链接（设置 → 运营分析 → 竞店）：填了以后巡逻也会看自己的店，好评率、回复率、上新可以和竞店放在同一个标准下比较。", "ยังไม่ได้กรอกลิงก์หน้าร้านของเรา (ตั้งค่า → วิเคราะห์การขาย → ร้านคู่แข่ง)")}</p>`}`)}
      <div class="row gap wrap" style="margin:6px 0"><input data-s-url style="flex:1;min-width:240px" placeholder="${Z("竞店首页链接，例如 https://www.lazada.co.th/shop/xxx", "ลิงก์หน้าร้านคู่แข่ง เช่น https://www.lazada.co.th/shop/xxx")}"><button data-s-add>${Z("盯这家店", "เฝ้าร้านนี้")}</button></div>
      <div id="os-det"></div>
      ${tbl([Z("店铺", "ร้าน"), Z("粉丝", "ผู้ติดตาม"), Z("好评率", "คะแนนเชิงบวก"), Z("回复率", "อัตราตอบ"), Z("在售", "สินค้า"), Z("日销（下限）", "ขาย/วัน (ขั้นต่ำ)"), Z("7 天上新", "ใหม่ 7 วัน"), Z("价格带", "ช่วงราคา"), Z("更新于", "อัปเดต"), ""], rows,
        Z("还没有店铺：上面贴链接，或者用浏览器扩展在店铺页点「🏪 采集店铺」。采竞品时会把它的店铺放进来（灰色 = 候选，点「盯这家」才巡逻）。", "ยังไม่มีร้าน: วางลิงก์ด้านบน หรือกด「🏪 เก็บข้อมูลร้าน」ในหน้าร้านด้วยส่วนขยาย"))}
      <p class="small muted">${Z("店铺日销（下限）= 店铺页上看得到的商品两次「累计已售」相减 ÷ 天数加起来；看不到的商品不算，所以是下限。Lazada 店铺要「店铺资料」和「全部商品」两页都采一次。",
        "ขาย/วัน (ขั้นต่ำ) = ผลรวมของผลต่างยอดขายสะสมของสินค้าที่เห็นในหน้าร้าน ÷ จำนวนวัน สินค้าที่มองไม่เห็นไม่นับ จึงเป็นค่าขั้นต่ำ")}</p>${extHint()}`;
    if (SDET) shopDetail(SDET);
    box.onclick = shopsClick;
  }
  async function shopDetail(id) {
    SDET = id;
    const d = await api(`/api/oa/shops/${id}`);
    const b = $("#os-det");
    if (!b) return;
    const x = d.m;
    const it = (arr) => tbl([Z("商品", "สินค้า"), Z("价格", "ราคา"), Z("已售", "ขายแล้ว"), Z("日销", "ขาย/วัน")], arr.map((i) => `<tr><td><div class="oa-pic">${img(i.image, 32)}${link(i.url, (i.title || i.item_key).slice(0, 70))}</div></td>
      <td class="num">${m(i.price)}</td><td class="num" data-notr>${esc(i.sold_text || "—")}</td><td class="num">${n1(i.daily)}</td></tr>`));
    b.innerHTML = card(`${img(d.shop.logo, 36)} <span data-notr>${esc(d.shop.name || d.shop.shop_key)}</span> <button class="mini" data-s-detclose>${Z("关闭", "ปิด")}</button>`,
      `<p class="small">${Z("开店", "เปิดร้าน")} <span data-notr>${esc(x.joined_text || "—")}</span> · ${Z("主营", "หมวดหลัก")} <span data-notr>${esc(x.main_category || "—")}</span> · ${Z("前 3 个商品占销量", "3 สินค้าแรกมีส่วนแบ่ง")} ${x.top3_share != null ? Math.round(x.top3_share * 100) + "%" : "—"}
        · ${Z("30 天销售额（推算）", "ยอดขาย 30 วัน (ประมาณ)")} ${m(x.rev_30d)}</p>
      <div class="row gap"><input data-s-note value="${esc(d.shop.note || "")}" placeholder="${Z("备注", "หมายเหตุ")}" style="flex:1"><button class="mini" data-s-savenote="${id}">${Z("保存备注", "บันทึกหมายเหตุ")}</button></div>
      <h4>${Z("卖得最好的", "ขายดีที่สุด")}</h4>${it(x.top)}${x.hot_new.length ? `<h4>${Z("新品起量（14 天内新出现、日销 ≥ 1）", "สินค้าใหม่เริ่มขายดี (ใหม่ใน 14 วัน ขาย ≥ 1/วัน)")}</h4>${it(x.hot_new)}` : ""}
      <h4>${Z("店铺数据记录", "ประวัติข้อมูลร้าน")}</h4>` + tbl([Z("时间", "เวลา"), Z("粉丝", "ผู้ติดตาม"), Z("好评率", "คะแนนเชิงบวก"), Z("回复率", "อัตราตอบ"), Z("商品数", "สินค้า")],
        d.snaps.map((s) => `<tr><td class="small">${day(s.ts)}</td><td class="num">${n1(s.followers, 0)}</td><td class="num">${s.positive_pct ?? "—"}</td><td class="num">${s.response_rate ?? "—"}</td><td class="num">${n1(s.products, 0)}</td></tr>`))
      + `<h4>${Z("全部商品", "สินค้าทั้งหมด")}（${d.items.length}）</h4>${it(d.items.slice(0, 100))}`);
  }
  async function shopsClick(e) {
    const t = (s) => e.target.closest(s);
    let b;
    if ((b = t("[data-s-add]"))) return busy(b, async () => { await api("/api/oa/shops", { json: { url: $("[data-s-url]").value } }); toast(Z("已加入，巡逻时会看", "เพิ่มแล้ว จะตระเวนดู")); show("ops_shops"); });
    if (t("[data-s-detclose]")) { SDET = null; $("#os-det").innerHTML = ""; return; }
    if ((b = t("[data-s-det]"))) return shopDetail(+b.dataset.sDet);
    if ((b = t("[data-s-watch]"))) return busy(b, async () => { await api(`/api/oa/shops/${b.dataset.sWatch}`, { json: { watch: b.dataset.w === "1" } }); show("ops_shops"); });
    if ((b = t("[data-s-savenote]"))) return busy(b, async () => { await api(`/api/oa/shops/${b.dataset.sSavenote}`, { json: { note: $("[data-s-note]").value } }); toast(Z("已保存", "บันทึกแล้ว")); });
    if ((b = t("[data-s-del]"))) { if (!confirm(Z("删掉这家店和它的全部记录？", "ลบร้านนี้และข้อมูลทั้งหมด?"))) return; await api(`/api/oa/shops/${b.dataset.sDel}`, { json: { delete: true } }); SDET = null; return show("ops_shops"); }
  }

  window.OPSB = Object.assign(window.OPSB || {}, { market: { tabs: Object.keys(BOX), show } });
})();
