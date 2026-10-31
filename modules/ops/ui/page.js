"use strict";
// 运营分析模块和框架的连接：打开菜单 → hub.js 画页面头、筛选条、页签，再让 ops.js / market.js / plan.js 加载数据
(function () {
  window.MODS = window.MODS || {};
  window.MODS.ops = { show(tab) { if (window.OPSHUB) return OPSHUB.show(tab); } };
})();
