"use strict";
// v2.54 生产 → 打印机：机群总览（数字卡片 → 机群地图 → 列表）+ 右边抽屉（状态、基本信息、按厂家的连接设置、测试 / 打印测试 /
// 网络诊断、单独设置、保养、记录）。添加：单台（先选机型 / 厂家）、🔍 局域网发现、📥 Excel / CSV 导入；🏷 二维码标签。
// 几千台也快：列表分页（服务器算好）、地图每台一个小色块。写操作只有老板能做（服务器也会核对）。
(function () {
  const Z = (zh, th) => (window.I18N && I18N.lang === "th" ? th : zh);
  const LANG = () => (window.I18N && I18N.lang === "th" ? "th" : "zh");
  const U = (u) => u + (u.includes("?") ? "&" : "?") + "lang=" + LANG();
  const own = () => window.OPSH && OPSH.isOwner();
  const SG = () => ({ printing: [Z("打印中", "กำลังพิมพ์"), "ok"], idle: [Z("空闲", "ว่าง"), "info"], error: [Z("出错", "ผิดพลาด"), "bad"],
    offline: [Z("连不上", "เชื่อมต่อไม่ได้"), "warn"], none: [Z("未连接", "ไม่ได้เชื่อมต่อ"), ""] });
  const ROLE = () => ({ any: Z("都可以", "ทั้งหมด"), orders: Z("只打订单", "เฉพาะออเดอร์"), stock: Z("只打备货", "เฉพาะสต็อก") });
  const FIELD = () => ({ nozzle: Z("喷嘴 mm", "หัวฉีด มม."), plate: Z("热床板", "แผ่นฐาน"), g_per_h: Z("每小时克数", "กรัมต่อชั่วโมง"),
    ams: Z("AMS / 多色", "AMS / หลายสี"), orca_machine: Z("Orca 打印机配置", "โปรไฟล์เครื่อง Orca"), orca_process: Z("Orca 工艺配置", "โปรไฟล์กระบวนการ Orca"),
    orca_filament: Z("Orca 耗材配置", "โปรไฟล์เส้นพลาสติก Orca") });
  const PLATES = () => [["", Z("不核对", "ไม่ตรวจ")], ["Textured PEI Plate", Z("纹理 PEI 板", "แผ่น PEI ผิวหยาบ")], ["Smooth PEI Plate", Z("光面 PEI 板", "แผ่น PEI ผิวเรียบ")],
    ["Cool Plate", Z("低温板", "แผ่นอุณหภูมิต่ำ")], ["Engineering Plate", Z("工程板", "แผ่นวิศวกรรม")], ["High Temp Plate", Z("高温板", "แผ่นอุณหภูมิสูง")], ["SuperTack Plate", Z("超粘板", "แผ่นยึดติดสูง")]];
  const STATES = () => ({ idle: Z("空闲", "ว่าง"), printing: Z("打印中", "กำลังพิมพ์"), paused: Z("已暂停", "หยุดชั่วคราว"), finished: Z("打印完成", "พิมพ์เสร็จ"),
    failed: Z("失败/已取消", "ล้มเหลว/ยกเลิก"), offline: Z("连不上", "เชื่อมต่อไม่ได้"), unknown: Z("未知", "ไม่ทราบ"), none: Z("未连接", "ไม่ได้เชื่อมต่อ") });
  let META = null, DATA = null, TIMER = null, OPEN = null, DET = null, PO = undefined;
  const Q = { status: "", model: "", group: "*", role: "", q: "", page: 1, per: 50, sort: "group" };
  const SEL = new Set();
  try { Object.assign(Q, JSON.parse(localStorage.getItem("fleet_q") || "{}"), { page: 1 }); } catch { /* 忽略 */ }
  const root = () => document.getElementById("fleet-root");

  async function meta() { if (!META) META = await api("/api/fleet/meta"); return META; }
  async function prodOrders() {      // 生产单（另一个功能做好以后才有）：有就给下拉，没有就填编号
    if (PO !== undefined) return PO;
    try { const r = await api("/api/porders?status=active"); PO = (r.orders || []).filter((o) => o && o.id != null); } catch { PO = null; }
    return PO;
  }

  // ---------------- 页面 ----------------
  function show() {
    clearInterval(TIMER);
    const u = new URLSearchParams(location.search);
    const want = u.get("printer");
    load().then(() => { if (want) { history.replaceState(history.state, "", location.pathname + location.hash); openDrawer(want); } }).catch((e) => toast(e.message, true));
    TIMER = setInterval(() => { if (!document.hidden && $("#tab-printers") && !$("#tab-printers").classList.contains("hidden")) load(true).catch(() => {}); }, 10000);
  }
  function qs() {
    const p = new URLSearchParams();
    for (const k of ["status", "model", "role", "q", "page", "per", "sort"]) if (Q[k]) p.set(k, Q[k]);
    if (Q.group !== "*") p.set("group", Q.group);
    return p.toString();
  }
  async function load(quiet) {
    if (quiet && document.activeElement && document.activeElement.closest && document.activeElement.closest("#fleet-root .fl-filters, #fl-drawer")) return;
    try { localStorage.setItem("fleet_q", JSON.stringify(Q)); } catch { /* 忽略 */ }
    await meta();
    DATA = await api("/api/fleet?" + qs());
    render();
    if (OPEN && quiet && DET && !document.querySelector("#fl-drawer :focus")) refreshDrawer().catch(() => {});
  }

  function kpis(k) {
    const pct = (x) => (x == null ? "—" : Math.round(x * 100) + "%");
    return UX.kpis([
      { label: Z("打印机", "เครื่องพิมพ์"), value: k.total, sub: Z(`启用 ${k.enabled} 台`, `เปิดใช้ ${k.enabled} เครื่อง`), go: "fl:" },
      { label: Z("在线", "ออนไลน์"), value: k.online, tone: k.online ? "ok" : "", go: "fl:online" },
      { label: Z("打印中", "กำลังพิมพ์"), value: k.printing, tone: "ok", go: "fl:printing" },
      { label: Z("空闲", "ว่าง"), value: k.idle, tone: "info", go: "fl:idle" },
      { label: Z("出错", "ผิดพลาด"), value: k.error, tone: k.error ? "bad" : "", go: "fl:error" },
      { label: Z("连不上", "เชื่อมต่อไม่ได้"), value: k.offline, tone: k.offline ? "warn" : "", go: "fl:offline", sub: k.none ? Z(`没设置连接 ${k.none} 台`, `ยังไม่ตั้งค่าการเชื่อมต่อ ${k.none} เครื่อง`) : "" },
      { label: Z("该保养", "ถึงเวลาบำรุงรักษา"), value: k.maint, tone: k.maint ? "warn" : "", go: "fl:maint", sub: k.paused ? Z(`暂停接单 ${k.paused} 台`, `หยุดรับงาน ${k.paused} เครื่อง`) : "" },
      { label: Z("今天利用率", "อัตราการใช้งานวันนี้"), value: pct(k.util_today), sub: Z(`今天打好 ${k.made_today} 件`, `วันนี้พิมพ์เสร็จ ${k.made_today} ชิ้น`),
        help: Z("今天打印的时间 ÷（启用的打印机台数 × 今天过去的小时数）", "เวลาพิมพ์วันนี้ ÷ (จำนวนเครื่องที่เปิดใช้ × ชั่วโมงที่ผ่านไปวันนี้)") },
    ]);
  }

  function mapHtml(tiles) {
    if (!tiles.length) return UX.empty(Z("没有符合条件的打印机", "ไม่มีเครื่องพิมพ์ที่ตรงเงื่อนไข"));
    const groups = {};
    tiles.forEach((t) => (groups[t.g] = groups[t.g] || []).push(t));
    const sg = SG();
    const legend = Object.entries(sg).map(([k, v]) => `<span class="fl-lg"><i class="fl-t fl-${k}"></i>${esc(v[0])}</span>`).join("") +
      `<span class="fl-lg"><i class="fl-t fl-idle fl-pz"></i>${esc(Z("暂停接单", "หยุดรับงาน"))}</span><span class="fl-lg"><i class="fl-t fl-idle fl-mt"></i>${esc(Z("该保养", "ถึงเวลาบำรุงรักษา"))}</span>`;
    return `<div class="fl-legend small">${legend}</div>` + Object.keys(groups).sort().map((g) => `<div class="fl-grp">
      <div class="fl-grp-h small"><b data-notr>${esc(g || Z("未分组", "ไม่มีกลุ่ม"))}</b> <span class="muted">${groups[g].length}</span></div>
      <div class="fl-tiles">${groups[g].map((t) => `<i class="fl-t fl-${t.sg}${t.p ? " fl-pz" : ""}${t.m ? " fl-mt" : ""}${t.en ? "" : " fl-off"}" data-flopen="${esc(t.id)}"
        title="${esc(t.code)}${t.loc ? " · " + esc(t.loc) : ""} · ${esc((sg[t.sg] || [""])[0])}${t.pr != null ? " " + t.pr + "%" : ""}" data-notr></i>`).join("")}</div></div>`).join("");
  }

  function filters() {
    const m = DATA.models || {}, g = DATA.groups || {};
    const sg = SG();
    const opt = (v, t, cur) => `<option value="${esc(v)}" ${String(v) === String(cur) ? "selected" : ""}>${esc(t)}</option>`;
    return `<div class="fl-filters row gap wrap">
      <select data-flq="status">${opt("", Z("全部状态", "ทุกสถานะ"), Q.status)}${Object.entries(sg).map(([k, v]) => opt(k, v[0], Q.status)).join("")}
        ${opt("online", Z("在线（打印中 + 空闲）", "ออนไลน์ (พิมพ์ + ว่าง)"), Q.status)}${opt("maint", Z("该保养", "ถึงเวลาบำรุงรักษา"), Q.status)}${opt("paused", Z("暂停接单", "หยุดรับงาน"), Q.status)}${opt("disabled", Z("停用", "ปิดใช้"), Q.status)}</select>
      <select data-flq="model" data-notr>${opt("", Z("全部机型", "ทุกรุ่น"), Q.model)}${Object.keys(m).sort().map((k) => opt(k, `${k} (${m[k]})`, Q.model)).join("")}</select>
      <select data-flq="group" data-notr>${opt("*", Z("全部分组", "ทุกกลุ่ม"), Q.group)}${Object.keys(g).sort().map((k) => opt(k, `${k || Z("未分组", "ไม่มีกลุ่ม")} (${g[k].n})`, Q.group)).join("")}</select>
      <select data-flq="role">${opt("", Z("全部用途", "ทุกการใช้งาน"), Q.role)}${Object.entries(ROLE()).map(([k, v]) => opt(k, v, Q.role)).join("")}</select>
      <input data-flq="q" value="${esc(Q.q)}" placeholder="${esc(Z("搜编码 / IP / 序列号", "ค้นหารหัส / IP / ซีเรียล"))}" style="width:180px">
      <select data-flq="sort">${opt("group", Z("按分组 / 位置", "ตามกลุ่ม / ตำแหน่ง"), Q.sort)}${opt("code", Z("按编码", "ตามรหัส"), Q.sort)}${opt("state", Z("按状态", "ตามสถานะ"), Q.sort)}${opt("util", Z("按利用率", "ตามอัตราการใช้งาน"), Q.sort)}</select></div>`;
  }

  function bulkBar() {
    if (!own()) return "";
    const n = SEL.size;
    const groupSel = Q.group !== "*";
    return `<div class="fl-bulk row gap wrap small ${n || groupSel ? "" : "muted"}">
      <span>${n ? Z(`已选 ${n} 台`, `เลือกแล้ว ${n} เครื่อง`) : groupSel ? Z("没勾选时：对整个分组操作", "ถ้าไม่เลือก: ทำกับทั้งกลุ่ม") : Z("勾选打印机后可以批量操作", "เลือกเครื่องพิมพ์แล้วทำหลายเครื่องพร้อมกันได้")}</span>
      <select id="fl-bact" ${n || groupSel ? "" : "disabled"}><option value="">${esc(Z("批量操作…", "ทำหลายเครื่อง…"))}</option>
        <option value="test">${esc(Z("测试连接", "ทดสอบการเชื่อมต่อ"))}</option><option value="enable">${esc(Z("启用", "เปิดใช้"))}</option><option value="disable">${esc(Z("停用", "ปิดใช้"))}</option>
        <option value="pause">${esc(Z("暂停接单（保养）", "หยุดรับงาน (บำรุงรักษา)"))}</option><option value="resume">${esc(Z("恢复接单", "รับงานต่อ"))}</option>
        <option value="role">${esc(Z("设用途…", "ตั้งการใช้งาน…"))}</option><option value="group">${esc(Z("设分组…", "ตั้งกลุ่ม…"))}</option><option value="location">${esc(Z("设位置…", "ตั้งตำแหน่ง…"))}</option>
        <option value="nozzle">${esc(Z("单独设喷嘴…", "ตั้งหัวฉีดเฉพาะเครื่อง…"))}</option><option value="plate">${esc(Z("单独设热床板…", "ตั้งแผ่นฐานเฉพาะเครื่อง…"))}</option>
        <option value="dedicate">${esc(Z("专门打某个生产单…", "ใช้พิมพ์ใบสั่งผลิตเดียว…"))}</option><option value="labels">${esc(Z("打印二维码标签", "พิมพ์ป้าย QR"))}</option>
        <option value="remove">${esc(Z("移除", "นำออก"))}</option></select>
      ${n ? `<a href="#" data-flclr>${esc(Z("取消勾选", "ยกเลิกที่เลือก"))}</a>` : ""}</div>`;
  }

  function stateChip(r) {
    const sg = SG()[r.sg] || ["", ""];
    const t = STATES()[r.state] || sg[0];
    return `${UX.dot(sg[1], t)}${r.paused ? ` <span class="pill">${esc(Z("暂停接单", "หยุดรับงาน"))}</span>` : ""}${r.enabled ? "" : ` <span class="pill">${esc(Z("停用", "ปิดใช้"))}</span>`}`;
  }
  function rowHtml(r) {
    const job = r.run ? `<span class="mono" data-notr>${esc(r.run.sku)}</span> × ${r.run.count}` : r.file && r.sg === "printing" ? `<span class="small" data-notr>${esc(r.file)}</span>` : "";
    const prog = r.sg === "printing" && r.progress != null ? `<div class="bar fl-bar"><div style="width:${Number(r.progress) || 0}%"></div></div><span class="small">${r.progress}%${r.remaining_min ? ` · ${Z("剩", "เหลือ")} ${Math.floor(r.remaining_min / 60)}h${r.remaining_min % 60}m` : ""}</span>` : "";
    return `<tr data-flopen="${esc(r.id)}" class="${SEL.has(r.id) ? "sel" : ""}">
      ${own() ? `<td><input type="checkbox" data-flsel="${esc(r.id)}" ${SEL.has(r.id) ? "checked" : ""}></td>` : ""}
      <td><b class="pcode" data-notr>${esc(r.code)}</b>${r.maint_due.length ? ` <span class="pill bad-pill" title="${esc(Z("该保养了", "ถึงเวลาบำรุงรักษา"))}">🔧</span>` : ""}${r.ovr.length ? ` <span class="pill" title="${esc(Z("有单独设置", "มีค่าเฉพาะเครื่อง"))}">✱</span>` : ""}</td>
      <td data-notr>${esc(r.name)}</td>
      <td data-notr>${esc(r.group)}${r.location ? ` <span class="muted">· ${esc(r.location)}</span>` : ""}${r.role !== "any" ? ` <span class="pill">${esc(ROLE()[r.role])}</span>` : ""}</td>
      <td>${stateChip(r)}${r.error ? `<div class="small bad" data-notr>${esc(r.error)}</div>` : ""}</td>
      <td>${job}${prog}</td>
      <td class="mono small" data-notr>${esc(r.host)}</td>
      <td class="num">${r.made_today || ""}</td>
      <td class="num">${r.util_today ? Math.round(r.util_today * 100) + "%" : ""}</td></tr>`;
  }
  function tableHtml() {
    const rows = DATA.rows || [];
    const pages = Math.max(1, Math.ceil(DATA.total / DATA.per));
    const allOn = rows.length && rows.every((r) => SEL.has(r.id));
    return `<div class="tbl-scroll"><table class="grid fl-table"><thead><tr>${own() ? `<th><input type="checkbox" data-flall ${allOn ? "checked" : ""}></th>` : ""}
      <th>${esc(Z("编码", "รหัส"))}</th><th>${esc(Z("机型", "รุ่น"))}</th><th>${esc(Z("分组 / 位置", "กลุ่ม / ตำแหน่ง"))}</th><th>${esc(Z("状态", "สถานะ"))}</th>
      <th>${esc(Z("当前任务", "งานปัจจุบัน"))}</th><th>IP</th><th>${esc(Z("今天打好", "วันนี้เสร็จ"))}</th><th>${esc(Z("利用率", "การใช้งาน"))}</th></tr></thead>
      <tbody>${rows.map(rowHtml).join("") || `<tr><td colspan="9">${UX.empty(Z("没有符合条件的打印机", "ไม่มีเครื่องพิมพ์ที่ตรงเงื่อนไข"))}</td></tr>`}</tbody></table></div>
      <div class="row gap small fl-pager"><button class="mini" data-flpg="-1" ${Q.page <= 1 ? "disabled" : ""}>‹</button>
        <span>${Z(`第 ${DATA.page} / ${pages} 页 · 共 ${DATA.total} 台`, `หน้า ${DATA.page} / ${pages} · ทั้งหมด ${DATA.total} เครื่อง`)}</span>
        <button class="mini" data-flpg="1" ${Q.page >= pages ? "disabled" : ""}>›</button>
        <select data-flq="per">${[25, 50, 100, 200].map((n) => `<option value="${n}" ${+Q.per === n ? "selected" : ""}>${Z(`每页 ${n}`, `หน้าละ ${n}`)}</option>`).join("")}</select></div>`;
  }

  function render() {
    const el = root();
    if (!el || !DATA) return;
    const btns = own() ? `<button class="primary" data-fladd>＋ ${esc(Z("添加", "เพิ่ม"))}</button><button data-fldisc>🔍 ${esc(Z("局域网发现", "ค้นหาในเครือข่าย"))}</button>
      <button data-flimp>📥 ${esc(Z("导入 Excel / CSV", "นำเข้า Excel / CSV"))}</button>` : "";
    el.innerHTML = UX.head(Z("打印机", "เครื่องพิมพ์"), `${btns}<a class="btn" target="_blank" href="/print/fleet-labels?lang=${LANG()}${Q.group !== "*" ? "&group=" + encodeURIComponent(Q.group) : ""}">🏷 ${esc(Z("二维码标签", "ป้าย QR"))}</a><button data-flreload>${esc(Z("刷新", "รีเฟรช"))}</button>`,
      Z("每台打印机一行；点一行打开右边的详情：连接设置、测试连接、打印测试、网络诊断、保养、打印记录、这台的单独设置。喷嘴、热床板、OrcaSlicer 配置、每小时克数在 系统 → 设置 → 生产 →「机型模板」里按机型设置，这里只改和模板不一样的地方。",
        "เครื่องละหนึ่งแถว กดที่แถวเพื่อเปิดรายละเอียดด้านขวา: ตั้งค่าการเชื่อมต่อ ทดสอบการเชื่อมต่อ ทดสอบพิมพ์ วินิจฉัยเครือข่าย บำรุงรักษา ประวัติการพิมพ์ ค่าเฉพาะเครื่อง หัวฉีด แผ่นฐาน โปรไฟล์ OrcaSlicer และกรัมต่อชั่วโมง ตั้งตามรุ่นที่ ระบบ → ตั้งค่า → การผลิต → «แม่แบบรุ่น» ที่นี่แก้เฉพาะส่วนที่ต่างจากแม่แบบ")) +
      kpis(DATA.kpis) +
      UX.card({ title: Z("机群地图", "แผนผังเครื่องพิมพ์"), help: Z("按分组排，每台一个小方块（颜色 = 状态）。点方块打开详情。", "เรียงตามกลุ่ม เครื่องละหนึ่งช่อง (สี = สถานะ) กดที่ช่องเพื่อเปิดรายละเอียด"), body: mapHtml(DATA.tiles || []) }) +
      UX.card({ title: Z("打印机列表", "รายการเครื่องพิมพ์"), body: filters() + bulkBar() + tableHtml() });
  }

  // ---------------- 抽屉 ----------------
  function drawerEl() {
    let d = document.getElementById("fl-drawer");
    if (!d) {
      d = document.createElement("div");
      d.id = "fl-drawer"; d.className = "drawer hidden";
      d.innerHTML = '<div class="drawer-in fl-din"></div>';
      document.body.appendChild(d);
      d.addEventListener("click", (e) => { if (e.target === d) closeDrawer(); });
      d.addEventListener("click", onDrawerClick);
      d.addEventListener("change", onDrawerChange);
      if (window.NAV && NAV.overlay) try { NAV.overlay(d, { close: closeDrawer }); } catch { /* 旧版本 */ }
    }
    return d;
  }
  function closeDrawer() { OPEN = null; DET = null; const d = document.getElementById("fl-drawer"); if (d) d.classList.add("hidden"); }
  async function openDrawer(key) {
    OPEN = key;
    const d = drawerEl();
    d.classList.remove("hidden");
    d.querySelector(".fl-din").innerHTML = `<p class="muted">${esc(Z("读取中…", "กำลังโหลด…"))}</p>`;
    try { await refreshDrawer(); } catch (e) { toast(e.message, true); closeDrawer(); }
  }
  async function refreshDrawer() {
    if (!OPEN) return;
    await meta();
    DET = await api("/api/fleet/printers/" + encodeURIComponent(OPEN));
    OPEN = DET.printer.id;
    if (own() && DET.printer.dedicated_po !== undefined) await prodOrders();
    drawerEl().querySelector(".fl-din").innerHTML = drawerHtml(DET);
  }
  function vendorForm(vend, c, v) {
    const V = META.vendors[vend] || META.vendors.none;
    const f = V.fields.map((x) => `<label>${esc(Z(x.zh, x.th))}${x.req ? " *" : ""}<input data-flc="${x.key}" value="${esc(x.kind === "secret" ? (c.access_code ? "******" : "") : c[x.key] || "")}"
      placeholder="${esc(x.ph || "")}" ${x.kind === "secret" ? 'type="password" autocomplete="new-password"' : ""} data-notr></label>`).join("");
    return `<div class="form2">${f}${vend !== "none" ? `<label class="row" style="align-self:end"><input type="checkbox" data-flc="auto_complete" ${c.auto_complete === false ? "" : "checked"}> ${esc(Z("打印机报告完成时自动记录", "บันทึกอัตโนมัติเมื่อเครื่องแจ้งว่าเสร็จ"))}</label>` : ""}</div>
      <p class="small muted">${esc(Z(V.hint_zh, V.hint_th))}</p>`;
  }
  function fieldVal(k, v) {
    if (v == null || v === "") return Z("机型默认", "ค่าเริ่มต้นของรุ่น");
    if (k === "ams") return v ? Z("有", "มี") : Z("没有", "ไม่มี");
    if (k === "plate") return (PLATES().find((p) => p[0] === v) || [v, v])[1];
    return String(v);
  }
  function ovrInput(f) {
    const k = f.key, o = f.override;
    if (k === "plate") return `<select data-flo="plate"><option value="">${esc(Z("跟随模板", "ตามแม่แบบ"))}</option>${PLATES().slice(1).map(([v, l]) => `<option value="${esc(v)}" ${o === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    if (k === "ams") return `<select data-flo="ams"><option value="">${esc(Z("跟随模板", "ตามแม่แบบ"))}</option><option value="true" ${o === true ? "selected" : ""}>${esc(Z("有", "มี"))}</option><option value="false" ${o === false ? "selected" : ""}>${esc(Z("没有", "ไม่มี"))}</option></select>`;
    return `<input data-flo="${k}" value="${esc(o == null ? "" : o)}" placeholder="${esc(Z("跟随模板", "ตามแม่แบบ"))}" data-notr>`;
  }
  function drawerHtml(D) {
    const p = D.printer, r = D.row, st = D.status || {}, c = p.conn || {}, ow = D.owner, h = OPSH;
    const vend = D.vendor;
    const models = META.models || [];
    const po = PO;
    const sec = (title, body, open = true) => `<details class="fl-sec" ${open ? "open" : ""}><summary><b>${esc(title)}</b></summary>${body}</details>`;
    const dis = ow ? "" : "disabled";
    const prog = st.state === "printing" || st.state === "paused";
    const statusB = `<div class="row gap wrap">${stateChip(r)}${r.maint_due.length ? ` <span class="pill bad-pill">${esc(Z("该保养了", "ถึงเวลาบำรุงรักษา"))}</span>` : ""}</div>
      ${prog ? `<div class="bar"><div style="width:${Number(st.progress) || 0}%"></div></div>` : ""}
      <div class="small">${st.file ? `${esc(Z("文件", "ไฟล์"))}：<span data-notr>${esc(st.file)}</span><br>` : ""}
        ${st.layer != null && st.total_layers ? `${esc(Z("层", "ชั้น"))} ${st.layer}/${st.total_layers} · ` : ""}
        ${st.nozzle != null ? `${esc(Z("喷头", "หัวฉีด"))} ${h.num(st.nozzle, 0)}°C · ${esc(Z("热床", "ฐานความร้อน"))} ${h.num(st.bed, 0)}°C` : ""}
        ${st.error ? `<div class="bad" data-notr>${esc(st.error)}</div>` : ""}</div>
      ${r.run ? `<div class="small">${esc(Z("这一盘", "เพลทนี้"))}：<b class="mono" data-notr data-p360="${esc(r.run.sku)}">${esc(r.run.sku)}</b> ${h.colorTxt(r.run.color)} × ${r.run.count}</div>` : ""}
      ${h.trayHtml(st)}
      <label class="small">${esc(Z("现在装的料（没有料盘读数时填，例如：白色,黑色）", "วัสดุที่ใส่อยู่ (กรอกเมื่อไม่มีข้อมูลจากถาด เช่น ขาว,ดำ)"))}
        <span class="row gap"><input data-flloaded value="${esc(c.loaded || "")}" list="color-list" data-notr><button class="mini" data-flsaveloaded>${esc(Z("保存", "บันทึก"))}</button></span></label>
      ${(c.type || "none") !== "none" ? `<div class="row gap wrap">${st.state === "printing" ? `<button data-flcmd="pause">⏸ ${esc(Z("暂停", "หยุดชั่วคราว"))}</button>` : ""}
        ${st.state === "paused" ? `<button data-flcmd="resume">▶ ${esc(Z("继续", "พิมพ์ต่อ"))}</button>` : ""}${prog ? `<button class="danger" data-flcmd="stop">⏹ ${esc(Z("取消打印", "ยกเลิกการพิมพ์"))}</button>` : ""}</div>` : ""}`;
    const basic = `<div class="form2">
      <label>${esc(Z("机器编码", "รหัสเครื่อง"))}<input data-flb="code" value="${esc(p.code || "")}" ${dis} data-notr></label>
      <label>${esc(Z("机型", "รุ่น"))}<select data-flb="name" ${dis} data-notr>${models.map((m) => `<option value="${esc(m.name)}" ${m.name === p.name ? "selected" : ""}>${esc(m.name)}</option>`).join("")}${models.some((m) => m.name === p.name) ? "" : `<option selected>${esc(p.name)}</option>`}</select></label>
      <label>${esc(Z("分组", "กลุ่ม"))}<input data-flb="group" value="${esc(p.group || "")}" list="fl-groups" placeholder="${esc(Z("例如 A 区", "เช่น โซน A"))}" ${dis} data-notr></label>
      <label>${esc(Z("位置（货架-层-位）", "ตำแหน่ง (ชั้นวาง-ชั้น-ช่อง)"))}<input data-flb="location" value="${esc(p.location || "")}" placeholder="A-03-2" ${dis} data-notr></label>
      <label>${esc(Z("用途", "การใช้งาน"))}<select data-flb="role" ${dis}>${Object.entries(ROLE()).map(([k, v]) => `<option value="${k}" ${k === p.role ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
      <label>${esc(Z("专门打的生产单", "ใช้พิมพ์ใบสั่งผลิต"))}${po && po.length ? `<select data-flb="dedicated_po" ${dis} data-notr><option value="">${esc(Z("不指定", "ไม่ระบุ"))}</option>${po.map((o) => `<option value="${esc(o.id)}" ${String(o.id) === String(p.dedicated_po) ? "selected" : ""}>${esc(o.code || o.no || o.id)} ${esc(o.name || o.title || "")}</option>`).join("")}</select>`
        : `<input data-flb="dedicated_po" value="${esc(p.dedicated_po || "")}" placeholder="${esc(Z("生产单号（空 = 不指定）", "เลขใบสั่งผลิต (ว่าง = ไม่ระบุ)"))}" ${dis} data-notr>`}</label>
      <label class="row"><input type="checkbox" data-flb="enabled" ${p.enabled === false ? "" : "checked"} ${dis}> ${esc(Z("启用（参与排单）", "เปิดใช้ (รับงานจากระบบจัดคิว)"))}</label>
      <label class="row"><input type="checkbox" data-flb="paused" ${p.paused ? "checked" : ""} ${dis}> ${esc(Z("暂停接单（保养中）", "หยุดรับงาน (กำลังบำรุงรักษา)"))}</label>
      <label>${esc(Z("备注", "หมายเหตุ"))}<input data-flb="note" value="${esc(p.note || "")}" ${dis} data-notr></label></div>
      <datalist id="fl-groups">${(META.groups || []).map((g) => `<option value="${esc(g)}">`).join("")}</datalist>
      ${ow ? `<div class="row gap"><button class="primary mini" data-flsavebasic>${esc(Z("保存", "บันทึก"))}</button></div>` : ""}`;
    const vopts = (D.vendors || []).map((k) => `<option value="${k}" ${k === vend ? "selected" : ""}>${esc(Z(META.vendors[k].zh, META.vendors[k].th))}</option>`).join("");
    const conn = ow ? `<label>${esc(Z("厂家 / 连接方式", "ยี่ห้อ / การเชื่อมต่อ"))}<select data-flvendor>${vopts}</select></label>
      <div data-flvform>${vendorForm(vend, c)}</div>
      <div class="row gap wrap"><button class="primary mini" data-flsaveconn>${esc(Z("保存连接", "บันทึกการเชื่อมต่อ"))}</button><button class="mini" data-fltest>${esc(Z("测试连接", "ทดสอบการเชื่อมต่อ"))}</button>
        ${window.TRIAL && TRIAL.can() ? `<button class="mini" data-tr-ptest="${r.index}">🧪 ${esc(Z("打印测试", "ทดสอบพิมพ์"))}</button>` : ""}
        <button class="mini" data-fldiag>${esc(Z("网络诊断", "วินิจฉัยเครือข่าย"))}</button></div><div data-fltestres></div>`
      : `<p class="small">${esc(Z(META.vendors[vend].zh, META.vendors[vend].th))} · <span class="mono" data-notr>${esc(c.host || "")}</span></p>
         <div class="row gap"><button class="mini" data-fldiag>${esc(Z("网络诊断", "วินิจฉัยเครือข่าย"))}</button>${window.TRIAL && TRIAL.can() ? `<button class="mini" data-tr-ptest="${r.index}">🧪 ${esc(Z("打印测试", "ทดสอบพิมพ์"))}</button>` : ""}</div>`;
    const fl = FIELD();
    const ovr = `<p class="small muted">${esc(Z("左边是机型模板的值（系统 → 设置 → 生产 → 机型模板）；这台不一样才填右边，例如这台换了 0.6 喷嘴。发送切片文件前按这里核对。", "ซ้ายคือค่าจากแม่แบบรุ่น (ระบบ → ตั้งค่า → การผลิต → แม่แบบรุ่น) กรอกด้านขวาเฉพาะเมื่อเครื่องนี้ต่างไป เช่น เปลี่ยนหัวฉีด 0.6 ระบบจะตรวจตามนี้ก่อนส่งไฟล์สไลซ์"))}</p>
      <table class="grid small fl-ovr"><thead><tr><th>${esc(Z("项目", "รายการ"))}</th><th>${esc(Z("机型模板", "แม่แบบรุ่น"))}</th><th>${esc(Z("这台单独设置", "ค่าเฉพาะเครื่องนี้"))}</th></tr></thead><tbody>
      ${D.fields.filter((f) => !(r.tech === "resin" && ["nozzle", "plate", "orca_machine", "orca_process", "orca_filament", "ams"].includes(f.key))).map((f) => `<tr class="${f.override != null ? "fl-has" : ""}"><td>${esc(fl[f.key])}</td><td data-notr>${esc(fieldVal(f.key, f.template))}</td>
        <td>${ow ? ovrInput(f) : `<span data-notr>${f.override != null ? esc(fieldVal(f.key, f.override)) : "—"}</span>`}</td></tr>`).join("")}</tbody></table>
      ${ow ? `<button class="primary mini" data-flsaveovr>${esc(Z("保存单独设置", "บันทึกค่าเฉพาะเครื่อง"))}</button>` : ""}`;
    const m = D.maintenance;
    const maint = m ? `<p class="small">${esc(Z(`累计打印 ${m.hours} 小时`, `พิมพ์สะสม ${m.hours} ชั่วโมง`))}</p>${m.items.map((it) => `<div class="row between small ${it.due ? "bad" : ""}">
        <span>${esc(it.label)}：${esc(Z(`每 ${it.every_h} 小时，已 ${it.since_h} 小时`, `ทุก ${it.every_h} ชม. ผ่านไป ${it.since_h} ชม.`))}</span><button class="mini" data-flmaint="${esc(it.item)}">${esc(Z("已保养", "บำรุงรักษาแล้ว"))}</button></div>`).join("")}
      ${D.maint_log.length ? `<details><summary class="small">${esc(Z("保养记录", "ประวัติการบำรุงรักษา"))}</summary><table class="grid small">${D.maint_log.map((x) => `<tr><td>${h.day(x.ts)}</td><td data-notr>${esc(x.item)}</td><td data-notr>${esc(x.username || "")}</td><td data-notr>${esc(x.note || "")}</td></tr>`).join("")}</table></details>` : ""}` : "";
    const RS = { done: Z("打好", "เสร็จ"), failed: Z("失败", "ล้มเหลว"), printing: Z("打印中", "กำลังพิมพ์") };
    const hist = D.history.length ? `<div class="tbl-scroll"><table class="grid small"><thead><tr><th>${esc(Z("开始", "เริ่ม"))}</th><th>SKU</th><th>${esc(Z("件数", "จำนวน"))}</th><th>${esc(Z("结果", "ผล"))}</th></tr></thead><tbody>
      ${D.history.map((x) => `<tr><td>${h.day(x.started_at)}</td><td class="mono" data-notr>${esc(x.sku || "")}</td><td>${x.count || ""}</td><td>${esc(RS[x.status] || x.status)}${x.fail_reason ? ` <span class="small muted" data-notr>${esc(x.fail_reason)}</span>` : ""}</td></tr>`).join("")}</tbody></table></div>` : UX.empty(Z("还没有打印记录", "ยังไม่มีประวัติการพิมพ์"));
    return `<div class="row between"><h3><span class="pcode" data-notr>${esc(p.code)}</span> <span data-notr>${esc(p.name)}</span></h3>
        <span class="row gap"><a class="btn mini" target="_blank" href="/print/fleet-labels?ids=${encodeURIComponent(p.id)}&lang=${LANG()}">🏷 ${esc(Z("标签", "ป้าย"))}</a><button class="mini" data-flclose>${esc(Z("关闭", "ปิด"))}</button></span></div>
      ${sec(Z("状态", "สถานะ"), statusB)}
      ${sec(Z("基本信息", "ข้อมูลพื้นฐาน"), basic)}
      ${sec(Z("连接", "การเชื่อมต่อ"), conn)}
      ${sec(Z("单独设置", "ค่าเฉพาะเครื่อง"), ovr, (p.ovr && Object.keys(p.ovr).length) > 0)}
      ${sec(Z("保养", "การบำรุงรักษา"), maint, r.maint_due.length > 0)}
      ${sec(Z("打印记录", "ประวัติการพิมพ์"), hist, false)}
      ${ow ? `<div class="row gap" style="margin-top:12px"><button class="danger mini" data-flremove>${esc(Z("移除这台打印机", "นำเครื่องนี้ออก"))}</button></div>` : ""}`;
  }
  function collect(sel, attr) {
    const o = {};
    $$(sel, drawerEl()).forEach((x) => (o[x.dataset[attr]] = x.type === "checkbox" ? x.checked : x.value));
    return o;
  }
  function connBody() {
    const vend = drawerEl().querySelector("[data-flvendor]").value;
    return { vendor: vend, conn: collect("[data-flc]", "flc") };
  }
  function testRes(r) {
    const box = drawerEl().querySelector("[data-fltestres]");
    if (!box) return;
    const ic = (ok) => (ok === true ? "✅" : ok === false ? "❌" : "ℹ️");
    box.innerHTML = `<div class="fl-test small">${r.ok ? `<b class="ok">${esc(Z("连接成功", "เชื่อมต่อสำเร็จ"))}：${esc(STATES()[(r.status || {}).state] || r.status_zh || "")}</b>` : `<b class="bad">${esc(Z("连接失败", "เชื่อมต่อไม่สำเร็จ"))}</b>`}
      ${(r.checks || []).map((c) => `<div>${ic(c.ok)} ${esc(Z(c.zh, c.th))}</div>`).join("")}${r.message && !r.ok ? `<div class="muted" data-notr>${esc(r.message)}</div>` : ""}</div>`;
  }
  async function onDrawerChange(e) {
    const t = e.target;
    if (t.dataset.flvendor !== undefined) {
      const c = (DET.printer.conn || {});
      drawerEl().querySelector("[data-flvform]").innerHTML = vendorForm(t.value, t.value === DET.vendor ? c : { auto_complete: c.auto_complete });
    }
  }
  async function onDrawerClick(e) {
    const t = e.target, D = DET;
    if (!D) return;
    const id = D.printer.id, idx = D.row.index;
    const save = async (body, btn) => { DET = await busy(btn, () => api(U("/api/fleet/printers/" + encodeURIComponent(id)), { json: body })); drawerEl().querySelector(".fl-din").innerHTML = drawerHtml(DET); toast(Z("已保存", "บันทึกแล้ว")); load(true).catch(() => {}); };
    try {
      if (t.dataset.flclose !== undefined) closeDrawer();
      else if (t.dataset.flsavebasic !== undefined) await save(collect("[data-flb]", "flb"), t);
      else if (t.dataset.flsaveconn !== undefined) await save(connBody(), t);
      else if (t.dataset.flsaveovr !== undefined) await save({ ovr: collect("[data-flo]", "flo") }, t);
      else if (t.dataset.fltest !== undefined) {
        const body = connBody();
        const r = await busy(t, () => api(U("/api/fleet/printers/" + encodeURIComponent(id) + "/test"), { json: body }));
        testRes(r);
      } else if (t.dataset.fldiag !== undefined) { if (window.PROD && PROD.netDiag) PROD.netDiag(idx, t, id); }
      else if (t.dataset.flcmd !== undefined) {
        if (t.dataset.flcmd === "stop" && !confirm(Z("确定取消这台打印机正在打的任务？", "ยืนยันยกเลิกงานที่เครื่องนี้กำลังพิมพ์?"))) return;
        await busy(t, () => api(`/api/printers/${idx}/command`, { json: { cmd: t.dataset.flcmd, printer_id: id } }));   // 带稳定 id：列表变了服务器会拒绝
        toast(Z("指令已发送", "ส่งคำสั่งแล้ว")); setTimeout(() => refreshDrawer().catch(() => {}), 2500);
      } else if (t.dataset.flsaveloaded !== undefined) {
        await api(`/api/printers/${idx}/loaded`, { json: { loaded: drawerEl().querySelector("[data-flloaded]").value, printer_id: id } });
        toast(Z("已保存，排单会优先用这台打印机打这些颜色", "บันทึกแล้ว ระบบจัดคิวจะใช้เครื่องนี้พิมพ์สีเหล่านี้ก่อน"));
      } else if (t.dataset.flmaint) {
        const done = () => { refreshDrawer().catch(() => {}); load(true).catch(() => {}); };
        if (window.PROD && PROD.maintDialog) await busy(t, () => PROD.maintDialog(idx, t.dataset.flmaint, done, id));   // 可以选用掉的备件
        else { await busy(t, () => api("/api/maintenance", { json: { printer: idx, item: t.dataset.flmaint, printer_id: id } })); toast(Z("已记录保养", "บันทึกการบำรุงรักษาแล้ว")); done(); }
      } else if (t.dataset.flremove !== undefined) {
        if (!confirm(Z(`移除打印机 ${D.printer.code}？\n排给它的任务会自动转到其他机器；打印记录保留。`, `นำเครื่อง ${D.printer.code} ออก?\nงานที่จัดให้เครื่องนี้จะย้ายไปเครื่องอื่นอัตโนมัติ ประวัติการพิมพ์ยังเก็บไว้`))) return;
        await busy(t, () => api(U("/api/fleet/printers/" + encodeURIComponent(id)), { method: "DELETE" }));
        toast(Z("已移除", "นำออกแล้ว")); closeDrawer(); META = null; load();
      }
    } catch (err) { toast(err.message, true); }
  }

  // ---------------- 添加 / 发现 / 导入 ----------------
  function modelOpts(cur) {
    return (META.models || []).map((m) => `<option value="${esc(m.name)}" ${m.name === cur ? "selected" : ""}>${esc(m.name)}</option>`).join("");
  }
  function addDialog() {
    const first = (META.models || [])[0] || { name: "", vendors: ["none"] };
    const m = MODAL.open(`<h3>${esc(Z("添加打印机", "เพิ่มเครื่องพิมพ์"))}</h3>
      <div class="form2"><label>${esc(Z("机型", "รุ่น"))}<select id="fa-model" data-notr>${modelOpts(first.name)}</select></label>
        <label>${esc(Z("台数", "จำนวนเครื่อง"))}<input id="fa-n" type="number" min="1" max="500" value="1"></label>
        <label>${esc(Z("机器编码（空 = 自动，例如 P1S-001）", "รหัสเครื่อง (ว่าง = อัตโนมัติ เช่น P1S-001)"))}<input id="fa-code" data-notr></label>
        <label>${esc(Z("分组", "กลุ่ม"))}<input id="fa-group" list="fa-groups" data-notr><datalist id="fa-groups">${(META.groups || []).map((g) => `<option value="${esc(g)}">`).join("")}</datalist></label>
        <label>${esc(Z("位置", "ตำแหน่ง"))}<input id="fa-loc" placeholder="A-03-2" data-notr></label>
        <label id="fa-nzl">${esc(Z("喷嘴直径 mm（请确认，每台单独记）", "ขนาดหัวฉีด มม. (กรุณายืนยัน บันทึกแยกแต่ละเครื่อง)"))}<input id="fa-nozzle" type="number" min="0.1" max="2" step="0.05" value="0.4"></label>
        <label>${esc(Z("厂家 / 连接方式", "ยี่ห้อ / การเชื่อมต่อ"))}<select id="fa-vendor"></select></label></div>
      <div id="fa-vform"></div>
      <p class="small muted" id="fa-many">${esc(Z("一次加多台时先不填连接（每台 IP 不一样）：加好后在列表里点每台填，或用「局域网发现」「导入」。", "ถ้าเพิ่มหลายเครื่องพร้อมกัน ยังไม่ต้องกรอกการเชื่อมต่อ (IP แต่ละเครื่องไม่เหมือนกัน) เพิ่มแล้วกดที่แต่ละเครื่องเพื่อกรอก หรือใช้ «ค้นหาในเครือข่าย» «นำเข้า»"))}</p>
      <div class="row gap"><button class="primary" id="fa-ok">${esc(Z("添加", "เพิ่ม"))}</button><button data-mclose>${esc(Z("取消", "ยกเลิก"))}</button></div>`);
    const sync = () => {
      const name = m.querySelector("#fa-model").value, n = +m.querySelector("#fa-n").value || 1;
      const mm = (META.models || []).find((x) => x.name === name) || { vendors: ["none"], vendor: "none" };
      const vs = m.querySelector("#fa-vendor");
      const keep = vs.value;
      vs.innerHTML = mm.vendors.map((k) => `<option value="${k}">${esc(Z(META.vendors[k].zh, META.vendors[k].th))}</option>`).join("");
      vs.value = mm.vendors.includes(keep) ? keep : mm.vendor;
      vs.disabled = n > 1;
      m.querySelector("#fa-code").disabled = n > 1;
      m.querySelector("#fa-many").classList.toggle("hidden", n <= 1);
      m.querySelector("#fa-nzl").classList.toggle("hidden", mm.tech === "resin");
      m.querySelector("#fa-vform").innerHTML = n > 1 ? "" : vendorForm(vs.value, {}).replace(/data-flc=/g, "data-fac=");
    };
    m.querySelector("#fa-model").onchange = sync; m.querySelector("#fa-n").oninput = sync;
    m.querySelector("#fa-vendor").onchange = () => { m.querySelector("#fa-vform").innerHTML = vendorForm(m.querySelector("#fa-vendor").value, {}).replace(/data-flc=/g, "data-fac="); };
    sync();
    m.querySelector("#fa-ok").onclick = (e) => busy(e.target, async () => {
      const conn = {}; m.querySelectorAll("[data-fac]").forEach((x) => (conn[x.dataset.fac] = x.type === "checkbox" ? x.checked : x.value));
      const n = +m.querySelector("#fa-n").value || 1;
      const body = { name: m.querySelector("#fa-model").value, n, group: m.querySelector("#fa-group").value, location: m.querySelector("#fa-loc").value,
        nozzle: m.querySelector("#fa-nozzle").value };
      if (n === 1) Object.assign(body, { code: m.querySelector("#fa-code").value, vendor: m.querySelector("#fa-vendor").value, conn });
      try {
        const r = await api(U("/api/fleet/printers"), { json: body });
        toast(Z(`已添加：${r.codes.join("、")}`, `เพิ่มแล้ว: ${r.codes.join(", ")}`)); MODAL.close(); META = null; await load();
        if (r.added.length === 1) openDrawer(r.added[0]);
      } catch (err) { toast(err.message, true); }
    });
  }
  function devRows(list, kind) {
    return `<div class="tbl-scroll" style="max-height:50vh"><table class="grid small fl-dev"><thead><tr><th><input type="checkbox" data-fdall checked></th><th>IP</th><th>${esc(Z("序列号", "ซีเรียล"))}</th><th>${esc(Z("机型", "รุ่น"))}</th>
      <th>${esc(Z("连接", "การเชื่อมต่อ"))}</th>${kind === "disc" ? `<th>${esc(Z("访问码", "รหัสเข้าถึง"))}</th>` : ""}<th>${esc(Z("喷嘴 mm", "หัวฉีด มม."))}</th><th>${esc(Z("编码", "รหัส"))}</th><th>${esc(Z("分组", "กลุ่ม"))}</th><th>${esc(Z("位置", "ตำแหน่ง"))}</th><th></th></tr></thead><tbody>
      ${list.map((d, i) => `<tr data-fd="${i}" class="${d.exists ? "muted" : ""}"><td><input type="checkbox" data-fdon ${d.exists || d.ok === false ? "" : "checked"} ${d.exists ? "disabled" : ""}></td>
        <td class="mono" data-notr>${esc(d.ip || d.host || "")}</td><td><input data-fdk="serial" value="${esc(d.serial || "")}" style="width:140px" data-notr></td>
        <td><select data-fdk="model" data-notr><option value="">—</option>${modelOpts(d.model)}</select>${d.guess ? ` <span class="small muted">${esc(Z("猜的", "เดา"))}</span>` : ""}</td>
        <td><select data-fdk="vendor">${Object.keys(META.vendors).map((k) => `<option value="${k}" ${k === d.vendor ? "selected" : ""}>${esc(Z(META.vendors[k].zh, META.vendors[k].th))}</option>`).join("")}</select></td>
        ${kind === "disc" ? `<td><input data-fdk="access_code" style="width:90px" placeholder="${d.vendor === "bambu" ? "12345678" : ""}" data-notr></td>` : ""}
        <td><input data-fdk="nozzle" type="number" min="0.1" max="2" step="0.05" value="${esc(d.nozzle || "0.4")}" style="width:60px"></td>
        <td><input data-fdk="code" value="${esc(d.code || "")}" placeholder="${esc(Z("自动", "อัตโนมัติ"))}" style="width:90px" data-notr></td>
        <td><input data-fdk="group" value="${esc(d.group || "")}" style="width:70px" data-notr></td><td><input data-fdk="location" value="${esc(d.location || "")}" style="width:80px" data-notr></td>
        <td class="small">${d.exists ? esc(Z(`已有：${d.exists}`, `มีแล้ว: ${d.exists}`)) : ""}${d.lan_mode === false ? `<span class="bad">${esc(Z("没开局域网模式", "ยังไม่เปิดโหมด LAN"))}</span>` : ""}
          ${(d.errors || []).map((x) => `<div class="bad">${esc(Z(x[0], x[1]))}</div>`).join("")}${(d.warnings || []).map((x) => `<div class="muted">${esc(Z(x[0], x[1]))}</div>`).join("")}</td></tr>`).join("")}</tbody></table></div>`;
  }
  function pickDevices(m, list) {
    return $$("tr[data-fd]", m).filter((tr) => tr.querySelector("[data-fdon]").checked).map((tr) => {
      const d = list[+tr.dataset.fd], o = { host: d.ip || d.host || "" };
      tr.querySelectorAll("[data-fdk]").forEach((x) => (o[x.dataset.fdk] = x.value));
      if (!o.access_code && d.access_code && d.access_code !== "******") o.access_code = d.access_code;
      if (d.row) o.row = d.row;          // 导入：访问码等原始值留在服务器上，按行号取（v2.54 复审：不经过浏览器）
      return o;
    });
  }
  async function commitDevices(m, list, btn) {
    const devs = pickDevices(m, list);
    if (!devs.length) { toast(Z("先勾选要添加的设备", "เลือกอุปกรณ์ที่จะเพิ่มก่อน"), true); return; }
    try {
      const r = await busy(btn, () => fetch(U("/api/fleet/add-many"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ devices: devs, token: list.token || undefined }) }).then((x) => x.json()));
      if (!r.ok) {
        toast(r.error || Z("有问题，没有添加", "มีปัญหา ยังไม่ได้เพิ่ม"), true);
        (r.rows || []).forEach((row, k) => {
          const tr = $$("tr[data-fd]", m).filter((x) => x.querySelector("[data-fdon]").checked)[k];
          if (tr && !row.ok) tr.lastElementChild.innerHTML = row.errors.map((x) => `<div class="bad">${esc(Z(x[0], x[1]))}</div>`).join("");
        });
        return;
      }
      toast(Z(`已添加 ${r.added.length} 台：${r.codes.slice(0, 10).join("、")}${r.codes.length > 10 ? "…" : ""}`, `เพิ่มแล้ว ${r.added.length} เครื่อง`)); MODAL.close(); META = null; load();
    } catch (err) { toast(err.message, true); }
  }
  function discoverDialog() {
    const m = MODAL.open(`<h3>🔍 ${esc(Z("局域网发现", "ค้นหาในเครือข่าย"))}</h3>
      <p class="small muted">${esc(Z("听拓竹打印机的广播（能拿到序列号），再扫服务器所在网段的打印机端口（8883 拓竹 / 9999 Creality / 7125、4408 Klipper）。大约 10–30 秒。拓竹的访问码要在打印机屏幕上看，填好再添加。", "ฟังสัญญาณจากเครื่อง Bambu (ได้หมายเลขซีเรียล) แล้วสแกนพอร์ตเครื่องพิมพ์ในเครือข่ายของเซิร์ฟเวอร์ (8883 Bambu / 9999 Creality / 7125, 4408 Klipper) ประมาณ 10–30 วินาที รหัสเข้าถึงของ Bambu ดูที่หน้าจอเครื่อง กรอกแล้วค่อยเพิ่ม"))}</p>
      <div class="row gap"><input id="fd-cidr" placeholder="${esc(Z("网段（空 = 自动），例如 192.168.1.0/24", "เครือข่าย (ว่าง = อัตโนมัติ) เช่น 192.168.1.0/24"))}" style="width:300px" data-notr><button class="primary" id="fd-go">${esc(Z("开始找", "เริ่มค้นหา"))}</button></div>
      <div id="fd-res"></div><div class="row gap" style="margin-top:8px"><button class="primary hidden" id="fd-add">${esc(Z("添加勾选的", "เพิ่มที่เลือก"))}</button><button data-mclose>${esc(Z("关闭", "ปิด"))}</button></div>`);
    let list = [];
    m.querySelector("#fd-go").onclick = (e) => busy(e.target, async () => {
      try {
        const r = await api(U("/api/fleet/discover"), { json: { cidr: m.querySelector("#fd-cidr").value.trim() } });
        list = r.devices.map((d) => Object.assign(d, { code: d.code_suggest || "" }));
        m.querySelector("#fd-res").innerHTML = `<p class="small">${esc(Z(`扫了 ${r.scanned} 个地址，找到 ${list.length} 台`, `สแกน ${r.scanned} ที่อยู่ พบ ${list.length} เครื่อง`))}</p>` + (list.length ? devRows(list, "disc") : "");
        m.querySelector("#fd-add").classList.toggle("hidden", !list.length);
      } catch (err) { toast(err.message, true); }
    });
    m.querySelector("#fd-add").onclick = (e) => commitDevices(m, list, e.target);
    m.addEventListener("change", (e) => { if (e.target.dataset.fdall !== undefined) $$("[data-fdon]:not(:disabled)", m).forEach((x) => (x.checked = e.target.checked)); });
  }
  function importDialog() {
    const m = MODAL.open(`<h3>📥 ${esc(Z("导入打印机（Excel / CSV）", "นำเข้าเครื่องพิมพ์ (Excel / CSV)"))}</h3>
      <p class="small muted">${esc(Z("表头：编码、机型、IP、序列号、访问码、分组、位置（英文 code, model, ip, serial, access code, group, location 也行）。先检查，确认没问题再添加。", "หัวตาราง: รหัส รุ่น IP ซีเรียล รหัสเข้าถึง กลุ่ม ตำแหน่ง (ภาษาอังกฤษ code, model, ip, serial, access code, group, location ก็ได้) ตรวจก่อน แล้วค่อยเพิ่ม"))}
        <a href="/api/fleet/import-template">${esc(Z("下载模板", "ดาวน์โหลดแม่แบบ"))}</a></p>
      <label class="filebtn">📄 ${esc(Z("选文件", "เลือกไฟล์"))}<input type="file" id="fi-file" accept=".xlsx,.csv,.txt" hidden></label>
      <div id="fi-res"></div><div class="row gap" style="margin-top:8px"><button class="primary hidden" id="fi-add">${esc(Z("添加勾选的", "เพิ่มที่เลือก"))}</button><button data-mclose>${esc(Z("关闭", "ปิด"))}</button></div>`);
    let list = [];
    m.querySelector("#fi-file").onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return;
      const fd = new FormData(); fd.append("file", f);
      try {
        const r = await fetch(U("/api/fleet/import"), { method: "POST", body: fd }).then((x) => x.json());
        if (r.error) { toast(r.error, true); return; }
        list = r.rows.map((x) => ({ ip: x.printer.conn.host || "", serial: x.printer.conn.serial || "", model: x.printer.name, vendor: x.printer.conn.type,
          code: x.printer.code, group: x.printer.group, location: x.printer.location, ok: x.ok, errors: x.errors, warnings: x.warnings,
          row: x.row, nozzle: (x.printer.ovr || {}).nozzle || "" }));
        list.token = r.token;
        m.querySelector("#fi-res").innerHTML = `<p class="small">${esc(Z(`共 ${r.rows.length} 行：${r.ok} 行可以添加，${r.bad} 行有问题`, `ทั้งหมด ${r.rows.length} แถว: เพิ่มได้ ${r.ok} แถว มีปัญหา ${r.bad} แถว`))}</p>` + devRows(list, "imp");
        m.querySelector("#fi-add").classList.toggle("hidden", !r.ok);
      } catch (err) { toast(err.message, true); }
    };
    m.querySelector("#fi-add").onclick = (e) => commitDevices(m, list, e.target);
    m.addEventListener("change", (e) => { if (e.target.dataset.fdall !== undefined) $$("[data-fdon]:not(:disabled)", m).forEach((x) => (x.checked = e.target.checked)); });
  }

  // ---------------- 批量操作 ----------------
  async function bulk(act) {
    const body = { action: act };
    if (SEL.size) body.ids = [...SEL]; else if (Q.group !== "*") body.group = Q.group; else return;
    const n = SEL.size || (DATA.groups[Q.group] || {}).n || 0;
    if (act === "labels") { window.open(`/print/fleet-labels?lang=${LANG()}&` + (SEL.size ? "ids=" + [...SEL].join(",") : "group=" + encodeURIComponent(Q.group)), "_blank"); return; }
    if (["role", "group", "location", "nozzle", "plate", "dedicate"].includes(act)) {
      let ask = "";
      if (act === "role") ask = Z("用途：any（都可以）/ orders（只打订单）/ stock（只打备货）", "การใช้งาน: any (ทั้งหมด) / orders (เฉพาะออเดอร์) / stock (เฉพาะสต็อก)");
      if (act === "group") ask = Z("分组（例如 A 区；空 = 不分组）", "กลุ่ม (เช่น โซน A; ว่าง = ไม่มีกลุ่ม)");
      if (act === "location") ask = Z("位置（例如 A-03-2）", "ตำแหน่ง (เช่น A-03-2)");
      if (act === "nozzle") ask = Z("喷嘴直径 mm（例如 0.6；空 = 跟随机型模板）", "ขนาดหัวฉีด มม. (เช่น 0.6; ว่าง = ตามแม่แบบรุ่น)");
      if (act === "plate") ask = Z("热床板：Textured PEI Plate / Smooth PEI Plate / Cool Plate / Engineering Plate / High Temp Plate（空 = 跟随模板）", "แผ่นฐาน: Textured PEI Plate / Smooth PEI Plate / Cool Plate / Engineering Plate / High Temp Plate (ว่าง = ตามแม่แบบ)");
      if (act === "dedicate") {
        const po = await prodOrders();
        ask = Z("生产单号（空 = 取消专用）", "เลขใบสั่งผลิต (ว่าง = ยกเลิก)") + (po && po.length ? "\n" + po.slice(0, 20).map((o) => `${o.id} ${o.code || o.name || ""}`).join("\n") : "");
      }
      const v = prompt(ask, act === "role" ? "any" : "");
      if (v === null) return;
      body.value = v.trim();
    } else if (act === "remove") {
      if (!confirm(Z(`移除 ${n} 台打印机？排给它们的任务会自动转到其他机器；打印记录保留。`, `นำเครื่องพิมพ์ ${n} เครื่องออก? งานที่จัดไว้จะย้ายไปเครื่องอื่นอัตโนมัติ ประวัติยังเก็บไว้`))) return;
    } else if (act !== "test" && !confirm(Z(`对 ${n} 台打印机执行？`, `ทำกับเครื่องพิมพ์ ${n} เครื่อง?`))) return;
    try {
      const r = await busyToast(Z("处理中", "กำลังทำงาน"), () => api(U("/api/fleet/bulk"), { json: body }));
      if (act === "test") {
        const bad = r.results.filter((x) => !x.ok);
        MODAL.open(`<h3>${esc(Z("测试连接结果", "ผลทดสอบการเชื่อมต่อ"))}</h3><p>${esc(Z(`${r.results.length - bad.length} 台成功，${bad.length} 台失败`, `สำเร็จ ${r.results.length - bad.length} เครื่อง ล้มเหลว ${bad.length} เครื่อง`))}${r.skipped ? esc(Z(`（另外 ${r.skipped} 台没测：一次最多 200 台）`, ` (ไม่ได้ทดสอบอีก ${r.skipped} เครื่อง: ครั้งละไม่เกิน 200)`)) : ""}</p>
          <div class="tbl-scroll" style="max-height:60vh"><table class="grid small">${r.results.map((x) => `<tr><td class="mono" data-notr>${esc(x.code)}</td><td>${x.ok ? "✅" : "❌"}</td><td data-notr>${esc(x.message || "")}</td></tr>`).join("")}</table></div>
          <button data-mclose>${esc(Z("关闭", "ปิด"))}</button>`);
      } else toast(Z(`已处理 ${r.n} 台`, `ดำเนินการแล้ว ${r.n} เครื่อง`));
      if (act === "remove") SEL.clear();
      META = null; load();
    } catch (err) { toast(err.message, true); }
  }

  // ---------------- 事件 ----------------
  document.addEventListener("click", (e) => {
    const r = root();
    if (!r || !r.contains(e.target)) return;
    const t = e.target;
    if (t.matches("[data-flsel], [data-flall]")) return;
    const ad = t.closest("[data-fladd],[data-fldisc],[data-flimp],[data-flreload],[data-flpg],[data-flclr]");
    if (ad) {
      e.preventDefault();
      if (ad.dataset.fladd !== undefined) meta().then(addDialog);
      if (ad.dataset.fldisc !== undefined) meta().then(discoverDialog);
      if (ad.dataset.flimp !== undefined) meta().then(importDialog);
      if (ad.dataset.flreload !== undefined) busy(ad, () => { META = null; return load(); });
      if (ad.dataset.flpg) { Q.page = Math.max(1, Q.page + +ad.dataset.flpg); load(); }
      if (ad.dataset.flclr !== undefined) { SEL.clear(); render(); }
      return;
    }
    const o = t.closest("[data-flopen]");
    if (o && !t.closest("a,button,input,select")) openDrawer(o.dataset.flopen);
  });
  document.addEventListener("ux-go", (e) => {
    const v = String(e.detail || "");
    if (!v.startsWith("fl:")) return;
    Q.status = v.slice(3); Q.page = 1; load();
  });
  document.addEventListener("change", (e) => {
    const r = root();
    if (!r || !r.contains(e.target)) return;
    const t = e.target;
    if (t.dataset.flq) { Q[t.dataset.flq] = t.value; Q.page = 1; load(); return; }
    if (t.dataset.flsel) { if (t.checked) SEL.add(t.dataset.flsel); else SEL.delete(t.dataset.flsel); render(); return; }
    if (t.dataset.flall !== undefined) { (DATA.rows || []).forEach((x) => (t.checked ? SEL.add(x.id) : SEL.delete(x.id))); render(); return; }
    if (t.id === "fl-bact" && t.value) { const a = t.value; t.value = ""; bulk(a); }
  });
  let qT = null;
  document.addEventListener("input", (e) => {
    if (!e.target.matches || !e.target.matches('#fleet-root [data-flq="q"]')) return;
    clearTimeout(qT); qT = setTimeout(() => { Q.q = e.target.value; Q.page = 1; load().then(() => { const i = document.querySelector('#fleet-root [data-flq="q"]'); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }); }, 350);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && OPEN && !document.querySelector("#modal:not(.hidden)")) closeDrawer(); });

  window.FLEET = { show, load, openDrawer, closeDrawer, stop: () => clearInterval(TIMER) };
})();
