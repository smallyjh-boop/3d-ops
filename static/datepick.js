// 日期选择（v2.42）：浏览器自带的日期框按电脑的语言显示（中文 Windows 上泰文界面也是「年/月/日」），
// 这里把页面上所有 <input type="date"> / <input type="datetime-local"> 换成文字框 + 自己的小日历，跟着系统界面语言走。
// 值的格式和原来一样（2026-10-31 / 2026-10-31T14:30），各模块读写 .value 的代码不用改；选完照样触发 input / change。
(function () {
  const TH = () => (typeof LANG !== "undefined" ? LANG : "zh") === "th";
  const MONTHS = {
    th: ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."],
    zh: ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
  };
  const DAYS = { th: ["อา", "จ", "อ", "พ", "พฤ", "ศ", "ส"], zh: ["日", "一", "二", "三", "四", "五", "六"] };
  const TXT = { th: { today: "วันนี้", clear: "ล้าง", ph: "ปปปป-ดด-วว", time: "เวลา" }, zh: { today: "今天", clear: "清空", ph: "年-月-日", time: "时间" } };
  const L = () => (TH() ? "th" : "zh");
  const P = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const DATE_RE = /^(\d{4})-(\d{1,2})-(\d{1,2})$/;

  function norm(s, withTime) {
    // 手打的也认：2026/10/31、2026-10-31 14:30
    s = String(s || "").trim().replace(/\//g, "-");
    if (!s) return "";
    const [d, t] = s.split(/[T\s]+/);
    const m = DATE_RE.exec(d || "");
    if (!m) return null;
    const out = `${m[1]}-${pad(m[2])}-${pad(m[3])}`;
    if (!withTime) return out;
    const tm = /^(\d{1,2}):(\d{2})/.exec(t || "00:00");
    return tm ? `${out}T${pad(tm[1])}:${tm[2]}` : null;
  }

  function upgrade(el) {
    if (el.dataset.dp) return;
    const withTime = el.type === "datetime-local";
    const cur = el.value;
    el.dataset.dp = withTime ? "dt" : "d";
    el.type = "text";
    el.autocomplete = "off";
    el.inputMode = "numeric";
    if (!el.placeholder) el.placeholder = TXT[L()].ph + (withTime ? " 00:00" : "");
    el.style.minWidth = withTime ? "150px" : "110px";
    if (withTime) {
      // 显示「2026-10-31 14:30」，读出来还是「2026-10-31T14:30」
      Object.defineProperty(el, "value", {
        configurable: true,
        get() { const v = norm(P.get.call(this), true); return v || ""; },
        set(v) { P.set.call(this, String(v || "").replace("T", " ").slice(0, 16)); },
      });
    }
    el.value = cur;
    el.addEventListener("focus", () => open(el));
    el.addEventListener("click", () => open(el));
    el.addEventListener("blur", () => {
      const v = norm(P.get.call(el), withTime);
      if (v === null) { el.classList.add("dp-bad"); return; }
      el.classList.remove("dp-bad");
      const show = withTime ? v.replace("T", " ") : v;
      if (P.get.call(el) !== show) { P.set.call(el, show); el.dispatchEvent(new Event("change", { bubbles: true })); }
    });
  }

  let box = null, target = null, view = null;
  function close() { if (box) box.remove(); box = target = null; }

  function pick(dateStr) {
    if (!target) return;
    const el = target;
    let v = dateStr;
    if (el.dataset.dp === "dt") {
      const t = box.querySelector(".dp-time");
      v = dateStr ? `${dateStr}T${(t && t.value) || "00:00"}` : "";
    }
    el.value = v;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    close();
  }

  function render() {
    const l = L(), y = view.getFullYear(), m = view.getMonth();
    const sel = norm(P.get.call(target), target.dataset.dp === "dt") || "";
    const selD = sel.slice(0, 10), today = iso(new Date());
    const first = new Date(y, m, 1).getDay(), n = new Date(y, m + 1, 0).getDate();
    let cells = "";
    for (let i = 0; i < first; i++) cells += "<span></span>";
    for (let d = 1; d <= n; d++) {
      const s = `${y}-${pad(m + 1)}-${pad(d)}`;
      cells += `<button type="button" data-d="${s}" class="${s === selD ? "on" : ""}${s === today ? " td" : ""}">${d}</button>`;
    }
    const yr = l === "th" ? `${y} (พ.ศ. ${y + 543})` : `${y}`;
    const time = target.dataset.dp === "dt"
      ? `<label class="dp-tl">${TXT[l].time} <input class="dp-time" type="text" inputmode="numeric" value="${sel.slice(11, 16) || "00:00"}" maxlength="5"></label>` : "";
    box.innerHTML = `<div class="dp-hd"><button type="button" data-nav="-12">«</button><button type="button" data-nav="-1">‹</button>
      <b>${MONTHS[l][m]} ${yr}</b><button type="button" data-nav="1">›</button><button type="button" data-nav="12">»</button></div>
      <div class="dp-wk">${DAYS[l].map((x) => `<span>${x}</span>`).join("")}</div><div class="dp-days">${cells}</div>
      <div class="dp-ft">${time}<span><button type="button" data-today>${TXT[l].today}</button> <button type="button" data-clear>${TXT[l].clear}</button></span></div>`;
  }

  function open(el) {
    if (target === el && box) return;
    close();
    target = el;
    const sel = norm(P.get.call(el), el.dataset.dp === "dt");
    const m = sel && DATE_RE.exec(sel.slice(0, 10));
    view = m ? new Date(+m[1], +m[2] - 1, 1) : new Date();
    box = document.createElement("div");
    box.className = "dp-box";
    box.setAttribute("data-notr", "");
    document.body.appendChild(box);
    render();
    const r = el.getBoundingClientRect();
    const top = r.bottom + 4 + box.offsetHeight > innerHeight ? r.top - box.offsetHeight - 4 : r.bottom + 4;
    box.style.top = `${Math.max(4, top)}px`;
    box.style.left = `${Math.max(4, Math.min(r.left, innerWidth - box.offsetWidth - 8))}px`;
    box.addEventListener("mousedown", (e) => { if (!e.target.closest(".dp-time")) e.preventDefault(); });   // 不让文字框失去焦点
    box.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.nav) { view = new Date(view.getFullYear(), view.getMonth() + +b.dataset.nav, 1); return render(); }
      if (b.dataset.d) return pick(b.dataset.d);
      if (b.hasAttribute("data-today")) return pick(iso(new Date()));
      if (b.hasAttribute("data-clear")) return pick("");
    });
  }

  document.addEventListener("mousedown", (e) => { if (box && !box.contains(e.target) && e.target !== target) close(); }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" || e.key === "Tab") close(); }, true);
  window.addEventListener("scroll", (e) => { if (box && !box.contains(e.target)) close(); }, true);
  window.addEventListener("resize", close);

  const scan = (root) => root.querySelectorAll && root.querySelectorAll('input[type="date"],input[type="datetime-local"]').forEach(upgrade);
  scan(document);
  new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => {
    if (n.nodeType !== 1) return;
    if (n.matches && n.matches('input[type="date"],input[type="datetime-local"]')) upgrade(n);
    scan(n);
  }))).observe(document.documentElement, { childList: true, subtree: true });
  window.DATEPICK = { upgrade, scan };
})();
