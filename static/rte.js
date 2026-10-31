"use strict";
// v2.46 富文本编辑器（商品详情）：把一个 <textarea>（里面是 HTML）换成「工具栏 + 可编辑区」，改动实时写回 textarea
// 并触发 input 事件，原来读写 textarea 的代码（保存、预览、AI 生成后填回）都不用改。
// 用法：RTE.attach(textarea, {images: () => [{src, title}], max: 25000})；程序改了 textarea.value 以后调 RTE.sync(textarea)（或 RTE.syncAll()）。
(function () {
  const ED = new Map();
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const FONTS = [["", "默认字体", "ฟอนต์เริ่มต้น"], ["Tahoma", "Tahoma"], ["Arial", "Arial"], ["Sarabun, sans-serif", "Sarabun"], ["Georgia, serif", "Georgia"], ["Courier New, monospace", "Courier New"]];
  const SIZES = [["1", "10px"], ["2", "13px"], ["3", "16px"], ["4", "18px"], ["5", "24px"], ["6", "32px"]];
  const FORMATS = [["p", "正文", "ข้อความ"], ["h2", "标题 1", "หัวข้อ 1"], ["h3", "标题 2", "หัวข้อ 2"], ["h4", "标题 3", "หัวข้อ 3"], ["blockquote", "引用", "อ้างอิง"], ["pre", "代码", "โค้ด"]];
  const STYLES = [["hl", "重点框", "กล่องเน้น"], ["note", "灰底说明", "หมายเหตุพื้นเทา"], ["center", "居中大标题", "หัวข้อกลางใหญ่"], ["warn", "红字提醒", "ข้อความเตือนสีแดง"]];
  const COLORS = ["#000000", "#444444", "#888888", "#ffffff", "#e11d48", "#f97316", "#eab308", "#16a34a", "#0ea5e9", "#2563eb", "#7c3aed", "#db2777", "#fee2e2", "#ffedd5", "#fef9c3", "#dcfce7", "#e0f2fe", "#ede9fe"];
  // 按钮：[命令, 图标, 提示中文, 提示泰文]
  const ROW1 = [
    ["source", "‹/›", "源码", "ซอร์สโค้ด"], "|",
    ["undo", "↶", "撤销", "เลิกทำ"], ["redo", "↷", "重做", "ทำซ้ำ"], "|",
    ["removeFormat", "T̸", "清除格式", "ล้างรูปแบบ"], ["bold", "<b>B</b>", "加粗", "ตัวหนา"], ["italic", "<i>I</i>", "斜体", "ตัวเอียง"],
    ["underline", "<u>U</u>", "下划线", "ขีดเส้นใต้"], ["strikeThrough", "<s>S</s>", "删除线", "ขีดฆ่า"], "|",
    ["insertOrderedList", "1≡", "编号列表", "รายการตัวเลข"], ["insertUnorderedList", "•≡", "项目列表", "รายการจุด"], "|",
    ["outdent", "⇤", "减少缩进", "ลดการเยื้อง"], ["indent", "⇥", "增加缩进", "เพิ่มการเยื้อง"], "|",
    ["justifyLeft", "⯇≡", "左对齐", "ชิดซ้าย"], ["justifyCenter", "≡", "居中", "กึ่งกลาง"], ["justifyRight", "≡⯈", "右对齐", "ชิดขวา"], ["justifyFull", "☰", "两端对齐", "เต็มบรรทัด"], "|",
    ["link", "🔗", "插入链接", "ใส่ลิงก์"], ["unlink", "⛓̸", "去掉链接", "ลบลิงก์"], "|",
    ["image", "🖼", "插入图片", "ใส่รูป"], ["table", "▦", "插入表格", "ใส่ตาราง"], ["insertHorizontalRule", "―", "分隔线", "เส้นคั่น"],
  ];

  function css() {
    if (document.getElementById("rte-css")) return;
    const s = document.createElement("style");
    s.id = "rte-css";
    s.textContent = `.rte{border:1px solid #cbd5e1;border-radius:6px;background:#fff;display:flex;flex-direction:column}
.rte.full{position:fixed;inset:8px;z-index:9999;box-shadow:0 10px 40px #0005}
.rte-bar{display:flex;flex-wrap:wrap;gap:2px;align-items:center;padding:4px 6px;background:#f8fafc;border-bottom:1px solid #e2e8f0;border-radius:6px 6px 0 0}
.rte-bar button,.rte-bar select{font-size:13px;min-width:28px;height:28px;padding:0 6px;border:1px solid transparent;background:transparent;border-radius:4px;cursor:pointer;color:#1f2937}
.rte-bar button:hover,.rte-bar select:hover{border-color:#cbd5e1;background:#fff}
.rte-bar button.on{background:#dbeafe;border-color:#93c5fd}
.rte-bar .sep{width:1px;height:20px;background:#e2e8f0;margin:0 3px}
.rte-bar select{min-width:70px;width:auto!important;max-width:120px;display:inline-block!important;margin:0!important;border-color:#e2e8f0}
.rte-bar button{width:auto!important;margin:0!important}
.rte-area{min-height:220px;max-height:560px;overflow:auto;padding:10px 12px;outline:none;line-height:1.6;font-size:14px}
.rte.full .rte-area{max-height:none;flex:1}
.rte-area img{max-width:100%;height:auto}.rte-area img.sel{outline:2px solid #2563eb}
.rte-area table{border-collapse:collapse;width:100%}.rte-area td,.rte-area th{border:1px solid #cbd5e1;padding:4px 6px;min-width:30px}
.rte-area blockquote{border-left:3px solid #cbd5e1;margin:6px 0;padding:2px 10px;color:#475569}
.rte-src{min-height:220px;font-family:monospace;font-size:12px;border:0;padding:10px;resize:vertical;outline:none}
.rte.full .rte-src{flex:1}
.rte-foot{display:flex;justify-content:space-between;padding:2px 8px;font-size:12px;color:#64748b;border-top:1px solid #e2e8f0;background:#f8fafc;border-radius:0 0 6px 6px}
.rte-foot .over{color:#dc2626;font-weight:700}
.rte-pop{position:absolute;z-index:10000;background:#fff;border:1px solid #cbd5e1;border-radius:6px;box-shadow:0 6px 20px #0003;padding:8px}
.rte-pop .sw{display:inline-block;width:20px;height:20px;border:1px solid #cbd5e1;margin:1px;cursor:pointer;border-radius:3px}
.rte-pop .grid{display:grid;grid-template-columns:repeat(8,18px);gap:2px}.rte-pop .grid span{width:18px;height:18px;border:1px solid #cbd5e1}
.rte-pop .grid span.on{background:#bfdbfe}
.rte-imgs{display:flex;flex-wrap:wrap;gap:6px;max-width:420px;max-height:260px;overflow:auto}.rte-imgs img{width:72px;height:72px;object-fit:cover;border:2px solid transparent;border-radius:4px;cursor:pointer}
.rte-imgs img:hover{border-color:#2563eb}`;
    document.head.appendChild(s);
  }

  const STYLE_HTML = {
    hl: (t) => `<div style="border:2px solid #f97316;border-radius:8px;padding:8px 12px;background:#fff7ed"><p>${t}</p></div>`,
    note: (t) => `<div style="background:#f1f5f9;padding:8px 12px;border-radius:6px;color:#475569"><p>${t}</p></div>`,
    center: (t) => `<h2 style="text-align:center">${t}</h2>`,
    warn: (t) => `<p style="color:#dc2626;font-weight:bold">${t}</p>`,
  };

  function clean(html) {
    // 去掉编辑时的辅助标记；空段落合并
    return String(html || "").replace(/\sclass="sel"/g, "").replace(/(<p><br><\/p>)+$/g, "").trim();
  }
  function textLen(html) { return String(html || "").length; }

  function attach(ta, opts) {
    if (!ta || ED.has(ta)) return ED.get(ta);
    css();
    opts = opts || {};
    const max = opts.max || 25000;
    const box = document.createElement("div");
    box.className = "rte";
    const bar = document.createElement("div");
    bar.className = "rte-bar";
    const sel = (cls, items, first) => `<select class="${cls}" title="${first}"><option value="">${first}</option>${items.map((x) => `<option value="${x[0]}">${Z(x[1], x[2] || x[1])}</option>`).join("")}</select>`;
    bar.innerHTML = ROW1.map((b) => (b === "|" ? '<span class="sep"></span>' : `<button type="button" data-c="${b[0]}" title="${Z(b[2], b[3])}">${b[1]}</button>`)).join("")
      + '<span style="flex-basis:100%;height:0"></span>'
      + sel("rte-style", STYLES, Z("样式", "สไตล์")) + sel("rte-format", FORMATS, Z("格式", "รูปแบบ"))
      + sel("rte-font", FONTS.slice(1), Z("字体", "ฟอนต์")) + sel("rte-size", SIZES.map(([v, l]) => [v, l]), Z("大小", "ขนาด"))
      + `<span class="sep"></span><button type="button" data-c="foreColor" title="${Z("文字颜色", "สีตัวอักษร")}"><span style="border-bottom:3px solid #e11d48">A</span>▾</button>`
      + `<button type="button" data-c="hiliteColor" title="${Z("背景颜色", "สีพื้นหลัง")}"><span style="background:#fde047;padding:0 3px">A</span>▾</button>`
      + `<span class="sep"></span><button type="button" data-c="full" title="${Z("全屏", "เต็มจอ")}">⛶</button>`;
    const area = document.createElement("div");
    area.className = "rte-area";
    area.contentEditable = "true";
    area.setAttribute("data-notr", "");
    const src = document.createElement("textarea");
    src.className = "rte-src";
    src.style.display = "none";
    src.setAttribute("data-notr", "");
    const foot = document.createElement("div");
    foot.className = "rte-foot";
    foot.innerHTML = `<span class="rte-hint">${Z("可以直接粘贴网页 / Word 的内容；点图片可以改大小", "วางเนื้อหาจากเว็บ / Word ได้ คลิกรูปเพื่อปรับขนาด")}</span><span class="rte-cnt"></span>`;
    box.append(bar, area, src, foot);
    ta.style.display = "none";
    (ta.closest("label") || ta).after(box);        // 放在 label 外面：点编辑区不会被 label 转给隐藏的 textarea
    const st = { ta, box, area, src, foot, source: false, range: null, max };
    ED.set(ta, st);

    const count = () => {
      const n = textLen(ta.value);
      const c = foot.querySelector(".rte-cnt");
      c.textContent = `${n}/${max}`;
      c.classList.toggle("over", n > max);
    };
    const push = () => {
      const html = st.source ? src.value : clean(area.innerHTML);
      if (html === ta.value) return count();
      ta.value = html;
      ta.dispatchEvent(new Event("input", { bubbles: true }));
      count();
    };
    st.push = push; st.count = count;
    const saveRange = () => {
      const s = window.getSelection();
      if (s.rangeCount && area.contains(s.getRangeAt(0).commonAncestorContainer)) st.range = s.getRangeAt(0).cloneRange();
    };
    const restore = () => {
      area.focus();
      if (st.range) { const s = window.getSelection(); s.removeAllRanges(); s.addRange(st.range); }
    };
    const exec = (cmd, val) => {
      restore();
      try { document.execCommand("styleWithCSS", false, cmd === "foreColor" || cmd === "hiliteColor" || cmd === "fontName"); } catch { /* */ }
      document.execCommand(cmd, false, val);
      saveRange(); push(); state();
    };
    const insert = (html) => { restore(); document.execCommand("insertHTML", false, html); saveRange(); push(); };
    st.insert = insert;
    const state = () => {
      bar.querySelectorAll("button[data-c]").forEach((b) => {
        const c = b.dataset.c;
        if (["bold", "italic", "underline", "strikeThrough", "insertOrderedList", "insertUnorderedList", "justifyLeft", "justifyCenter", "justifyRight", "justifyFull"].includes(c)) {
          let on = false; try { on = document.queryCommandState(c); } catch { /* */ }
          b.classList.toggle("on", on && !st.source);
        }
      });
      bar.querySelector('[data-c="source"]').classList.toggle("on", st.source);
      bar.querySelector('[data-c="full"]').classList.toggle("on", box.classList.contains("full"));
    };

    area.addEventListener("input", () => { saveRange(); push(); });
    area.addEventListener("keyup", () => { saveRange(); state(); });
    area.addEventListener("mouseup", () => { saveRange(); state(); });
    area.addEventListener("blur", saveRange);
    src.addEventListener("input", push);
    area.addEventListener("paste", (e) => {
      // 粘贴：保留常见格式，去掉 Word / 网页带来的 class、脚本、样式表
      const h = e.clipboardData && e.clipboardData.getData("text/html");
      if (!h) return;
      e.preventDefault();
      const d = document.createElement("div");
      d.innerHTML = h;
      d.querySelectorAll("script,style,meta,link,title,xml,o\\:p").forEach((x) => x.remove());
      d.querySelectorAll("*").forEach((x) => { x.removeAttribute("class"); x.removeAttribute("id"); [...x.attributes].forEach((a) => { if (/^on/i.test(a.name)) x.removeAttribute(a.name); }); });
      document.execCommand("insertHTML", false, d.innerHTML);
      push();
    });
    // 点图片：选中，弹出改大小
    area.addEventListener("click", (e) => {
      area.querySelectorAll("img.sel").forEach((x) => x.classList.remove("sel"));
      if (e.target.tagName === "IMG") { e.target.classList.add("sel"); imgPop(st, e.target); }
    });

    bar.addEventListener("mousedown", (e) => { if (e.target.closest("button")) e.preventDefault(); });
    bar.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-c]"); if (!b) return;
      const c = b.dataset.c;
      if (c === "source") {
        st.source = !st.source;
        if (st.source) { src.value = ta.value; src.style.display = ""; area.style.display = "none"; }
        else { area.innerHTML = src.value; src.style.display = "none"; area.style.display = ""; push(); }
        return state();
      }
      if (st.source) return;
      if (c === "full") { box.classList.toggle("full"); return state(); }
      if (c === "link") {
        saveRange();
        const u = prompt(Z("链接地址（https://…）", "ที่อยู่ลิงก์ (https://…)"), "https://");
        if (u && u !== "https://") exec("createLink", u);
        return;
      }
      if (c === "image") return imgPick(st, b, opts);
      if (c === "table") return tablePick(st, b);
      if (c === "foreColor" || c === "hiliteColor") return colorPick(st, b, c, exec);
      exec(c);
    });
    bar.addEventListener("change", (e) => {
      const s = e.target; const v = s.value; s.value = "";
      if (!v || st.source) return;
      if (s.classList.contains("rte-format")) exec("formatBlock", v);
      if (s.classList.contains("rte-font")) exec("fontName", v);
      if (s.classList.contains("rte-size")) exec("fontSize", v);
      if (s.classList.contains("rte-style")) {
        restore();
        const t = window.getSelection().toString() || Z("在这里输入文字", "พิมพ์ข้อความที่นี่");
        insert(STYLE_HTML[v](t.replace(/[<>&]/g, (m) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[m]))));
      }
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && box.classList.contains("full")) { box.classList.remove("full"); state(); } });
    sync(ta);
    return st;
  }

  function pop(anchor, html) {
    closePop();
    const p = document.createElement("div");
    p.className = "rte-pop";
    p.innerHTML = html;
    document.body.appendChild(p);
    const r = anchor.getBoundingClientRect();
    p.style.left = Math.min(window.scrollX + r.left, window.scrollX + window.innerWidth - p.offsetWidth - 10) + "px";
    p.style.top = window.scrollY + r.bottom + 4 + "px";
    setTimeout(() => document.addEventListener("mousedown", outside), 0);
    return p;
  }
  function outside(e) { const p = document.querySelector(".rte-pop"); if (p && !p.contains(e.target)) closePop(); }
  function closePop() { document.querySelectorAll(".rte-pop").forEach((x) => x.remove()); document.removeEventListener("mousedown", outside); }

  function colorPick(st, b, cmd, exec) {
    const p = pop(b, COLORS.map((c) => `<span class="sw" data-v="${c}" style="background:${c}"></span>`).join("") +
      `<div style="margin-top:4px"><input type="color" value="#e11d48"> <button type="button" class="mini" data-none>${Z("无", "ไม่มี")}</button></div>`);
    p.addEventListener("mousedown", (e) => e.preventDefault());
    p.addEventListener("click", (e) => {
      const v = e.target.dataset.v;
      if (v) { exec(cmd, v); closePop(); }
      if (e.target.dataset.none !== undefined) { exec(cmd, cmd === "hiliteColor" ? "transparent" : "#000000"); closePop(); }
    });
    p.querySelector("input").addEventListener("change", (e) => { exec(cmd, e.target.value); closePop(); });
  }
  function tablePick(st, b) {
    const p = pop(b, `<div class="small rte-tsize">${Z("选择行列", "เลือกแถว×คอลัมน์")}</div><div class="grid">${Array.from({ length: 64 }, (_, i) => `<span data-r="${Math.floor(i / 8) + 1}" data-c="${i % 8 + 1}"></span>`).join("")}</div>`);
    p.addEventListener("mousedown", (e) => e.preventDefault());
    p.addEventListener("mouseover", (e) => {
      const r = +e.target.dataset.r, c = +e.target.dataset.c; if (!r) return;
      p.querySelectorAll(".grid span").forEach((x) => x.classList.toggle("on", +x.dataset.r <= r && +x.dataset.c <= c));
      p.querySelector(".rte-tsize").textContent = `${r} × ${c}`;
    });
    p.addEventListener("click", (e) => {
      const r = +e.target.dataset.r, c = +e.target.dataset.c; if (!r) return;
      closePop();
      st.insert(`<table style="border-collapse:collapse;width:100%"><tbody>${Array.from({ length: r }, () => `<tr>${Array.from({ length: c }, () => '<td style="border:1px solid #ccc;padding:4px">&nbsp;</td>').join("")}</tr>`).join("")}</tbody></table><p><br></p>`);
    });
  }
  function imgPick(st, b, opts) {
    const imgs = (opts.images && opts.images()) || [];
    const p = pop(b, `<div class="small">${Z("点产品图片插入", "คลิกรูปสินค้าเพื่อใส่")}</div>
      <div class="rte-imgs">${imgs.map((x) => `<img src="${x.src}" title="${x.title || ""}" data-src="${x.src}">`).join("") || `<span class="small">${Z("产品还没有图片", "ยังไม่มีรูป")}</span>`}</div>
      <div style="margin-top:6px;display:flex;gap:4px"><input class="rte-url" placeholder="${Z("或者填图片网址 https://…", "หรือใส่ URL รูป")}" style="flex:1"><button type="button" class="mini" data-url>${Z("插入", "ใส่")}</button></div>`);
    p.addEventListener("mousedown", (e) => { if (e.target.tagName !== "INPUT") e.preventDefault(); });
    p.addEventListener("click", (e) => {
      let u = e.target.dataset.src;
      if (e.target.dataset.url !== undefined) u = p.querySelector(".rte-url").value.trim();
      if (!u) return;
      closePop();
      st.insert(`<p><img src="${u.replace(/"/g, "&quot;")}" style="max-width:100%"></p>`);
    });
  }
  function imgPop(st, img) {
    const p = pop(img, `<div class="small">${Z("图片宽度", "ความกว้างรูป")}</div>
      ${["25%", "50%", "75%", "100%"].map((w) => `<button type="button" class="mini" data-w="${w}">${w}</button>`).join(" ")}
      <button type="button" class="mini" data-al="center">${Z("居中", "กลาง")}</button> <button type="button" class="mini danger" data-del>${Z("删除图片", "ลบรูป")}</button>`);
    p.addEventListener("mousedown", (e) => e.preventDefault());
    p.addEventListener("click", (e) => {
      const w = e.target.dataset.w;
      if (w) { img.style.width = w; img.style.maxWidth = "100%"; img.removeAttribute("width"); img.removeAttribute("height"); }
      if (e.target.dataset.al) { img.style.display = "block"; img.style.margin = "0 auto"; }
      if (e.target.dataset.del !== undefined) img.remove();
      closePop(); st.push();
    });
  }

  function sync(ta) {
    const st = ED.get(ta); if (!st) return;
    if (st.source) st.src.value = ta.value;
    else if (clean(st.area.innerHTML) !== ta.value) st.area.innerHTML = ta.value || "";
    st.count();
  }
  function syncAll() { ED.forEach((_, ta) => sync(ta)); }

  window.RTE = { attach, sync, syncAll };
})();
