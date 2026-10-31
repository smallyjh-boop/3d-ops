"use strict";
// v2.49：财务模块开着时，订单模块的「每单利润」菜单并进「财务 → 订单利润」（菜单藏起来，点旧链接 / 书签会跳过去）。
// 关掉财务模块时这个文件不加载，「每单利润」照旧。
(function () {
  const b = document.querySelector('#subnav .tab[data-tab="profit"]');
  if (b) b.classList.add("ghost");
  if (typeof CUR_TAB !== "undefined" && CUR_TAB === "profit" && typeof showTab === "function") showTab("profit");
})();
