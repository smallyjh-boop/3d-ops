"use strict";
// 采购模块和框架的连接：四个菜单共用一个页面，PURCHASE.show 按菜单切换视图
(function () {
  window.MODS = window.MODS || {};
  window.MODS.pur = { show(tab) { if (window.PURCHASE) return PURCHASE.show(tab); } };
})();
