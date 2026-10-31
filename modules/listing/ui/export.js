"use strict";
// 上架导出模块：导出上架表格页（选产品、分组、导出 Lazada / Shopee 表格、上架批次和状态）。v2.31 从 app.js 搬过来。
// 和 app.js 共用的：PRODUCT_LIST（产品列表）、lstBadge / LST_*（上架状态小标签，产品库也用）、api / esc / toast 等工具函数。
async function loadExport() {
  await loadCats();
  const nf = new Set(CATS.map((c) => c.template)).size;
  $("#exp-tplinfo").textContent = CATS.length ? `${CATS.length} 个类目 · ${nf} 个模板文件` : "还没有模板";
  const [list, g] = await Promise.all([api("/api/products"), api("/api/groups").catch(() => ({ groups: [] }))]);
  PRODUCT_LIST = list; EXP_GROUPS = g.groups || [];
  const cur = $("#exp-group").value;
  $("#exp-group").innerHTML = `<option value="">全部（${list.length}）</option><option value="none">未分组（${list.filter((p) => !(p.groups || []).length).length}）</option>` +
    EXP_GROUPS.map((x) => `<option value="${x.id}" data-notr>${esc(x.name)}（${x.count}）</option>`).join("");
  $("#exp-group").value = cur;
  const cur2 = $("#exp-addgroup").value;
  $("#exp-addgroup").innerHTML = '<option value="">（不加）</option>' + EXP_GROUPS.map((x) => `<option value="${x.id}" data-notr>${esc(x.name)}</option>`).join("");
  $("#exp-addgroup").value = cur2;
  renderExpList();
  loadBatches();
}
let EXP_GROUPS = [];
const EXP_SEL = new Set();

