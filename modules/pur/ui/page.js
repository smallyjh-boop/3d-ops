"use strict";
// 采购模块和框架的连接：一个页面（purchase）；旧菜单 po_suggest / po_recv / po_suppliers / po_pay 在 PURCHASE.show 里跳到对应的页签
(function () {
  window.MODS = window.MODS || {};
  window.MODS.pur = { show(tab) { if (window.PURCHASE) return PURCHASE.show(tab); } };
})();
