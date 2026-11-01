"use strict";
// 设置 → AI 与对接：「AI 接口」卡片（详细设置在 系统 → AI 接口）。v2.53
(function () {
  const Z = (zh, th) => (window.I18N && I18N.lang === "th" ? th : zh);
  async function settings(box) {
    let v = null;
    try { v = await api("/api/ai/settings"); } catch { /* 员工没有权限 */ }
    if (!v) { box.innerHTML = ""; return; }
    const keyed = v.providers.filter((p) => p.has_key);
    box.innerHTML = `<div class="card"><div class="row between wrap gap"><h3>🤖 ${Z("AI 接口（统一管理）", "การเชื่อมต่อ AI (จัดการรวม)")}</h3>
      <div class="row gap"><a class="btn" href="#" id="aic-go">${Z("打开 AI 接口", "เปิดการเชื่อมต่อ AI")}</a> <a class="btn" href="#" id="aiu-go">${Z("AI 用量", "การใช้ AI")}</a></div></div>
      <p class="small">${Z("下面的「AI」设置是默认文字 AI（旧设置，继续有效）。多家 AI 的密钥、每个任务用哪个 AI 和备用、出图（场景图）、费用上限都在「AI 接口」页。",
        "การตั้งค่า「AI」ด้านล่างคือ AI ข้อความเริ่มต้น (การตั้งค่าเดิม ยังใช้ได้) คีย์ของหลายผู้ให้บริการ AI ของแต่ละงานและตัวสำรอง การสร้างรูป (รูปฉาก) และเพดานค่าใช้จ่าย อยู่ในหน้า「การเชื่อมต่อ AI」")}</p>
      <p class="small">${Z("已填密钥", "ใส่คีย์แล้ว")}：${keyed.length ? keyed.map((p) => `<span class="pill">${UX.esc(Z(p.zh, p.th))}</span>`).join(" ") : `<span class="bad">${Z("还没有", "ยังไม่มี")}</span>`}
        · ${Z("本月费用", "ค่าใช้จ่ายเดือนนี้")} ${(+v.usage.month).toFixed(2)} ${Z("铢", "บาท")}</p></div>`;
    box.querySelector("#aic-go").onclick = (e) => { e.preventDefault(); goTab("ai_conf"); };
    box.querySelector("#aiu-go").onclick = (e) => { e.preventDefault(); goTab("ai_usage"); };
  }
  window.MODS = window.MODS || {};
  window.MODS.ai = Object.assign(window.MODS.ai || {}, { settings });
})();
