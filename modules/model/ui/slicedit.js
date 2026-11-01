"use strict";
// v2.56（T36）打印方案每一盘「✏ 在 Bambu Studio / OrcaSlicer 中编辑」：
// 桌面客户端 → 下载编辑文件、用软件打开（最大化）、保存后自动回传；页面顶部浮条（正在编辑哪一盘 · 最后同步 · 完成 / 放弃 / 左右分屏）
// 浏览器 → 下载编辑文件，在软件里改完拖回浮条上传；提示装桌面客户端以后自动回传
// 盘上显示主文件（哪个软件、什么时候保存的）和「需要确认」的原因
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const enc = encodeURIComponent;
  const APPN = { bambu: "Bambu Studio", orca: "OrcaSlicer" };
  const DL = { bambu: "https://bambulab.com/en/download/studio", orca: "https://github.com/SoftFever/OrcaSlicer/releases" };
  const DESK = () => (window.pywebview && window.pywebview.api && window.pywebview.api.edit_in_slicer ? window.pywebview.api : null);
  let ST = null;           // {pid, spec, plates: {id: 状态}, me}
  let JOB = null;          // 正在编辑：{sid, pid, spec, plate, k, app, download, upload, syncs, last_sync, desktop, timer, filename}

  const css = `
  .se-box{border-top:1px dashed #dfe5ee;margin-top:8px;padding-top:6px;font-size:13px}
  .se-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  .se-conf{background:#fff4e5;border:1px solid #f3c27a;border-radius:8px;padding:6px 8px;margin:6px 0}
  .se-conf li{margin:2px 0}
  #se-bar{position:fixed;top:0;left:0;right:0;z-index:1000;background:#0f3d75;color:#fff;padding:7px 14px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:14px;box-shadow:0 2px 8px rgba(0,0,0,.25)}
  #se-bar button,#se-bar .btn{padding:3px 10px}
  #se-bar .se-drop{border:1px dashed rgba(255,255,255,.6);border-radius:6px;padding:2px 8px}
  #se-bar a{color:#cfe4ff}
  `;
  if (!document.getElementById("se-css")) { const st = document.createElement("style"); st.id = "se-css"; st.textContent = css; document.head.appendChild(st); }

  function guessApp(pl) { return /bambu/i.test(pl.printer || "") ? "bambu" : "orca"; }
  function inner(S, pl, k) {
    const st = (ST && ST.pid === S.pid && ST.spec === S.spec && ST.plates[pl.id]) || {};
    const app = st.app || guessApp(pl), s = st.session, m = st.master;
    const mine = s && ST && s.user === ST.me;
    const conf = st.confirm || [];
    let h = `<div class="se-row">`;
    if (S.d && S.d.follow) h += `<span class="muted small">${Z("按主模型缩放的规格：请编辑主模型的打印方案", "แบบนี้ย่อขยายตามโมเดลหลัก: แก้ที่แผนของโมเดลหลัก")}</span>`;
    else if (s && !mine) h += `<span class="pill warn-pill">🔒 <span data-notr>${esc(s.display || s.user)}</span> ${Z("正在", "กำลังแก้ไขใน")} ${APPN[s.app]}${Z(" 里编辑", "")}（${fmtTime(s.started)}）</span>`;
    else h += `<button class="mini primary-lite" data-se="edit" data-plate="${pl.id}" data-k="${k + 1}" data-app="${app}" title="${Z("用切片软件本身摆盘、改方向、涂色、加支撑；保存后自动同步回这里", "ใช้โปรแกรมสไลซ์จัดถาด เปลี่ยนทิศ ลงสี เพิ่มซัพพอร์ต บันทึกแล้วซิงก์กลับอัตโนมัติ")}">✏ ${Z(`在 ${APPN[app]} 中编辑`, `แก้ไขใน ${APPN[app]}`)}</button>
      <button class="mini" data-se="edit-other" data-plate="${pl.id}" data-k="${k + 1}" data-app="${app === "bambu" ? "orca" : "bambu"}" title="${Z("用另一个软件编辑", "แก้ไขด้วยอีกโปรแกรม")}">${APPN[app === "bambu" ? "orca" : "bambu"]}</button>`;
    if (m) h += `<span class="small">📄 ${Z("主文件", "ไฟล์หลัก")}：<b>${APPN[m.app] || ""} <span data-notr>${esc(m.app_ver || "")}</span></b> ${Z("保存于", "บันทึกเมื่อ")} ${fmtTime(m.saved_at)}${m.by ? ` · <span data-notr>${esc(m.by)}</span>` : ""}${m.plate_no > 1 ? Z(`（文件里第 ${m.plate_no} 盘）`, ` (ถาดที่ ${m.plate_no} ในไฟล์)`) : ""}
      · <a href="/api/products/${enc(S.pid)}/print-plan/edit/master?spec=${enc(S.spec)}&plate=${enc(pl.id)}">⬇ ${Z("下载主文件", "ดาวน์โหลดไฟล์หลัก")}</a>
      <span class="muted">${Z(`（切片直接用它；历史 ${st.history || 1} 个）`, `(สไลซ์ใช้ไฟล์นี้; ประวัติ ${st.history || 1})`)}</span></span>`;
    h += `</div>`;
    if (conf.length) h += `<div class="se-conf"><b>⚠ ${Z("需要确认（切片软件里改过，确认前不能切片）", "ต้องยืนยัน (แก้ในโปรแกรมสไลซ์ ยืนยันก่อนจึงสไลซ์ได้)")}</b><ul>${conf.map((c) => `<li>${esc(TH() ? c.th : c.zh)}</li>`).join("")}</ul>
      <button class="mini" data-se="confirm" data-plate="${pl.id}">✓ ${Z("我看过了，确认没问题", "ตรวจแล้ว ยืนยันว่าไม่มีปัญหา")}</button></div>`;
    else if (st.confirmed) h += `<div class="small muted">✓ ${Z("已确认", "ยืนยันแล้ว")} · <span data-notr>${esc(st.confirmed.by || "")}</span> ${fmtTime(st.confirmed.at)}</div>`;
    return h;
  }
  function plateHtml(S, pl, k) { return `<div class="se-box" data-se-box="${pl.id}" data-se-k="${k}">${inner(S, pl, k)}</div>`; }

  async function refresh(S) {
    if (!S || !S.pid) return;
    const r = await api(`/api/products/${enc(S.pid)}/print-plan/edit/status?spec=${enc(S.spec)}`);
    ST = { pid: S.pid, spec: S.spec, me: r.me, plates: {} };
    r.plates.forEach((p) => { ST.plates[p.id] = p; });
    document.querySelectorAll("[data-se-box]").forEach((el) => {
      const pl = S.plan && S.plan.plates.find((x) => x.id === el.dataset.seBox);
      if (pl) el.innerHTML = inner(S, pl, +el.dataset.seK);
    });
    if (!JOB) {                         // 刷新了页面：我还有没结束的编辑 → 浮条接着显示
      const mine = r.plates.find((p) => p.session && p.session.user === r.me);
      if (mine) {
        const s = mine.session;
        JOB = { sid: s.id, pid: S.pid, spec: S.spec, plate: s.plate, k: r.plates.indexOf(mine) + 1, app: s.app, syncs: s.syncs || 0, last_sync: s.last_sync, desktop: false };
        const d = DESK();
        if (d) { try { const js = await d.edit_status(s.id); if (js && js.status === "editing") JOB.desktop = true; } catch { /* 忽略 */ } }
        bar(); if (JOB.desktop) poll();
      }
    }
  }

  // ---------------- 浮条 ----------------
  function bar() {
    let b = document.getElementById("se-bar");
    if (!JOB) { if (b) b.remove(); document.body.style.paddingTop = ""; return; }
    if (!b) { b = document.createElement("div"); b.id = "se-bar"; document.body.appendChild(b); }
    const pname = (typeof P !== "undefined" && P && P.id === JOB.pid) ? (P.name_zh || P.id) : JOB.pid;
    const last = JOB.last_sync ? `${Z("最后同步", "ซิงก์ล่าสุด")} ${fmtTime(JOB.last_sync)}` : Z("还没同步", "ยังไม่ได้ซิงก์");
    b.innerHTML = `<b>✏ ${Z(`正在 ${APPN[JOB.app]} 里编辑`, `กำลังแก้ไขใน ${APPN[JOB.app]}`)}</b>
      <span><span data-notr>${esc(pname)}${JOB.spec ? " · " + esc(JOB.spec) : ""}</span> · ${Z(`第 ${JOB.k} 盘`, `ถาดที่ ${JOB.k}`)}</span>
      ${JOB.desktop ? `<span>· ${Z("保存后自动同步", "บันทึกแล้วซิงก์อัตโนมัติ")}（${last}）</span>${JOB.error ? `<span class="bad" data-notr>${esc(JOB.error)}</span>` : ""}
        <button class="mini" data-se="split">⇆ ${Z("左右分屏", "แบ่งจอซ้ายขวา")}</button>`
      : `<span>· ${last}</span>${JOB.download ? `<a class="btn mini-btn" href="${esc(JOB.download)}" data-se-dl>⬇ ${Z("下载编辑文件", "ดาวน์โหลดไฟล์แก้ไข")}</a>` : ""}
        <label class="se-drop">⬆ ${Z("改完拖到这里 / 点这里上传", "แก้เสร็จลากมาวางที่นี่ / คลิกเพื่ออัปโหลด")} <input type="file" accept=".3mf" data-se-up hidden></label>
        <a href="/api/desktop/package">💻 ${Z("装桌面客户端以后自动回传", "ติดตั้งโปรแกรมเดสก์ท็อปแล้วจะส่งกลับอัตโนมัติ")}</a>`}
      <span style="margin-left:auto"></span>
      <button class="mini primary" data-se="finish">✓ ${Z("完成", "เสร็จ")}</button>
      <button class="mini danger" data-se="abandon">✕ ${Z("放弃", "ยกเลิก")}</button>`;
    document.body.style.paddingTop = b.offsetHeight + "px";
  }
  function showResult(r) {
    const conf = (r && r.confirm) || [];
    const ch = (r && r.changes) || [];
    toast(Z("已同步", "ซิงก์แล้ว") + (ch.length ? `：${ch.map((c) => TH() ? c.th : c.zh).join(Z("，", ", "))}` : "") +
      (conf.length ? ` · ⚠ ${Z(`${conf.length} 项需要确认`, `ต้องยืนยัน ${conf.length} รายการ`)}` : ""), !!conf.length, 6000);
  }
  async function reloadPlan() {
    if (window.PLAN && PLAN.state && PLAN.state.pid === (JOB || {}).pid) { if (!PLAN.dirty()) await PLAN.reload(); }
    else if (window.PLAN && PLAN.state) await refresh(PLAN.state);
  }
  function poll() {
    clearInterval(JOB && JOB.timer);
    if (!JOB || !JOB.desktop) return;
    JOB.timer = setInterval(async () => {
      const d = DESK(); if (!d || !JOB) return;
      let s; try { s = await d.edit_status(JOB.sid); } catch { return; }
      if (!s || s.status === "none") return;
      JOB.error = s.error || "";
      if (s.syncs > (JOB.syncs || 0)) { JOB.syncs = s.syncs; JOB.last_sync = s.last_sync || Date.now() / 1000; showResult(s.last_result); await reloadPlan(); }
      if (s.status === "ended") { toast(Z("编辑已经结束（别处完成 / 放弃 / 超时）", "การแก้ไขสิ้นสุดแล้ว"), true); end(); return; }
      bar();
    }, 2000);
  }
  function end() { if (JOB) clearInterval(JOB.timer); JOB = null; bar(); }

  async function start(btn) {
    const S = window.PLAN && PLAN.state;
    if (!S) return;
    if (PLAN.dirty()) { toast(Z("打印方案有改动还没保存：先保存再到切片软件里编辑", "แผนยังไม่ได้บันทึก: บันทึกก่อนแล้วค่อยแก้ในโปรแกรม"), true); return; }
    if (JOB) { toast(Z("已经在编辑另一盘：先点浮条上的「完成」或「放弃」", "กำลังแก้ไขถาดอื่นอยู่: กด「เสร็จ」หรือ「ยกเลิก」ก่อน"), true); return; }
    const app = btn.dataset.app, d = DESK();
    if (d) {                            // 桌面端：先看软件装了没有
      let sl = null; try { sl = await d.slicers(); } catch { sl = null; }
      if (sl && !(sl.found || {})[app]) { noApp(app, sl); return; }
    }
    let r;
    try { r = await api(`/api/products/${enc(S.pid)}/print-plan/edit/start`, { json: { spec: S.spec, plate_id: btn.dataset.plate, colour: S.colour || "", app } }); }
    catch (e) { toast(e.message, true); refresh(S).catch(() => {}); return; }
    JOB = { sid: r.session.id, pid: S.pid, spec: S.spec, plate: btn.dataset.plate, k: +btn.dataset.k, app: r.session.app, syncs: 0, last_sync: null,
      download: r.download, upload: r.upload, filename: r.filename, desktop: !!d };
    (r.session.notes || []).forEach((n) => toast(TH() ? n.th : n.zh, false, 6000));
    if (d) {
      toast(Z(`正在下载并用 ${APPN[JOB.app]} 打开…`, `กำลังดาวน์โหลดและเปิดด้วย ${APPN[JOB.app]}…`));
      let st;
      try { st = await d.edit_in_slicer({ sid: JOB.sid, app: JOB.app, download: r.download, upload: r.upload, filename: r.filename, folder: S.pid }); }
      catch (e) { st = { status: "error", error: e.message }; }
      if (st.status === "no_app") { JOB.desktop = false; JOB.download = null; noApp(JOB.app, { download: st.download_links }); }
      else if (st.status !== "editing") { JOB.desktop = false; toast(st.error || Z("打不开切片软件", "เปิดโปรแกรมสไลซ์ไม่ได้"), true); }
      else JOB.download = null;
    }
    bar(); poll(); refresh(S).catch(() => {});
  }
  function noApp(app, sl) {
    const links = (sl && sl.download) || DL;
    const m = $("#modal-in");
    m.innerHTML = `<h3>${Z(`这台电脑没有装 ${APPN[app]}`, `เครื่องนี้ยังไม่ได้ติดตั้ง ${APPN[app]}`)}</h3>
      <p class="small">${Z("装好以后再点「编辑」。也可以先用浏览器方式：下载编辑文件，在别的电脑的软件里改好再上传。", "ติดตั้งแล้วกด「แก้ไข」อีกครั้ง หรือดาวน์โหลดไฟล์ไปแก้ในเครื่องอื่นแล้วอัปโหลด")}</p>
      <div class="row gap wrap"><a class="btn primary" href="${esc(links.bambu || DL.bambu)}" target="_blank" rel="noopener">⬇ Bambu Studio</a>
        <a class="btn" href="${esc(links.orca || DL.orca)}" target="_blank" rel="noopener">⬇ OrcaSlicer</a><button data-mclose>${Z("关闭", "ปิด")}</button></div>`;
    $("#modal").classList.remove("hidden");
  }
  async function upload(file) {
    if (!JOB || !file) return;
    const fd = new FormData(); fd.append("file", file); fd.append("sid", JOB.sid);
    try {
      const r = await api(`/api/products/${enc(JOB.pid)}/print-plan/edit/upload?sid=${enc(JOB.sid)}`, { method: "POST", body: fd });
      JOB.syncs += 1; JOB.last_sync = Date.now() / 1000; showResult(r); bar(); await reloadPlan();
    } catch (e) { toast(e.message, true); }
  }

  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest && ev.target.closest("[data-se]"); if (!b) return;
    const a = b.dataset.se;
    if (a === "edit" || a === "edit-other") { ev.preventDefault(); await busy(b, () => start(b)); return; }
    if (a === "confirm") {
      const S = window.PLAN && PLAN.state; if (!S) return;
      try { await api(`/api/products/${enc(S.pid)}/print-plan/edit/confirm`, { json: { spec: S.spec, plate_id: b.dataset.plate } }); await refresh(S); }
      catch (e) { toast(e.message, true); }
      return;
    }
    if (!JOB) return;
    if (a === "split") { const d = DESK(); if (d) { const r = await d.split_screen(JOB.sid); toast(r.ok ? Z("已左右分屏", "แบ่งจอแล้ว") : (r.msg || Z("分屏失败", "แบ่งจอไม่สำเร็จ")), !r.ok); } return; }
    if (a === "finish" || a === "abandon") {
      if (a === "abandon" && !confirm(Z("放弃这次编辑？这一盘会恢复到开始编辑前（这次在软件里改的都不要了）", "ยกเลิกการแก้ไข? ถาดนี้จะกลับเป็นแบบก่อนแก้ไข"))) return;
      try { await api(`/api/products/${enc(JOB.pid)}/print-plan/edit/${a}`, { json: { sid: JOB.sid } }); }
      catch (e) { toast(e.message, true); }
      const d = DESK(); if (d && JOB.desktop) { try { await d.edit_stop(JOB.sid, a === "finish" ? "done" : "abandoned"); } catch { /* 忽略 */ } }
      end(); await reloadPlan();
    }
  });
  document.addEventListener("click", (ev) => { if (ev.target.closest && ev.target.closest("[data-se-dl]") && JOB) setTimeout(() => { JOB.download = null; bar(); }, 500); });
  document.addEventListener("change", (ev) => { if (ev.target.matches && ev.target.matches("[data-se-up]")) upload(ev.target.files[0]); });
  document.addEventListener("dragover", (ev) => { if (JOB && !JOB.desktop && ev.target.closest && ev.target.closest("#se-bar")) ev.preventDefault(); });
  document.addEventListener("drop", (ev) => {
    if (!JOB || JOB.desktop || !(ev.target.closest && ev.target.closest("#se-bar"))) return;
    ev.preventDefault(); ev.stopPropagation();
    const f = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0]; if (f) upload(f);
  }, true);

  window.SLICEDIT = { plateHtml, refresh, get job() { return JOB; } };
})();