function expFiltered() {
  const gsel = $("#exp-group").value, st = $("#exp-status").value, plat = $("#exp-plat").value;
  const q = $("#exp-q").value.trim().toLowerCase();
  let rows = PRODUCT_LIST.filter((p) => {
    if (gsel === "none" && (p.groups || []).length) return false;
    if (gsel && gsel !== "none" && !(p.groups || []).map(String).includes(gsel)) return false;
    const ls = ((plat === "shopee" ? p.sp : p.lz) || {}).status || "none";
    if (st === "ready") { if (ON_PLAT.includes(ls) || (plat === "shopee" ? p.sp_errors : p.errors)) return false; }
    else if (st && ls !== st) return false;
    if (q && !`${p.id} ${p.name_zh} ${p.category} ${p.category_th}`.toLowerCase().includes(q)) return false;
    return true;
  });
  const by = $("#exp-sort").value;
  const key = {
    id: (p) => p.id, id_desc: (p) => p.id, name: (p) => p.name_zh || "", cat: (p) => (p.category || "") + p.id,
    status: (p) => LST_RANK[((plat === "shopee" ? p.sp : p.lz) || {}).status || "none"] + p.id, updated: (p) => -(p.updated_at || 0),
  }[by] || ((p) => p.id);
  rows = rows.sort((a, b) => { const x = key(a), y = key(b); return x < y ? -1 : x > y ? 1 : 0; });
  if (by === "id_desc") rows.reverse();
  return rows;
}
function renderExpList() {
  const rows = expFiltered();
  const plat = $("#exp-plat").value;
  const gname = Object.fromEntries(EXP_GROUPS.map((x) => [x.id, x.name]));
  const cnt = Object.fromEntries(Object.keys(LST_ZH).map((k) => [k, 0]));
  rows.forEach((p) => { const k = ((plat === "shopee" ? p.sp : p.lz) || {}).status || "none"; cnt[k] = (cnt[k] || 0) + 1; });
  $("#exp-sum").innerHTML = `显示 ${rows.length} 个 · ${plat === "shopee" ? "Shopee" : "Lazada"}：` +
    ["none", "pending", "failed", "uploaded", "rejected", "live", "inactive", "update"].map((k) => `<span>${LST_ZH[k]}</span> ${cnt[k]}`).join(" · ");      // v2.41：标签单独一段，泰文才翻得到
  const row = (p) => `<tr class="${EXP_SEL.has(p.id) ? "sel" : ""}"><td><input type="checkbox" class="exp-p" value="${esc(p.id)}" ${EXP_SEL.has(p.id) ? "checked" : ""}></td>
      <td class="mono" data-notr>${esc(p.id)}${p.exported ? " 🔒" : ""}</td><td><span data-notr>${esc(p.name_zh)}</span>${p.active === false ? ' <span class="pill bad-pill">已下架</span>' : ""}</td>
      <td>${p.category ? `<span data-notr>${esc(LANG === "th" ? p.category_th || p.category : p.category)}</span>` : '<span class="bad">未选</span>'}</td>
      <td>${(p.groups || []).map((g) => gname[g] ? `<span class="pill tag-pill" data-notr>${esc(gname[g])}</span>` : "").join(" ")}</td>
      <td>${statusBadge(p.errors, p.warnings)} ${lstBadge(p.lz, "lazada")}</td><td>${statusBadge(p.sp_errors, p.sp_warnings)} ${lstBadge(p.sp, "shopee")}</td></tr>`;
  const head = '<thead><tr><th></th><th>编码</th><th>名称</th><th>类目</th><th>分组</th><th>Lazada（检查 · 上架）</th><th>Shopee（检查 · 上架）</th></tr></thead>';
  if (!rows.length) { $("#exp-products").innerHTML = '<p class="muted">没有符合条件的产品</p>'; updExpN(); return; }
  let html = "";
  if ($("#exp-bygroup").checked && !$("#exp-group").value) {
    const secs = EXP_GROUPS.map((g) => ({ id: String(g.id), name: g.name, rows: [] })).concat([{ id: "none", name: "未分组", rows: [] }]);
    const byId = Object.fromEntries(secs.map((x) => [x.id, x]));
    rows.forEach((p) => { const g = (p.groups || []).map(String).find((x) => byId[x]); (byId[g] || byId.none).rows.push(p); });
    html = secs.filter((x) => x.rows.length).map((x) => `<details class="exp-sec" open><summary><label class="row gap" onclick="event.stopPropagation()"><input type="checkbox" data-secall="${x.id}"></label>
        <b data-notr>${esc(x.name)}</b> <span class="muted small">${x.rows.length} 个</span></summary>
      <table class="grid" data-sec="${x.id}">${head}<tbody>${x.rows.map(row).join("")}</tbody></table></details>`).join("");
    html += '<p class="muted small">一个产品在多个分组里时，只显示在第一个分组下。</p>';
  } else {
    html = `<label class="prod-check"><input type="checkbox" data-secall="all"> 全选列表里的产品</label><table class="grid" data-sec="all">${head}<tbody>${rows.map(row).join("")}</tbody></table>`;
  }
  $("#exp-products").innerHTML = html;
  updExpN();
}
function updExpN() { $("#exp-n").textContent = EXP_SEL.size; }
["#exp-group", "#exp-status", "#exp-sort", "#exp-plat", "#exp-bygroup"].forEach((k) => $(k).addEventListener("change", renderExpList));
{ let t = null; $("#exp-q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(renderExpList, 250); }); }
$("#exp-products").addEventListener("change", (e) => {
  const t = e.target;
  if (t.classList.contains("exp-p")) { t.checked ? EXP_SEL.add(t.value) : EXP_SEL.delete(t.value); t.closest("tr").classList.toggle("sel", t.checked); updExpN(); return; }
  if (t.dataset.secall) {
    const tbl = t.dataset.secall === "all" ? $('#exp-products table[data-sec="all"]') : $(`#exp-products table[data-sec="${t.dataset.secall}"]`);
    tbl.querySelectorAll(".exp-p").forEach((c) => { c.checked = t.checked; t.checked ? EXP_SEL.add(c.value) : EXP_SEL.delete(c.value); c.closest("tr").classList.toggle("sel", t.checked); });
    updExpN();
  }
});
$("#exp-newgroup").addEventListener("click", async () => {
  const n = prompt("新分组名称（例如：猫咪系列、10 月第 1 批、节日礼物）"); if (!n) return;
  try { await api("/api/groups", { json: { name: n } }); await loadExport(); const g = EXP_GROUPS.find((x) => x.name === n.trim()); if (g) $("#exp-addgroup").value = g.id; toast("已新建分组"); } catch (err) { toast(err.message, true); }
});
$("#exp-addgroup").addEventListener("change", async (e) => {
  const g = e.target.value; if (!g || !EXP_SEL.size) return;
  if (!confirm(`把已选的 ${EXP_SEL.size} 个产品加入这个分组？（导出时也会自动加入）`)) return;
  await api("/api/groups/assign", { json: { ids: [...EXP_SEL], group: +g, add: true } });
  toast("已加入分组"); loadExport();
});
$$(".exp-actions [data-mark]").forEach((b) => b.addEventListener("click", async () => {
  if (!EXP_SEL.size) return toast("先勾选产品", true);
  const plat = $("#exp-plat").value, st = b.dataset.mark;
  let note = null;
  if (st === "failed") { note = prompt("失败原因（可空），例如：类目属性缺失、图片不合格、价格被拦截"); if (note === null) return; }
  if (st === "rejected") { note = prompt("平台给的不通过原因（可空），例如：图片有水印、类目错误、违禁词"); if (note === null) return; }
  await api("/api/listing/status", { json: { ids: [...EXP_SEL], platform: plat, status: st, note } });
  toast(`已把 ${EXP_SEL.size} 个产品的 ${plat === "shopee" ? "Shopee" : "Lazada"} 状态改成「${LST_ZH[st]}」`);
  loadExport();
}));
async function loadBatches() {
  const r = await api(`/api/listing/batches?platform=${$("#bt-plat").value}`);
  $("#exp-batches").innerHTML = r.batches.map((b) => {
    const c = b.counts;
    // v2.41 复审：挪到别的批次的产品不算在这一批里（不然这一批永远不会「完成」）
    const done = (c.live || 0) + (c.inactive || 0) + (c.moved || 0) === b.items.length && b.items.length > (c.moved || 0);
    return `<details class="batch ${done ? "batch-done" : ""}" data-bid="${b.id}"><summary>
        <span class="pill ${b.platform === "shopee" ? "plat-shopee" : "plat-lazada"}">${b.platform === "shopee" ? "Shopee" : "Lazada"}</span>
        <b data-notr>${esc(b.name)}</b> <span class="muted small">${fmtTime(b.created_at)} · ${b.items.length} 个产品 · <span data-notr>${esc(b.username || "")}</span></span>
        <span class="small">${["pending", "failed", "uploaded", "rejected", "live", "inactive", "update"].filter((k) => c[k]).map((k) => `<span class="lst lst-${k}">${LST_ZH[k]} ${c[k]}</span>`).join("")}${c.moved ? `<span class="lst lst-none" title="后来在别的批次重新导出了"><span>移到别的批次</span> ${c.moved}</span>` : ""}</span></summary>
      <div class="batch-body">
        <div class="row gap wrap">${b.files.map((f) => `<a class="btn mini-btn" href="/api/export/${encodeURIComponent(f.file)}">⬇ ${esc(f.file)}</a>`).join("")}</div>
        <div class="row gap wrap" style="margin:8px 0">${c.pending ? '<button class="primary mini" data-bt="ok">⬆ 整批上传成功（待上传的改成「平台审核中」）</button>' : ""}
          ${c.pending || c.uploaded ? '<button class="primary mini" data-bt="live">✔ 整批审核通过（改成「已上线」）</button>' : ""}
          <button class="mini" data-bt="rename">改名</button><button class="mini danger" data-bt="del">删除批次记录</button></div>
        <table class="grid small"><tbody>${b.items.map((i) => `<tr><td class="mono" data-notr>${esc(i.id)}</td><td data-notr>${esc(i.name)}</td>
          <td>${lstBadge(i, b.platform)}${i.other_batch ? ' <span class="muted">（已在其他批次重新导出）</span>' : ""}${i.note ? ` <span class="muted" data-notr>${esc(i.note)}</span>` : ""}</td>
          <td class="nowrap">${i.other_batch ? "" : `<button class="mini" data-bti="uploaded" data-pid="${esc(i.id)}">审核中</button><button class="mini" data-bti="live" data-pid="${esc(i.id)}">✔ 上线</button><button class="mini" data-bti="rejected" data-pid="${esc(i.id)}">✗ 不通过</button><button class="mini" data-bti="failed" data-pid="${esc(i.id)}">上传失败</button>`}</td></tr>`).join("")}</tbody></table>
      </div></details>`;
  }).join("") || '<p class="muted small">还没有批次。导出表格后会自动生成。</p>';
}
$("#bt-plat").addEventListener("change", loadBatches);
$("#exp-batches").addEventListener("click", async (e) => {
  const t = e.target, box = t.closest("[data-bid]"); if (!box) return;
  const bid = box.dataset.bid;
  const plat = box.querySelector(".plat-shopee") ? "shopee" : "lazada";
  try {
    if (t.dataset.bt === "ok") { const r = await api(`/api/listing/batches/${bid}`, { json: { status: "uploaded" } }); toast(`${r.changed} 个产品已标记为「平台审核中」`); return loadExport(); }
    if (t.dataset.bt === "live") { const r = await api(`/api/listing/batches/${bid}`, { json: { status: "live" } }); toast(`${r.changed} 个产品已标记为「已上线」`); return loadExport(); }
    if (t.dataset.bt === "rename") { const n = prompt("批次名称"); if (!n) return; await api(`/api/listing/batches/${bid}`, { json: { name: n } }); return loadBatches(); }
    if (t.dataset.bt === "del") { if (!confirm("只删除这条批次记录（产品状态和导出的文件都不变）。继续？")) return; await api(`/api/listing/batches/${bid}`, { method: "DELETE" }); return loadBatches(); }
    if (t.dataset.bti) {
      let note = null;
      if (t.dataset.bti === "failed") { note = prompt("失败原因（可空）"); if (note === null) return; }
      if (t.dataset.bti === "rejected") { note = prompt("平台给的不通过原因（可空）"); if (note === null) return; }
      await api("/api/listing/status", { json: { ids: [t.dataset.pid], platform: plat, status: t.dataset.bti, note } });
      const open = [...$$("#exp-batches details[open]")].map((d) => d.dataset.bid);
      await loadExport();
      open.forEach((id) => { const d = $(`#exp-batches [data-bid="${id}"]`); if (d) d.open = true; });
    }
  } catch (err) { toast(err.message, true); }
});

async function doExport(e, url, note) {
  const ids = [...EXP_SEL];
  if (!ids.length) return toast("先勾选要导出的产品", true);
  const platform = url.includes("shopee") ? "shopee" : "lazada";
  const up = PRODUCT_LIST.filter((p) => ids.includes(p.id) && ["uploaded", "live", "rejected", "inactive"].includes(((platform === "shopee" ? p.sp : p.lz) || {}).status));
  if (up.length && !confirm(`其中 ${up.length} 个产品在 ${platform === "shopee" ? "Shopee" : "Lazada"} 上已经有了（${up.slice(0, 6).map((p) => p.id).join("、")}${up.length > 6 ? "…" : ""}）。\n再导出新建会生成重复商品（平台不允许重复铺货）。审核不通过的请在平台后台修改后重新提交。确定继续？`)) return;
  // 按分组分别导出：每个分组一个批次
  const parts = [];
  if ($("#exp-split").checked) {
    const gname = Object.fromEntries(EXP_GROUPS.map((x) => [String(x.id), x.name]));
    const by = {};
    ids.forEach((id) => { const p = PRODUCT_LIST.find((x) => x.id === id); const g = ((p && p.groups) || []).map(String).find((x) => gname[x]) || ""; (by[g] = by[g] || []).push(id); });
    Object.entries(by).forEach(([g, list]) => parts.push({ ids: list, name: `${$("#exp-batch").value.trim() || (platform === "shopee" ? "Shopee" : "Lazada")} · ${g ? gname[g] : "未分组"}`, group: g }));
  } else parts.push({ ids, name: $("#exp-batch").value.trim(), group: $("#exp-addgroup").value });
  await busy(e.target, async () => {
    const list = (arr, cls) => arr.length ? `<ul class="msgs">${arr.map((m) => `<li class="${cls}">${esc(m)}</li>`).join("")}</ul>` : "";
    let html = "";
    for (const part of parts) {
      const r = await api(url, { json: { product_ids: part.ids, force: $("#exp-force").checked, batch_name: part.name, group_id: part.group || "" } });
      html += (r.ok
        ? `<p class="ok">✅ ${r.batch ? `批次「<span data-notr>${esc(r.batch.name)}</span>」：` : ""}已生成 ${r.rows} 行（一行一个 SKU），${r.batch && r.batch.items ? r.batch.items.length : part.ids.length} 个产品已改成「待上传」：</p><ul>${r.files.map((f) =>
            `<li><a href="/api/export/${encodeURIComponent(f.file)}">下载 ${esc(f.file)}</a> <span class="muted small">${f.rows} 行 · ${f.categories.map(esc).join("、")}</span></li>`).join("")}</ul>`
        : `<p class="bad">${parts.length > 1 ? `「<span data-notr>${esc(part.name)}</span>」` : ""}有红色项未处理，没有生成文件：</p>`) + list(r.errors, "bad") + list(r.warnings, "warn");
    }
    $("#exp-result").innerHTML = html + `<p class="muted small">${note}上传成功后，到下面「3. 上架批次」点「整批上传成功」。</p>`;
    EXP_SEL.clear();
    await loadExport();
  });
}
$("#btn-export").addEventListener("click", (e) => doExport(e, "/api/export", "Lazada 卖家中心 → 批量管理 → 逐个上传这些文件。导出后这些产品的 SKU 已锁定。"));
$("#btn-export-sp").addEventListener("click", (e) => doExport(e, "/api/export/shopee", "Shopee 卖家中心 → 我的产品 → 批量功能 → 批量上传 → 上传文件。上传后 Shopee 可能要求补充品牌等属性（在 Shopee 后台补）。"));
// v2.41.2：直接推送到 Lazada（接口）：平台上还没有就新建，推过的就更新
$("#btn-lz-push").addEventListener("click", async (e) => {
  const ids = [...EXP_SEL];
  if (!ids.length) return toast("先勾选要推送的产品", true);
  const xls = PRODUCT_LIST.filter((p) => ids.includes(p.id) && ["uploaded", "live", "rejected", "inactive"].includes((p.lz || {}).status) && !p.lz_item);
  if (xls.length && !confirm(`其中 ${xls.length} 个产品已经用表格传到 Lazada 了（${xls.slice(0, 6).map((p) => p.id).join("、")}${xls.length > 6 ? "…" : ""}）。\n再推送会新建一个重复的商品。确定继续？`)) return;
  if (!confirm(`把 ${ids.length} 个产品推送到 Lazada？平台上还没有的会新建，推送过的会更新（标题、详情、属性、图片、价格、库存）。`)) return;
  await busy(e.target, async () => {
    const list = (arr, cls) => arr.length ? `<ul class="msgs">${arr.map((m) => `<li class="${cls}">${esc(m)}</li>`).join("")}</ul>` : "";
    const r = await api("/api/listing/lazada/push", { json: { product_ids: ids, force: $("#exp-force").checked } });
    let html = "";
    if (r.errors.length && !r.ok.length && !r.failed.length) html = `<p class="bad">有红色项未处理，没有推送：</p>`;
    if (r.ok.length) html += `<p class="ok">✅ 已推送 ${r.ok.length} 个产品（新建 ${r.ok.filter((x) => x.created).length}，更新 ${r.ok.filter((x) => !x.created).length}），状态改成「平台审核中」。Lazada 审核通过后在卖家中心能看到。</p>`;
    if (r.failed.length) html += `<p class="bad">${r.failed.length} 个推送失败（把下面的原因发给开发者）：</p>` + list(r.failed.map((x) => `${x.id}：${x.error}`), "bad");
    $("#exp-result").innerHTML = html + list(r.errors, "bad") + list(r.warnings, "warn");
    EXP_SEL.clear();
    await loadExport();
  });
});
