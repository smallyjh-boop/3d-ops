"use strict";
// 财务模块和框架的连接：打开菜单 → FIN 加载数据
(function () {
  window.MODS = window.MODS || {};
  window.MODS.fin = { show(tab) { if (window.FIN) return FIN.show(tab); } };
})();
