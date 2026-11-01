// 展示模型：组装视图（ES 模块，点「🧩 查看 / 编辑组装」时才加载 three.js）。
// v2.52：多零件模型每个零件可以用鼠标拖动 / 旋转（three.js TransformControls），拼成商品照片里组装好的样子；「AI 按图片组装」当初稿。
// v2.53：展示和打印完全分开 ——
//   左边「零件」：模型库里所有文件和文件里的组件，勾选 + 数量（例如 4 条腿），和主模型 / 打印方案无关；
//   「自动选零件」按文件 / 零件名和规格对应的模型选一套；「自动组合」按几何形状叠 / 插到一起（盖子盖上、头插上），给置信度，
//   置信度低时可以再用 AI（AI 的结果再按几何往下落到贴合）；「爆炸图」沿组装方向拉开（出「零件说明图」）；撤销 / 重做 Ctrl+Z / Ctrl+Y。
//   每个规格各有一份（③ 顶部切换规格）。服务器 modules/model/assembly.py + mating.py。坐标：Z 朝上，毫米。
import * as THREE from "three";
import { OrbitControls } from "/static/vendor/three/OrbitControls.js";
import { TransformControls } from "/static/vendor/three/TransformControls.js";

const TH = () => window.I18N && I18N.lang === "th";
const Z = (zh, th) => (TH() ? th : zh);
const D2R = Math.PI / 180, R2D = 180 / Math.PI;
const enc = encodeURIComponent;
const hexOf = (name) => { try { return (window.colorInfo ? colorInfo(name || "") : { hex: "#cfcfcf" }).hex || "#cfcfcf"; } catch { return "#cfcfcf"; } };
const gkey = (id, part) => `${id}/${part == null ? "all" : part}`;
const newUid = () => "u" + Math.random().toString(16).slice(2, 8);

let A = null;     // 当前打开的组装视图

const css = `
.asm-head{display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:space-between;margin-bottom:4px}
.asm-tools{display:flex;flex-wrap:wrap;gap:4px;align-items:center;margin:2px 0}
.asm-tools label{display:inline-flex;align-items:center;gap:3px;white-space:nowrap}
.asm-tools input[type=checkbox]{width:auto!important;margin:0}
.asm-side label{white-space:nowrap}
.asm-tools .on{background:#1565c0;color:#fff;border-color:#1565c0}
.asm-main{display:grid;grid-template-columns:230px minmax(0,1fr) 250px;gap:10px}
@media (max-width:1180px){.asm-main{grid-template-columns:1fr}}
.asm-3d{height:460px;border-radius:8px;overflow:hidden;background:#fff;border:1px solid #eee;position:relative}
.asm-side,.asm-pick{font-size:13px;max-height:460px;overflow:auto}
.asm-side table{width:100%;border-collapse:collapse}.asm-side td{padding:3px 4px;border-bottom:1px solid #f0f0f0;vertical-align:middle}
.asm-side tr.on{background:#eaf3ff}
.asm-side select{max-width:96px}
.asm-pick .pf{border:1px solid #eef1f5;border-radius:8px;padding:4px 6px;margin-bottom:6px}
.asm-pick .pf.main{border-color:#c9dcf5}
.asm-pick label{display:flex!important;flex-direction:row;gap:4px;align-items:center;margin:2px 0;font-weight:normal}
.asm-pick label.pp{padding-left:14px}
.asm-pick input[type=checkbox]{width:auto!important;margin:0;flex:none}
.asm-pick input[type=number]{width:48px!important;flex:none;padding:1px 3px;min-height:0;height:24px}
.asm-pick .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.asm-ai{background:#fff3cd;border:1px solid #f0c36d;color:#7a5200;border-radius:8px;padding:6px 10px;margin:6px 0;font-size:13px}
.asm-ok{background:#e3f5ea;border:1px solid #9fd6b3;color:#18794e;border-radius:8px;padding:6px 10px;margin:6px 0;font-size:13px}
.asm-info{background:#eef5ff;border:1px solid #c9dcf5;color:#0b4f94;border-radius:8px;padding:6px 10px;margin:6px 0;font-size:13px}
.asm-hint{position:absolute;left:8px;bottom:6px;font-size:12px;color:#667;background:rgba(255,255,255,.85);border-radius:6px;padding:2px 6px;pointer-events:none}
`;
if (!document.getElementById("asm-css")) { const st = document.createElement("style"); st.id = "asm-css"; st.textContent = css; document.head.appendChild(st); }

async function fetchMesh(pid, id, part) {
  const r = await fetch(`/api/products/${enc(pid)}/display/mesh/${enc(id)}/${part == null ? "all" : part}`, { credentials: "same-origin" });
  if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || r.statusText); }
  return new Float32Array(await r.arrayBuffer());
}

