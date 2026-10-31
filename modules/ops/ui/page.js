"use strict";
// 运营分析模块和框架的连接：打开菜单 → OPSA 加载数据（ops.js）
(function () {
  window.MODS = window.MODS || {};
  window.MODS.ops = { show(tab) { if (window.OPSA) return OPSA.show(tab); } };
})();
