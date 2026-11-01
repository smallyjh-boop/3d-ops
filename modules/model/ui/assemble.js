// v2.52 展示模型：组装视图（ES 模块，点「🧩 打开组装视图」时才加载）。
// 多零件模型：每个零件可以用鼠标拖动 / 旋转（three.js TransformControls），拼成商品照片里组装好的样子；
// 「AI 按图片组装」：浏览器把每个零件画几个角度，连同商品主图交给 ERP 的 AI，AI 给每个零件的位置 / 旋转当初稿，员工再调。
// 保存后编辑页的 3D 预览和商品图都按组装好的样子显示（服务器 modules/model/assembly.py）。坐标：Z 朝上，毫米。
import * as THREE from "three";
import { OrbitControls } from "/static/vendor/three/OrbitControls.js";
import { TransformControls } from "/static/vendor/three/TransformControls.js";

const TH = () => window.I18N && I18N.lang === "th";
const Z = (zh, th) => (TH() ? th : zh);
const D2R = Math.PI / 180, R2D = 180 / Math.PI;
const hexOf = (name) => { try { return (window.colorInfo ? colorInfo(name || "") : { hex: "#cfcfcf" }).hex || "#cfcfcf"; } catch { return "#cfcfcf"; } };

let A = null;     // 当前打开的组装视图

const css = `
.asm-head{display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:space-between;margin-bottom:6px}
.asm-tools{display:flex;flex-wrap:wrap;gap:4px;align-items:center}
.asm-tools label{display:inline-flex;align-items:center;gap:3px;white-space:nowrap}
.asm-side label{white-space:nowrap}
.asm-tools .on{background:#1565c0;color:#fff;border-color:#1565c0}
.asm-main{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:10px}
@media (max-width:1100px){.asm-main{grid-template-columns:1fr}}
.asm-3d{height:440px;border-radius:8px;overflow:hidden;background:#fff;border:1px solid #eee;position:relative}
.asm-side{font-size:13px;max-height:440px;overflow:auto}
.asm-side table{width:100%;border-collapse:collapse}.asm-side td{padding:3px 4px;border-bottom:1px solid #f0f0f0;vertical-align:middle}
.asm-side tr.on{background:#eaf3ff}
.asm-side select{max-width:110px}
.asm-ai{background:#fff3cd;border:1px solid #f0c36d;color:#7a5200;border-radius:8px;padding:6px 10px;margin:6px 0;font-size:13px}
.asm-hint{position:absolute;left:8px;bottom:6px;font-size:12px;color:#667;background:rgba(255,255,255,.85);border-radius:6px;padding:2px 6px;pointer-events:none}
`;
if (!document.getElementById("asm-css")) { const st = document.createElement("style"); st.id = "asm-css"; st.textContent = css; document.head.appendChild(st); }

async function fetchPart(pid, i) {
  const r = await fetch(`/api/products/${encodeURIComponent(pid)}/display/part/${i}`, { credentials: "same-origin" });
  if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || r.statusText); }
  return new Float32Array(await r.arrayBuffer());
}

