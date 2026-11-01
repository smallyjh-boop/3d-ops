"use strict";
// 仓库 → 货位页的三个页签（v2.52）：待上架（推荐货位，扫 / 选货位确认）、补货 · 移库（拣货位低了从备货区搬的任务）、提醒（空货位、呆滞、太分散）。
// 还有「移库」弹窗：从哪个货位（或待上架）→ 哪些物品、多少 → 到哪个货位。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const num = (v, d = 2) => (v == null || v === "" ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const itName = (it) => (TH() && it.name_th ? it.name_th : it.name_zh) || "";
  const can = (k) => !window.INV || !INV.can || INV.can(k);
  const L = () => window.INVLOC;
  const REASON = () => ({ same: Z("同物品已在", "สินค้าเดิมอยู่"), near: Z("同类附近空位", "ช่องว่างใกล้หมวดเดียวกัน"), empty: Z("空货位", "ช่องว่าง") });

  async function render(sub, box, map) {
    if (sub === "pending") return pending(box);
    if (sub === "tasks") return tasks(box);
    if (sub === "alerts") return alerts(box, map);
  }

  // ---------------- 待上架 ----------------
  async function pending(box) {
    const r = await api("/api/inv/wms/pending");
    const R = REASON();
    box.innerHTML = UX.card({ title: Z("待上架", "รอจัดเก็บ"), help: Z("到了货、还没放到货位上的数量。推荐顺序：这个物品已经在的货位（有空间）→ 同类物品附近的空位 → 其它空位；遵守容量、固定货位、不混放、尺寸。手机上：扫物品 → 扫货位 就放好了。",
      "จำนวนที่มาถึงแต่ยังไม่ได้วาง ลำดับแนะนำ: ช่องที่สินค้านี้อยู่แล้ว (มีที่ว่าง) → ช่องว่างใกล้สินค้าหมวดเดียวกัน → ช่องว่างอื่น ตามความจุ ช่องตายตัว ไม่ปน ขนาด บนมือถือ: สแกนสินค้า → สแกนตำแหน่ง"),
    right: can("inv.in") && r.items.length ? `<button class="primary" id="wp-all">${esc(Z("全部按推荐上架", "จัดเก็บทั้งหมดตามแนะนำ"))}</button>` : "",
    body: r.items.length ? `<div class="tbl-x"><table class="grid small"><thead><tr><th>${esc(Z("物品", "รายการ"))}</th><th>${esc(Z("待上架", "รอจัดเก็บ"))}</th><th>${esc(Z("推荐", "แนะนำ"))}</th>${can("inv.in") ? `<th>${esc(Z("放到", "วางที่"))}</th><th></th>` : ""}</tr></thead><tbody>
      ${r.items.map((x) => `<tr data-iid="${x.item.id}"><td data-notr><b class="mono">${esc(x.item.code)}</b> ${esc(itName(x.item))}</td><td class="nowrap"><b>${num(x.qty)}</b></td>
        <td class="small">${x.suggest.length ? x.suggest.map((p) => `<span class="nowrap"><b class="mono" data-notr>${esc(p.code)}</b>${p.qty ? ` ×${num(p.qty)}` : ""} <span class="muted">${esc(R[p.reason] || "")}</span></span>`).join("<br>")
          : `<span class="warn">${esc(Z("没有合适的空位（建货架 / 设库区放哪些分类）", "ไม่มีช่องที่เหมาะ (สร้างแร็ค / ตั้งหมวดของโซน)"))}</span>`}</td>
        ${can("inv.in") ? `<td class="nowrap"><input type="number" min="0" step="any" data-q value="${+(+(x.suggest[0] && x.suggest[0].qty ? x.suggest[0].qty : x.qty)).toFixed(3)}" class="loc-mq">
          <select data-to class="loc-to" data-notr>${L().locOpts(x.suggest[0] ? x.suggest[0].code : "", Z("选货位", "เลือกช่อง"))}</select></td>
          <td><button class="mini primary" data-put>${esc(Z("上架", "จัดเก็บ"))}</button></td>` : ""}</tr>`).join("")}</tbody></table></div>`
      : UX.empty(Z("没有待上架的东西 ✓", "ไม่มีของรอจัดเก็บ ✓")) });
    box.onclick = async (e) => {
      try {
        if (e.target.id === "wp-all") {
          const x = await api("/api/inv/wms/putaway", { json: { all: true } });
          toast(Z(`已上架 ${x.done.length} 笔`, `จัดเก็บแล้ว ${x.done.length} รายการ`)); return L().page();
        }
        if (e.target.dataset.put !== undefined) {
          const tr = e.target.closest("tr"), code = tr.querySelector("[data-to]").value;
          if (!code) return toast(Z("先选货位", "เลือกช่องก่อน"), true);
          await L().putaway(+tr.dataset.iid, code, tr.querySelector("[data-q]").value);
          return L().page();
        }
      } catch (er) { toast(er.message, true); }
    };
  }

  // ---------------- 补货 · 移库任务 ----------------
  async function tasks(box) {
    const r = await api("/api/inv/wms/tasks");
    const dry = r.suggest.filter((s) => !s.sources.length);
    box.innerHTML = UX.card({ title: Z("库内补货任务", "งานเติมสินค้าในคลัง"), help: Z("拣货区的货位设了「最低数量」，低于它就从备货区搬到拣货位（补到容量，没设容量补到最低数量的 2 倍）。任务也在右上角 🔔 待办里；手机「移库」页可以扫码做。",
      "ช่องหยิบที่ตั้ง「ขั้นต่ำ」ไว้ ต่ำกว่านั้นจะย้ายจากโซนสำรองมาเติม (เติมถึงความจุ ถ้าไม่ตั้งเติมเป็น 2 เท่าของขั้นต่ำ) งานอยู่ใน 🔔 ด้วย ทำบนมือถือหน้า「ย้าย」ได้"),
    right: can("inv.in") ? `<button id="wt-move">${esc(Z("↔ 移库", "↔ ย้ายตำแหน่ง"))}</button>` : "",
    body: (r.tasks.length ? `<div class="tbl-x"><table class="grid small"><thead><tr><th>${esc(Z("物品", "รายการ"))}</th><th>${esc(Z("从", "จาก"))}</th><th></th><th>${esc(Z("到", "ไป"))}</th><th>${esc(Z("搬多少", "จำนวน"))}</th><th>${esc(Z("那里还有", "ที่นั่นมี"))}</th><th></th></tr></thead><tbody>
      ${r.tasks.map((t) => `<tr data-tid="${t.id}"><td data-notr><b class="mono">${esc(t.code)}</b> ${esc(itName(t))}</td><td class="mono" data-notr><b>${esc(t.from_loc)}</b></td><td>→</td>
        <td class="mono" data-notr><b>${esc(t.to_loc)}</b></td><td><input type="number" min="0" step="any" data-q value="${+(+Math.min(t.qty, t.available || t.qty)).toFixed(3)}" class="loc-mq"></td>
        <td>${num(t.available)}</td><td class="nowrap">${can("inv.in") ? `<button class="mini primary" data-do>${esc(Z("搬好了", "ย้ายแล้ว"))}</button><button class="mini" data-cancel>${esc(Z("取消", "ยกเลิก"))}</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`
      : UX.empty(Z("没有补货任务 ✓（拣货位设了最低数量才会自动出任务）", "ไม่มีงานเติมสินค้า ✓ (ต้องตั้งขั้นต่ำของช่องหยิบก่อน)"))) +
      (dry.length ? `<div class="warnbox small" style="margin-top:10px"><b>${esc(Z("备货区也没货了：", "โซนสำรองก็ไม่มีแล้ว:"))}</b> ${dry.map((s) => `<span class="chip" data-notr>${esc(s.code)} @ ${esc(s.to)} ${num(s.now)}/${num(s.min)}</span>`).join(" ")}
        <span>${esc(Z("→ 采购或安排生产", "→ สั่งซื้อหรือวางแผนผลิต"))}</span></div>` : "") });
    box.onclick = async (e) => {
      try {
        if (e.target.id === "wt-move") return moveModal();
        const tr = e.target.closest("tr[data-tid]");
        if (!tr) return;
        if (e.target.dataset.do !== undefined) {
          await api(`/api/inv/wms/tasks/${tr.dataset.tid}/do`, { json: { qty: tr.querySelector("[data-q]").value } });
          toast(Z("已完成", "เสร็จแล้ว")); return L().page();
        }
        if (e.target.dataset.cancel !== undefined) {
          await api(`/api/inv/wms/tasks/${tr.dataset.tid}/cancel`, { json: {} }); return L().page();
        }
      } catch (er) { toast(er.message, true); }
    };
  }

  // ---------------- 提醒 ----------------
  async function alerts(box, map) {
    const a = map.alerts;
    const chips = (codes) => codes.slice(0, 80).map((c) => `<span class="chip mono" data-locgo-code="${esc(c)}" data-notr>${esc(c)}</span>`).join("") + (codes.length > 80 ? ` <span class="muted">…+${codes.length - 80}</span>` : "");
    box.innerHTML = `<div class="loc-alerts">` +
      UX.card({ title: Z(`很久没动的货位（${a.idle.length}）`, `ช่องที่ไม่เคลื่อนไหวนาน (${a.idle.length})`), help: Z(`有货、超过 ${a.idle_days} 天没有上架 / 移库 / 拣货的货位（呆滞库存）。天数在 设置 → 库存 → 货位 里改。`, `ช่องที่มีของแต่ไม่เคลื่อนไหวเกิน ${a.idle_days} วัน (สต็อกค้าง) แก้จำนวนวันได้ในตั้งค่า`),
        body: a.idle.length ? `<div class="chips">${a.idle.slice(0, 80).map((x) => `<span class="chip" data-locgo-code="${esc(x.code)}" data-notr><b class="mono">${esc(x.code)}</b> ${esc(Z(`${x.days} 天`, `${x.days} วัน`))}</span>`).join("")}</div>` : UX.empty(Z("没有 ✓", "ไม่มี ✓")) }) +
      UX.card({ title: Z(`放得太分散的物品（${a.spread.length}）`, `สินค้าที่กระจายหลายช่องเกินไป (${a.spread.length})`), help: Z(`一个物品放在超过 ${a.max_spread} 个货位，拣货要跑好几个地方：用「移库」并到一起。`, `สินค้าอยู่เกิน ${a.max_spread} ช่อง หยิบยาก ใช้「ย้าย」รวมกัน`),
        body: a.spread.length ? `<table class="grid small"><tbody>${a.spread.map((x) => `<tr><td data-notr><b class="mono">${esc(x.code)}</b> ${esc(itName(x))}</td><td><div class="chips">${chips(x.locations)}</div></td></tr>`).join("")}</tbody></table>` : UX.empty(Z("没有 ✓", "ไม่มี ✓")) }) +
      UX.card({ title: Z(`空货位（${a.empty.length}）`, `ช่องว่าง (${a.empty.length})`), help: Z("可以直接上架的空货位（按走路顺序）", "ช่องว่างที่วางของได้ (เรียงตามทางเดิน)"),
        body: a.empty.length ? `<div class="chips">${chips(a.empty)}</div>` : UX.empty(Z("没有空货位了：建新货架或者把东西并一并", "ไม่มีช่องว่างแล้ว: สร้างแร็คใหม่หรือรวมของ")) }) + "</div>";
    box.onclick = (e) => {
      const c = e.target.closest("[data-locgo-code]");
      if (c) api(`/api/inv/locations/find?code=${encodeURIComponent(c.dataset.locgoCode)}`).then((d) => d.location && L().detail(d.location.id, d)).catch((er) => toast(er.message, true));
    };
  }

  // ---------------- 移库弹窗：扫 / 选 原货位 → 物品和数量 → 目标货位 ----------------
  async function moveModal(from) {
    if (!L().list().length) await L().loadLocs();
    const m = MODAL.open(`<h3>${esc(Z("↔ 移库", "↔ ย้ายตำแหน่ง"))}</h3>
      <p class="small muted">${esc(Z("扫码枪也行：先扫原货位，勾要搬的物品和数量，再扫目标货位。可以一次搬几样。", "ใช้เครื่องสแกนได้: สแกนช่องต้นทาง เลือกสินค้าและจำนวน แล้วสแกนช่องปลายทาง ย้ายหลายอย่างพร้อมกันได้"))}</p>
      <div class="form4"><label>${esc(Z("原货位", "ช่องต้นทาง"))}<select id="mv-from" data-notr>${L().locOpts(from || "", Z("选货位", "เลือกช่อง"))}</select></label>
        <label>${esc(Z("目标货位", "ช่องปลายทาง"))}<select id="mv-to" data-notr>${L().locOpts("", Z("选货位", "เลือกช่อง"))}</select></label>
        <label>${esc(Z("扫码", "สแกน"))}<input id="mv-scan" placeholder="${esc(Z("扫货位条码", "สแกนป้ายตำแหน่ง"))}" autocomplete="off"></label></div>
      <div id="mv-items"></div>
      <div class="row gap" style="margin-top:8px"><button class="primary" id="mv-ok">${esc(Z("搬过去", "ย้าย"))}</button><button data-mclose>${esc(Z("关闭", "ปิด"))}</button></div>`);
    m.classList.add("wide");
    const fill = async () => {
      const code = m.querySelector("#mv-from").value, box = m.querySelector("#mv-items");
      if (!code) { box.innerHTML = ""; return; }
      const d = await api(`/api/inv/locations/find?code=${encodeURIComponent(code)}`);
      const its = (d.items || []).filter((x) => x.qty > 1e-9);
      box.innerHTML = its.length ? `<table class="grid small"><tbody>${its.map((x) => `<tr data-iid="${x.id}"><td><input type="checkbox" data-pick checked></td><td data-notr><b class="mono">${esc(x.code)}</b> ${esc(itName(x))}</td>
        <td>${esc(Z("有", "มี"))} ${num(x.qty)}</td><td><input type="number" min="0" step="any" data-q value="${+(+x.qty).toFixed(3)}" class="loc-mq"></td></tr>`).join("")}</tbody></table>`
        : `<p class="muted">${esc(Z("这个货位是空的", "ช่องนี้ว่าง"))}</p>`;
    };
    m.querySelector("#mv-from").onchange = () => fill().catch((e) => toast(e.message, true));
    m.querySelector("#mv-scan").addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      const v = e.target.value.trim().toUpperCase(); e.target.value = "";
      api(`/api/inv/locations/find?code=${encodeURIComponent(v)}`).then((d) => {
        if (d.type !== "location") return toast(Z("这不是货位条码", "นี่ไม่ใช่ป้ายตำแหน่ง"), true);
        const f = m.querySelector("#mv-from");
        if (!f.value) { f.value = d.location.code; fill(); } else m.querySelector("#mv-to").value = d.location.code;
      }).catch((er) => toast(er.message, true));
    });
    m.querySelector("#mv-ok").onclick = () => busy(m.querySelector("#mv-ok"), async () => {
      const from_ = m.querySelector("#mv-from").value, to = m.querySelector("#mv-to").value;
      const lines = [...m.querySelectorAll("#mv-items tr[data-iid]")].filter((tr) => tr.querySelector("[data-pick]").checked)
        .map((tr) => ({ item_id: +tr.dataset.iid, qty: tr.querySelector("[data-q]").value }));
      if (!from_ || !to) return toast(Z("选好原货位和目标货位", "เลือกช่องต้นทางและปลายทาง"), true);
      if (!lines.length) return toast(Z("勾要搬的物品", "เลือกสินค้าที่จะย้าย"), true);
      await L().move(from_, to, lines);
      MODAL.close(); L().page();
    });
    if (from) fill().catch(() => {});
  }

  window.INVWMS = { render, moveModal };
})();
