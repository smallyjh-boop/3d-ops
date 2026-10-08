"use strict";
// 商品模块：Lazada 类目模板库（设置 → 商品与上架）、上架状态小标签。v2.34 从 static/app.js 搬过来，代码没改。
// ---------------- 导出 ----------------
let TPL_SYNC_T = null;
async function renderTplSync() {
  const box = $("#tpl-sync"); if (!box) return;
  let st; try { st = await api("/api/templates/sync"); } catch { box.innerHTML = ""; return; }
  const r = st.running || {};
  box.innerHTML = !st.files ? "" : r.on
    ? `<span class="warn">⏳ 正在下载 Lazada 全部类目模板：${r.done} / ${r.total}</span>`
    : `${st.downloaded >= st.files ? '<span class="ok">✓ Lazada 全部类目模板已下载</span>' : `<span class="warn">Lazada 类目模板已下载 ${st.downloaded} / ${st.files} 个文件</span>`}
       · 有模板的类目 <b>${st.categories_with_template ?? "…"}</b> / ${st.categories_total}
       ${st.downloaded < st.files ? '<button class="mini primary" id="btn-tpl-sync">下载剩下的模板</button>' : '<button class="mini" id="btn-tpl-sync" data-force="1">重新下载全部</button>'}
       ${st.parsing ? '<span class="muted">（正在整理新下载的模板，第一次要几分钟）</span>' : ""}
       ${(st.errors || []).length ? `<div class="bad small">下载失败：${esc(st.errors.join("；"))}</div>` : ""}`;
  clearTimeout(TPL_SYNC_T);
  if (r.on || st.parsing) TPL_SYNC_T = setTimeout(renderTplSync, r.on ? 4000 : 10000);
}
document.addEventListener("click", async (e) => {
  if (e.target.id !== "btn-tpl-sync") return;
  if (e.target.dataset.force && !confirm("重新下载全部 Lazada 类目模板（约 160 个文件）？")) return;
  try { api("/api/templates/sync?async=1", { json: { force: !!e.target.dataset.force } }); setTimeout(renderTplSync, 1500); } catch (err) { toast(err.message, true); }
});
// v2.27：类目模板库搬到 设置 → 商品与上架
async function renderTplLib() {
  renderTplSync();
  await loadCats();
  const byFile = {};
  CATS.forEach((c) => (byFile[c.template] = byFile[c.template] || []).push(c));
  const files = Object.keys(byFile).sort();
  $("#tpl-count").textContent = CATS.length ? `（${CATS.length} 个类目 · ${files.length} 个模板文件）` : "";
  $("#btn-tpl-manage").textContent = TPL_MANAGE ? "完成管理" : "管理模板";
  $("#tpl-list").innerHTML = files.length ? files.map((f) => `
    <div class="tpl-file">
      <div class="row between"><b data-notr>📄 ${esc(f)}</b>
        <span><span class="muted small">${byFile[f].length} 个类目</span>
        ${TPL_MANAGE ? ` <button class="danger" data-deltpl="${esc(f)}">删除这个模板文件</button>` : ""}</span></div>
      <table class="grid"><tbody>${byFile[f].map((c) => `
        <tr><td><span data-notr>${esc(catName(c))}</span>${c.needs_license ? ' <span class="warn small">需TISI许可证</span>' : ""}<br><span class="muted small" data-notr>${esc(c.path)}</span></td>
        <td class="small" style="width:110px">${esc(c.cat_id)}</td></tr>`).join("")}</tbody></table>
    </div>`).join("") : '<p class="muted">还没有模板</p>';
  if (TPL_MANAGE) $("#tpl-details").open = true;
  if (!PRODUCT_LIST.length) { try { PRODUCT_LIST = await api("/api/products"); } catch { /* 忽略 */ } }
}
// 上架状态按平台自己的商品状态（Lazada：Pending QC → Active / QC Rejected / Inactive；Shopee：审核中 → 在售 / 违规 / 已下架）
const LST_ZH = { none: "未导出", pending: "待上传", failed: "上传失败", uploaded: "平台审核中", rejected: "审核不通过",
  live: "已上线", inactive: "平台已下架", update: "有修改待同步" };
const LST_PLAT = { lazada: { uploaded: "Pending QC", live: "Active", rejected: "QC Rejected", inactive: "Inactive" },
  shopee: { uploaded: "Reviewing", live: "Live", rejected: "Violation", inactive: "Unlisted" } };
const LST_RANK = { failed: 0, rejected: 1, update: 2, pending: 3, none: 4, uploaded: 5, inactive: 6, live: 7 };
const ON_PLAT = ["uploaded", "live", "rejected", "inactive", "update"];
function lstBadge(x, plat) {
  const st = (x && x.status) || "none";
  const pn = plat && (LST_PLAT[plat] || {})[st];
  const tip = [pn ? `${plat === "shopee" ? "Shopee" : "Lazada"}: ${pn}` : "", (x && x.note) || ""].filter(Boolean).join(" · ");
  return `<span class="lst lst-${st}" title="${esc(tip)}">${LST_ZH[st] || st}${(st === "failed" || st === "rejected") && x.note ? " ⓘ" : ""}</span>`;
}
let TPL_MANAGE = false;
let PRODUCT_LIST = [];
$("#btn-tpl-manage").addEventListener("click", () => { TPL_MANAGE = !TPL_MANAGE; renderTplLib(); });
$("#tpl-list").addEventListener("click", async (e) => {
  const t = e.target.dataset.deltpl; if (!t) return;
  const cats = CATS.filter((c) => c.template === t);
  const ids = new Set(cats.map((c) => c.id));
  const used = PRODUCT_LIST.filter((p) => ids.has(p.category_id));
  let msg = `确定删除模板文件「${t}」？\n\n里面的 ${cats.length} 个类目会一起移除。`;
  if (used.length) msg += `\n\n⚠ 有 ${used.length} 个产品正在使用这些类目：${used.slice(0, 8).map((p) => p.id).join("、")}${used.length > 8 ? "…" : ""}\n删除后这些产品需要重新选类目。`;
  msg += "\n\n（文件会移到 templates_lazada\\_deleted 文件夹，可以找回。）";
  if (!confirm(msg)) return;
  if (used.length && !confirm(`再次确认：删除后 ${used.length} 个产品将无法导出，直到重新选类目。继续删除？`)) return;
  try {
    await api(`/api/templates/${encodeURIComponent(t)}`, { method: "DELETE" });
    toast("模板已移到 _deleted 文件夹");
  } catch (err) { toast(err.message, true); }
  renderTplLib();
});
$("#tpl-input").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try {
    const r = await api("/api/templates", { method: "POST", body: fd });
    toast(`模板已添加，包含类目：${r.categories.join("、")}`);
    await renderTplLib();
  } catch (err) { toast(err.message, true); }
  e.target.value = "";
});