class Assembly {
  constructor(box, pid, opts) {
    this.box = box; this.pid = pid; this.opts = opts || {}; this.meshes = []; this.sel = null; this.ai = false; this.dirty = false; this.alive = true;
  }
  async open() {
    this.d = await api(`/api/products/${encodeURIComponent(this.pid)}/display`);
    const cols = (typeof P !== "undefined" && P ? [...new Set((P.variants || []).map((v) => (v.opt1_zh || "").trim()).filter(Boolean))] : []);
    this.colours = cols; this.colour = cols[0] || "";
    this.box.innerHTML = `
      <div class="asm-head"><b>🧩 ${Z("组装视图（展示用）", "มุมมองประกอบ (สำหรับแสดงผล)")} · <span data-notr>${esc(this.d.source_name)}</span>
          <span class="muted small">${this.d.parts.length} ${Z("个零件", "ชิ้น")}</span></b>
        <span class="asm-tools">
          <button class="mini on" data-asm="translate" title="${Z("拖动箭头挪位置（快捷键 W）", "ลากลูกศรเพื่อย้าย (W)")}">✥ ${Z("移动", "ย้าย")}</button>
          <button class="mini" data-asm="rotate" title="${Z("拖动圆环旋转（快捷键 E）", "ลากวงแหวนเพื่อหมุน (E)")}">⟳ ${Z("旋转", "หมุน")}</button>
          <label class="small"><input type="checkbox" data-asm-snap checked> ${Z("吸附（1 mm / 15°）", "แม่เหล็ก (1 mm / 15°)")}</label>
          <button class="mini" data-asm="floor" title="${Z("选中的零件放到地面（最低点 z = 0）", "วางชิ้นที่เลือกลงพื้น")}">⤓ ${Z("放到地面", "วางลงพื้น")}</button>
          <button class="mini" data-asm="reset1">${Z("这个零件复原", "คืนค่าชิ้นนี้")}</button>
          <button class="mini" data-asm="resetall">${Z("全部复原", "คืนค่าทั้งหมด")}</button>
          <button class="mini primary-lite" data-asm="ai" title="${Z("把商品主图和每个零件几个角度的图交给 AI，让它给出每个零件的位置和角度（初稿）", "ส่งรูปสินค้าหลักและรูปแต่ละชิ้นให้ AI เสนอตำแหน่งและมุม (ร่างแรก)")}">🤖 ${Z("AI 按图片组装", "AI ประกอบตามรูป")}</button>
          <button class="mini" data-asm="shots" title="${Z("按组装好的样子、各零件的颜色，每个款式出一张商品图", "สร้างรูปสินค้าแบบประกอบแล้ว แบบละ 1 รูป")}">📷 ${Z("按组装出商品图", "สร้างรูปสินค้าแบบประกอบ")}</button>
          <button class="mini primary" data-asm="save">💾 ${Z("保存组装", "บันทึกการประกอบ")}</button>
          <button class="mini" data-asm="close">${Z("收起", "ปิด")}</button></span></div>
      <div class="asm-ai hidden" data-asm-ai>⚠ <b>${Z("AI 结果仅供参考，请手动调整", "ผลจาก AI ใช้อ้างอิงเท่านั้น กรุณาปรับเอง")}</b> <span data-asm-ainote data-notr></span></div>
      <div class="asm-main"><div class="asm-3d"><div class="asm-hint">${Z("点零件选中 · 拖箭头 / 圆环 · 右键平移 · 滚轮缩放", "คลิกเลือกชิ้น · ลากลูกศร / วงแหวน · คลิกขวาเลื่อน · ล้อเมาส์ซูม")}</div></div>
        <div class="asm-side">
          ${this.colours.length ? `<div class="small">${Z("看哪个款式", "ดูแบบสีไหน")}：<select data-asm-col>${this.colours.map((c) => `<option value="${esc(c)}" data-notr>${esc((TH() && window.colorInfo && colorInfo(c).th) || c)}</option>`).join("")}</select></div>` : ""}
          <table><tbody>${this.d.parts.map((p) => `<tr data-i="${p.index}"><td><b>${p.index + 1}</b></td>
            <td><span data-notr title="${esc(p.name)}">${esc(String(p.name).slice(0, 18))}</span><div class="muted" data-notr>${p.size.map((v) => Math.round(v)).join("×")} mm</div></td>
            <td><select data-asm-pc title="${Z("零件颜色（展示用）", "สีของชิ้น (แสดงผล)")}"><option value="">${Z("款式色", "สีของแบบ")}</option>${Object.keys(window.COLORS || {}).map((c) => `<option value="${esc(c)}" ${c === p.colour ? "selected" : ""} data-notr>${esc((TH() && (window.COLORS[c] || {}).th) || c)}</option>`).join("")}</select></td>
            <td><label title="${Z("不显示（例如螺丝、备用件）", "ไม่แสดง")}"><input type="checkbox" data-asm-hide ${p.hidden ? "checked" : ""}>${Z("隐藏", "ซ่อน")}</label></td></tr>`).join("")}</tbody></table>
          <p class="small muted">${Z("组装只影响 3D 预览和商品图；打印时零件按「打印方案」平放在热床上。", "การประกอบมีผลแค่การแสดงผลและรูปสินค้า ตอนพิมพ์ชิ้นงานวางตาม「แผนการพิมพ์」")}</p>
          <div class="small" data-asm-st></div>
        </div></div>`;
    this.el3d = this.box.querySelector(".asm-3d");
    this._scene();
    await this._load();
    this._wire();
    this._fit();
  }
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
    this.orbit = new OrbitControls(cam, r.domElement);
    this.orbit.addEventListener("change", () => this.redraw());
    const tc = this.tc = new TransformControls(cam, r.domElement);
    tc.setSize(0.9);
    tc.addEventListener("dragging-changed", (e) => { this.orbit.enabled = !e.value; if (!e.value) { this.dirty = true; this._status(); } });
    tc.addEventListener("change", () => this.redraw());
    s.add(tc.getHelper ? tc.getHelper() : tc);
    this._snap(true);
    this.ro = new ResizeObserver(() => this._resize()); this.ro.observe(this.el3d);
    this._resize();
  }
  _resize() {
    const w = this.el3d.clientWidth || 600, h = this.el3d.clientHeight || 440;
    this.renderer.setSize(w, h); this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); this.redraw();
  }
  redraw() {
    if (this._pend || !this.alive) return;
    this._pend = true;
    requestAnimationFrame(() => { this._pend = false; if (this.alive) this.renderer.render(this.scene, this.camera); });
  }
  _snap(on) {
    this.tc.setTranslationSnap(on ? 1 : null); this.tc.setRotationSnap(on ? 15 * D2R : null);
  }
  async _load() {
    const st = this.box.querySelector("[data-asm-st]");
    for (const p of this.d.parts) {
      st.textContent = Z(`读取零件 ${p.index + 1} / ${this.d.parts.length}…`, `กำลังโหลดชิ้นที่ ${p.index + 1} / ${this.d.parts.length}…`);
      const arr = await fetchPart(this.pid, p.index);
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(arr, 3));
      g.translate(-p.center[0], -p.center[1], -p.center[2]);     // 零件的外框中心 = 原点（pos 是外框中心的位置）
      g.computeVertexNormals();
      const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: hexOf(p.colour || this.colour), roughness: 0.55, metalness: 0.02 }));
      m.userData = { index: p.index, center: p.center, colour: p.colour || "", hidden: !!p.hidden };
      this._pose(m, p.pos, p.rot);
      m.visible = !p.hidden;
      this.scene.add(m); this.meshes.push(m);
    }
    this._status();
  }
  _pose(m, pos, rot) {
    m.position.set(+pos[0] || 0, +pos[1] || 0, +pos[2] || 0);
    m.rotation.set((+rot[0] || 0) * D2R, (+rot[1] || 0) * D2R, (+rot[2] || 0) * D2R, "XYZ");
  }
  _status() {
    const st = this.box.querySelector("[data-asm-st]");
    if (!st) return;
    st.innerHTML = this.dirty ? `<b class="warn">${Z("有改动，还没保存", "มีการแก้ไข ยังไม่ได้บันทึก")}</b>`
      : this.d.has_pose ? `<span class="ok">${Z("已保存组装", "บันทึกการประกอบแล้ว")}${this.d.ai ? Z("（AI 初稿 + 人工调整）", " (ร่าง AI + ปรับเอง)") : ""}</span>` : `<span class="muted">${Z("还没保存过：现在是文件里原来的位置", "ยังไม่เคยบันทึก: ตอนนี้เป็นตำแหน่งเดิมในไฟล์")}</span>`;
    this.box.querySelectorAll("tr[data-i]").forEach((tr) => tr.classList.toggle("on", this.sel && +tr.dataset.i === this.sel.userData.index));
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
    this.sel = m || null;
    if (m) this.tc.attach(m); else this.tc.detach();
    this._status(); this.redraw();
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
    this.onKey = (e) => {
      if (!this.alive || !this.box.contains(document.activeElement) && document.activeElement !== document.body) return;
      if (e.target.closest && e.target.closest("input,select,textarea")) return;
      if (e.key === "w" || e.key === "W") this._mode("translate");
      else if (e.key === "e" || e.key === "E") this._mode("rotate");
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
  _part(i) { return this.d.parts.find((p) => p.index === i); }
  async _click(e) {
    const tr = e.target.closest("tr[data-i]");
    if (tr && !e.target.closest("select,input,label")) { const m = this.meshes.find((x) => x.userData.index === +tr.dataset.i); if (m && m.visible) this.select(m); return; }
    const b = e.target.closest("[data-asm]"); if (!b) return;
    const a = b.dataset.asm;
    try {
      if (a === "translate" || a === "rotate") { this._mode(a); return; }
      if (a === "close") { close(); return; }
      if (a === "floor") {
        if (!this.sel) { toast(Z("先点一下要放的零件", "คลิกเลือกชิ้นก่อน"), true); return; }
        const bb = new THREE.Box3().setFromObject(this.sel); this.sel.position.z -= bb.min.z; this.dirty = true; this._status(); this.redraw(); return;
      }
      if (a === "reset1") {
        if (!this.sel) { toast(Z("先点一下要复原的零件", "คลิกเลือกชิ้นก่อน"), true); return; }
        this._pose(this.sel, this.sel.userData.center, [0, 0, 0]); this.dirty = true; this._status(); this.redraw(); return;
      }
      if (a === "resetall") {
        if (!confirm(Z("所有零件回到文件里原来的位置？", "ให้ทุกชิ้นกลับไปตำแหน่งเดิมในไฟล์?"))) return;
        this.meshes.forEach((m) => this._pose(m, m.userData.center, [0, 0, 0])); this.ai = false; this.dirty = true; this._status(); this._fit(); return;
      }
      if (a === "save") { await busy(b, () => this.save()); return; }
      if (a === "ai") { await busy(b, () => this.aiAssemble()); return; }
      if (a === "shots") { await busy(b, () => this.shots()); return; }
    } catch (err) { toast(err.message || String(err), true); }
  }
  _change(e) {
    const t = e.target;
    if (t.dataset.asmSnap !== undefined) { this._snap(t.checked); return; }
    if (t.dataset.asmCol !== undefined) { this.colour = t.value; this._recolour(); return; }
    const tr = t.closest("tr[data-i]"); if (!tr) return;
    const m = this.meshes.find((x) => x.userData.index === +tr.dataset.i); if (!m) return;
    if (t.dataset.asmPc !== undefined) { m.userData.colour = t.value; this._recolour(); this.dirty = true; this._status(); return; }
    if (t.dataset.asmHide !== undefined) { m.userData.hidden = t.checked; m.visible = !t.checked; if (t.checked && this.sel === m) this.select(null); this.dirty = true; this._status(); this.redraw(); }
  }
  _recolour(colour) {
    this.meshes.forEach((m) => m.material.color.set(hexOf(m.userData.colour || (colour !== undefined ? colour : this.colour))));
    this.redraw();
  }
  pose() {
    return this.meshes.map((m) => ({ index: m.userData.index, pos: [m.position.x, m.position.y, m.position.z].map((v) => Math.round(v * 100) / 100),
      rot: [m.rotation.x, m.rotation.y, m.rotation.z].map((v) => Math.round(v * R2D * 10) / 10), colour: m.userData.colour || "", hidden: !!m.userData.hidden }));
  }
  async save() {
    this.d = await api(`/api/products/${encodeURIComponent(this.pid)}/display`, { json: { source: this.d.source, parts: this.pose(), ai: this.ai } });
    this.dirty = false; this._status();
    toast(Z("组装已保存：3D 预览和商品图按组装好的样子显示", "บันทึกการประกอบแล้ว: การแสดงผลและรูปสินค้าจะใช้แบบประกอบ"));
    if (this.opts.onSaved) await this.opts.onSaved();
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
      for (const m of this.meshes) {
        if (m.userData.hidden) continue;
        this.meshes.forEach((x) => (x.visible = x === m));
        m.position.set(0, 0, 0); m.rotation.set(0, 0, 0);
        const p = this._part(m.userData.index), r = Math.max(...p.size) * 0.9 || 30, dist = r / Math.sin(15 * D2R);
        out[m.userData.index] = [[0, -1, 0.15], [1, 0, 0.15], [0.01, -0.01, 1]].map(([x, y, z]) => {
          const v = new THREE.Vector3(x, y, z).normalize().multiplyScalar(dist); cam.position.copy(v); cam.lookAt(0, 0, 0);
          rr.render(this.scene, cam); return rr.domElement.toDataURL("image/jpeg", 0.85);
        });
      }
    } finally {
      this.meshes.forEach((m, i) => { m.visible = saved[i][0]; m.position.copy(saved[i][1]); m.rotation.copy(saved[i][2]); });
      helper.visible = hv; this.grid.visible = gv; rr.dispose(); this.redraw();
    }
    return out;
  }
  async aiAssemble() {
    if (this.dirty && !confirm(Z("AI 会重新摆所有零件（现在的改动会被替换，没保存前可以「全部复原」）。继续？", "AI จะจัดทุกชิ้นใหม่ ดำเนินการต่อ?"))) return;
    const renders = this._renders();
    const r = await apiJob(`/api/products/${encodeURIComponent(this.pid)}/display/ai`, { json: { renders } });
    for (const x of r.parts || []) { const m = this.meshes.find((y) => y.userData.index === x.index); if (m) this._pose(m, x.pos, x.rot); }
    this.ai = true; this.dirty = true;
    const box = this.box.querySelector("[data-asm-ai]"); box.classList.remove("hidden");
    box.querySelector("[data-asm-ainote]").textContent = (TH() ? r.note_th : r.note_zh) || r.note_zh || "";
    if (!r.has_photo) box.querySelector("[data-asm-ainote]").textContent += Z("（这个产品还没有商品图，AI 按常识组装）", " (ยังไม่มีรูปสินค้า AI ประกอบตามความเข้าใจทั่วไป)");
    this._status(); this._fit();
  }
  async shots() {
    if (typeof P === "undefined" || !P || P.id !== this.pid || !window.postRenders) { toast(Z("在编辑产品页里才能出图", "สร้างรูปได้ในหน้าแก้ไขสินค้า"), true); return; }
    if (this.dirty) await this.save();
    const list = this.colours.length ? this.colours.filter((c) => !(window.isRandomColor && isRandomColor(c))) : [""];
    const helper = this.tc.getHelper ? this.tc.getHelper() : this.tc; const hv = helper.visible, gv = this.grid.visible;
    helper.visible = false; this.grid.visible = false;
    const W = 1200, rr = this.renderer, old = [rr.domElement.width, rr.domElement.height, this.camera.aspect];
    const shots = [];
    try {
      rr.setSize(W, W, false); this.camera.aspect = 1; this.camera.updateProjectionMatrix();
      for (const c of list) {
        this._recolour(c);
        rr.render(this.scene, this.camera);
        shots.push({ data: rr.domElement.toDataURL("image/jpeg", 0.92), kind: "main", color: c });
      }
    } finally {
      helper.visible = hv; this.grid.visible = gv; this._recolour(); this._resize();
      void old;
    }
    const n = await postRenders(shots, { replace_renders: false });
    toast(Z(`已添加 ${n} 张（按组装好的样子、现在的角度）`, `เพิ่มแล้ว ${n} รูป`));
  }
  dispose() {
    this.alive = false;
    window.removeEventListener("keydown", this.onKey);
    try { this.ro.disconnect(); } catch { /* 忽略 */ }
    try { this.tc.dispose(); this.orbit.dispose(); } catch { /* 忽略 */ }
    this.meshes.forEach((m) => { m.geometry.dispose(); m.material.dispose(); });
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
  const box = A.box; A.dispose(); A = null; box.innerHTML = ""; box.classList.add("hidden");
}
window.ASM = { open, close, get current() { return A; } };
