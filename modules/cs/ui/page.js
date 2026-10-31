"use strict";
// AI 客服模块和框架的连接：打开菜单 → CS / CSREC 加载数据；设置 → 客服 / 账号与权限 里的卡片。
(function () {
  window.MODS = window.MODS || {};
  window.MODS.cs = {
    show(tab) {
      if (window.CS) CS.show(tab);
      if (window.CSDASH) CSDASH.show(tab);
      if (window.CSREC) CSREC.show(tab);
    },
    settings(box, cat) {
      if (cat === "cs") {
        if (!box.querySelector("#cskb-settings")) {
          box.innerHTML = `<div class="card"><div class="row between"><h3>客服设置（店铺政策、自动回复、提醒、邮件）</h3><div class="lockbar" id="cskb-setbar"></div></div><div id="cskb-settings" class="form1"></div></div>`;
        }
        if (window.CS) CS.show("cskb");
      }
      if (cat === "accounts") {
        if (!box.querySelector("#cs-agents")) box.innerHTML = '<div class="card" id="cs-agents"></div>';
        if (window.CSREC) CSREC.show("csext");
      }
    },
  };
})();
