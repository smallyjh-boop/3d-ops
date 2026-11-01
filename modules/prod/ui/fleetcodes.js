"use strict";
// v2.55 打印机编码规则：积木式规则编辑器（⚙）+ 批量重新编号对话框（旧 → 新预览、冲突标红、确认后改）。
// 规则：固定前缀 / 分组 / 机架-层-位（来自位置）/ 机型简称 / 顺序号（2·3·4 位；同机型·同分组·全部）+ 分隔符。
// 打印机身份是稳定 id，改编码不会动任务和记录；料卷、出入库记录、仓库生产区货位由服务器一起改。
(function () {
  const Z = (zh, th) => (window.I18N && I18N.lang === "th" ? th : zh);
  const LANG = () => (window.I18N && I18N.lang === "th" ? "th" : "zh");
  const U = (u) => u + (u.includes("?") ? "&" : "?") + "lang=" + LANG();
  const BT = () => ({ fixed: Z("固定前缀", "คำนำหน้าคงที่"), group: Z("分组", "กลุ่ม"), loc: Z("机架-层-位（位置）", "ชั้นวาง-ชั้น-ช่อง (ตำแหน่ง)"),
    model: Z("机型简称", "ชื่อย่อรุ่น"), seq: Z("顺序号", "เลขลำดับ") });
  const SC = () => ({ model: Z("同机型内排", "นับตามรุ่น"), group: Z("同分组内排", "นับตามกลุ่ม"), global: Z("全部一起排", "นับรวมทั้งหมด") });
  const SEPS = () => [["-", "-"], ["_", "_"], ["", Z("不要", "ไม่ใช้")]];
  let R = null, CUR = "", T = null;

  const clone = (x) => JSON.parse(JSON.stringify(x));
  const newId = () => "r" + Math.random().toString(36).slice(2, 8);

  // ---------------- 规则编辑器 ----------------
  function blockHtml(b, i, n) {
    const bt = BT();
    let ex = "";
    if (b.t === "fixed") ex = `<input data-cb="v" value="${esc(b.v || "")}" maxlength="8" placeholder="PR" style="width:70px" data-notr>`;
    if (b.t === "seq") ex = `<select data-cb="width">${[2, 3, 4].map((w) => `<option value="${w}" ${+b.width === w ? "selected" : ""}>${Z(w + " 位", w + " หลัก")}</option>`).join("")}</select>
      <select data-cb="scope">${Object.entries(SC()).map(([k, v]) => `<option value="${k}" ${b.scope === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
    return `<div class="cd-blk" data-bi="${i}"><b>${esc(bt[b.t])}</b>${ex}
      <span class="cd-mv"><button class="mini" data-cmv="-1" ${i ? "" : "disabled"}>◀</button><button class="mini" data-cmv="1" ${i < n - 1 ? "" : "disabled"}>▶</button><button class="mini" data-cdel>✕</button></span></div>`;
  }
  function editorHtml() {
    const r = R.rules[CUR];
    const ids = Object.keys(R.rules);
    const bt = BT();
    const groups = R.group_list || [];
    return `<div class="row gap wrap" style="align-items:end">
        <label>${esc(Z("规则", "กฎ"))}<select id="cd-sel">${ids.map((k) => `<option value="${esc(k)}" ${k === CUR ? "selected" : ""} data-notr>${esc(R.rules[k].name || k)}${k === R.default ? " ★" : ""}</option>`).join("")}</select></label>
        <button class="mini" data-cnew>＋ ${esc(Z("新建规则", "สร้างกฎใหม่"))}</button>
        <button class="mini" data-cdef ${CUR === R.default ? "disabled" : ""}>★ ${esc(Z("设为默认", "ตั้งเป็นค่าเริ่มต้น"))}</button>
        <button class="mini danger" data-crm ${ids.length < 2 ? "disabled" : ""}>${esc(Z("删除这条", "ลบกฎนี้"))}</button></div>
      <div class="form2" style="margin-top:8px"><label>${esc(Z("规则名称", "ชื่อกฎ"))}<input id="cd-name" value="${esc(r.name || "")}" maxlength="30" data-notr></label>
        <label>${esc(Z("分隔符", "ตัวคั่น"))}<select id="cd-sep">${SEPS().map(([v, l]) => `<option value="${esc(v)}" ${r.sep === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label></div>
      <div class="small muted" style="margin:8px 0 2px">${esc(Z("积木按顺序拼成编码；点 ◀ ▶ 调顺序。", "บล็อกจะต่อเป็นรหัสตามลำดับ กด ◀ ▶ เพื่อสลับตำแหน่ง"))}</div>
      <div class="cd-blks">${r.blocks.map((b, i) => blockHtml(b, i, r.blocks.length)).join("")}
        <select id="cd-add"><option value="">＋ ${esc(Z("加积木…", "เพิ่มบล็อก…"))}</option>${Object.entries(bt).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></div>
      <div class="cd-prev" id="cd-prev"></div>
      <h4 style="margin:14px 0 4px">${esc(Z("各分组用哪条规则", "แต่ละกลุ่มใช้กฎไหน"))}</h4>
      <p class="small muted">${esc(Z("没单独设的分组用默认规则。「分组简称」是分组积木用的英文 / 数字（分组名是中文 / 泰文时填）。", "กลุ่มที่ไม่ได้ตั้งไว้ใช้กฎเริ่มต้น «ชื่อย่อกลุ่ม» คือตัวอักษร/ตัวเลขที่บล็อกกลุ่มใช้ (กรอกเมื่อชื่อกลุ่มเป็นจีน/ไทย)"))}</p>
      ${groups.length ? `<table class="grid small"><thead><tr><th>${esc(Z("分组", "กลุ่ม"))}</th><th>${esc(Z("规则", "กฎ"))}</th><th>${esc(Z("分组简称", "ชื่อย่อกลุ่ม"))}</th></tr></thead><tbody>
        ${groups.map((g) => `<tr><td data-notr>${esc(g)}</td><td><select data-cgr="${esc(g)}"><option value="">${esc(Z("默认规则", "กฎเริ่มต้น"))}</option>${ids.map((k) => `<option value="${esc(k)}" ${R.groups[g] === k ? "selected" : ""} data-notr>${esc(R.rules[k].name || k)}</option>`).join("")}</select></td>
        <td><input data-cgc="${esc(g)}" value="${esc(R.group_codes[g] || "")}" maxlength="6" style="width:80px" placeholder="${esc(Z("自动", "อัตโนมัติ"))}" data-notr></td></tr>`).join("")}</tbody></table>`
        : `<p class="small muted">${esc(Z("还没有分组。", "ยังไม่มีกลุ่ม"))}</p>`}
      <p class="small muted" style="margin-top:8px">${esc(Z("新规则只用于以后新添加 / 发现 / 导入的打印机；已有打印机的编码不会变，要改请勾选打印机 → 批量操作 →「按规则重新编号」。", "กฎใหม่ใช้กับเครื่องที่เพิ่ม / ค้นพบ / นำเข้าภายหลังเท่านั้น รหัสเดิมไม่เปลี่ยน ถ้าจะเปลี่ยนให้เลือกเครื่อง → ทำหลายเครื่อง → «เปลี่ยนรหัสตามกฎ»"))}</p>
      <div class="row gap"><button class="primary" id="cd-save">${esc(Z("保存", "บันทึก"))}</button><button data-mclose>${esc(Z("关闭", "ปิด"))}</button></div>`;
  }
  function draw(m) {
    m.querySelector("#cd-body").innerHTML = editorHtml();
    preview(m);
  }
  function pullBasics(m) {      // 把输入框里的改动写回 R
    const r = R.rules[CUR];
    const nm = m.querySelector("#cd-name"), sp = m.querySelector("#cd-sep");
    if (nm) r.name = nm.value;
    if (sp) r.sep = sp.value;
    $$("[data-bi]", m).forEach((el) => {
      const b = r.blocks[+el.dataset.bi];
      el.querySelectorAll("[data-cb]").forEach((x) => { b[x.dataset.cb] = x.dataset.cb === "width" ? +x.value : x.value; });
    });
    $$("[data-cgr]", m).forEach((x) => { if (x.value) R.groups[x.dataset.cgr] = x.value; else delete R.groups[x.dataset.cgr]; });
    $$("[data-cgc]", m).forEach((x) => { if (x.value.trim()) R.group_codes[x.dataset.cgc] = x.value.trim(); else delete R.group_codes[x.dataset.cgc]; });
  }
  function preview(m) {
    clearTimeout(T);
    T = setTimeout(async () => {
      const box = m.querySelector("#cd-prev");
      if (!box) return;
      try {
        const r = await api(U("/api/fleet/codes/preview"), { json: { rule: R.rules[CUR], group_codes: R.group_codes } });
        box.innerHTML = r.ok ? `<div class="small muted">${esc(Z("预览（例子）", "ตัวอย่าง"))}</div><div class="cd-ex">${r.examples.map((x) => `<span class="cd-chip ${x.problem || x.code.length > 16 ? "bad" : ""}"><b class="mono" data-notr>${esc(x.code)}</b>
          <i class="small muted" data-notr>${esc(x.name)} · ${esc(x.group)} · ${esc(x.location)}</i></span>`).join("")}</div>${r.length_ok ? "" : `<div class="small bad">${esc(Z("编码超过 16 位：减少积木或缩短前缀。", "รหัสยาวเกิน 16 ตัว: ลดบล็อกหรือลดคำนำหน้า"))}</div>`}`
          : `<div class="small bad">${r.errors.map((e) => esc(e.msg)).join("<br>")}</div>`;
      } catch (e) { box.innerHTML = `<div class="small bad">${esc(e.message)}</div>`; }
    }, 150);
  }
  async function rulesDialog() {
    R = clone(await api("/api/fleet/codes/rules"));
    CUR = R.default;
    const m = MODAL.open(`<h3>⚙ ${esc(Z("打印机编码规则", "กฎรหัสเครื่องพิมพ์"))}</h3>
      <p class="small muted">${esc(Z("像货位编码一样用积木拼：固定前缀、分组、机架-层-位、机型简称、顺序号。添加 / 发现 / 导入打印机没填编码时，按这里的规则自动编。例如 A-P1S-001。", "ต่อรหัสด้วยบล็อกเหมือนรหัสตำแหน่งคลัง: คำนำหน้าคงที่ กลุ่ม ชั้นวาง-ชั้น-ช่อง ชื่อย่อรุ่น เลขลำดับ เมื่อเพิ่ม / ค้นพบ / นำเข้าเครื่องโดยไม่กรอกรหัส ระบบจะตั้งตามกฎนี้ เช่น A-P1S-001"))}</p>
      <div id="cd-body"></div>`);
    draw(m);
    m.addEventListener("change", (e) => {
      const t = e.target;
      if (t.id === "cd-sel") { pullBasics(m); CUR = t.value; draw(m); return; }
      if (t.id === "cd-add") {
        pullBasics(m);
        if (t.value) {
          const b = { t: t.value };
          if (t.value === "fixed") b.v = "PR";
          if (t.value === "seq") { b.width = 3; b.scope = "model"; }
          R.rules[CUR].blocks.push(b);
        }
        draw(m); return;
      }
      pullBasics(m);
      if (t.dataset.cb !== undefined || t.id === "cd-sep" || t.dataset.cgc !== undefined) preview(m);
    });
    m.addEventListener("input", (e) => { if (e.target.dataset.cb !== undefined || e.target.dataset.cgc !== undefined) { pullBasics(m); preview(m); } });
    m.addEventListener("click", async (e) => {
      const t = e.target;
      const blk = t.closest("[data-bi]");
      if (t.dataset.cmv && blk) {
        pullBasics(m);
        const bl = R.rules[CUR].blocks, i = +blk.dataset.bi, j = i + +t.dataset.cmv;
        [bl[i], bl[j]] = [bl[j], bl[i]]; draw(m);
      } else if (t.dataset.cdel !== undefined && blk) { pullBasics(m); R.rules[CUR].blocks.splice(+blk.dataset.bi, 1); draw(m); }
      else if (t.dataset.cnew !== undefined) {
        pullBasics(m);
        const id = newId();
        R.rules[id] = { name: Z("新规则", "กฎใหม่") + " " + Object.keys(R.rules).length, sep: "-", blocks: [{ t: "group" }, { t: "model" }, { t: "seq", width: 3, scope: "model" }] };
        CUR = id; draw(m);
      } else if (t.dataset.cdef !== undefined) { pullBasics(m); R.default = CUR; draw(m); }
      else if (t.dataset.crm !== undefined) {
        if (!confirm(Z("删除这条规则？用它的分组会改回默认规则。已有打印机的编码不受影响。", "ลบกฎนี้? กลุ่มที่ใช้กฎนี้จะกลับไปใช้กฎเริ่มต้น รหัสเครื่องเดิมไม่เปลี่ยน"))) return;
        pullBasics(m);
        delete R.rules[CUR];
        Object.keys(R.groups).forEach((g) => { if (R.groups[g] === CUR) delete R.groups[g]; });
        CUR = Object.keys(R.rules)[0];
        if (R.default === undefined || !R.rules[R.default]) R.default = CUR;
        draw(m);
      } else if (t.id === "cd-save") {
        pullBasics(m);
        try {
          await busy(t, () => api(U("/api/fleet/codes/rules"), { json: { rules: R.rules, default: R.default, groups: R.groups, group_codes: R.group_codes } }));
          toast(Z("编码规则已保存", "บันทึกกฎรหัสแล้ว")); MODAL.close();
        } catch (er) { toast(er.message, true); }
      }
    });
  }

  // ---------------- 批量重新编号 ----------------
  // sel：{ids: [...]} 或 {group: "A 区"}；after：改完后刷新列表的回调
  async function renumber(sel, after) {
    const rs = await api("/api/fleet/codes/rules");
    const o = { rule: "", order: "location" };
    const m = MODAL.open(`<h3>🔢 ${esc(Z("按规则重新编号", "เปลี่ยนรหัสตามกฎ"))}</h3>
      <div class="row gap wrap"><label>${esc(Z("用哪条规则", "ใช้กฎไหน"))}<select id="rn-rule"><option value="">${esc(Z("每台按所在分组的规则", "แต่ละเครื่องตามกฎของกลุ่ม"))}</option>
        ${Object.keys(rs.rules).map((k) => `<option value="${esc(k)}" data-notr>${esc(rs.rules[k].name || k)}</option>`).join("")}</select></label>
        <label>${esc(Z("编号顺序", "ลำดับการให้เลข"))}<select id="rn-order"><option value="location">${esc(Z("按 分组 / 位置", "ตามกลุ่ม / ตำแหน่ง"))}</option>
          <option value="code">${esc(Z("按现在的编码", "ตามรหัสปัจจุบัน"))}</option><option value="list">${esc(Z("按列表顺序", "ตามลำดับในรายการ"))}</option></select></label>
        <button class="mini" data-rnrule>⚙ ${esc(Z("改规则", "แก้กฎ"))}</button></div>
      <div id="rn-res"><p class="muted">${esc(Z("读取中…", "กำลังโหลด…"))}</p></div>
      <p class="small muted">${esc(Z("改的只是显示用的编码：任务、打印记录、保养按打印机 id 对，不受影响；料卷装在哪台、出入库记录、仓库生产区货位名称会一起改过去。已经印出去的旧标签扫码仍能打开这台（记着旧编码）。", "เปลี่ยนเฉพาะรหัสที่แสดง งาน ประวัติการพิมพ์ การบำรุงรักษาอิงตาม id เครื่อง จึงไม่กระทบ ม้วนฟิลาเมนต์ที่ใส่ ประวัติเข้าออกคลัง และชื่อตำแหน่งโซนผลิตจะเปลี่ยนตามไปด้วย ป้ายเก่าที่พิมพ์ไปแล้วสแกนแล้วยังเปิดเครื่องนี้ได้ (จำรหัสเก่าไว้)"))}</p>
      <div class="row gap"><button class="primary" id="rn-ok" disabled>${esc(Z("确认改编码", "ยืนยันเปลี่ยนรหัส"))}</button><button data-mclose>${esc(Z("取消", "ยกเลิก"))}</button></div>`);
    const body = () => Object.assign({}, sel, { rule: o.rule, order: o.order });
    const load = async () => {
      const box = m.querySelector("#rn-res"), ok = m.querySelector("#rn-ok");
      try {
        const r = await api(U("/api/fleet/codes/renumber"), { json: body() });
        const rows = r.rows.slice().sort((a, b) => (b.status === "conflict") - (a.status === "conflict"));
        const shown = rows.slice(0, 300);
        const st = { same: Z("不变", "ไม่เปลี่ยน"), change: Z("改", "เปลี่ยน"), conflict: Z("冲突", "ชนกัน") };
        box.innerHTML = `<p class="small">${esc(Z(`共 ${r.rows.length} 台：${r.changed} 台会改，${r.same} 台不变`, `ทั้งหมด ${r.rows.length} เครื่อง: เปลี่ยน ${r.changed} ไม่เปลี่ยน ${r.same}`))}${r.conflicts ? ` · <b class="bad">${esc(Z(`${r.conflicts} 台冲突，不能改`, `${r.conflicts} เครื่องชนกัน แก้ไม่ได้`))}</b>` : ""}</p>
          <div class="tbl-scroll" style="max-height:45vh"><table class="grid small rn-tbl"><thead><tr><th>${esc(Z("旧编码", "รหัสเดิม"))}</th><th></th><th>${esc(Z("新编码", "รหัสใหม่"))}</th>
            <th>${esc(Z("机型", "รุ่น"))}</th><th>${esc(Z("分组 / 位置", "กลุ่ม / ตำแหน่ง"))}</th><th>${esc(Z("状态", "สถานะ"))}</th></tr></thead><tbody>
          ${shown.map((x) => `<tr class="rn-${x.status}"><td class="mono" data-notr>${esc(x.old)}</td><td>→</td><td class="mono" data-notr><b>${esc(x.new)}</b></td><td data-notr>${esc(x.name)}</td>
            <td data-notr>${esc(x.group)}${x.location ? " · " + esc(x.location) : ""}</td><td class="${x.status === "conflict" ? "bad" : ""}">${esc(st[x.status])}${x.problem ? ` <span class="small" data-notr>${esc(x.problem)}</span>` : ""}</td></tr>`).join("")}</tbody></table></div>
          ${rows.length > shown.length ? `<p class="small muted">${esc(Z(`只显示前 ${shown.length} 行（冲突排最前）`, `แสดง ${shown.length} แถวแรก (ที่ชนกันอยู่บนสุด)`))}</p>` : ""}`;
        ok.disabled = !r.changed || !!r.conflicts;
      } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; ok.disabled = true; }
    };
    m.querySelector("#rn-rule").onchange = (e) => { o.rule = e.target.value; load(); };
    m.querySelector("#rn-order").onchange = (e) => { o.order = e.target.value; load(); };
    m.querySelector("[data-rnrule]").onclick = async () => { MODAL.close(); await rulesDialog(); };
    m.querySelector("#rn-ok").onclick = (e) => busy(e.target, async () => {
      try {
        const r = await api(U("/api/fleet/codes/renumber"), { json: Object.assign(body(), { apply: true }) });
        MODAL.close();
        toast(Z(`已改 ${r.n} 台的编码`, `เปลี่ยนรหัส ${r.n} เครื่องแล้ว`));
        if (after) after(r);
        if (r.n && confirm(Z("编码改了，要重新打印这些打印机的标签吗？", "เปลี่ยนรหัสแล้ว ต้องการพิมพ์ป้ายของเครื่องเหล่านี้ใหม่หรือไม่?")))
          window.open(`/print/fleet-labels?lang=${LANG()}&ids=` + encodeURIComponent(r.ids.join(",")), "_blank");
      } catch (er) { toast(er.message, true); }
    });
    load();
  }

  // 改了分组 / 位置、编码里带着旧的：问一句（不自动改）
  function suggest(ids, after) {
    if (!ids || !ids.length) return;
    if (confirm(Z(`${ids.length} 台打印机的编码里带着旧的分组 / 位置。要按新位置重新编号吗？`, `รหัสของเครื่องพิมพ์ ${ids.length} เครื่องมีกลุ่ม / ตำแหน่งเดิมอยู่ ต้องการเปลี่ยนรหัสตามตำแหน่งใหม่หรือไม่?`)))
      renumber({ ids }, after);
  }

  window.FLEETCODES = { rulesDialog, renumber, suggest };
})();