class Assembly {
  constructor(box, pid, opts) {
    this.box = box; this.pid = pid; this.opts = opts || {}; this.spec = this.opts.spec || "";
    this.meshes = []; this.geos = {}; this.sel = null; this.ai = false; this.auto = null; this.dirty = false; this.alive = true;
    this.undo = []; this.redo = []; this.exploded = null;
  }
  get readOnly() { return this.d && this.d.mode === "scale"; }
  async open() {
    this.d = await api(`/api/products/${enc(this.pid)}/display?spec=${enc(this.spec)}`);
    this.items = JSON.parse(JSON.stringify(this.d.items));
    const cols = (typeof P !== "undefined" && P ? [...new Set((P.variants || []).filter((v) => !this.spec || (v.opt2_zh || "").trim() === this.spec).map((v) => (v.opt1_zh || "").trim()).filter(Boolean))] : []);
    this.colours = cols; this.colour = cols[0] || "";
    const lab = this.spec ? `<span data-notr>${esc(this.spec)}</span>` : Z("主模型", "โมเดลหลัก");
    this.box.innerHTML = `
      <div class="asm-head"><b>🧩 ${Z("组装视图（展示用）", "มุมมองประกอบ (สำหรับแสดงผล)")} · ${lab} <span class="muted small" data-asm-count></span></b>
        <span class="asm-tools">
          <button class="mini" data-asm="undo" title="Ctrl+Z">↶ ${Z("撤销", "ย้อน")}</button>
          <button class="mini" data-asm="redo" title="Ctrl+Y">↷ ${Z("重做", "ทำซ้ำ")}</button>
          <button class="mini on" data-asm="translate" title="${Z("拖动箭头挪位置（快捷键 W）", "ลากลูกศรเพื่อย้าย (W)")}">✥ ${Z("移动", "ย้าย")}</button>
          <button class="mini" data-asm="rotate" title="${Z("拖动圆环旋转（快捷键 E）", "ลากวงแหวนเพื่อหมุน (E)")}">⟳ ${Z("旋转", "หมุน")}</button>
          <label class="small"><input type="checkbox" data-asm-snap checked> ${Z("吸附（1 mm / 15°）", "แม่เหล็ก (1 mm / 15°)")}</label>
          <button class="mini" data-asm="floor" title="${Z("选中的零件放到地面（最低点 z = 0）", "วางชิ้นที่เลือกลงพื้น")}">⤓ ${Z("放到地面", "วางลงพื้น")}</button>
          <button class="mini" data-asm="drop" title="${Z("所有零件往下落，贴到下面的零件 / 地面", "ทุกชิ้นตกลงจนแนบชิ้นด้านล่าง / พื้น")}">⬇ ${Z("落下贴合", "ตกลงให้แนบ")}</button>
          <button class="mini" data-asm="reset1">${Z("这个零件复原", "คืนค่าชิ้นนี้")}</button>
          <button class="mini" data-asm="resetall">${Z("全部复原", "คืนค่าทั้งหมด")}</button>
          <button class="mini" data-asm="close">${Z("收起", "ปิด")}</button></span></div>
      <div class="asm-tools">
          <button class="mini" data-asm="autosel" title="${Z("按文件 / 零件名、规格对应的模型选一套零件（数量按名字里的 x4 等）", "เลือกชิ้นงานอัตโนมัติตามชื่อไฟล์ / ชิ้นงาน และโมเดลของแบบ")}">🔍 ${Z("自动选零件", "เลือกชิ้นอัตโนมัติ")}</button>
          <button class="mini primary-lite" data-asm="auto" title="${Z("按形状把零件叠 / 插到一起（盖子盖上、头插上），给出置信度；置信度低时可以再用 AI", "ประกอบตามรูปทรง (ฝาปิด หัวเสียบ) พร้อมความมั่นใจ ถ้าต่ำใช้ AI ต่อได้")}">🧲 ${Z("自动组合", "ประกอบอัตโนมัติ")}</button>
          <button class="mini" data-asm="ai" title="${Z("把商品主图和每个零件几个角度的图交给 AI，让它给出每个零件的位置和角度（初稿），再按形状落下贴合", "ส่งรูปสินค้าและรูปแต่ละชิ้นให้ AI เสนอตำแหน่ง (ร่าง)")}">🤖 ${Z("AI 按图片组装", "AI ประกอบตามรูป")}</button>
          <button class="mini" data-asm="explode" title="${Z("零件沿组装方向拉开，看清每个零件（可以出「零件说明图」）", "แยกชิ้นตามแนวประกอบ (ใช้ทำรูปอธิบายชิ้นส่วน)")}">💥 ${Z("爆炸图", "มุมมองแยกชิ้น")}</button>
          <button class="mini" data-asm="shots" title="${Z("按组装好的样子、各零件的颜色，每个款式出一张商品图", "สร้างรูปสินค้าแบบประกอบแล้ว แบบละ 1 รูป")}">📷 ${Z("按组装出商品图", "สร้างรูปสินค้าแบบประกอบ")}</button>
          <button class="mini" data-asm="partsimg" title="${Z("爆炸图 + 零件编号，加到商品图里（告诉买家有哪些零件）", "รูปแยกชิ้น + หมายเลขชิ้น เพิ่มเป็นรูปสินค้า")}">🧾 ${Z("零件说明图", "รูปอธิบายชิ้นส่วน")}</button>
          <button class="mini" data-asm="default" title="${Z("这个规格回到默认（主模型 / 规格自己的模型；合并的打印盘自动拆回零件）", "กลับเป็นค่าเริ่มต้น")}">${Z("恢复默认", "ค่าเริ่มต้น")}</button>
          <button class="mini primary" data-asm="save">💾 ${Z("保存组装", "บันทึกการประกอบ")}</button></div>
      ${this.modeNote()}
      <div class="asm-ai hidden" data-asm-ai></div>
      <div class="asm-main">
        <div class="asm-pick" data-asm-pick></div>
        <div class="asm-3d"><div class="asm-hint">${Z("点零件选中 · 拖箭头 / 圆环 · 右键平移 · 滚轮缩放", "คลิกเลือกชิ้น · ลากลูกศร / วงแหวน · คลิกขวาเลื่อน · ล้อเมาส์ซูม")}</div></div>
        <div class="asm-side">
          ${this.colours.length ? `<div class="small">${Z("看哪个款式", "ดูแบบสีไหน")}：<select data-asm-col>${this.colours.map((c) => `<option value="${esc(c)}" data-notr>${esc((TH() && window.colorInfo && colorInfo(c).th) || c)}</option>`).join("")}</select></div>` : ""}
          <table><tbody data-asm-rows></tbody></table>
          <p class="small muted">${Z("组装只影响 3D 预览和商品图；打印时零件按「打印方案」平放在热床上。", "การประกอบมีผลแค่การแสดงผลและรูปสินค้า ตอนพิมพ์ชิ้นงานวางตาม「แผนการพิมพ์」")}</p>
          <div class="small" data-asm-st></div>
        </div></div>`;
    this.el3d = this.box.querySelector(".asm-3d");
    this._scene();
    this.renderPick();
    await this._build(this.d.parts);
    this._wire();
    this._fit();
  }
  modeNote() {
    const d = this.d;
    if (d.mode === "scale") return `<div class="asm-info">🔒 ${Z(`这个规格「按主模型缩放 ${d.scale}%」：展示跟着主模型（这里是放大 / 缩小后的样子）。要单独改，先在 ③ 顶部「取消缩放」。`, `แบบนี้ย่อ/ขยายจากโมเดลหลัก ${d.scale}%: การแสดงผลตามโมเดลหลัก ถ้าจะแก้แยกให้ยกเลิกการย่อ/ขยายก่อน`)}</div>`;
    if (d.mode === "merged") return `<div class="asm-info">ℹ ${Z("主模型是「合并成一套」的打印盘：展示自动拆回原来的零件（合并只影响打印，不影响展示）。可以在左边改零件，或点「自动组合」。", "โมเดลหลักเป็นถาดที่รวมไว้สำหรับพิมพ์: การแสดงผลแยกกลับเป็นชิ้นเดิมอัตโนมัติ (การรวมมีผลกับการพิมพ์เท่านั้น)")}</div>`;
    if (d.mode === "inherit") return `<div class="asm-info">ℹ ${Z("这个规格现在跟着主模型的展示；在这里改了保存后，这个规格用自己的展示（零件 / 数量 / 姿势）。", "แบบนี้ตอนนี้ใช้การแสดงผลของโมเดลหลัก ถ้าแก้และบันทึก แบบนี้จะมีการแสดงผลของตัวเอง")}</div>`;
    return "";
  }
  // ---------------- 左边：零件选择 ----------------
  renderPick() {
    const el = this.box.querySelector("[data-asm-pick]");
    const has = (id, part) => this.items.find((it) => it.id === id && (it.part == null ? null : +it.part) === part);
    const row = (e, part, name, size, sub) => {
      const it = has(e.id, part);
      return `<label class="${sub ? "pp" : ""}" data-pk="${esc(e.id)}|${part == null ? "" : part}"><input type="checkbox" data-pk-on ${it ? "checked" : ""} ${this.readOnly ? "disabled" : ""}>
        <span class="nm" data-notr title="${esc(name)}">${sub ? "└ " : ""}${esc(name)}</span>
        <input type="number" min="1" max="50" value="${it ? it.qty : 1}" data-pk-qty ${this.readOnly ? "disabled" : ""} title="${Z("几个（例如 4 条腿）", "กี่ชิ้น (เช่น ขา 4 ข้าง)")}"></label>
        ${!sub && size ? `<div class="muted small" data-notr style="padding-left:20px">${UX.sizeText(size, "×")}</div>` : ""}`;
    };
    el.innerHTML = `<div class="small"><b>${Z("零件（展示用）", "ชิ้นงาน (แสดงผล)")}</b> <span class="muted">${Z("勾选 + 数量", "เลือก + จำนวน")}</span></div>
      ${(this.d.library || []).map((e) => `<div class="pf ${e.main ? "main" : ""}">
        ${row(e, null, e.name, e.size, false)}
        ${e.merged ? `<div class="small muted">${Z("合并出来的打印盘（一般不用于展示）", "ถาดที่รวมไว้สำหรับพิมพ์ (ปกติไม่ใช้แสดงผล)")}</div>` : ""}
        ${e.main ? `<div class="small muted">${Z("主模型（打印用）", "โมเดลหลัก (สำหรับพิมพ์)")}</div>` : ""}
        ${(e.parts || []).map((p) => row(e, p.index, p.name || "#" + (p.index + 1), p.size, true)).join("")}</div>`).join("") || `<p class="muted small">${Z("模型库里没有文件", "ไม่มีไฟล์ในคลังโมเดล")}</p>`}`;
  }
  async _pickChange(lab) {
    if (this.readOnly) return;
    const [id, ps] = lab.dataset.pk.split("|"), part = ps === "" ? null : +ps;
    const on = lab.querySelector("[data-pk-on]").checked, qty = Math.max(1, Math.min(50, +lab.querySelector("[data-pk-qty]").value || 1));
    this.push();
    const i = this.items.findIndex((it) => it.id === id && (it.part == null ? null : +it.part) === part);
    if (on && i < 0) this.items.push({ uid: newUid(), id, part, qty });
    else if (!on && i >= 0) this.items.splice(i, 1);
    else if (on) this.items[i].qty = qty;
    if (!this.items.length) { toast(Z("至少选一个零件", "เลือกอย่างน้อย 1 ชิ้น"), true); this.undo.pop(); this.renderPick(); return; }
    if (on && i < 0) lab.querySelector("[data-pk-qty]").value = 1;
    this.dirty = true;
    await this._build(this.pose(), true);
  }
  // ---------------- 3D ----------------
  _scene() {
    const r = this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    r.outputColorSpace = THREE.SRGBColorSpace;
    this.el3d.appendChild(r.domElement);
    const s = this.scene = new THREE.Scene();
    s.background = new THREE.Color(0xffffff);
    const cam = this.camera = new THREE.PerspectiveCamera(35, 1, 0.5, 20000);
    cam.up.set(0, 0, 1);
    s.add(new THREE.HemisphereLight(0xffffff, 0xb0b0b0, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(200, -300, 400); s.add(sun);
    const fill = new THREE.DirectionalLight(0xffffff, 0.5); fill.position.set(-300, 200, 200); s.add(fill);
    this.grid = new THREE.GridHelper(400, 40, 0xc8ced6, 0xe6e9ee); this.grid.rotation.x = Math.PI / 2; s.add(this.grid);
    this.root = new THREE.Group(); s.add(this.root);
    if (this.readOnly && this.d.scale) this.root.scale.setScalar(this.d.scale / 100);
    this.orbit = new OrbitControls(cam, r.domElement);
    this.orbit.addEventListener("change", () => this.redraw());
    const tc = this.tc = new TransformControls(cam, r.domElement);
    tc.setSize(0.9);
    tc.addEventListener("dragging-changed", (e) => { this.orbit.enabled = !e.value; if (e.value) this.push(); else { this.dirty = true; this._status(); } });
    tc.addEventListener("change", () => this.redraw());
    s.add(tc.getHelper ? tc.getHelper() : tc);
    this._snap(true);
    this.ro = new ResizeObserver(() => this._resize()); this.ro.observe(this.el3d);
    this._resize();
  }
  _resize() {
    const w = this.el3d.clientWidth || 600, h = this.el3d.clientHeight || 460;
    this.renderer.setSize(w, h); this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); this.redraw();
  }
  redraw() {
    if (this._pend || !this.alive) return;
    this._pend = true;
    requestAnimationFrame(() => { this._pend = false; if (this.alive) this.renderer.render(this.scene, this.camera); });
  }
  _snap(on) { this.tc.setTranslationSnap(on ? 1 : null); this.tc.setRotationSnap(on ? 15 * D2R : null); }
  async _geo(id, part) {
    const k = gkey(id, part);
    if (!this.geos[k]) {
      const arr = await fetchMesh(this.pid, id, part);
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(arr, 3));
      g.computeBoundingBox();
      const c = g.boundingBox.getCenter(new THREE.Vector3()), sz = g.boundingBox.getSize(new THREE.Vector3());
      g.translate(-c.x, -c.y, -c.z);            // 零件外框中心 = 原点（pos 是外框中心的位置）
      g.computeVertexNormals();
      this.geos[k] = { g, center: [c.x, c.y, c.z], size: [sz.x, sz.y, sz.z] };
    }
    return this.geos[k];
  }
  instances() {
    const out = [];
    for (const it of this.items) for (let k = 0; k < Math.max(1, +it.qty || 1); k++) out.push({ key: `${it.uid}.${k}`, it, k });
    return out;
  }
  // 按 this.items 重建零件（keep：保留已有的姿势；新的零件放在右边）
  async _build(poses, keep) {
    const st = this.box.querySelector("[data-asm-st]");
    const old = Object.fromEntries((poses || []).map((x) => [x.key, x]));
    this.select(null);
    this.meshes.forEach((m) => { this.root.remove(m); m.material.dispose(); });
    this.meshes = [];
    const inst = this.instances();
    const bb = new THREE.Box3();
    let i = 0;
    const fresh = [];
    for (const x of inst) {
      if (st) st.textContent = Z(`读取零件 ${++i} / ${inst.length}…`, `กำลังโหลดชิ้นที่ ${i} / ${inst.length}…`);
      const g = await this._geo(x.it.id, x.it.part);
      const q = old[x.key];
      const m = new THREE.Mesh(g.g, new THREE.MeshStandardMaterial({ color: hexOf((q && q.colour) || this.colour), roughness: 0.55, metalness: 0.02 }));
      m.userData = { key: x.key, id: x.it.id, part: x.it.part, center: g.center, size: g.size, colour: (q && q.colour) || "", hidden: !!(q && q.hidden), name: this._name(x.it) + (x.it.qty > 1 ? ` #${x.k + 1}` : "") };
      if (q && q.pos) { this._pose(m, q.pos, q.rot || [0, 0, 0]); m.updateMatrixWorld(); bb.expandByObject(m); } else fresh.push(m);
      m.visible = !m.userData.hidden;
      this.root.add(m); this.meshes.push(m);
    }
    // 没有姿势的零件：排在右边（底面放地上）
    let x0 = bb.isEmpty() ? 0 : bb.max.x + 5;
    for (const m of fresh) {
      const s = m.userData.size;
      if (!keep && bb.isEmpty() && fresh.length === inst.length) { this._pose(m, m.userData.center, [0, 0, 0]); continue; }
      this._pose(m, [x0 + s[0] / 2, 0, s[2] / 2], [0, 0, 0]); x0 += s[0] + 5;
    }
    this.renderRows(); this._status(); this.redraw();
  }
  _name(it) {
    const e = (this.d.library || []).find((x) => x.id === it.id);
    if (!e) return it.id;
    if (it.part == null) return e.name;
    const p = (e.parts || []).find((x) => x.index === +it.part);
    return p ? p.name : `${e.name} #${+it.part + 1}`;
  }
  renderRows() {
    const tb = this.box.querySelector("[data-asm-rows]");
    const cn = Object.keys(window.COLORS || {});
    tb.innerHTML = this.meshes.map((m, i) => `<tr data-k="${esc(m.userData.key)}"><td><b>${i + 1}</b></td>
      <td><span data-notr title="${esc(m.userData.name)}">${esc(String(m.userData.name).slice(0, 18))}</span><div class="muted" data-notr>${UX.sizeText(m.userData.size, "×")}</div></td>
      <td><select data-asm-pc title="${Z("零件颜色（展示用）", "สีของชิ้น (แสดงผล)")}"><option value="">${Z("款式色", "สีของแบบ")}</option>${cn.map((c) => `<option value="${esc(c)}" ${c === m.userData.colour ? "selected" : ""} data-notr>${esc((TH() && (window.COLORS[c] || {}).th) || c)}</option>`).join("")}</select></td>
      <td><label title="${Z("不显示（例如螺丝、备用件）", "ไม่แสดง")}"><input type="checkbox" data-asm-hide ${m.userData.hidden ? "checked" : ""}>${Z("隐藏", "ซ่อน")}</label></td></tr>`).join("");
    const c = this.box.querySelector("[data-asm-count]");
    if (c) c.textContent = Z(`${this.meshes.length} 个零件`, `${this.meshes.length} ชิ้น`);
  }
  _pose(m, pos, rot) {
    m.position.set(+pos[0] || 0, +pos[1] || 0, +pos[2] || 0);
    m.rotation.set((+rot[0] || 0) * D2R, (+rot[1] || 0) * D2R, (+rot[2] || 0) * D2R, "XYZ");
  }
  _status() {
    const st = this.box.querySelector("[data-asm-st]");
    if (!st) return;
    st.innerHTML = this.dirty ? `<b class="warn">${Z("有改动，还没保存", "มีการแก้ไข ยังไม่ได้บันทึก")}</b>`
      : this.d.has_pose ? `<span class="ok">${Z("已保存组装", "บันทึกการประกอบแล้ว")}${this.d.ai ? Z("（AI 初稿 + 人工调整）", " (ร่าง AI + ปรับเอง)") : ""}</span>` : `<span class="muted">${Z("还没保存过：同一个文件的组件用文件里原来的位置，其他排成一排", "ยังไม่เคยบันทึก: ชิ้นจากไฟล์เดียวกันใช้ตำแหน่งเดิม ชิ้นอื่นเรียงเป็นแถว")}</span>`;
    this.box.querySelectorAll("tr[data-k]").forEach((tr) => tr.classList.toggle("on", !!this.sel && tr.dataset.k === this.sel.userData.key));
  }
  _fit() {
    const b = new THREE.Box3();
    this.meshes.filter((m) => m.visible).forEach((m) => b.expandByObject(m));
    if (b.isEmpty()) return;
    const c = b.getCenter(new THREE.Vector3()), r = b.getSize(new THREE.Vector3()).length() / 2 || 50;
    const dist = r / Math.sin((this.camera.fov * D2R) / 2) * 1.1;
    this.camera.position.set(c.x + dist * 0.6, c.y - dist * 0.75, c.z + dist * 0.45);
    this.orbit.target.copy(c); this.orbit.update();
    this.grid.scale.setScalar(Math.max(0.3, r / 100)); this.grid.position.set(c.x, c.y, Math.min(0, b.min.z));
    this.redraw();
  }
  select(m) {
    if (m && (this.exploded || this.readOnly)) m = null;           // 爆炸图 / 缩放的规格：只看
    this.sel = m || null;
    if (m) this.tc.attach(m); else this.tc.detach();
    this._status(); this.redraw();
  }
  // ---------------- 撤销 / 重做 ----------------
  snap() { return JSON.stringify({ items: this.items, poses: this.pose() }); }
  push() { const s = this.snap(); if (this.undo[this.undo.length - 1] !== s) { this.undo.push(s); if (this.undo.length > 80) this.undo.shift(); } this.redo = []; }
  async undoRedo(back) {
    const from = back ? this.undo : this.redo, to = back ? this.redo : this.undo;
    if (!from.length) { toast(back ? Z("没有可以撤销的", "ไม่มีอะไรให้ย้อน") : Z("没有可以重做的", "ไม่มีอะไรให้ทำซ้ำ")); return; }
    if (this.exploded) this.unexplode();
    to.push(this.snap());
    const s = JSON.parse(from.pop());
    const sameItems = JSON.stringify(s.items) === JSON.stringify(this.items);
    this.items = s.items; this.dirty = true;
    if (sameItems) { s.poses.forEach((q) => { const m = this.meshes.find((x) => x.userData.key === q.key); if (m) { this._pose(m, q.pos, q.rot); m.userData.colour = q.colour; m.userData.hidden = q.hidden; m.visible = !q.hidden; } }); this._recolour(); this.renderRows(); this._status(); }
    else { this.renderPick(); await this._build(s.poses); }
  }
  _wire() {
    const dom = this.renderer.domElement;
    let down = null;
    dom.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
    dom.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || this.tc.dragging) { down = null; return; }
      down = null;
      const r = dom.getBoundingClientRect();
      const ray = new THREE.Raycaster();
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), this.camera);
      const hit = ray.intersectObjects(this.meshes.filter((m) => m.visible), false)[0];
      if (hit) this.select(hit.object); else if (!this.tc.axis) this.select(null);
    });
    this.box.tabIndex = -1;
    this.box.addEventListener("pointerdown", () => { this.focused = true; });
    this.onDocDown = (e) => { this.focused = this.box.contains(e.target); };
    document.addEventListener("pointerdown", this.onDocDown, true);
    this.onKey = (e) => {
      if (!this.alive || !this.focused) return;
      if (e.target.closest && e.target.closest("input,select,textarea")) return;
      const k = (e.key || "").toLowerCase();
      if ((e.ctrlKey || e.metaKey) && (k === "z" || k === "y")) { e.preventDefault(); this.undoRedo(k === "z" && !e.shiftKey); return; }
      if (k === "w") this._mode("translate");
      else if (k === "e") this._mode("rotate");
      else if (e.key === "Escape") this.select(null);
    };
    window.addEventListener("keydown", this.onKey);
    this.box.addEventListener("click", (e) => this._click(e));
    this.box.addEventListener("change", (e) => this._change(e));
  }
  _mode(m) {
    this.tc.setMode(m);
    this.box.querySelectorAll("[data-asm=translate],[data-asm=rotate]").forEach((b) => b.classList.toggle("on", b.dataset.asm === m));
  }
  _apply(parts) {
    for (const x of parts || []) { const m = this.meshes.find((y) => y.userData.key === x.key) || (x.index != null ? this.meshes[x.index] : null); if (m) this._pose(m, x.pos, x.rot); }
  }
  _banner(cls, html) {
    const box = this.box.querySelector("[data-asm-ai]");
    box.className = `${cls}`; box.dataset.asmAi = ""; box.innerHTML = html;
  }
  async _click(e) {
    const tr = e.target.closest("tr[data-k]");
    if (tr && !e.target.closest("select,input,label")) { const m = this.meshes.find((x) => x.userData.key === tr.dataset.k); if (m && m.visible) this.select(m); return; }
    const b = e.target.closest("[data-asm]"); if (!b) return;
    const a = b.dataset.asm;
    const ro = ["floor", "drop", "reset1", "resetall", "autosel", "auto", "ai", "save", "default"];
    try {
      if (a === "translate" || a === "rotate") { this._mode(a); return; }
      if (a === "close") { close(); return; }
      if (a === "undo" || a === "redo") { await this.undoRedo(a === "undo"); return; }
      if (a === "explode") { await busy(b, () => this.toggleExplode(b)); return; }
      if (a === "shots") { await busy(b, () => this.shots()); return; }
      if (a === "partsimg") { await busy(b, () => this.partsImage()); return; }
      if (this.readOnly && ro.includes(a)) { toast(Z("按主模型缩放的规格不能单独改（先取消缩放）", "แบบที่ย่อ/ขยายจากโมเดลหลักแก้แยกไม่ได้"), true); return; }
      if (this.exploded) this.unexplode();
      if (a === "floor") {
        if (!this.sel) { toast(Z("先点一下要放的零件", "คลิกเลือกชิ้นก่อน"), true); return; }
        this.push(); const bb = new THREE.Box3().setFromObject(this.sel); this.sel.position.z -= bb.min.z; this.dirty = true; this._status(); this.redraw(); return;
      }
      if (a === "drop") { await busy(b, () => this.drop()); return; }
      if (a === "reset1") {
        if (!this.sel) { toast(Z("先点一下要复原的零件", "คลิกเลือกชิ้นก่อน"), true); return; }
        this.push(); this._pose(this.sel, this.sel.userData.center, [0, 0, 0]); this.dirty = true; this._status(); this.redraw(); return;
      }
      if (a === "resetall") {
        this.push();
        this.meshes.forEach((m) => this._pose(m, m.userData.center, [0, 0, 0])); this.ai = false; this.auto = null; this.dirty = true; this._status(); this._fit(); return;
      }
      if (a === "autosel") { await busy(b, () => this.autoSelect()); return; }
      if (a === "auto") { await busy(b, () => this.autoAssemble()); return; }
      if (a === "save") { await busy(b, () => this.save()); return; }
      if (a === "ai") { await busy(b, () => this.aiAssemble()); return; }
      if (a === "default") {
        if (!confirm(Z("这个规格的展示回到默认（自己选的零件和姿势会清掉）？", "กลับเป็นค่าเริ่มต้น (ชิ้นที่เลือกและท่าจะถูกล้าง)?"))) return;
        await busy(b, () => api(`/api/products/${enc(this.pid)}/display?spec=${enc(this.spec)}`, { method: "DELETE" }));
        this.dirty = false;
        if (this.opts.onSaved) await this.opts.onSaved();
        await open(this.box, this.pid, this.opts);
        return;
      }
    } catch (err) { toast(err.message || String(err), true); }
  }
  _change(e) {
    const t = e.target;
    if (t.dataset.asmSnap !== undefined) { this._snap(t.checked); return; }
    if (t.dataset.asmCol !== undefined) { this.colour = t.value; this._recolour(); return; }
    const lab = t.closest("[data-pk]");
    if (lab) { this._pickChange(lab).catch((err) => toast(err.message || String(err), true)); return; }
    const tr = t.closest("tr[data-k]"); if (!tr) return;
    const m = this.meshes.find((x) => x.userData.key === tr.dataset.k); if (!m) return;
    if (t.dataset.asmPc !== undefined) { this.push(); m.userData.colour = t.value; this._recolour(); this.dirty = true; this._status(); return; }
    if (t.dataset.asmHide !== undefined) { this.push(); m.userData.hidden = t.checked; m.visible = !t.checked; if (t.checked && this.sel === m) this.select(null); this.dirty = true; this._status(); this.redraw(); }
  }
  _recolour(colour) {
    this.meshes.forEach((m) => m.material.color.set(hexOf(m.userData.colour || (colour !== undefined ? colour : this.colour))));
    this.redraw();
  }
  pose() {
    return this.meshes.map((m) => {
      const base = this.exploded && this.exploded[m.userData.key];
      const p = base ? base : [m.position.x, m.position.y, m.position.z];
      return { key: m.userData.key, pos: p.map((v) => Math.round(v * 100) / 100),
        rot: [m.rotation.x, m.rotation.y, m.rotation.z].map((v) => Math.round(v * R2D * 10) / 10), colour: m.userData.colour || "", hidden: !!m.userData.hidden };
    });
  }
  body(extra) { return { spec: this.spec, items: this.items, parts: this.pose(), ...(extra || {}) }; }
  async save() {
    if (this.exploded) this.unexplode();
    this.d = await api(`/api/products/${enc(this.pid)}/display`, { json: this.body({ ai: this.ai, auto: this.auto }) });
    this.items = JSON.parse(JSON.stringify(this.d.items));
    this.dirty = false; this._status();
    toast(Z("组装已保存：3D 预览和商品图按组装好的样子显示", "บันทึกการประกอบแล้ว: การแสดงผลและรูปสินค้าจะใช้แบบประกอบ"));
    if (this.opts.onSaved) await this.opts.onSaved();
  }
  async autoSelect() {
    const r = await api(`/api/products/${enc(this.pid)}/display/auto-select`, { json: { spec: this.spec } });
    if (!(r.items || []).length) { toast(Z("没找到合适的零件", "ไม่พบชิ้นที่เหมาะสม"), true); return; }
    this.push();
    this.items = r.items; this.dirty = true; this.auto = null;
    this.renderPick();
    await this._build([]);
    this._fit();
    this._banner("asm-info", `🔍 <b>${Z("自动选零件", "เลือกชิ้นอัตโนมัติ")}</b>：<span data-notr>${esc((TH() ? r.note_th : r.note_zh) || "")}</span> · ${Z("接着可以点「自动组合」", "ต่อไปกด「ประกอบอัตโนมัติ」ได้")}`);
  }
  async autoAssemble() {
    const r = await apiJob(`/api/products/${enc(this.pid)}/display/auto-assemble`, { json: this.body() });
    this.push();
    this._apply(r.parts);
    this.auto = { conf: r.confidence }; this.ai = false; this.dirty = true;
    const pct = Math.round(r.confidence * 100);
    this._banner(r.low ? "asm-ai" : "asm-ok", `${r.low ? "⚠" : "✓"} <b>${Z("自动组合", "ประกอบอัตโนมัติ")} · ${Z("置信度", "ความมั่นใจ")} ${pct}%</b> <span data-notr>${esc((TH() ? r.note_th : r.note_zh) || "")}</span>
      ${r.low ? ` <button class="mini primary-lite" data-asm="ai">🤖 ${Z("用 AI 按图片组装", "ใช้ AI ประกอบตามรูป")}</button>` : ""}`);
    this._status(); this._fit();
    if (r.low && confirm(Z(`自动组合置信度低（${pct}%）。要再用「AI 按图片组装」吗？（AI 的结果会再按形状落下贴合）`, `ความมั่นใจต่ำ (${pct}%) ใช้ AI ประกอบตามรูปต่อไหม?`))) {
      try { await this.aiAssemble(true); } catch (err) { toast(err.message || String(err), true); }
    }
  }
  async drop() {
    const r = await api(`/api/products/${enc(this.pid)}/display/settle`, { json: this.body() });
    this.push(); this._apply(r.parts); this.dirty = true; this._status(); this.redraw();
  }
  async toggleExplode(btn) {
    if (this.exploded) { this.unexplode(); return; }
    const r = await api(`/api/products/${enc(this.pid)}/display/explode`, { json: { ...this.body(), factor: 1 } });
    this.select(null);
    this.exploded = {};
    this.meshes.forEach((m) => {
      this.exploded[m.userData.key] = [m.position.x, m.position.y, m.position.z];
      const o = (r.offsets || {})[m.userData.key]; if (o) m.position.set(m.position.x + o[0], m.position.y + o[1], m.position.z + o[2]);
    });
    btn.classList.add("on"); this._fit();
  }
  unexplode() {
    if (!this.exploded) return;
    this.meshes.forEach((m) => { const p = this.exploded[m.userData.key]; if (p) m.position.set(p[0], p[1], p[2]); });
    this.exploded = null;
    const b = this.box.querySelector("[data-asm=explode]"); if (b) b.classList.remove("on");
    this._fit();
  }
  // 每个零件按原始朝向画 3 张（正面 / 侧面 / 俯视），给 AI 看
  _renders() {
    const size = 256, rr = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    rr.setSize(size, size); rr.outputColorSpace = THREE.SRGBColorSpace;
    const cam = new THREE.PerspectiveCamera(30, 1, 0.5, 20000); cam.up.set(0, 0, 1);
    const saved = this.meshes.map((m) => [m.visible, m.position.clone(), m.rotation.clone()]);
    const helper = this.tc.getHelper ? this.tc.getHelper() : this.tc; const hv = helper.visible, gv = this.grid.visible;
    helper.visible = false; this.grid.visible = false;
    const out = {};
    try {
      this.meshes.forEach((m, i) => {
        if (m.userData.hidden) return;
        this.meshes.forEach((x) => (x.visible = x === m));
        m.position.set(0, 0, 0); m.rotation.set(0, 0, 0);
        const r = Math.max(...m.userData.size) * 0.9 || 30, dist = r / Math.sin(15 * D2R);
        out[i] = [[0, -1, 0.15], [1, 0, 0.15], [0.01, -0.01, 1]].map(([x, y, z]) => {
          const v = new THREE.Vector3(x, y, z).normalize().multiplyScalar(dist); cam.position.copy(v); cam.lookAt(0, 0, 0);
          rr.render(this.scene, cam); return rr.domElement.toDataURL("image/jpeg", 0.85);
        });
      });
    } finally {
      this.meshes.forEach((m, i) => { m.visible = saved[i][0]; m.position.copy(saved[i][1]); m.rotation.copy(saved[i][2]); });
      helper.visible = hv; this.grid.visible = gv; rr.dispose(); this.redraw();
    }
    return out;
  }
  async aiAssemble(fromAuto) {
    if (!fromAuto && this.dirty && !confirm(Z("AI 会重新摆所有零件（可以撤销）。继续？", "AI จะจัดทุกชิ้นใหม่ (ย้อนได้) ดำเนินการต่อ?"))) return;
    const renders = this._renders();
    const r = await apiJob(`/api/products/${enc(this.pid)}/display/ai`, { json: { renders, spec: this.spec, items: this.items } });
    this.push();
    this._apply(r.parts);
    this.ai = true; this.dirty = true;
    const note = esc((TH() ? r.note_th : r.note_zh) || r.note_zh || "") + (r.has_photo ? "" : Z("（这个产品还没有商品图，AI 按常识组装）", " (ยังไม่มีรูปสินค้า AI ประกอบตามความเข้าใจทั่วไป)"));
    this._banner("asm-ai", `⚠ <b>${Z("AI 结果仅供参考，请手动调整", "ผลจาก AI ใช้อ้างอิงเท่านั้น กรุณาปรับเอง")}</b> <span data-notr>${note}</span>${r.snapped ? ` · ${Z("已按形状落下贴合", "ปรับให้แนบตามรูปทรงแล้ว")}` : ""}`);
    this._status(); this._fit();
  }
  _hide(fn) {
    const helper = this.tc.getHelper ? this.tc.getHelper() : this.tc; const hv = helper.visible, gv = this.grid.visible;
    helper.visible = false; this.grid.visible = false;
    try { return fn(); } finally { helper.visible = hv; this.grid.visible = gv; }
  }
  async shots() {
    if (typeof P === "undefined" || !P || P.id !== this.pid || !window.postRenders) { toast(Z("在编辑产品页里才能出图", "สร้างรูปได้ในหน้าแก้ไขสินค้า"), true); return; }
    if (this.dirty && !this.readOnly) await this.save();
    const list = this.colours.length ? this.colours.filter((c) => !(window.isRandomColor && isRandomColor(c))) : [""];
    const W = 1200, rr = this.renderer, shots = [];
    try {
      this._hide(() => {
        rr.setSize(W, W, false); this.camera.aspect = 1; this.camera.updateProjectionMatrix();
        for (const c of list) { this._recolour(c); rr.render(this.scene, this.camera); shots.push({ data: rr.domElement.toDataURL("image/jpeg", 0.92), kind: "main", color: c }); }
      });
    } finally { this._recolour(); this._resize(); }
    const n = await postRenders(shots, { replace_renders: false });
    toast(Z(`已添加 ${n} 张（按组装好的样子、现在的角度）`, `เพิ่มแล้ว ${n} รูป`));
  }
  // 零件说明图：爆炸图 + 每个零件的编号（买家看得懂有哪些零件）
  async partsImage() {
    if (typeof P === "undefined" || !P || P.id !== this.pid || !window.postRenders) { toast(Z("在编辑产品页里才能出图", "สร้างรูปได้ในหน้าแก้ไขสินค้า"), true); return; }
    const was = !!this.exploded;
    if (!was) await this.toggleExplode(this.box.querySelector("[data-asm=explode]"));
    const W = 1200, rr = this.renderer;
    let data = "";
    try {
      this._hide(() => {
        rr.setSize(W, W, false); this.camera.aspect = 1; this.camera.updateProjectionMatrix();
        rr.render(this.scene, this.camera);
        const cv = document.createElement("canvas"); cv.width = W; cv.height = W;
        const g = cv.getContext("2d"); g.drawImage(rr.domElement, 0, 0, W, W);
        g.font = "bold 34px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
        this.meshes.forEach((m, i) => {
          if (!m.visible) return;
          const bb = new THREE.Box3().setFromObject(m), c = bb.getCenter(new THREE.Vector3()).project(this.camera);
          const x = (c.x + 1) / 2 * W, y = (1 - c.y) / 2 * W;
          g.fillStyle = "rgba(21,101,192,.92)"; g.beginPath(); g.arc(x, y, 26, 0, Math.PI * 2); g.fill();
          g.fillStyle = "#fff"; g.fillText(String(i + 1), x, y + 1);
        });
        data = cv.toDataURL("image/jpeg", 0.92);
      });
    } finally { this._resize(); if (!was) this.unexplode(); }
    const n = await postRenders([{ data, kind: "parts", color: "" }], { replace_renders: false });
    toast(Z(`已添加零件说明图（${n} 张）`, `เพิ่มรูปอธิบายชิ้นส่วนแล้ว (${n} รูป)`));
  }
  dispose() {
    this.alive = false;
    window.removeEventListener("keydown", this.onKey);
    document.removeEventListener("pointerdown", this.onDocDown, true);
    try { this.ro.disconnect(); } catch { /* 忽略 */ }
    try { this.tc.dispose(); this.orbit.dispose(); } catch { /* 忽略 */ }
    this.meshes.forEach((m) => m.material.dispose());
    Object.values(this.geos).forEach((g) => g.g.dispose());
    try { this.renderer.dispose(); } catch { /* 忽略 */ }
  }
}

async function open(box, pid, opts) {
  if (A) A.dispose();
  box.classList.remove("hidden");
  box.innerHTML = `<p class="muted small">${Z("读取零件…", "กำลังโหลดชิ้นงาน…")}</p>`;
  A = new Assembly(box, pid, opts);
  try { await A.open(); } catch (e) { box.innerHTML = `<p class="bad small">${esc(e.message || String(e))}</p>`; throw e; }
  return A;
}
function close() {
  if (!A) return;
  if (A.dirty && !confirm(Z("组装有改动还没保存，收起会丢掉。继续？", "การประกอบยังไม่ได้บันทึก ปิดแล้วจะหาย ดำเนินการต่อ?"))) return;
  const box = A.box, cb = A.opts.onClose; A.dispose(); A = null; box.innerHTML = ""; box.classList.add("hidden");
  if (cb) cb();
}
window.ASM = { open, close, get current() { return A; } };
