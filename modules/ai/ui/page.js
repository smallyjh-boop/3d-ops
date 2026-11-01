"use strict";
// AI 接口（系统 → AI 接口）+ AI 用量（系统 → AI 用量）。v2.53
// 设置页：服务商（密钥只显示打码，留空 = 不改，填「-」= 清空）、测试连接、能力标签；按任务选 AI + 备用 + 上限；价格表；场景图模板。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const E = (s) => (window.UX ? UX.esc(s) : esc(s));
  const money = (v) => (v == null ? "—" : (+v).toFixed(+v >= 100 ? 0 : 2));
  const NEED = { text: ["文字", "ข้อความ"], vision: ["看图", "ดูรูป"], vision_opt: ["能看图更好", "ดูรูปได้จะดีกว่า"], image: ["出图", "สร้างรูป"] };
  let V = null;

  const capBadges = (caps) => (caps || []).map((c) => `<span class="pill" data-cap="${c}">${E(Z(...((V && V.cap_names[c]) || [c, c])))}</span>`).join(" ");
  const pname = (id) => { const p = V && V.providers.find((x) => x.id === id); return p ? Z(p.zh, p.th) : id; };

  function provOptions(cur, kind, allowEmpty) {
    const list = V.providers.filter((p) => (kind === "image" ? p.image_caps.includes("image") : p.caps.includes("text")));
    return (allowEmpty ? `<option value="">${Z("（不用）", "(ไม่ใช้)")}</option>` : "") +
      list.map((p) => `<option value="${p.id}" ${p.id === cur ? "selected" : ""}>${E(Z(p.zh, p.th))}${p.has_key ? "" : " ✗"}</option>`).join("");
  }

  // ---------------- 设置页 ----------------
  async function showConf() {
    const root = $("#aic-page");
    if (!root) return;
    try { V = await api("/api/ai/settings"); } catch (e) { root.innerHTML = `<div class="card"><p class="bad" data-notr>${E(e.message)}</p></div>`; return; }
    const keyed = V.providers.filter((p) => p.has_key).length;
    const fb = V.tasks.filter((t) => t.chain.length > 1).length;
    const tpl = await api("/api/scenes/templates").catch(() => null);
    root.innerHTML = UX.head(Z("AI 接口", "การเชื่อมต่อ AI"), `<button class="mini" id="aic-usage">📊 ${Z("AI 用量", "การใช้ AI")}</button> <button class="primary" id="aic-save">💾 ${Z("保存", "บันทึก")}</button>`,
      Z("系统里所有 AI 调用都按这里的设置：每个任务用哪家、哪个模型，出错 / 限流 / 超时自动换备用；每次调用记费用。密钥只存在 NAS 上，网页只显示打码。",
        "การเรียก AI ทั้งหมดในระบบใช้การตั้งค่านี้: แต่ละงานใช้ผู้ให้บริการและโมเดลไหน ถ้าผิดพลาด / ถูกจำกัด / หมดเวลา จะสลับไปตัวสำรองอัตโนมัติ ทุกครั้งบันทึกค่าใช้จ่าย คีย์เก็บบน NAS เท่านั้น หน้าเว็บแสดงแบบปิดบัง")) +
      UX.kpis([
        { label: Z("今天费用（铢）", "ค่าใช้จ่ายวันนี้ (บาท)"), value: money(V.usage.today), sub: Z(`${V.usage.today_n} 次`, `${V.usage.today_n} ครั้ง`), go: "tab:ai_usage" },
        { label: Z("本月费用（铢）", "ค่าใช้จ่ายเดือนนี้ (บาท)"), value: money(V.usage.month), sub: Z(`${V.usage.month_n} 次`, `${V.usage.month_n} ครั้ง`), go: "tab:ai_usage",
          tone: V.limits.monthly_thb && V.usage.month >= V.limits.monthly_thb ? "bad" : "" },
        { label: Z("已填密钥的服务商", "ผู้ให้บริการที่ใส่คีย์แล้ว"), value: `${keyed} / ${V.providers.length}`, tone: keyed ? "ok" : "bad" },
        { label: Z("设了备用的任务", "งานที่มีตัวสำรอง"), value: `${fb} / ${V.tasks.length}` },
      ]) +
      (V.migrated ? `<p class="small muted">${Z("已从旧设置接过来：默认文字 AI、场景图 AI、客服单独的模型、拍照识别次数（旧设置继续有效）。",
        "รับค่าจากการตั้งค่าเดิมแล้ว: AI ข้อความเริ่มต้น AI รูปฉาก โมเดลแชทแยก จำนวนครั้งถ่ายรูปจดจำ (การตั้งค่าเดิมยังใช้ได้)")}</p>` : "") +
      UX.card({ title: Z("默认 AI", "AI เริ่มต้น"), help: Z("任务没有单独设置时用这里的。看图任务：填了 Claude 的密钥时默认用 Claude。",
        "งานที่ไม่ได้ตั้งแยกจะใช้ค่านี้ งานดูรูป: ถ้าใส่คีย์ Claude ไว้ จะใช้ Claude เป็นค่าเริ่มต้น"), body: `<div class="row gap wrap">
        <label>${Z("文字 / 看图", "ข้อความ / ดูรูป")} <select id="aic-dt">${provOptions(V.default_text.p, "text")}</select></label>
        <label>${Z("模型", "โมเดล")} <input id="aic-dtm" value="${E(V.default_text.m)}" data-notr style="width:200px"></label>
        <label>${Z("出图", "สร้างรูป")} <select id="aic-di">${provOptions(V.default_image.p, "image")}</select></label>
        <label>${Z("模型", "โมเดล")} <input id="aic-dim" value="${E(V.default_image.m)}" placeholder="${Z("留空 = 默认", "ว่าง = ค่าเริ่มต้น")}" data-notr style="width:200px"></label></div>` }) +
      UX.card({ title: Z("服务商", "ผู้ให้บริการ"), help: Z("密钥：留空 = 不改；填一个减号「-」= 清空。能力标签不对时可以手动勾。",
        "คีย์: เว้นว่าง = ไม่เปลี่ยน ใส่เครื่องหมายลบ「-」= ล้าง ถ้าความสามารถไม่ถูกต้องติ๊กเองได้"), body: provTable() }) +
      UX.card({ title: Z("按任务选 AI", "เลือก AI ตามงาน"), help: Z("主选 + 最多两个备用：主选出错、限流、超时就自动用下一个。费用上限 0 = 不限；「硬上限」= 到了就暂停这个任务（不勾只提醒）。",
        "ตัวหลัก + ตัวสำรองไม่เกิน 2: ถ้าตัวหลักผิดพลาด ถูกจำกัด หรือหมดเวลา จะใช้ตัวถัดไปอัตโนมัติ เพดานค่าใช้จ่าย 0 = ไม่จำกัด「เพดานบังคับ」= ถึงแล้วหยุดงานนี้ (ไม่ติ๊ก = เตือนเท่านั้น)"), body: taskTable() }) +
      UX.card({ title: Z("总费用上限 · 价格表", "เพดานค่าใช้จ่ายรวม · ตารางราคา"), body: limitsAndPrices() }) +
      (tpl ? UX.card({ title: Z("场景图模板", "เทมเพลตรูปฉาก"), help: Z("场景图「按类目推荐」用：类目名 / 品名里有「关键词」里的词就推荐这个模板。提示词用英文效果更稳定。",
        "ใช้กับ「แนะนำตามหมวดหมู่」ของรูปฉาก: ถ้าชื่อหมวด / ชื่อสินค้ามีคำใน「คีย์เวิร์ด」จะแนะนำเทมเพลตนี้ พรอมต์ภาษาอังกฤษได้ผลนิ่งกว่า"),
        right: `<button class="mini" id="aic-tpl-add">＋ ${Z("加模板", "เพิ่มเทมเพลต")}</button> <button class="mini" id="aic-tpl-reset">${Z("恢复默认", "คืนค่าเริ่มต้น")}</button> <button class="mini primary" id="aic-tpl-save">${Z("保存模板", "บันทึกเทมเพลต")}</button>`,
        body: tplTable(tpl.templates) }) : "");
    bindConf(root, tpl);
  }

  function provTable() {
    return `<div class="tbl-scroll"><table class="grid small" id="aic-prov"><thead><tr><th>${Z("服务商", "ผู้ให้บริการ")}</th><th>${Z("能力", "ความสามารถ")}</th>
      <th>${Z("密钥", "คีย์")}</th><th>${Z("模型（留空 = 默认）", "โมเดล (ว่าง = ค่าเริ่มต้น)")}</th><th>${Z("接口地址（留空 = 官方）", "ที่อยู่ API (ว่าง = ทางการ)")}</th><th>${Z("启用", "เปิดใช้")}</th><th></th></tr></thead><tbody>
      ${V.providers.map((p) => {
        const caps = [...new Set([...(p.caps || []), ...(p.image_caps || [])])];
        const hasText = p.kinds.includes("text"), hasImg = p.kinds.includes("image");
        return `<tr data-pid="${p.id}"><td><b>${E(Z(p.zh, p.th))}</b>${p.legacy ? `<div class="muted">${Z("（用旧设置里的密钥）", "(ใช้คีย์จากการตั้งค่าเดิม)")}</div>` : ""}</td>
          <td>${capBadges(caps)}<details class="small"><summary>${Z("改能力", "แก้ความสามารถ")}</summary>${["text", "vision", "image", "edit"].map((c) =>
            `<label class="row gap"><input type="checkbox" data-capbox="${c}" ${(p.caps_override.length ? p.caps_override : caps).includes(c) ? "checked" : ""}> ${E(Z(...V.cap_names[c]))}</label>`).join("")}</details></td>
          <td><input type="password" data-k="api_key" autocomplete="new-password" placeholder="${E(p.has_key ? p.key_mask : Z("未填写", "ยังไม่ได้ใส่"))}" style="width:170px" data-notr>
            ${p.has_key ? `<div class="ok">✓ <span data-notr>${E(p.key_mask)}</span></div>` : ""}
            ${hasImg && hasText ? `<details><summary>${Z("出图单独的密钥", "คีย์แยกสำหรับสร้างรูป")}</summary><input type="password" data-k="image_key" autocomplete="new-password" placeholder="${E(p.has_image_key ? p.image_key_mask : Z("同上", "เหมือนด้านบน"))}" style="width:170px" data-notr>
              <input data-k="image_base" value="${E(p.image_base)}" placeholder="${Z("出图接口地址", "ที่อยู่ API สร้างรูป")}" style="width:170px" data-notr></details>` : ""}</td>
          <td>${hasText ? `<div>${Z("文字", "ข้อความ")} <input data-k="text_model" value="${E(p.text_model)}" placeholder="${E(p.def_text)}" style="width:170px" data-notr></div>` : ""}
            ${hasImg ? `<div>${Z("出图", "สร้างรูป")} <input data-k="image_model" value="${E(p.image_model)}" placeholder="${E(p.def_image)}" style="width:170px" data-notr></div>` : ""}
            ${p.def_edit ? `<div>${Z("改图", "แก้รูป")} <input data-k="edit_model" value="${E(p.edit_model)}" placeholder="${E(p.def_edit)}" style="width:170px" data-notr></div>` : ""}
            ${p.id === "openai" ? `<div>${Z("出图清晰度", "ความละเอียดรูป")} <select data-k="image_quality">${["", "low", "medium", "high"].map((q) => `<option value="${q}" ${q === p.image_quality ? "selected" : ""}>${q || Z("默认", "ค่าเริ่มต้น")}</option>`).join("")}</select></div>` : ""}</td>
          <td><input data-k="base_url" value="${E(p.base_url)}" placeholder="${E(p.base_default || Z("必填", "ต้องกรอก"))}" style="width:190px" data-notr></td>
          <td><input type="checkbox" data-k="enabled" ${p.enabled ? "checked" : ""}></td>
          <td class="nowrap">${hasText ? `<button class="mini" data-test="text">${Z("测试连接", "ทดสอบการเชื่อมต่อ")}</button>` : ""}
            ${hasImg ? `<button class="mini" data-test="image">${Z("测试出图密钥", "ทดสอบคีย์สร้างรูป")}</button>` : ""}<div class="small" data-res></div></td></tr>`;
      }).join("")}</tbody></table></div>`;
  }

  function taskTable() {
    const groups = V.group_order || Object.keys(V.groups);
    return groups.map((g) => `<h4>${E(Z(...V.groups[g]))}</h4><div class="tbl-scroll"><table class="grid small aic-tasks"><thead><tr><th>${Z("任务", "งาน")}</th><th>${Z("要求", "ต้องการ")}</th>
      <th>${Z("主选", "ตัวหลัก")}</th><th>${Z("备用 1", "สำรอง 1")}</th><th>${Z("备用 2", "สำรอง 2")}</th><th>${Z("每天上限（铢）", "เพดานต่อวัน (บาท)")}</th><th>${Z("每月上限（铢）", "เพดานต่อเดือน (บาท)")}</th><th>${Z("硬上限", "เพดานบังคับ")}</th></tr></thead><tbody>
      ${V.tasks.filter((t) => t.group === g).map((t) => {
        const kind = t.need === "image" ? "image" : "text";
        const ch = t.explicit ? t.chain : [];
        const cell = (i) => `<select data-ch="${i}">${i === 0 ? `<option value="">${Z("跟随默认", "ตามค่าเริ่มต้น")}${!t.explicit && t.chain[0] ? " · " + E(pname(t.chain[0].p)) : ""}</option>` : `<option value="">${Z("（不用）", "(ไม่ใช้)")}</option>`}${provOptions((ch[i] || {}).p, kind, false)}</select>
          <input data-chm="${i}" value="${E((ch[i] || {}).m || "")}" placeholder="${Z("模型（空=默认）", "โมเดล (ว่าง=ค่าเริ่มต้น)")}" style="width:130px" data-notr>`;
        return `<tr data-task="${t.id}"><td>${E(Z(t.zh, t.th))}</td><td>${E(Z(...NEED[t.need]))}</td><td>${cell(0)}</td><td>${cell(1)}</td><td>${cell(2)}</td>
          <td><input type="number" min="0" step="1" data-cap="daily_thb" value="${t.daily_thb || ""}" style="width:70px"></td>
          <td><input type="number" min="0" step="1" data-cap="monthly_thb" value="${t.monthly_thb || ""}" style="width:80px"></td>
          <td><input type="checkbox" data-cap="hard" ${t.hard ? "checked" : ""}></td></tr>`;
      }).join("")}</tbody></table></div>`).join("");
  }

  function limitsAndPrices() {
    const L = V.limits || {};
    const rows = Object.entries(V.prices);
    return `<div class="row gap wrap"><label>${Z("全部 AI 每天上限（铢，0 = 不限）", "เพดานรวมต่อวัน (บาท, 0 = ไม่จำกัด)")} <input type="number" id="aic-ld" value="${L.daily_thb || ""}" style="width:90px"></label>
      <label>${Z("每月上限（铢）", "เพดานต่อเดือน (บาท)")} <input type="number" id="aic-lm" value="${L.monthly_thb || ""}" style="width:90px"></label>
      <label class="row gap"><input type="checkbox" id="aic-lh" ${L.hard ? "checked" : ""}> ${Z("硬上限（到了就暂停所有 AI）", "เพดานบังคับ (ถึงแล้วหยุด AI ทั้งหมด)")}</label></div>
      <p class="small muted">${Z("价格只用来估算费用（泰铢）：每百万 token 输入 / 输出，每张图。按自己的账单改；某个模型单独的价格加一行「服务商:模型」。",
        "ราคาใช้ประมาณค่าใช้จ่าย (บาท): ต่อล้าน token ขาเข้า / ขาออก ต่อรูป แก้ตามบิลจริง ราคาเฉพาะโมเดลให้เพิ่มแถว「ผู้ให้บริการ:โมเดล」")}</p>
      <div class="tbl-scroll"><table class="grid small" id="aic-prices"><thead><tr><th>${Z("服务商 / 模型", "ผู้ให้บริการ / โมเดล")}</th><th>${Z("输入 / 百万 token", "ขาเข้า / ล้าน token")}</th><th>${Z("输出 / 百万 token", "ขาออก / ล้าน token")}</th><th>${Z("每张图", "ต่อรูป")}</th><th>${Z("每张改图", "ต่อรูปแก้")}</th></tr></thead><tbody>
      ${rows.map(([k, p]) => priceRow(k, p)).join("")}</tbody></table></div>
      <button class="mini" id="aic-price-add">＋ ${Z("加一行", "เพิ่มแถว")}</button>`;
  }
  const priceRow = (k, p) => `<tr><td><input data-pk value="${E(k)}" style="width:220px" data-notr></td>${["in", "out", "img", "edit"].map((f) =>
    `<td><input type="number" min="0" step="0.01" data-pf="${f}" value="${p && p[f] != null ? p[f] : ""}" style="width:80px"></td>`).join("")}</tr>`;

  function tplTable(list) {
    return `<div class="tbl-scroll"><table class="grid small" id="aic-tpl"><thead><tr><th>${Z("编号", "รหัส")}</th><th>${Z("中文名", "ชื่อภาษาจีน")}</th><th>${Z("泰文名", "ชื่อภาษาไทย")}</th>
      <th>${Z("场景提示词（英文）", "พรอมต์ฉาก (อังกฤษ)")}</th><th>${Z("类目关键词（逗号分隔）", "คีย์เวิร์ดหมวด (คั่นด้วยจุลภาค)")}</th><th></th></tr></thead><tbody>${list.map(tplRow).join("")}</tbody></table></div>`;
  }
  const tplRow = (t) => `<tr><td><input data-t="key" value="${E(t.key || "")}" style="width:100px" data-notr></td><td><input data-t="zh" value="${E(t.zh || "")}" style="width:110px" data-notr></td>
    <td><input data-t="th" value="${E(t.th || "")}" style="width:130px" data-notr></td><td><textarea data-t="prompt" rows="2" style="width:320px" data-notr>${E(t.prompt || "")}</textarea></td>
    <td><input data-t="cats" value="${E((t.cats || []).join(", "))}" style="width:180px" data-notr></td><td><button class="mini danger" data-tdel>✕</button></td></tr>`;

  function collect(root) {
    const providers = {};
    root.querySelectorAll("#aic-prov tr[data-pid]").forEach((tr) => {
      const d = {};
      tr.querySelectorAll("[data-k]").forEach((el) => { d[el.dataset.k] = el.type === "checkbox" ? el.checked : el.value.trim(); });
      const all = [...tr.querySelectorAll("[data-capbox]")];
      const on = all.filter((x) => x.checked).map((x) => x.dataset.capbox);
      const p = V.providers.find((x) => x.id === tr.dataset.pid);
      const auto = [...new Set([...(p.caps || []), ...(p.image_caps || [])])].sort().join();
      d.caps = on.sort().join() === auto && !p.caps_override.length ? [] : on;
      providers[tr.dataset.pid] = d;
    });
    const tasks = {};
    root.querySelectorAll("tr[data-task]").forEach((tr) => {
      const chain = [0, 1, 2].map((i) => ({ p: tr.querySelector(`[data-ch="${i}"]`).value, m: tr.querySelector(`[data-chm="${i}"]`).value.trim() })).filter((x) => x.p);
      tasks[tr.dataset.task] = { chain, daily_thb: +tr.querySelector('[data-cap="daily_thb"]').value || 0,
        monthly_thb: +tr.querySelector('[data-cap="monthly_thb"]').value || 0, hard: tr.querySelector('[data-cap="hard"]').checked };
    });
    const prices = {};
    root.querySelectorAll("#aic-prices tbody tr").forEach((tr) => {
      const k = tr.querySelector("[data-pk]").value.trim(); if (!k) return;
      const o = {}; tr.querySelectorAll("[data-pf]").forEach((el) => { if (el.value !== "") o[el.dataset.pf] = +el.value; }); prices[k] = o;
    });
    return { providers, tasks, prices, limits: { daily_thb: +$("#aic-ld").value || 0, monthly_thb: +$("#aic-lm").value || 0, hard: $("#aic-lh").checked },
      default_text: { p: $("#aic-dt").value, m: $("#aic-dtm").value.trim() }, default_image: { p: $("#aic-di").value, m: $("#aic-dim").value.trim() } };
  }

  function bindConf(root, tpl) {
    $("#aic-usage").onclick = () => goTab("ai_usage");
    $("#aic-save").onclick = (e) => busy(e.target, async () => {
      V = await api("/api/ai/settings", { json: collect(root) });
      toast(Z("已保存", "บันทึกแล้ว")); showConf();
    });
    root.querySelectorAll("[data-test]").forEach((b) => (b.onclick = () => busy(b, async () => {
      const tr = b.closest("tr"), out = tr.querySelector("[data-res]");
      const pending = [...tr.querySelectorAll('input[type="password"]')].some((x) => x.value.trim());
      if (pending) V = await api("/api/ai/settings", { json: { providers: collect(root).providers } });   // 先保存刚填的密钥
      const r = await api("/api/ai/test", { json: { provider: tr.dataset.pid, kind: b.dataset.test } });
      out.innerHTML = r.ok ? `<span class="ok">✓ ${Z("能用", "ใช้ได้")} · ${(r.ms / 1000).toFixed(1)}s</span>` : `<span class="bad" data-notr>${E(r.msg)}</span>`;
    })));
    $("#aic-price-add").onclick = () => $("#aic-prices tbody").insertAdjacentHTML("beforeend", priceRow("", {}));
    if (!tpl) return;
    const tb = $("#aic-tpl tbody");
    tb.onclick = (e) => { if (e.target.closest("[data-tdel]")) e.target.closest("tr").remove(); };
    $("#aic-tpl-add").onclick = () => tb.insertAdjacentHTML("beforeend", tplRow({}));
    $("#aic-tpl-reset").onclick = (e) => busy(e.target, async () => {
      if (!confirm(Z("恢复成默认的场景模板？", "คืนเทมเพลตรูปฉากเป็นค่าเริ่มต้น?"))) return;
      await api("/api/scenes/templates", { json: { reset: true } }); toast(Z("已恢复", "คืนค่าแล้ว")); showConf();
    });
    $("#aic-tpl-save").onclick = (e) => busy(e.target, async () => {
      const list = [...tb.querySelectorAll("tr")].map((tr) => { const o = {}; tr.querySelectorAll("[data-t]").forEach((el) => (o[el.dataset.t] = el.value.trim())); return o; })
        .filter((o) => o.key || o.prompt);
      await api("/api/scenes/templates", { json: { templates: list } }); toast(Z("模板已保存", "บันทึกเทมเพลตแล้ว")); showConf();
    });
  }

  // ---------------- 用量页 ----------------
  const UF = { days: 30, task: "", provider: "" };
  async function showUsage() {
    const root = $("#aiu-page");
    if (!root) return;
    let d;
    try { d = await api(`/api/ai/usage?days=${UF.days}&task=${encodeURIComponent(UF.task)}&provider=${encodeURIComponent(UF.provider)}`); }
    catch (e) { root.innerHTML = `<div class="card"><p class="bad" data-notr>${E(e.message)}</p></div>`; return; }
    const tn = (k) => (d.tasks[k] ? Z(d.tasks[k].zh, d.tasks[k].th) : k || "—");
    const pn = (k) => (d.providers[k] ? Z(d.providers[k].zh, d.providers[k].th) : k || "—");
    const T = d.total, err = T.n ? (T.n - T.ok) / T.n : 0;
    const filters = `<select id="aiu-days">${[7, 30, 90, 365].map((x) => `<option value="${x}" ${x === UF.days ? "selected" : ""}>${Z(`近 ${x} 天`, `${x} วันล่าสุด`)}</option>`).join("")}</select>
      <select id="aiu-task"><option value="">${Z("全部任务", "ทุกงาน")}</option>${Object.entries(d.tasks).map(([k, v]) => `<option value="${k}" ${k === UF.task ? "selected" : ""}>${E(Z(v.zh, v.th))}</option>`).join("")}</select>
      <select id="aiu-prov"><option value="">${Z("全部服务商", "ทุกผู้ให้บริการ")}</option>${Object.entries(d.providers).map(([k, v]) => `<option value="${k}" ${k === UF.provider ? "selected" : ""}>${E(Z(v.zh, v.th))}</option>`).join("")}</select>
      <button class="mini" id="aiu-conf">⚙ ${Z("AI 接口", "การเชื่อมต่อ AI")}</button>`;
    root.innerHTML = UX.head(Z("AI 用量", "การใช้ AI"), filters, Z("费用按「AI 接口」页的价格表估算（泰铢），和服务商账单可能有出入。",
      "ค่าใช้จ่ายประมาณจากตารางราคาในหน้า「การเชื่อมต่อ AI」(บาท) อาจต่างจากบิลจริง")) +
      UX.kpis([
        { label: Z("费用（铢）", "ค่าใช้จ่าย (บาท)"), value: money(T.cost), spark: d.by_day.map((x) => x.cost) },
        { label: Z("调用次数", "จำนวนครั้ง"), value: T.n, spark: d.by_day.map((x) => x.n) },
        { label: Z("出错率", "อัตราผิดพลาด"), value: Math.round(err * 100) + "%", tone: err > 0.2 ? "bad" : err > 0.05 ? "warn" : "ok", sub: Z(`${T.n - T.ok} 次出错`, `ผิดพลาด ${T.n - T.ok} ครั้ง`) },
        { label: Z("用了备用", "ใช้ตัวสำรอง"), value: T.fb, help: Z("主选失败、自动换成备用的次数", "จำนวนครั้งที่ตัวหลักล้มเหลวแล้วสลับไปตัวสำรอง") },
        { label: Z("token（输入 / 输出）", "token (เข้า / ออก)"), value: `${Math.round(T.tin / 1000)}k / ${Math.round(T.tout / 1000)}k` },
        { label: Z("出图张数", "จำนวนรูป"), value: T.img },
        { label: Z("平均用时", "เวลาเฉลี่ย"), value: (T.ms / 1000).toFixed(1) + "s" },
        { label: Z("今天 / 本月（铢）", "วันนี้ / เดือนนี้ (บาท)"), value: `${money(d.today.cost)} / ${money(d.month.cost)}`,
          tone: d.limits.monthly_thb && d.month.cost >= d.limits.monthly_thb ? "bad" : "" },
      ]) +
      UX.card({ title: Z("每天费用（铢）", "ค่าใช้จ่ายรายวัน (บาท)"), body: UX.columns(d.by_day.map((x) => ({ label: x.day, value: x.cost, text: money(x.cost) })), { from: d.by_day[0] && d.by_day[0].day, to: d.by_day.length && d.by_day[d.by_day.length - 1].day }) }) +
      `<div class="lanes two">` +
      UX.card({ title: Z("按任务（铢）", "ตามงาน (บาท)"), body: UX.bars(d.by_task.map((x) => ({ label: tn(x.task), value: x.cost, text: `${money(x.cost)} · ${x.n}${x.err ? " · ✗" + x.err : ""}`, tone: x.err ? "warn" : "" }))) }) +
      UX.card({ title: Z("按服务商 / 模型（铢）", "ตามผู้ให้บริการ / โมเดล (บาท)"), body: UX.bars(d.by_provider.map((x) => ({ label: `${pn(x.provider)} · ${x.model || ""}`, raw: true, value: x.cost, text: `${money(x.cost)} · ${x.n}`, tone: x.err ? "warn" : "" }))) }) +
      `</div>` +
      UX.card({ title: Z("明细（最近 50 次）", "รายละเอียด (50 ครั้งล่าสุด)"), body: d.recent.length ? `<div class="tbl-scroll"><table class="grid small"><thead><tr>
        <th>${Z("时间", "เวลา")}</th><th>${Z("任务", "งาน")}</th><th>${Z("服务商", "ผู้ให้บริการ")}</th><th>${Z("模型", "โมเดล")}</th><th>${Z("类型", "ประเภท")}</th><th>token</th><th>${Z("图", "รูป")}</th><th>${Z("费用（铢）", "ค่าใช้จ่าย (บาท)")}</th><th>${Z("用时", "เวลา")}</th><th>${Z("结果", "ผล")}</th></tr></thead><tbody>
        ${d.recent.slice(0, 50).map((r) => `<tr><td class="nowrap">${E(typeof fmtTime === "function" ? fmtTime(r.ts) : new Date(r.ts * 1000).toLocaleString())}</td><td>${E(tn(r.task))}</td><td>${E(pn(r.provider))}</td><td data-notr>${E(r.model)}</td>
          <td>${E(Z(...(NEED[r.kind] || { edit: ["改图", "แก้รูป"] }[r.kind] || [r.kind, r.kind])))}</td><td>${r.tokens_in || r.tokens_out ? `${r.tokens_in} / ${r.tokens_out}` : ""}</td><td>${r.images || ""}</td>
          <td>${money(r.cost_thb)}</td><td>${(r.ms / 1000).toFixed(1)}s</td>
          <td>${r.ok ? `<span class="ok">✓</span>${r.fallback ? ` <span class="pill">${Z("备用", "สำรอง")}</span>` : ""}` : `<span class="bad">✗</span> <span class="small" data-notr>${E(r.error)}</span>`}</td></tr>`).join("")}</tbody></table></div>` : UX.empty() });
    $("#aiu-days").onchange = (e) => { UF.days = +e.target.value; showUsage(); };
    $("#aiu-task").onchange = (e) => { UF.task = e.target.value; showUsage(); };
    $("#aiu-prov").onchange = (e) => { UF.provider = e.target.value; showUsage(); };
    $("#aiu-conf").onclick = () => goTab("ai_conf");
  }

  async function show(tab) {
    if (tab === "ai_usage") return showUsage();
    return showConf();
  }

  window.MODS = window.MODS || {};
  window.MODS.ai = Object.assign(window.MODS.ai || {}, { show });
})();
